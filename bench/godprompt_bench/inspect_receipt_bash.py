"""Opt-in Inspect bash tool with host-observed sandbox process receipts.

This is a building block for the experimental MCP arm, not a live arm or a
substitute for Inspect's named bash/text_editor approval policy. The caller must
create a separate EvidenceSession per sample/attempt and install this tool only
inside the existing approval-controlled Inspect agent.
"""
from __future__ import annotations

from uuid import uuid4
from typing import Any

from .mcp_contract_adapter import ContractHold, EvidenceSession, InspectExecutionScope


def receipt_bash_tool(
    session: EvidenceSession,
    *,
    scope: InspectExecutionScope,
    timeout: int | None = 60,
    user: str | None = None,
    sandbox: str | None = None,
) -> Any:
    """Build a bash-named Inspect tool with the stock single-command interface.

    A verification receipt is captured only *after* the actual sandbox exec
    returns. Stock Inspect bash normally discards ExecResult.returncode, so
    neither its text nor a ToolEvent can be used to infer process success.

    The surrogate invocation ID is assigned here, not supplied by the model.
    It is not Inspect's model ToolCall ID and must not be treated as such.
    """
    if not isinstance(session, EvidenceSession):
        raise ContractHold("expected a trusted evidence session")
    if (
        not isinstance(scope, InspectExecutionScope)
        or session.execution_scope is None
        or scope != session.execution_scope
    ):
        raise ContractHold("missing or cross-sample execution scope")
    if timeout is not None and (type(timeout) is not int or timeout <= 0):
        raise ContractHold("invalid sandbox command timeout")

    checks_by_command: dict[str, str] = {}
    check_ids: set[str] = set()
    try:
        checks = session.contract["verification_commands"]
        if not isinstance(checks, list) or not checks:
            raise ContractHold("missing verification commands")
        for item in checks:
            check_id, command = item["id"], item["command"]
            if (
                not isinstance(check_id, str) or not check_id
                or not isinstance(command, str) or not command
            ):
                raise ContractHold("invalid verification requirement")
            if command in checks_by_command:
                raise ContractHold("ambiguous duplicate verification command")
            if check_id in check_ids:
                raise ContractHold("ambiguous duplicate verification ID")
            checks_by_command[command] = check_id
            check_ids.add(check_id)
    except (TypeError, KeyError) as exc:
        raise ContractHold("malformed verification commands") from exc

    # A local import keeps offline evaluation tests free of Inspect import costs.
    from inspect_ai.tool import Tool, tool

    @tool(parallel=True)
    def bash() -> Tool:
        """Execute bash commands inside the configured Inspect sandbox.

        Args:
            command: Bash shell command, subject to the agent's normal approval.
        """
        async def execute(command: str) -> str:
            """Use this function to execute bash commands.

            Args:
                command: The bash command to execute.

            Returns:
                The output of the command.
            """
            from inspect_ai.util import sandbox as sandbox_env

            # Match the stock Inspect 0.3.260 bash execution path and output.
            result = await sandbox_env(sandbox).exec(
                cmd=["bash", "--login", "-c", command],
                timeout=timeout,
                user=user,
            )
            check_id = checks_by_command.get(command)
            if check_id is not None:
                session.observe_inspect_exec(
                    check_id,
                    scope=scope,
                    tool_call_id="ins-" + uuid4().hex,
                    command=command,
                    exec_result=result,
                    event_complete=True,
                )
            error = f"{result.stderr}\n" if result.stderr else ""
            return f"{error}{result.stdout}"

        return execute

    return bash()
