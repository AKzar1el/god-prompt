from __future__ import annotations

import re
from collections.abc import Mapping
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
        if not prefix:
            raise ValueError("GodPrompt.md is empty; refusing an invalid treatment benchmark")
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


def experimental_contract_coding_agent(repo_root: Path, *, session, scope):
    """Assemble one opt-in, scope-bound contract agent under stock approvals.

    The host must create a distinct EvidenceSession and InspectExecutionScope
    for each sample/attempt. This does not register a third eval condition,
    authorize a tool call, or run a provider. Native ToolCall correlation and
    per-sample orchestration are separate prerequisites for a live third arm.
    """
    from inspect_ai.agent import react
    from inspect_ai.approval import ApprovalPolicy
    from inspect_ai.tool import text_editor

    from .inspect_receipt_bash import receipt_bash_tool

    # Build the receipt tool first so a missing/mismatched scope fails closed.
    observed_bash = receipt_bash_tool(session, scope=scope, timeout=60)
    approval = [
        ApprovalPolicy(
            approver=inspect_workspace_approver(),
            tools=["bash", "text_editor"],
        )
    ]
    return react(
        prompt=condition_prompt("godprompt", repo_root),
        tools=[observed_bash, text_editor(timeout=60)],
        approval=approval,
        attempts=1,
    )


def experimental_contract_sample_agent(repo_root: Path, *, state, client, contract):
    """Bind one opt-in agent/evidence session to an actual Inspect sample epoch.

    The host must pass its TaskState and an already prepared MCP contract.
    This only assembles an agent; it does not install a solver, run a model,
    or turn surrogate sandbox invocation IDs into native ToolCall IDs.
    """
    from inspect_ai.solver import TaskState

    from .mcp_contract_adapter import (
        ContractHold, EvidenceSession, InspectExecutionScope, _contract_sha,
    )

    if not isinstance(state, TaskState):
        raise ContractHold("expected host Inspect TaskState")
    if (
        not isinstance(state.sample_id, str)
        or not re.fullmatch(r"[A-Za-z0-9_-]{3,80}", state.sample_id)
        or type(state.epoch) is not int
        or state.epoch < 1
    ):
        raise ContractHold("invalid Inspect sample/epoch scope")
    if not isinstance(state.input, str) or not isinstance(state.metadata, Mapping):
        raise ContractHold("missing Inspect sample task metadata")
    if not isinstance(contract, Mapping):
        raise ContractHold("missing prepared MCP contract")
    try:
        commands = [item["command"] for item in contract["verification_commands"]]
        expected_commands = state.metadata["expected_verification_commands"]
        expected_paths = state.metadata["allowed_paths"]
        digest = _contract_sha({
            key: value for key, value in contract.items() if key != "contract_id"
        })
        if (
            not isinstance(expected_commands, list)
            or not expected_commands
            or not isinstance(expected_paths, list)
            or not expected_paths
            or any(not isinstance(item, str) or not item for item in commands)
            or contract["task"] != state.input
            or commands != expected_commands
            or contract["allowed_paths"] != expected_paths
            or contract["contract_id"] != digest
        ):
            raise ContractHold("MCP contract is not bound to the Inspect sample")
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise ContractHold("malformed Inspect sample contract") from exc

    scope = InspectExecutionScope(state.sample_id, f"epoch-{state.epoch}-attempt-1")
    session = EvidenceSession(client, contract, execution_scope=scope)
    return experimental_contract_coding_agent(
        repo_root, session=session, scope=scope,
    ), session
