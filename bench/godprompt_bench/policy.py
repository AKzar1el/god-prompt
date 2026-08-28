from __future__ import annotations

import shlex
from functools import lru_cache
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    reason: str


def validate_workspace_path(path: str) -> bool:
    if not path or "\x00" in path or path.startswith("~") or "$HOME" in path:
        return False
    parsed = PurePosixPath(path)
    if parsed.is_absolute() or ".." in parsed.parts:
        return False
    return True


def _path_operand(token: str) -> str:
    # Strip common shell redirection prefixes before checking the target path.
    return token.lstrip("0123456789<>")


def classify_shell_command(command: str | list[str]) -> PolicyDecision:
    try:
        tokens = list(command) if isinstance(command, list) else shlex.split(command)
    except ValueError:
        return PolicyDecision(False, "invalid-shell-syntax")
    if not tokens:
        return PolicyDecision(False, "empty-command")

    banned_network = {"curl", "wget", "ssh", "scp", "nc", "ncat", "telnet"}
    command_names = {PurePosixPath(token).name for token in tokens if token not in {"&&", "||", ";", "|"}}
    if command_names & banned_network:
        return PolicyDecision(False, "network-command")

    for index, token in enumerate(tokens):
        executable = PurePosixPath(token).name
        if executable == "git" and index + 2 < len(tokens):
            tail = tokens[index + 1 :]
            if tail and tail[0] == "config" and "--global" in tail:
                return PolicyDecision(False, "global-git-config")
        if executable == "find" and index + 1 < len(tokens) and tokens[index + 1] == "/":
            return PolicyDecision(False, "root-filesystem-search")

    for token in tokens[1:]:
        operand = _path_operand(token)
        if not operand or operand in {"&&", "||", ";", "|"}:
            continue
        if operand.startswith("/"):
            return PolicyDecision(False, "absolute-path")
        if operand.startswith("~") or "$HOME" in operand:
            return PolicyDecision(False, "home-path")
        if operand.startswith("../") or "/../" in operand or operand == "..":
            return PolicyDecision(False, "parent-path")

    return PolicyDecision(True, "allowed")


def classify_tool_call(function: str, arguments: dict[str, Any]) -> PolicyDecision:
    if function == "bash":
        command = arguments.get("cmd")
        if not isinstance(command, (str, list)):
            return PolicyDecision(False, "invalid-bash-command")
        if isinstance(command, list) and not all(isinstance(item, str) for item in command):
            return PolicyDecision(False, "invalid-bash-command")
        return classify_shell_command(command)

    if function == "text_editor":
        path = arguments.get("path")
        if not isinstance(path, str) or not validate_workspace_path(path):
            return PolicyDecision(False, "outside-workspace")
        return PolicyDecision(True, "allowed")

    return PolicyDecision(False, "unsupported-tool")


@lru_cache(maxsize=1)
def inspect_workspace_approver():
    """Return one registered Inspect approver for the benchmark workspace policy."""
    from inspect_ai.approval import Approval, approver

    @approver(name="godprompt_workspace")
    def factory():
        async def approve(message, call, view, history):  # noqa: ARG001
            decision = classify_tool_call(call.function, dict(call.arguments))
            if decision.allowed:
                return Approval(
                    decision="approve",
                    explanation="GodPrompt Bench workspace policy allows this tool call.",
                    metadata={"godprompt_bench_policy": "allowed", "reason": decision.reason},
                )
            return Approval(
                decision="reject",
                explanation=f"GodPrompt Bench rejected this tool call: {decision.reason}.",
                metadata={"godprompt_bench_policy": "rejected", "reason": decision.reason},
            )

        return approve

    return factory()
