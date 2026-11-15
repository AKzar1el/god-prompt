import base64
import re
import subprocess
import sys
from pathlib import Path

import pytest
from godprompt_bench import run as benchmark_runner


ROOT = Path(__file__).resolve().parents[2]


def test_benchmark_readme_model_example_is_not_misrepresented_as_current_flagship():
    readme = (ROOT / "bench" / "README.md").read_text(encoding="utf-8")
    run_section = readme.split("## Run", 1)[1].split("## Output", 1)[0]

    assert "current OpenAI flagship" not in run_section
    assert "Confirm that your account has access" in run_section
    assert "may incur provider charges" in run_section


def test_benchmark_readme_windows_install_uses_direct_venv_python():
    readme = (ROOT / "bench" / "README.md").read_text(encoding="utf-8")
    install_section = readme.split("## Install", 1)[1].split("## Run", 1)[0]
    match = re.search(r"```powershell\n(.*?)\n```", install_section, re.DOTALL)
    assert match is not None
    commands = [line.strip() for line in match.group(1).splitlines() if line.strip()]
    assert commands == [
        "python -m venv .venv",
        r".\.venv\Scripts\python.exe -m pip install --upgrade pip",
        r".\.venv\Scripts\python.exe -m pip install -e '.[test,openai]'",
        r".\.venv\Scripts\python.exe -m pytest -q",
    ]

    if sys.platform == "win32":
        # Syntax-only validation; never install packages or execute model runs.
        script = (
            "$lines=@('"
            + "','".join(base64.b64encode(line.encode("utf-8")).decode("ascii") for line in commands)
            + "');foreach($b64 in $lines){"
            "$line=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($b64));"
            "$tokens=$null;$errors=$null;"
            "[Management.Automation.Language.Parser]::ParseInput("
            "$line,[ref]$tokens,[ref]$errors)|Out-Null;"
            "if($errors.Count -ne 0){exit 2}}"
        )
        subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        )


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


@pytest.mark.parametrize("profile", ("smoke", "full"))
def test_benchmark_readme_powershell_model_examples_parse_without_provider_calls(profile, monkeypatch):
    readme = (ROOT / "bench" / "README.md").read_text(encoding="utf-8")
    match = re.search(r"For Windows PowerShell[^\n]*\n+```powershell\n(.*?)\n```", readme, re.DOTALL)
    assert match is not None
    commands = [line.strip() for line in match.group(1).splitlines() if line.strip()]
    parts = commands[1 + ("smoke", "full").index(profile)].split()
    assert parts[:3] == [r".\.venv\Scripts\python.exe", "-m", "godprompt_bench.run"]

    captured = []

    def capture_without_evaluating(repo_root, bench_root, loaded_profile, **kwargs):
        captured.append((repo_root, bench_root, loaded_profile, kwargs))
        return Path("NO_PROVIDER_EXECUTION")

    monkeypatch.setattr(benchmark_runner, "execute_benchmark", capture_without_evaluating)
    monkeypatch.setattr(sys, "argv", ["godprompt_bench.run", *parts[3:]])
    benchmark_runner.main()

    assert len(captured) == 1
    repo_root, bench_root, loaded_profile, options = captured[0]
    assert repo_root == ROOT
    assert bench_root == ROOT / "bench"
    assert loaded_profile.name == profile
    assert options["model"] == parts[parts.index("--model") + 1]
    assert options["seed"] == int(parts[parts.index("--seed") + 1])
    assert options["reasoning_effort"] == parts[parts.index("--reasoning-effort") + 1]
    assert options["reasoning_mode"] == parts[parts.index("--reasoning-mode") + 1]
