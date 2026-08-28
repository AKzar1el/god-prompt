import json
from pathlib import Path
from types import SimpleNamespace

from godprompt_bench.run import execute_benchmark, load_profile, public_trajectory, sample_record

ROOT = Path(__file__).parents[1]


def test_profiles_are_frozen_and_full_is_240_samples():
    smoke = load_profile(ROOT / 'configs' / 'smoke.json')
    full = load_profile(ROOT / 'configs' / 'full.json')
    assert len(smoke.task_ids) == 6 and smoke.epochs == 1
    assert len(full.task_ids) == 40 and full.epochs == 3
    assert len(full.task_ids) * full.epochs * 2 == 240


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


def test_public_trajectory_excludes_system_and_reasoning_content():
    messages = [
        SimpleNamespace(role='system', model_dump=lambda **kwargs: {'role': 'system', 'content': 'secret prompt'}),
        SimpleNamespace(role='user', model_dump=lambda **kwargs: {'role': 'user', 'content': 'task'}),
        SimpleNamespace(role='assistant', model_dump=lambda **kwargs: {'role': 'assistant', 'content': [
            {'type': 'reasoning', 'reasoning': 'private'}, {'type': 'text', 'text': 'public'}
        ]}),
    ]
    event = SimpleNamespace(event='tool', model_dump=lambda **kwargs: {'event': 'tool', 'function': 'bash', 'arguments': {'cmd': 'python test.py'}, 'result': 'ok'})
    sample = SimpleNamespace(id='x', epoch=1, messages=messages, events=[event])
    trajectory = public_trajectory(sample, 'baseline')
    assert [m['role'] for m in trajectory['messages']] == ['user', 'assistant']
    assert trajectory['messages'][1]['content'] == [{'type': 'text', 'text': 'public'}]
    assert trajectory['events'][0]['event'] == 'tool'


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

    result = execute_benchmark(
        ROOT.parent,
        ROOT,
        profile,
        model='mockllm/model',
        output_dir=tmp_path,
    )

    assert captured['actual_models'] == ['mockllm/model', 'mockllm/model']
    assert result == tmp_path / 'test-run'
