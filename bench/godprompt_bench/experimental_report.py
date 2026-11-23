"""Offline, descriptive comparison of host-supplied experimental sample triples.

This does not register an Inspect solver, attest tool-call provenance, validate
model identity, or change the canonical two-condition benchmark/export.
"""
from __future__ import annotations

from typing import Iterable

from .aggregate import _historical_flag, _summarize
from .models import SampleRecord


EXPERIMENTAL_CONDITION = "experimental_mcp_contract"
_CONDITIONS = ("baseline", "godprompt", EXPERIMENTAL_CONDITION)
_COMPLETION_STATUSES = {"complete", "blocked", "error", "timeout", "protocol-invalid"}


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
    cautions = [
        "not_causal", "no_verified_provenance", "no_uncertainty_interval",
        "live_third_arm_not_enabled",
    ]
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
        "cautions": cautions,
    }
