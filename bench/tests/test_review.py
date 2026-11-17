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
    assert "mock_model" in report["before"]["cautions"]
    assert {p.name: p.read_bytes() for p in before.iterdir()} == before_files
    assert {p.name: p.read_bytes() for p in after.iterdir()} == after_files


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
    assert "Joint baseline/GodPrompt pair transitions" not in render_markdown(report)


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
