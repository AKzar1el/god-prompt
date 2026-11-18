from pathlib import Path

import pytest

pytest.importorskip('inspect_ai')

from godprompt_bench.eval import build_task
from godprompt_bench.agent import experimental_contract_coding_agent
from godprompt_bench.mcp_contract_adapter import ContractHold, EvidenceSession, InspectExecutionScope

ROOT = Path(__file__).parents[1]
REPO_ROOT = ROOT.parent


def test_current_inspect_api_builds_both_conditions():
    for condition in ('baseline', 'godprompt'):
        task = build_task(
            condition,
            ROOT,
            REPO_ROOT,
            ['impl-py-slugify'],
            epochs=1,
            max_messages=5,
            max_time_seconds=30,
            max_output_tokens=1024,
        )
        assert task is not None


def test_experimental_agent_assembles_with_real_inspect_and_rejects_cross_sample():
    scope = InspectExecutionScope('fixture-001', 'attempt-001')
    session = EvidenceSession(
        lambda *_: {},
        {'schema': 'godprompt.work_contract.v1', 'verification_commands': [
            {'id': 'VC-01', 'command': 'python -m pytest tests/test_parser.py'},
        ]},
        execution_scope=scope,
    )
    assert experimental_contract_coding_agent(REPO_ROOT, session=session, scope=scope) is not None
    other_scope = InspectExecutionScope('fixture-002', 'attempt-001')
    with pytest.raises(ContractHold, match='scope'):
        experimental_contract_coding_agent(REPO_ROOT, session=session, scope=other_scope)
