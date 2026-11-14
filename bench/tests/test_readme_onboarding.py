import base64
import re
import subprocess
import sys
from pathlib import Path

import pytest


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


@pytest.mark.parametrize("profile", ("smoke", "full"))
def test_benchmark_readme_powershell_run_examples_are_copyable_without_executing_models(profile):
    readme = (ROOT / "bench" / "README.md").read_text(encoding="utf-8")
    match = re.search(r"For Windows PowerShell[^\n]*\n+```powershell\n(.*?)\n```", readme, re.DOTALL)
    assert match is not None
    commands = [line.strip() for line in match.group(1).splitlines() if line.strip()]
    assert len(commands) == 3
    command = commands[1 + ("smoke", "full").index(profile)]
    parts = command.split()
    assert parts[:3] == [r".\.venv\Scripts\python.exe", "-m", "godprompt_bench.run"]
    for flag in ("--profile", "--model", "--seed", "--reasoning-effort", "--reasoning-mode"):
        assert parts.count(flag) == 1
        assert parts.index(flag) + 1 < len(parts)
    assert parts[parts.index("--profile") + 1] == profile

    if sys.platform == "win32":
        # Parse only: never execute a documented, potentially billable model run.
        encoded = base64.b64encode(command.encode("utf-8")).decode("ascii")
        script = (
            "$line=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('"
            + encoded
            + "'));$tokens=$null;$errors=$null;"
            "[Management.Automation.Language.Parser]::ParseInput("
            "$line,[ref]$tokens,[ref]$errors)|Out-Null;"
            "if($errors.Count -ne 0){exit 2}"
        )
        subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        )


def test_benchmark_readme_powershell_help_is_free_preflight():
    readme = (ROOT / "bench" / "README.md").read_text(encoding="utf-8")
    match = re.search(r"For Windows PowerShell[^\n]*\n+```powershell\n(.*?)\n```", readme, re.DOTALL)
    assert match is not None
    commands = [line.strip() for line in match.group(1).splitlines() if line.strip()]
    assert commands[0] == r".\.venv\Scripts\python.exe -m godprompt_bench.run --help"
    assert "--model" not in commands[0]

    # Run --help using the installed interpreter; argparse exits before any evaluation.
    result = subprocess.run(
        [sys.executable, "-B", "-m", "godprompt_bench.run", "--help"],
        cwd=ROOT / "bench",
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert "--profile" in result.stdout
    assert "--model" in result.stdout
