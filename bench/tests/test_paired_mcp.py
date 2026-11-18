import json
import math
from pathlib import Path
import subprocess
import sys

import pytest

from godprompt_bench.paired_mcp import (
    ARMS, MAX_FILE_BYTES, SCHEMA, analyze, read_jsonl, validate_row,
)


def row(condition, task="task-a", *, passed=True, epoch=1, seed=7, **changes):
    result = {
        "schema": SCHEMA,
        "task_id": task,
        "category": "implementation",
        "epoch": epoch,
        "seed": seed,
        "condition": condition,
        "model_id": "provider/example-model",
        "fixture_sha256": "a" * 64,
        "controls_sha256": "b" * 64,
        "toolset_sha256": {"baseline": "c", "godprompt": "d", "godprompt_mcp": "e"}[condition] * 64,
        "passed": passed,
        "scope_violation": False,
        "completion_status": "complete",
        "verification_attempts": 1,
        "input_tokens": 100,
        "output_tokens": 25,
        "latency_seconds": 1.0,
        "infrastructure_error": None,
        "contract_id": "sha256:" + "f" * 64 if condition == "godprompt_mcp" else None,
    }
    result.update(changes)
    return result


def triple(task="task-a", *, passes=(True, True, True), **changes):
    return [row(arm, task, passed=passes[i], **changes)
            for i, arm in enumerate(ARMS)]


def test_paired_three_arm_metrics_require_matched_denominators():
    records = triple("one", passes=(False, True, True))
    records += triple("two", passes=(True, True, False))
    report = analyze(records)
    assert report["pairs_total"] == 2
    assert report["pairs_evaluated"] == 2
    assert report["model_evaluations_run"] is False
    assert report["caller_supplied_results"] is True
    assert report["arms"]["baseline"]["pass_rate"] == 0.5
    assert report["arms"]["godprompt"]["pass_rate"] == 1.0
    assert report["arms"]["godprompt_mcp"]["pass_rate"] == 0.5
    assert report["arms"]["godprompt_mcp"]["false_completions"] == 1
    assert report["paired_comparisons"]["baseline_vs_godprompt"] == {
        "matched_pairs": 2, "improved_only": 1, "regressed_only": 0,
        "net_pass_rate_delta": 0.5,
    }
    assert report["paired_comparisons"]["baseline_vs_godprompt_mcp"] == {
        "matched_pairs": 2, "improved_only": 1, "regressed_only": 1,
        "net_pass_rate_delta": 0.0,
    }
    assert report["paired_comparisons"]["godprompt_vs_godprompt_mcp"]["net_pass_rate_delta"] == -0.5
    assert "statistical significance" in " ".join(report["warnings"])
    json.dumps(report, allow_nan=False)


def test_scope_violation_cannot_be_counted_as_success():
    records = triple()
    records[2] = row("godprompt_mcp", passed=True, scope_violation=True)
    report = analyze(records)
    assert report["arms"]["godprompt_mcp"]["pass_rate"] == 0.0
    assert report["arms"]["godprompt_mcp"]["scope_violations"] == 1
    assert report["arms"]["godprompt_mcp"]["false_completions"] == 1
    assert report["paired_comparisons"]["godprompt_vs_godprompt_mcp"]["regressed_only"] == 1


def test_infrastructure_failure_excludes_whole_triple_from_paired_denominator():
    records = triple()
    records[1] = row("godprompt", infrastructure_error="offline sandbox failed")
    report = analyze(records)
    assert report["pairs_total"] == 1
    assert report["pairs_evaluated"] == 0
    assert report["pairs_excluded_infrastructure"] == 1
    for arm in ARMS:
        assert report["arms"][arm]["pass_rate"] is None
        assert report["arms"][arm]["input_tokens_total"] is None
    assert report["paired_comparisons"]["baseline_vs_godprompt_mcp"]["net_pass_rate_delta"] is None


@pytest.mark.parametrize("field,value", [
    ("passed", 1),
    ("scope_violation", "false"),
    ("epoch", True),
    ("seed", -1),
    ("verification_attempts", -2),
    ("input_tokens", 1.25),
    ("output_tokens", -7),
    ("latency_seconds", float("nan")),
    ("latency_seconds", float("inf")),
    ("latency_seconds", -1),
    ("completion_status", "COMPLETED"),
    ("contract_id", "unauthenticated"),
    ("model_id", "bad model name"),
    ("fixture_sha256", "123"),
])
def test_bad_fields_rejected(field, value):
    with pytest.raises(ValueError):
        validate_row(row("godprompt_mcp", **{field: value}))


def test_extra_private_trace_fields_rejected():
    with pytest.raises(ValueError, match="allowlisted"):
        validate_row(row("godprompt_mcp", raw_logs="PRIVATE_TEXT"))


def test_non_mcp_arms_cannot_claim_contract():
    with pytest.raises(ValueError, match="non-MCP"):
        validate_row(row("baseline", contract_id="sha256:" + "f" * 64))


def test_missing_or_duplicate_arms_fail_closed():
    with pytest.raises(ValueError, match="missing comparison arm"):
        analyze(triple()[:2])
    with pytest.raises(ValueError, match="duplicate outcome"):
        analyze(triple() + [row("baseline")])


@pytest.mark.parametrize("field,value", [
    ("model_id", "provider/different"),
    ("fixture_sha256", "0" * 64),
    ("controls_sha256", "1" * 64),
    ("category", "debugging"),
])
def test_mismatched_comparison_controls_rejected(field, value):
    records = triple()
    records[2] = row("godprompt_mcp", **{field: value})
    with pytest.raises(ValueError, match="mismatch across paired arms"):
        analyze(records)


def test_toolset_drift_within_arm_rejected():
    records = triple("task-a") + triple("task-b")
    records[3] = row("baseline", "task-b", toolset_sha256="1" * 64)
    with pytest.raises(ValueError, match="toolset fingerprint drift"):
        analyze(records)


def test_missing_tokens_not_underreported_as_zero_and_finite_median_does_not_overflow():
    records = triple("task-a", latency_seconds=1e308)
    records += triple("task-b", latency_seconds=1e308)
    records[4] = row("godprompt", "task-b", input_tokens=None, latency_seconds=1e308)
    report = analyze(records)
    assert report["arms"]["godprompt"]["input_tokens_total"] is None
    assert report["arms"]["godprompt"]["median_latency_seconds"] == 1e308
    assert math.isfinite(report["arms"]["godprompt"]["median_latency_seconds"])
    assert report["arms"]["godprompt"]["reported_latency_samples"] == 2
    json.dumps(report, allow_nan=False)


def test_jsonl_reader_rejects_duplicate_fields_nonfinite_values_and_symlinks(tmp_path):
    filename = tmp_path / "rows.jsonl"
    filename.write_text('{"schema":"x","schema":"y"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate JSON key"):
        read_jsonl(filename)
    filename.write_text(json.dumps(row("baseline", latency_seconds=float("nan"))) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="non-finite"):
        read_jsonl(filename)
    filename.write_text(json.dumps(row("baseline")) + "\n", encoding="utf-8")
    target = tmp_path / "link.jsonl"
    target.symlink_to(filename)
    with pytest.raises(ValueError, match="symlink"):
        read_jsonl(target)


def test_jsonl_reader_has_strict_bounded_input(tmp_path):
    filename = tmp_path / "rows.jsonl"
    filename.write_bytes(b"x" * (MAX_FILE_BYTES + 1))
    with pytest.raises(ValueError, match="5 MiB"):
        read_jsonl(filename)


def test_cli_is_stdlib_only_and_offline_with_real_temporary_jsonl(tmp_path):
    filename = tmp_path / "samples.jsonl"
    filename.write_text(
        "".join(json.dumps(item) + "\n" for item in triple()),
        encoding="utf-8",
    )
    bench_root = Path(__file__).resolve().parents[1]
    run = subprocess.run(
        [sys.executable, "-m", "godprompt_bench.paired_mcp", "--input", str(filename)],
        cwd=bench_root, capture_output=True, text=True, timeout=10,
        check=False,
    )
    assert run.returncode == 0, run.stderr
    report = json.loads(run.stdout)
    assert report["pairs_total"] == 1
    assert report["pairs_evaluated"] == 1
    assert report["model_evaluations_run"] is False
    assert report["caller_supplied_results"] is True
