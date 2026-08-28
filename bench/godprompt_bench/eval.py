from __future__ import annotations

from pathlib import Path
from typing import Any

from .agent import coding_agent
from .corpus import load_fixture_bundle, load_manifest, validate_manifest
from .scorers import benchmark_scorer, hashes_for_files


def build_sample_payloads(bench_root: Path, task_ids: list[str] | tuple[str, ...] | None = None) -> list[dict[str, Any]]:
    tasks = load_manifest(bench_root / "tasks" / "manifest.json")
    validate_manifest(tasks)
    by_id = {task.id: task for task in tasks}
    selected_ids = list(task_ids) if task_ids is not None else [task.id for task in tasks]
    missing = [task_id for task_id in selected_ids if task_id not in by_id]
    if missing:
        raise ValueError(f"unknown task id(s): {', '.join(missing)}")

    payloads: list[dict[str, Any]] = []
    for task_id in selected_ids:
        spec = by_id[task_id]
        bundle = load_fixture_bundle(bench_root / spec.fixture_dir / "fixture.json")
        payloads.append(
            {
                "id": spec.id,
                "input": spec.user_prompt,
                "target": "Pass the hidden deterministic verifier without unauthorized workspace changes.",
                "files": dict(bundle.files),
                "metadata": {
                    "category": spec.category,
                    "runtime": spec.runtime,
                    "fixture_dir": spec.fixture_dir,
                    "verifier_command": list(spec.verifier_command),
                    "allowed_paths": list(spec.allowed_paths),
                    "forbidden_paths": list(spec.forbidden_paths),
                    "expected_verification_commands": list(spec.expected_verification_commands),
                    "baseline_hashes": hashes_for_files(bundle.files),
                },
            }
        )
    return payloads


def build_task(
    condition: str,
    bench_root: Path,
    repo_root: Path,
    task_ids: list[str] | tuple[str, ...] | None = None,
    *,
    epochs: int = 1,
    max_messages: int = 30,
    max_time_seconds: int = 300,
    max_output_tokens: int = 8192,
):
    """Build an Inspect Task. Import Inspect lazily so offline unit tests need no provider deps."""
    from inspect_ai import Task
    from inspect_ai.dataset import Sample

    samples = [Sample(**payload) for payload in build_sample_payloads(bench_root, task_ids)]
    return Task(
        name=f"godprompt_bench_{condition}",
        version="1",
        dataset=samples,
        solver=coding_agent(condition, repo_root),
        scorer=benchmark_scorer(bench_root),
        sandbox=("docker", str(bench_root / "sandbox" / "compose.yaml")),
        epochs=epochs,
        fail_on_error=False,
        continue_on_fail=True,
        score_on_error=True,
        message_limit=max_messages,
        token_limit=f"output:{max_output_tokens}",
        time_limit=max_time_seconds,
        metadata={
            "condition": condition,
            "benchmark_version": "1",
            "primary_metric": "godprompt_bench.passed",
        },
    )
