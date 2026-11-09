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
_WINDOWS_DEVICE_DIGITS = str.maketrans("\u00b9\u00b2\u00b3", "123")


def validate_workspace_path(path: str) -> bool:
    if (not path or any(ord(char) < 32 or char in '*?"<>|' for char in path)
            or path.startswith("~") or "$HOME" in path):
        return False
    parsed = PurePosixPath(path)
    windows = PureWindowsPath(path)
    # An editor can interpret backslashes and drive-relative paths on Windows.
    nonportable_component = any(
        part.endswith((".", " ")) or part.split(".", 1)[0].rstrip(" ").upper().translate(
            _WINDOWS_DEVICE_DIGITS
        ) in _WINDOWS_DEVICE_NAMES
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
    # env/git accept an attached -C/path argument without a separating space.
    if operand.startswith("-C") and len(operand) > 2:
        return operand[2:]
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


def _package_executable_name(token: str) -> str:
    # Windows package managers commonly launch through PATHEXT shims.
    name = PurePosixPath(token.replace("\\", "/")).name.casefold()
    for suffix in (".exe", ".cmd", ".bat", ".com"):
        if name.endswith(suffix):
            return name[:-len(suffix)]
    return name


def _runs_package_network_command(tokens: list[str]) -> bool:
    # Inspect the actual launched program, not inert script arguments.
    index = 0
    while index < len(tokens):
        launcher = _package_executable_name(tokens[index])
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", tokens[index]):
            index += 1
        elif launcher == "env":
            index += 1
            while index < len(tokens):
                option = tokens[index]
                if option in {"-i", "--ignore-environment", "--"} or re.fullmatch(
                    r"[A-Za-z_][A-Za-z0-9_]*=.*", option
                ):
                    index += 1
                elif option in {"-C", "--chdir"} and index + 1 < len(tokens):
                    index += 2
                elif option.startswith("--chdir=") or (option.startswith("-C") and len(option) > 2):
                    index += 1
                elif option in {"-u", "--unset"} and index + 1 < len(tokens):
                    index += 2
                else:
                    break
        elif launcher == "command" and index + 1 < len(tokens):
            index += 1
            if tokens[index] in {"-v", "-V"}:
                return False
            if tokens[index] == "-p":
                index += 1
        elif launcher == "corepack":
            index += 1
            if index < len(tokens) and tokens[index] in {
                "prepare", "install", "use", "up", "pack", "hydrate",
            }:
                return True
        else:
            break
    if index >= len(tokens):
        return False
    launcher = _package_executable_name(tokens[index])
    config_mutations: set[str] = set()
    if launcher in {"npx", "pnpx", "bunx", "uvx"}:
        return True
    if re.fullmatch(r"pip(?:[23](?:\.\d+)*)?", launcher):
        blocked = {"install", "download", "wheel", "index", "search"}
        config_mutations = {"set", "unset", "edit"}
        value_options = {"--python", "--index-url", "-i", "--extra-index-url", "--proxy"}
    elif launcher == "npm":
        blocked = {"install", "i", "ci", "update", "upgrade", "add", "exec", "x", "publish", "pack", "audit", "set", "delete"}
        config_mutations = {"set", "delete", "rm", "edit", "fix"}
        value_options = {"--prefix", "-C", "--workspace", "-w", "--registry", "--cache", "--userconfig"}
    elif launcher == "pnpm":
        blocked = {"add", "install", "i", "update", "up", "upgrade", "dlx", "exec", "fetch", "publish", "audit"}
        value_options = {"-C", "--dir", "--prefix", "--filter", "-F", "--registry", "--store-dir"}
    elif launcher in {"yarn", "yarnpkg"}:
        blocked = {"add", "install", "up", "upgrade", "dlx", "exec", "publish", "audit", "npm", "global"}
        value_options = {"--cwd", "--modules-folder", "--cache-folder", "--registry"}
    elif launcher == "bun":
        blocked = {"add", "install", "i", "update", "upgrade", "x", "publish", "pm"}
        value_options = {"--cwd", "--registry"}
    elif launcher == "uv":
        blocked = {"add", "sync", "lock", "run", "build", "publish", "self"}
        value_options = {"--directory", "--project", "--config-file", "--python", "--index-url"}
    elif launcher == "pipx":
        blocked = {"install", "run", "runpip", "inject", "upgrade", "upgrade-all"}
        value_options = {"--python", "--pip-args", "--index-url"}
    elif launcher == "poetry":
        blocked = {"add", "install", "update", "lock", "sync", "publish", "build", "self"}
        value_options = {"-C", "--directory", "--project", "--config"}
    else:
        return False
    skip_value = False
    uv_group = None
    for option in tokens[index + 1:]:
        if skip_value:
            skip_value = False
        elif option in value_options:
            skip_value = True
        elif option.startswith("-"):
            continue
        elif option == "config":
            # Config mutators can write to user/system files outside the repo.
            return any(value in config_mutations for value in tokens[index + 1 :])
        else:
            if launcher == "uv" and uv_group is None and option in {"pip", "tool"}:
                uv_group = option
                continue
            if uv_group == "pip":
                return option in {"install", "compile", "sync"}
            if uv_group == "tool":
                return option in {"install", "run", "upgrade", "upgrade-all"}
            return option in blocked
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

    # Windows drive-rooted and UNC launchers bypass PurePosixPath name checks.
    # Preserve inert echo/printf arguments as data, including escaped dollars.
    if any(PureWindowsPath(token).drive or token.startswith("\\") for token in executable_tokens):
        return PolicyDecision(False, "absolute-path")

    # NODE_OPTIONS can preload executable modules before the visible command
    # starts; a caller-controlled assignment defeats argv-only approval.
    if any(token.casefold().startswith("node_options=") for token in executable_tokens):
        return PolicyDecision(False, "node-options-override")

    # Git accepts environment-supplied aliases, config files and helper paths
    # that can change what a harmless-looking `git check` actually executes.
    # Reject assignment-shaped tokens conservatively, including `env` prefixes.
    if any(
        "=" in token and (
            token.split("=", 1)[0].casefold().startswith("git_config_")
            or token.split("=", 1)[0].casefold() in {"git_exec_path", "git_template_dir"}
        )
        for token in executable_tokens
    ):
        return PolicyDecision(False, "git-environment-override")

    # Language runtimes and native loaders can execute modules from these
    # overrides before the visible script or test command is evaluated.
    startup_variables = {
        "ld_preload", "ld_audit", "ld_library_path",
        "pythonpath", "pythonstartup", "pythonhome",
        "perl5opt", "perl5lib", "rubyopt", "rubylib",
    }
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

    inline_interpreters = {
        "python", "python3", "py", "pyw", "pythonw", "node", "nodejs",
        "perl", "ruby", "php",
    }
    inline_flags = {"-c", "-e", "--eval", "--execute"}
    for index, token in enumerate(executable_tokens):
        # Windows can launch the same language runtime with a case-insensitive
        # .exe suffix; normalize it before examining inline execution flags.
        executable_name = PurePosixPath(token).name.casefold().removesuffix(".exe")
        # Common version-suffixed interpreter binaries can run the same inline
        # payloads as their unversioned names (e.g. python3.12 -c).
        if executable_name in inline_interpreters or re.fullmatch(
            r"(?:python[23]|pythonw[23]?|pypy[23]?|perl5|ruby[23]|php[578])(?:\.\d+)*",
            executable_name,
        ):
            is_node = executable_name in {"node", "nodejs"}
            is_perl = executable_name.startswith("perl")
            is_php = executable_name.startswith("php")
            is_ruby = executable_name.startswith("ruby")
            is_python = executable_name.startswith(("python", "pypy")) or executable_name in {"py", "pyw"}
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
                if is_python and (option == "-m" or option.startswith("-m")):
                    module = options[offset + 1] if option == "-m" and offset + 1 < len(options) else option[2:]
                    if (module.split(".", 1)[0] in {
                        "pip", "pipx", "poetry", "uv", "ensurepip", "pdm", "hatch", "build"
                    } or module == "http.server" or module.startswith("http.server.")):
                        return PolicyDecision(False, "network-command")
                # Short interpreter switches can be bundled: -Ic, -0e, -we,
                # and -nr still invoke inline code. Avoid operand-taking -X,
                # -W, -I (Perl/Ruby), and -d (PHP) to preserve ordinary scripts.
                compact_inline = (
                    (is_python and re.match(r"^-[bBdEhiIOPqRsSuUvVx]+c", option))
                    or (is_perl and re.match(r"^-(?:[0-7]+|[awntpT]+)[eE]", option))
                    or (is_ruby and re.match(r"^-[aCdlnpswUv]+e", option))
                    or (is_php and re.match(r"^-[nv]+r", option))
                )
                if (
                    option in inline_flags
                    or option.startswith(("--eval=", "--execute=", "-c", "-e"))
                    or (is_node and (option.startswith("-p") or option == "--print" or option.startswith("--print=")))
                    or (is_perl and option.startswith("-E"))
                    or (is_php and option.startswith("-r"))
                    or compact_inline
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

    banned_network = {
        "curl", "wget", "ssh", "scp", "sftp", "ftp", "tftp", "rsync",
        "nc", "ncat", "socat", "telnet",
    }
    # Match Windows executable shims (.exe/.cmd/.bat/.com) as well as bare names.
    command_names = {
        _package_executable_name(token)
        for token in executable_tokens if token not in {"&&", "||", ";", "|"}
    }
    if command_names & banned_network or _runs_package_network_command(executable_tokens):
        return PolicyDecision(False, "network-command")

    for index, token in enumerate(executable_tokens):
        executable = PurePosixPath(token).name
        if executable.casefold().removesuffix(".exe") == "git":
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
            if offset < len(tail):
                git_command = tail[offset]
                # These Git entry points can contact remotes, run configured
                # transports or launch helpers even without curl/ssh in argv.
                if git_command in {
                    "clone", "fetch", "pull", "push", "ls-remote", "remote",
                    "submodule", "send-pack", "receive-pack", "upload-pack",
                    "upload-archive", "http-fetch", "http-push", "daemon",
                    "instaweb", "send-email", "svn",
                } or (git_command == "archive" and any(
                    option == "--remote" or option.startswith("--remote=")
                    for option in tail[offset + 1:]
                )):
                    return PolicyDecision(False, "network-command")
            if offset < len(tail) and tail[offset] == "config" and any(
                option in {"--global", "--system"} for option in tail[offset + 1 :]
            ):
                return PolicyDecision(False, "global-git-config")
        if executable == "find" and index + 1 < len(executable_tokens) and executable_tokens[index + 1] == "/":
            return PolicyDecision(False, "root-filesystem-search")

    # Preserve more specific policy reasons for known launchers before rejecting
    # unreviewed absolute POSIX executables outside the workspace.
    if PurePosixPath(tokens[0]).is_absolute():
        return PolicyDecision(False, "absolute-path")

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

    # Array-form commands lack shell quoting context: reject expansion or
    # operators hidden inside one apparent argv element after specific checks.
    if isinstance(command, list):
        if any(_has_dynamic_dollar(token) or "`" in token or "\n" in token
               or "\r" in token or "<<<" in token for token in tokens):
            return PolicyDecision(False, "dynamic-shell-syntax")
        if any(any(operator in token for operator in ";&|") for token in tokens):
            return PolicyDecision(False, "compound-shell-command")

    return PolicyDecision(True, "allowed")


def classify_tool_call(function: str, arguments: dict[str, Any]) -> PolicyDecision:
    if function == "bash":
        # Inspect AI's bash tool exposes `command`; keep the legacy `cmd`
        # spelling for older callers, but never guess when both are supplied.
        if "command" in arguments and "cmd" in arguments:
            return PolicyDecision(False, "invalid-bash-command")
        command = arguments.get("command", arguments.get("cmd"))
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
