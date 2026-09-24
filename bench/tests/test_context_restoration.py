from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_context_restoration_binds_recovery_artifacts_to_session_provenance() -> None:
    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")

    assert "recovery transcript, log, scratch path, or artifact" in skill
    assert "active task/session/agent" in skill
    assert "provenance is unknown or mismatched" in skill
    assert "do not treat it as this execution's history" in skill


def test_compiled_prompt_preserves_context_recovery_provenance_guard() -> None:
    compiled = (ROOT / "GodPrompt.md").read_text(encoding="utf-8")

    assert "recovery transcript, log, scratch path, or artifact" in compiled
    assert "active task/session/agent" in compiled
    assert "do not treat it as this execution's history" in compiled
