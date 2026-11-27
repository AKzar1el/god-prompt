"""Offline, no-provider checks for the opt-in Bench 2.0 paired plan."""
from __future__ import annotations

import io
import json
from pathlib import Path
import sys

import pytest

import godprompt_bench.three_arm as three_arm
from godprompt_bench.heldout import preflight_heldout_corpus
from godprompt_bench.mcp_contract_adapter import MCP_RELEASE_SHA


ROOT = Path(__file__).parents[1]
SHA = "sha256:" + "a" * 64


@pytest.fixture
def inputs(tmp_path: Path):
    reference = ROOT / "tasks" / "manifest.json"
    public = json.loads(reference.read_text(encoding="utf-8"))
    tasks = []
    for n in range(2):
        task = dict(public[n])
        task["id"] = f"private-case-{n + 1}"
        task["fixture_dir"] = f"private/fixture-{n + 1}"
        task["user_prompt"] = "SENSITIVE_HELDOUT_PROMPT"
        tasks.append(task)
    heldout = tmp_path / "heldout.json"
    heldout.write_text(json.dumps(tasks), encoding="utf-8")
    modes = tmp_path / "modes.json"
    modes.write_text(json.dumps({
        "schema": "godprompt.heldout_modes.v1",
        "cases": [
            {"id": tasks[0]["id"], "failure_mode": "false_completion"},
            {"id": tasks[1]["id"], "failure_mode": "scope_creep"},
        ],
    }), encoding="utf-8")
    corpus = preflight_heldout_corpus(reference, heldout, modes)
    plan = {
        "schema": "godprompt.three_arm_plan.v1",
        "arms": ["baseline", "godprompt", "godprompt_mcp_contract"],
        "corpus": {
            "reference_sha256": corpus["reference_manifest_sha256"],
            "heldout_sha256": corpus["heldout_manifest_sha256"],
            "modes_sha256": corpus["mode_manifest_sha256"],
        },
        "model": {
            "provider": "mockllm",
            "id": "mockllm/test",
            "temperature": 0,
            "seed": 1234,
        },
        "limits": {
            "epochs": 2, "max_messages": 15,
            "max_time_seconds": 120, "max_output_tokens": 2048,
        },
        "controls": {
            "source_commit": "b" * 40,
            "sandbox_compose_sha256": SHA,
            "tool_inventory_sha256": SHA,
            "approval_policy_sha256": SHA,
            "baseline_prompt_sha256": SHA,
            "godprompt_prompt_sha256": SHA,
            "mcp_release_sha": MCP_RELEASE_SHA,
        },
    }
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan), encoding="utf-8")
    return path, reference, heldout, modes, plan


def _preflight(inputs):
    return three_arm.preflight_three_arm_plan(*inputs[:4])


@pytest.mark.parametrize("size", [65535, 65536, 65537, 131072])
def test_plan_read_bounds_consumption_even_if_stat_is_stale(tmp_path, monkeypatch, size):
    path = tmp_path / "plan.json"
    path.write_bytes(b"{}")
    data = b" " * size
    reads = []
    original_open = Path.open

    class TrackedStream(io.BytesIO):
        def read(self, size=-1):
            reads.append(size)
            return super().read(size)

    def open_snapshot(self, *args, **kwargs):
        if self == path:
            return TrackedStream(data)
        return original_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", open_snapshot)
    if size > 65536:
        with pytest.raises(ValueError, match="64 KiB limit"):
            three_arm._read_plan(path)
    else:
        assert three_arm._read_plan(path) == data
    assert reads == [65537]


def test_exact_three_arm_paired_preview_has_no_model_or_private_content(inputs):
    path, reference, heldout, modes, plan = inputs
    before = tuple(p.read_bytes() for p in (reference, heldout, modes, path))
    result = _preflight(inputs)
    assert result["schema"] == "godprompt.three_arm_preview.v1"
    assert result["preview_only"] is True
    assert result["arms"] == plan["arms"]
    assert result["heldout_task_count"] == 2
    assert result["epochs"] == 2
    assert result["samples_per_arm"] == 4
    assert result["total_planned_samples"] == 12
    assert result["cost_estimate_usd"] is None
    assert result["plan_sha256"].startswith("sha256:")
    assert "SENSITIVE_HELDOUT_PROMPT" not in json.dumps(result)
    assert "mockllm/test" not in json.dumps(result)
    assert tuple(p.read_bytes() for p in (reference, heldout, modes, path)) == before


@pytest.mark.parametrize("arms", [
    ["baseline", "godprompt"],
    ["baseline", "godprompt_mcp_contract", "godprompt"],
    ["baseline", "godprompt", "godprompt_mcp_contract", "extra"],
    ["baseline", "baseline", "godprompt_mcp_contract"],
])
def test_wrong_arm_count_order_or_identity_fails_closed(inputs, arms):
    path, *_, plan = inputs
    plan["arms"] = arms
    path.write_text(json.dumps(plan), encoding="utf-8")
    with pytest.raises(ValueError, match="exactly three|arms"):
        _preflight(inputs)


@pytest.mark.parametrize("field", ["reference_sha256", "heldout_sha256", "modes_sha256"])
def test_stale_or_fabricated_corpus_fingerprint_rejected(inputs, field):
    path, *_, plan = inputs
    plan["corpus"][field] = "sha256:" + "0" * 64
    path.write_text(json.dumps(plan), encoding="utf-8")
    with pytest.raises(ValueError, match="fingerprint"):
        _preflight(inputs)


@pytest.mark.parametrize("mutate", [
    lambda plan: plan.update(unknown_flag=True),
    lambda plan: plan["controls"].update(allow_paid_execution=True),
    lambda plan: plan["model"].update(api_key="secret"),
    lambda plan: plan.update(schema="wrong"),
])
def test_unknown_fields_and_execution_switches_rejected(inputs, mutate):
    path, *_, plan = inputs
    mutate(plan)
    path.write_text(json.dumps(plan), encoding="utf-8")
    with pytest.raises(ValueError, match="schema|fields"):
        _preflight(inputs)


@pytest.mark.parametrize("field,value", [
    ("epochs", 0), ("epochs", True), ("epochs", 20),
    ("max_messages", 500), ("max_output_tokens", -1),
])
def test_nonpositive_boolean_or_over_budget_limits_rejected(inputs, field, value):
    path, *_, plan = inputs
    plan["limits"][field] = value
    path.write_text(json.dumps(plan), encoding="utf-8")
    with pytest.raises(ValueError, match="limit|budget"):
        _preflight(inputs)


@pytest.mark.parametrize("field,value", [
    ("temperature", float("nan")), ("temperature", "0"),
    ("temperature", 10**400), ("temperature", -(10**400)),
    ("temperature", float("inf")), ("temperature", True),
    ("seed", True), ("seed", -1), ("id", "model?api_key=secret"),
])
def test_nonfinite_malformed_or_credential_like_model_settings_rejected(inputs, field, value):
    path, *_, plan = inputs
    plan["model"][field] = value
    path.write_text(json.dumps(plan), encoding="utf-8")
    with pytest.raises(ValueError, match="model|seed|temperature"):
        _preflight(inputs)


@pytest.mark.parametrize("temperature", [0, 1.5, 2])
def test_bounded_temperature_accepted(inputs, temperature):
    path, *_, plan = inputs
    plan["model"]["temperature"] = temperature
    path.write_text(json.dumps(plan), encoding="utf-8")
    assert _preflight(inputs)["preview_only"] is True


def test_unreleased_mcp_sha_and_missing_control_rejected(inputs):
    path, *_, plan = inputs
    plan["controls"]["mcp_release_sha"] = "0" * 40
    path.write_text(json.dumps(plan), encoding="utf-8")
    with pytest.raises(ValueError, match="MCP release"):
        _preflight(inputs)
    del plan["controls"]["approval_policy_sha256"]
    path.write_text(json.dumps(plan), encoding="utf-8")
    with pytest.raises(ValueError, match="control|fields"):
        _preflight(inputs)


def test_duplicate_json_fields_rejected_before_preview(inputs):
    path, *_ = inputs
    path.write_text(
        '{"schema":"godprompt.three_arm_plan.v1","schema":"override"}',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate JSON key"):
        _preflight(inputs)


def test_plan_changed_during_corpus_validation_is_rejected(inputs, monkeypatch):
    path, *_ = inputs
    original = three_arm.preflight_heldout_corpus

    def changing(*args):
        result = original(*args)
        path.write_text(path.read_text(encoding="utf-8") + " ", encoding="utf-8")
        return result

    monkeypatch.setattr(three_arm, "preflight_heldout_corpus", changing)
    with pytest.raises(ValueError, match="changed during validation"):
        _preflight(inputs)


def test_cli_returns_offline_json_preview_without_private_inputs(
    inputs, monkeypatch, capsys
):
    path, reference, heldout, modes, _ = inputs
    monkeypatch.setattr(sys, "argv", [
        "three_arm", "--plan", str(path), "--reference", str(reference),
        "--heldout", str(heldout), "--modes", str(modes),
    ])
    three_arm.main()
    printed = capsys.readouterr().out
    assert json.loads(printed)["total_planned_samples"] == 12
    assert "SENSITIVE_HELDOUT_PROMPT" not in printed
    assert "mockllm/test" not in printed
