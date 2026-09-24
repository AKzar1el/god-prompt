from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_skill_authority_is_source_qualified() -> None:
    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")

    assert "exact instruction/skill source" in skill
    assert "Never transfer trust or an allow decision by name alone" in skill
    assert "shadows/collides with a trusted instruction or skill identifier" in skill
    assert "re-resolve both content and provenance" in skill


def test_compiled_prompt_preserves_source_qualified_authority() -> None:
    compiled = (ROOT / "GodPrompt.md").read_text(encoding="utf-8")

    assert "Never transfer trust or an allow decision by name alone" in compiled
    assert "re-resolve both content and provenance" in compiled


def test_runtime_delivered_skill_content_is_verified() -> None:
    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")

    assert "Runtime-delivery integrity guard" in skill
    assert "effective runtime-delivered/materialized content and source" in skill
    assert "settings/UI version, installer success, cache refresh" in skill
    assert "not proof of delivered bytes" in skill


def test_compiled_prompt_preserves_runtime_delivery_integrity_guard() -> None:
    compiled = (ROOT / "GodPrompt.md").read_text(encoding="utf-8")

    assert "Runtime-delivery integrity guard" in compiled
    assert "not proof of delivered bytes" in compiled


def test_approval_evidence_is_bound_to_material_call_arguments() -> None:
    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    sample = (ROOT / "AGENT_HARNESS_REVIEW_SAMPLE.md").read_text(encoding="utf-8")

    assert "Approval-evidence binding" in skill
    assert "exact material call parameters" in skill
    assert "exposes only the tool name or omits material parameters" in skill
    assert "material call arguments and effect scope" in sample
    assert "tool-name-only permission evidence" in sample


def test_compiled_prompt_preserves_approval_evidence_binding() -> None:
    compiled = (ROOT / "GodPrompt.md").read_text(encoding="utf-8")

    assert "Approval-evidence binding" in compiled
    assert "exact material call parameters" in compiled


def test_tool_plane_transitions_require_live_inventory_convergence() -> None:
    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")

    assert "Tool-plane transition readiness" in skill
    assert "configuration success or a connected status" in skill
    assert "live model-visible/executable inventory has converged" in skill
    assert "stale, incomplete, or cannot be reconciled" in skill


def test_compiled_prompt_preserves_tool_plane_transition_readiness() -> None:
    compiled = (ROOT / "GodPrompt.md").read_text(encoding="utf-8")

    assert "Tool-plane transition readiness" in compiled
    assert "live model-visible/executable inventory has converged" in compiled
