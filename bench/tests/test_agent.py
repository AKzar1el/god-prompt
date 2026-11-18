from pathlib import Path

import pytest

from godprompt_bench.agent import COMMON_AGENT_INSTRUCTIONS, condition_prompt
from godprompt_bench.corpus import load_fixture_bundle


def test_only_condition_payload_differs(tmp_path: Path):
    prompt = "# GodPrompt\nEVIDENCE BEFORE CLAIMS\n"
    (tmp_path / 'GodPrompt.md').write_text(prompt, encoding='utf-8')
    baseline = condition_prompt('baseline', tmp_path)
    godprompt = condition_prompt('godprompt', tmp_path)
    assert 'GodPrompt' not in baseline
    assert prompt.strip() in godprompt
    assert baseline.endswith(COMMON_AGENT_INSTRUCTIONS)
    assert godprompt.endswith(COMMON_AGENT_INSTRUCTIONS)


def test_unknown_condition_is_rejected(tmp_path: Path):
    (tmp_path / 'GodPrompt.md').write_text('x', encoding='utf-8')
    with pytest.raises(ValueError, match='condition'):
        condition_prompt('other', tmp_path)


@pytest.mark.parametrize('content', ['', '   \n\t  '])
def test_empty_godprompt_file_cannot_silently_run_treatment_as_scaffold(tmp_path: Path, content: str):
    (tmp_path / 'GodPrompt.md').write_text(content, encoding='utf-8')
    with pytest.raises(ValueError, match='GodPrompt.md.*empty'):
        condition_prompt('godprompt', tmp_path)


def test_fixture_bundle_keeps_hidden_verifier_out_of_model_files():
    root = Path(__file__).parents[1]
    bundle = load_fixture_bundle(root / 'tasks' / 'impl-py-slugify' / 'fixture.json')
    assert 'src/text.py' in bundle.files
    assert '.godprompt_verifier.py' not in bundle.files
    assert bundle.hidden_verifier.strip()


def test_coding_agent_applies_identical_single_attempt_approval_policy(tmp_path: Path, monkeypatch):
    import sys
    import types

    (tmp_path / 'GodPrompt.md').write_text('# GP', encoding='utf-8')
    agent_mod = types.ModuleType('inspect_ai.agent')
    tool_mod = types.ModuleType('inspect_ai.tool')
    approval_mod = types.ModuleType('inspect_ai.approval')

    def react(**kwargs):
        return kwargs

    agent_mod.react = react
    tool_mod.bash = lambda **kwargs: ('bash', kwargs)
    tool_mod.text_editor = lambda **kwargs: ('text_editor', kwargs)

    class ApprovalPolicy:
        def __init__(self, approver, tools):
            self.approver = approver
            self.tools = tools

    approval_mod.ApprovalPolicy = ApprovalPolicy
    monkeypatch.setitem(sys.modules, 'inspect_ai.agent', agent_mod)
    monkeypatch.setitem(sys.modules, 'inspect_ai.tool', tool_mod)
    monkeypatch.setitem(sys.modules, 'inspect_ai.approval', approval_mod)

    import godprompt_bench.agent as agent
    monkeypatch.setattr(agent, 'inspect_workspace_approver', lambda: 'approver')

    baseline = agent.coding_agent('baseline', tmp_path)
    godprompt = agent.coding_agent('godprompt', tmp_path)
    for built in (baseline, godprompt):
        assert built['attempts'] == 1
        assert [tool[0] for tool in built['tools']] == ['bash', 'text_editor']
        assert len(built['approval']) == 1
        assert built['approval'][0].tools == ['bash', 'text_editor']
        assert built['approval'][0].approver == 'approver'


def test_opt_in_contract_agent_reuses_named_approval_and_scoped_bash(tmp_path: Path, monkeypatch):
    import sys
    import types
    from godprompt_bench.mcp_contract_adapter import EvidenceSession, InspectExecutionScope
    import godprompt_bench.agent as agent
    import godprompt_bench.inspect_receipt_bash as receipt_module

    (tmp_path / 'GodPrompt.md').write_text('# GP', encoding='utf-8')
    scope = InspectExecutionScope('fixture-001', 'attempt-001')
    session = EvidenceSession(
        lambda *_: {},
        {'schema': 'godprompt.work_contract.v1', 'verification_commands': [
            {'id': 'VC-01', 'command': 'python -m pytest tests/test_parser.py'},
        ]},
        execution_scope=scope,
    )
    fake_agent = types.ModuleType('inspect_ai.agent')
    fake_tool = types.ModuleType('inspect_ai.tool')
    fake_approval = types.ModuleType('inspect_ai.approval')
    fake_agent.react = lambda **kwargs: kwargs
    fake_tool.text_editor = lambda **kwargs: ('text_editor', kwargs)
    class ApprovalPolicy:
        def __init__(self, approver, tools):
            self.approver = approver
            self.tools = tools
    fake_approval.ApprovalPolicy = ApprovalPolicy
    monkeypatch.setitem(sys.modules, 'inspect_ai.agent', fake_agent)
    monkeypatch.setitem(sys.modules, 'inspect_ai.tool', fake_tool)
    monkeypatch.setitem(sys.modules, 'inspect_ai.approval', fake_approval)
    monkeypatch.setattr(agent, 'inspect_workspace_approver', lambda: 'approver')
    received = []
    def fake_receipt_bash(actual_session, *, scope, timeout):
        received.append((actual_session, scope, timeout))
        return ('bash', 'observed-process-result')
    monkeypatch.setattr(receipt_module, 'receipt_bash_tool', fake_receipt_bash)

    built = agent.experimental_contract_coding_agent(tmp_path, session=session, scope=scope)
    assert received == [(session, scope, 60)]
    assert built['prompt'] == agent.condition_prompt('godprompt', tmp_path)
    assert built['tools'] == [('bash', 'observed-process-result'), ('text_editor', {'timeout': 60})]
    assert built['attempts'] == 1
    assert len(built['approval']) == 1
    assert built['approval'][0].tools == ['bash', 'text_editor']
    assert built['approval'][0].approver == 'approver'
