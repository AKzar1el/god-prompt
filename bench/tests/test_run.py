import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from godprompt_bench.run import execute_benchmark, load_profile, public_trajectory, sample_record, validate_sample_coverage, fixture_fingerprints, condition_batches, build_manifest
from godprompt_bench.models import RunProfile

ROOT = Path(__file__).parents[1]


def test_run_manifest_fingerprints_actual_compose_isolation_configuration():
    profile = load_profile(ROOT / 'configs' / 'smoke.json')
    manifest = build_manifest(
        ROOT.parent, ROOT, profile,
        requested_model='mockllm/model', actual_models=['mockllm/model'],
        temperature=None, seed=7, reasoning_effort=None, reasoning_mode=None,
        records=[], benchmark_commit_sha='benchmark-sha',
        godprompt_commit_sha='prompt-sha', working_tree_dirty=False,
    )
    config = ROOT / 'sandbox' / 'compose.yaml'
    assert manifest['sandbox_compose_sha256'] == hashlib.sha256(config.read_bytes()).hexdigest()
    assert manifest['sandbox_compose_sha256'] != manifest['sandbox_dockerfile_sha256']


def test_condition_batches_counterbalance_order_without_additional_samples():
    task_ids = tuple(f'task-{i}' for i in range(6))
    batches = condition_batches(task_ids)
    assert batches == [
        ('baseline', ('task-0', 'task-2', 'task-4')),
        ('godprompt', ('task-0', 'task-2', 'task-4')),
        ('godprompt', ('task-1', 'task-3', 'task-5')),
        ('baseline', ('task-1', 'task-3', 'task-5')),
    ]
    assert condition_batches(task_ids) == batches
    for condition in ('baseline', 'godprompt'):
        assert sorted(task for label, group in batches if label == condition for task in group) == sorted(task_ids)
    assert condition_batches(('solo',)) == [('baseline', ('solo',)), ('godprompt', ('solo',))]


def test_fixture_fingerprints_cover_selected_bundles_and_hidden_verifiers(tmp_path: Path):
    tasks = tmp_path / 'tasks'
    tasks.mkdir()
    manifest = [
        {'id': 'task-b', 'fixture_dir': 'tasks/b'},
        {'id': 'task-a', 'fixture_dir': 'tasks/a'},
    ]
    (tasks / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    for name in ('a', 'b'):
        directory = tasks / name
        directory.mkdir()
        (directory / 'fixture.json').write_text(json.dumps({'hidden_verifier': f'check {name}', 'files': {'x': '1'}}), encoding='utf-8')

    first = fixture_fingerprints(tmp_path, ('task-a', 'task-b'))
    reverse = fixture_fingerprints(tmp_path, ('task-b', 'task-a'))
    assert first == reverse
    assert set(first['fixture_bundle_sha256']) == {'task-a', 'task-b'}
    assert all(len(value) == 64 for value in first['fixture_bundle_sha256'].values())
    assert len(first['fixture_bundles_sha256']) == 64
    assert 'check a' not in repr(first)

    (tasks / 'a' / 'fixture.json').write_text(json.dumps({'hidden_verifier': 'changed secret verifier', 'files': {'x': '1'}}), encoding='utf-8')
    changed = fixture_fingerprints(tmp_path, ('task-a', 'task-b'))
    assert changed['fixture_bundle_sha256']['task-a'] != first['fixture_bundle_sha256']['task-a']
    assert changed['fixture_bundle_sha256']['task-b'] == first['fixture_bundle_sha256']['task-b']
    assert changed['fixture_bundles_sha256'] != first['fixture_bundles_sha256']

    with pytest.raises(ValueError, match='missing fixture'):
        fixture_fingerprints(tmp_path, ('task-unknown',))


def test_sample_coverage_rejects_missing_duplicate_and_extra_samples():
    profile = RunProfile(name='tiny', task_ids=('task-a', 'task-b'), epochs=2,
                         max_messages=10, max_time_seconds=30, max_output_tokens=1000)
    expected = [(condition, task_id, epoch)
                for condition in ('baseline', 'godprompt')
                for task_id in profile.task_ids for epoch in (1, 2)]
    records = [SimpleNamespace(condition=c, task_id=t, epoch=e) for c, t, e in expected]
    validate_sample_coverage(profile, records)

    with pytest.raises(ValueError, match='missing.*godprompt.*task-b'):
        validate_sample_coverage(profile, records[:-1])
    with pytest.raises(ValueError, match='duplicate.*baseline.*task-a'):
        validate_sample_coverage(profile, records + [records[0]])
    with pytest.raises(ValueError, match='unexpected.*baseline.*task-a'):
        validate_sample_coverage(profile, records + [SimpleNamespace(condition='baseline', task_id='task-a', epoch=3)])


def test_execute_benchmark_rejects_incomplete_samples_before_export(monkeypatch, tmp_path):
    import inspect_ai
    import godprompt_bench.run as run_module

    profile = load_profile(ROOT / 'configs' / 'smoke.json')
    logs = [SimpleNamespace(metadata={'condition': condition}, eval=SimpleNamespace(model='mockllm/model'), samples=[])
            for condition in ('baseline', 'godprompt')]
    monkeypatch.setattr(run_module, 'build_task', lambda *args, **kwargs: object())
    monkeypatch.setattr(inspect_ai, 'eval', lambda *args, **kwargs: logs)
    monkeypatch.setattr(run_module, 'export_run', lambda *args, **kwargs: pytest.fail('must not publish incomplete benchmark'))
    with pytest.raises(ValueError, match='missing'):
        execute_benchmark(ROOT.parent, ROOT, profile, model='mockllm/model', output_dir=tmp_path)


def test_profiles_are_frozen_and_full_is_240_samples():
    smoke = load_profile(ROOT / 'configs' / 'smoke.json')
    full = load_profile(ROOT / 'configs' / 'full.json')
    assert len(smoke.task_ids) == 6 and smoke.epochs == 1
    assert len(full.task_ids) == 40 and full.epochs == 3
    assert len(full.task_ids) * full.epochs * 2 == 240


def test_profile_rejects_duplicate_ids_before_any_evaluation(tmp_path: Path):
    profile = json.loads((ROOT / 'configs' / 'smoke.json').read_text(encoding='utf-8'))
    profile['task_ids'].append(profile['task_ids'][0])
    path = tmp_path / 'duplicate.json'
    path.write_text(json.dumps(profile), encoding='utf-8')
    with pytest.raises(ValueError, match='duplicate task id.*impl-py-slugify'):
        load_profile(path)


@pytest.mark.parametrize('invalid_root', ([], None, 'smoke', 42))
def test_profile_rejects_nonobject_root_with_actionable_error(tmp_path: Path, invalid_root):
    path = tmp_path / 'malformed.json'
    path.write_text(json.dumps(invalid_root), encoding='utf-8')
    with pytest.raises(ValueError, match='profile root must be an object'):
        load_profile(path)


@pytest.mark.parametrize('invalid_id', ('', '  \t'))
def test_profile_rejects_blank_task_ids_before_evaluation(tmp_path: Path, invalid_id):
    profile = json.loads((ROOT / 'configs' / 'smoke.json').read_text(encoding='utf-8'))
    profile['task_ids'][0] = invalid_id
    path = tmp_path / 'blank-id.json'
    path.write_text(json.dumps(profile), encoding='utf-8')
    with pytest.raises(ValueError, match='profile task_ids must be non-empty strings'):
        load_profile(path)


def test_profile_rejects_unknown_resource_limit_fields(tmp_path: Path):
    # A misspelled budget key must not silently leave the default cap in effect.
    profile = json.loads((ROOT / 'configs' / 'smoke.json').read_text(encoding='utf-8'))
    profile['max_output_token'] = 100
    path = tmp_path / 'misspelled-budget.json'
    path.write_text(json.dumps(profile), encoding='utf-8')
    with pytest.raises(ValueError, match='unknown profile fields.*max_output_token'):
        load_profile(path)


@pytest.mark.parametrize('invalid_name', (None, 12, {}, [], '', '  \t '))
def test_profile_requires_nonempty_string_name(tmp_path: Path, invalid_name):
    # Do not mislabel exported benchmark results using str(None) or repr(dict).
    profile = json.loads((ROOT / 'configs' / 'smoke.json').read_text(encoding='utf-8'))
    profile['name'] = invalid_name
    path = tmp_path / 'invalid-name.json'
    path.write_text(json.dumps(profile), encoding='utf-8')
    with pytest.raises(ValueError, match='profile name must be a non-empty string'):
        load_profile(path)


@pytest.mark.parametrize(('field', 'invalid'), (
    ('epochs', True),
    ('epochs', 1.5),
    ('max_messages', '10'),
    ('max_time_seconds', False),
    ('max_output_tokens', 0),
))
def test_profile_rejects_non_integer_or_nonpositive_budgets(tmp_path: Path, field, invalid):
    # Reject silently coerced configuration before running any paid evaluations.
    profile = json.loads((ROOT / 'configs' / 'smoke.json').read_text(encoding='utf-8'))
    profile[field] = invalid
    path = tmp_path / 'invalid-budget.json'
    path.write_text(json.dumps(profile), encoding='utf-8')
    with pytest.raises(ValueError, match='profile numeric limits must be positive integers'):
        load_profile(path)


def test_sample_record_uses_score_and_sums_provider_usage():
    score = SimpleNamespace(
        value={'passed': 1, 'false_completion': 0, 'scope_violation': 0, 'tool_misuse_count': 1, 'verification_attempts': 2, 'failed_tool_calls': 1, 'retries': 1},
        metadata={'completion_status': 'complete'},
    )
    usage = SimpleNamespace(input_tokens=10, input_tokens_cache_read=3, input_tokens_cache_write=2, output_tokens=7)
    sample = SimpleNamespace(
        id='x', epoch=2, metadata={'category': 'debugging'}, scores={'godprompt_bench': score},
        model_usage={'m': usage}, total_time=1.5, error=None, limit=None,
    )
    record = sample_record(sample, 'godprompt')
    assert record.input_tokens == 15
    assert record.output_tokens == 7
    assert record.tool_misuse_count == 1
    assert record.infrastructure_error is None


@pytest.mark.parametrize('latency', [
    '1.5', True, -1.0, float('nan'), float('inf'), 10 ** 400,
])
def test_sample_record_rejects_invalid_latency_telemetry(latency):
    sample = SimpleNamespace(
        id='synthetic', epoch=1, metadata={}, scores={}, model_usage={},
        total_time=latency, error=None, limit=None,
    )
    with pytest.raises(ValueError, match='invalid sample latency'):
        sample_record(sample, 'baseline')


def test_sample_record_accepts_missing_and_zero_latency():
    sample = SimpleNamespace(
        id='synthetic', epoch=1, metadata={}, scores={}, model_usage={},
        total_time=None, error=None, limit=None,
    )
    assert sample_record(sample, 'baseline').latency_seconds is None
    sample.total_time = 0
    assert sample_record(sample, 'baseline').latency_seconds == 0.0


@pytest.mark.parametrize('field,value', [
    ('input_tokens', -3),
    ('input_tokens', True),
    ('input_tokens_cache_read', '7'),
    ('input_tokens_cache_write', 2.5),
    ('output_tokens', float('nan')),
    ('output_tokens', float('inf')),
])
def test_usage_totals_rejects_invalid_token_telemetry(field, value):
    from godprompt_bench.run import _usage_totals

    usage = SimpleNamespace(
        input_tokens=10, input_tokens_cache_read=2, input_tokens_cache_write=1,
        output_tokens=5,
    )
    setattr(usage, field, value)
    with pytest.raises(ValueError, match='invalid model usage token count'):
        _usage_totals({'synthetic-model': usage})


def test_usage_totals_accepts_integral_floats_and_missing_optional_counts():
    from godprompt_bench.run import _usage_totals

    usage = SimpleNamespace(input_tokens=5.0, input_tokens_cache_read=None, output_tokens=3.0)
    assert _usage_totals({'synthetic-model': usage}) == (5, 3)


def test_public_trajectory_excludes_system_and_reasoning_content():
    messages = [
        SimpleNamespace(role='system', model_dump=lambda **kwargs: {'role': 'system', 'content': 'secret prompt'}),
        SimpleNamespace(role='user', model_dump=lambda **kwargs: {'role': 'user', 'content': 'task'}),
        SimpleNamespace(role='assistant', model_dump=lambda **kwargs: {'role': 'assistant', 'content': [
            {'type': 'reasoning', 'reasoning': 'private'},
            {'type': 'thinking', 'thinking': 'synthetic private thought'},
            {'type': 'redacted_thinking', 'data': 'synthetic opaque block'},
            {'type': 'text', 'text': 'public', 'thinking': 'synthetic private field'},
        ]}),
    ]
    event = SimpleNamespace(event='tool', model_dump=lambda **kwargs: {'event': 'tool', 'function': 'bash', 'arguments': {'cmd': 'python test.py'}, 'result': 'ok'})
    sample = SimpleNamespace(id='x', epoch=1, messages=messages, events=[event])
    trajectory = public_trajectory(sample, 'baseline')
    assert [m['role'] for m in trajectory['messages']] == ['user', 'assistant']
    assert trajectory['messages'][1]['content'] == [{'type': 'text', 'text': 'public'}]
    assert trajectory['events'][0]['event'] == 'tool'


def test_public_trajectory_filters_privileged_mapping_messages_and_keeps_mapping_events():
    sample = SimpleNamespace(
        id='fixture', epoch=1,
        messages=[
            {'role': 'system', 'content': 'SYNTHETIC_SYSTEM_PRIVATE'},
            {'role': 'developer', 'content': 'SYNTHETIC_DEVELOPER_PRIVATE'},
            SimpleNamespace(role='developer', model_dump=lambda **kwargs: {
                'role': 'developer', 'content': 'SYNTHETIC_OBJECT_PRIVATE',
            }),
            {'role': 'user', 'content': 'public task'},
        ],
        events=[
            {'event': 'tool', 'function': 'bash', 'arguments': {'cmd': 'echo harmless'}},
            {'event': 'approval', 'decision': 'approve'},
            {'event': 'message', 'content': 'not a tool event'},
        ],
    )
    trajectory = public_trajectory(sample, 'baseline')
    assert trajectory['messages'] == [{'role': 'user', 'content': 'public task'}]
    assert [event['event'] for event in trajectory['events']] == ['tool', 'approval']
    assert 'PRIVATE' not in json.dumps(trajectory)


def test_public_trajectory_fails_closed_on_conflicting_or_unknown_message_roles():
    sample = SimpleNamespace(
        id='fixture', epoch=1,
        messages=[
            {'role': 'SYSTEM', 'content': 'SYNTHETIC_UPPERCASE_PRIVATE'},
            {'role': 'admin', 'content': 'SYNTHETIC_UNKNOWN_PRIVATE'},
            SimpleNamespace(role='developer', model_dump=lambda **kwargs: {
                'role': 'user', 'content': 'SYNTHETIC_DISGUISED_PRIVATE',
            }),
            SimpleNamespace(role='system', model_dump=lambda **kwargs: {
                'role': None, 'content': 'SYNTHETIC_NULL_PRIVATE',
            }),
            {'role': 'user', 'content': 'public task'},
            {'role': 'assistant', 'content': 'public answer'},
            {'role': 'tool', 'content': 'public tool response'},
        ],
        events=[],
    )
    trajectory = public_trajectory(sample, 'baseline')
    assert [message['role'] for message in trajectory['messages']] == ['user', 'assistant', 'tool']
    assert 'PRIVATE' not in json.dumps(trajectory)


def test_execute_benchmark_reads_actual_model_from_eval_spec(monkeypatch, tmp_path):
    import inspect_ai
    import godprompt_bench.run as run_module

    profile = load_profile(ROOT / 'configs' / 'smoke.json')
    logs = [
        SimpleNamespace(metadata={'condition': 'baseline'}, eval=SimpleNamespace(model='mockllm/model'), samples=[]),
        SimpleNamespace(metadata={'condition': 'godprompt'}, eval=SimpleNamespace(model='mockllm/model'), samples=[]),
    ]
    captured = {}

    monkeypatch.setattr(run_module, 'build_task', lambda *args, **kwargs: object())
    monkeypatch.setattr(inspect_ai, 'eval', lambda *args, **kwargs: logs)

    def fake_manifest(*args, actual_models, **kwargs):
        captured['actual_models'] = actual_models
        return {'run_id': 'test-run'}

    monkeypatch.setattr(run_module, 'build_manifest', fake_manifest)
    monkeypatch.setattr(run_module, 'export_run', lambda *args, **kwargs: None)
    monkeypatch.setattr(run_module, 'validate_sample_coverage', lambda *args: None)

    result = execute_benchmark(
        ROOT.parent,
        ROOT,
        profile,
        model='mockllm/model',
        output_dir=tmp_path,
    )

    assert captured['actual_models'] == ['mockllm/model', 'mockllm/model']
    assert result == tmp_path / 'test-run'


def test_execute_benchmark_captures_git_state_before_eval(monkeypatch, tmp_path):
    import inspect_ai
    import godprompt_bench.run as run_module

    profile = load_profile(ROOT / 'configs' / 'smoke.json')
    logs = [
        SimpleNamespace(metadata={'condition': 'baseline'}, eval=SimpleNamespace(model='mockllm/model'), samples=[]),
        SimpleNamespace(metadata={'condition': 'godprompt'}, eval=SimpleNamespace(model='mockllm/model'), samples=[]),
    ]
    events = []

    monkeypatch.setattr(run_module, 'build_task', lambda *args, **kwargs: object())

    def fake_git(repo_root, *args):
        events.append(('git', args))
        if args[0] == 'status':
            return ''
        return 'abc123'

    def fake_eval(*args, **kwargs):
        events.append(('eval', ()))
        return logs

    monkeypatch.setattr(run_module, '_git', fake_git)
    monkeypatch.setattr(inspect_ai, 'eval', fake_eval)
    monkeypatch.setattr(run_module, 'export_run', lambda *args, **kwargs: None)
    monkeypatch.setattr(run_module, 'validate_sample_coverage', lambda *args: None)

    execute_benchmark(
        ROOT.parent,
        ROOT,
        profile,
        model='mockllm/model',
        output_dir=tmp_path,
    )

    assert events[0][0] == 'git'
    assert next(i for i, event in enumerate(events) if event[0] == 'git') < next(
        i for i, event in enumerate(events) if event[0] == 'eval'
    )
