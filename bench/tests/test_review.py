from __future__ import annotations

import csv
import hashlib
import json
import os
import sys
from dataclasses import replace
from pathlib import Path
from stat import S_IFLNK
from tempfile import TemporaryDirectory
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

import pytest

from godprompt_bench.export import export_run
from godprompt_bench.models import SampleRecord


def record(condition: str, *, passed: bool = True, infra: str | None = None) -> SampleRecord:
    return SampleRecord(
        task_id="impl-example", category="implementation", condition=condition, epoch=1,
        passed=passed, completion_status="complete" if infra is None else "error",
        false_completion=not passed, scope_violation=False,
        tool_misuse_count=0, verification_attempts=1, failed_tool_calls=0, retries=0,
        input_tokens=10 if infra is None else None,
        output_tokens=5 if infra is None else None,
        latency_seconds=1.25 if infra is None else None,
        infrastructure_error=infra,
    )


@pytest.fixture
def exported(tmp_path: Path) -> Path:
    folder = tmp_path / "sample-run"
    manifest = {
        "run_id": "sample-run", "profile": "full",
        "requested_model": "mockllm/test", "actual_models": ["mockllm/test"],
        "requested_samples": 3, "completed_samples": 2, "infrastructure_failures": 1,
        "benchmark_commit_sha": "a" * 40, "godprompt_commit_sha": "b" * 40,
        "working_tree_dirty": False,
    }
    export_run(folder, manifest, [
        record("baseline"), record("godprompt", passed=False),
        replace(record("godprompt", infra="sandbox unavailable"), epoch=2),
    ], [])
    return folder


def test_review_verifies_exported_scores_and_preserves_denominators(exported: Path):
    from godprompt_bench.review import review_result

    report = review_result(exported)
    assert report["review_only"] is True
    assert report["artifact_consistency"] == "verified"
    assert report["public_artifact_sha256"] == {
        name: hashlib.sha256((exported / name).read_bytes()).hexdigest()
        for name in ("manifest.json", "summary.json", "scores.csv")
    }
    assert report["run_id"] == "sample-run"
    assert report["actual_models"] == ["mockllm/test"]
    assert report["coverage"] == {
        "requested_samples": 3, "recorded_samples": 3, "model_samples": 2,
        "infrastructure_failures": 1, "complete": True,
    }
    assert report["conditions"]["baseline"]["pass_rate"] == 1.0
    assert report["conditions"]["godprompt"]["pass_rate"] == 0.0
    assert report["conditions"]["godprompt"]["model_samples"] == 1
    assert report["conditions"]["godprompt"]["infrastructure_failures"] == 1
    assert "mock_model" in report["cautions"]
    assert report["performance_claim_verified"] is False
    assert report["within_run_condition_pairs"] == {
        "baseline_fail_godprompt_pass": 0,
        "baseline_pass_godprompt_fail": 1,
        "both_pass": 0,
        "both_fail": 0,
        "paired_task_epochs": 1,
        "unpaired_task_epochs": 1,
        "by_category": {
            "implementation": {
                "baseline_fail_godprompt_pass": 0,
                "baseline_pass_godprompt_fail": 1,
                "both_pass": 0,
                "both_fail": 0,
                "paired_task_epochs": 1,
            },
        },
    }


@pytest.mark.parametrize(("keys", "value"), [
    (("baseline", "samples"), True),
    (("godprompt", "passed"), False),
    (("baseline", "pass_rate"), True),
    (("by_category", "implementation", "baseline", "pass_rate"), True),
    (("baseline", "tool_misuse_count"), False),
])
def test_review_rejects_boolean_summary_numbers(exported: Path, keys, value):
    from godprompt_bench.review import review_result

    path = exported / "summary.json"
    summary = json.loads(path.read_text(encoding="utf-8"))
    parent = summary
    for key in keys[:-1]:
        parent = parent[key]
    assert type(parent[keys[-1]]) in (int, float)
    assert parent[keys[-1]] == value
    parent[keys[-1]] = value
    path.write_text(json.dumps(summary), encoding="utf-8")
    with pytest.raises(ValueError, match="summary does not match"):
        review_result(exported)


def test_review_accepts_equivalent_json_numeric_representations(exported: Path):
    from godprompt_bench.review import review_result

    original = review_result(exported)
    path = exported / "summary.json"
    summary = json.loads(path.read_text(encoding="utf-8"))
    summary["baseline"]["samples"] = 1.0
    summary["baseline"]["pass_rate"] = 1
    path.write_text(json.dumps(summary), encoding="utf-8")
    revised = review_result(exported)
    assert revised["artifact_consistency"] == "verified"
    assert revised["public_artifact_sha256"] != original["public_artifact_sha256"]
    del revised["public_artifact_sha256"], original["public_artifact_sha256"]
    assert revised == original


def test_review_flags_mixed_actual_models_as_unverified_comparison(exported: Path):
    from godprompt_bench.review import review_result

    path = exported / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["actual_models"] = ["provider/model-a", "provider/model-b"]
    path.write_text(json.dumps(manifest), encoding="utf-8")

    report = review_result(exported)
    assert report["actual_models"] == ["provider/model-a", "provider/model-b"]
    assert "mixed_actual_models" in report["cautions"]
    assert report["performance_claim_verified"] is False


def test_review_pairs_conditions_without_leaking_task_ids_or_counting_infra(
    exported: Path, tmp_path: Path,
):
    from godprompt_bench.review import render_markdown, review_result

    rows = [
        replace(record("baseline", passed=False), task_id="private-a"),
        replace(record("godprompt"), task_id="private-a"),
        replace(record("baseline"), task_id="private-b"),
        replace(record("godprompt", passed=False), task_id="private-b"),
        replace(record("baseline"), task_id="private-c", category="verification"),
        replace(record("godprompt"), task_id="private-c", category="verification"),
        replace(record("baseline", passed=False), task_id="private-d", category="verification"),
        replace(record("godprompt", passed=False), task_id="private-d", category="verification"),
        replace(record("baseline"), task_id="private-infra"),
        replace(record("godprompt", infra="sandbox unavailable"), task_id="private-infra"),
        replace(record("baseline"), task_id="private-missing"),
        replace(record("baseline"), task_id="private-category"),
        replace(record("godprompt"), task_id="private-category", category="verification"),
    ]
    manifest = json.loads((exported / "manifest.json").read_text(encoding="utf-8"))
    manifest.update(run_id="mixed-pairs", requested_samples=len(rows),
                    completed_samples=len(rows) - 1, infrastructure_failures=1)
    folder = tmp_path / "mixed-pairs"
    export_run(folder, manifest, rows, [])

    report = review_result(folder)
    pairs = report["within_run_condition_pairs"]
    assert {key: pairs[key] for key in (
        "baseline_fail_godprompt_pass", "baseline_pass_godprompt_fail",
        "both_pass", "both_fail", "paired_task_epochs", "unpaired_task_epochs",
    )} == {
        "baseline_fail_godprompt_pass": 1,
        "baseline_pass_godprompt_fail": 1,
        "both_pass": 1,
        "both_fail": 1,
        "paired_task_epochs": 4,
        "unpaired_task_epochs": 3,
    }
    assert pairs["by_category"]["implementation"]["paired_task_epochs"] == 2
    assert pairs["by_category"]["verification"]["paired_task_epochs"] == 2
    markdown = render_markdown(report)
    assert "Within-run matched condition outcomes" in markdown
    assert "1 | 1 | 1 | 1 | 4 | 3" in markdown
    assert "private-" not in markdown
    assert "not a performance claim" in markdown.lower()


def test_paired_cluster_bootstrap_is_deterministic_and_keeps_epochs_together():
    from godprompt_bench.review import _paired_cluster_uncertainty

    rows = []
    for task in range(12):
        for epoch in (1, 2, 3):
            rows.extend([
                replace(record("baseline", passed=task >= 8),
                        task_id=f"private-task-{task}", epoch=epoch),
                replace(record("godprompt", passed=task < 8),
                        task_id=f"private-task-{task}", epoch=epoch),
            ])
    report = _paired_cluster_uncertainty(rows, [])
    single_epoch = [row for row in rows if row.epoch == 1]
    once = _paired_cluster_uncertainty(single_epoch, [])
    assert report["method"] == "paired_task_cluster_bootstrap_percentile"
    assert report["confidence_level"] == 0.95
    assert report["resamples"] == 2048
    assert report["matched_task_epochs"] == 36
    assert report["distinct_tasks"] == 12
    assert report["observed_pass_rate_delta"] == pytest.approx(1 / 3)
    assert report["interval_95"] == once["interval_95"]
    assert report["interval_95"] == _paired_cluster_uncertainty(list(reversed(rows)), [])["interval_95"]
    assert report["interval_95"][0] <= 1 / 3 <= report["interval_95"][1]
    assert "private-task" not in json.dumps(report)


def test_paired_cluster_uncertainty_fails_closed_for_small_mock_or_missing_pairs():
    from godprompt_bench.review import _paired_cluster_uncertainty

    rows = [replace(record(condition), task_id=f"private-{i}")
            for i in range(12) for condition in ("baseline", "godprompt")]
    small = _paired_cluster_uncertainty(rows[:12], [])
    assert small["interval_95"] is None
    assert "fewer_than_10_distinct_tasks" in small["limitations"]
    mock = _paired_cluster_uncertainty(rows, ["mock_model"])
    assert mock["interval_95"] is None
    assert "mock_model" in mock["limitations"]
    missing = _paired_cluster_uncertainty(rows[:-1], [])
    assert missing["matched_task_epochs"] == 11
    assert missing["excluded_task_epochs"] == 1
    assert missing["interval_95"] is None
    assert "unpaired_or_infrastructure_failed" in missing["limitations"]


def test_cross_run_paired_contrast_uncertainty_keeps_task_epochs_together():
    from godprompt_bench.review import _cross_run_paired_cluster_uncertainty

    before, after = {}, {}
    for task in range(12):
        for epoch in (1, 2, 3):
            for condition in ("baseline", "godprompt"):
                key = (f"private-task-{task}", condition, epoch)
                before[key] = ("implementation", True, False)
                after[key] = ("implementation", True,
                              task < 8 if condition == "godprompt" else task >= 8)
    report = _cross_run_paired_cluster_uncertainty(before, after, [], [])
    once = _cross_run_paired_cluster_uncertainty(
        {key: value for key, value in before.items() if key[2] == 1},
        {key: value for key, value in after.items() if key[2] == 1}, [], [],
    )
    assert report["method"] == "cross_run_paired_task_cluster_bootstrap_percentile"
    assert report["resamples"] == 2048
    assert report["matched_task_epochs"] == 36
    assert report["distinct_tasks"] == 12
    assert report["observed_contrast_change"] == pytest.approx(1 / 3)
    assert report["interval_95"] == once["interval_95"]
    assert report["interval_95"][0] <= 1 / 3 <= report["interval_95"][1]
    assert "private-task" not in json.dumps(report)


def test_cross_run_paired_contrast_interval_suppresses_unqualified_evidence():
    from godprompt_bench.review import _cross_run_paired_cluster_uncertainty

    before = {(f"private-{task}", condition, 1): ("implementation", True, True)
              for task in range(12) for condition in ("baseline", "godprompt")}
    after = dict(before)
    mock = _cross_run_paired_cluster_uncertainty(before, after, ["mock_model"], [])
    assert mock["interval_95"] is None
    assert "before:mock_model" in mock["limitations"]
    after.pop(("private-11", "godprompt", 1))
    missing = _cross_run_paired_cluster_uncertainty(before, after, [], [])
    assert missing["excluded_task_epochs"] == 1
    assert missing["interval_95"] is None
    assert "unpaired_or_infrastructure_failed" in missing["limitations"]
    small_tasks = {f"private-{task}" for task in range(8)}
    small = _cross_run_paired_cluster_uncertainty(
        {key: value for key, value in before.items() if key[0] in small_tasks},
        {key: value for key, value in before.items() if key[0] in small_tasks}, [], [],
    )
    assert small["interval_95"] is None
    assert "fewer_than_10_distinct_tasks" in small["limitations"]


def test_paired_outcomes_use_scope_aware_passes_for_historical_exports(tmp_path: Path):
    from godprompt_bench.review import review_result

    rows = [
        replace(record("baseline"), scope_violation=True),
        replace(record("godprompt"), scope_violation=False),
    ]
    folder = tmp_path / "scope-aware-pairs"
    manifest = {
        "run_id": "scope-aware-pairs", "profile": "smoke",
        "requested_model": "mockllm/test", "actual_models": ["mockllm/test"],
        "requested_samples": 2, "completed_samples": 2, "infrastructure_failures": 0,
        "benchmark_commit_sha": "a" * 40, "godprompt_commit_sha": "b" * 40,
        "working_tree_dirty": False,
    }
    export_run(folder, manifest, rows, [])
    report = review_result(folder)
    assert report["conditions"]["baseline"]["passed"] == 0
    assert report["conditions"]["godprompt"]["passed"] == 1
    assert report["within_run_condition_pairs"]["baseline_fail_godprompt_pass"] == 1
    assert report["paired_pass_uncertainty"]["observed_pass_rate_delta"] == 1.0


def test_review_renders_conservative_uncertainty_not_a_performance_claim(exported: Path):
    from godprompt_bench.review import review_result, render_markdown

    report = review_result(exported)
    uncertainty = report["paired_pass_uncertainty"]
    assert uncertainty["observed_pass_rate_delta"] == -1.0
    assert uncertainty["matched_task_epochs"] == 1
    assert uncertainty["interval_95"] is None
    markdown = render_markdown(report)
    assert "Task-cluster uncertainty" in markdown
    assert "not a performance claim" in markdown.lower()
    assert "Public file SHA256" in markdown
    assert report["public_artifact_sha256"]["scores.csv"] in markdown


def test_review_file_digests_change_for_valid_whitespace_only_edit(exported: Path):
    from godprompt_bench.review import review_result

    first = review_result(exported)["public_artifact_sha256"]
    path = exported / "manifest.json"
    path.write_bytes(path.read_bytes() + b"\n")
    second = review_result(exported)["public_artifact_sha256"]
    assert second["manifest.json"] != first["manifest.json"]
    assert second["summary.json"] == first["summary.json"]
    assert second["scores.csv"] == first["scores.csv"]


def test_review_refuses_changed_summary(exported: Path):
    from godprompt_bench.review import review_result

    path = exported / "summary.json"
    summary = json.loads(path.read_text(encoding="utf-8"))
    summary["baseline"]["passed"] = 0
    path.write_text(json.dumps(summary), encoding="utf-8")
    with pytest.raises(ValueError, match="summary does not match"):
        review_result(exported)


@pytest.mark.parametrize(
    ("filename", "duplicated_key", "first_value"),
    [
        ("manifest.json", "requested_samples", 999),
        ("summary.json", "baseline", {}),
    ],
)
def test_review_rejects_duplicate_top_level_json_keys(
    exported: Path, filename: str, duplicated_key: str, first_value: object,
):
    from godprompt_bench.review import review_result

    path = exported / filename
    original = json.loads(path.read_text(encoding="utf-8"))
    # Python normally accepts the last JSON key, masking a conflicting first value.
    duplicate = f'{{"{duplicated_key}": {json.dumps(first_value)}, {json.dumps(original)[1:]}'
    path.write_text(duplicate, encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate JSON key"):
        review_result(exported)


def test_review_rejects_nested_duplicate_summary_keys(exported: Path):
    from godprompt_bench.review import review_result

    path = exported / "summary.json"
    original = json.loads(path.read_text(encoding="utf-8"))
    serialized = json.dumps(original, separators=(",", ":"))
    assert '"baseline":{' in serialized
    path.write_text(
        serialized.replace('"baseline":{', '"baseline":{"passed":999,', 1),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate JSON key"):
        review_result(exported)


def test_review_refuses_malformed_csv_outcome(exported: Path):
    from godprompt_bench.review import review_result

    path = exported / "scores.csv"
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    rows[0]["passed"] = "yes"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    with pytest.raises(ValueError, match="passed"):
        review_result(exported)


@pytest.mark.parametrize("status", ["completed", "COMPLETE", "protocol-invalid\nspoofed"])
def test_review_refuses_unknown_completion_status(exported: Path, status: str):
    from godprompt_bench.review import review_result

    path = exported / "scores.csv"
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    rows[0]["completion_status"] = status
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    with pytest.raises(ValueError, match="completion_status"):
        review_result(exported)


def test_review_refuses_duplicate_sample_identity(exported: Path):
    from godprompt_bench.review import review_result

    path = exported / "scores.csv"
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows([*rows, rows[0]])
    with pytest.raises(ValueError, match="duplicate"):
        review_result(exported)


def test_review_rejects_manifest_count_disagreement(exported: Path):
    from godprompt_bench.review import review_result

    path = exported / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["completed_samples"] = 3
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="completed_samples"):
        review_result(exported)


def test_review_marks_incomplete_export_without_claiming_success(exported: Path):
    from godprompt_bench.review import review_result

    path = exported / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["requested_samples"] = 4
    path.write_text(json.dumps(manifest), encoding="utf-8")
    report = review_result(exported)
    assert report["coverage"]["complete"] is False
    assert "incomplete_coverage" in report["cautions"]
    assert report["performance_claim_verified"] is False


def test_offline_review_cli_prints_json_without_writing_or_running_model(
    exported: Path, monkeypatch, capsys,
):
    from godprompt_bench import review

    before = {p.name: p.read_bytes() for p in exported.iterdir()}
    monkeypatch.setattr(sys, "argv", ["godprompt_bench.review", str(exported)])
    review.main()
    report = json.loads(capsys.readouterr().out)
    assert report["artifact_consistency"] == "verified"
    assert {p.name: p.read_bytes() for p in exported.iterdir()} == before


@pytest.mark.parametrize("scenario", ["infrastructure", "missing"])
@pytest.mark.parametrize("output_format", ["json", "markdown"])
def test_offline_review_cli_require_evaluable_fails_with_diagnostics(
    exported: Path, tmp_path: Path, monkeypatch, capsys,
    scenario: str, output_format: str,
):
    from godprompt_bench import review

    folder = exported
    if scenario == "missing":
        folder = tmp_path / "missing-samples"
        manifest = json.loads((exported / "manifest.json").read_text(encoding="utf-8"))
        manifest.update(
            run_id="missing-samples", requested_samples=3,
            completed_samples=2, infrastructure_failures=0,
        )
        export_run(folder, manifest, [record("baseline"), record("godprompt")], [])
    snapshot = {p.name: p.read_bytes() for p in folder.iterdir()}
    monkeypatch.setattr(sys, "argv", [
        "godprompt_bench.review", str(folder),
        "--require-evaluable", "--format", output_format,
    ])
    with pytest.raises(SystemExit) as exit_info:
        review.main()
    assert exit_info.value.code == 1
    output = capsys.readouterr().out
    if output_format == "json":
        coverage = json.loads(output)["coverage"]
        assert coverage["model_samples"] < coverage["requested_samples"]
        assert coverage["infrastructure_failures"] == (1 if scenario == "infrastructure" else 0)
    else:
        assert "Coverage:" in output
        assert "model-evaluable" in output
    assert {p.name: p.read_bytes() for p in folder.iterdir()} == snapshot


def test_offline_review_cli_require_evaluable_succeeds_for_all_model_samples(
    exported: Path, tmp_path: Path, monkeypatch, capsys,
):
    from godprompt_bench import review

    manifest = json.loads((exported / "manifest.json").read_text(encoding="utf-8"))
    manifest.update(
        run_id="evaluable", requested_samples=2,
        completed_samples=2, infrastructure_failures=0,
    )
    folder = tmp_path / "evaluable"
    export_run(folder, manifest, [record("baseline"), record("godprompt")], [])
    monkeypatch.setattr(sys, "argv", [
        "godprompt_bench.review", str(folder), "--require-evaluable",
    ])
    review.main()
    coverage = json.loads(capsys.readouterr().out)["coverage"]
    assert coverage["complete"] is True
    assert coverage["model_samples"] == coverage["requested_samples"] == 2


@pytest.mark.parametrize("output_format", ["json", "markdown"])
@pytest.mark.parametrize(
    ("outcomes", "missing", "exit_code"),
    [
        ([(False, True)], False, 0),
        ([(True, False)], False, 1),
        ([(True, True)], False, 0),
        ([(False, True), (True, False)], False, 0),
        ([(True, None)], False, 1),
        ([(True, "infra")], False, 1),
        ([(True, True)], True, 1),
    ],
)
def test_offline_review_cli_require_nondegrading_pairs(
    exported: Path, tmp_path: Path, monkeypatch, capsys,
    outcomes, missing: bool, exit_code: int, output_format: str,
):
    from godprompt_bench import review

    rows = []
    for index, (baseline_passed, godprompt_passed) in enumerate(outcomes):
        task_id = f"private-{index}"
        rows.append(replace(record("baseline", passed=baseline_passed), task_id=task_id))
        if godprompt_passed == "infra":
            rows.append(replace(record("godprompt", infra="sandbox unavailable"), task_id=task_id))
        elif godprompt_passed is not None:
            rows.append(replace(record("godprompt", passed=godprompt_passed), task_id=task_id))
    infra_count = sum(row.infrastructure_error is not None for row in rows)
    manifest = json.loads((exported / "manifest.json").read_text(encoding="utf-8"))
    manifest.update(
        run_id="paired-gate", requested_samples=len(rows) + int(missing),
        completed_samples=len(rows) - infra_count, infrastructure_failures=infra_count,
    )
    folder = tmp_path / "paired-gate"
    export_run(folder, manifest, rows, [])
    snapshot = {p.name: p.read_bytes() for p in folder.iterdir()}
    monkeypatch.setattr(sys, "argv", [
        "godprompt_bench.review", str(folder),
        "--require-nondegrading-pairs", "--format", output_format,
    ])
    if exit_code:
        with pytest.raises(SystemExit) as exc:
            review.main()
        assert exc.value.code == exit_code
    else:
        review.main()
    output = capsys.readouterr().out
    if output_format == "json":
        pairs = json.loads(output)["within_run_condition_pairs"]
        assert pairs["paired_task_epochs"] >= 0
        assert "private-" not in output
    else:
        assert "Within-run matched condition outcomes" in output
        assert "private-" not in output
    assert {p.name: p.read_bytes() for p in folder.iterdir()} == snapshot


def test_offline_review_cli_require_nondegrading_pairs_rejects_comparison(
    exported: Path, monkeypatch, capsys,
):
    from godprompt_bench import review

    monkeypatch.setattr(sys, "argv", [
        "godprompt_bench.review", str(exported), "--compare", str(exported),
        "--require-nondegrading-pairs",
    ])
    with pytest.raises(SystemExit) as exc:
        review.main()
    assert exc.value.code == 2
    assert "--require-nondegrading-pairs" in capsys.readouterr().err


def test_offline_paired_gate_rejects_mixed_actual_models(
    exported: Path, tmp_path: Path, monkeypatch, capsys,
):
    from godprompt_bench import review

    manifest = json.loads((exported / "manifest.json").read_text(encoding="utf-8"))
    manifest.update(
        run_id="mixed-model-pairs", actual_models=["provider/a", "provider/b"],
        requested_samples=2, completed_samples=2, infrastructure_failures=0,
    )
    folder = tmp_path / "mixed-model-pairs"
    export_run(folder, manifest, [record("baseline"), record("godprompt")], [])
    monkeypatch.setattr(sys, "argv", [
        "godprompt_bench.review", str(folder), "--require-nondegrading-pairs",
    ])

    with pytest.raises(SystemExit) as exc:
        review.main()
    assert exc.value.code == 1
    assert "mixed_actual_models" in capsys.readouterr().out


@pytest.fixture
def comparable_exports(exported: Path, tmp_path: Path) -> tuple[Path, Path]:
    common = {
        "task_manifest_sha256": "c" * 64,
        "fixture_bundles_sha256": "d" * 64,
        "baseline_system_prompt_sha256": "e" * 64,
        "sandbox_dockerfile_sha256": "f" * 64,
        "sandbox_compose_sha256": "1" * 64,
        "epochs": 2,
        "max_messages": 20,
        "max_time_seconds": 120,
        "max_output_tokens": 1000,
        "temperature": None,
        "seed": 7,
        "reasoning_effort": None,
        "reasoning_mode": "standard",
        "inspect_ai_version": "test-only",
    }
    original = json.loads((exported / "manifest.json").read_text(encoding="utf-8"))
    original.update(common)
    (exported / "manifest.json").write_text(json.dumps(original), encoding="utf-8")
    after = tmp_path / "later-run"
    export_run(after, {**original, "run_id": "later-run", "godprompt_commit_sha": "3" * 40}, [
        record("baseline", passed=False), record("godprompt"),
        replace(record("godprompt", infra="sandbox unavailable"), epoch=2),
    ], [])
    return exported, after


def test_offline_comparison_reports_condition_deltas_and_no_performance_claim(
    comparable_exports: tuple[Path, Path],
):
    from godprompt_bench.review import compare_results

    before, after = comparable_exports
    before_files = {p.name: p.read_bytes() for p in before.iterdir()}
    after_files = {p.name: p.read_bytes() for p in after.iterdir()}
    report = compare_results(before, after)
    assert report["comparison_only"] is True
    assert report["metadata_aligned"] is True
    assert report["performance_claim_verified"] is False
    assert report["condition_pass_rate_delta"]["baseline"] == -1.0
    assert report["condition_pass_rate_delta"]["godprompt"] == 1.0
    assert report["category_pass_rate_delta"] == {
        "implementation": {"baseline": -1.0, "godprompt": 1.0},
    }
    assert report["before"]["run_id"] == "sample-run"
    assert report["after"]["run_id"] == "later-run"
    from godprompt_bench.review import render_markdown
    markdown = render_markdown(report)
    for name in ("manifest.json", "summary.json", "scores.csv"):
        assert report["before"]["public_artifact_sha256"][name] in markdown
        assert report["after"]["public_artifact_sha256"][name] in markdown
    assert "mock_model" in report["before"]["cautions"]
    assert report["cross_run_paired_uncertainty"]["interval_95"] is None
    assert "before:mock_model" in report["cross_run_paired_uncertainty"]["limitations"]
    assert {p.name: p.read_bytes() for p in before.iterdir()} == before_files
    assert {p.name: p.read_bytes() for p in after.iterdir()} == after_files


def test_cross_run_paired_contrast_renders_only_local_descriptive_uncertainty(
    comparable_exports: tuple[Path, Path], tmp_path: Path,
):
    from godprompt_bench.review import compare_results, render_markdown

    template = json.loads(
        (comparable_exports[0] / "manifest.json").read_text(encoding="utf-8")
    )
    template.update(
        requested_model="provider/test-model", actual_models=["provider/test-model"],
        requested_samples=72, completed_samples=72, infrastructure_failures=0,
        epochs=3,
    )
    before_rows, after_rows = [], []
    for task in range(12):
        for epoch in (1, 2, 3):
            for condition in ("baseline", "godprompt"):
                before_rows.append(replace(
                    record(condition, passed=False),
                    task_id=f"private-{task}", epoch=epoch,
                ))
                after_rows.append(replace(
                    record(condition, passed=(
                        task < 8 if condition == "godprompt" else task >= 8
                    )),
                    task_id=f"private-{task}", epoch=epoch,
                ))
    before, after = tmp_path / "cross-run-before", tmp_path / "cross-run-after"
    export_run(before, {**template, "run_id": "cross-run-before"}, before_rows, [])
    export_run(after, {**template, "run_id": "cross-run-after"}, after_rows, [])

    report = compare_results(before, after)
    assert report["metadata_aligned"] is True
    contrast = report["cross_run_paired_uncertainty"]
    assert contrast["observed_contrast_change"] == pytest.approx(1 / 3)
    assert contrast["interval_95"] is not None
    assert contrast["limitations"] == []
    rendered = render_markdown(report)
    assert "Cross-run paired contrast change" in rendered
    assert "+33.3 pp" in rendered
    assert "not a causal confidence interval" in rendered
    assert "private-" not in rendered
    assert "private-" not in json.dumps(report)
    assert report["performance_claim_verified"] is False


def test_comparison_suppresses_deltas_when_both_runs_route_multiple_models(
    comparable_exports: tuple[Path, Path],
):
    from godprompt_bench.review import compare_results

    before, after = comparable_exports
    for folder in (before, after):
        path = folder / "manifest.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["actual_models"] = ["provider/model-a", "provider/model-b"]
        path.write_text(json.dumps(manifest), encoding="utf-8")

    report = compare_results(before, after)
    assert report["metadata_aligned"] is False
    assert "before:mixed_actual_models" in report["comparison_cautions"]
    assert "after:mixed_actual_models" in report["comparison_cautions"]
    assert report["condition_pass_rate_delta"] is None
    assert report["condition_pass_transitions"] is None


def test_comparison_counts_joint_condition_pair_transitions_without_task_ids(
    comparable_exports: tuple[Path, Path], tmp_path: Path,
):
    from godprompt_bench.review import compare_results, render_markdown

    sample, _ = comparable_exports
    manifest = json.loads((sample / "manifest.json").read_text(encoding="utf-8"))
    manifest.update(requested_samples=12, completed_samples=11, infrastructure_failures=1)
    earlier_rows = [
        replace(record("baseline", passed=False), task_id="secret-a"),
        replace(record("godprompt"), task_id="secret-a"),
        replace(record("baseline"), task_id="secret-b"),
        replace(record("godprompt"), task_id="secret-b"),
        replace(record("baseline"), task_id="secret-c"),
        replace(record("godprompt", passed=False), task_id="secret-c"),
        replace(record("baseline", passed=False), task_id="secret-d"),
        replace(record("godprompt", passed=False), task_id="secret-d"),
        replace(record("baseline", infra="unavailable"), task_id="secret-e"),
        replace(record("godprompt"), task_id="secret-e"),
        replace(record("baseline"), task_id="secret-f"),
        replace(record("godprompt"), task_id="secret-f", category="verification"),
    ]
    later_rows = [
        replace(record("baseline"), task_id="secret-a"),
        replace(record("godprompt"), task_id="secret-a"),
        replace(record("baseline"), task_id="secret-b"),
        replace(record("godprompt", passed=False), task_id="secret-b"),
        replace(record("baseline", passed=False), task_id="secret-c"),
        replace(record("godprompt", passed=False), task_id="secret-c"),
        replace(record("baseline", passed=False), task_id="secret-d"),
        replace(record("godprompt"), task_id="secret-d"),
        replace(record("baseline", infra="unavailable"), task_id="secret-e"),
        replace(record("godprompt"), task_id="secret-e"),
        replace(record("baseline"), task_id="secret-f"),
        replace(record("godprompt"), task_id="secret-f", category="verification"),
    ]
    before, after = tmp_path / "joint-before", tmp_path / "joint-after"
    export_run(before, {**manifest, "run_id": "joint-before"}, earlier_rows, [])
    export_run(after, {**manifest, "run_id": "joint-after"}, later_rows, [])

    report = compare_results(before, after)
    assert report["metadata_aligned"] is True
    pairs = report["cross_run_condition_pair_transitions"]
    assert pairs["paired_task_epochs"] == 4
    assert pairs["excluded_task_epochs"] == 2
    matrix = pairs["transitions"]
    assert matrix["baseline_fail_godprompt_pass"]["both_pass"] == 1
    assert matrix["both_pass"]["baseline_pass_godprompt_fail"] == 1
    assert matrix["baseline_pass_godprompt_fail"]["both_fail"] == 1
    assert matrix["both_fail"]["baseline_fail_godprompt_pass"] == 1
    assert sum(sum(row.values()) for row in matrix.values()) == 4
    rendered = render_markdown(report)
    assert "Joint baseline/GodPrompt pair transitions" in rendered
    assert "4 matched task-epochs; 2 excluded" in rendered
    assert "secret-" not in rendered
    assert "secret-" not in json.dumps(report)
    assert report["performance_claim_verified"] is False


def test_comparison_suppresses_joint_pair_transitions_if_metadata_is_unaligned(
    comparable_exports: tuple[Path, Path],
):
    from godprompt_bench.review import compare_results, render_markdown

    before, after = comparable_exports
    manifest_path = after / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["seed"] = 42
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    report = compare_results(before, after)
    assert report["metadata_aligned"] is False
    assert report["cross_run_condition_pair_transitions"] is None
    assert report["cross_run_paired_uncertainty"] is None
    assert "Joint baseline/GodPrompt pair transitions" not in render_markdown(report)
    assert "Cross-run paired contrast change" not in render_markdown(report)


def test_offline_comparison_resource_deltas_keep_unknown_tokens_unknown(
    comparable_exports: tuple[Path, Path], tmp_path: Path,
):
    from godprompt_bench.review import compare_results, render_markdown

    before, later = comparable_exports
    manifest = json.loads((later / "manifest.json").read_text(encoding="utf-8"))
    changed = tmp_path / "resource-later"
    export_run(changed, {**manifest, "run_id": "resource-later"}, [
        replace(record("baseline", passed=False), input_tokens=25,
                output_tokens=None, failed_tool_calls=2, retries=1),
        record("godprompt"),
        replace(record("godprompt", infra="sandbox unavailable"), epoch=2),
    ], [])

    report = compare_results(before, changed)
    assert report["metadata_aligned"] is True
    assert report["condition_resource_delta"] == {
        "baseline": {"input_tokens": 15, "output_tokens": None,
                     "failed_tool_calls": 2, "retries": 1},
        "godprompt": {"input_tokens": 0, "output_tokens": 0,
                      "failed_tool_calls": 0, "retries": 0},
    }
    rendered = render_markdown(report)
    assert "Observed resource deltas" in rendered
    assert "+15" in rendered and "n/a" in rendered and "+2" in rendered
    assert "not a performance claim" in rendered.lower()


def test_offline_comparison_suppresses_resource_deltas_when_unaligned(
    comparable_exports: tuple[Path, Path],
):
    from godprompt_bench.review import compare_results, render_markdown

    before, after = comparable_exports
    path = after / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["seed"] = 42
    path.write_text(json.dumps(manifest), encoding="utf-8")
    report = compare_results(before, after)
    assert report["metadata_aligned"] is False
    assert report["condition_resource_delta"] is None
    assert "Observed resource deltas" not in render_markdown(report)


def test_offline_comparison_suppresses_delta_for_different_fixtures(
    comparable_exports: tuple[Path, Path],
):
    from godprompt_bench.review import compare_results

    before, after = comparable_exports
    manifest_path = after / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["fixture_bundles_sha256"] = "9" * 64
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    report = compare_results(before, after)
    assert report["metadata_aligned"] is False
    assert "different:fixture_bundles_sha256" in report["comparison_cautions"]
    assert report["condition_pass_rate_delta"] is None
    assert report["category_pass_rate_delta"] is None


def test_offline_comparison_breaks_down_categories_without_inventing_missing_rates(
    comparable_exports: tuple[Path, Path], tmp_path: Path,
):
    from godprompt_bench.review import compare_results

    original, _ = comparable_exports
    manifest = json.loads((original / "manifest.json").read_text(encoding="utf-8"))
    manifest.update(requested_samples=4, completed_samples=3, infrastructure_failures=1)
    before = tmp_path / "category-before"
    after = tmp_path / "category-after"
    records_before = [
        record("baseline"), record("godprompt", passed=False),
        replace(record("baseline", infra="unavailable"), task_id="verify", category="verification"),
        replace(record("godprompt"), task_id="verify", category="verification"),
    ]
    records_after = [
        record("baseline", passed=False), record("godprompt"),
        replace(record("baseline", infra="unavailable"), task_id="verify", category="verification"),
        replace(record("godprompt", passed=False), task_id="verify", category="verification"),
    ]
    export_run(before, {**manifest, "run_id": "category-before"}, records_before, [])
    export_run(after, {**manifest, "run_id": "category-after", "godprompt_commit_sha": "3" * 40}, records_after, [])

    report = compare_results(before, after)
    assert report["metadata_aligned"] is True
    assert report["category_pass_rate_delta"] == {
        "implementation": {"baseline": -1.0, "godprompt": 1.0},
        "verification": {"baseline": None, "godprompt": -1.0},
    }
    assert report["category_pass_transitions"] == {
        "implementation": {
            "baseline": {"fail_to_pass": 0, "pass_to_fail": 1,
                         "pass_to_pass": 0, "fail_to_fail": 0, "paired_samples": 1},
            "godprompt": {"fail_to_pass": 1, "pass_to_fail": 0,
                          "pass_to_pass": 0, "fail_to_fail": 0, "paired_samples": 1},
        },
        "verification": {
            "baseline": {"fail_to_pass": 0, "pass_to_fail": 0,
                         "pass_to_pass": 0, "fail_to_fail": 0, "paired_samples": 0},
            "godprompt": {"fail_to_pass": 0, "pass_to_fail": 1,
                          "pass_to_pass": 0, "fail_to_fail": 0, "paired_samples": 1},
        },
    }
    from godprompt_bench.review import render_markdown
    markdown = render_markdown(report)
    assert "Per-category paired transitions" in markdown
    assert "| implementation | baseline | 0 | 1 | 0 | 0 | 1 |" in markdown
    assert "| verification | baseline | 0 | 0 | 0 | 0 | 0 |" in markdown
    assert "| verification | godprompt | 0 | 1 | 0 | 0 | 1 |" in markdown
    assert "| impl-example |" not in markdown
    assert "| verify |" not in markdown
    for condition in ("baseline", "godprompt"):
        for field, count in report["condition_pass_transitions"][condition].items():
            assert sum(
                category[condition][field]
                for category in report["category_pass_transitions"].values()
            ) == count
    assert report["performance_claim_verified"] is False


def test_offline_comparison_requires_metadata_and_complete_exports(exported: Path, tmp_path: Path):
    from godprompt_bench.review import compare_results

    after = tmp_path / "later-run"
    manifest = json.loads((exported / "manifest.json").read_text(encoding="utf-8"))
    export_run(after, {**manifest, "run_id": "later-run"}, [
        record("baseline"), record("godprompt", passed=False),
        replace(record("godprompt", infra="sandbox unavailable"), epoch=2),
    ], [])
    report = compare_results(exported, after)
    assert report["metadata_aligned"] is False
    assert "missing:fixture_bundles_sha256" in report["comparison_cautions"]
    assert report["condition_pass_rate_delta"] is None


def test_offline_comparison_cli_prints_json_without_provider_calls(
    comparable_exports: tuple[Path, Path], monkeypatch, capsys,
):
    from godprompt_bench import review

    before, after = comparable_exports
    monkeypatch.setattr(sys, "argv", ["godprompt_bench.review", str(before), "--compare", str(after)])
    review.main()
    report = json.loads(capsys.readouterr().out)
    assert report["metadata_aligned"] is True
    assert report["before"]["run_id"] == "sample-run"


def test_offline_comparison_cli_require_aligned_succeeds_for_comparable_exports(
    comparable_exports: tuple[Path, Path], monkeypatch, capsys,
):
    from godprompt_bench import review

    before, after = comparable_exports
    original = {folder: {p.name: p.read_bytes() for p in folder.iterdir()}
                for folder in (before, after)}
    monkeypatch.setattr(sys, "argv", [
        "godprompt_bench.review", str(before), "--compare", str(after),
        "--require-aligned",
    ])
    review.main()
    assert json.loads(capsys.readouterr().out)["metadata_aligned"] is True
    assert all({p.name: p.read_bytes() for p in folder.iterdir()} == contents
               for folder, contents in original.items())


@pytest.mark.parametrize("output_format", ["json", "markdown"])
def test_offline_comparison_cli_require_aligned_fails_but_prints_diagnostics(
    comparable_exports: tuple[Path, Path], monkeypatch, capsys, output_format: str,
):
    from godprompt_bench import review

    before, after = comparable_exports
    path = after / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["fixture_bundles_sha256"] = "9" * 64
    path.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", [
        "godprompt_bench.review", str(before), "--compare", str(after),
        "--require-aligned", "--format", output_format,
    ])
    with pytest.raises(SystemExit) as exit_info:
        review.main()
    assert exit_info.value.code == 1
    output = capsys.readouterr().out
    if output_format == "json":
        report = json.loads(output)
        assert report["metadata_aligned"] is False
        assert "different:fixture_bundles_sha256" in report["comparison_cautions"]
        assert report["condition_pass_rate_delta"] is None
    else:
        assert "different:fixture_bundles_sha256" in output
        assert "not comparable" in output.lower()


def test_offline_review_cli_require_aligned_requires_compare(exported: Path, monkeypatch, capsys):
    from godprompt_bench import review

    monkeypatch.setattr(sys, "argv", [
        "godprompt_bench.review", str(exported), "--require-aligned",
    ])
    with pytest.raises(SystemExit) as exit_info:
        review.main()
    assert exit_info.value.code == 2
    assert "--compare" in capsys.readouterr().err


def test_offline_comparison_cli_require_evaluable_checks_both_runs(
    comparable_exports: tuple[Path, Path], monkeypatch, capsys,
):
    from godprompt_bench import review

    before, after = comparable_exports
    monkeypatch.setattr(sys, "argv", [
        "godprompt_bench.review", str(before), "--compare", str(after),
        "--require-aligned", "--require-evaluable",
    ])
    with pytest.raises(SystemExit) as exit_info:
        review.main()
    assert exit_info.value.code == 1
    report = json.loads(capsys.readouterr().out)
    assert report["metadata_aligned"] is True
    assert report["before"]["coverage"]["infrastructure_failures"] == 1
    assert report["after"]["coverage"]["infrastructure_failures"] == 1


def test_offline_review_cli_markdown_is_read_only_and_non_promotional(
    exported: Path, monkeypatch, capsys,
):
    from godprompt_bench import review

    before = {p.name: p.read_bytes() for p in exported.iterdir()}
    monkeypatch.setattr(sys, "argv", [
        "godprompt_bench.review", str(exported), "--format", "markdown",
    ])
    review.main()
    rendered = capsys.readouterr().out
    assert "# GodPrompt Bench" in rendered
    assert "sample-run" in rendered
    assert "baseline" in rendered and "godprompt" in rendered
    assert "mock_model" in rendered
    assert "a" * 40 in rendered and "b" * 40 in rendered
    assert "not independently verified" in rendered.lower()
    assert "not a performance claim" in rendered.lower()
    assert {p.name: p.read_bytes() for p in exported.iterdir()} == before


def test_markdown_report_escapes_untrusted_export_labels(exported: Path, monkeypatch, capsys):
    from godprompt_bench import review

    manifest_path = exported / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["run_id"] = "run|example\n# injected heading"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", [
        "godprompt_bench.review", str(exported), "--format", "markdown",
    ])
    review.main()
    rendered = capsys.readouterr().out
    assert "run\\|example # injected heading" in rendered
    assert "\n# injected heading" not in rendered


def test_markdown_report_neutralizes_terminal_and_bidi_controls(exported: Path, monkeypatch, capsys):
    from godprompt_bench import review

    manifest_path = exported / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["run_id"] = "first\x1b[2J\x9b0K\u202ehidden\u2066last"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", [
        "godprompt_bench.review", str(exported), "--format", "markdown",
    ])

    review.main()
    rendered = capsys.readouterr().out
    assert "first" in rendered and "last" in rendered
    assert all(control not in rendered for control in ("\x1b", "\x9b", "\u202e", "\u2066"))
    assert "not independently verified" in rendered.lower()


def test_offline_comparison_cli_markdown_shows_category_changes_only_if_aligned(
    comparable_exports: tuple[Path, Path], monkeypatch, capsys,
):
    from godprompt_bench import review

    before, after = comparable_exports
    monkeypatch.setattr(sys, "argv", [
        "godprompt_bench.review", str(before), "--compare", str(after),
        "--format", "markdown",
    ])
    review.main()
    rendered = capsys.readouterr().out
    assert "implementation" in rendered
    assert "-100.0 pp" in rendered
    assert "+100.0 pp" in rendered
    assert "3" * 40 in rendered
    assert "not a performance claim" in rendered.lower()

    path = after / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["fixture_bundles_sha256"] = "9" * 64
    path.write_text(json.dumps(manifest), encoding="utf-8")
    review.main()
    rejected = capsys.readouterr().out
    assert "different:fixture_bundles_sha256" in rejected
    assert "not comparable" in rejected.lower()
    assert "-100.0 pp" not in rejected
    assert "+100.0 pp" not in rejected


@pytest.mark.parametrize("changed_field", ["task_id", "category"])
def test_offline_comparison_suppresses_delta_for_different_scored_samples(
    comparable_exports: tuple[Path, Path], tmp_path: Path, changed_field: str,
):
    from godprompt_bench.review import compare_results

    before, after = comparable_exports
    manifest = json.loads((after / "manifest.json").read_text(encoding="utf-8"))
    replacement = "other-task" if changed_field == "task_id" else "other-category"
    changed = {changed_field: replacement}
    different = tmp_path / "different-scored-samples"
    export_run(different, {**manifest, "run_id": "different-scored-samples"}, [
        replace(record("baseline", passed=False), **changed),
        replace(record("godprompt"), **changed),
        replace(record("godprompt", infra="sandbox unavailable"), epoch=2, **changed),
    ], [])

    report = compare_results(before, different)
    assert report["metadata_aligned"] is False
    assert "different:scored_samples" in report["comparison_cautions"]
    assert report["condition_pass_rate_delta"] is None


def test_offline_comparison_suppresses_delta_for_different_evaluable_samples(
    comparable_exports: tuple[Path, Path], tmp_path: Path,
):
    from godprompt_bench.review import compare_results

    before, after = comparable_exports
    manifest = json.loads((after / "manifest.json").read_text(encoding="utf-8"))
    different = tmp_path / "different-model-coverage"
    export_run(different, {
        **manifest, "run_id": "different-model-coverage",
        "completed_samples": 3, "infrastructure_failures": 0,
    }, [
        record("baseline", passed=False), record("godprompt"),
        replace(record("godprompt"), epoch=2),
    ], [])

    report = compare_results(before, different)
    assert report["metadata_aligned"] is False
    assert "different:model_sample_coverage" in report["comparison_cautions"]
    assert report["condition_pass_rate_delta"] is None


def test_offline_comparison_shows_paired_pass_transitions_without_listing_tasks(
    comparable_exports: tuple[Path, Path],
):
    from godprompt_bench.review import compare_results, render_markdown

    before, after = comparable_exports
    report = compare_results(before, after)
    assert report["metadata_aligned"] is True
    assert report["condition_pass_transitions"] == {
        "baseline": {"fail_to_pass": 0, "pass_to_fail": 1,
                     "pass_to_pass": 0, "fail_to_fail": 0, "paired_samples": 1},
        "godprompt": {"fail_to_pass": 1, "pass_to_fail": 0,
                      "pass_to_pass": 0, "fail_to_fail": 0, "paired_samples": 1},
    }
    markdown = render_markdown(report)
    assert "Paired outcome transitions" in markdown
    assert "| baseline | 0 | 1 | 0 | 0 | 1 |" in markdown
    assert "| godprompt | 1 | 0 | 0 | 0 | 1 |" in markdown
    assert "impl-example" not in markdown  # no sample-level IDs in shareable evidence
    assert "not a performance claim" in markdown.lower()


@pytest.mark.parametrize("modified_side", ("before", "after"))
def test_offline_comparison_rejects_artifact_change_after_individual_review(
    comparable_exports: tuple[Path, Path], monkeypatch, modified_side,
):
    from godprompt_bench import review

    before, after = comparable_exports
    original_hashes = review._public_artifact_sha256
    after_reads = 0

    def change_after_validation(folder):
        nonlocal after_reads
        hashes = original_hashes(folder)
        if folder == after:
            after_reads += 1
            if after_reads == 2:
                path = (before if modified_side == "before" else after) / "scores.csv"
                with path.open(encoding="utf-8", newline="") as handle:
                    reader = csv.DictReader(handle)
                    names = reader.fieldnames
                    rows = list(reader)
                for row in rows:
                    if row["condition"] == "godprompt":
                        row["passed"] = "False" if row["passed"] == "True" else "True"
                with path.open("w", encoding="utf-8", newline="") as handle:
                    writer = csv.DictWriter(handle, fieldnames=names)
                    writer.writeheader()
                    writer.writerows(rows)
        return hashes

    monkeypatch.setattr(review, "_public_artifact_sha256", change_after_validation)
    with pytest.raises(ValueError, match="changed during offline comparison"):
        review.compare_results(before, after)


def test_offline_comparison_counts_unchanged_and_mixed_paired_outcomes(
    comparable_exports: tuple[Path, Path], tmp_path: Path,
):
    from godprompt_bench.review import compare_results

    original, _ = comparable_exports
    manifest = json.loads((original / "manifest.json").read_text(encoding="utf-8"))
    common = {**manifest, "requested_samples": 5, "completed_samples": 5,
              "infrastructure_failures": 0}
    earlier, later = tmp_path / "earlier-mixed", tmp_path / "later-mixed"
    before_states = [True, False, True, False]
    after_states = [True, True, False, False]
    before_records = [replace(record("baseline", passed=state), task_id=f"task-{i}")
                      for i, state in enumerate(before_states)]
    after_records = [replace(record("baseline", passed=state), task_id=f"task-{i}")
                     for i, state in enumerate(after_states)]
    export_run(earlier, {**common, "run_id": "earlier-mixed"},
               [*before_records, record("godprompt")], [])
    export_run(later, {**common, "run_id": "later-mixed", "godprompt_commit_sha": "3" * 40},
               [*after_records, record("godprompt")], [])

    report = compare_results(earlier, later)
    assert report["metadata_aligned"] is True
    assert report["condition_pass_transitions"]["baseline"] == {
        "fail_to_pass": 1, "pass_to_fail": 1,
        "pass_to_pass": 1, "fail_to_fail": 1, "paired_samples": 4,
    }
    assert report["condition_pass_transitions"]["godprompt"] == {
        "fail_to_pass": 0, "pass_to_fail": 0,
        "pass_to_pass": 1, "fail_to_fail": 0, "paired_samples": 1,
    }


def test_offline_comparison_suppresses_paired_transitions_for_unaligned_samples(
    comparable_exports: tuple[Path, Path],
):
    from godprompt_bench.review import compare_results, render_markdown

    before, after = comparable_exports
    path = after / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["seed"] = 42
    path.write_text(json.dumps(manifest), encoding="utf-8")
    report = compare_results(before, after)
    assert report["metadata_aligned"] is False
    assert report["condition_pass_transitions"] is None
    assert report["category_pass_transitions"] is None
    assert "Paired outcome transitions" not in render_markdown(report)
    assert "Per-category paired transitions" not in render_markdown(report)


@pytest.mark.parametrize("output_format", ["json", "markdown"])
@pytest.mark.parametrize(
    ("earlier", "later", "missing", "infra", "misaligned", "expected_exit"),
    [
        ([False], [True], False, False, False, 0),
        ([True], [True], False, False, False, 0),
        ([True, False], [False, True], False, False, False, 0),
        ([True], [False], False, False, False, 1),
        ([], [], False, False, False, 1),
        ([True], [True], True, False, False, 1),
        ([True], [True], False, True, False, 1),
        ([True], [True], False, False, True, 1),
    ],
)
def test_offline_comparison_cli_requires_no_net_godprompt_regression(
    comparable_exports: tuple[Path, Path], tmp_path: Path, monkeypatch, capsys,
    earlier, later, missing: bool, infra: bool, misaligned: bool,
    expected_exit: int, output_format: str,
):
    from godprompt_bench import review

    template = json.loads(
        (comparable_exports[0] / "manifest.json").read_text(encoding="utf-8")
    )
    runs = []
    for label, outcomes in (("earlier", earlier), ("later", later)):
        rows = []
        for index, passed in enumerate(outcomes):
            task_id = f"private-task-{index}"
            rows.append(replace(record("baseline"), task_id=task_id))
            rows.append(replace(
                record("godprompt", passed=passed,
                       infra="offline failure" if infra and label == "later" else None),
                task_id=task_id,
            ))
        failures = sum(row.infrastructure_error is not None for row in rows)
        manifest = {
            **template, "run_id": label,
            "requested_samples": len(rows) + (int(missing) if label == "later" else 0),
            "completed_samples": len(rows) - failures,
            "infrastructure_failures": failures,
            "godprompt_commit_sha": ("b" if label == "earlier" else "3") * 40,
        }
        if misaligned and label == "later":
            manifest["seed"] = 999
        folder = tmp_path / label
        export_run(folder, manifest, rows, [])
        runs.append(folder)

    before_files = {
        folder: {path.name: path.read_bytes() for path in folder.iterdir()}
        for folder in runs
    }
    monkeypatch.setattr(sys, "argv", [
        "godprompt_bench.review", str(runs[0]), "--compare", str(runs[1]),
        "--require-no-godprompt-regression", "--format", output_format,
    ])
    if expected_exit:
        with pytest.raises(SystemExit) as exc:
            review.main()
        assert exc.value.code == expected_exit
    else:
        review.main()
    output = capsys.readouterr().out
    if output_format == "json":
        report = json.loads(output)
        assert report["performance_claim_verified"] is False
        if misaligned:
            assert report["metadata_aligned"] is False
        else:
            assert "condition_pass_transitions" in report
    else:
        assert "not a performance claim" in output.lower()
        assert "Comparison cautions" in output
    assert "private-task-" not in output
    assert all(
        {path.name: path.read_bytes() for path in folder.iterdir()} == snapshot
        for folder, snapshot in before_files.items()
    )


def test_offline_comparison_no_regression_flag_requires_compare(
    exported: Path, monkeypatch, capsys,
):
    from godprompt_bench import review

    monkeypatch.setattr(sys, "argv", [
        "godprompt_bench.review", str(exported),
        "--require-no-godprompt-regression",
    ])
    with pytest.raises(SystemExit) as exc:
        review.main()
    assert exc.value.code == 2
    assert "--compare" in capsys.readouterr().err


@pytest.mark.parametrize("output_format", ["json", "markdown"])
@pytest.mark.parametrize(
    ("outcomes", "missing", "infra", "misaligned", "expected_exit"),
    [
        # Two verification recoveries must not mask one implementation regression.
        ([("implementation", True, False),
          ("verification", False, True),
          ("verification", False, True)], False, False, False, 1),
        ([("implementation", False, True),
          ("verification", True, True)], False, False, False, 0),
        ([("implementation", True, False),
          ("implementation", False, True),
          ("verification", False, False)], False, False, False, 0),
        ([("implementation", True, False),
          ("verification", False, False)], False, False, False, 1),
        ([("implementation", True, True)], True, False, False, 1),
        ([("implementation", True, True)], False, True, False, 1),
        ([("implementation", True, True)], False, False, True, 1),
    ],
)
def test_offline_comparison_cli_requires_no_godprompt_category_regression(
    comparable_exports: tuple[Path, Path], tmp_path: Path, monkeypatch, capsys,
    outcomes: list[tuple[str, bool, bool]], missing: bool, infra: bool,
    misaligned: bool, expected_exit: int, output_format: str,
):
    from godprompt_bench import review

    template = json.loads(
        (comparable_exports[0] / "manifest.json").read_text(encoding="utf-8")
    )
    runs = []
    for label, index in (("earlier", 1), ("later", 2)):
        rows = []
        for sample_index, (category, before_passed, after_passed) in enumerate(outcomes):
            task_id = f"private-task-{sample_index}"
            rows.append(replace(record("baseline"), task_id=task_id, category=category))
            rows.append(replace(
                record(
                    "godprompt", passed=before_passed if index == 1 else after_passed,
                    infra="offline failure" if infra and index == 2 else None,
                ),
                task_id=task_id, category=category,
            ))
        failures = sum(row.infrastructure_error is not None for row in rows)
        manifest = {
            **template, "run_id": label,
            "requested_samples": len(rows) + (int(missing) if index == 2 else 0),
            "completed_samples": len(rows) - failures,
            "infrastructure_failures": failures,
            "godprompt_commit_sha": ("b" if index == 1 else "3") * 40,
        }
        if misaligned and index == 2:
            manifest["seed"] = 999
        folder = tmp_path / label
        export_run(folder, manifest, rows, [])
        runs.append(folder)

    snapshots = {
        folder: {path.name: path.read_bytes() for path in folder.iterdir()}
        for folder in runs
    }
    report = review.compare_results(*runs)
    if len(outcomes) == 3 and outcomes[0] == ("implementation", True, False):
        # The existing net gate allows this total improvement, proving that
        # category-level gating adds protection rather than renaming the net gate.
        assert review._no_net_godprompt_regression_between_runs(report)

    monkeypatch.setattr(sys, "argv", [
        "godprompt_bench.review", str(runs[0]), "--compare", str(runs[1]),
        "--require-no-godprompt-category-regression", "--format", output_format,
    ])
    if expected_exit:
        with pytest.raises(SystemExit) as exc:
            review.main()
        assert exc.value.code == expected_exit
    else:
        review.main()
    output = capsys.readouterr().out
    if output_format == "json":
        parsed = json.loads(output)
        assert parsed["performance_claim_verified"] is False
        assert "category_pass_transitions" in parsed
    else:
        assert "not a performance claim" in output.lower()
    assert "private-task-" not in output
    assert all(
        {path.name: path.read_bytes() for path in folder.iterdir()} == original
        for folder, original in snapshots.items()
    )


def test_offline_comparison_category_regression_flag_requires_compare(
    exported: Path, monkeypatch, capsys,
):
    from godprompt_bench import review

    monkeypatch.setattr(sys, "argv", [
        "godprompt_bench.review", str(exported),
        "--require-no-godprompt-category-regression",
    ])
    with pytest.raises(SystemExit) as exc:
        review.main()
    assert exc.value.code == 2
    assert "--compare" in capsys.readouterr().err


@pytest.mark.parametrize("output_format", ("json", "markdown"))
def test_review_cli_requires_matching_saved_plan_fingerprint(
    exported: Path, monkeypatch, capsys, output_format,
):
    from godprompt_bench import review

    digest = "a" * 64
    path = exported / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest.update(plan_sha256_schema="godprompt.bench.plan.v1", plan_sha256=digest)
    path.write_text(json.dumps(manifest), encoding="utf-8")
    original = {entry.name: entry.read_bytes() for entry in exported.iterdir()}

    monkeypatch.setattr(sys, "argv", [
        "godprompt_bench.review", str(exported),
        "--require-plan-sha256", digest, "--format", output_format,
    ])
    review.main()
    output = capsys.readouterr().out
    assert digest in output
    if output_format == "json":
        assert json.loads(output)["reviewed_plan"]["matched_saved_manifest"] is True
    else:
        assert "reviewed plan" in output.lower()
    assert {entry.name: entry.read_bytes() for entry in exported.iterdir()} == original


@pytest.mark.parametrize("manifest_case", ("missing", "wrong_schema", "mismatch"))
def test_review_rejects_unreviewed_or_mismatched_saved_plan(exported: Path, manifest_case):
    from godprompt_bench.review import review_result

    path = exported / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest_case != "missing":
        manifest["plan_sha256_schema"] = (
            "unsupported" if manifest_case == "wrong_schema" else "godprompt.bench.plan.v1"
        )
        manifest["plan_sha256"] = "b" * 64
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="plan"):
        review_result(exported, required_plan_sha256="a" * 64)


@pytest.mark.parametrize("extra", (
    ["--compare", "second-run"], ["--require-plan-sha256", "NOT-A-SHA"],
))
def test_review_cli_rejects_ambiguous_or_malformed_plan_guard(
    exported: Path, monkeypatch, capsys, extra,
):
    from godprompt_bench import review

    args = ["godprompt_bench.review", str(exported), "--require-plan-sha256", "a" * 64]
    if extra[0] == "--require-plan-sha256":
        args[-1] = extra[1]
    else:
        args.extend(extra)
    monkeypatch.setattr(sys, "argv", args)
    with pytest.raises(SystemExit) as exc:
        review.main()
    assert exc.value.code == 2
    assert "plan" in capsys.readouterr().err.lower()


@pytest.mark.parametrize("output_format", ("json", "markdown"))
def test_review_cli_accepts_all_external_public_artifact_sha256_pins(
    exported: Path, monkeypatch, capsys, output_format,
):
    from godprompt_bench import review

    original = {
        name: (exported / name).read_bytes()
        for name in ("manifest.json", "summary.json", "scores.csv")
    }
    pins = [
        f"{name}={hashlib.sha256(data).hexdigest()}"
        for name, data in original.items()
    ]
    argv = ["godprompt_bench.review", str(exported), "--format", output_format]
    for pin in reversed(pins):
        argv.extend(["--require-public-artifact-sha256", pin])
    monkeypatch.setattr(sys, "argv", argv)

    review.main()
    rendered = capsys.readouterr().out
    for pin in pins:
        assert pin.split("=", 1)[1] in rendered
    assert {
        name: (exported / name).read_bytes() for name in original
    } == original


@pytest.mark.parametrize("output_format", ("json", "markdown"))
def test_review_cli_fails_on_external_sha256_pin_mismatch_after_valid_file_change(
    exported: Path, monkeypatch, capsys, output_format,
):
    from godprompt_bench import review

    names = ("manifest.json", "summary.json", "scores.csv")
    expected = {
        name: hashlib.sha256((exported / name).read_bytes()).hexdigest()
        for name in names
    }
    manifest = exported / "manifest.json"
    manifest.write_bytes(manifest.read_bytes() + b" ")
    snapshot = {name: (exported / name).read_bytes() for name in names}
    argv = ["godprompt_bench.review", str(exported), "--format", output_format]
    for name in names:
        argv.extend(["--require-public-artifact-sha256", f"{name}={expected[name]}"])
    monkeypatch.setattr(sys, "argv", argv)

    with pytest.raises(SystemExit) as exc:
        review.main()
    assert exc.value.code == 1
    output = capsys.readouterr()
    assert "manifest.json" in output.err and "SHA256" in output.err
    assert hashlib.sha256(snapshot["manifest.json"]).hexdigest() in output.out
    assert {name: (exported / name).read_bytes() for name in names} == snapshot


@pytest.mark.parametrize("pins", [
    ["manifest.json=" + "a" * 64],
    ["manifest.json=" + "a" * 64, "summary.json=" + "b" * 64,
     "manifest.json=" + "a" * 64, "scores.csv=" + "c" * 64],
    ["manifest.json=" + "a" * 64, "summary.json=" + "b" * 64,
     "private.json=" + "c" * 64],
    ["manifest.json=" + "A" * 64, "summary.json=" + "b" * 64,
     "scores.csv=" + "c" * 64],
    ["manifest.json=bad", "summary.json=" + "b" * 64,
     "scores.csv=" + "c" * 64],
])
def test_review_cli_refuses_partial_duplicate_unknown_or_invalid_pins(
    exported: Path, monkeypatch, capsys, pins,
):
    from godprompt_bench import review

    argv = ["godprompt_bench.review", str(exported)]
    for pin in pins:
        argv.extend(["--require-public-artifact-sha256", pin])
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(SystemExit) as exc:
        review.main()
    assert exc.value.code == 2
    assert "public-artifact-sha256" in capsys.readouterr().err


def test_review_cli_public_hash_pins_are_single_run_only(
    exported: Path, monkeypatch, capsys,
):
    from godprompt_bench import review

    monkeypatch.setattr(sys, "argv", [
        "godprompt_bench.review", str(exported), "--compare", str(exported),
        "--require-public-artifact-sha256", "manifest.json=" + "a" * 64,
    ])
    with pytest.raises(SystemExit) as exc:
        review.main()
    assert exc.value.code == 2
    assert "--compare" in capsys.readouterr().err


@pytest.mark.parametrize("output_format", ("json", "markdown"))
def test_comparison_cli_accepts_independent_external_public_sha256_pins(
    comparable_exports: tuple[Path, Path], monkeypatch, capsys, output_format,
):
    from godprompt_bench import review

    before, after = comparable_exports
    originals = {
        side: {name: (folder / name).read_bytes()
               for name in ("manifest.json", "summary.json", "scores.csv")}
        for side, folder in (("before", before), ("after", after))
    }
    argv = ["godprompt_bench.review", str(before), "--compare", str(after),
            "--format", output_format]
    for side, files in originals.items():
        for name, data in files.items():
            argv.extend(["--require-public-artifact-sha256",
                         f"{side}:{name}={hashlib.sha256(data).hexdigest()}"])
    monkeypatch.setattr(sys, "argv", argv)

    review.main()
    rendered = capsys.readouterr().out
    for side, files in originals.items():
        for name, data in files.items():
            assert hashlib.sha256(data).hexdigest() in rendered
        folder = before if side == "before" else after
        assert {name: (folder / name).read_bytes() for name in files} == files


@pytest.mark.parametrize("output_format", ("json", "markdown"))
@pytest.mark.parametrize("modified_side", ("before", "after"))
def test_comparison_cli_fails_after_reporting_changed_pinned_artifact(
    comparable_exports: tuple[Path, Path], monkeypatch, capsys, output_format, modified_side,
):
    from godprompt_bench import review

    before, after = comparable_exports
    names = ("manifest.json", "summary.json", "scores.csv")
    pins = {
        side: {name: hashlib.sha256((folder / name).read_bytes()).hexdigest()
               for name in names}
        for side, folder in (("before", before), ("after", after))
    }
    modified_folder = before if modified_side == "before" else after
    changed = modified_folder / "manifest.json"
    changed.write_bytes(changed.read_bytes() + b" ")
    argv = ["godprompt_bench.review", str(before), "--compare", str(after),
            "--format", output_format]
    for side, files in pins.items():
        for name, digest in files.items():
            argv.extend(["--require-public-artifact-sha256", f"{side}:{name}={digest}"])
    monkeypatch.setattr(sys, "argv", argv)

    with pytest.raises(SystemExit) as exc:
        review.main()
    assert exc.value.code == 1
    output = capsys.readouterr()
    assert f"{modified_side}:manifest.json" in output.err and "SHA256" in output.err
    assert hashlib.sha256(changed.read_bytes()).hexdigest() in output.out


@pytest.mark.parametrize("invalid", (
    "partial", "duplicate", "unqualified", "invalid_side", "wrong_digest",
))
def test_comparison_cli_rejects_incomplete_or_ambiguous_public_sha256_pins(
    comparable_exports: tuple[Path, Path], monkeypatch, capsys, invalid,
):
    from godprompt_bench import review

    before, after = comparable_exports
    names = ("manifest.json", "summary.json", "scores.csv")
    pins = [f"{side}:{name}=" + "a" * 64
            for side in ("before", "after") for name in names]
    if invalid == "partial":
        pins.pop()
    elif invalid == "duplicate":
        pins.append(pins[0])
    elif invalid == "unqualified":
        pins[0] = pins[0].replace("before:", "", 1)
    elif invalid == "invalid_side":
        pins[0] = pins[0].replace("before:", "other:", 1)
    elif invalid == "wrong_digest":
        pins[0] = pins[0].replace("a" * 64, "A" * 64)
    argv = ["godprompt_bench.review", str(before), "--compare", str(after)]
    for pin in pins:
        argv.extend(["--require-public-artifact-sha256", pin])
    monkeypatch.setattr(sys, "argv", argv)

    with pytest.raises(SystemExit) as exc:
        review.main()
    assert exc.value.code == 2
    assert "public-artifact-sha256" in capsys.readouterr().err


def _public_zip(source: Path, target: Path) -> Path:
    with ZipFile(target, "w", compression=ZIP_DEFLATED) as archive:
        for name in ("manifest.json", "summary.json", "scores.csv"):
            archive.write(source / name, arcname=name)
    return target


@pytest.mark.parametrize("output_format", ("json", "markdown"))
def test_review_cli_reads_portable_public_zip_without_rewriting_it(
    exported: Path, tmp_path: Path, monkeypatch, capsys, output_format,
):
    from godprompt_bench import review

    archive = _public_zip(exported, tmp_path / "public-evidence.zip")
    original = archive.read_bytes()
    monkeypatch.setattr(review, "TemporaryDirectory",
                        lambda **kwargs: TemporaryDirectory(dir=tmp_path, **kwargs))
    monkeypatch.setattr(sys, "argv", [
        "godprompt_bench.review", str(archive), "--format", output_format,
    ])

    review.main()
    rendered = capsys.readouterr().out
    if output_format == "json":
        assert json.loads(rendered)["run_id"] == "sample-run"
    else:
        assert "sample-run" in rendered and "not independently verified" in rendered
    assert archive.read_bytes() == original
    assert sorted(path.name for path in tmp_path.iterdir()) == ["public-evidence.zip", "sample-run"]


def test_comparison_cli_accepts_two_public_zips_with_pin_verification(
    comparable_exports: tuple[Path, Path], tmp_path: Path, monkeypatch, capsys,
):
    from godprompt_bench import review

    before, after = comparable_exports
    earlier = _public_zip(before, tmp_path / "earlier.zip")
    later = _public_zip(after, tmp_path / "later.zip")
    argv = ["godprompt_bench.review", str(earlier), "--compare", str(later)]
    for side, folder in (("before", before), ("after", after)):
        for name in ("manifest.json", "summary.json", "scores.csv"):
            argv += ["--require-public-artifact-sha256",
                     f"{side}:{name}={hashlib.sha256((folder / name).read_bytes()).hexdigest()}"]
    monkeypatch.setattr(sys, "argv", argv)

    review.main()
    assert json.loads(capsys.readouterr().out)["metadata_aligned"] is True


@pytest.mark.parametrize("invalid", ("extra", "traversal", "duplicate", "missing", "symlink", "oversize", "corrupt"))
def test_review_cli_rejects_unsafe_or_incomplete_public_zips(
    exported: Path, tmp_path: Path, monkeypatch, capsys, invalid,
):
    from godprompt_bench import review

    archive = tmp_path / f"{invalid}.zip"
    monkeypatch.setattr(review, "TemporaryDirectory",
                        lambda **kwargs: TemporaryDirectory(dir=tmp_path, **kwargs))
    if invalid == "corrupt":
        archive.write_bytes(b"not a ZIP")
    elif invalid in ("missing", "symlink", "oversize"):
        with ZipFile(archive, "w", compression=ZIP_DEFLATED) as output:
            for name in ("manifest.json", "summary.json", "scores.csv"):
                if invalid == "missing" and name == "scores.csv":
                    continue
                if invalid == "symlink" and name == "summary.json":
                    entry = ZipInfo(name)
                    entry.create_system = 3
                    entry.external_attr = (S_IFLNK | 0o777) << 16
                    output.writestr(entry, "elsewhere")
                elif invalid == "oversize" and name == "summary.json":
                    output.writestr(name, b"x" * 2_000_001)
                else:
                    output.write(exported / name, arcname=name)
    else:
        _public_zip(exported, archive)
        with ZipFile(archive, "a", compression=ZIP_DEFLATED) as output:
            if invalid == "extra":
                output.writestr("trajectory.jsonl", "private")
            elif invalid == "traversal":
                output.writestr("../outside", "private")
            elif invalid == "duplicate":
                with pytest.warns(UserWarning, match="Duplicate name"):
                    output.writestr("manifest.json", "{}")
    monkeypatch.setattr(sys, "argv", ["godprompt_bench.review", str(archive)])
    with pytest.raises(SystemExit) as exc:
        review.main()
    assert exc.value.code == 2
    assert "zip" in capsys.readouterr().err.lower()
    assert not list(tmp_path.glob("godprompt_public_review_*"))


def test_review_cli_reports_invalid_deflate_stream_and_cleans_temp_files(
    exported: Path, tmp_path: Path, monkeypatch, capsys,
):
    from godprompt_bench import review

    archive = _public_zip(exported, tmp_path / "broken-deflate.zip")
    with ZipFile(archive) as source:
        entry = source.getinfo("manifest.json")
        assert entry.compress_type == ZIP_DEFLATED
        assert entry.compress_size > 0

    content = bytearray(archive.read_bytes())
    header = entry.header_offset
    name_length = int.from_bytes(content[header + 26:header + 28], "little")
    extra_length = int.from_bytes(content[header + 28:header + 30], "little")
    payload_offset = header + 30 + name_length + extra_length
    content[payload_offset] = 0x06  # Reserved DEFLATE block type, not valid input.
    archive.write_bytes(content)

    monkeypatch.setattr(review, "TemporaryDirectory",
                        lambda **kwargs: TemporaryDirectory(dir=tmp_path, **kwargs))
    monkeypatch.setattr(sys, "argv", ["godprompt_bench.review", str(archive)])
    with pytest.raises(SystemExit) as exc:
        review.main()
    assert exc.value.code == 2
    assert "invalid public evidence ZIP" in capsys.readouterr().err
    assert not list(tmp_path.glob("godprompt_public_review_*"))


def test_public_evidence_packer_roundtrips_with_offline_reviewer(exported: Path, tmp_path: Path):
    from contextlib import ExitStack
    from godprompt_bench.pack import pack_public_evidence
    from godprompt_bench.review import _public_zip_directory, review_result

    first = tmp_path / "first.zip"
    second = tmp_path / "second.zip"
    receipt = pack_public_evidence(exported, first)
    pack_public_evidence(exported, second)
    assert first.read_bytes() == second.read_bytes()
    assert receipt["public_zip_sha256"] == hashlib.sha256(first.read_bytes()).hexdigest()
    assert receipt["performance_claim_verified"] is False
    with ZipFile(first) as archive:
        assert archive.namelist() == ["manifest.json", "summary.json", "scores.csv"]
        assert "trajectories.jsonl" not in archive.namelist()
    with ExitStack() as stack:
        report = review_result(_public_zip_directory(first, stack))
    assert receipt["public_artifact_sha256"] == report["public_artifact_sha256"]


def test_public_evidence_packer_cli_reports_hashes(exported: Path, tmp_path: Path, monkeypatch, capsys):
    from godprompt_bench import pack

    output = tmp_path / "share.zip"
    monkeypatch.setattr(sys, "argv", ["godprompt_bench.pack", str(exported), str(output)])
    pack.main()
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["public_zip_sha256"] == hashlib.sha256(output.read_bytes()).hexdigest()
    assert receipt["public_artifact_sha256"]["manifest.json"] == hashlib.sha256(
        (exported / "manifest.json").read_bytes()
    ).hexdigest()


@pytest.mark.parametrize("invalid", (
    "missing_source", "malformed_summary", "existing_target", "non_zip",
    "missing_parent", "oversized_score", "changed_after_review",
))
def test_public_evidence_packer_fails_closed_without_writing_target(
    exported: Path, tmp_path: Path, monkeypatch, invalid,
):
    from godprompt_bench import pack

    source = exported
    target = tmp_path / "receipt.zip"
    if invalid == "missing_source":
        source = tmp_path / "missing"
    elif invalid == "malformed_summary":
        (exported / "summary.json").write_text("{}", encoding="utf-8")
    elif invalid == "existing_target":
        target.write_bytes(b"existing owner data")
    elif invalid == "non_zip":
        target = tmp_path / "receipt.txt"
    elif invalid == "missing_parent":
        target = tmp_path / "not-created" / "receipt.zip"
    elif invalid == "oversized_score":
        (exported / "scores.csv").write_bytes(b"x" * 20_000_001)
    elif invalid == "changed_after_review":
        original = pack.review_result

        def change_after_validation(folder):
            report = original(folder)
            (folder / "manifest.json").write_text(
                (folder / "manifest.json").read_text(encoding="utf-8") + " ",
                encoding="utf-8",
            )
            return report

        monkeypatch.setattr(pack, "review_result", change_after_validation)
    with pytest.raises((ValueError, OSError)):
        pack.pack_public_evidence(source, target)
    if invalid == "existing_target":
        assert target.read_bytes() == b"existing owner data"
    else:
        assert not target.exists()


def test_public_evidence_packer_keeps_private_trajectories_out(exported: Path, tmp_path: Path):
    from godprompt_bench.pack import pack_public_evidence

    (exported / "trajectories.jsonl").write_text("private sentinel not for buyers", encoding="utf-8")
    output = tmp_path / "buyer.zip"
    pack_public_evidence(exported, output)
    assert b"private sentinel" not in output.read_bytes()


@pytest.mark.parametrize("output_format", ("json", "markdown"))
@pytest.mark.parametrize("digest_case", ("lower", "upper"))
def test_review_cli_accepts_independent_whole_zip_sha256(
    exported: Path, tmp_path: Path, monkeypatch, capsys, output_format, digest_case,
):
    from godprompt_bench import review
    from godprompt_bench.pack import pack_public_evidence

    archive = tmp_path / "buyer.zip"
    receipt = pack_public_evidence(exported, archive)
    original = archive.read_bytes()
    pin = receipt["public_zip_sha256"]
    if digest_case == "upper":
        pin = pin.upper()
    monkeypatch.setattr(sys, "argv", [
        "godprompt_bench.review", str(archive), "--format", output_format,
        "--require-public-zip-sha256", pin,
    ])
    review.main()
    assert capsys.readouterr().out
    assert archive.read_bytes() == original


def test_review_cli_whole_zip_mismatch_reports_review_first(
    exported: Path, tmp_path: Path, monkeypatch, capsys,
):
    from godprompt_bench import review
    from godprompt_bench.pack import pack_public_evidence

    archive = tmp_path / "buyer.zip"
    pack_public_evidence(exported, archive)
    monkeypatch.setattr(sys, "argv", [
        "godprompt_bench.review", str(archive),
        "--require-public-zip-sha256", "0" * 64,
    ])
    with pytest.raises(SystemExit) as exc:
        review.main()
    assert exc.value.code == 1
    output = capsys.readouterr()
    assert '"review_only": true' in output.out
    assert "ZIP SHA256 mismatch" in output.err


@pytest.mark.parametrize("pins", [
    ["bad"], ["G" * 64], ["0" * 64, "0" * 64],
    ["before:" + "0" * 64], ["after:" + "0" * 64],
])
def test_review_cli_rejects_invalid_or_ambiguous_single_zip_pin(
    exported: Path, tmp_path: Path, monkeypatch, capsys, pins,
):
    from godprompt_bench import review
    from godprompt_bench.pack import pack_public_evidence

    archive = tmp_path / "buyer.zip"
    pack_public_evidence(exported, archive)
    argv = ["godprompt_bench.review", str(archive)]
    for pin in pins:
        argv.extend(["--require-public-zip-sha256", pin])
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(SystemExit) as exc:
        review.main()
    assert exc.value.code == 2
    assert "public-zip-sha256" in capsys.readouterr().err


def test_review_cli_whole_zip_pin_requires_zip_not_directory(
    exported: Path, monkeypatch, capsys,
):
    from godprompt_bench import review

    monkeypatch.setattr(sys, "argv", [
        "godprompt_bench.review", str(exported),
        "--require-public-zip-sha256", "0" * 64,
    ])
    with pytest.raises(SystemExit) as exc:
        review.main()
    assert exc.value.code == 2
    assert "ZIP" in capsys.readouterr().err


def test_review_cli_comparison_requires_two_independent_whole_zip_pins(
    comparable_exports: tuple[Path, Path], tmp_path: Path, monkeypatch, capsys,
):
    from godprompt_bench import review
    from godprompt_bench.pack import pack_public_evidence

    first = tmp_path / "before.zip"
    second = tmp_path / "after.zip"
    before = pack_public_evidence(comparable_exports[0], first)["public_zip_sha256"]
    after = pack_public_evidence(comparable_exports[1], second)["public_zip_sha256"]
    argv = ["godprompt_bench.review", str(first), "--compare", str(second)]
    monkeypatch.setattr(sys, "argv", argv + [
        "--require-public-zip-sha256", "before:" + before,
    ])
    with pytest.raises(SystemExit) as exc:
        review.main()
    assert exc.value.code == 2
    capsys.readouterr()
    monkeypatch.setattr(sys, "argv", argv + [
        "--require-public-zip-sha256", "before:" + before.upper(),
        "--require-public-zip-sha256", "after:" + after.upper(),
    ])
    review.main()
    assert '"before"' in capsys.readouterr().out
    monkeypatch.setattr(sys, "argv", argv + [
        "--require-public-zip-sha256", "before:" + before,
        "--require-public-zip-sha256", "after:" + "0" * 64,
    ])
    with pytest.raises(SystemExit) as mismatch:
        review.main()
    assert mismatch.value.code == 1
    output = capsys.readouterr()
    assert '"after"' in output.out and "after" in output.err


def test_review_cli_rejects_zip_changed_after_unpack_even_with_same_stat(
    exported: Path, tmp_path: Path, monkeypatch, capsys,
):
    from godprompt_bench import review
    from godprompt_bench.pack import pack_public_evidence

    archive = tmp_path / "buyer.zip"
    expected = pack_public_evidence(exported, archive)["public_zip_sha256"]
    before = archive.stat()
    original_unpack = review._public_zip_directory

    def change_after_unpack(source, stack):
        extracted = original_unpack(source, stack)
        content = bytearray(source.read_bytes())
        content[0] ^= 1
        source.write_bytes(content)
        os.utime(source, ns=(before.st_atime_ns, before.st_mtime_ns))
        assert source.stat().st_size == before.st_size
        assert source.stat().st_mtime_ns == before.st_mtime_ns
        return extracted

    monkeypatch.setattr(review, "_public_zip_directory", change_after_unpack)
    monkeypatch.setattr(sys, "argv", [
        "godprompt_bench.review", str(archive),
        "--require-public-zip-sha256", expected,
    ])
    with pytest.raises(SystemExit) as exc:
        review.main()
    assert exc.value.code == 2
    assert "changed during review" in capsys.readouterr().err
