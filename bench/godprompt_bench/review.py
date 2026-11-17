"""Read-only, offline inspection of a completed public benchmark export.

This verifies agreement between public scores, summary and manifest counts.
It is not an attestation of model identity, runner execution or publication quality.
"""

from __future__ import annotations

import argparse
import csv
from html import escape
import json
from dataclasses import fields
from math import isfinite
from pathlib import Path
import re
from typing import Any

from .aggregate import aggregate
from .corpus import _reject_duplicate_json_keys
from .models import SampleRecord


_JSON_MAX_BYTES = 2_000_000
_CSV_MAX_BYTES = 20_000_000
_REPORT_CONTROLS = re.compile(r"[\x00-\x1f\x7f-\x9f\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069\ufeff]")
_SHA = re.compile(r"[0-9a-f]{40}\Z")
_INT = re.compile(r"(?:0|[1-9][0-9]*)\Z")
_NUMERIC = {"epoch", "tool_misuse_count", "verification_attempts", "failed_tool_calls", "retries"}
_OPTIONAL_INT = {"input_tokens", "output_tokens"}
_BOOLEAN = {"passed", "false_completion", "scope_violation"}
_OPTIONAL_TEXT = {"infrastructure_error"}
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
    "missing_actual_model_identity", "incomplete_commit_provenance",
    "unverified_clean_source",
}
_RESOURCE_FIELDS = ("input_tokens", "output_tokens", "failed_tool_calls", "retries")


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


def _within_run_condition_pairs(
    records: list[SampleRecord],
) -> dict[str, Any]:
    """Count matched baseline/GodPrompt outcomes, without exposing task IDs."""
    outcome_keys = (
        "baseline_fail_godprompt_pass", "baseline_pass_godprompt_fail",
        "both_pass", "both_fail",
    )
    totals = {key: 0 for key in outcome_keys}
    totals.update(paired_task_epochs=0, unpaired_task_epochs=0)
    by_category = {
        category: {**{key: 0 for key in outcome_keys}, "paired_task_epochs": 0}
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
        if baseline.passed and godprompt.passed:
            outcome = "both_pass"
        elif not baseline.passed and not godprompt.passed:
            outcome = "both_fail"
        elif baseline.passed:
            outcome = "baseline_pass_godprompt_fail"
        else:
            outcome = "baseline_fail_godprompt_pass"
        totals[outcome] += 1
        totals["paired_task_epochs"] += 1
        by_category[baseline.category][outcome] += 1
        by_category[baseline.category]["paired_task_epochs"] += 1
    return {**totals, "by_category": by_category}


def review_result(folder: Path) -> dict[str, Any]:
    """Validate a saved export and return a compact, non-promotional review."""
    manifest = _read_json(folder, "manifest.json")
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
    if any(not isinstance(sha, str) or not _SHA.fullmatch(sha)
           for sha in (benchmark_sha, prompt_sha)):
        cautions.append("incomplete_commit_provenance")
    if manifest.get("working_tree_dirty") is not False:
        cautions.append("unverified_clean_source")

    return {
        "review_only": True,
        "artifact_consistency": "verified",
        "performance_claim_verified": False,
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
        (row.category, row.infrastructure_error is None, row.passed)
        for row in _read_scores(before_folder)
    }
    after_samples = {
        (row.task_id, row.condition, row.epoch):
        (row.category, row.infrastructure_error is None, row.passed)
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
            "",
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
    lines += ["", "*Local artifact consistency does not authenticate a model run or establish a causal benefit.*"]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Review an existing GodPrompt benchmark export offline; never calls a model"
    )
    parser.add_argument("result_dir", type=Path, help="Directory containing manifest.json, summary.json and scores.csv")
    parser.add_argument("--compare", type=Path, metavar="OTHER_RESULT_DIR",
                        help="Compare with another saved export, without running a model")
    parser.add_argument("--format", choices=("json", "markdown"), default="json",
                        help="Output format; Markdown is a read-only, non-promotional summary")
    args = parser.parse_args()
    try:
        report = compare_results(args.result_dir, args.compare) if args.compare else review_result(args.result_dir)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    if args.format == "markdown":
        print(render_markdown(report))
    else:
        print(json.dumps(report, indent=2, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
