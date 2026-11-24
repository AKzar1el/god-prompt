"""Offline tests for an Inspect bash tool that captures real sandbox receipts.

No model, Docker, provider, or host shell is invoked. Sandbox execution is fake.
"""
import asyncio
import re

import pytest
from inspect_ai.util import ExecResult
import inspect_ai.util
from inspect_ai.tool._tool_def import tool_registry_info

from godprompt_bench.mcp_contract_adapter import (
    ContractHold,
    EvidenceSession,
    InspectExecutionScope,
)
from godprompt_bench.inspect_receipt_bash import receipt_bash_tool


CHECK = "python -m pytest tests/test_parser.py"
SCOPE = InspectExecutionScope("fixture-001", "attempt-001")


class FakeSandbox:
    def __init__(self, result=None, failure=None):
        self.result = result or ExecResult(success=True, returncode=0, stdout="1 passed", stderr="")
        self.failure = failure
        self.calls = []

    async def exec(self, cmd, timeout=None, user=None):
        self.calls.append((cmd, timeout, user))
        if self.failure is not None:
            raise self.failure
        return self.result


def make_session(*, commands=None):
    captured = []
    checks = commands if commands is not None else [{"id": "VC-01", "command": CHECK}]
    contract = {"schema": "godprompt.work_contract.v1", "verification_commands": checks}
    def mcp(name, payload):
        assert name == "review_work_evidence"
        captured.append(payload)
        has_ok = (
            len(payload["checks"]) == 1
            and payload["checks"][0]["exit_code"] == 0
            and bool(payload["checks"][0]["evidence_excerpt"])
        )
        return {"structuredContent": {
            "status": "REPORTED_READY_FOR_INDEPENDENT_REVIEW" if has_ok else "HOLD",
            "issues": [] if has_ok else [{"code": "VERIFICATION_NOT_PROVEN"}],
            "independently_verified": False,
            "completion_authorized": False,
        }}
    return EvidenceSession(mcp, contract, execution_scope=SCOPE), captured


def review(session):
    return session.review(changed_files=[], operations_performed=[], acceptance=[])


def test_receipt_bash_is_named_bash_and_preserves_stock_command_surface(monkeypatch):
    session, captured = make_session()
    sb = FakeSandbox(ExecResult(success=True, returncode=0, stdout="SECRET=example\n1 passed", stderr="warning"))
    monkeypatch.setattr(inspect_ai.util, "sandbox", lambda name=None: sb)
    command = receipt_bash_tool(session, scope=SCOPE, timeout=60, sandbox="docker-fixture")
    assert command.__name__ == "execute"
    assert tool_registry_info(command)[0] == "bash"
    assert asyncio.run(command(command=CHECK)) == "warning\nSECRET=example\n1 passed"
    assert sb.calls == [(["bash", "--login", "-c", CHECK], 60, None)]
    assert review(session)["status"] == "REPORTED_READY_FOR_INDEPENDENT_REVIEW"
    sent = captured[-1]["checks"][0]
    assert re.fullmatch(r"tool_id_sha256:[0-9a-f]{64}", sent["evidence_excerpt"].split(";")[0].split()[-1])
    assert sent["exit_code"] == 0
    assert "SECRET" not in str(captured[-1])


def test_identical_success_text_does_not_hide_nonzero_process_code(monkeypatch):
    session, captured = make_session()
    sb = FakeSandbox(ExecResult(success=False, returncode=9, stdout="1 passed", stderr=""))
    monkeypatch.setattr(inspect_ai.util, "sandbox", lambda name=None: sb)
    tool = receipt_bash_tool(session, scope=SCOPE)
    assert asyncio.run(tool(command=CHECK)) == "1 passed"
    assert review(session)["status"] == "HOLD"
    assert captured[-1]["checks"][0]["exit_code"] == 9


def test_unrelated_bash_command_preserves_stock_behavior_without_forged_check(monkeypatch):
    session, captured = make_session()
    sb = FakeSandbox()
    monkeypatch.setattr(inspect_ai.util, "sandbox", lambda name=None: sb)
    tool = receipt_bash_tool(session, scope=SCOPE)
    assert asyncio.run(tool(command="pwd")) == "1 passed"
    assert sb.calls[0][0] == ["bash", "--login", "-c", "pwd"]
    assert review(session)["status"] == "HOLD"
    assert captured[-1]["checks"] == []


def test_sandbox_error_or_denial_never_yields_receipt(monkeypatch):
    session, captured = make_session()
    sb = FakeSandbox(failure=TimeoutError("execution cancelled"))
    monkeypatch.setattr(inspect_ai.util, "sandbox", lambda name=None: sb)
    tool = receipt_bash_tool(session, scope=SCOPE)
    with pytest.raises(TimeoutError):
        asyncio.run(tool(command=CHECK))
    assert review(session)["status"] == "HOLD"
    assert captured[-1]["checks"] == []


def test_duplicate_execution_fails_closed_instead_of_reusing_receipt(monkeypatch):
    session, _ = make_session()
    sb = FakeSandbox()
    monkeypatch.setattr(inspect_ai.util, "sandbox", lambda name=None: sb)
    tool = receipt_bash_tool(session, scope=SCOPE)
    assert asyncio.run(tool(command=CHECK)) == "1 passed"
    with pytest.raises(ContractHold, match="duplicate"):
        asyncio.run(tool(command=CHECK))


def test_ambiguous_contract_command_and_cross_sample_scope_are_rejected(monkeypatch):
    session, _ = make_session(commands=[{"id": "VC-01", "command": CHECK}, {"id": "VC-02", "command": CHECK}])
    sb = FakeSandbox()
    monkeypatch.setattr(inspect_ai.util, "sandbox", lambda name=None: sb)
    with pytest.raises(ContractHold, match="ambiguous"):
        receipt_bash_tool(session, scope=SCOPE)
    session, _ = make_session(commands=[
        {"id": "VC-01", "command": CHECK},
        {"id": "VC-01", "command": "python -m pytest tests/other.py"},
    ])
    with pytest.raises(ContractHold, match="duplicate verification ID"):
        receipt_bash_tool(session, scope=SCOPE)
    other = InspectExecutionScope("fixture-002", "attempt-001")
    session, _ = make_session()
    with pytest.raises(ContractHold, match="scope"):
        receipt_bash_tool(session, scope=other)
    assert sb.calls == []


def test_inconsistent_exec_result_is_rejected_not_recorded(monkeypatch):
    session, captured = make_session()
    sb = FakeSandbox(ExecResult(success=True, returncode=4, stdout="1 passed", stderr=""))
    monkeypatch.setattr(inspect_ai.util, "sandbox", lambda name=None: sb)
    tool = receipt_bash_tool(session, scope=SCOPE)
    with pytest.raises(ContractHold, match="status"):
        asyncio.run(tool(command=CHECK))
    assert review(session)["status"] == "HOLD"
    assert captured[-1]["checks"] == []
