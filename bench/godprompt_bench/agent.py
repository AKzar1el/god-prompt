from __future__ import annotations

from pathlib import Path

from .policy import inspect_workspace_approver

COMMON_AGENT_INSTRUCTIONS = """You are a software-engineering agent working in an isolated repository fixture.
Use the available workspace tools to complete the user's task.
Stay inside the workspace and do not use network access.
When finished, submit exactly one JSON object with status complete, blocked, or error and a short summary."""

BASELINE_INSTRUCTIONS = """You are a software-engineering agent. Complete the requested code task accurately and concisely."""


def condition_prompt(condition: str, repo_root: Path) -> str:
    if condition == "baseline":
        prefix = BASELINE_INSTRUCTIONS
    elif condition == "godprompt":
        prompt_path = repo_root / "GodPrompt.md"
        prefix = prompt_path.read_text(encoding="utf-8").rstrip()
    else:
        raise ValueError(f"unknown benchmark condition: {condition}")
    return prefix.rstrip() + "\n\n" + COMMON_AGENT_INSTRUCTIONS


def coding_agent(condition: str, repo_root: Path):
    """Build the identical Inspect ReAct scaffold for one benchmark condition."""
    from inspect_ai.agent import react
    from inspect_ai.approval import ApprovalPolicy
    from inspect_ai.tool import bash, text_editor

    approval = [
        ApprovalPolicy(
            approver=inspect_workspace_approver(),
            tools=["bash", "text_editor"],
        )
    ]
    return react(
        prompt=condition_prompt(condition, repo_root),
        tools=[bash(timeout=60), text_editor(timeout=60)],
        approval=approval,
        attempts=1,
    )
