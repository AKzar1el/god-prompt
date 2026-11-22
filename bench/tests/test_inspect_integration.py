import asyncio
from pathlib import Path

import pytest

pytest.importorskip('inspect_ai')

from godprompt_bench.eval import build_task
from godprompt_bench.agent import experimental_contract_coding_agent
from godprompt_bench.mcp_contract_adapter import ContractHold, EvidenceSession, InspectExecutionScope, _contract_sha

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


def _sample_and_contract(*, epoch=1, sample_id='impl-py-slugify'):
    from inspect_ai.solver import TaskState

    command = 'python -m pytest tests/test_parser.py'
    task = 'Implement the requested slug normalizer'
    state = TaskState(
        model='mockllm/test', sample_id=sample_id, epoch=epoch,
        input=task, messages=[],
        metadata={
            'allowed_paths': ['src/text.py'],
            'expected_verification_commands': [command],
        },
    )
    contract = {
        'schema': 'godprompt.work_contract.v1',
        'task': task,
        'allowed_paths': ['src/text.py'],
        'verification_commands': [{'id': 'VC-01', 'command': command}],
        'forbidden_actions': ['network access'],
        'success_criteria': [{'id': 'SC-01', 'text': 'Slug normalizer works'}],
    }
    contract['contract_id'] = _contract_sha(contract)
    return state, contract


def test_experimental_sample_agent_creates_fresh_epoch_bound_sessions(monkeypatch):
    import godprompt_bench.agent as agent

    assembled = []
    def fake_agent(root, *, session, scope):
        assembled.append((root, session, scope))
        return ('agent', scope)
    monkeypatch.setattr(agent, 'experimental_contract_coding_agent', fake_agent)
    state, contract = _sample_and_contract(epoch=1)
    a1, session1 = agent.experimental_contract_sample_agent(
        REPO_ROOT, state=state, client=lambda *_: {}, contract=contract,
    )
    state2, _ = _sample_and_contract(epoch=2)
    a2, session2 = agent.experimental_contract_sample_agent(
        REPO_ROOT, state=state2, client=lambda *_: {}, contract=contract,
    )
    assert a1[0] == a2[0] == 'agent'
    assert session1 is not session2
    assert session1.execution_scope == InspectExecutionScope('impl-py-slugify', 'epoch-1-attempt-1')
    assert session2.execution_scope == InspectExecutionScope('impl-py-slugify', 'epoch-2-attempt-1')
    assert assembled[0][1] is session1 and assembled[1][1] is session2


def test_experimental_sample_agent_builds_with_installed_inspect():
    from godprompt_bench.agent import experimental_contract_sample_agent

    state, contract = _sample_and_contract()
    built, session = experimental_contract_sample_agent(
        REPO_ROOT, state=state, client=lambda *_: {}, contract=contract,
    )
    assert built is not None
    assert session.execution_scope == InspectExecutionScope('impl-py-slugify', 'epoch-1-attempt-1')


@pytest.mark.parametrize('invalid', [
    'wrong_task', 'wrong_paths', 'wrong_checks', 'wrong_digest', 'missing_metadata',
])
def test_experimental_sample_agent_rejects_unbound_contracts(invalid):
    from godprompt_bench.agent import experimental_contract_sample_agent

    state, contract = _sample_and_contract()
    if invalid == 'wrong_task':
        contract['task'] = 'Different task'
    elif invalid == 'wrong_paths':
        contract['allowed_paths'] = ['other.py']
    elif invalid == 'wrong_checks':
        contract['verification_commands'][0]['command'] = 'echo skipped'
    elif invalid == 'wrong_digest':
        contract['contract_id'] = 'sha256:' + '0' * 64
    else:
        state.metadata = None
    if invalid in ('wrong_task', 'wrong_paths', 'wrong_checks'):
        # Even a correctly re-fingerprinted contract cannot cross the sample boundary.
        contract['contract_id'] = _contract_sha({
            key: value for key, value in contract.items() if key != 'contract_id'
        })
    with pytest.raises(ContractHold):
        experimental_contract_sample_agent(
            REPO_ROOT, state=state, client=lambda *_: {}, contract=contract,
        )


@pytest.mark.parametrize('sample_id,epoch', [(12, 1), ('impl-py-slugify', 0), ('a/b', 1)])
def test_experimental_sample_agent_rejects_unusable_inspect_scope(sample_id, epoch):
    from godprompt_bench.agent import experimental_contract_sample_agent

    state, contract = _sample_and_contract(sample_id=sample_id, epoch=epoch)
    with pytest.raises(ContractHold, match='scope'):
        experimental_contract_sample_agent(
            REPO_ROOT, state=state, client=lambda *_: {}, contract=contract,
        )


def _contract_planning_client(calls, *, ambiguous=False):
    def client(name, payload):
        calls.append((name, payload))
        if name == 'classify_task':
            return {'structuredContent': {'task_type': 'BUILD', 'ambiguous': ambiguous}}
        if name == 'create_work_contract':
            contract = {
                'schema': 'godprompt.work_contract.v1',
                'task': payload['task'],
                'task_type': payload['task_type'],
                'risk_level': payload['risk_level'],
                'allowed_paths': payload['allowed_paths'],
                'forbidden_actions': payload['forbidden_actions'],
                'success_criteria': [
                    {'id': f'AC-{index:02}', 'text': text}
                    for index, text in enumerate(payload['success_criteria'], 1)
                ],
                'verification_commands': [
                    {'id': f'VC-{index:02}', 'command': command}
                    for index, command in enumerate(payload['verification_commands'], 1)
                ],
            }
            contract['contract_id'] = _contract_sha(contract)
            return {'structuredContent': {
                'definition_status': 'DEFINED', 'issues': [], 'contract': contract,
            }}
        raise AssertionError(f'unexpected MCP call: {name}')
    return client


def test_experimental_sample_preparation_uses_only_public_host_requirements(monkeypatch):
    from godprompt_bench.agent import prepare_experimental_contract_sample_agent
    import godprompt_bench.agent as agent

    state, _ = _sample_and_contract(epoch=2)
    state.metadata['hidden_verifier_secret'] = 'never forward me'
    calls = []
    monkeypatch.setattr(
        agent, 'experimental_contract_coding_agent',
        lambda root, *, session, scope: ('agent', scope),
    )
    built, session, contract = prepare_experimental_contract_sample_agent(
        REPO_ROOT, state=state, client=_contract_planning_client(calls),
        success_criteria=['Public acceptance criterion'],
        forbidden_actions=['network access'],
    )
    assert built == ('agent', InspectExecutionScope('impl-py-slugify', 'epoch-2-attempt-1'))
    assert session.contract == contract
    assert [name for name, _ in calls] == ['classify_task', 'create_work_contract']
    assert calls[1][1]['task'] == state.input
    assert calls[1][1]['allowed_paths'] == ['src/text.py']
    assert calls[1][1]['verification_commands'] == ['python -m pytest tests/test_parser.py']
    assert calls[1][1]['success_criteria'] == ['Public acceptance criterion']
    assert 'hidden_verifier_secret' not in repr(calls)


@pytest.mark.parametrize('invalid', [
    'sample_scope', 'missing_metadata', 'missing_paths', 'duplicate_commands',
    'missing_public_criteria', 'missing_forbidden_actions',
])
def test_experimental_sample_preparation_fails_before_mcp_for_invalid_host_data(invalid):
    from godprompt_bench.agent import prepare_experimental_contract_sample_agent

    state, _ = _sample_and_contract(
        sample_id='bad/sample' if invalid == 'sample_scope' else 'impl-py-slugify',
    )
    criteria = ['Public acceptance criterion']
    forbidden = ['network access']
    if invalid == 'missing_metadata':
        state.metadata = None
    elif invalid == 'missing_paths':
        state.metadata['allowed_paths'] = []
    elif invalid == 'duplicate_commands':
        state.metadata['expected_verification_commands'] *= 2
    elif invalid == 'missing_public_criteria':
        criteria = []
    elif invalid == 'missing_forbidden_actions':
        forbidden = []
    calls = []
    with pytest.raises(ContractHold):
        prepare_experimental_contract_sample_agent(
            REPO_ROOT, state=state, client=_contract_planning_client(calls),
            success_criteria=criteria, forbidden_actions=forbidden,
        )
    assert calls == []


def test_experimental_sample_preparation_builds_installed_inspect_agent_offline():
    from godprompt_bench.agent import prepare_experimental_contract_sample_agent

    state, _ = _sample_and_contract()
    calls = []
    built, session, contract = prepare_experimental_contract_sample_agent(
        REPO_ROOT, state=state, client=_contract_planning_client(calls),
        success_criteria=['Public acceptance criterion'],
        forbidden_actions=['network access'],
    )
    assert built is not None
    assert session.contract == contract
    assert session.execution_scope == InspectExecutionScope(
        'impl-py-slugify', 'epoch-1-attempt-1',
    )
    assert [name for name, _ in calls] == ['classify_task', 'create_work_contract']


def test_experimental_sample_preparation_holds_ambiguous_mcp_without_agent():
    from godprompt_bench.agent import prepare_experimental_contract_sample_agent

    state, _ = _sample_and_contract()
    calls = []
    with pytest.raises(ContractHold, match='ambiguous'):
        prepare_experimental_contract_sample_agent(
            REPO_ROOT, state=state,
            client=_contract_planning_client(calls, ambiguous=True),
            success_criteria=['Public acceptance criterion'],
            forbidden_actions=['network access'],
        )
    assert [name for name, _ in calls] == ['classify_task']


def test_experimental_contract_batch_preflights_every_sample_before_mcp():
    from godprompt_bench.agent import prepare_experimental_contract_sample_batch

    first, _ = _sample_and_contract(sample_id='fixture-001')
    duplicate, _ = _sample_and_contract(sample_id='fixture-001')
    calls = []
    samples = [
        {'state': first, 'success_criteria': ['Works'], 'forbidden_actions': ['network']},
        {'state': duplicate, 'success_criteria': ['Works'], 'forbidden_actions': ['network']},
    ]
    with pytest.raises(ContractHold, match='duplicate'):
        prepare_experimental_contract_sample_batch(
            REPO_ROOT, samples=samples, client=_contract_planning_client(calls),
        )
    assert calls == []

    valid_second, _ = _sample_and_contract(sample_id='fixture-002')
    samples[1]['state'] = valid_second
    samples[1]['success_criteria'] = []
    with pytest.raises(ContractHold, match='success criteria'):
        prepare_experimental_contract_sample_batch(
            REPO_ROOT, samples=samples, client=_contract_planning_client(calls),
        )
    assert calls == []


def test_experimental_contract_batch_isolates_per_epoch_evidence_sessions(monkeypatch):
    import godprompt_bench.agent as agent

    monkeypatch.setattr(
        agent, 'experimental_contract_coding_agent',
        lambda root, *, session, scope: ('agent', scope),
    )
    first, _ = _sample_and_contract(epoch=1)
    second, _ = _sample_and_contract(epoch=2)
    calls = []
    results = agent.prepare_experimental_contract_sample_batch(
        REPO_ROOT,
        samples=[
            {'state': first, 'success_criteria': ['First success'], 'forbidden_actions': ['network']},
            {'state': second, 'success_criteria': ['Second success'], 'forbidden_actions': ['network']},
        ],
        client=_contract_planning_client(calls),
    )
    assert set(results) == {('impl-py-slugify', 1), ('impl-py-slugify', 2)}
    _, first_session, first_contract = results[('impl-py-slugify', 1)]
    _, second_session, second_contract = results[('impl-py-slugify', 2)]
    assert first_session is not second_session
    assert first_session.execution_scope == InspectExecutionScope(
        'impl-py-slugify', 'epoch-1-attempt-1',
    )
    assert second_session.execution_scope == InspectExecutionScope(
        'impl-py-slugify', 'epoch-2-attempt-1',
    )
    assert first_contract['success_criteria'][0]['text'] == 'First success'
    assert second_contract['success_criteria'][0]['text'] == 'Second success'
    assert [name for name, _ in calls] == [
        'classify_task', 'create_work_contract', 'classify_task', 'create_work_contract',
    ]


def test_opt_in_sample_solver_is_lazy_and_registered_without_provider_calls():
    from inspect_ai._util.registry import registry_info
    from godprompt_bench.agent import experimental_contract_sample_solver

    calls = []
    prepared = []
    solver = experimental_contract_sample_solver(
        REPO_ROOT, client=_contract_planning_client(calls),
        success_criteria_by_sample={'impl-py-slugify': ['Public criterion']},
        forbidden_actions=['network access'],
        on_prepared=lambda *args: prepared.append(args),
    )
    assert callable(solver)
    assert registry_info(solver).type == 'solver'
    assert calls == [] and prepared == []


def test_opt_in_sample_solver_runs_independent_epochs_and_retains_sessions(monkeypatch):
    import inspect_ai.agent
    from godprompt_bench.agent import experimental_contract_sample_solver

    calls, prepared, executed = [], [], []
    real_as_solver = inspect_ai.agent.as_solver

    def fake_as_solver(agent):
        assert agent is not None
        assert callable(real_as_solver(agent))

        async def run(state, generate):
            executed.append((state.sample_id, state.epoch, generate))
            return state

        return run

    monkeypatch.setattr(inspect_ai.agent, 'as_solver', fake_as_solver)
    solver = experimental_contract_sample_solver(
        REPO_ROOT, client=_contract_planning_client(calls),
        success_criteria_by_sample={'impl-py-slugify': ['Public criterion']},
        forbidden_actions=['network access'],
        on_prepared=lambda *args: prepared.append(args),
    )
    marker = object()
    first, _ = _sample_and_contract(epoch=1)
    second, _ = _sample_and_contract(epoch=2)
    assert asyncio.run(solver(first, marker)) is first
    assert asyncio.run(solver(second, marker)) is second
    assert executed == [
        ('impl-py-slugify', 1, marker), ('impl-py-slugify', 2, marker),
    ]
    assert [name for name, _ in calls] == [
        'classify_task', 'create_work_contract',
        'classify_task', 'create_work_contract',
    ]
    assert [scope for scope, *_ in prepared] == [
        InspectExecutionScope('impl-py-slugify', 'epoch-1-attempt-1'),
        InspectExecutionScope('impl-py-slugify', 'epoch-2-attempt-1'),
    ]
    assert prepared[0][1] is not prepared[1][1]
    assert prepared[0][1].execution_scope != prepared[1][1].execution_scope


def test_opt_in_sample_solver_rejects_missing_criteria_before_mcp_or_model(monkeypatch):
    import inspect_ai.agent
    from godprompt_bench.agent import experimental_contract_sample_solver

    monkeypatch.setattr(inspect_ai.agent, 'as_solver',
                        lambda agent: pytest.fail('model solver must not be invoked'))
    calls, prepared = [], []
    solver = experimental_contract_sample_solver(
        REPO_ROOT, client=_contract_planning_client(calls),
        success_criteria_by_sample={'different-task': ['Wrong public criterion']},
        forbidden_actions=['network access'],
        on_prepared=lambda *args: prepared.append(args),
    )
    state, _ = _sample_and_contract()
    with pytest.raises(ContractHold, match='public success criteria'):
        asyncio.run(solver(state, object()))
    assert calls == [] and prepared == []


def test_opt_in_sample_solver_rejects_duplicate_epoch_before_mcp(monkeypatch):
    import inspect_ai.agent
    from godprompt_bench.agent import experimental_contract_sample_solver

    async def fake_run(state, generate):
        return state

    monkeypatch.setattr(inspect_ai.agent, 'as_solver', lambda agent: fake_run)
    calls, prepared = [], []
    solver = experimental_contract_sample_solver(
        REPO_ROOT, client=_contract_planning_client(calls),
        success_criteria_by_sample={'impl-py-slugify': ['Public criterion']},
        forbidden_actions=['network access'],
        on_prepared=lambda *args: prepared.append(args),
    )
    state, _ = _sample_and_contract()
    asyncio.run(solver(state, object()))
    with pytest.raises(ContractHold, match='duplicate'):
        asyncio.run(solver(state, object()))
    assert len(calls) == 2 and len(prepared) == 1


def test_opt_in_sample_solver_refuses_invalid_sink_before_any_execution():
    from godprompt_bench.agent import experimental_contract_sample_solver

    with pytest.raises(ContractHold, match='host preparation callback'):
        experimental_contract_sample_solver(
            REPO_ROOT, client=lambda *_: {},
            success_criteria_by_sample={'impl-py-slugify': ['Public criterion']},
            forbidden_actions=['network access'], on_prepared=None,
        )


def test_opt_in_sample_solver_freezes_host_public_requirements(monkeypatch):
    import inspect_ai.agent
    from godprompt_bench.agent import experimental_contract_sample_solver

    async def fake_run(state, generate):
        return state

    monkeypatch.setattr(inspect_ai.agent, 'as_solver', lambda agent: fake_run)
    calls = []
    criteria = ['Public criterion']
    forbidden = ['network access']
    solver = experimental_contract_sample_solver(
        REPO_ROOT, client=_contract_planning_client(calls),
        success_criteria_by_sample={'impl-py-slugify': criteria},
        forbidden_actions=forbidden, on_prepared=lambda *args: None,
    )
    criteria[0] = 'Changed after configuration'
    forbidden[0] = 'Changed after configuration'
    state, _ = _sample_and_contract()
    assert asyncio.run(solver(state, object())) is state
    assert calls[1][1]['success_criteria'] == ['Public criterion']
    assert calls[1][1]['forbidden_actions'] == ['network access']
