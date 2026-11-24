from __future__ import annotations

import re
from inspect import isawaitable, iscoroutine, iscoroutinefunction
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


def _inspect_sample_inputs(state):
    """Extract only the public, host-supplied contract inputs for one sample."""
    from inspect_ai.solver import TaskState

    from .mcp_contract_adapter import ContractHold, _valid_inspect_sample_id

    if not isinstance(state, TaskState):
        raise ContractHold("expected host Inspect TaskState")
    if (
        not _valid_inspect_sample_id(state.sample_id)
        or type(state.epoch) is not int
        or state.epoch < 1
    ):
        raise ContractHold("invalid Inspect sample/epoch scope")
    if not isinstance(state.input, str) or not isinstance(state.metadata, Mapping):
        raise ContractHold("missing Inspect sample task metadata")
    paths = state.metadata.get("allowed_paths")
    commands = state.metadata.get("expected_verification_commands")
    if any(
        not isinstance(values, list)
        or not values
        or any(not isinstance(item, str) or not item.strip() for item in values)
        or len(values) != len(set(values))
        for values in (paths, commands)
    ):
        raise ContractHold("invalid Inspect sample contract requirements")
    return state.input, list(paths), list(commands)


def experimental_contract_sample_agent(repo_root: Path, *, state, client, contract):
    """Bind one opt-in agent/evidence session to an actual Inspect sample epoch.

    The host must pass its TaskState and an already prepared MCP contract.
    This only assembles an agent; it does not install a solver, run a model,
    or turn surrogate sandbox invocation IDs into native ToolCall IDs.
    """
    from .mcp_contract_adapter import (
        ContractHold, EvidenceSession, InspectExecutionScope, _contract_sha,
    )

    task, expected_paths, expected_commands = _inspect_sample_inputs(state)
    if not isinstance(contract, Mapping):
        raise ContractHold("missing prepared MCP contract")
    try:
        commands = [item["command"] for item in contract["verification_commands"]]
        digest = _contract_sha({
            key: value for key, value in contract.items() if key != "contract_id"
        })
        if (
            any(not isinstance(item, str) or not item for item in commands)
            or contract["task"] != task
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


def prepare_experimental_contract_sample_agent(
    repo_root: Path, *, state, client, success_criteria, forbidden_actions,
    risk_level: str = "medium",
):
    """Prepare an opt-in MCP contract from an Inspect sample before agent assembly.

    Only public criteria supplied explicitly by the host are forwarded. Hidden
    verifier material and unrelated TaskState metadata never enter MCP calls.
    No model, sandbox, or benchmark evaluation is run by this helper.
    """
    from .mcp_contract_adapter import ContractHold, prepare_contract

    task, paths, commands = _inspect_sample_inputs(state)
    for label, values in (
        ("public success criteria", success_criteria),
        ("forbidden actions", forbidden_actions),
    ):
        if (
            not isinstance(values, (list, tuple))
            or not values
            or any(not isinstance(value, str) or not value.strip() for value in values)
            or len(values) != len(set(values))
        ):
            raise ContractHold(f"missing or invalid {label}")
    if not callable(client):
        raise ContractHold("missing MCP contract client")

    contract = prepare_contract(
        client,
        task=task,
        allowed_paths=paths,
        forbidden_actions=forbidden_actions,
        success_criteria=success_criteria,
        verification_commands=commands,
        risk_level=risk_level,
    )
    agent, session = experimental_contract_sample_agent(
        repo_root, state=state, client=client, contract=contract,
    )
    return agent, session, contract


def prepare_experimental_contract_sample_batch(
    repo_root: Path, *, samples, client, risk_level: str = "medium",
):
    """Preflight and prepare independent opt-in agents for multiple Inspect samples.

    Validate the entire host-supplied batch before making any MCP calls, so a
    duplicate epoch or malformed public requirement cannot silently reuse a
    previous sample's evidence session. This does not execute the agents,
    register a third evaluation condition or authenticate native ToolCall IDs.
    """
    from .mcp_contract_adapter import ContractHold

    if not isinstance(samples, (list, tuple)) or not samples:
        raise ContractHold("missing Inspect sample batch")
    if not callable(client):
        raise ContractHold("missing MCP contract client")

    validated = []
    seen = set()
    for item in samples:
        if not isinstance(item, Mapping):
            raise ContractHold("malformed Inspect sample batch item")
        state = item.get("state")
        _inspect_sample_inputs(state)
        key = (state.sample_id, state.epoch)
        if key in seen:
            raise ContractHold("duplicate Inspect sample/epoch in batch")
        seen.add(key)
        criteria = item.get("success_criteria")
        forbidden = item.get("forbidden_actions")
        for label, values in (
            ("success criteria", criteria),
            ("forbidden actions", forbidden),
        ):
            if (
                not isinstance(values, (list, tuple))
                or not values
                or any(not isinstance(value, str) or not value.strip() for value in values)
                or len(values) != len(set(values))
            ):
                raise ContractHold(f"missing or invalid {label} for Inspect sample")
        validated.append((key, state, list(criteria), list(forbidden)))

    result = {}
    for key, state, criteria, forbidden in validated:
        result[key] = prepare_experimental_contract_sample_agent(
            repo_root, state=state, client=client,
            success_criteria=criteria, forbidden_actions=forbidden,
            risk_level=risk_level,
        )
    return result

def experimental_contract_sample_solver(
    repo_root: Path, *, client, success_criteria_by_sample,
    forbidden_actions, on_prepared,
):
    """Opt-in Inspect solver that prepares an isolated MCP agent per sample/epoch.

    The host supplies explicit public criteria and a synchronous callback to
    retain the EvidenceSession. The callback reports *preparation*, not task
    completion or independent evidence verification. This solver is intentionally
    not registered as a default Bench condition or exposed through the runner.
    """
    from inspect_ai.agent import as_solver
    from inspect_ai.solver import solver

    from .mcp_contract_adapter import ContractHold

    if not callable(client):
        raise ContractHold("missing MCP contract client")
    if not isinstance(success_criteria_by_sample, Mapping):
        raise ContractHold("missing public success criteria by sample")
    if not callable(on_prepared) or iscoroutinefunction(on_prepared):
        raise ContractHold("missing or asynchronous host preparation callback")
    if (
        not isinstance(forbidden_actions, (list, tuple))
        or not forbidden_actions
        or any(not isinstance(item, str) or not item.strip() for item in forbidden_actions)
        or len(forbidden_actions) != len(set(forbidden_actions))
    ):
        raise ContractHold("invalid forbidden actions")
    frozen_forbidden = tuple(forbidden_actions)

    # Freeze the host's public plan for this solver instance across epochs.
    criteria = {}
    for sample_id, values in success_criteria_by_sample.items():
        if (
            not isinstance(sample_id, str)
            or not re.fullmatch(r"[A-Za-z0-9_-]{3,80}", sample_id)
            or not isinstance(values, (list, tuple))
            or not values
            or any(not isinstance(item, str) or not item.strip() for item in values)
            or len(values) != len(set(values))
        ):
            raise ContractHold("invalid public success criteria by sample")
        criteria[sample_id] = tuple(values)

    @solver
    def scoped_contract_solver():
        seen_scopes = set()

        async def solve(state, generate):
            _inspect_sample_inputs(state)
            if state.sample_id not in criteria:
                raise ContractHold("missing public success criteria for Inspect sample")
            scope_key = (state.sample_id, state.epoch)
            if scope_key in seen_scopes:
                raise ContractHold("duplicate Inspect sample/epoch invocation")

            agent, session, contract = prepare_experimental_contract_sample_agent(
                repo_root, state=state, client=client,
                success_criteria=criteria[state.sample_id],
                forbidden_actions=frozen_forbidden,
            )
            converted = as_solver(agent)
            seen_scopes.add(scope_key)
            retained = on_prepared(session.execution_scope, session, contract)
            if isawaitable(retained):
                if iscoroutine(retained):
                    retained.close()
                raise ContractHold("host preparation callback must be synchronous")
            return await converted(state, generate)

        return solve

    return scoped_contract_solver()
