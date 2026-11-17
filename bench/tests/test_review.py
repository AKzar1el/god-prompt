from __future__ import annotations

import csv
import json
import sys
from dataclasses import replace
from pathlib import Path

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


def test_review_refuses_changed_summary(exported: Path):
    from godprompt_bench.review import review_result

    path = exported / "summary.json"
    summary = json.loads(path.read_text(encoding="utf-8"))
    summary["baseline"]["passed"] = 0
    path.write_text(json.dumps(summary), encoding="utf-8")
    with pytest.raises(ValueError, match="summary does not match"):
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
    assert report["before"]["run_id"] == "sample-run"
    assert report["after"]["run_id"] == "later-run"
    assert "mock_model" in report["before"]["cautions"]
    assert {p.name: p.read_bytes() for p in before.iterdir()} == before_files
    assert {p.name: p.read_bytes() for p in after.iterdir()} == after_files


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
