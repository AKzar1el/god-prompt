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
