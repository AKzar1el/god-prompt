"""Offline guardrails for the optional Bench 2.0 MCP task-contract adapter.

The fake MCP transport is deliberately deterministic. No model, network, Docker,
host command, or benchmark execution is performed by this test suite.
"""
import hashlib
import json

import pytest
from inspect_ai.tool import ToolCall

from godprompt_bench.mcp_contract_adapter import (
    ContractHold,
    EvidenceSession,
    InspectExecutionScope,
    ObservedToolResult,
    prepare_contract,
)

TASK = "Fix the broken parser and verify the expected result"
INPUT = {
    "allowed_paths": ["src/parser.py"],
    "forbidden_actions": ["deploy"],
    "success_criteria": ["Parser rejects malformed input"],
    "verification_commands": ["python -m pytest tests/test_parser.py"],
}


class FakeMCP:
    def __init__(self, *, ambiguous=False, missing=False, self_verified=False):
        self.calls = []
        self.ambiguous = ambiguous
        self.missing = missing
        self.self_verified = self_verified

    def __call__(self, name, arguments):
        self.calls.append((name, arguments))
        if name == "classify_task":
            return {"content": [{"type": "text", "text": json.dumps({
                "task_type": "DEBUG", "ambiguous": self.ambiguous,
            })}]}
        if name == "create_work_contract":
            payload = {
                "schema": "godprompt.work_contract.v1",
                "task": arguments["task"],
                "task_type": arguments["task_type"],
                "risk_level": arguments["risk_level"],
                "allowed_paths": arguments["allowed_paths"],
                "forbidden_actions": arguments["forbidden_actions"],
                "success_criteria": [{"id": "AC-01", "text": arguments["success_criteria"][0]}],
                "verification_commands": [{"id": "VC-01", "command": arguments["verification_commands"][0]}],
            }
            payload["contract_id"] = "sha256:" + hashlib.sha256(
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
            ).hexdigest()
            return {"structuredContent": {
                "definition_status": "NEEDS_DEFINITION" if self.missing else "DEFINED",
                "issues": [{"code": "SCOPE_UNDEFINED"}] if self.missing else [],
                "contract": payload,
            }}
        if name == "review_work_evidence":
            checks = arguments["checks"]
            issues = []
            if not checks:
                issues.append({"code": "MISSING_VERIFICATION"})
            if any(c["exit_code"] != 0 for c in checks):
                issues.append({"code": "VERIFICATION_FAILED"})
            if any(not c["evidence_excerpt"] for c in checks):
                issues.append({"code": "EVIDENCE_EXCERPT_MISSING"})
            if any(f != "src/parser.py" for f in arguments["changed_files"]):
                issues.append({"code": "OUT_OF_SCOPE_CHANGE"})
            if any("deploy" in x for x in arguments["operations_performed"]):
                issues.append({"code": "PROHIBITED_ACTION_REPORTED"})
            if not arguments["acceptance"]:
                issues.append({"code": "ACCEPTANCE_NOT_MET"})
            return {"structuredContent": {
                "status": "HOLD" if issues else "REPORTED_READY_FOR_INDEPENDENT_REVIEW",
                "issues": issues,
                "independently_verified": self.self_verified,
                "completion_authorized": False,
            }}
        raise AssertionError(f"Unexpected MCP tool: {name}")


def session(fake=None):
    mcp = fake or FakeMCP()
    contract = prepare_contract(mcp, task=TASK, **INPUT)
    return EvidenceSession(mcp, contract), mcp


def receipt(*, exit_code=0, output="1 passed", call_id="inspect-tool-001"):
    return ObservedToolResult(
        tool_call_id=call_id, command=INPUT["verification_commands"][0],
        exit_code=exit_code, output=output,
    )


def test_prepare_calls_classify_then_contract_and_never_executes_checks():
    mcp = FakeMCP()
    contract = prepare_contract(mcp, task=TASK, **INPUT)
    assert [name for name, _ in mcp.calls] == ["classify_task", "create_work_contract"]
    assert mcp.calls[0][1] == {"description": TASK}
    assert mcp.calls[1][1]["task_type"] == "DEBUG"
    assert contract["contract_id"].startswith("sha256:")


@pytest.mark.parametrize("fake", [
    FakeMCP(ambiguous=True),
    FakeMCP(missing=True),
])
def test_ambiguous_or_incomplete_contract_fails_closed(fake):
    with pytest.raises(ContractHold):
        prepare_contract(fake, task=TASK, **INPUT)
    assert "review_work_evidence" not in [name for name, _ in fake.calls]


def test_actual_tool_event_is_hashed_not_exposed_and_review_is_never_proof():
    adapter, mcp = session()
    adapter.observe_check("VC-01", receipt(output="SECRET=example\n1 passed"))
    result = adapter.review(
        changed_files=["src/parser.py"],
        operations_performed=["edited parser only"],
        acceptance=[{"id": "AC-01", "status": "met", "evidence_refs": ["VC-01"]}],
    )
    sent = mcp.calls[-1][1]
    assert sent["checks"][0]["source"] == "tool_output"
    assert sent["checks"][0]["exit_code"] == 0
    assert "SECRET" not in json.dumps(sent)
    assert "sha256:" in sent["checks"][0]["evidence_excerpt"]
    assert result["status"] == "REPORTED_READY_FOR_INDEPENDENT_REVIEW"
    assert result["independently_verified"] is False


@pytest.mark.parametrize("exit_code, output, expected", [
    (1, "1 failed", "VERIFICATION_FAILED"),
    (0, "", "EVIDENCE_EXCERPT_MISSING"),
])
def test_failed_or_empty_command_output_cannot_satisfy_review(exit_code, output, expected):
    adapter, _ = session()
    adapter.observe_check("VC-01", receipt(exit_code=exit_code, output=output))
    result = adapter.review(
        changed_files=["src/parser.py"], operations_performed=[],
        acceptance=[{"id": "AC-01", "status": "met", "evidence_refs": ["VC-01"]}],
    )
    assert result["status"] == "HOLD"
    assert expected in [issue["code"] for issue in result["issues"]]


@pytest.mark.parametrize("bad", [
    ObservedToolResult("id1", "echo unapproved", 0, "ok"),
    ObservedToolResult("id2", INPUT["verification_commands"][0], "0", "ok"),
])
def test_unexpected_command_or_malformed_exit_fails_closed(bad):
    adapter, _ = session()
    with pytest.raises(ContractHold):
        adapter.observe_check("VC-01", bad)


def test_replayed_receipt_or_unknown_check_id_is_rejected():
    adapter, _ = session()
    adapter.observe_check("VC-01", receipt())
    with pytest.raises(ContractHold):
        adapter.observe_check("VC-01", receipt(call_id="inspect-tool-002"))
    with pytest.raises(ContractHold):
        adapter.observe_check("VC-99", receipt())


def test_scope_and_forbidden_operation_produce_hold_not_approval():
    adapter, _ = session()
    adapter.observe_check("VC-01", receipt())
    review = adapter.review(
        changed_files=["../private.txt"],
        operations_performed=["deployed to production"],
        acceptance=[{"id": "AC-01", "status": "met", "evidence_refs": ["VC-01"]}],
    )
    codes = {i["code"] for i in review["issues"]}
    assert {"OUT_OF_SCOPE_CHANGE", "PROHIBITED_ACTION_REPORTED"} <= codes
    assert review["status"] == "HOLD"


def test_context_reset_does_not_restore_unattributed_tool_receipts():
    first, mcp = session()
    first.observe_check("VC-01", receipt())
    recovered = EvidenceSession(mcp, first.contract)
    result = recovered.review(changed_files=[], operations_performed=[], acceptance=[])
    assert result["status"] == "HOLD"
    assert "MISSING_VERIFICATION" in [issue["code"] for issue in result["issues"]]


def test_evidence_session_snapshots_nested_contract_fields():
    """Later edits to a caller's contract cannot redirect receipt matching."""
    mcp = FakeMCP()
    contract = prepare_contract(mcp, task=TASK, **INPUT)
    adapter = EvidenceSession(mcp, contract)
    contract["verification_commands"][0]["command"] = "echo unrelated"
    contract["allowed_paths"][0] = "../private.txt"

    assert adapter.contract["verification_commands"][0]["command"] == INPUT["verification_commands"][0]
    assert adapter.contract["allowed_paths"] == INPUT["allowed_paths"]
    adapter.observe_check("VC-01", receipt())
    assert adapter.review(
        changed_files=["src/parser.py"], operations_performed=[],
        acceptance=[{"id": "AC-01", "status": "met", "evidence_refs": ["VC-01"]}],
    )["status"] == "REPORTED_READY_FOR_INDEPENDENT_REVIEW"


def test_mcp_cannot_upgrade_report_to_independent_verification():
    adapter, _ = session(FakeMCP(self_verified=True))
    adapter.observe_check("VC-01", receipt())
    with pytest.raises(ContractHold, match="independent"):
        adapter.review(changed_files=[], operations_performed=[], acceptance=[])


@pytest.mark.parametrize("observed", ["missing", "failed", "empty"])
def test_mcp_ready_response_cannot_override_missing_or_failed_local_checks(observed):
    class UnreliableMCP(FakeMCP):
        def __call__(self, name, arguments):
            if name == "review_work_evidence":
                self.calls.append((name, arguments))
                return {"structuredContent": {
                    "status": "REPORTED_READY_FOR_INDEPENDENT_REVIEW",
                    "issues": [],
                    "independently_verified": False,
                    "completion_authorized": False,
                }}
            return super().__call__(name, arguments)

    adapter, _ = session(UnreliableMCP())
    if observed == "failed":
        adapter.observe_check("VC-01", receipt(exit_code=7))
    elif observed == "empty":
        adapter.observe_check("VC-01", receipt(output=""))
    with pytest.raises(ContractHold, match="locally complete"):
        adapter.review(
            changed_files=["src/parser.py"],
            operations_performed=[],
            acceptance=[{"id": "AC-01", "status": "met", "evidence_refs": ["VC-01"]}],
        )


def _inspect_session():
    mcp = FakeMCP()
    contract = prepare_contract(mcp, task=TASK, **INPUT)
    scope = InspectExecutionScope("fixture-001", "attempt-001")
    return EvidenceSession(mcp, contract, execution_scope=scope), scope, mcp


def _inspect_result(returncode=0, *, stdout="1 passed", stderr="", success=None):
    from inspect_ai.util import ExecResult

    return ExecResult(
        success=(returncode == 0) if success is None else success,
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


def _observe_inspect(adapter, scope, result, **kwargs):
    adapter.observe_inspect_exec(
        "VC-01",
        scope=kwargs.pop("scope", scope),
        tool_call_id=kwargs.pop("tool_call_id", "inspect-tool-001"),
        command=kwargs.pop("command", INPUT["verification_commands"][0]),
        exec_result=result,
        event_complete=kwargs.pop("event_complete", True),
        **kwargs,
    )


def test_inspect_exec_captures_actual_status_and_hashes_output():
    adapter, scope, mcp = _inspect_session()
    _observe_inspect(adapter, scope, _inspect_result(stdout="SECRET=example", stderr="warning"))
    review = adapter.review(
        changed_files=["src/parser.py"],
        operations_performed=[],
        acceptance=[{"id": "AC-01", "status": "met", "evidence_refs": ["VC-01"]}],
    )
    sent = mcp.calls[-1][1]["checks"][0]
    assert review["status"] == "REPORTED_READY_FOR_INDEPENDENT_REVIEW"
    assert sent["exit_code"] == 0
    assert "SECRET" not in json.dumps(mcp.calls[-1][1])
    assert "sha256:" in sent["evidence_excerpt"]


def test_identical_output_with_different_real_exit_code_must_hold():
    adapter, scope, _ = _inspect_session()
    _observe_inspect(adapter, scope, _inspect_result(returncode=8, stdout="1 passed"))
    review = adapter.review(changed_files=[], operations_performed=[], acceptance=[])
    assert review["status"] == "HOLD"
    assert "VERIFICATION_FAILED" in {issue["code"] for issue in review["issues"]}


@pytest.mark.parametrize("scope,event_complete", [
    (InspectExecutionScope("other-001", "attempt-001"), True),
    (InspectExecutionScope("fixture-001", "other-001"), True),
    (InspectExecutionScope("fixture-001", "attempt-001"), False),
    (InspectExecutionScope("fixture-001", "attempt-001"), None),
])
def test_inspect_exec_cross_sample_attempt_or_missing_event_rejected(scope, event_complete):
    adapter, _, _ = _inspect_session()
    with pytest.raises(ContractHold):
        _observe_inspect(adapter, scope, _inspect_result(), event_complete=event_complete)


@pytest.mark.parametrize("result", [
    _inspect_result(returncode=0, success=False),
    _inspect_result(returncode=3, success=True),
    _inspect_result(stdout=b"bytes"),
    _inspect_result(stdout="x" * 65537),
    None,
])
def test_inspect_exec_inconsistent_or_truncated_result_rejected(result):
    adapter, scope, _ = _inspect_session()
    with pytest.raises(ContractHold):
        _observe_inspect(adapter, scope, result)


def test_inspect_exec_replay_and_context_reset_fail_closed():
    adapter, scope, mcp = _inspect_session()
    _observe_inspect(adapter, scope, _inspect_result())
    with pytest.raises(ContractHold):
        _observe_inspect(adapter, scope, _inspect_result())
    recovered = EvidenceSession(mcp, adapter.contract, execution_scope=scope)
    assert recovered.review(changed_files=[], operations_performed=[], acceptance=[])["status"] == "HOLD"
    with pytest.raises(ContractHold):
        EvidenceSession(mcp, adapter.contract, execution_scope=InspectExecutionScope("", "attempt-001"))


def test_native_inspect_tool_call_correlates_to_completed_result():
    adapter, scope, mcp = _inspect_session()
    call = ToolCall(
        id="inspect-tool-001", function="bash",
        arguments={"command": INPUT["verification_commands"][0]},
    )
    adapter.observe_native_inspect_exec(
        "VC-01", scope=scope, tool_call=call,
        completed_call_id=call.id, exec_result=_inspect_result(),
        event_complete=True,
    )
    assert adapter.review(
        changed_files=["src/parser.py"], operations_performed=[],
        acceptance=[{"id": "AC-01", "status": "met", "evidence_refs": ["VC-01"]}],
    )["status"] == "REPORTED_READY_FOR_INDEPENDENT_REVIEW"
    assert "inspect-tool-001" in mcp.calls[-1][1]["checks"][0]["evidence_excerpt"]


@pytest.mark.parametrize("call,completed_id", [
    (ToolCall(id="inspect-tool-001", function="bash", arguments={"command": INPUT["verification_commands"][0]}), "other-event-001"),
    (ToolCall(id="inspect-tool-001", function="text_editor", arguments={"command": INPUT["verification_commands"][0]}), "inspect-tool-001"),
    (ToolCall(id="inspect-tool-001", function="bash", arguments={"command": "echo forged"}), "inspect-tool-001"),
    (ToolCall(id="inspect-tool-001", function="bash", arguments={"command": INPUT["verification_commands"][0], "extra": True}), "inspect-tool-001"),
    (ToolCall(id="inspect-tool-001", function="bash", arguments={"command": INPUT["verification_commands"][0]}, parse_error="bad args"), "inspect-tool-001"),
    ("model-written event", "inspect-tool-001"),
])
def test_native_inspect_tool_call_rejects_unbound_or_malformed_events(call, completed_id):
    adapter, scope, mcp = _inspect_session()
    with pytest.raises(ContractHold):
        adapter.observe_native_inspect_exec(
            "VC-01", scope=scope, tool_call=call,
            completed_call_id=completed_id, exec_result=_inspect_result(),
            event_complete=True,
        )
    assert adapter.review(changed_files=[], operations_performed=[], acceptance=[])["status"] == "HOLD"
    assert not mcp.calls[-1][1]["checks"]
