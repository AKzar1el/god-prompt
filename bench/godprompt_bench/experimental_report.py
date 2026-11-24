"""Offline, descriptive comparison of host-supplied experimental sample triples.

This does not register an Inspect solver, attest tool-call provenance, validate
model identity, or change the canonical two-condition benchmark/export.
"""
from __future__ import annotations

import argparse
from dataclasses import fields
import json
from pathlib import Path
import sys
from typing import Iterable

from .aggregate import _historical_flag, _summarize
from .models import SampleRecord
from .review import (
    _percentage_points, _percent, _read_scores, _task_cluster_interval,
    _UNCERTAINTY_MIN_TASKS, _UNCERTAINTY_RESAMPLES, _check_file,
    _no_nonfinite, _reject_duplicate_json_keys,
)


EXPERIMENTAL_CONDITION = "experimental_mcp_contract"
_CONDITIONS = ("baseline", "godprompt", EXPERIMENTAL_CONDITION)
_COMPLETION_STATUSES = {"complete", "blocked", "error", "timeout", "protocol-invalid"}
_UNCERTAINTY_MAX_TASKS = 500
_EXPECTED_IDENTITIES_MAX_BYTES = 2_000_000
_EXPECTED_IDENTITIES_MAX_ENTRIES = 10_000


def _read_expected_identities(path: Path) -> set[tuple[str, int]]:
    """Validate a bounded caller-provided plan, without authenticating it."""
    try:
        _check_file(path, _EXPECTED_IDENTITIES_MAX_BYTES)
        data = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_json_keys,
            parse_constant=_no_nonfinite,
        )
    except (OSError, UnicodeError, ValueError) as exc:
        raise ValueError("invalid or unreadable expected identity manifest") from exc
    if (
        type(data) is not dict
        or set(data) != {"schema_version", "task_epochs"}
        or type(data["schema_version"]) is not int
        or data["schema_version"] != 1
        or type(data["task_epochs"]) is not list
        or not 1 <= len(data["task_epochs"]) <= _EXPECTED_IDENTITIES_MAX_ENTRIES
    ):
        raise ValueError("invalid expected identity manifest schema")
    identities: set[tuple[str, int]] = set()
    for entry in data["task_epochs"]:
        if (
            type(entry) is not dict
            or set(entry) != {"task_id", "epoch"}
            or type(entry["task_id"]) is not str
            or not entry["task_id"]
            or type(entry["epoch"]) is not int
            or entry["epoch"] < 1
        ):
            raise ValueError("invalid expected identity manifest entry")
        identity = (entry["task_id"], entry["epoch"])
        if identity in identities:
            raise ValueError("duplicate expected identity")
        identities.add(identity)
    return identities


def summarize_experimental_triplets(records: Iterable[SampleRecord]) -> dict:
    """Compare complete task/epoch triples without exporting task identities.

    A missing arm, infrastructure error or invalid category alignment cannot
    contribute to an apparent paired pass-rate improvement. This is descriptive
    offline analysis only; caller-provided rows are not authenticated evidence.
    """
    groups: dict[tuple[str, int], dict[str, SampleRecord]] = {}
    for record in records:
        if record.condition not in _CONDITIONS or type(record.condition) is not str:
            raise ValueError("unknown experimental benchmark condition")
        if type(record.task_id) is not str or not record.task_id:
            raise ValueError("invalid experimental task identity")
        if type(record.category) is not str or not record.category:
            raise ValueError("invalid experimental task category")
        if type(record.completion_status) is not str or record.completion_status not in _COMPLETION_STATUSES:
            raise ValueError("invalid experimental completion status")
        if type(record.epoch) is not int or record.epoch < 1:
            raise ValueError("invalid experimental task epoch")
        if record.infrastructure_error is None:
            _historical_flag(record.passed, "passed")
            _historical_flag(record.scope_violation, "scope_violation")
        identity = (record.task_id, record.epoch)
        group = groups.setdefault(identity, {})
        if record.condition in group:
            raise ValueError("duplicate experimental sample identity")
        group[record.condition] = record

    aligned = {condition: [] for condition in _CONDITIONS}
    excluded = 0
    distinct_tasks: set[str] = set()
    included_task_ids: list[str] = []
    for (task_id, _epoch), group in groups.items():
        if len({record.category for record in group.values()}) != 1:
            raise ValueError("inconsistent experimental task category")
        if len(group) != len(_CONDITIONS) or any(
            record.infrastructure_error is not None for record in group.values()
        ):
            excluded += 1
            continue
        for condition in _CONDITIONS:
            aligned[condition].append(group[condition])
        distinct_tasks.add(task_id)
        included_task_ids.append(task_id)

    summaries = {condition: _summarize(aligned[condition]) for condition in _CONDITIONS}
    baseline_rate = summaries["baseline"]["pass_rate"]
    deltas = {
        condition: (
            summaries[condition]["pass_rate"] - baseline_rate
            if baseline_rate is not None else None
        )
        for condition in _CONDITIONS[1:]
    }
    scope_safe_passes = {
        condition: [
            _historical_flag(record.passed, "passed")
            and not _historical_flag(record.scope_violation, "scope_violation")
            for record in aligned[condition]
        ]
        for condition in _CONDITIONS
    }
    paired_outcomes = {}
    paired_pass_uncertainty = {}
    for candidate, reference in (
        ("godprompt", "baseline"),
        (EXPERIMENTAL_CONDITION, "baseline"),
        (EXPERIMENTAL_CONDITION, "godprompt"),
    ):
        pairs = list(zip(scope_safe_passes[candidate], scope_safe_passes[reference]))
        paired_outcomes[f"{candidate}_vs_{reference}"] = {
            "matched_task_epochs": len(pairs),
            "both_pass": sum(
                candidate_pass and reference_pass
                for candidate_pass, reference_pass in pairs
            ),
            "candidate_only_pass": sum(
                candidate_pass and not reference_pass
                for candidate_pass, reference_pass in pairs
            ),
            "reference_only_pass": sum(
                not candidate_pass and reference_pass
                for candidate_pass, reference_pass in pairs
            ),
            "neither_pass": sum(
                not candidate_pass and not reference_pass
                for candidate_pass, reference_pass in pairs
            ),
        }
        clusters: dict[str, list[int]] = {}
        for task_id, (candidate_pass, reference_pass) in zip(included_task_ids, pairs):
            clusters.setdefault(task_id, []).append(int(candidate_pass) - int(reference_pass))
        limitations = []
        if excluded:
            limitations.append("incomplete_or_infrastructure_failed")
        if len(clusters) < _UNCERTAINTY_MIN_TASKS:
            limitations.append("fewer_than_10_distinct_tasks")
        if len(clusters) > _UNCERTAINTY_MAX_TASKS:
            limitations.append("more_than_500_distinct_tasks")
        matched = len(pairs)
        paired_pass_uncertainty[f"{candidate}_vs_{reference}"] = {
            "method": "paired_task_cluster_bootstrap_percentile",
            "confidence_level": 0.95,
            "resamples": 0 if limitations else _UNCERTAINTY_RESAMPLES,
            "matched_task_epochs": matched,
            "distinct_tasks": len(clusters),
            "observed_pass_rate_delta": (
                sum(sum(values) for values in clusters.values()) / matched
                if matched else None
            ),
            "interval_95": (
                None if limitations else _task_cluster_interval(clusters, seed=348)
            ),
            "limitations": limitations,
        }
    cautions = [
        "not_causal", "no_verified_provenance", "live_third_arm_not_enabled",
    ]
    if any(value["interval_95"] is None for value in paired_pass_uncertainty.values()):
        cautions.append("no_uncertainty_interval")
    if excluded:
        cautions.append("incomplete_or_infrastructure_failed")

    return {
        "schema_version": 1,
        "offline_review_only": True,
        "performance_claim_verified": False,
        "matched_task_epochs": len(aligned["baseline"]),
        "excluded_task_epochs": excluded,
        "distinct_tasks": len(distinct_tasks),
        "conditions": summaries,
        "pass_rate_delta_vs_baseline": deltas,
        "paired_outcomes": paired_outcomes,
        "paired_pass_uncertainty": paired_pass_uncertainty,
        "cautions": cautions,
    }


def render_markdown(report: dict) -> str:
    """Format only aggregate, fixed-label offline statistics for human review."""
    labels = {
        "baseline": "baseline",
        "godprompt": "godprompt",
        EXPERIMENTAL_CONDITION: "experimental MCP contract",
    }
    lines = [
        "# GodPrompt Bench - experimental offline triplets",
        "",
        "**Evidence status:** Caller-supplied scores are not independently verified; "
        "this is not a causal result, model performance claim or enabled live third arm.",
        "",
        f"**Matched task-epochs:** {report['matched_task_epochs']}",
        f"**Excluded task-epochs:** {report['excluded_task_epochs']}",
        f"**Distinct tasks:** {report['distinct_tasks']}",
    ]
    coverage = report.get("caller_coverage_gate")
    if coverage is not None:
        label = " and ".join(
            name for enabled, name in (
                (coverage["count_matched"], "count"),
                (coverage["exact_identities_matched"], "exact identities"),
            ) if enabled
        )
        lines.append(
            f"**Caller coverage gate:** {label} matched "
            f"({coverage['expected_task_epochs']} task-epochs); provenance not verified."
        )
    lines += [
        "",
        "| Condition | Scope-safe pass rate | Matched samples | Scope violations | False completions |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for condition in _CONDITIONS:
        summary = report["conditions"][condition]
        lines.append(
            f"| {labels[condition]} | {_percent(summary['pass_rate'])} | "
            f"{summary['samples']} | {summary['scope_violations']} | "
            f"{summary['false_completions']} |"
        )
    lines += [
        "",
        "**Paired scope-safe outcomes and exploratory uncertainty:** "
        "Differences are percentage points, not independent proof of improvement.",
        "",
        "| Comparison | Both pass | Candidate only | Reference only | Neither pass | "
        "Observed delta | Exploratory 95% interval |",
        "| --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for candidate, reference in (
        ("godprompt", "baseline"),
        (EXPERIMENTAL_CONDITION, "baseline"),
        (EXPERIMENTAL_CONDITION, "godprompt"),
    ):
        name = f"{candidate}_vs_{reference}"
        counts = report["paired_outcomes"][name]
        uncertainty = report["paired_pass_uncertainty"][name]
        interval = uncertainty["interval_95"]
        interval_label = (
            f"{_percentage_points(interval[0])} to {_percentage_points(interval[1])}"
            if interval is not None
            else "withheld (" + ", ".join(uncertainty["limitations"]) + ")"
        )
        lines.append(
            f"| {labels[candidate]} vs {labels[reference]} | "
            f"{counts['both_pass']} | {counts['candidate_only_pass']} | "
            f"{counts['reference_only_pass']} | {counts['neither_pass']} | "
            f"{_percentage_points(uncertainty['observed_pass_rate_delta'])} | "
            f"{interval_label} |"
        )
    lines += [
        "",
        "Intervals, when present, use a deterministic 2048-resample paired "
        "task-cluster bootstrap. Repeated epochs stay within each task; "
        "excluded or incomplete triples suppress intervals.",
        "",
        "**Cautions:** " + ", ".join(report["cautions"]),
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Read a bounded offline scores.csv and emit aggregate-only output."""
    parser = argparse.ArgumentParser(
        description="Summarize supplied experimental triplets offline; no model calls."
    )
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument(
        "--scores-dir", type=Path,
        help="Directory containing an offline scores.csv with the SampleRecord schema",
    )
    action.add_argument(
        "--print-scores-header", action="store_true",
        help="Print the required CSV header only; no input files are read",
    )
    parser.add_argument(
        "--format", choices=("json", "markdown"),
        help="Report format (default: json); Markdown is a copyable, descriptive offline summary",
    )
    parser.add_argument(
        "--expected-task-epochs", type=int,
        help="Require exactly this many observed task/epoch identities, all with complete triples",
    )
    parser.add_argument(
        "--expected-identities", type=Path,
        help="Caller-provided JSON task/epoch identity plan; require an exact observed match",
    )
    args = parser.parse_args(argv)
    if args.print_scores_header:
        if any(value is not None for value in (
            args.format, args.expected_task_epochs, args.expected_identities,
        )):
            parser.error("--print-scores-header cannot be combined with report options")
        print(",".join(field.name for field in fields(SampleRecord)))
        return 0
    if args.expected_task_epochs is not None and args.expected_task_epochs < 1:
        print("Expected task-epochs must be a positive integer", file=sys.stderr)
        return 2
    try:
        # Reuse the public reviewer's bounded, strict CSV parser only. This does
        # not authenticate rows or invoke the canonical two-arm review workflow.
        records = _read_scores(args.scores_dir)
        report = summarize_experimental_triplets(records)
    except ValueError as exc:
        print(f"Offline scores rejected: {exc}", file=sys.stderr)
        return 2
    except OSError:
        print("Offline scores unavailable or unreadable", file=sys.stderr)
        return 2
    if args.expected_task_epochs is not None:
        observed = report["matched_task_epochs"] + report["excluded_task_epochs"]
        if observed != args.expected_task_epochs or report["excluded_task_epochs"]:
            print(
                "Offline triplet coverage failed: expected task-epochs must match "
                "observed identities, with no incomplete or failed triples "
                f"(expected={args.expected_task_epochs}, observed={observed}, "
                f"excluded={report['excluded_task_epochs']})",
                file=sys.stderr,
            )
            return 2
    if args.expected_identities is not None:
        try:
            expected = _read_expected_identities(args.expected_identities)
        except ValueError:
            print("Invalid or unreadable expected identity manifest", file=sys.stderr)
            return 2
        observed = {(record.task_id, record.epoch) for record in records}
        if expected != observed or report["excluded_task_epochs"]:
            print(
                "Offline triplet identity coverage failed: expected and observed "
                "task-epochs must match with complete, nonfailed triples "
                f"(expected={len(expected)}, observed={len(observed)}, "
                f"missing={len(expected - observed)}, "
                f"unexpected={len(observed - expected)}, "
                f"excluded={report['excluded_task_epochs']})",
                file=sys.stderr,
            )
            return 2
    if args.expected_task_epochs is not None or args.expected_identities is not None:
        # Only record successful caller-requested gates, not sample authenticity.
        report["caller_coverage_gate"] = {
            "count_matched": args.expected_task_epochs is not None,
            "exact_identities_matched": args.expected_identities is not None,
            "expected_task_epochs": report["matched_task_epochs"],
            "provenance_verified": False,
        }
    if args.format == "markdown":
        print(render_markdown(report))
    else:
        print(json.dumps(report, sort_keys=True, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
