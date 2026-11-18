"""Opt-in, offline Bench 2.0 bridge to the released GodPrompt MCP contract tools.

This is a *client-side* boundary, not a third benchmark condition. It can
prepare/review deterministic contracts with an injected, read-only MCP client,
and accept receipts only from the caller's trusted tool-result instrumentation.
It cannot execute commands, contact model providers, or authorize completion.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

# Inspect adapter inputs against an actual released source, not an open PR.
MCP_RELEASE_TAG = "v1.1.1"
MCP_RELEASE_SHA = "5934340cd4279d7ce103f344279058f54e0c6668"
CONTRACT_SCHEMA = "godprompt.work_contract.v1"

MCPCall = Callable[[str, dict[str, Any]], Mapping[str, Any]]


class ContractHold(ValueError):
    """Fail closed when a contract, execution receipt, or review is untrustworthy."""


@dataclass(frozen=True)
class ObservedToolResult:
    """A result emitted by a trusted tool-execution hook, never by the model.

    The caller is responsible for proving the originating tool call/session.
    Merely constructing this object does not attest that a process ran.
    """

    tool_call_id: str
    command: str
    exit_code: int | None
    output: str


@dataclass(frozen=True)
class InspectExecutionScope:
    """Host-assigned sample and attempt identity for an Inspect sandbox result."""

    sample_id: str
    attempt_id: str


def _mcp_json(result: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(result, Mapping) or result.get("isError") is True:
        raise ContractHold("MCP tool call failed")
    value = result.get("structuredContent")
    if value is None:
        content = result.get("content")
        if not isinstance(content, list) or not content:
            raise ContractHold("MCP response has no structured payload")
        part = content[0]
        if not isinstance(part, Mapping) or part.get("type") != "text":
            raise ContractHold("MCP response has no JSON text payload")
        raw = part.get("text")
        if not isinstance(raw, str) or len(raw) > 131072:
            raise ContractHold("MCP payload missing or too large")
        try:
            value = json.loads(raw)
        except (ValueError, TypeError) as exc:
            raise ContractHold("MCP response is not valid JSON") from exc
    if not isinstance(value, dict):
        raise ContractHold("MCP response JSON must be an object")
    return value


def _contract_sha(payload: Mapping[str, Any]) -> str:
    # The released MCP fingerprints its ordered object with JSON.stringify.
    encoded = json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def prepare_contract(
    client: MCPCall,
    *,
    task: str,
    allowed_paths: Sequence[str],
    forbidden_actions: Sequence[str],
    success_criteria: Sequence[str],
    verification_commands: Sequence[str],
    risk_level: str = "medium",
) -> dict[str, Any]:
    """Call only released deterministic MCP tools; invent no scopes or checks.

    This function never runs verification commands or a model. Ambiguous
    classifications or incomplete contract definitions must be resolved first.
    """
    if not isinstance(task, str) or not (5 <= len(task.strip()) <= 1000):
        raise ContractHold("task must contain 5-1000 characters for classify_task")
    classification = _mcp_json(client("classify_task", {"description": task}))
    task_type = classification.get("task_type")
    if classification.get("ambiguous") is not False or task_type not in {
        "BUILD", "DEBUG", "REFACTOR", "CONTENT", "DESIGN", "SHIP",
        "ANALYZE", "AUTOMATE", "PLAN",
    }:
        raise ContractHold("classification is ambiguous or unclassified")
    if risk_level not in ("low", "medium", "high", "critical"):
        raise ContractHold("invalid risk level")
    raw_input = {
        "task": task,
        "task_type": task_type,
        "risk_level": risk_level,
        "allowed_paths": list(allowed_paths),
        "forbidden_actions": list(forbidden_actions),
        "success_criteria": list(success_criteria),
        "verification_commands": list(verification_commands),
    }
    created = _mcp_json(client("create_work_contract", raw_input))
    if created.get("definition_status") != "DEFINED" or created.get("issues"):
        raise ContractHold("MCP contract requires additional definition")
    contract = created.get("contract")
    if not isinstance(contract, dict) or contract.get("schema") != CONTRACT_SCHEMA:
        raise ContractHold("unexpected MCP contract schema")
    try:
        actual = {
            "task": contract["task"],
            "task_type": contract["task_type"],
            "risk_level": contract["risk_level"],
            "allowed_paths": contract["allowed_paths"],
            "forbidden_actions": contract["forbidden_actions"],
            "success_criteria": [c["text"] for c in contract["success_criteria"]],
            "verification_commands": [c["command"] for c in contract["verification_commands"]],
        }
        fields = {k: actual[k] for k in raw_input}
        canonical = {k: v for k, v in contract.items() if k != "contract_id"}
        digest = _contract_sha(canonical)
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise ContractHold("MCP contract fields are malformed") from exc
    if fields != raw_input or contract.get("contract_id") != digest:
        raise ContractHold("MCP contract changed supplied requirements or fingerprint")
    if (len(set(c["id"] for c in contract["verification_commands"])) !=
            len(contract["verification_commands"])):
        raise ContractHold("duplicate verification IDs")
    return contract


class EvidenceSession:
    """Ephemeral evidence bridge; a context reset intentionally drops receipts."""

    def __init__(
        self,
        client: MCPCall,
        contract: Mapping[str, Any],
        *,
        execution_scope: InspectExecutionScope | None = None,
    ):
        if not isinstance(contract, Mapping) or contract.get("schema") != CONTRACT_SCHEMA:
            raise ContractHold("invalid work contract")
        if execution_scope is not None and (
            not isinstance(execution_scope, InspectExecutionScope)
            or not all(
                isinstance(part, str) and re.fullmatch(r"[A-Za-z0-9_-]{3,80}", part)
                for part in (execution_scope.sample_id, execution_scope.attempt_id)
            )
        ):
            raise ContractHold("invalid Inspect execution scope")
        self.client = client
        self.contract = dict(contract)
        self.execution_scope = execution_scope
        self._checks: dict[str, dict[str, Any]] = {}
        self._tool_call_ids: set[str] = set()

    def observe_inspect_exec(
        self,
        check_id: str,
        *,
        scope: InspectExecutionScope,
        tool_call_id: str,
        command: str,
        exec_result: Any,
        event_complete: bool,
    ) -> None:
        """Capture a trusted sandbox ExecResult without guessing from ToolEvent.

        Call only from host-controlled instrumentation *after* the ordinary
        Inspect tool approval and sandbox execution. This helper neither runs
        commands nor proves that its caller was trusted. The stock Inspect
        bash ToolEvent is insufficient: it discards the process return code.
        """
        if self.execution_scope is None or scope != self.execution_scope:
            raise ContractHold("missing or cross-sample Inspect execution scope")
        if event_complete is not True:
            raise ContractHold("incomplete or cancelled Inspect execution event")
        try:
            from inspect_ai.util import ExecResult
        except ImportError as exc:
            raise ContractHold("pinned Inspect runtime is unavailable") from exc
        if not isinstance(exec_result, ExecResult):
            raise ContractHold("not an Inspect sandbox ExecResult")
        if (
            type(exec_result.returncode) is not int
            or type(exec_result.success) is not bool
            or exec_result.success != (exec_result.returncode == 0)
        ):
            raise ContractHold("inconsistent or missing sandbox process status")
        if type(exec_result.stdout) is not str or type(exec_result.stderr) is not str:
            raise ContractHold("sandbox output is not complete text")
        output = "\n".join(
            part for part in (exec_result.stdout, exec_result.stderr) if part
        )
        if len(output.encode("utf-8")) > 65536:
            raise ContractHold("sandbox output exceeds capture limit")
        self.observe_check(
            check_id,
            ObservedToolResult(tool_call_id, command, exec_result.returncode, output),
        )

    def observe_check(self, check_id: str, result: ObservedToolResult) -> None:
        """Ingest one event only at the trusted Inspect tool-result boundary.

        Do not pass model-written transcripts or self-reported exit codes.
        The adapter never runs the command; the existing sandbox/approval path
        remains the only place to execute it.
        """
        if not isinstance(result, ObservedToolResult):
            raise ContractHold("only observed execution events are accepted")
        expected = {
            item["id"]: item["command"]
            for item in self.contract["verification_commands"]
        }
        if check_id not in expected or check_id in self._checks:
            raise ContractHold("unknown or duplicate verification ID")
        if result.command != expected[check_id]:
            raise ContractHold("observed command does not match contract")
        if type(result.exit_code) is not int and result.exit_code is not None:
            raise ContractHold("invalid observed exit code")
        if not isinstance(result.output, str):
            raise ContractHold("observed tool output must be text")
        if (
            not isinstance(result.tool_call_id, str)
            or not re.fullmatch(r"[A-Za-z0-9_-]{3,80}", result.tool_call_id)
            or result.tool_call_id in self._tool_call_ids
        ):
            raise ContractHold("missing, malformed or replayed tool invocation ID")

        # Never send raw stdout/stderr (which may contain secrets) to an MCP.
        # Empty output remains empty evidence so the MCP review must HOLD.
        excerpt = ""
        if result.output.strip():
            encoded = result.output.encode("utf-8")
            excerpt = (
                f"captured tool result {result.tool_call_id}; bytes={len(encoded)}; "
                f"sha256:{hashlib.sha256(encoded).hexdigest()}"
            )
        self._checks[check_id] = {
            "id": check_id,
            "command": expected[check_id],
            "exit_code": result.exit_code,
            "evidence_excerpt": excerpt,
            "source": "tool_output",
        }
        self._tool_call_ids.add(result.tool_call_id)

    def review(
        self,
        *,
        changed_files: Sequence[str],
        operations_performed: Sequence[str],
        acceptance: Sequence[Mapping[str, Any]],
        human_review_reported: bool = False,
    ) -> dict[str, Any]:
        """Request a reported MCP review, never an independently verified one."""
        payload = {
            "contract": self.contract,
            "changed_files": list(changed_files),
            "operations_performed": list(operations_performed),
            "checks": list(self._checks.values()),
            "acceptance": [dict(item) for item in acceptance],
            "observations": [],
            "human_review_reported": human_review_reported,
        }
        reviewed = _mcp_json(self.client("review_work_evidence", payload))
        if (
            reviewed.get("independently_verified") is not False
            or reviewed.get("completion_authorized") is not False
            or reviewed.get("status") not in ("HOLD", "REPORTED_READY_FOR_INDEPENDENT_REVIEW")
        ):
            raise ContractHold("MCP review cannot claim independent verification or authorization")
        if reviewed["status"] == "REPORTED_READY_FOR_INDEPENDENT_REVIEW" and reviewed.get("issues"):
            raise ContractHold("contradictory MCP review result")
        return reviewed
