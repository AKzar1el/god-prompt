from __future__ import annotations

import re
import shlex
from functools import lru_cache
from dataclasses import dataclass
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    reason: str


_WINDOWS_DEVICE_NAMES = {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"} | {
    f"{prefix}{number}" for prefix in ("COM", "LPT") for number in range(1, 10)
}


def validate_workspace_path(path: str) -> bool:
    if not path or "\x00" in path or path.startswith("~") or "$HOME" in path:
        return False
    parsed = PurePosixPath(path)
    windows = PureWindowsPath(path)
    # An editor can interpret backslashes and drive-relative paths on Windows.
    nonportable_component = any(
        part.endswith((".", " ")) or part.split(".", 1)[0].rstrip(" ").upper() in _WINDOWS_DEVICE_NAMES
        for part in parsed.parts
    )
    if (
        parsed == PurePosixPath(".")
        or parsed.is_absolute()
        or ".." in parsed.parts
        or ":" in path
        or nonportable_component
        or "\\" in path
        or windows.drive
        or windows.root
    ):
        return False
    return True


def _path_operand(token: str) -> str:
    # Strip common shell redirection prefixes before checking the target path.
    operand = token.lstrip("0123456789<>")
    # GNU --option=/absolute/path hides a path behind an option assignment.
    if operand.startswith("-") and "=" in operand:
        return operand.split("=", 1)[1]
    return operand


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


def _has_unquoted_here_string(command: str) -> bool:
    # Here-strings can feed unreviewed code to an interpreter via stdin.
    quote = None
    escaped = False
    for index, char in enumerate(command):
        if escaped:
            escaped = False
        elif char == "\\" and quote != "'":
            escaped = True
        elif char == "'" and quote != '"':
            quote = None if quote == "'" else "'"
        elif char == '"' and quote != "'":
            quote = None if quote == '"' else '"'
        elif quote is None and command.startswith("<<<", index):
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
    if isinstance(command, str) and (
        _has_dynamic_dollar(command)
        or _has_unquoted_here_string(command)
        or "`" in command
        or "\n" in command
    ):
        return PolicyDecision(False, "dynamic-shell-syntax")
    if isinstance(command, list) and any("<<<" in token for token in tokens):
        return PolicyDecision(False, "dynamic-shell-syntax")

    # echo/printf render arguments as data; an argument named "curl" or "bash"
    # is not a command. Keep the full scan for every command containing shell
    # control operators so a real chained command can never be overlooked.
    literal_output = (
        tokens[0] in {"echo", "printf"}
        and not any(token in {";", "&&", "||", "|", "&", "|&"} for token in tokens)
    )
    executable_tokens = tokens[:1] if literal_output else tokens

    # NODE_OPTIONS can preload executable modules before the visible command
    # starts; a caller-controlled assignment defeats argv-only approval.
    if any(token.casefold().startswith("node_options=") for token in executable_tokens):
        return PolicyDecision(False, "node-options-override")

    # These assignments can load libraries or Python startup modules that are
    # invisible to the command's argument scan.
    startup_variables = {"ld_preload", "ld_audit", "pythonpath"}
    if any("=" in token and token.split("=", 1)[0].casefold() in startup_variables
           for token in executable_tokens):
        return PolicyDecision(False, "interpreter-env-override")

    shell_names = {
        "sh", "bash", "dash", "ash", "zsh", "ksh", "fish", "csh", "tcsh",
        "pwsh", "pwsh.exe", "powershell", "powershell.exe", "cmd", "cmd.exe",
        "eval", "source",
    }
    if any(PurePosixPath(token).name.casefold() in shell_names for token in executable_tokens):
        return PolicyDecision(False, "nested-shell-interpreter")

    # GNU env -S re-tokenizes a single argument into a new command, hiding
    # executable names from the normal shell-token scan.
    if "env" in {PurePosixPath(token).name for token in executable_tokens}:
        if any(token.startswith(("-S", "--split-string=")) or token == "--split-string"
               for token in executable_tokens):
            return PolicyDecision(False, "dynamic-env-command")

    inline_interpreters = {"python", "python3", "node", "nodejs", "perl", "ruby", "php"}
    inline_flags = {"-c", "-e", "--eval", "--execute"}
    for index, token in enumerate(executable_tokens):
        executable_name = PurePosixPath(token).name
        # Common version-suffixed interpreter binaries can run the same inline
        # payloads as their unversioned names (e.g. python3.12 -c).
        if executable_name in inline_interpreters or re.fullmatch(
            r"(?:python[23]|pypy[23]?|perl5|ruby[23]|php[578])(?:\.\d+)*",
            executable_name,
        ):
            is_node = executable_name in {"node", "nodejs"}
            is_perl = executable_name.startswith("perl")
            is_php = executable_name.startswith("php")
            is_ruby = executable_name.startswith("ruby")
            is_python = executable_name.startswith(("python", "pypy"))
            # Examine the full interpreter option prefix, not only four tokens.
            # Stop at a script operand so ordinary script arguments remain data.
            consumes_value = False
            options = executable_tokens[index + 1 :]
            for offset, option in enumerate(options):
                if consumes_value:
                    consumes_value = False
                    continue
                if option == "--":
                    break
                if is_node and option.partition("=")[0] in {
                    "--import", "--loader", "--experimental-loader"
                }:
                    _, has_equals, value = option.partition("=")
                    preload = value if has_equals else (
                        options[offset + 1] if offset + 1 < len(options) else ""
                    )
                    if preload.lower().startswith("data:"):
                        return PolicyDecision(False, "inline-interpreter")
                # These modules evaluate statements or expose interactive Python
                # consoles; none requires the interpreter's own -c flag.
                if is_python and (option in {"-mtimeit", "-mpdb", "-mcode", "-masyncio"} or (
                    option == "-m" and offset + 1 < len(options) and options[offset + 1] in {"timeit", "pdb", "code", "asyncio"}
                )):
                    return PolicyDecision(False, "inline-interpreter")
                # These modules can open a network listener or fetch/install packages.
                if is_python and (option in {"-mhttp.server", "-mpip"} or (
                    option == "-m" and offset + 1 < len(options) and options[offset + 1] in {"http.server", "pip"}
                )):
                    return PolicyDecision(False, "network-command")
                if (
                    option in inline_flags
                    or option.startswith(("--eval=", "--execute=", "-c", "-e"))
                    or (is_node and (option.startswith("-p") or option == "--print" or option.startswith("--print=")))
                    or (is_perl and option.startswith("-E"))
                    or (is_php and option.startswith("-r"))
                ):
                    return PolicyDecision(False, "inline-interpreter")
                if (
                    option in {"-W", "-X", "--check-hash-based-pycs", "-r", "--require", "--import", "--loader", "--experimental-loader", "--title"}
                    or (is_php and option == "-d")
                    or ((is_perl or is_ruby) and option == "-I")
                ):
                    consumes_value = True
                elif not option.startswith("-"):
                    break

    banned_network = {"curl", "wget", "ssh", "scp", "nc", "ncat", "telnet"}
    # Windows resolves these network binaries case-insensitively with .exe suffixes.
    command_names = {
        PurePosixPath(token).name.casefold().removesuffix(".exe")
        for token in executable_tokens if token not in {"&&", "||", ";", "|"}
    }
    if command_names & banned_network:
        return PolicyDecision(False, "network-command")

    for index, token in enumerate(executable_tokens):
        executable = PurePosixPath(token).name
        if executable == "git":
            tail = executable_tokens[index + 1 :]
            # Git aliases can launch commands hidden behind innocuous subcommands.
            for position, option in enumerate(tail):
                config = None
                if option == "-c" and position + 1 < len(tail):
                    config = tail[position + 1]
                elif option.startswith("-c") and len(option) > 2:
                    config = option[2:]
                elif option.startswith("--config-env="):
                    config = option.split("=", 1)[1]
                if config is not None and config.casefold().startswith("alias."):
                    return PolicyDecision(False, "dynamic-git-alias")
            # Git accepts global flags before the subcommand, including -C/-c.
            offset = 0
            options_with_values = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--config-env"}
            while offset < len(tail) and tail[offset].startswith("-"):
                offset += 2 if tail[offset] in options_with_values else 1
            if offset < len(tail) and tail[offset] == "config" and "--global" in tail[offset + 1 :]:
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
