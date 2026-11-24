"""Offline governance checks for an opt-in held-out benchmark corpus."""
from __future__ import annotations

import json
import sys
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


def _make_private_fixtures(root: Path, tasks: list[dict]) -> None:
    for task in tasks:
        path = root / task["fixture_dir"] / "fixture.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "files": {"main.py": "print('private starter')"},
            "hidden_verifier": "PRIVATE_HIDDEN_VERIFIER_SENTINEL",
            "starter_expected_pass": False,
        }), encoding="utf-8")


def test_opt_in_fixture_fingerprint_freezes_hidden_bundle_bytes_without_disclosure(manifests, tmp_path):
    reference, heldout, sidecar, tasks, _ = manifests
    _make_private_fixtures(tmp_path, tasks)
    base = preflight_heldout_corpus(reference, heldout, sidecar)
    assert "fixture_bundle_sha256" not in base
    report = preflight_heldout_corpus(reference, heldout, sidecar, fixture_root=tmp_path)
    assert report["fixture_bundle_count"] == 2
    assert report["fixture_bundle_sha256"].startswith("sha256:")
    assert "PRIVATE_HIDDEN_VERIFIER_SENTINEL" not in json.dumps(report)
    assert report["heldout_manifest_sha256"] == base["heldout_manifest_sha256"]
    target = tmp_path / tasks[0]["fixture_dir"] / "fixture.json"
    target.write_text(target.read_text(encoding="utf-8").replace(
        "PRIVATE_HIDDEN_VERIFIER_SENTINEL", "CHANGED_PRIVATE_VERIFIER"
    ), encoding="utf-8")
    changed = preflight_heldout_corpus(reference, heldout, sidecar, fixture_root=tmp_path)
    assert changed["fixture_bundle_sha256"] != report["fixture_bundle_sha256"]
    assert changed["heldout_manifest_sha256"] == report["heldout_manifest_sha256"]


def test_fixture_fingerprint_is_independent_of_manifest_order(manifests, tmp_path):
    reference, heldout, sidecar, tasks, cases = manifests
    _make_private_fixtures(tmp_path, tasks)
    first = preflight_heldout_corpus(reference, heldout, sidecar, fixture_root=tmp_path)
    heldout.write_text(json.dumps(list(reversed(tasks))), encoding="utf-8")
    sidecar.write_text(json.dumps({
        "schema": "godprompt.heldout_modes.v1", "cases": list(reversed(cases)),
    }), encoding="utf-8")
    second = preflight_heldout_corpus(reference, heldout, sidecar, fixture_root=tmp_path)
    assert second["fixture_bundle_sha256"] == first["fixture_bundle_sha256"]


def test_expected_report_gate_accepts_unchanged_private_corpus(manifests, tmp_path):
    reference, heldout, sidecar, tasks, _ = manifests
    _make_private_fixtures(tmp_path, tasks)
    initial = preflight_heldout_corpus(reference, heldout, sidecar, fixture_root=tmp_path)
    lock = tmp_path / "frozen-preflight.json"
    lock.write_text(json.dumps(initial), encoding="utf-8")
    checked = preflight_heldout_corpus(
        reference, heldout, sidecar, fixture_root=tmp_path, expected_report=lock,
    )
    assert checked["input_fingerprints_match"] is True
    assert checked["fixture_bundle_sha256"] == initial["fixture_bundle_sha256"]
    assert "PRIVATE_HIDDEN_VERIFIER_SENTINEL" not in json.dumps(checked)


def test_expected_report_gate_rejects_private_verifier_drift(manifests, tmp_path):
    reference, heldout, sidecar, tasks, _ = manifests
    _make_private_fixtures(tmp_path, tasks)
    initial = preflight_heldout_corpus(reference, heldout, sidecar, fixture_root=tmp_path)
    lock = tmp_path / "frozen-preflight.json"
    lock.write_text(json.dumps(initial), encoding="utf-8")
    target = tmp_path / tasks[0]["fixture_dir"] / "fixture.json"
    target.write_text(target.read_text(encoding="utf-8").replace(
        "PRIVATE_HIDDEN_VERIFIER_SENTINEL", "PRIVATE_MODIFIED_VERIFIER",
    ), encoding="utf-8")
    with pytest.raises(ValueError, match="fixture_bundle_sha256") as error:
        preflight_heldout_corpus(
            reference, heldout, sidecar, fixture_root=tmp_path, expected_report=lock,
        )
    assert "PRIVATE_MODIFIED_VERIFIER" not in str(error.value)


def test_expected_report_gate_rejects_manifest_byte_drift(manifests, tmp_path):
    reference, heldout, sidecar, tasks, _ = manifests
    _make_private_fixtures(tmp_path, tasks)
    initial = preflight_heldout_corpus(reference, heldout, sidecar, fixture_root=tmp_path)
    lock = tmp_path / "frozen-preflight.json"
    lock.write_text(json.dumps(initial), encoding="utf-8")
    heldout.write_text(heldout.read_text(encoding="utf-8") + " ", encoding="utf-8")
    with pytest.raises(ValueError, match="heldout_manifest_sha256"):
        preflight_heldout_corpus(
            reference, heldout, sidecar, fixture_root=tmp_path, expected_report=lock,
        )


def test_expected_report_requires_full_fixture_check(manifests, tmp_path):
    reference, heldout, sidecar, _, _ = manifests
    lock = tmp_path / "frozen-preflight.json"
    lock.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="fixture_root"):
        preflight_heldout_corpus(reference, heldout, sidecar, expected_report=lock)


def test_expected_report_rejects_incomplete_or_malformed_lock(manifests, tmp_path):
    reference, heldout, sidecar, tasks, _ = manifests
    _make_private_fixtures(tmp_path, tasks)
    initial = preflight_heldout_corpus(reference, heldout, sidecar, fixture_root=tmp_path)
    lock = tmp_path / "frozen-preflight.json"
    for bad in ({key: val for key, val in initial.items() if key != "fixture_bundle_sha256"},
                {**initial, "schema": "other"},
                {**initial, "fixture_bundle_sha256": "sha256:not-a-hash"}):
        lock.write_text(json.dumps(bad), encoding="utf-8")
        with pytest.raises(ValueError, match="expected report"):
            preflight_heldout_corpus(
                reference, heldout, sidecar, fixture_root=tmp_path, expected_report=lock,
            )


def test_expected_report_cli_checks_frozen_private_inputs(manifests, tmp_path, monkeypatch, capsys):
    reference, heldout, sidecar, tasks, _ = manifests
    _make_private_fixtures(tmp_path, tasks)
    initial = preflight_heldout_corpus(reference, heldout, sidecar, fixture_root=tmp_path)
    lock = tmp_path / "frozen-preflight.json"
    lock.write_text(json.dumps(initial), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", [
        "heldout", "--reference", str(reference), "--heldout", str(heldout),
        "--modes", str(sidecar), "--fixture-root", str(tmp_path),
        "--expected-report", str(lock),
    ])
    heldout_module.main()
    assert json.loads(capsys.readouterr().out)["input_fingerprints_match"] is True


def test_opt_in_fixture_fingerprint_rejects_missing_invalid_or_oversized_bundle(manifests, tmp_path):
    reference, heldout, sidecar, tasks, _ = manifests
    with pytest.raises(ValueError, match="missing fixture bundle"):
        preflight_heldout_corpus(reference, heldout, sidecar, fixture_root=tmp_path)
    _make_private_fixtures(tmp_path, tasks)
    target = tmp_path / tasks[0]["fixture_dir"] / "fixture.json"
    target.write_text('{"files":{"main.py":"secret"},"hidden_verifier":"PRIVATE_HIDDEN_VERIFIER_SENTINEL"}', encoding="utf-8")
    with pytest.raises(ValueError, match="invalid held-out fixture bundle") as failure:
        preflight_heldout_corpus(reference, heldout, sidecar, fixture_root=tmp_path)
    assert "PRIVATE_HIDDEN_VERIFIER_SENTINEL" not in str(failure.value)
    target.write_bytes(b"x" * (1024 * 1024 + 1))
    with pytest.raises(ValueError, match="too large"):
        preflight_heldout_corpus(reference, heldout, sidecar, fixture_root=tmp_path)


def test_opt_in_fixture_fingerprint_rejects_symlinked_bundle(manifests, tmp_path):
    reference, heldout, sidecar, tasks, _ = manifests
    _make_private_fixtures(tmp_path, tasks)
    target = tmp_path / tasks[0]["fixture_dir"] / "fixture.json"
    outside = tmp_path / "outside-private.json"
    target.rename(outside)
    try:
        target.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation unavailable on this host")
    with pytest.raises(ValueError, match="linked fixture"):
        preflight_heldout_corpus(reference, heldout, sidecar, fixture_root=tmp_path)


def test_opt_in_minimum_coverage_rejects_incomplete_failure_families(manifests):
    reference, heldout, sidecar, _, _ = manifests
    assert preflight_heldout_corpus(reference, heldout, sidecar)["uncovered_failure_modes"]
    with pytest.raises(ValueError, match="minimum failure-mode coverage"):
        preflight_heldout_corpus(reference, heldout, sidecar, min_cases_per_mode=1)


@pytest.mark.parametrize("minimum", [0, -1, True, 1.5, "2", 10001])
def test_minimum_failure_mode_coverage_rejects_invalid_threshold(manifests, minimum):
    reference, heldout, sidecar, _, _ = manifests
    with pytest.raises(ValueError, match="min_cases_per_mode"):
        preflight_heldout_corpus(reference, heldout, sidecar, min_cases_per_mode=minimum)


def test_opt_in_minimum_coverage_accepts_all_modes_without_leaking_cases(manifests):
    reference, heldout, sidecar, _, _ = manifests
    source = json.loads(reference.read_text(encoding="utf-8"))
    tasks = []
    cases = []
    for index, mode in enumerate(FAILURE_MODES):
        task = dict(source[index])
        task["id"] = f"private-heldout-{index}"
        task["fixture_dir"] = f"private-fixtures/coverage-{index}"
        task["user_prompt"] = "PRIVATE_COVERAGE_SENTINEL"
        tasks.append(task)
        cases.append({"id": task["id"], "failure_mode": mode})
    heldout.write_text(json.dumps(tasks), encoding="utf-8")
    sidecar.write_text(json.dumps({"schema": "godprompt.heldout_modes.v1", "cases": cases}), encoding="utf-8")
    report = preflight_heldout_corpus(reference, heldout, sidecar, min_cases_per_mode=1)
    assert report["uncovered_failure_modes"] == []
    assert all(report["failure_mode_counts"][mode] == 1 for mode in FAILURE_MODES)
    assert "PRIVATE_COVERAGE_SENTINEL" not in json.dumps(report)
    with pytest.raises(ValueError, match="minimum failure-mode coverage"):
        preflight_heldout_corpus(reference, heldout, sidecar, min_cases_per_mode=2)


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
