import csv
from dataclasses import asdict, fields, replace
import json
from pathlib import Path
import subprocess
import sys

import pytest

from godprompt_bench.aggregate import aggregate
from godprompt_bench.experimental_report import main, summarize_experimental_triplets
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
    assert report["paired_outcomes"]["godprompt_vs_baseline"] == {
        "matched_task_epochs": 2, "both_pass": 2,
        "candidate_only_pass": 0, "reference_only_pass": 0,
        "neither_pass": 0,
    }
    assert "no_uncertainty_interval" in report["cautions"]


def test_paired_outcomes_expose_scope_aware_discordant_counts():
    rows = [
        row("baseline", task="private-a", passed=False),
        row("godprompt", task="private-a"),
        row(THIRD, task="private-a"),
        row("baseline", task="private-b"),
        row("godprompt", task="private-b", passed=False),
        row(THIRD, task="private-b"),
        row("baseline", task="private-c", passed=False),
        row("godprompt", task="private-c", passed=False),
        row(THIRD, task="private-c", passed=False),
        row("baseline", task="private-d"),
        row("godprompt", task="private-d"),
        row(THIRD, task="private-d", scope_violation=True),
        row("baseline", task="private-e"),
        row("godprompt", task="private-e", passed=False),
        row(THIRD, task="private-e", passed=False),
        row("baseline", task="private-excluded"),
        row("godprompt", task="private-excluded"),
    ]
    result = summarize_experimental_triplets(rows)
    assert result["matched_task_epochs"] == 5
    assert result["excluded_task_epochs"] == 1
    assert result["paired_outcomes"] == {
        "godprompt_vs_baseline": {
            "matched_task_epochs": 5, "both_pass": 1,
            "candidate_only_pass": 1, "reference_only_pass": 2,
            "neither_pass": 1,
        },
        "experimental_mcp_contract_vs_baseline": {
            "matched_task_epochs": 5, "both_pass": 1,
            "candidate_only_pass": 1, "reference_only_pass": 2,
            "neither_pass": 1,
        },
        "experimental_mcp_contract_vs_godprompt": {
            "matched_task_epochs": 5, "both_pass": 1,
            "candidate_only_pass": 1, "reference_only_pass": 1,
            "neither_pass": 2,
        },
    }
    for comparison, counts in result["paired_outcomes"].items():
        assert sum(
            value for key, value in counts.items()
            if key != "matched_task_epochs"
        ) == 5
        candidate, reference = comparison.split("_vs_")
        assert (
            counts["candidate_only_pass"] - counts["reference_only_pass"]
        ) / 5 == pytest.approx(
            result["conditions"][candidate]["pass_rate"]
            - result["conditions"][reference]["pass_rate"]
        )
    assert "private-" not in json.dumps(result, allow_nan=False)


def test_paired_outcomes_are_empty_when_no_complete_triplets_exist():
    result = summarize_experimental_triplets([row("baseline"), row("godprompt")])
    assert all(
        counts == {
            "matched_task_epochs": 0, "both_pass": 0,
            "candidate_only_pass": 0, "reference_only_pass": 0,
            "neither_pass": 0,
        }
        for counts in result["paired_outcomes"].values()
    )
    assert len(result["paired_outcomes"]) == 3


def test_paired_uncertainty_is_deterministic_and_clusters_repeated_task_epochs():
    rows = []
    for task in range(10):
        for epoch in (1, 2):
            rows.extend([
                row("baseline", task=f"private-{task}", epoch=epoch,
                    passed=task % 3 == 0),
                row("godprompt", task=f"private-{task}", epoch=epoch,
                    passed=task % 2 == 0),
                row(THIRD, task=f"private-{task}", epoch=epoch,
                    passed=task % 4 != 0),
            ])
    report = summarize_experimental_triplets(rows)
    assert report["matched_task_epochs"] == 20
    assert report["distinct_tasks"] == 10
    assert "no_uncertainty_interval" not in report["cautions"]
    assert report["paired_pass_uncertainty"] == (
        summarize_experimental_triplets(reversed(rows))["paired_pass_uncertainty"]
    )
    for name, result in report["paired_pass_uncertainty"].items():
        assert result["method"] == "paired_task_cluster_bootstrap_percentile"
        assert result["resamples"] == 2048
        assert result["matched_task_epochs"] == 20
        assert result["distinct_tasks"] == 10
        assert result["limitations"] == []
        observed = (
            report["paired_outcomes"][name]["candidate_only_pass"]
            - report["paired_outcomes"][name]["reference_only_pass"]
        ) / 20
        assert result["observed_pass_rate_delta"] == pytest.approx(observed)
        low, high = result["interval_95"]
        assert -1 <= low <= observed <= high <= 1
    assert "private-" not in json.dumps(report, allow_nan=False)


def test_paired_uncertainty_requires_ten_complete_distinct_tasks():
    rows = [
        row(condition, task=f"private-{task}", epoch=epoch)
        for task in range(9)
        for epoch in (1, 2)
        for condition in ("baseline", "godprompt", THIRD)
    ]
    result = summarize_experimental_triplets(rows)
    assert "no_uncertainty_interval" in result["cautions"]
    assert all(
        uncertainty["interval_95"] is None
        and uncertainty["resamples"] == 0
        and uncertainty["distinct_tasks"] == 9
        and "fewer_than_10_distinct_tasks" in uncertainty["limitations"]
        for uncertainty in result["paired_pass_uncertainty"].values()
    )
    rows.extend([
        row("baseline", task="private-10"),
        row("godprompt", task="private-10"),
        row(THIRD, task="private-10"),
        row("baseline", task="private-excluded"),
    ])
    excluded = summarize_experimental_triplets(rows)
    assert excluded["distinct_tasks"] == 10
    assert excluded["excluded_task_epochs"] == 1
    assert all(
        uncertainty["interval_95"] is None
        and "incomplete_or_infrastructure_failed" in uncertainty["limitations"]
        for uncertainty in excluded["paired_pass_uncertainty"].values()
    )


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


def _write_offline_scores(folder, rows):
    path = folder / "scores.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(asdict(rows[0])))
        writer.writeheader()
        writer.writerows(asdict(record) for record in rows)


def _run_offline_report(folder, *extra_args):
    return subprocess.run(
        [
            sys.executable, "-B", "-m", "godprompt_bench.experimental_report",
            "--scores-dir", str(folder),
            *extra_args,
        ],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True, text=True, check=False,
    )


def test_offline_triplet_cli_reports_pairs_without_private_source_rows(tmp_path):
    rows = [
        row("baseline", task="private-customer-task", passed=False),
        row("godprompt", task="private-customer-task"),
        row(THIRD, task="private-customer-task"),
        row("baseline", task="private-incident-task"),
        row("godprompt", task="private-incident-task"),
        row(THIRD, task="private-incident-task", infra="secret credential in log"),
    ]
    _write_offline_scores(tmp_path, rows)
    result = _run_offline_report(tmp_path)
    assert result.returncode == 0, result.stderr
    parsed = json.loads(result.stdout)
    assert parsed["offline_review_only"] is True
    assert parsed["performance_claim_verified"] is False
    assert parsed["matched_task_epochs"] == 1
    assert parsed["excluded_task_epochs"] == 1
    assert parsed["paired_outcomes"]["godprompt_vs_baseline"]["candidate_only_pass"] == 1
    assert "private-" not in result.stdout
    assert "credential" not in result.stdout
    assert list(tmp_path.iterdir()) == [tmp_path / "scores.csv"]


def test_offline_triplet_markdown_cli_is_copyable_and_redacted(tmp_path):
    rows = [
        row("baseline", task="private-customer-task", passed=False),
        row("godprompt", task="private-customer-task"),
        row(THIRD, task="private-customer-task"),
        row("baseline", task="private-incident-task"),
        row("godprompt", task="private-incident-task"),
        row(THIRD, task="private-incident-task", infra="private credential leak"),
    ]
    _write_offline_scores(tmp_path, rows)
    result = _run_offline_report(tmp_path, "--format", "markdown")
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert "# GodPrompt Bench - experimental offline triplets" in result.stdout
    assert "| baseline | 0.0% | 1 |" in result.stdout
    assert "| godprompt | 100.0% | 1 |" in result.stdout
    assert "| godprompt vs baseline |" in result.stdout
    assert "**Matched task-epochs:** 1" in result.stdout
    assert "**Excluded task-epochs:** 1" in result.stdout
    assert "withheld" in result.stdout
    assert "not independently verified" in result.stdout
    assert "private-" not in result.stdout
    assert "credential" not in result.stdout
    assert list(tmp_path.iterdir()) == [tmp_path / "scores.csv"]


def test_offline_triplet_markdown_cli_displays_exploratory_intervals(tmp_path):
    rows = []
    for task in range(10):
        rows.extend([
            row("baseline", task=f"private-{task}", passed=task % 3 == 0),
            row("godprompt", task=f"private-{task}", passed=task % 2 == 0),
            row(THIRD, task=f"private-{task}", passed=task % 4 != 0),
        ])
    _write_offline_scores(tmp_path, rows)
    result = _run_offline_report(tmp_path, "--format", "markdown")
    assert result.returncode == 0, result.stderr
    assert "**Matched task-epochs:** 10" in result.stdout
    assert "95% interval" in result.stdout
    assert "paired task-cluster bootstrap" in result.stdout
    assert "withheld" not in result.stdout
    assert "private-" not in result.stdout
    assert "not independently verified" in result.stdout


def test_offline_triplet_cli_rejects_duplicate_rows_without_echoing_them(tmp_path):
    _write_offline_scores(tmp_path, [
        row("baseline", task="private-credential-task"),
        row("baseline", task="private-credential-task"),
        row("godprompt", task="private-credential-task"),
        row(THIRD, task="private-credential-task"),
    ])
    result = _run_offline_report(tmp_path)
    assert result.returncode == 2
    assert not result.stdout
    assert "duplicate" in result.stderr.lower()
    assert "private-credential-task" not in result.stderr


def test_offline_triplet_cli_expected_coverage_accepts_only_exact_complete_triples(tmp_path):
    rows = [
        row(condition, task=task)
        for task in ("private-one", "private-two")
        for condition in ("baseline", "godprompt", THIRD)
    ]
    _write_offline_scores(tmp_path, rows)
    good = _run_offline_report(tmp_path, "--expected-task-epochs", "2")
    assert good.returncode == 0, good.stderr
    assert json.loads(good.stdout)["matched_task_epochs"] == 2

    missing = _run_offline_report(tmp_path, "--expected-task-epochs", "3")
    assert missing.returncode == 2
    assert not missing.stdout
    assert "coverage" in missing.stderr.lower()
    assert "private-" not in missing.stderr


def test_offline_triplet_cli_expected_coverage_rejects_exclusions_and_bad_bounds(tmp_path):
    rows = [
        row(condition, task="private-complete")
        for condition in ("baseline", "godprompt", THIRD)
    ] + [
        row("baseline", task="private-incomplete"),
        row("godprompt", task="private-incomplete"),
    ]
    _write_offline_scores(tmp_path, rows)
    excluded = _run_offline_report(tmp_path, "--expected-task-epochs", "2", "--format", "markdown")
    assert excluded.returncode == 2
    assert not excluded.stdout
    assert "coverage" in excluded.stderr.lower()
    assert "private-" not in excluded.stderr
    for invalid in ("0", "-1"):
        rejected = _run_offline_report(tmp_path, "--expected-task-epochs", invalid)
        assert rejected.returncode == 2
        assert not rejected.stdout


def test_offline_triplet_manifest_rejects_same_count_identity_substitution(tmp_path):
    _write_offline_scores(tmp_path, [
        row(condition, task="private-substituted")
        for condition in ("baseline", "godprompt", THIRD)
    ])
    manifest = tmp_path / "expected.json"
    manifest.write_text(json.dumps({
        "schema_version": 1,
        "task_epochs": [{"task_id": "private-planned", "epoch": 1}],
    }), encoding="utf-8")
    count_only = _run_offline_report(tmp_path, "--expected-task-epochs", "1")
    assert count_only.returncode == 0, count_only.stderr
    gated = _run_offline_report(tmp_path, "--expected-identities", str(manifest))
    assert gated.returncode == 2
    assert not gated.stdout
    assert "identity" in gated.stderr.lower() or "coverage" in gated.stderr.lower()
    assert "private-" not in gated.stderr


def test_offline_triplet_manifest_mismatch_reports_only_aggregate_coverage(tmp_path):
    _write_offline_scores(tmp_path, [
        row(condition, task=task)
        for task in ("private-present", "private-unexpected")
        for condition in ("baseline", "godprompt", THIRD)
    ])
    manifest = tmp_path / "private-plan.json"
    manifest.write_text(json.dumps({
        "schema_version": 1,
        "task_epochs": [
            {"task_id": "private-present", "epoch": 1},
            {"task_id": "private-missing", "epoch": 1},
        ],
    }), encoding="utf-8")
    result = _run_offline_report(tmp_path, "--expected-identities", str(manifest))
    assert result.returncode == 2
    assert not result.stdout
    assert "expected=2" in result.stderr
    assert "observed=2" in result.stderr
    assert "missing=1" in result.stderr
    assert "unexpected=1" in result.stderr
    assert "excluded=0" in result.stderr
    assert "private-" not in result.stderr


def test_offline_triplet_manifest_incomplete_reports_exclusion_count(tmp_path):
    _write_offline_scores(tmp_path, [
        row(condition, task="private-complete")
        for condition in ("baseline", "godprompt", THIRD)
    ] + [
        row("baseline", task="private-incomplete"),
        row("godprompt", task="private-incomplete"),
    ])
    manifest = tmp_path / "private-plan.json"
    manifest.write_text(json.dumps({
        "schema_version": 1,
        "task_epochs": [
            {"task_id": "private-complete", "epoch": 1},
            {"task_id": "private-incomplete", "epoch": 1},
        ],
    }), encoding="utf-8")
    result = _run_offline_report(tmp_path, "--expected-identities", str(manifest))
    assert result.returncode == 2
    assert not result.stdout
    assert "missing=0" in result.stderr
    assert "unexpected=0" in result.stderr
    assert "excluded=1" in result.stderr
    assert "private-" not in result.stderr


def test_offline_triplet_count_gate_reports_safe_counts(tmp_path):
    _write_offline_scores(tmp_path, [
        row(condition, task="private-a")
        for condition in ("baseline", "godprompt", THIRD)
    ])
    result = _run_offline_report(tmp_path, "--expected-task-epochs", "2")
    assert result.returncode == 2
    assert not result.stdout
    assert "expected=2" in result.stderr
    assert "observed=1" in result.stderr
    assert "excluded=0" in result.stderr
    assert "private-" not in result.stderr


def test_offline_triplet_manifest_accepts_exact_epochs_and_conflicting_count_fails(tmp_path):
    rows = [
        row(condition, task=task, epoch=epoch)
        for task, epoch in (("private-a", 2), ("private-b", 1))
        for condition in ("baseline", "godprompt", THIRD)
    ]
    _write_offline_scores(tmp_path, rows)
    manifest = tmp_path / "expected.json"
    manifest.write_text(json.dumps({
        "schema_version": 1,
        "task_epochs": [
            {"task_id": "private-b", "epoch": 1},
            {"task_id": "private-a", "epoch": 2},
        ],
    }), encoding="utf-8")
    passed = _run_offline_report(
        tmp_path, "--expected-identities", str(manifest),
        "--expected-task-epochs", "2", "--format", "markdown",
    )
    assert passed.returncode == 0, passed.stderr
    assert "**Matched task-epochs:** 2" in passed.stdout
    assert "private-" not in passed.stdout
    refused = _run_offline_report(
        tmp_path, "--expected-identities", str(manifest),
        "--expected-task-epochs", "3",
    )
    assert refused.returncode == 2
    assert not refused.stdout


@pytest.mark.parametrize("manifest_data", (
    {"schema_version": 1, "task_epochs": []},
    {"schema_version": True, "task_epochs": [{"task_id": "x", "epoch": 1}]},
    {"schema_version": 1, "task_epochs": [{"task_id": "x", "epoch": True}]},
    {"schema_version": 1, "task_epochs": [{"task_id": "x", "epoch": 1}] * 2},
    {"schema_version": 1, "task_epochs": [{"task_id": "x", "epoch": 1, "extra": "x"}]},
))
def test_offline_triplet_manifest_rejects_invalid_schema_without_leak(tmp_path, manifest_data):
    _write_offline_scores(tmp_path, [
        row(condition) for condition in ("baseline", "godprompt", THIRD)
    ])
    manifest = tmp_path / "private-expected.json"
    manifest.write_text(json.dumps(manifest_data), encoding="utf-8")
    result = _run_offline_report(tmp_path, "--expected-identities", str(manifest))
    assert result.returncode == 2
    assert not result.stdout
    assert "private-" not in result.stderr


def test_offline_triplet_manifest_rejects_missing_and_duplicate_json_keys(tmp_path):
    _write_offline_scores(tmp_path, [
        row(condition) for condition in ("baseline", "godprompt", THIRD)
    ])
    missing = _run_offline_report(
        tmp_path, "--expected-identities", str(tmp_path / "secret-missing.json"),
    )
    assert missing.returncode == 2
    assert not missing.stdout
    assert "secret-" not in missing.stderr
    manifest = tmp_path / "private.json"
    manifest.write_text(
        '{"schema_version":1,"task_epochs":[{"task_id":"x","epoch":1,"epoch":2}]}',
        encoding="utf-8",
    )
    duplicate = _run_offline_report(tmp_path, "--expected-identities", str(manifest))
    assert duplicate.returncode == 2
    assert not duplicate.stdout
    assert "private" not in duplicate.stderr


def test_offline_triplet_cli_rejects_missing_input_without_writes(tmp_path):
    result = _run_offline_report(tmp_path)
    assert result.returncode == 2
    assert not result.stdout
    assert not list(tmp_path.iterdir())


def test_print_scores_header_without_input(monkeypatch, capsys):
    def refuse_read(*args):
        pytest.fail("Schema discovery must not read scores")

    monkeypatch.setattr("godprompt_bench.experimental_report._read_scores", refuse_read)
    assert main(["--print-scores-header"]) == 0
    captured = capsys.readouterr()
    assert list(csv.reader(captured.out.splitlines())) == [
        [field.name for field in fields(SampleRecord)]
    ]
    assert not captured.err


@pytest.mark.parametrize("extra_args", [
    ["--scores-dir", "unused"],
    ["--format", "markdown"],
    ["--format", "json"],
    ["--expected-task-epochs", "1"],
    ["--expected-identities", "unused.json"],
])
def test_print_scores_header_rejects_report_options(extra_args, capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--print-scores-header", *extra_args])
    assert exc.value.code == 2
    captured = capsys.readouterr()
    assert not captured.out
    assert "--print-scores-header" in captured.err
