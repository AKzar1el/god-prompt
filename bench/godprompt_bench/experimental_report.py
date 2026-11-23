"""Offline, descriptive comparison of host-supplied experimental sample triples.

This does not register an Inspect solver, attest tool-call provenance, validate
model identity, or change the canonical two-condition benchmark/export.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Iterable

from .aggregate import _historical_flag, _summarize
from .models import SampleRecord
from .review import (
    _percentage_points, _percent, _read_scores, _task_cluster_interval,
    _UNCERTAINTY_MIN_TASKS, _UNCERTAINTY_RESAMPLES,
)


EXPERIMENTAL_CONDITION = "experimental_mcp_contract"
_CONDITIONS = ("baseline", "godprompt", EXPERIMENTAL_CONDITION)
_COMPLETION_STATUSES = {"complete", "blocked", "error", "timeout", "protocol-invalid"}
_UNCERTAINTY_MAX_TASKS = 500


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
    parser.add_argument(
        "--scores-dir", type=Path, required=True,
        help="Directory containing an offline scores.csv with the SampleRecord schema",
    )
    parser.add_argument(
        "--format", choices=("json", "markdown"), default="json",
        help="Output format; Markdown is a copyable, descriptive offline summary",
    )
    args = parser.parse_args(argv)
    try:
        # Reuse the public reviewer's bounded, strict CSV parser only. This does
        # not authenticate rows or invoke the canonical two-arm review workflow.
        report = summarize_experimental_triplets(_read_scores(args.scores_dir))
    except ValueError as exc:
        print(f"Offline scores rejected: {exc}", file=sys.stderr)
        return 2
    except OSError:
        print("Offline scores unavailable or unreadable", file=sys.stderr)
        return 2
    if args.format == "markdown":
        print(render_markdown(report))
    else:
        print(json.dumps(report, sort_keys=True, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
