from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import uuid
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path
from typing import Any, Mapping

from .agent import condition_prompt
from .eval import build_task
from .export import export_run
from .models import RunProfile, SampleRecord


def load_profile(path: Path) -> RunProfile:
    raw = json.loads(path.read_text(encoding="utf-8"))
    required = {"name", "task_ids", "epochs", "max_messages", "max_time_seconds", "max_output_tokens"}
    missing = required - raw.keys()
    if missing:
        raise ValueError(f"profile missing fields: {sorted(missing)}")
    task_ids = raw["task_ids"]
    if not isinstance(task_ids, list) or not task_ids or not all(isinstance(v, str) for v in task_ids):
        raise ValueError("profile task_ids must be a non-empty list of strings")
    profile = RunProfile(
        name=str(raw["name"]),
        task_ids=tuple(task_ids),
        epochs=int(raw["epochs"]),
        max_messages=int(raw["max_messages"]),
        max_time_seconds=int(raw["max_time_seconds"]),
        max_output_tokens=int(raw["max_output_tokens"]),
    )
    if min(profile.epochs, profile.max_messages, profile.max_time_seconds, profile.max_output_tokens) <= 0:
        raise ValueError("profile numeric limits must be positive")
    return profile


def _usage_totals(model_usage: Mapping[str, Any] | None) -> tuple[int | None, int | None]:
    if not model_usage:
        return None, None
    input_tokens = 0
    output_tokens = 0
    for usage in model_usage.values():
        input_tokens += int(getattr(usage, "input_tokens", 0) or 0)
        input_tokens += int(getattr(usage, "input_tokens_cache_read", 0) or 0)
        input_tokens += int(getattr(usage, "input_tokens_cache_write", 0) or 0)
        output_tokens += int(getattr(usage, "output_tokens", 0) or 0)
    return input_tokens, output_tokens


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
        passed=bool(values.get("passed", 0)),
        completion_status=completion_status,
        false_completion=bool(values.get("false_completion", 0)),
        scope_violation=bool(values.get("scope_violation", 0)),
        tool_misuse_count=int(values.get("tool_misuse_count", 0) or 0),
        verification_attempts=int(values.get("verification_attempts", 0) or 0),
        failed_tool_calls=int(values.get("failed_tool_calls", 0) or 0),
        retries=int(values.get("retries", 0) or 0),
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
            if isinstance(item, Mapping) and str(item.get("type", "")).lower() in {"reasoning", "redacted_reasoning"}:
                continue
            result.append(_strip_reasoning(item))
        return result
    if isinstance(value, Mapping):
        return {key: _strip_reasoning(item) for key, item in value.items() if key not in {"reasoning", "encrypted_content"}}
    return value


def public_trajectory(sample: Any, condition: str) -> dict[str, Any]:
    messages: list[dict[str, Any]] = []
    for message in getattr(sample, "messages", []) or []:
        role = getattr(message, "role", None)
        dumped = _dump(message)
        if role == "system" or not isinstance(dumped, dict):
            continue
        messages.append(_strip_reasoning(dumped))

    events: list[dict[str, Any]] = []
    for event in getattr(sample, "events", []) or []:
        if getattr(event, "event", None) not in {"tool", "approval"}:
            continue
        dumped = _dump(event)
        if isinstance(dumped, dict):
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
) -> dict[str, Any]:
    head = _git(repo_root, "rev-parse", "HEAD")
    godprompt_commit = _git(
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
    dirty = bool(_git(repo_root, "status", "--porcelain"))
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
        "godprompt_commit_sha": godprompt_commit,
        "benchmark_commit_sha": head,
        "working_tree_dirty": dirty,
        "task_manifest_sha256": _sha256(manifest_path),
        "sandbox_dockerfile_sha256": _sha256(bench_root / "sandbox" / "Dockerfile"),
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

    tasks = [
        build_task(
            condition,
            bench_root,
            repo_root,
            profile.task_ids,
            epochs=profile.epochs,
            max_messages=profile.max_messages,
            max_time_seconds=profile.max_time_seconds,
            max_output_tokens=profile.max_output_tokens,
        )
        for condition in ("baseline", "godprompt")
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
