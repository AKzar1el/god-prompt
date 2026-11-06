import json
from pathlib import Path

import pytest

from godprompt_bench.eval import build_sample_payloads

ROOT = Path(__file__).parents[1]


def test_sample_payloads_materialize_visible_files_and_hashes_only():
    samples = build_sample_payloads(ROOT, ['impl-py-slugify'])
    assert len(samples) == 1
    sample = samples[0]
    assert sample['id'] == 'impl-py-slugify'
    assert 'src/text.py' in sample['files']
    assert '.godprompt_verifier.py' not in sample['files']
    assert sample['metadata']['category'] == 'implementation'
    assert sample['metadata']['baseline_hashes']
    assert 'hidden_verifier' not in sample['metadata']


def test_sample_payloads_reject_unknown_task_ids():
    with pytest.raises(ValueError, match='unknown task id'):
        build_sample_payloads(ROOT, ['missing-task'])


def test_sample_payloads_reject_duplicate_ids_from_direct_call():
    with pytest.raises(ValueError, match='duplicate task id.*impl-py-slugify'):
        build_sample_payloads(ROOT, ['impl-py-slugify', 'impl-py-slugify'])


def test_sample_payloads_reject_symlinked_fixture_outside_benchmark_root(tmp_path: Path):
    bench = tmp_path / 'bench'
    (bench / 'tasks').mkdir(parents=True)
    outside = tmp_path / 'outside'
    outside.mkdir()
    (outside / 'fixture.json').write_text(json.dumps({
        'files': {'src/marker.py': 'SYNTHETIC_EXTERNAL_FIXTURE'},
        'hidden_verifier': 'print(1)',
        'starter_expected_pass': False,
    }), encoding='utf-8')
    try:
        (bench / 'tasks' / 'linked').symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip('directory symlinks not supported by this runner')
    manifest = [{
        'id': 'sample', 'category': 'implementation', 'runtime': 'python',
        'fixture_dir': 'tasks/linked', 'user_prompt': 'synthetic task',
        'verifier_command': ['python', '-V'], 'allowed_paths': ['src/marker.py'],
    }]
    (bench / 'tasks' / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    with pytest.raises(ValueError, match='fixture file outside benchmark root'):
        build_sample_payloads(bench, ['sample'])
