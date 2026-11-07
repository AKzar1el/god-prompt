from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import uuid
from collections import Counter
from datetime import datetime, timezone
from importlib.metadata import version
from math import isfinite
from pathlib import Path
from typing import Any, Mapping

from .agent import condition_prompt
from .eval import build_task
from .export import export_run
from .models import RunProfile, SampleRecord


def load_profile(path: Path) -> RunProfile:
    raw = json.loads(path.read_text(encoding="utf-8"))
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


def validate_sample_coverage(profile: RunProfile, records: list[SampleRecord]) -> None:
    """Reject partial or duplicated Inspect results before publishing pass rates."""
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
    if duplicates or missing or unexpected:
        raise ValueError(
            f"invalid benchmark sample coverage: duplicate={duplicates[:5]}; "
            f"missing={missing[:5]}; unexpected={unexpected[:5]}"
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
    for usage in model_usage.values():
        input_tokens += _token_count(getattr(usage, "input_tokens", None), "input_tokens")
        input_tokens += _token_count(getattr(usage, "input_tokens_cache_read", None), "input_tokens_cache_read")
        input_tokens += _token_count(getattr(usage, "input_tokens_cache_write", None), "input_tokens_cache_write")
        output_tokens += _token_count(getattr(usage, "output_tokens", None), "output_tokens")
    return input_tokens, output_tokens


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


def sample_record(sample: Any, condition: str) -> SampleRecord:
    score = (getattr(sample, "scores", None) or {}).get("godprompt_bench")
    limit = getattr(sample, "limit", None)
    error = getattr(sample, "error", None)
    values: Mapping[str, Any] = {}
    score_metadata: Mapping[str, Any] = {}
    if score is not None:
        values = score.value if isinstance(score.value, Mapping) else {}
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
        task_id=str(sample.id),
        category=str(metadata.get("category", "unknown")),
        condition=condition,
        epoch=int(sample.epoch),
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
        latency_seconds=getattr(sample, "total_time", None),
        infrastructure_error=infrastructure_error,
    )


def _dump(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", exclude_none=True)
    if isinstance(value, Mapping):
        return dict(value)
    return value


def _strip_reasoning(value: Any) -> Any:
    if isinstance(value, list):
        result = []
        for item in value:
            if isinstance(item, Mapping) and str(item.get("type", "")).lower() in {
                "reasoning", "redacted_reasoning", "thinking", "redacted_thinking"
            }:
                continue
            result.append(_strip_reasoning(item))
        return result
    if isinstance(value, Mapping):
        return {
            key: _strip_reasoning(item) for key, item in value.items()
            if key not in {"reasoning", "thinking", "redacted_thinking", "encrypted_content"}
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
        if not roles or not all(_is_public_message_role(role) for role in roles):
            continue
        messages.append(_strip_reasoning(dumped))

    events: list[dict[str, Any]] = []
    for event in getattr(sample, "events", []) or []:
        dumped = _dump(event)
        if not isinstance(dumped, dict):
            continue
        if dumped.get("event", getattr(event, "event", None)) not in ("tool", "approval"):
            continue
        events.append(_strip_reasoning(dumped))

    return {
        "task_id": str(sample.id),
        "epoch": int(sample.epoch),
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


def fixture_fingerprints(bench_root: Path, task_ids: tuple[str, ...]) -> dict[str, Any]:
    """Fingerprint selected fixture files, including their hidden verifier content."""
    manifest = json.loads((bench_root / "tasks" / "manifest.json").read_text(encoding="utf-8"))
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
) -> dict[str, Any]:
    manifest_path = bench_root / "tasks" / "manifest.json"
    baseline_hash = hashlib.sha256(condition_prompt("baseline", repo_root).encode()).hexdigest()
    godprompt_hash = hashlib.sha256(condition_prompt("godprompt", repo_root).encode()).hexdigest()
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
        "epochs": profile.epochs,
        "requested_samples": len(profile.task_ids) * profile.epochs * 2,
        "completed_samples": len(records) - infrastructure_failures,
        "infrastructure_failures": infrastructure_failures,
    }


def _condition_for_log(log: Any) -> str:
    metadata = getattr(log, "metadata", None) or {}
    condition = metadata.get("condition")
    if condition in {"baseline", "godprompt"}:
        return condition
    task_name = str(getattr(getattr(log, "eval", None), "task", ""))
    if "godprompt_bench_godprompt" in task_name:
        return "godprompt"
    if "godprompt_bench_baseline" in task_name:
        return "baseline"
    raise RuntimeError("could not determine benchmark condition from Inspect log")


def condition_batches(task_ids: tuple[str, ...]) -> list[tuple[str, tuple[str, ...]]]:
    """Counterbalance baseline-first and treatment-first tasks without repeats."""
    baseline_first = task_ids[::2]
    treatment_first = task_ids[1::2]
    batches = [("baseline", baseline_first), ("godprompt", baseline_first)]
    if treatment_first:
        batches.extend((("godprompt", treatment_first), ("baseline", treatment_first)))
    return batches


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
) -> Path:
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
    raw_log_dir = output_dir / "inspect-logs"
    raw_log_dir.mkdir(parents=True, exist_ok=True)
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

    validate_sample_coverage(profile, records)

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
    )
    public_dir = output_dir / manifest["run_id"]
    export_run(public_dir, manifest, records, trajectories)
    return public_dir


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the GodPrompt baseline-vs-GodPrompt benchmark")
    parser.add_argument("--profile", choices=("smoke", "half", "full"), default="smoke")
    parser.add_argument("--model", required=True, help="Inspect model name, e.g. openai/gpt-5.6")
    parser.add_argument("--temperature", type=float)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--reasoning-effort", choices=("none", "minimal", "low", "medium", "high", "xhigh", "max"))
    parser.add_argument("--reasoning-mode", choices=("standard", "pro"))
    parser.add_argument("--output", type=Path, default=Path("bench/results"))
    args = parser.parse_args()

    bench_root = Path(__file__).resolve().parents[1]
    repo_root = bench_root.parent
    profile = load_profile(bench_root / "configs" / f"{args.profile}.json")
    result = execute_benchmark(
        repo_root,
        bench_root,
        profile,
        model=args.model,
        output_dir=args.output,
        temperature=args.temperature,
        seed=args.seed,
        reasoning_effort=args.reasoning_effort,
        reasoning_mode=args.reasoning_mode,
    )
    print(result)


if __name__ == "__main__":
    main()
