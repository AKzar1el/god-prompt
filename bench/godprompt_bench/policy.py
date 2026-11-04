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


def _has_dynamic_dollar(command: str) -> bool:
    # shlex strips quoting before policy checks, but a shell expands unescaped
    # dollars outside single quotes (including ANSI-C $'...' command fragments).
    quote = None
    escaped = False
    for char in command:
        if escaped:
            escaped = False
        elif char == "\\" and quote != "'":
            escaped = True
        elif char == "'" and quote != '"':
            quote = None if quote == "'" else "'"
        elif char == '"' and quote != "'":
            quote = None if quote == '"' else '"'
        elif char == "$" and quote != "'":
            return True
    return False


def classify_shell_command(command: str | list[str]) -> PolicyDecision:
    try:
        if isinstance(command, list):
            tokens = list(command)
        else:
            # Keep shell operators separate even when there is no whitespace.
            lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|<>()")
            lexer.whitespace_split = True
            tokens = list(lexer)
    except ValueError:
        return PolicyDecision(False, "invalid-shell-syntax")
    if not tokens:
        return PolicyDecision(False, "empty-command")

    # The approver does not execute or parse nested programs. Deny mechanisms
    # that can execute an entirely different command after this check.
    if isinstance(command, str) and (_has_dynamic_dollar(command) or "`" in command or "\n" in command):
        return PolicyDecision(False, "dynamic-shell-syntax")

    # echo/printf render arguments as data; an argument named "curl" or "bash"
    # is not a command. Keep the full scan for every command containing shell
    # control operators so a real chained command can never be overlooked.
    literal_output = (
        tokens[0] in {"echo", "printf"}
        and not any(token in {";", "&&", "||", "|", "&", "|&"} for token in tokens)
    )
    executable_tokens = tokens[:1] if literal_output else tokens

    shell_names = {"sh", "bash", "dash", "ash", "zsh", "ksh", "eval", "source"}
    if any(PurePosixPath(token).name in shell_names for token in executable_tokens):
        return PolicyDecision(False, "nested-shell-interpreter")

    # GNU env -S re-tokenizes a single argument into a new command, hiding
    # executable names from the normal shell-token scan.
    if "env" in {PurePosixPath(token).name for token in executable_tokens}:
        if any(token.startswith(("-S", "--split-string=")) or token == "--split-string"
               for token in executable_tokens):
            return PolicyDecision(False, "dynamic-env-command")

    inline_interpreters = {"python", "python3", "node", "perl", "ruby", "php"}
    inline_flags = {"-c", "-e", "--eval", "--execute"}
    for index, token in enumerate(executable_tokens):
        if PurePosixPath(token).name in inline_interpreters:
            # Examine the full interpreter option prefix, not only four tokens.
            # Stop at a script operand so ordinary script arguments remain data.
            consumes_value = False
            for option in executable_tokens[index + 1 :]:
                if consumes_value:
                    consumes_value = False
                    continue
                if option == "--":
                    break
                if (option in inline_flags or option.startswith(("--eval=", "--execute=", "-c", "-e"))):
                    return PolicyDecision(False, "inline-interpreter")
                if option in {"-W", "-X", "--check-hash-based-pycs", "-r", "--require", "--import", "--loader", "--title"}:
                    consumes_value = True
                elif not option.startswith("-"):
                    break

    banned_network = {"curl", "wget", "ssh", "scp", "nc", "ncat", "telnet"}
    command_names = {PurePosixPath(token).name for token in executable_tokens if token not in {"&&", "||", ";", "|"}}
    if command_names & banned_network:
        return PolicyDecision(False, "network-command")

    for index, token in enumerate(executable_tokens):
        executable = PurePosixPath(token).name
        if executable == "git" and index + 2 < len(executable_tokens):
            tail = executable_tokens[index + 1 :]
            if tail and tail[0] == "config" and "--global" in tail:
                return PolicyDecision(False, "global-git-config")
        if executable == "find" and index + 1 < len(executable_tokens) and executable_tokens[index + 1] == "/":
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

    if any(token in {";", "&&", "||", "|", "&", "|&"} or (token and not token.strip("()"))
           for token in tokens):
        return PolicyDecision(False, "compound-shell-command")

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
