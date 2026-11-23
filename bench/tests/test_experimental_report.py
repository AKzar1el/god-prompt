from dataclasses import replace
import json

import pytest

from godprompt_bench.aggregate import aggregate
from godprompt_bench.experimental_report import summarize_experimental_triplets
from godprompt_bench.models import SampleRecord


def row(condition, *, task="private-task-a", epoch=1, passed=True, infra=None, **overrides):
    record = SampleRecord(
        task_id=task, category="implementation", condition=condition, epoch=epoch,
        passed=passed, completion_status="complete" if infra is None else "error",
        false_completion=not passed, scope_violation=False,
        tool_misuse_count=0, verification_attempts=1, failed_tool_calls=0,
        retries=0, input_tokens=10 if infra is None else None,
        output_tokens=5 if infra is None else None,
        latency_seconds=1.25 if infra is None else None, infrastructure_error=infra,
    )
    return replace(record, **overrides)


THIRD = "experimental_mcp_contract"


def test_matched_triplets_summarize_effective_outcomes_without_raw_identifiers():
    rows = [
        row("baseline", passed=False),
        row("godprompt"),
        row(THIRD),
        row("baseline", task="private-task-b"),
        row("godprompt", task="private-task-b", passed=False),
        row(THIRD, task="private-task-b", scope_violation=True),
    ]
    report = summarize_experimental_triplets(rows)
    assert report["offline_review_only"] is True
    assert report["performance_claim_verified"] is False
    assert report["matched_task_epochs"] == 2
    assert report["excluded_task_epochs"] == 0
    assert report["distinct_tasks"] == 2
    assert report["conditions"]["baseline"]["pass_rate"] == 0.5
    assert report["conditions"]["godprompt"]["pass_rate"] == 0.5
    assert report["conditions"][THIRD]["pass_rate"] == 0.5
    assert report["conditions"][THIRD]["scope_violations"] == 1
    assert report["pass_rate_delta_vs_baseline"] == {"godprompt": 0.0, THIRD: 0.0}
    serialized = json.dumps(report, allow_nan=False)
    assert "private-task" not in serialized
    assert "not_causal" in report["cautions"]


def test_excludes_incomplete_and_infrastructure_failed_task_epochs():
    rows = [
        row("baseline", task="missing"),
        row("godprompt", task="missing"),
        row("baseline", task="infra"),
        row("godprompt", task="infra"),
        row(THIRD, task="infra", infra="private incident with credential"),
        row("baseline", task="good"),
        row("godprompt", task="good"),
        row(THIRD, task="good"),
    ]
    report = summarize_experimental_triplets(rows)
    assert report["matched_task_epochs"] == 1
    assert report["excluded_task_epochs"] == 2
    assert report["conditions"][THIRD]["samples"] == 1
    assert "incomplete_or_infrastructure_failed" in report["cautions"]
    assert "private incident" not in json.dumps(report)


def test_descriptive_delta_uses_only_matched_scope_safe_outcomes():
    rows = [
        row("baseline", passed=False),
        row("godprompt", passed=True),
        row(THIRD, passed=True, scope_violation=True),
        row("baseline", task="private-incomplete", passed=False),
        row("godprompt", task="private-incomplete", passed=True),
    ]
    report = summarize_experimental_triplets(rows)
    assert report["matched_task_epochs"] == 1
    assert report["excluded_task_epochs"] == 1
    assert report["pass_rate_delta_vs_baseline"] == {"godprompt": 1.0, THIRD: 0.0}
    assert report["performance_claim_verified"] is False


def test_no_paired_samples_does_not_invent_zero_rates_or_uplift():
    report = summarize_experimental_triplets([row("baseline"), row("godprompt")])
    assert report["matched_task_epochs"] == 0
    assert report["conditions"]["baseline"]["pass_rate"] is None
    assert report["conditions"][THIRD]["input_tokens"] is None
    assert report["pass_rate_delta_vs_baseline"] == {"godprompt": None, THIRD: None}


def test_missing_usage_remains_unknown_on_matched_triplets():
    rows = [row("baseline"), row("godprompt"), row(THIRD, input_tokens=None)]
    report = summarize_experimental_triplets(rows)
    assert report["conditions"][THIRD]["input_tokens"] is None
    assert report["conditions"][THIRD]["output_tokens"] == 5


def test_epochs_are_matched_separately_but_not_treated_as_independent_tasks():
    rows = [
        row(c, epoch=e)
        for e in (1, 2)
        for c in ("baseline", "godprompt", THIRD)
    ]
    report = summarize_experimental_triplets(rows)
    assert report["matched_task_epochs"] == 2
    assert report["distinct_tasks"] == 1
    assert "no_uncertainty_interval" in report["cautions"]


@pytest.mark.parametrize("condition", ("unexpected", "Baseline", "", None))
def test_unknown_or_malformed_condition_fails_closed(condition):
    with pytest.raises(ValueError, match="condition"):
        summarize_experimental_triplets([row(condition)])


def test_canonical_two_condition_aggregate_remains_unchanged():
    with pytest.raises(ValueError, match="unknown benchmark condition"):
        aggregate([row(THIRD)])


def test_duplicate_identity_is_rejected_without_silently_choosing_last():
    with pytest.raises(ValueError, match="duplicate"):
        summarize_experimental_triplets([row("baseline"), row("baseline")])


def test_inconsistent_category_across_matching_triplet_is_rejected():
    rows = [row("baseline"), row("godprompt", category="debugging"), row(THIRD)]
    with pytest.raises(ValueError, match="category"):
        summarize_experimental_triplets(rows)


@pytest.mark.parametrize("bad", ("yes", 2, float("nan"), None))
def test_malformed_outcome_flag_is_rejected_instead_of_inflating_rates(bad):
    with pytest.raises(ValueError, match="flag"):
        summarize_experimental_triplets([
            row("baseline", passed=bad), row("godprompt"), row(THIRD),
        ])


@pytest.mark.parametrize("bad", ("COMPLETE", " complete ", "success", "", None, 1))
def test_invalid_completion_status_cannot_hide_false_completions(bad):
    # A malformed completion status must not silently undercount false completions.
    with pytest.raises(ValueError, match="completion status"):
        summarize_experimental_triplets([
            row("baseline", passed=False, completion_status=bad),
            row("godprompt"), row(THIRD),
        ])


@pytest.mark.parametrize("status", ("complete", "blocked", "error", "timeout", "protocol-invalid"))
def test_valid_completion_statuses_preserve_false_completion_semantics(status):
    report = summarize_experimental_triplets([
        row("baseline", passed=False, completion_status=status),
        row("godprompt"), row(THIRD),
    ])
    assert report["conditions"]["baseline"]["false_completions"] == int(status == "complete")


@pytest.mark.parametrize("bad", (True, 0, -1, "1"))
def test_invalid_epoch_cannot_create_ambiguous_matching_identity(bad):
    with pytest.raises(ValueError, match="epoch"):
        summarize_experimental_triplets([row("baseline", epoch=bad)])
