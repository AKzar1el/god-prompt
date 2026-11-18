"""Offline governance checks for an opt-in held-out benchmark corpus."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import godprompt_bench.heldout as heldout_module
from godprompt_bench.heldout import FAILURE_MODES, preflight_heldout_corpus

ROOT = Path(__file__).parents[1]


@pytest.fixture
def manifests(tmp_path: Path):
    reference = ROOT / "tasks" / "manifest.json"
    source = json.loads(reference.read_text(encoding="utf-8"))
    tasks = []
    for index in range(2):
        task = dict(source[index])
        task["id"] = f"heldout-fixture-{index + 1}"
        task["fixture_dir"] = f"private-fixtures/heldout-{index + 1}"
        task["user_prompt"] = f"Synthetic held-out case {index + 1}. PRIVATE_PROMPT_SENTINEL"
        task["verifier_command"] = [
            "python3", ".godprompt_verifier.py", task["id"]
        ]
        tasks.append(task)
    heldout = tmp_path / "heldout_tasks.json"
    heldout.write_text(json.dumps(tasks), encoding="utf-8")
    sidecar = tmp_path / "failure_modes.json"
    cases = [
        {"id": tasks[0]["id"], "failure_mode": "false_completion"},
        {"id": tasks[1]["id"], "failure_mode": "scope_creep"},
    ]
    sidecar.write_text(
        json.dumps({"schema": "godprompt.heldout_modes.v1", "cases": cases}),
        encoding="utf-8",
    )
    return reference, heldout, sidecar, tasks, cases


def test_offline_preflight_is_disjoint_and_does_not_leak_prompts_or_verifiers(manifests):
    reference, heldout, sidecar, _, _ = manifests
    before = reference.read_bytes()
    result = preflight_heldout_corpus(reference, heldout, sidecar)
    assert result["preview_only"] is True
    assert result["reference_task_count"] == 40
    assert result["heldout_task_count"] == 2
    assert result["failure_mode_counts"] == {
        "false_completion": 1, "scope_creep": 1,
    }
    assert len(result["uncovered_failure_modes"]) == len(FAILURE_MODES) - 2
    assert result["reference_manifest_sha256"].startswith("sha256:")
    assert result["heldout_manifest_sha256"].startswith("sha256:")
    assert result["mode_manifest_sha256"].startswith("sha256:")
    serialized = json.dumps(result)
    assert "PRIVATE_PROMPT_SENTINEL" not in serialized
    assert ".godprompt_verifier.py" not in serialized
    assert reference.read_bytes() == before


def test_reference_task_id_casefold_overlap_is_rejected(manifests):
    reference, heldout, sidecar, tasks, cases = manifests
    original = json.loads(reference.read_text(encoding="utf-8"))[0]["id"]
    tasks[0]["id"] = original.upper()
    heldout.write_text(json.dumps(tasks), encoding="utf-8")
    cases[0]["id"] = original.upper()
    sidecar.write_text(
        json.dumps({"schema": "godprompt.heldout_modes.v1", "cases": cases}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="reference task ID"):
        preflight_heldout_corpus(reference, heldout, sidecar)


def test_reference_fixture_casefold_overlap_is_rejected(manifests):
    reference, heldout, sidecar, tasks, _ = manifests
    tasks[0]["fixture_dir"] = json.loads(reference.read_text(encoding="utf-8"))[0]["fixture_dir"].upper()
    heldout.write_text(json.dumps(tasks), encoding="utf-8")
    with pytest.raises(ValueError, match="reference fixture"):
        preflight_heldout_corpus(reference, heldout, sidecar)


@pytest.mark.parametrize("mode", ["new_unreviewed_mode", "", None, 2])
def test_unrecognized_failure_family_is_rejected(manifests, mode):
    reference, heldout, sidecar, _, cases = manifests
    cases[0]["failure_mode"] = mode
    sidecar.write_text(
        json.dumps({"schema": "godprompt.heldout_modes.v1", "cases": cases}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="failure mode"):
        preflight_heldout_corpus(reference, heldout, sidecar)


def test_missing_and_extra_sidecar_case_are_rejected(manifests):
    reference, heldout, sidecar, _, cases = manifests
    for invalid in [cases[:1], cases + [{"id": "unknown-heldout", "failure_mode": "stale_context"}]]:
        sidecar.write_text(
            json.dumps({"schema": "godprompt.heldout_modes.v1", "cases": invalid}),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="exactly match"):
            preflight_heldout_corpus(reference, heldout, sidecar)


def test_casefold_duplicate_sidecar_ids_are_rejected(manifests):
    reference, heldout, sidecar, _, cases = manifests
    cases[1]["id"] = cases[0]["id"].upper()
    sidecar.write_text(
        json.dumps({"schema": "godprompt.heldout_modes.v1", "cases": cases}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate case ID"):
        preflight_heldout_corpus(reference, heldout, sidecar)


def test_duplicate_json_security_key_is_rejected(manifests):
    reference, heldout, sidecar, _, _ = manifests
    sidecar.write_text(
        '{"schema":"godprompt.heldout_modes.v1","cases":[],'
        '"cases":[{"id":"fake","failure_mode":"scope_creep"}]}',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate JSON key"):
        preflight_heldout_corpus(reference, heldout, sidecar)


@pytest.mark.parametrize("mutate", [
    lambda obj: obj.update(schema="unknown"),
    lambda obj: obj.update(unreviewed=True),
    lambda obj: obj["cases"][0].update(hidden_verifier="do not expose"),
])
def test_unknown_schema_or_hidden_verifier_in_sidecar_is_rejected(manifests, mutate):
    reference, heldout, sidecar, _, cases = manifests
    obj = {"schema": "godprompt.heldout_modes.v1", "cases": cases}
    mutate(obj)
    sidecar.write_text(json.dumps(obj), encoding="utf-8")
    with pytest.raises(ValueError, match="schema|unknown fields"):
        preflight_heldout_corpus(reference, heldout, sidecar)


def test_fixture_traversal_is_rejected_before_any_external_execution(manifests):
    reference, heldout, sidecar, tasks, _ = manifests
    tasks[0]["fixture_dir"] = "../secrets"
    heldout.write_text(json.dumps(tasks), encoding="utf-8")
    with pytest.raises(ValueError, match="safe relative path"):
        preflight_heldout_corpus(reference, heldout, sidecar)


def test_manifest_changed_during_validation_refuses_stale_fingerprint(
    manifests, monkeypatch
):
    reference, heldout, sidecar, _, _ = manifests
    original = heldout_module.load_manifest

    def changing_loader(path):
        tasks = original(path)
        if Path(path).resolve() == heldout.resolve():
            with heldout.open("a", encoding="utf-8") as stream:
                stream.write(" ")
        return tasks

    monkeypatch.setattr(heldout_module, "load_manifest", changing_loader)
    with pytest.raises(ValueError, match="changed during validation"):
        preflight_heldout_corpus(reference, heldout, sidecar)
