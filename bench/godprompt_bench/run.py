from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import stat
import subprocess
import uuid
from collections import Counter
from datetime import datetime, timezone
from importlib.metadata import version
from math import isfinite
from pathlib import Path
from typing import Any, Mapping

from .agent import condition_prompt
from .corpus import _reject_duplicate_json_keys, load_manifest, validate_manifest
from .eval import build_task
from .export import export_run
from .models import RunProfile, SampleRecord


def load_profile(path: Path) -> RunProfile:
    raw = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_reject_duplicate_json_keys)
    if not isinstance(raw, dict):
        raise ValueError("profile root must be an object")
    required = {"name", "task_ids", "epochs", "max_messages", "max_time_seconds", "max_output_tokens"}
    missing = required - raw.keys()
    if missing:
        raise ValueError(f"profile missing fields: {sorted(missing)}")
    unknown = raw.keys() - required
    if unknown:
        raise ValueError(f"unknown profile fields: {sorted(unknown)}")
    if not isinstance(raw["name"], str) or not raw["name"].strip():
        raise ValueError("profile name must be a non-empty string")
    task_ids = raw["task_ids"]
    if not isinstance(task_ids, list) or not task_ids or not all(isinstance(v, str) and v.strip() for v in task_ids):
        raise ValueError("profile task_ids must be non-empty strings in a non-empty list")
    seen_ids: set[str] = set()
    for task_id in task_ids:
        if task_id in seen_ids:
            raise ValueError(f"duplicate task id in profile: {task_id}")
        seen_ids.add(task_id)
    limit_fields = ("epochs", "max_messages", "max_time_seconds", "max_output_tokens")
    if any(type(raw[field]) is not int or raw[field] <= 0 for field in limit_fields):
        raise ValueError("profile numeric limits must be positive integers")
    profile = RunProfile(
        name=raw["name"],
        task_ids=tuple(task_ids),
        epochs=raw["epochs"],
        max_messages=raw["max_messages"],
        max_time_seconds=raw["max_time_seconds"],
        max_output_tokens=raw["max_output_tokens"],
    )
    return profile


def load_custom_profile(path: Path, bench_root: Path) -> RunProfile:
    """Allow smaller local plans without impersonating frozen reference profiles."""
    if path.suffix.lower() != ".json" or path.is_symlink() or not path.is_file():
        raise ValueError("custom profile must be an existing regular JSON file")
    if path.stat().st_size > 65536:
        raise ValueError("custom profile JSON exceeds 64 KiB")
    profile = load_profile(path)
    if not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", profile.name):
        raise ValueError("custom profile name must be a short lowercase identifier")
    if profile.name in ("smoke", "half", "full") or profile.name.startswith("half-frozen"):
        raise ValueError("custom profile cannot reuse a bundled reference name")
    full = load_profile(bench_root / "configs" / "full.json")
    limits = ("epochs", "max_messages", "max_time_seconds", "max_output_tokens")
    if any(getattr(profile, key) > getattr(full, key) for key in limits):
        raise ValueError("custom profile limits cannot exceed the bundled full profile")
    known_ids = {task.id for task in load_manifest(bench_root / "tasks" / "manifest.json")}
    if not set(profile.task_ids).issubset(known_ids):
        raise ValueError("custom profile task IDs must belong to the bundled corpus")
    return RunProfile(
        name=f"custom-{profile.name}",
        task_ids=profile.task_ids,
        epochs=profile.epochs,
        max_messages=profile.max_messages,
        max_time_seconds=profile.max_time_seconds,
        max_output_tokens=profile.max_output_tokens,
    )


def validate_sample_coverage(
    profile: RunProfile, records: list[SampleRecord], task_categories: Mapping[str, str]
) -> None:
    """Reject incomplete or misattributed Inspect results before publishing rates."""
    missing_categories = sorted(set(profile.task_ids) - task_categories.keys())
    if missing_categories:
        raise ValueError(f"missing canonical benchmark categories: {missing_categories}")
    expected = Counter(
        (condition, task_id, epoch)
        for condition in ("baseline", "godprompt")
        for task_id in profile.task_ids
        for epoch in range(1, profile.epochs + 1)
    )
    actual = Counter((record.condition, record.task_id, record.epoch) for record in records)
    duplicates = sorted(key for key, count in actual.items() if count > 1)
    missing = sorted(expected.keys() - actual.keys())
    unexpected = sorted(actual.keys() - expected.keys())
    wrong_categories = sorted(
        (record.condition, record.task_id, record.epoch, task_categories[record.task_id], record.category)
        for record in records
        if record.task_id in task_categories and record.category != task_categories[record.task_id]
    )
    if duplicates or missing or unexpected or wrong_categories:
        raise ValueError(
            f"invalid benchmark sample coverage: duplicate={duplicates[:5]}; "
            f"missing={missing[:5]}; unexpected={unexpected[:5]}; category={wrong_categories[:5]}"
        )


def _token_count(value: Any, field: str) -> int:
    if value is None:
        return 0
    if type(value) is int:
        count = value
    elif type(value) is float and isfinite(value) and value.is_integer():
        count = int(value)
    else:
        raise ValueError(f"invalid model usage token count: {field}")
    if count < 0:
        raise ValueError(f"invalid model usage token count: {field}")
    return count


def _usage_totals(model_usage: Mapping[str, Any] | None) -> tuple[int | None, int | None]:
    if not model_usage:
        return None, None
    input_tokens = 0
    output_tokens = 0
    input_observed = True
    output_observed = True
    fields = ("input_tokens", "input_tokens_cache_read", "input_tokens_cache_write", "output_tokens")
    for usage in model_usage.values():
        counts = {
            field: usage.get(field) if isinstance(usage, Mapping) else getattr(usage, field, None)
            for field in fields
        }
        input_observed &= any(counts[field] is not None for field in fields[:3])
        output_observed &= counts["output_tokens"] is not None
        input_tokens += sum(_token_count(counts[field], field) for field in fields[:3])
        output_tokens += _token_count(counts["output_tokens"], "output_tokens")
    return input_tokens if input_observed else None, output_tokens if output_observed else None


def _score_count(value: Any, field: str) -> int:
    if value is None:
        return 0
    if type(value) is int:
        count = value
    elif type(value) is float and isfinite(value) and value.is_integer():
        count = int(value)
    else:
        raise ValueError(f"invalid benchmark counter: {field}")
    if count < 0:
        raise ValueError(f"invalid benchmark counter: {field}")
    return count


def _score_flag(value: Any, field: str) -> bool:
    # Inspect's binary scorer values may arrive as bool, int or integral float.
    # Generic bool(...) coercion turns "false", -1 and NaN into false successes.
    if value is None:
        return False
    if type(value) is bool:
        return value
    if type(value) is int and value in (0, 1):
        return bool(value)
    if type(value) is float and isfinite(value) and value in (0.0, 1.0):
        return bool(value)
    raise ValueError(f"invalid benchmark score flag: {field}")


def _sample_latency_seconds(value: Any) -> float | None:
    if value is None:
        return None
    if type(value) not in (int, float) or value < 0:
        raise ValueError("invalid sample latency: expected finite nonnegative seconds")
    try:
        seconds = float(value)
    except OverflowError as exc:
        raise ValueError("invalid sample latency: expected finite nonnegative seconds") from exc
    if not isfinite(seconds):
        raise ValueError("invalid sample latency: expected finite nonnegative seconds")
    return seconds


def _sample_epoch(value: Any) -> int:
    # int(...) silently truncates fractional epochs and accepts bool/string IDs.
    if type(value) is not int or value <= 0:
        raise ValueError("invalid sample epoch: expected positive integer")
    return value


def _sample_task_id(value: Any) -> str:
    # Benchmark manifest IDs are strings. Coercing an Inspect log ID (such as
    # integer 123) could silently attribute it to the manifest task "123".
    if type(value) is not str or not value.strip():
        raise ValueError("invalid sample task id: expected non-empty string")
    return value


def sample_record(sample: Any, condition: str) -> SampleRecord:
    score = (getattr(sample, "scores", None) or {}).get("godprompt_bench")
    limit = getattr(sample, "limit", None)
    error = getattr(sample, "error", None)
    values: Mapping[str, Any] = {}
    score_metadata: Mapping[str, Any] = {}
    if score is not None:
        if not isinstance(score.value, Mapping):
            raise ValueError("invalid benchmark score value: expected mapping")
        values = score.value
        score_metadata = score.metadata or {}

    if score is not None:
        completion_status = str(score_metadata.get("completion_status", "protocol-invalid"))
        infrastructure_error = None
    elif limit is not None:
        limit_type = str(getattr(limit, "type", ""))
        completion_status = "timeout" if limit_type in {"time", "working"} else "error"
        infrastructure_error = None
    else:
        completion_status = "error"
        infrastructure_error = (
            str(getattr(error, "message", error)) if error is not None else "sample completed without benchmark score"
        )

    input_tokens, output_tokens = _usage_totals(getattr(sample, "model_usage", None))
    metadata = getattr(sample, "metadata", {}) or {}
    return SampleRecord(
        task_id=_sample_task_id(sample.id),
        category=str(metadata.get("category", "unknown")),
        condition=condition,
        epoch=_sample_epoch(sample.epoch),
        passed=_score_flag(values.get("passed"), "passed"),
        completion_status=completion_status,
        false_completion=_score_flag(values.get("false_completion"), "false_completion"),
        scope_violation=_score_flag(values.get("scope_violation"), "scope_violation"),
        tool_misuse_count=_score_count(values.get("tool_misuse_count"), "tool_misuse_count"),
        verification_attempts=_score_count(values.get("verification_attempts"), "verification_attempts"),
        failed_tool_calls=_score_count(values.get("failed_tool_calls"), "failed_tool_calls"),
        retries=_score_count(values.get("retries"), "retries"),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        latency_seconds=_sample_latency_seconds(getattr(sample, "total_time", None)),
        infrastructure_error=infrastructure_error,
    )


def _dump(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", exclude_none=True)
    if isinstance(value, Mapping):
        return dict(value)
    return value


_PRIVATE_REASONING_FIELDS = {
    "analysis", "analysiscontent", "analysisdelta", "analysisdetails", "analysistext",
    "chainofthought",
    "reasoning", "reasoningcontent", "reasoningdelta", "reasoningdetails", "redactedreasoning",
    "reasoningtext", "thinking", "thinkingcontent", "thinkingdetails",
    "thinkingdelta", "thinkingtext", "redactedthinking",
    "encryptedcontent",
}


def _private_reasoning_field(value: Any) -> bool:
    return isinstance(value, str) and re.sub(r"[\s_.-]+", "", value.casefold()) in _PRIVATE_REASONING_FIELDS


def _private_channel(value: Any) -> bool:
    # Preserve the object's original channel, even if model_dump labels it final.
    channel = getattr(value, "value", value)
    # Serialized enum-like channels can use either a value or a name.
    candidates = (channel.get("value"), channel.get("name")) if isinstance(channel, Mapping) else (channel,)
    return any(
        isinstance(candidate, str) and (
            candidate.strip().casefold() == "private" or _private_reasoning_field(candidate)
        )
        for candidate in candidates
    )


def _private_reasoning_block(value: Any) -> bool:
    if not isinstance(value, Mapping):
        return False
    channel = value.get("channel")
    return _private_channel(value.get("type")) or _private_channel(channel)


def _strip_reasoning(value: Any) -> Any:
    # JSON writes tuples as arrays too, so sanitize their elements like lists.
    if isinstance(value, (list, tuple)):
        result = []
        for item in value:
            if _private_reasoning_block(item):
                continue
            result.append(_strip_reasoning(item))
        return result
    if isinstance(value, Mapping):
        return {
            key: _strip_reasoning(item) for key, item in value.items()
            if not _private_reasoning_field(key) and not _private_reasoning_block(item)
        }
    return value


def _is_public_message_role(role: Any) -> bool:
    value = getattr(role, "value", role)
    return isinstance(value, str) and value in {"user", "assistant", "tool"}


def public_trajectory(sample: Any, condition: str) -> dict[str, Any]:
    messages: list[dict[str, Any]] = []
    for message in getattr(sample, "messages", []) or []:
        dumped = _dump(message)
        if not isinstance(dumped, dict):
            continue
        roles = [role for role in (dumped.get("role"), getattr(message, "role", None)) if role is not None]
        channels = (dumped.get("channel"), getattr(message, "channel", None))
        if (not roles or not all(_is_public_message_role(role) for role in roles)
                or _private_reasoning_block(dumped)
                or any(_private_channel(channel) for channel in channels)):
            continue
        messages.append(_strip_reasoning(dumped))

    events: list[dict[str, Any]] = []
    for event in getattr(sample, "events", []) or []:
        dumped = _dump(event)
        if not isinstance(dumped, dict):
            continue
        # A serialized public label must not override an original private event kind.
        original_kind = getattr(event, "event", None)
        original_kind = getattr(original_kind, "value", original_kind)
        if (dumped.get("event", getattr(event, "event", None)) not in ("tool", "approval")
                or (original_kind is not None and original_kind not in ("tool", "approval"))
                or _private_reasoning_block(dumped)
                or _private_channel(getattr(event, "channel", None))):
            continue
        events.append(_strip_reasoning(dumped))

    return {
        "task_id": _sample_task_id(sample.id),
        "epoch": _sample_epoch(sample.epoch),
        "condition": condition,
        "messages": messages,
        "events": events,
    }


def _git(repo_root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=repo_root, text=True, capture_output=True, check=True
    )
    return result.stdout.strip()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _create_raw_log_directory(raw_log_dir: Path) -> None:
    # Inspect writes unsanitized evaluation logs before the public exporter runs.
    # A linked parent must not redirect those private logs to another location.
    for candidate in (raw_log_dir, *raw_log_dir.parents):
        try:
            entry = candidate.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(entry.st_mode) or (
            getattr(entry, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        ):
            raise ValueError(f"refusing linked raw log directory: {candidate}")
    raw_log_dir.mkdir(parents=True, exist_ok=True)


def fixture_fingerprints(bench_root: Path, task_ids: tuple[str, ...]) -> dict[str, Any]:
    """Fingerprint selected fixture files, including their hidden verifier content."""
    manifest = json.loads(
        (bench_root / "tasks" / "manifest.json").read_text(encoding="utf-8"),
        object_pairs_hook=_reject_duplicate_json_keys,
    )
    fixture_dirs = {item["id"]: item["fixture_dir"] for item in manifest}
    hashes: dict[str, str] = {}
    for task_id in sorted(task_ids):
        if task_id not in fixture_dirs:
            raise ValueError(f"missing fixture manifest entry for task {task_id}")
        fixture_path = (bench_root / fixture_dirs[task_id] / "fixture.json").resolve()
        if not fixture_path.is_relative_to(bench_root.resolve()) or not fixture_path.is_file():
            raise ValueError(f"missing fixture file for task {task_id}")
        hashes[task_id] = _sha256(fixture_path)
    fingerprint = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode("utf-8")).hexdigest()
    return {"fixture_bundle_sha256": hashes, "fixture_bundles_sha256": fingerprint}


def build_manifest(
    repo_root: Path,
    bench_root: Path,
    profile: RunProfile,
    *,
    requested_model: str,
    actual_models: list[str],
    temperature: float | None,
    seed: int | None,
    reasoning_effort: str | None,
    reasoning_mode: str | None,
    records: list[SampleRecord],
    benchmark_commit_sha: str,
    godprompt_commit_sha: str,
    working_tree_dirty: bool,
    evaluated_godprompt_sha256: str | None = None,
    evaluated_plan_sha256: str | None = None,
) -> dict[str, Any]:
    manifest_path = bench_root / "tasks" / "manifest.json"
    baseline_hash = hashlib.sha256(condition_prompt("baseline", repo_root).encode()).hexdigest()
    godprompt_hash = evaluated_godprompt_sha256 or hashlib.sha256(
        condition_prompt("godprompt", repo_root).encode()
    ).hexdigest()
    infrastructure_failures = sum(record.infrastructure_error is not None for record in records)
    return {
        "run_id": f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "profile": profile.name,
        "provider": requested_model.split("/", 1)[0] if "/" in requested_model else "unspecified",
        "requested_model": requested_model,
        "actual_models": sorted(set(actual_models)),
        "temperature": temperature,
        "seed": seed,
        "reasoning_effort": reasoning_effort,
        "reasoning_mode": reasoning_mode,
        "max_output_tokens": profile.max_output_tokens,
        "max_messages": profile.max_messages,
        "max_time_seconds": profile.max_time_seconds,
        "tools": ["bash", "text_editor"],
        "inspect_ai_version": version("inspect-ai"),
        "python_version": platform.python_version(),
        "godprompt_commit_sha": godprompt_commit_sha,
        "benchmark_commit_sha": benchmark_commit_sha,
        "working_tree_dirty": working_tree_dirty,
        "task_manifest_sha256": _sha256(manifest_path),
        **fixture_fingerprints(bench_root, profile.task_ids),
        "sandbox_dockerfile_sha256": _sha256(bench_root / "sandbox" / "Dockerfile"),
        "sandbox_compose_sha256": _sha256(bench_root / "sandbox" / "compose.yaml"),
        "baseline_system_prompt_sha256": baseline_hash,
        "godprompt_system_prompt_sha256": godprompt_hash,
        "plan_sha256_schema": "godprompt.bench.plan.v1" if evaluated_plan_sha256 else None,
        "plan_sha256": evaluated_plan_sha256,
        "epochs": profile.epochs,
        "requested_samples": len(profile.task_ids) * profile.epochs * 2,
        "completed_samples": len(records) - infrastructure_failures,
        "infrastructure_failures": infrastructure_failures,
    }


def _condition_for_log(log: Any) -> str:
    metadata = getattr(log, "metadata", None) or {}
    condition = metadata.get("condition")
    task_name = str(getattr(getattr(log, "eval", None), "task", ""))
    task_condition = {
        "godprompt_bench_baseline": "baseline",
        "godprompt_bench_godprompt": "godprompt",
    }.get(task_name)
    if task_name and task_condition is None:
        raise RuntimeError("could not determine benchmark condition: unrecognized task identity")
    if condition is not None and condition not in {"baseline", "godprompt"}:
        raise RuntimeError("invalid benchmark condition in Inspect log metadata")
    if condition is not None and task_condition is not None and condition != task_condition:
        raise RuntimeError("Inspect log condition conflicts with task identity")
    if condition is not None:
        return condition
    if task_condition is not None:
        return task_condition
    raise RuntimeError("could not determine benchmark condition from Inspect log")


def condition_batches(task_ids: tuple[str, ...]) -> list[tuple[str, tuple[str, ...]]]:
    """Counterbalance baseline-first and treatment-first tasks without repeats."""
    baseline_first = task_ids[::2]
    treatment_first = task_ids[1::2]
    batches = [("baseline", baseline_first), ("godprompt", baseline_first)]
    if treatment_first:
        batches.extend((("godprompt", treatment_first), ("baseline", treatment_first)))
    return batches


def _plan_sha256(bench_root: Path, profile: RunProfile, plan: dict[str, Any]) -> str:
    """Bind an optional live-run guard to the exact offline inputs, not prices."""
    source_root = bench_root / "godprompt_bench"
    source_hashes = {
        path.name: _sha256(path)
        for path in sorted(source_root.glob("*.py"))
    }
    if not source_hashes:
        raise ValueError("missing benchmark source files for plan fingerprint")
    inputs = {
        "schema": "godprompt.bench.plan.v1",
        "plan": {key: value for key, value in plan.items()
                 if key not in ("preview_only", "cost_estimate_usd", "cost_note")},
        "task_ids": list(profile.task_ids),
        "task_manifest_sha256": _sha256(bench_root / "tasks" / "manifest.json"),
        "godprompt_sha256": _sha256(bench_root.parent / "GodPrompt.md"),
        "dockerfile_sha256": _sha256(bench_root / "sandbox" / "Dockerfile"),
        "compose_sha256": _sha256(bench_root / "sandbox" / "compose.yaml"),
        "pyproject_sha256": _sha256(bench_root / "pyproject.toml"),
        "source_sha256": source_hashes,
    }
    payload = json.dumps(inputs, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=True, allow_nan=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def preview_benchmark(
    bench_root: Path,
    profile: RunProfile,
    *,
    model: str | None = None,
    temperature: float | None = None,
    seed: int | None = None,
    reasoning_effort: str | None = None,
    reasoning_mode: str | None = None,
) -> dict[str, Any]:
    """Validate the selected fixtures and show run size without starting a model."""
    if temperature is not None and not isfinite(temperature):
        raise ValueError("temperature must be finite")
    tasks = load_manifest(bench_root / "tasks" / "manifest.json")
    validate_manifest(tasks)
    categories = {task.id: task.category for task in tasks}
    missing = sorted(set(profile.task_ids) - categories.keys())
    if missing:
        raise ValueError(f"profile contains unknown task IDs: {missing}")
    fingerprints = fixture_fingerprints(bench_root, profile.task_ids)
    plan = {
        "preview_only": True,
        "profile": profile.name,
        "model": model,
        "conditions": ["baseline", "godprompt"],
        "tasks_per_condition": len(profile.task_ids),
        "epochs": profile.epochs,
        "planned_samples": 2 * len(profile.task_ids) * profile.epochs,
        "categories": dict(sorted(Counter(categories[task_id] for task_id in profile.task_ids).items())),
        "max_messages_per_sample": profile.max_messages,
        "max_time_seconds_per_sample": profile.max_time_seconds,
        "max_output_tokens_per_sample": profile.max_output_tokens,
        "requested_controls": {
            "temperature": temperature,
            "seed": seed,
            "reasoning_effort": reasoning_effort,
            "reasoning_mode": reasoning_mode,
        },
        "fixture_bundles_sha256": fingerprints["fixture_bundles_sha256"],
        "cost_estimate_usd": None,
        "cost_note": "Actual provider cost cannot be inferred from configured sample limits.",
    }
    plan["plan_sha256"] = _plan_sha256(bench_root, profile, plan)
    return plan


def format_preview_markdown(plan: dict[str, Any]) -> str:
    """Render an already validated offline plan for human preflight review."""
    def safe(value: Any) -> str:
        if value is None:
            return "not selected"
        text = str(value).replace("\r", " ").replace("\n", " ").replace("\t", " ")
        for char in ("\\", "`", "|", "*", "_"):
            text = text.replace(char, "\\" + char)
        return text

    controls = plan["requested_controls"]
    lines = [
        "# GodPrompt Bench evaluation plan",
        "",
        "**Preview only** - No Docker, model or provider calls; no results written.",
        "",
        f"- Profile: {safe(plan['profile'])}",
        f"- Model: {safe(plan['model'])}",
        f"- Conditions: {', '.join(safe(c) for c in plan['conditions'])}",
        f"- Tasks per condition: {plan['tasks_per_condition']}",
        f"- Epochs: {plan['epochs']}",
        f"- Planned samples: {plan['planned_samples']}",
        f"- Max messages per sample: {plan['max_messages_per_sample']}",
        f"- Max seconds per sample: {plan['max_time_seconds_per_sample']}",
        f"- Max output tokens per sample: {plan['max_output_tokens_per_sample']}",
        f"- Fixture SHA256: {safe(plan['fixture_bundles_sha256'])}",
        f"- Plan SHA256: {safe(plan['plan_sha256'])}",
        "",
        "## Task categories",
        "",
    ]
    lines.extend(f"- {safe(name)}: {count}" for name, count in plan["categories"].items())
    lines.extend([
        "",
        "## Requested controls",
        "",
        f"- Temperature: {safe(controls['temperature'])}",
        f"- Seed: {safe(controls['seed'])}",
        f"- Reasoning effort: {safe(controls['reasoning_effort'])}",
        f"- Reasoning mode: {safe(controls['reasoning_mode'])}",
        "",
        "**Cost is unknown:** actual provider cost cannot be inferred from sample limits.",
        "This preview does not establish Docker daemon readiness, credentials, model "
        "compatibility or benchmark results.",
    ])
    if "experimental_arm" in plan:
        arm = plan["experimental_arm"]
        lines.extend([
            "",
            "## Experimental MCP task-contract arm (preview only)",
            "",
            f"- Planned additional samples: {arm['planned_additional_samples']}",
            f"- Pinned MCP release: {safe(arm['mcp_release_tag'])} ({safe(arm['mcp_release_sha'])})",
            "- Reference baseline and GodPrompt conditions are unchanged.",
            "- No live-run plan SHA is offered for this disabled experimental arm.",
            "- Live execution is disabled; trusted tool-output receipts and separate",
            "  provider-spend approval are required before any paired evaluation.",
        ])
    if "reviewed_live_argv" in plan:
        lines.extend([
            "",
            "## Reviewed live-run arguments (JSON argv)",
            "",
            "Each array element is a separate argument, not a shell command.",
            "Live evaluation may incur provider charges; review the output destination separately.",
            "",
            "```json",
            json.dumps(plan["reviewed_live_argv"], indent=2, ensure_ascii=True),
            "```",
        ])
    return "\n".join(lines) + "\n"


def format_discovery_markdown(report: dict[str, Any]) -> str:
    """Render validated offline profile/task discovery without a model run."""
    def safe(value: Any) -> str:
        text = str(value).replace("\r", " ").replace("\n", " ").replace("\t", " ")
        for char in ("\\", "`", "|", "*", "_"):
            text = text.replace(char, "\\" + char)
        return text

    def duration(seconds: int) -> str:
        if seconds % 3600 == 0:
            return f"{seconds // 3600} h"
        if seconds % 60 == 0:
            return f"{seconds // 60} min"
        return f"{seconds} s"

    if "profiles" in report:
        lines = [
            "# GodPrompt Bench profiles",
            "",
            "**Preview only** - No Docker, model or provider calls; no results written.",
            "",
            "| Profile | Tasks per condition | Epochs | Planned samples | Per-sample limit | Cumulative sample-time ceiling |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
        for profile in report["profiles"]:
            lines.append(
                f"| {safe(profile['profile'])} | {profile['tasks_per_condition']} "
                f"| {profile['epochs']} | {profile['planned_samples']} "
                f"| {profile['max_time_seconds_per_sample']} s "
                f"| {duration(profile['cumulative_sample_time_limit_seconds'])} |"
            )
        lines.extend([
            "",
            "Cumulative limits sum per-sample time caps across both conditions and all epochs; "
            "not a wall-clock or cost estimate (parallelism and overhead vary).",
        ])
        lines.extend(["", "## Fixture and category coverage", ""])
        for profile in report["profiles"]:
            categories = ", ".join(
                f"{safe(category)}: {count}"
                for category, count in profile["categories"].items()
            )
            lines.append(
                f"- {safe(profile['profile'])} ({safe(profile['profile_id'])}): "
                f"{categories}; Fixture SHA256: {safe(profile['fixture_bundles_sha256'])}"
            )
    else:
        lines = [
            "# GodPrompt Bench tasks",
            "",
            "**Preview only** - No Docker, model or provider calls; no results written.",
            "",
            f"- Profile: {safe(report['profile'])} ({safe(report['profile_id'])})",
            f"- Tasks per condition: {report['tasks_per_condition']}",
            f"- Fixture SHA256: {safe(report['fixture_bundles_sha256'])}",
            "",
        ]
        for heading, counts in (
            ("Category coverage", report["categories"]),
            ("Runtime coverage", report["runtimes"]),
        ):
            lines.extend([f"## {heading}", ""])
            lines.extend(f"- {safe(name)}: {count}" for name, count in counts.items())
            lines.append("")
        lines.extend(["| ID | Category | Runtime |", "| --- | --- | --- |"])
        lines.extend(
            f"| {safe(task['id'])} | {safe(task['category'])} | {safe(task['runtime'])} |"
            for task in report["tasks"]
        )
    return "\n".join(lines) + "\n"


def execute_benchmark(
    repo_root: Path,
    bench_root: Path,
    profile: RunProfile,
    *,
    model: str,
    output_dir: Path,
    temperature: float | None = None,
    seed: int | None = None,
    reasoning_effort: str | None = None,
    reasoning_mode: str | None = None,
    required_plan_sha256: str | None = None,
) -> Path:
    if temperature is not None and not isfinite(temperature):
        raise ValueError("temperature must be finite")

    plan_sha256 = preview_benchmark(
        bench_root, profile, model=model, temperature=temperature,
        seed=seed, reasoning_effort=reasoning_effort, reasoning_mode=reasoning_mode,
    )["plan_sha256"]
    if required_plan_sha256 is not None and plan_sha256 != required_plan_sha256:
        raise ValueError("plan fingerprint mismatch before evaluation")

    from inspect_ai import eval as inspect_eval

    benchmark_commit_sha = _git(repo_root, "rev-parse", "HEAD")
    godprompt_commit_sha = _git(
        repo_root,
        "log",
        "-1",
        "--format=%H",
        "--",
        "GodPrompt.md",
        "SKILL.md",
        "references/01-PROTOCOLS.md",
        "references/02-GATES.md",
        "references/03-ANTI-PATTERNS.md",
    )
    working_tree_dirty = bool(_git(repo_root, "status", "--porcelain"))

    canonical_tasks = load_manifest(bench_root / "tasks" / "manifest.json")
    validate_manifest(canonical_tasks)
    task_categories = {task.id: task.category for task in canonical_tasks}
    evaluated_prompt = condition_prompt("godprompt", repo_root)
    evaluated_prompt_sha256 = hashlib.sha256(evaluated_prompt.encode()).hexdigest()

    tasks = [
        build_task(
            condition,
            bench_root,
            repo_root,
            batch_ids,
            epochs=profile.epochs,
            max_messages=profile.max_messages,
            max_time_seconds=profile.max_time_seconds,
            max_output_tokens=profile.max_output_tokens,
        )
        for condition, batch_ids in condition_batches(profile.task_ids)
    ]
    if condition_prompt("godprompt", repo_root) != evaluated_prompt:
        raise ValueError("GodPrompt instructions changed during task construction; refusing evaluation")
    # A mid-run fixture edit must not be attributed to the files used to build
    # the evaluation tasks in the published benchmark provenance.
    evaluated_fixtures = fixture_fingerprints(bench_root, profile.task_ids)
    raw_log_dir = output_dir / "inspect-logs"
    _create_raw_log_directory(raw_log_dir)
    kwargs: dict[str, Any] = {
        "model": model,
        "log_dir": str(raw_log_dir),
        "log_format": "eval",
        "fail_on_error": False,
        "continue_on_fail": True,
        "score_on_error": True,
        "max_tokens": profile.max_output_tokens,
        "max_samples": 1,
        "max_tasks": 1,
        "max_sandboxes": 1,
        "max_connections": 1,
        "adaptive_connections": False,
        "cache": False,
        "cache_prompt": False,
        "log_model_api": False,
    }
    if temperature is not None:
        kwargs["temperature"] = temperature
    if seed is not None:
        kwargs["seed"] = seed
    if reasoning_effort is not None:
        kwargs["reasoning_effort"] = reasoning_effort
    if reasoning_mode is not None:
        kwargs["reasoning_mode"] = reasoning_mode

    logs = inspect_eval(tasks, **kwargs)
    records: list[SampleRecord] = []
    trajectories: list[dict[str, Any]] = []
    actual_models: list[str] = []
    for log in logs:
        condition = _condition_for_log(log)
        actual_models.append(str(log.eval.model))
        for sample in log.samples or []:
            records.append(sample_record(sample, condition))
            trajectories.append(public_trajectory(sample, condition))

    validate_sample_coverage(profile, records, task_categories)

    if fixture_fingerprints(bench_root, profile.task_ids) != evaluated_fixtures:
        raise ValueError("benchmark fixture files changed during evaluation; refusing public export")
    if condition_prompt("godprompt", repo_root) != evaluated_prompt:
        raise ValueError("GodPrompt instructions changed during evaluation; refusing public export")
    if preview_benchmark(
        bench_root, profile, model=model, temperature=temperature,
        seed=seed, reasoning_effort=reasoning_effort, reasoning_mode=reasoning_mode,
    )["plan_sha256"] != plan_sha256:
        raise ValueError("benchmark plan inputs changed during evaluation; refusing public export")

    manifest = build_manifest(
        repo_root,
        bench_root,
        profile,
        requested_model=model,
        actual_models=actual_models,
        temperature=temperature,
        seed=seed,
        reasoning_effort=reasoning_effort,
        reasoning_mode=reasoning_mode,
        records=records,
        benchmark_commit_sha=benchmark_commit_sha,
        godprompt_commit_sha=godprompt_commit_sha,
        working_tree_dirty=working_tree_dirty,
        evaluated_godprompt_sha256=evaluated_prompt_sha256,
        evaluated_plan_sha256=plan_sha256,
    )
    public_dir = output_dir / manifest["run_id"]
    export_run(public_dir, manifest, records, trajectories)
    return public_dir


def main() -> None:
    bench_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Run the GodPrompt baseline-vs-GodPrompt benchmark")
    profile_names = ("smoke", "half", "full")
    profile_selection = parser.add_mutually_exclusive_group()
    profile_selection.add_argument("--profile", choices=profile_names, default=None)
    profile_selection.add_argument("--profile-file", type=Path,
                                   help="Local bounded JSON profile (non-reference run)")
    parser.add_argument("--model", help="Inspect model name (required for a live evaluation, optional for --dry-run)")
    parser.add_argument("--temperature", type=float)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--reasoning-effort", choices=("none", "minimal", "low", "medium", "high", "xhigh", "max"))
    parser.add_argument("--reasoning-mode", choices=("standard", "pro"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--format", choices=("json", "markdown"), default="json",
                        help="Output format for offline previews/discovery; JSON is the default")
    parser.add_argument(
        "--experimental-mcp-contract", action="store_true",
        help="Preview the opt-in third MCP contract arm offline; live execution is not enabled",
    )
    parser.add_argument(
        "--require-plan-sha256", metavar="SHA256",
        help="Opt-in live-run guard: require the same fingerprint shown by --dry-run",
    )
    offline_actions = parser.add_mutually_exclusive_group()
    offline_actions.add_argument("--dry-run", action="store_true", help="Validate fixtures and print planned samples without model calls")
    offline_actions.add_argument("--list-profiles", action="store_true", help="Compare validated bundled profile sizes offline without model calls")
    offline_actions.add_argument("--list-tasks", action="store_true", help="List task IDs, categories and runtimes for a selected profile offline")
    offline_actions.add_argument(
        "--expected-identities-plan", action="store_true",
        help="Print caller-plan JSON for offline three-arm identity checks; not execution provenance",
    )
    parser.add_argument(
        "--expected-identities-output", type=Path, metavar="FILE",
        help="Write caller-plan JSON as UTF-8 to a new file (requires --expected-identities-plan)",
    )
    args = parser.parse_args()
    if args.expected_identities_output is not None and not args.expected_identities_plan:
        parser.error("--expected-identities-output requires --expected-identities-plan")
    if args.model is not None and not args.model.strip():
        parser.error("--model must be non-blank")
    if args.temperature is not None and not isfinite(args.temperature):
        parser.error("temperature must be finite")
    if args.experimental_mcp_contract and not args.dry_run:
        parser.error("--experimental-mcp-contract currently requires --dry-run; live MCP evaluation is not enabled")
    if args.require_plan_sha256 is not None:
        if args.dry_run or args.list_profiles or args.list_tasks or args.expected_identities_plan:
            parser.error("--require-plan-sha256 is only valid for a live run")
        if re.fullmatch(r"[0-9a-f]{64}", args.require_plan_sha256) is None:
            parser.error("--require-plan-sha256 must be 64 lowercase hexadecimal characters")
    if args.profile_file is not None and args.list_profiles:
        parser.error("--list-profiles only lists bundled profiles, not --profile-file")
    if args.format == "markdown" and not (args.dry_run or args.list_profiles or args.list_tasks or args.expected_identities_plan):
        parser.error("--format markdown requires an offline action")
    if args.expected_identities_plan and args.format != "json":
        parser.error("--expected-identities-plan outputs JSON only")
    if not (args.dry_run or args.list_profiles or args.list_tasks or args.expected_identities_plan) and args.model is None:
        parser.error("--model is required unless --dry-run, --list-profiles, --list-tasks, or --expected-identities-plan is specified")

    repo_root = bench_root.parent
    if args.list_profiles:
        profiles = []
        for name in profile_names:
            plan = preview_benchmark(bench_root, load_profile(bench_root / "configs" / f"{name}.json"))
            profiles.append({
                "profile": name,
                "profile_id": plan["profile"],
                **{key: plan[key] for key in (
                    "tasks_per_condition", "epochs", "planned_samples",
                    "max_time_seconds_per_sample", "categories", "fixture_bundles_sha256",
                )},
                "cumulative_sample_time_limit_seconds": (
                    plan["planned_samples"] * plan["max_time_seconds_per_sample"]
                ),
            })
        report = {"preview_only": True, "profiles": profiles}
        print(format_discovery_markdown(report) if args.format == "markdown"
              else json.dumps(report, indent=2, sort_keys=True))
        return
    if args.profile_file is not None:
        try:
            profile = load_custom_profile(args.profile_file, bench_root)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            parser.error(f"invalid custom profile: {exc}")
    else:
        profile = load_profile(bench_root / "configs" / f"{args.profile or 'smoke'}.json")
    if args.expected_identities_plan:
        # Validate the profile and fixtures before offering a caller-generated
        # plan. These identities do not attest to third-arm execution records.
        preview_benchmark(bench_root, profile)
        payload = json.dumps({
            "schema_version": 1,
            "task_epochs": [
                {"task_id": task_id, "epoch": epoch}
                for task_id in profile.task_ids
                for epoch in range(1, profile.epochs + 1)
            ],
        }, sort_keys=True, indent=2)
        if args.expected_identities_output is None:
            print(payload)
        else:
            # Exclusive creation prevents accidentally replacing a caller's plan.
            # Explicit UTF-8 avoids PowerShell 5.1's UTF-16LE stdout redirection.
            try:
                with args.expected_identities_output.open("x", encoding="utf-8", newline="\n") as target:
                    target.write(payload + "\n")
            except OSError:
                parser.error("could not create --expected-identities-output file; choose a new writable path")
        return
    if args.list_tasks:
        plan = preview_benchmark(bench_root, profile)
        canonical_tasks = {task.id: task for task in load_manifest(bench_root / "tasks" / "manifest.json")}
        report = {
            "preview_only": True,
            "profile": "custom" if args.profile_file is not None else (args.profile or "smoke"),
            "profile_id": plan["profile"],
            "tasks_per_condition": plan["tasks_per_condition"],
            "fixture_bundles_sha256": plan["fixture_bundles_sha256"],
            "categories": plan["categories"],
            "runtimes": dict(sorted(Counter(
                canonical_tasks[task_id].runtime for task_id in profile.task_ids
            ).items())),
            "tasks": [
                {"id": task_id, "category": canonical_tasks[task_id].category,
                 "runtime": canonical_tasks[task_id].runtime}
                for task_id in profile.task_ids
            ],
        }
        print(format_discovery_markdown(report) if args.format == "markdown"
              else json.dumps(report, indent=2, sort_keys=True))
        return
    if args.dry_run:
        plan = preview_benchmark(
            bench_root,
            profile,
            model=args.model,
            temperature=args.temperature,
            seed=args.seed,
            reasoning_effort=args.reasoning_effort,
            reasoning_mode=args.reasoning_mode,
        )
        if args.model is not None and not args.experimental_mcp_contract:
            # Keep arguments structured: a model or profile path is not shell code.
            reviewed_argv = (
                [f"--profile-file={args.profile_file}"]
                if args.profile_file is not None
                else [f"--profile={args.profile or 'smoke'}"]
            )
            reviewed_argv.append(f"--model={args.model}")
            for flag, value in (
                ("--temperature", args.temperature),
                ("--seed", args.seed),
                ("--reasoning-effort", args.reasoning_effort),
                ("--reasoning-mode", args.reasoning_mode),
            ):
                if value is not None:
                    reviewed_argv.append(f"{flag}={value}")
            if args.output is not None:
                reviewed_argv.append(f"--output={args.output}")
            reviewed_argv.append(f"--require-plan-sha256={plan['plan_sha256']}")
            plan["reviewed_live_argv"] = reviewed_argv
        if args.experimental_mcp_contract:
            from .mcp_contract_adapter import MCP_RELEASE_SHA, MCP_RELEASE_TAG

            # A third-arm preview must not supply a hash that approves a two-arm live run.
            plan["plan_sha256"] = None
            plan["experimental_arm"] = {
                "name": "godprompt_mcp_contract",
                "preview_only": True,
                "live_execution_enabled": False,
                "reference_conditions_unchanged": True,
                "planned_additional_samples": len(profile.task_ids) * profile.epochs,
                "mcp_release_tag": MCP_RELEASE_TAG,
                "mcp_release_sha": MCP_RELEASE_SHA,
                "requires_trusted_tool_receipts": True,
                "requires_separate_provider_spend_approval": True,
                "held_out_failure_corpus": "not selected",
            }
        if args.format == "markdown":
            print(format_preview_markdown(plan), end="")
        else:
            print(json.dumps(plan, indent=2, sort_keys=True))
        return
    if args.require_plan_sha256 is not None:
        actual = preview_benchmark(
            bench_root, profile, model=args.model, temperature=args.temperature,
            seed=args.seed, reasoning_effort=args.reasoning_effort,
            reasoning_mode=args.reasoning_mode,
        )["plan_sha256"]
        if actual != args.require_plan_sha256:
            parser.error("plan fingerprint mismatch; rerun --dry-run with the intended exact controls and review its plan SHA256")
    result = execute_benchmark(
        repo_root,
        bench_root,
        profile,
        model=args.model,
        output_dir=args.output if args.output is not None else bench_root / "results",
        temperature=args.temperature,
        seed=args.seed,
        reasoning_effort=args.reasoning_effort,
        reasoning_mode=args.reasoning_mode,
        required_plan_sha256=args.require_plan_sha256,
    )
    print(result)


if __name__ == "__main__":
    main()
