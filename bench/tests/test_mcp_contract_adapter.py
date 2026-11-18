"""Offline guardrails for the optional Bench 2.0 MCP task-contract adapter.

The fake MCP transport is deliberately deterministic. No model, network, Docker,
host command, or benchmark execution is performed by this test suite.
"""
import hashlib
import json

import pytest

from godprompt_bench.mcp_contract_adapter import (
    ContractHold,
    EvidenceSession,
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


def test_mcp_cannot_upgrade_report_to_independent_verification():
    adapter, _ = session(FakeMCP(self_verified=True))
    adapter.observe_check("VC-01", receipt())
    with pytest.raises(ContractHold, match="independent"):
        adapter.review(changed_files=[], operations_performed=[], acceptance=[])
