from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_chatgpt_onboarding_does_not_require_oversized_custom_instructions():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    section = readme.split("**Option D", 1)[1].split("**Option E", 1)[0]

    # The full skill/prompt exceeds even the largest ChatGPT global field limit.
    assert len((ROOT / "SKILL.md").read_text(encoding="utf-8")) > 5000
    assert len((ROOT / "GodPrompt.md").read_text(encoding="utf-8")) > 5000
    assert "Paste the contents of `SKILL.md` into the Project's Custom Instructions" not in section
    assert "Paste the contents of `GodPrompt.md`" not in section
    assert "Project files" in section
    assert "Custom Instructions" in section
