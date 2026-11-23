"""Read-only, offline inspection of a completed public benchmark export.

This verifies agreement between public scores, summary and manifest counts.
It is not an attestation of model identity, runner execution or publication quality.
"""

from __future__ import annotations

import argparse
from contextlib import ExitStack
import csv
import hashlib
from html import escape
import json
from dataclasses import fields
from math import isfinite
from pathlib import Path
from random import Random
import re
from stat import S_IFMT, S_IFREG
from tempfile import TemporaryDirectory
from typing import Any
from zipfile import BadZipFile, ZipFile
import zlib

from .aggregate import aggregate
from .corpus import _reject_duplicate_json_keys
from .models import SampleRecord


_JSON_MAX_BYTES = 2_000_000
_CSV_MAX_BYTES = 20_000_000
_PUBLIC_ARTIFACTS = (
    ("manifest.json", _JSON_MAX_BYTES),
    ("summary.json", _JSON_MAX_BYTES),
    ("scores.csv", _CSV_MAX_BYTES),
)
_MAX_PUBLIC_ZIP_BYTES = sum(maximum for _, maximum in _PUBLIC_ARTIFACTS) + 1_000_000
_REPORT_CONTROLS = re.compile(r"[\x00-\x1f\x7f-\x9f\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069\ufeff]")
_SHA = re.compile(r"[0-9a-f]{40}\Z")
_INT = re.compile(r"(?:0|[1-9][0-9]*)\Z")
_NUMERIC = {"epoch", "tool_misuse_count", "verification_attempts", "failed_tool_calls", "retries"}
_OPTIONAL_INT = {"input_tokens", "output_tokens"}
_BOOLEAN = {"passed", "false_completion", "scope_violation"}
_OPTIONAL_TEXT = {"infrastructure_error"}
# Scorer protocol statuses plus the runner's local timeout/error fallbacks.
_COMPLETION_STATUSES = {"complete", "blocked", "error", "timeout", "protocol-invalid"}
_COMPARISON_FIELDS = (
    "profile", "requested_model", "actual_models", "requested_samples",
    "task_manifest_sha256", "fixture_bundles_sha256",
    "sandbox_dockerfile_sha256", "sandbox_compose_sha256",
    "baseline_system_prompt_sha256", "epochs", "max_messages",
    "max_time_seconds", "max_output_tokens", "temperature", "seed",
    "reasoning_effort", "reasoning_mode", "inspect_ai_version",
)
_COMPARISON_DISQUALIFIERS = {
    "incomplete_coverage", "missing_model_identity",
    "missing_actual_model_identity", "mixed_actual_models", "incomplete_commit_provenance",
    "unverified_clean_source",
}
_RESOURCE_FIELDS = ("input_tokens", "output_tokens", "failed_tool_calls", "retries")
_UNCERTAINTY_RESAMPLES = 2048
_UNCERTAINTY_MIN_TASKS = 10
_UNCERTAINTY_DISQUALIFIERS = {
    "mock_model", "non_full_profile", "incomplete_coverage",
    "missing_model_identity", "missing_actual_model_identity", "mixed_actual_models",
    "incomplete_commit_provenance", "unverified_clean_source",
}


def _no_nonfinite(value: str) -> Any:
    raise ValueError(f"invalid non-finite JSON constant: {value}")


def _read_json(folder: Path, name: str) -> dict[str, Any]:
    path = folder / name
    _check_file(path, _JSON_MAX_BYTES)
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_json_keys,
            parse_constant=_no_nonfinite,
        )
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid {name}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{name} must contain a JSON object")
    return value


def _check_file(path: Path, maximum: int) -> None:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"missing or linked artifact: {path.name}")
    if path.stat().st_size > maximum:
        raise ValueError(f"artifact too large: {path.name}")


def _public_artifact_sha256(folder: Path) -> dict[str, str]:
    """Fingerprint the bounded public files, never private trajectories."""
    hashes = {}
    for name, maximum in _PUBLIC_ARTIFACTS:
        path = folder / name
        _check_file(path, maximum)
        hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashes


def _public_zip_directory(source: Path, stack: ExitStack) -> Path:
    """Read only three public ZIP entries into short-lived, isolated local files."""
    if source.is_dir() or source.suffix.lower() != ".zip":
        return source
    if source.is_symlink() or not source.is_file():
        raise ValueError("missing or linked public evidence ZIP")
    initial = source.stat()
    if initial.st_size > _MAX_PUBLIC_ZIP_BYTES:
        raise ValueError("public evidence ZIP is too large")
    expected = {name: maximum for name, maximum in _PUBLIC_ARTIFACTS}
    try:
        with ZipFile(source) as archive:
            entries = archive.infolist()
            if len(entries) != len(expected) or {item.filename for item in entries} != set(expected):
                raise ValueError("public evidence ZIP requires exactly three root-level public files")
            output = Path(stack.enter_context(TemporaryDirectory(prefix="godprompt_public_review_")))
            for item in entries:
                if item.flag_bits & 1:
                    raise ValueError("encrypted public evidence ZIP entries are unsupported")
                if (item.is_dir() or S_IFMT(item.external_attr >> 16) not in (0, S_IFREG)):
                    raise ValueError("linked or non-regular public evidence ZIP entry")
                maximum = expected[item.filename]
                if item.file_size > maximum:
                    raise ValueError(f"public evidence ZIP entry too large: {item.filename}")
                with archive.open(item) as handle:
                    data = handle.read(maximum + 1)
                    if len(data) > maximum or handle.read(1):
                        raise ValueError(f"public evidence ZIP entry too large: {item.filename}")
                (output / item.filename).write_bytes(data)
    except (BadZipFile, EOFError, RuntimeError, NotImplementedError, zlib.error) as exc:
        raise ValueError(f"invalid public evidence ZIP: {exc}") from exc
    final = source.stat()
    if (initial.st_size, initial.st_mtime_ns) != (final.st_size, final.st_mtime_ns):
        raise ValueError("public evidence ZIP changed during review")
    return output


def _public_zip_sha256(source: Path) -> str:
    """Hash only a bounded, regular public ZIP, for an independently supplied pin."""
    if source.suffix.lower() != ".zip" or source.is_symlink() or not source.is_file():
        raise ValueError("public ZIP SHA256 pin requires an existing regular ZIP file")
    initial = source.stat()
    if initial.st_size > _MAX_PUBLIC_ZIP_BYTES:
        raise ValueError("public evidence ZIP is too large")
    with source.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    final = source.stat()
    if (initial.st_size, initial.st_mtime_ns) != (final.st_size, final.st_mtime_ns):
        raise ValueError("public evidence ZIP changed during digest verification")
    return digest


def _parse_integer(value: str, name: str, optional: bool = False) -> int | None:
    if optional and value == "":
        return None
    if not _INT.fullmatch(value):
        raise ValueError(f"{name} must be a nonnegative integer")
    number = int(value)
    if name == "epoch" and number < 1:
        raise ValueError("epoch must be positive")
    return number


def _parse_number(value: str, name: str) -> float | None:
    if value == "":
        return None
    try:
        number = float(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a finite number") from exc
    if not isfinite(number) or number < 0:
        raise ValueError(f"{name} must be finite and nonnegative")
    return number


def _parse_record(row: dict[str, str]) -> SampleRecord:
    converted: dict[str, Any] = {}
    for field in fields(SampleRecord):
        name = field.name
        value = row[name]
        if name in _BOOLEAN:
            if value not in ("True", "False"):
                raise ValueError(f"{name} must be True or False")
            converted[name] = value == "True"
        elif name in _NUMERIC or name in _OPTIONAL_INT:
            converted[name] = _parse_integer(value, name, name in _OPTIONAL_INT)
        elif name == "latency_seconds":
            converted[name] = _parse_number(value, name)
        elif name == "completion_status":
            if value not in _COMPLETION_STATUSES:
                raise ValueError("completion_status is not a recognized benchmark status")
            converted[name] = value
        elif name in _OPTIONAL_TEXT:
            converted[name] = value or None
        else:
            if not value:
                raise ValueError(f"{name} cannot be empty")
            converted[name] = value
    return SampleRecord(**converted)


def _read_scores(folder: Path) -> list[SampleRecord]:
    path = folder / "scores.csv"
    _check_file(path, _CSV_MAX_BYTES)
    expected = [field.name for field in fields(SampleRecord)]
    records: list[SampleRecord] = []
    seen: set[tuple[str, str, int]] = set()
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames != expected:
                raise ValueError("scores.csv column schema differs from the public export")
            for line, row in enumerate(reader, start=2):
                if None in row or any(v is None for v in row.values()):
                    raise ValueError(f"invalid scores.csv column count on line {line}")
                try:
                    record = _parse_record(row)
                except ValueError as exc:
                    raise ValueError(f"invalid scores.csv line {line}: {exc}") from exc
                identity = (record.task_id, record.condition, record.epoch)
                if identity in seen:
                    raise ValueError(f"duplicate benchmark sample identity on line {line}")
                seen.add(identity)
                records.append(record)
    except (UnicodeError, csv.Error) as exc:
        raise ValueError(f"invalid scores.csv: {exc}") from exc
    return records


def _manifest_count(manifest: dict[str, Any], name: str) -> int:
    value = manifest.get(name)
    if type(value) is not int or value < 0:
        raise ValueError(f"invalid manifest {name}")
    return value


_PAIR_OUTCOMES = (
    "baseline_fail_godprompt_pass", "baseline_pass_godprompt_fail",
    "both_pass", "both_fail",
)


def _pair_outcome(baseline_passed: bool, godprompt_passed: bool) -> str:
    if baseline_passed and godprompt_passed:
        return "both_pass"
    if not baseline_passed and not godprompt_passed:
        return "both_fail"
    return "baseline_pass_godprompt_fail" if baseline_passed else "baseline_fail_godprompt_pass"


def _effective_pass(record: SampleRecord) -> bool:
    """Match aggregate's scope-aware definition for imported historical rows."""
    return bool(record.passed and not record.scope_violation)


def _task_cluster_interval(clusters: dict[str, list[int]], *, seed: int) -> list[float]:
    """Resample whole task bundles; repeated epochs are not independent tasks."""
    task_groups = [clusters[key] for key in sorted(clusters)]
    n = len(task_groups)
    rng = Random(seed)
    samples: list[float] = []
    for _ in range(_UNCERTAINTY_RESAMPLES):
        sampled = [task_groups[rng.randrange(n)] for _ in range(n)]
        samples.append(sum(sum(group) for group in sampled) / sum(len(group) for group in sampled))
    samples.sort()

    def percentile(probability: float) -> float:
        position = (len(samples) - 1) * probability
        index = int(position)
        fraction = position - index
        return samples[index] + fraction * (
            samples[min(index + 1, len(samples) - 1)] - samples[index]
        )

    return [percentile(0.025), percentile(0.975)]


def _paired_cluster_uncertainty(
    records: list[SampleRecord], cautions: list[str],
) -> dict[str, Any]:
    """Exploratory paired pass delta, resampling tasks rather than repeated epochs.

    The interval describes variation across observed task clusters only, not
    model-run authenticity, unseen benchmark generalization or causal effect.
    """
    pairs: dict[tuple[str, int], dict[str, SampleRecord]] = {}
    for record in records:
        pairs.setdefault((record.task_id, record.epoch), {})[record.condition] = record
    clusters: dict[str, list[int]] = {}
    excluded = 0
    for (task_id, _), pair in pairs.items():
        baseline, godprompt = pair.get("baseline"), pair.get("godprompt")
        if (baseline is None or godprompt is None
                or baseline.category != godprompt.category
                or baseline.infrastructure_error is not None
                or godprompt.infrastructure_error is not None):
            excluded += 1
            continue
        delta = int(_effective_pass(godprompt)) - int(_effective_pass(baseline))
        clusters.setdefault(task_id, []).append(delta)

    matched = sum(len(values) for values in clusters.values())
    limitations = sorted(set(cautions) & _UNCERTAINTY_DISQUALIFIERS)
    if excluded:
        limitations.append("unpaired_or_infrastructure_failed")
    if len(clusters) < _UNCERTAINTY_MIN_TASKS:
        limitations.append("fewer_than_10_distinct_tasks")

    result: dict[str, Any] = {
        "method": "paired_task_cluster_bootstrap_percentile",
        "confidence_level": 0.95,
        "resamples": 0,
        "matched_task_epochs": matched,
        "excluded_task_epochs": excluded,
        "distinct_tasks": len(clusters),
        "observed_pass_rate_delta": (
            sum(sum(values) for values in clusters.values()) / matched if matched else None
        ),
        "interval_95": None,
        "limitations": limitations,
    }
    if limitations:
        return result

    result["resamples"] = _UNCERTAINTY_RESAMPLES
    result["interval_95"] = _task_cluster_interval(clusters, seed=348)
    return result


def _within_run_condition_pairs(
    records: list[SampleRecord],
) -> dict[str, Any]:
    """Count matched baseline/GodPrompt outcomes, without exposing task IDs."""
    totals = {key: 0 for key in _PAIR_OUTCOMES}
    totals.update(paired_task_epochs=0, unpaired_task_epochs=0)
    by_category = {
        category: {**{key: 0 for key in _PAIR_OUTCOMES}, "paired_task_epochs": 0}
        for category in sorted({record.category for record in records})
    }
    pairs: dict[tuple[str, int], dict[str, SampleRecord]] = {}
    for record in records:
        pairs.setdefault((record.task_id, record.epoch), {})[record.condition] = record
    for pair in pairs.values():
        baseline, godprompt = pair.get("baseline"), pair.get("godprompt")
        if (baseline is None or godprompt is None
                or baseline.category != godprompt.category
                or baseline.infrastructure_error is not None
                or godprompt.infrastructure_error is not None):
            totals["unpaired_task_epochs"] += 1
            continue
        outcome = _pair_outcome(_effective_pass(baseline), _effective_pass(godprompt))
        totals[outcome] += 1
        totals["paired_task_epochs"] += 1
        by_category[baseline.category][outcome] += 1
        by_category[baseline.category]["paired_task_epochs"] += 1
    return {**totals, "by_category": by_category}


def _cross_run_condition_pair_transitions(
    before_samples: dict[tuple[str, str, int], tuple[str, bool, bool]],
    after_samples: dict[tuple[str, str, int], tuple[str, bool, bool]],
) -> dict[str, Any]:
    """Track joint baseline/GodPrompt outcome changes for matching task-epochs.

    Called only after cross-run sample/metadata alignment is established. Export
    counts, never the task identities used for local matching.
    """
    result = {
        "paired_task_epochs": 0,
        "excluded_task_epochs": 0,
        "transitions": {
            earlier: {later: 0 for later in _PAIR_OUTCOMES}
            for earlier in _PAIR_OUTCOMES
        },
    }
    for task_id, epoch in {(task, number) for task, _, number in before_samples}:
        baseline_key = (task_id, "baseline", epoch)
        godprompt_key = (task_id, "godprompt", epoch)
        earlier_baseline = before_samples.get(baseline_key)
        earlier_godprompt = before_samples.get(godprompt_key)
        later_baseline = after_samples.get(baseline_key)
        later_godprompt = after_samples.get(godprompt_key)
        if (earlier_baseline is None or earlier_godprompt is None
                or later_baseline is None or later_godprompt is None
                or earlier_baseline[0] != earlier_godprompt[0]
                or later_baseline[0] != later_godprompt[0]
                or not all(row[1] for row in (
                    earlier_baseline, earlier_godprompt, later_baseline, later_godprompt
                ))):
            result["excluded_task_epochs"] += 1
            continue
        earlier_outcome = _pair_outcome(earlier_baseline[2], earlier_godprompt[2])
        later_outcome = _pair_outcome(later_baseline[2], later_godprompt[2])
        result["transitions"][earlier_outcome][later_outcome] += 1
        result["paired_task_epochs"] += 1
    return result


def _cross_run_paired_cluster_uncertainty(
    before_samples: dict[tuple[str, str, int], tuple[str, bool, bool]],
    after_samples: dict[tuple[str, str, int], tuple[str, bool, bool]],
    before_cautions: list[str],
    after_cautions: list[str],
) -> dict[str, Any]:
    """Exploratory change in the within-task GodPrompt-minus-baseline contrast.

    The caller must establish matching run metadata and scored identities first.
    This is a descriptive paired comparison, not a causal difference-in-differences
    estimate or independent authentication of two benchmark executions.
    """
    clusters: dict[str, list[int]] = {}
    excluded = 0
    task_epochs = {
        (task, epoch) for task, _, epoch in before_samples.keys() | after_samples.keys()
    }
    for task_id, epoch in task_epochs:
        keys = ((task_id, "baseline", epoch), (task_id, "godprompt", epoch))
        rows = (
            before_samples.get(keys[0]), before_samples.get(keys[1]),
            after_samples.get(keys[0]), after_samples.get(keys[1]),
        )
        if (
            any(row is None for row in rows)
            or not all(row[1] for row in rows)
            or len({row[0] for row in rows}) != 1
        ):
            excluded += 1
            continue
        earlier = int(rows[1][2]) - int(rows[0][2])
        later = int(rows[3][2]) - int(rows[2][2])
        clusters.setdefault(task_id, []).append(later - earlier)

    matched = sum(len(values) for values in clusters.values())
    limitations = sorted(
        [f"before:{c}" for c in set(before_cautions) & _UNCERTAINTY_DISQUALIFIERS]
        + [f"after:{c}" for c in set(after_cautions) & _UNCERTAINTY_DISQUALIFIERS]
    )
    if excluded:
        limitations.append("unpaired_or_infrastructure_failed")
    if len(clusters) < _UNCERTAINTY_MIN_TASKS:
        limitations.append("fewer_than_10_distinct_tasks")
    result: dict[str, Any] = {
        "method": "cross_run_paired_task_cluster_bootstrap_percentile",
        "confidence_level": 0.95,
        "resamples": 0,
        "matched_task_epochs": matched,
        "excluded_task_epochs": excluded,
        "distinct_tasks": len(clusters),
        "observed_contrast_change": (
            sum(sum(values) for values in clusters.values()) / matched if matched else None
        ),
        "interval_95": None,
        "limitations": limitations,
    }
    if not limitations:
        result["resamples"] = _UNCERTAINTY_RESAMPLES
        result["interval_95"] = _task_cluster_interval(clusters, seed=349)
    return result


def review_result(
    folder: Path, *, required_plan_sha256: str | None = None,
) -> dict[str, Any]:
    """Validate a saved export and return a compact, non-promotional review."""
    initial_artifact_sha256 = _public_artifact_sha256(folder)
    manifest = _read_json(folder, "manifest.json")
    if required_plan_sha256 is not None:
        if re.fullmatch(r"[0-9a-f]{64}", required_plan_sha256) is None:
            raise ValueError("reviewed plan SHA256 must be 64 lowercase hexadecimal characters")
        if manifest.get("plan_sha256_schema") != "godprompt.bench.plan.v1":
            raise ValueError("saved run has no supported reviewed plan SHA256 schema")
        if manifest.get("plan_sha256") != required_plan_sha256:
            raise ValueError("saved run plan SHA256 does not match the reviewed dry-run plan")
    saved_summary = _read_json(folder, "summary.json")
    records = _read_scores(folder)
    recomputed = aggregate(records)
    if saved_summary != recomputed:
        raise ValueError("summary does not match the exported scores.csv")

    requested = _manifest_count(manifest, "requested_samples")
    completed = _manifest_count(manifest, "completed_samples")
    failures = _manifest_count(manifest, "infrastructure_failures")
    recorded = len(records)
    model_samples = sum(row.infrastructure_error is None for row in records)
    if completed != model_samples:
        raise ValueError("manifest completed_samples differs from scores.csv")
    if failures != recorded - model_samples:
        raise ValueError("manifest infrastructure_failures differs from scores.csv")
    if recorded > requested:
        raise ValueError("recorded samples exceed manifest requested_samples")
    run_id = manifest.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        raise ValueError("invalid manifest run_id")

    profile = manifest.get("profile")
    requested_model = manifest.get("requested_model")
    actual_models = manifest.get("actual_models")
    benchmark_sha = manifest.get("benchmark_commit_sha")
    prompt_sha = manifest.get("godprompt_commit_sha")
    cautions = []
    if profile != "full":
        cautions.append("non_full_profile")
    if requested != recorded or requested == 0:
        cautions.append("incomplete_coverage")
    if not isinstance(requested_model, str) or not requested_model:
        cautions.append("missing_model_identity")
    elif requested_model.startswith("mockllm/"):
        cautions.append("mock_model")
    if not isinstance(actual_models, list) or not actual_models or any(
        not isinstance(name, str) or not name for name in actual_models
    ):
        cautions.append("missing_actual_model_identity")
        actual_models = []
    elif len(set(actual_models)) > 1:
        # A shared model list does not establish which model served each condition.
        cautions.append("mixed_actual_models")
    if any(not isinstance(sha, str) or not _SHA.fullmatch(sha)
           for sha in (benchmark_sha, prompt_sha)):
        cautions.append("incomplete_commit_provenance")
    if manifest.get("working_tree_dirty") is not False:
        cautions.append("unverified_clean_source")

    artifact_sha256 = _public_artifact_sha256(folder)
    if artifact_sha256 != initial_artifact_sha256:
        raise ValueError("public benchmark artifacts changed during offline review")

    return {
        "review_only": True,
        "artifact_consistency": "verified",
        "public_artifact_sha256": artifact_sha256,
        "performance_claim_verified": False,
        **({"reviewed_plan": {
            "plan_sha256": required_plan_sha256,
            "matched_saved_manifest": True,
            "scope": "local_manifest_field_only",
        }} if required_plan_sha256 is not None else {}),
        "run_id": run_id,
        "profile": profile,
        "requested_model": requested_model,
        "actual_models": actual_models,
        "benchmark_commit_sha": benchmark_sha,
        "godprompt_commit_sha": prompt_sha,
        "coverage": {
            "requested_samples": requested,
            "recorded_samples": recorded,
            "model_samples": model_samples,
            "infrastructure_failures": failures,
            "complete": requested > 0 and recorded == requested,
        },
        "conditions": {name: recomputed[name] for name in ("baseline", "godprompt")},
        "by_category": recomputed["by_category"],
        "within_run_condition_pairs": _within_run_condition_pairs(records),
        "paired_pass_uncertainty": _paired_cluster_uncertainty(records, cautions),
        "cautions": cautions,
        "note": "Counts and summaries were checked against local export rows; "
                "this does not independently verify model execution, provenance or a performance claim.",
    }


def compare_results(before_folder: Path, after_folder: Path) -> dict[str, Any]:
    """Compare two independently validated exports, never asserting causal improvement."""
    before = review_result(before_folder)
    after = review_result(after_folder)
    before_manifest = _read_json(before_folder, "manifest.json")
    after_manifest = _read_json(after_folder, "manifest.json")

    # Matching manifest fingerprints alone cannot establish which rows were scored.
    before_samples = {
        (row.task_id, row.condition, row.epoch):
        (row.category, row.infrastructure_error is None, _effective_pass(row))
        for row in _read_scores(before_folder)
    }
    after_samples = {
        (row.task_id, row.condition, row.epoch):
        (row.category, row.infrastructure_error is None, _effective_pass(row))
        for row in _read_scores(after_folder)
    }

    cautions: list[str] = []
    if before["run_id"] == after["run_id"]:
        cautions.append("same_run_id")
    if before_samples.keys() != after_samples.keys() or any(
        before_samples[key][0] != after_samples[key][0]
        for key in before_samples.keys() & after_samples.keys()
    ):
        cautions.append("different:scored_samples")
    elif any(before_samples[key][1] != after_samples[key][1] for key in before_samples):
        cautions.append("different:model_sample_coverage")
    for field in _COMPARISON_FIELDS:
        if field not in before_manifest or field not in after_manifest:
            cautions.append(f"missing:{field}")
        elif before_manifest[field] != after_manifest[field]:
            cautions.append(f"different:{field}")
    for label, report in (("before", before), ("after", after)):
        for caution in report["cautions"]:
            if caution in _COMPARISON_DISQUALIFIERS:
                cautions.append(f"{label}:{caution}")
        if any(report["conditions"][condition]["pass_rate"] is None
               for condition in ("baseline", "godprompt")):
            cautions.append(f"{label}:missing_model_samples")

    aligned = not cautions
    delta = None
    category_delta = None
    resource_delta = None
    pass_transitions = None
    category_pass_transitions = None
    cross_run_pair_transitions = None
    cross_run_paired_uncertainty = None
    if aligned:
        delta = {
            condition: after["conditions"][condition]["pass_rate"]
            - before["conditions"][condition]["pass_rate"]
            for condition in ("baseline", "godprompt")
        }
        category_delta = {}
        for category, before_conditions in before["by_category"].items():
            category_delta[category] = {}
            for condition in ("baseline", "godprompt"):
                earlier = before_conditions[condition]["pass_rate"]
                later = after["by_category"][category][condition]["pass_rate"]
                # A zero model-evaluable denominator has no defined rate to compare.
                category_delta[category][condition] = (
                    later - earlier if earlier is not None and later is not None else None
                )
        resource_delta = {}
        for condition in ("baseline", "godprompt"):
            resource_delta[condition] = {}
            for field in _RESOURCE_FIELDS:
                earlier = before["conditions"][condition][field]
                later = after["conditions"][condition][field]
                # A missing or malformed provider count is not zero usage.
                resource_delta[condition][field] = (
                    later - earlier if type(earlier) is int and type(later) is int else None
                )
        pass_transitions = {
            condition: {"fail_to_pass": 0, "pass_to_fail": 0,
                        "pass_to_pass": 0, "fail_to_fail": 0, "paired_samples": 0}
            for condition in ("baseline", "godprompt")
        }
        category_pass_transitions = {
            category: {
                condition: {"fail_to_pass": 0, "pass_to_fail": 0,
                            "pass_to_pass": 0, "fail_to_fail": 0, "paired_samples": 0}
                for condition in ("baseline", "godprompt")
            }
            for category in before["by_category"]
        }
        for (task_id, condition, epoch), (
            category, model_evaluable, was_passed
        ) in before_samples.items():
            if not model_evaluable:
                continue
            # Alignment above proves the same sample is model-evaluable in both exports.
            # Export only condition/category aggregates, never task IDs or sample content.
            later_passed = after_samples[(task_id, condition, epoch)][2]
            transition = ("pass" if was_passed else "fail") + "_to_" + (
                "pass" if later_passed else "fail"
            )
            pass_transitions[condition][transition] += 1
            pass_transitions[condition]["paired_samples"] += 1
            category_pass_transitions[category][condition][transition] += 1
            category_pass_transitions[category][condition]["paired_samples"] += 1
        cross_run_pair_transitions = _cross_run_condition_pair_transitions(
            before_samples, after_samples
        )
        cross_run_paired_uncertainty = _cross_run_paired_cluster_uncertainty(
            before_samples, after_samples, before["cautions"], after["cautions"]
        )
    return {
        "comparison_only": True,
        "metadata_aligned": aligned,
        "performance_claim_verified": False,
        "before": before,
        "after": after,
        "comparison_cautions": cautions,
        "condition_pass_rate_delta": delta,
        "category_pass_rate_delta": category_delta,
        "condition_resource_delta": resource_delta,
        "condition_pass_transitions": pass_transitions,
        "category_pass_transitions": category_pass_transitions,
        "cross_run_condition_pair_transitions": cross_run_pair_transitions,
        "cross_run_paired_uncertainty": cross_run_paired_uncertainty,
        "note": "Rate differences are descriptive, not a causal effect or verified performance claim. "
                "Metadata alignment does not independently authenticate model runs; "
                "non-full or mock results are not publication evidence.",
    }


def _markdown_text(value: Any) -> str:
    """Keep exported, untrusted labels inert when copied into a Markdown report."""
    # An exported label must not clear a terminal or reverse displayed text.
    clean = escape(_REPORT_CONTROLS.sub(" ", str(value) if value is not None else "unavailable"))
    return re.sub(r"([\\`*\[\]|])", r"\\\1", clean)


def _percent(rate: float | None) -> str:
    return f"{100 * rate:.1f}%" if rate is not None else "n/a"


def _percentage_points(delta: float | None) -> str:
    return f"{100 * delta:+.1f} pp" if delta is not None else "n/a"


def _count_change(delta: int | None) -> str:
    return f"{delta:+d}" if delta is not None else "n/a"


def _markdown_cautions(label: str, cautions: list[str]) -> list[str]:
    return [f"**{label}:** " + (
        ", ".join(_markdown_text(caution) for caution in cautions)
        if cautions else "No local cautions (not independent verification)"
    )]


def _markdown_artifact_hashes(first: dict[str, Any], second: dict[str, Any] | None = None) -> list[str]:
    """Copyable local export digests; not an execution or identity attestation."""
    lines = [
        "**Public file SHA256 (local bytes only; not proof of model execution):**",
        "",
        "| File | " + ("Earlier SHA256 | Later SHA256 |" if second else "SHA256 |"),
        "| --- | " + ("--- | --- |" if second else "--- |"),
    ]
    for name, _ in _PUBLIC_ARTIFACTS:
        digest = first["public_artifact_sha256"][name]
        if second:
            lines.append(f"| {name} | `{digest}` | `{second['public_artifact_sha256'][name]}` |")
        else:
            lines.append(f"| {name} | `{digest}` |")
    return lines


def render_markdown(report: dict[str, Any]) -> str:
    """Create an offline, copyable evidence summary without a performance claim."""
    lines = [
        "# GodPrompt Bench - offline " + ("comparison" if report.get("comparison_only") else "review"),
        "",
        "**Evidence status:** Model execution and provenance are not independently verified; "
        "this is not a performance claim or a causal estimate.",
        "",
    ]
    if report.get("comparison_only"):
        before, after = report["before"], report["after"]
        lines += [
            f"**Earlier run:** {_markdown_text(before['run_id'])}",
            f"**Later run:** {_markdown_text(after['run_id'])}",
            f"**Requested models:** {_markdown_text(before['requested_model'])} / "
            f"{_markdown_text(after['requested_model'])}",
            f"**Benchmark commits:** {_markdown_text(before['benchmark_commit_sha'])} / "
            f"{_markdown_text(after['benchmark_commit_sha'])}",
            f"**GodPrompt commits:** {_markdown_text(before['godprompt_commit_sha'])} / "
            f"{_markdown_text(after['godprompt_commit_sha'])}",
            f"**Comparability:** " + (
                "Aligned local metadata and scored sample identities; not authenticated."
                if report["metadata_aligned"] else "Not comparable; all deltas suppressed."
            ),
            *_markdown_cautions("Comparison cautions", report["comparison_cautions"]),
            *_markdown_cautions("Earlier run cautions", before["cautions"]),
            *_markdown_cautions("Later run cautions", after["cautions"]),
            "", *_markdown_artifact_hashes(before, after), "",
        ]
        if report["metadata_aligned"]:
            lines += [
                "| Condition | Earlier pass rate | Later pass rate | Delta |",
                "| --- | ---: | ---: | ---: |",
            ]
            for condition in ("baseline", "godprompt"):
                lines.append(
                    f"| {condition} | {_percent(before['conditions'][condition]['pass_rate'])} | "
                    f"{_percent(after['conditions'][condition]['pass_rate'])} | "
                    f"{_percentage_points(report['condition_pass_rate_delta'][condition])} |"
                )
            lines += [
                "", "| Category | Baseline delta | GodPrompt delta |",
                "| --- | ---: | ---: |",
            ]
            for category, conditions in sorted(report["category_pass_rate_delta"].items()):
                lines.append(
                    f"| {_markdown_text(category)} | "
                    f"{_percentage_points(conditions['baseline'])} | "
                    f"{_percentage_points(conditions['godprompt'])} |"
                )
            lines += [
                "", "**Paired outcome transitions:** Matching model-evaluable samples only; "
                "descriptive, not a performance claim. No task IDs are displayed.",
                "", "| Condition | Fail to pass | Pass to fail | Pass to pass | "
                "Fail to fail | Paired samples |",
                "| --- | ---: | ---: | ---: | ---: | ---: |",
            ]
            for condition, counts in report["condition_pass_transitions"].items():
                lines.append(
                    f"| {condition} | {counts['fail_to_pass']} | {counts['pass_to_fail']} | "
                    f"{counts['pass_to_pass']} | {counts['fail_to_fail']} | "
                    f"{counts['paired_samples']} |"
                )
            lines += [
                "", "**Per-category paired transitions:** Aggregated by category and condition; "
                "zero paired samples means no model-evaluable comparison.",
                "", "| Category | Condition | Fail to pass | Pass to fail | Pass to pass | "
                "Fail to fail | Paired samples |",
                "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
            ]
            for category, conditions in sorted(report["category_pass_transitions"].items()):
                for condition in ("baseline", "godprompt"):
                    counts = conditions[condition]
                    lines.append(
                        f"| {_markdown_text(category)} | {condition} | "
                        f"{counts['fail_to_pass']} | {counts['pass_to_fail']} | "
                        f"{counts['pass_to_pass']} | {counts['fail_to_fail']} | "
                        f"{counts['paired_samples']} |"
                    )
            pair_changes = report["cross_run_condition_pair_transitions"]
            labels = {
                "baseline_fail_godprompt_pass": "Baseline fail / GodPrompt pass",
                "baseline_pass_godprompt_fail": "Baseline pass / GodPrompt fail",
                "both_pass": "Both pass", "both_fail": "Both fail",
            }
            lines += [
                "", "**Joint baseline/GodPrompt pair transitions:** "
                f"{pair_changes['paired_task_epochs']} matched task-epochs; "
                f"{pair_changes['excluded_task_epochs']} excluded (missing, infrastructure-failed "
                "or mismatched condition pairs). These are descriptive, not causal.",
                "", "| Earlier pair outcome / Later pair outcome | "
                + " | ".join(labels[outcome] for outcome in _PAIR_OUTCOMES) + " |",
                "| --- |" + " ---: |" * len(_PAIR_OUTCOMES),
            ]
            for earlier in _PAIR_OUTCOMES:
                row = pair_changes["transitions"][earlier]
                lines.append(
                    f"| {labels[earlier]} | "
                    + " | ".join(str(row[later]) for later in _PAIR_OUTCOMES) + " |"
                )
            contrast = report["cross_run_paired_uncertainty"]
            bounds = contrast["interval_95"]
            interval_text = (
                f"{_percentage_points(bounds[0])} to {_percentage_points(bounds[1])}"
                if bounds is not None else "n/a (insufficient qualified evidence)"
            )
            lines += [
                "", "**Cross-run paired contrast change (exploratory):** "
                "(later GodPrompt minus baseline) minus (earlier GodPrompt minus baseline) "
                f"= {_percentage_points(contrast['observed_contrast_change'])}; "
                f"95% task-cluster percentile interval {interval_text}.",
                f"Matched {contrast['matched_task_epochs']} task-epochs across "
                f"{contrast['distinct_tasks']} distinct tasks; "
                f"{contrast['excluded_task_epochs']} excluded.",
                "Resampling keeps a task's repeated epochs together. This is descriptive, "
                "not a causal confidence interval or an authenticated model result.",
            ]
            if contrast["limitations"]:
                lines.append("**Cross-run interval limitations:** " + ", ".join(
                    _markdown_text(value) for value in contrast["limitations"]
                ))
            lines += [
                "", "**Observed resource deltas:** Later minus earlier; provider tokens may be "
                "unreported (n/a). No price or efficiency claim is implied.",
                "", "| Condition | Input tokens | Output tokens | Failed tool calls | Retries |",
                "| --- | ---: | ---: | ---: | ---: |",
            ]
            for condition, counts in report["condition_resource_delta"].items():
                lines.append(
                    f"| {condition} | " + " | ".join(
                        _count_change(counts[field]) for field in _RESOURCE_FIELDS
                    ) + " |"
                )
    else:
        if report.get("reviewed_plan"):
            lines.append(
                "**Reviewed plan SHA256:** "
                + report["reviewed_plan"]["plan_sha256"]
                + " (matches local manifest field/schema; not an attestation)"
            )
        lines += [
            f"**Run:** {_markdown_text(report['run_id'])}",
            f"**Profile:** {_markdown_text(report['profile'])}",
            f"**Model requested:** {_markdown_text(report['requested_model'])}",
            f"**Benchmark commit:** {_markdown_text(report['benchmark_commit_sha'])}",
            f"**GodPrompt commit:** {_markdown_text(report['godprompt_commit_sha'])}",
            f"**Coverage:** {report['coverage']['recorded_samples']}/"
            f"{report['coverage']['requested_samples']} recorded, "
            f"{report['coverage']['model_samples']} model-evaluable, "
            f"{report['coverage']['infrastructure_failures']} infrastructure failures.",
            *_markdown_cautions("Cautions", report["cautions"]),
            "", *_markdown_artifact_hashes(report),
            "", "| Condition | Passed / model samples | Pass rate |",
            "| --- | ---: | ---: |",
        ]
        for condition in ("baseline", "godprompt"):
            score = report["conditions"][condition]
            lines.append(
                f"| {condition} | {score['passed']}/{score['model_samples']} | "
                f"{_percent(score['pass_rate'])} |"
            )
        lines += ["", "| Category | Condition | Passed / model samples | Pass rate |",
                  "| --- | --- | ---: | ---: |"]
        for category, conditions in sorted(report["by_category"].items()):
            for condition in ("baseline", "godprompt"):
                score = conditions[condition]
                lines.append(
                    f"| {_markdown_text(category)} | {condition} | "
                    f"{score['passed']}/{score['model_samples']} | {_percent(score['pass_rate'])} |"
                )
        pairs = report["within_run_condition_pairs"]
        lines += [
            "", "**Within-run matched condition outcomes:** Same task and epoch, "
            "both model-evaluable and in the same category. Exclusions include "
            "missing conditions, infrastructure failures or category mismatches; "
            "these counts do not establish a causal improvement.",
            "", "| Baseline fail / GodPrompt pass | Baseline pass / GodPrompt fail | "
            "Both pass | Both fail | Matched task-epochs | Excluded task-epochs |",
            "| ---: | ---: | ---: | ---: | ---: | ---: |",
            f"| {pairs['baseline_fail_godprompt_pass']} | "
            f"{pairs['baseline_pass_godprompt_fail']} | {pairs['both_pass']} | "
            f"{pairs['both_fail']} | {pairs['paired_task_epochs']} | "
            f"{pairs['unpaired_task_epochs']} |",
            "", "| Category | Baseline fail / GodPrompt pass | "
            "Baseline pass / GodPrompt fail | Both pass | Both fail | Matched task-epochs |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
        for category, counts in sorted(pairs["by_category"].items()):
            lines.append(
                f"| {_markdown_text(category)} | "
                f"{counts['baseline_fail_godprompt_pass']} | "
                f"{counts['baseline_pass_godprompt_fail']} | "
                f"{counts['both_pass']} | {counts['both_fail']} | "
                f"{counts['paired_task_epochs']} |"
            )
        uncertainty = report["paired_pass_uncertainty"]
        bounds = uncertainty["interval_95"]
        interval_text = (
            f"{_percentage_points(bounds[0])} to {_percentage_points(bounds[1])}"
            if bounds is not None else "n/a (insufficient comparable evidence)"
        )
        lines += [
            "", "**Task-cluster uncertainty (exploratory):** "
            f"GodPrompt minus baseline {_percentage_points(uncertainty['observed_pass_rate_delta'])}; "
            f"95% percentile interval {interval_text}; "
            f"{uncertainty['distinct_tasks']} distinct task clusters, "
            f"{uncertainty['matched_task_epochs']} matched task-epochs.",
            "The resampling keeps each task's epochs together. It is not a performance claim, "
            "not a causal confidence interval, and cannot authenticate model execution "
            "or establish generalization beyond the observed tasks.",
        ]
        if uncertainty["limitations"]:
            lines.append("**Interval limitations:** " + ", ".join(
                _markdown_text(value) for value in uncertainty["limitations"]
            ))
    lines += ["", "*Local artifact consistency does not authenticate a model run or establish a causal benefit.*"]
    return "\n".join(lines)


def _fully_model_evaluable(report: dict[str, Any]) -> bool:
    coverage = report["coverage"]
    return (
        coverage["complete"]
        and coverage["infrastructure_failures"] == 0
        and coverage["model_samples"] == coverage["requested_samples"]
    )


def _nondegrading_condition_pairs(report: dict[str, Any]) -> bool:
    """Require complete matched evidence and no net baseline-only advantage."""
    if not _fully_model_evaluable(report) or "mixed_actual_models" in report["cautions"]:
        return False
    pairs = report["within_run_condition_pairs"]
    return (
        pairs["paired_task_epochs"] > 0
        and pairs["unpaired_task_epochs"] == 0
        and pairs["baseline_pass_godprompt_fail"]
        <= pairs["baseline_fail_godprompt_pass"]
    )


def _no_net_godprompt_regression_between_runs(report: dict[str, Any]) -> bool:
    """Gate aligned, fully paired exports on net GodPrompt pass transitions."""
    if not report["metadata_aligned"] or not all(
        _fully_model_evaluable(report[name]) for name in ("before", "after")
    ):
        return False
    pairs = report["cross_run_condition_pair_transitions"]
    changes = report["condition_pass_transitions"]["godprompt"]
    return (
        pairs["paired_task_epochs"] > 0
        and pairs["excluded_task_epochs"] == 0
        and changes["paired_samples"] == pairs["paired_task_epochs"]
        and changes["fail_to_pass"] >= changes["pass_to_fail"]
    )


def _no_godprompt_category_regression_between_runs(report: dict[str, Any]) -> bool:
    """Refuse a category-specific loss even when gains elsewhere hide it."""
    if not _no_net_godprompt_regression_between_runs(report):
        return False
    categories = report["category_pass_transitions"]
    paired = report["cross_run_condition_pair_transitions"]["paired_task_epochs"]
    if not categories:
        return False
    changes = [conditions["godprompt"] for conditions in categories.values()]
    return (
        sum(change["paired_samples"] for change in changes) == paired
        and all(
            change["paired_samples"] > 0
            and change["fail_to_pass"] >= change["pass_to_fail"]
            for change in changes
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Review an existing GodPrompt benchmark export offline; never calls a model"
    )
    parser.add_argument("result_dir", type=Path, help="Directory or public-only ZIP containing manifest.json, summary.json and scores.csv")
    parser.add_argument("--compare", type=Path, metavar="OTHER_RESULT_DIR",
                        help="Compare with another saved directory or public-only ZIP, without running a model")
    parser.add_argument("--format", choices=("json", "markdown"), default="json",
                        help="Output format; Markdown is a read-only, non-promotional summary")
    parser.add_argument("--require-aligned", action="store_true",
                        help="With --compare, exit 1 on unaligned results after printing diagnostics")
    parser.add_argument("--require-evaluable", action="store_true",
                        help="Exit 1 unless all requested samples in each reviewed run were model-evaluable")
    parser.add_argument("--require-plan-sha256", metavar="SHA256",
                        help="Require one saved run to match a reviewed offline plan digest")
    parser.add_argument("--require-public-artifact-sha256", action="append",
                        metavar="[SIDE:]NAME=SHA256",
                        help="Pin all public files; with --compare, require before:/after: pins for both runs")
    parser.add_argument("--require-public-zip-sha256", action="append",
                        metavar="[SIDE:]SHA256",
                        help="Pin the entire ZIP from an independent channel; with --compare, require before:/after: ZIP pins")
    parser.add_argument("--require-nondegrading-pairs", action="store_true",
                        help="For one run, exit 1 on missing/unpaired evidence or more baseline-only wins")
    parser.add_argument("--require-no-godprompt-regression", action="store_true",
                        help="With --compare, exit 1 on incomplete/unpaired evidence or net GodPrompt pass loss")
    parser.add_argument("--require-no-godprompt-category-regression", action="store_true",
                        help="With --compare, exit 1 if any category loses net GodPrompt passes or evidence is incomplete")
    args = parser.parse_args()
    if args.require_aligned and args.compare is None:
        parser.error("--require-aligned requires --compare")
    if args.require_plan_sha256 is not None:
        if args.compare is not None:
            parser.error("--require-plan-sha256 reviews one run; omit --compare")
        if re.fullmatch(r"[0-9a-f]{64}", args.require_plan_sha256) is None:
            parser.error("--require-plan-sha256 must be 64 lowercase hexadecimal characters")
    expected_artifact_sha256 = None
    if args.require_public_artifact_sha256:
        comparing = args.compare is not None
        sides = ("before", "after") if comparing else ("single",)
        expected_artifact_sha256 = {side: {} for side in sides}
        names = {name for name, _ in _PUBLIC_ARTIFACTS}
        for pin in args.require_public_artifact_sha256:
            label, separator, digest = pin.partition("=")
            if comparing:
                side, colon, name = label.partition(":")
                if colon != ":" or side not in sides:
                    parser.error("--require-public-artifact-sha256 with --compare requires before:NAME=SHA256 or after:NAME=SHA256")
            else:
                side, name = "single", label
            if (separator != "=" or name not in names
                    or re.fullmatch(r"[0-9a-f]{64}", digest) is None):
                parser.error("--require-public-artifact-sha256 requires [SIDE:]NAME=64-lowercase-hex for a public file")
            if name in expected_artifact_sha256[side]:
                parser.error("--require-public-artifact-sha256 repeats a public file")
            expected_artifact_sha256[side][name] = digest
        if any(set(expected_artifact_sha256[side]) != names for side in sides):
            parser.error("--require-public-artifact-sha256 requires all three public files"
                         + (" for each of before and after with --compare" if comparing else ""))
    expected_zip_sha256 = None
    if args.require_public_zip_sha256:
        comparing = args.compare is not None
        sides = ("before", "after") if comparing else ("single",)
        expected_zip_sha256 = {}
        for pin in args.require_public_zip_sha256:
            if comparing:
                side, colon, digest = pin.partition(":")
                if colon != ":" or side not in sides:
                    parser.error("--require-public-zip-sha256 with --compare requires before:SHA256 and after:SHA256")
            else:
                side, digest = "single", pin
            if re.fullmatch(r"[0-9a-fA-F]{64}", digest) is None:
                parser.error("--require-public-zip-sha256 requires 64 hexadecimal characters")
            if side in expected_zip_sha256:
                parser.error("--require-public-zip-sha256 repeats a ZIP pin")
            expected_zip_sha256[side] = digest.lower()
        if set(expected_zip_sha256) != set(sides):
            parser.error("--require-public-zip-sha256 requires one pin per ZIP"
                         + (" (before: and after:) with --compare" if comparing else ""))
        sources = (args.result_dir, args.compare) if comparing else (args.result_dir,)
        if any(source.suffix.lower() != ".zip" or source.is_dir() for source in sources):
            parser.error("--require-public-zip-sha256 requires ZIP inputs, not directories")
    if args.require_nondegrading_pairs and args.compare is not None:
        parser.error("--require-nondegrading-pairs reviews one run; omit --compare")
    if args.require_no_godprompt_regression and args.compare is None:
        parser.error("--require-no-godprompt-regression requires --compare")
    if args.require_no_godprompt_category_regression and args.compare is None:
        parser.error("--require-no-godprompt-category-regression requires --compare")
    try:
        with ExitStack() as stack:
            zip_sources = ({"before": args.result_dir, "after": args.compare}
                           if args.compare else {"single": args.result_dir})
            zip_digests_before = ({
                side: _public_zip_sha256(source) for side, source in zip_sources.items()
            } if expected_zip_sha256 is not None else None)
            first = _public_zip_directory(args.result_dir, stack)
            second = _public_zip_directory(args.compare, stack) if args.compare else None
            report = (compare_results(first, second) if second is not None
                      else review_result(first, required_plan_sha256=args.require_plan_sha256))
            if zip_digests_before is not None and any(
                _public_zip_sha256(source) != zip_digests_before[side]
                for side, source in zip_sources.items()
            ):
                raise ValueError("public evidence ZIP changed during review")
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    if args.format == "markdown":
        print(render_markdown(report))
    else:
        print(json.dumps(report, indent=2, sort_keys=True, allow_nan=False))
    if expected_artifact_sha256 is not None:
        reviewed = ({"before": report["before"], "after": report["after"]}
                    if args.compare else {"single": report})
        mismatches = [
            f"{side}:{name}" if args.compare else name
            for side, item in reviewed.items()
            for name, _ in _PUBLIC_ARTIFACTS
            if item["public_artifact_sha256"][name] != expected_artifact_sha256[side][name]
        ]
        if mismatches:
            parser.exit(1, "public artifact SHA256 mismatch for: " + ", ".join(mismatches) + "\n")
    if expected_zip_sha256 is not None:
        mismatches = [
            side for side, digest in zip_digests_before.items()
            if digest != expected_zip_sha256[side]
        ]
        if mismatches:
            names = ", ".join(mismatches) if args.compare else "single ZIP"
            parser.exit(1, "public ZIP SHA256 mismatch for: " + names + "\n")
    if args.require_aligned and not report["metadata_aligned"]:
        raise SystemExit(1)
    if args.require_evaluable:
        reviewed = (report["before"], report["after"]) if args.compare else (report,)
        if not all(_fully_model_evaluable(item) for item in reviewed):
            raise SystemExit(1)
    if args.require_nondegrading_pairs and not _nondegrading_condition_pairs(report):
        raise SystemExit(1)
    if args.require_no_godprompt_regression and not _no_net_godprompt_regression_between_runs(report):
        raise SystemExit(1)
    if args.require_no_godprompt_category_regression and not _no_godprompt_category_regression_between_runs(report):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
