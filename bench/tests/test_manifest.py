from collections import Counter
from pathlib import Path

import pytest

from godprompt_bench.corpus import load_manifest, validate_manifest

ROOT = Path(__file__).parents[1]


def test_manifest_has_exact_v1_distribution():
    tasks = load_manifest(ROOT / 'tasks' / 'manifest.json')
    validate_manifest(tasks)
    assert len(tasks) == 40
    assert Counter(t.category for t in tasks) == {
        'implementation': 8,
        'debugging': 8,
        'refactor': 6,
        'scope-control': 6,
        'verification': 6,
        'tool-discipline': 6,
    }
    assert len({t.id for t in tasks}) == 40


def test_every_task_declares_fixture_and_verifier():
    tasks = load_manifest(ROOT / 'tasks' / 'manifest.json')
    for task in tasks:
        assert task.runtime in {'python', 'javascript'}
        assert task.fixture_dir
        assert task.user_prompt.strip()
        assert task.verifier_command
        assert task.allowed_paths


def test_manifest_rejects_duplicate_ids(tmp_path: Path):
    manifest = tmp_path / 'manifest.json'
    manifest.write_text(
        '[{"id":"x","category":"implementation","runtime":"python","fixture_dir":"tasks/x","user_prompt":"abc","verifier_command":["python","-V"],"allowed_paths":["src/a.py"]},'
        '{"id":"x","category":"implementation","runtime":"python","fixture_dir":"tasks/y","user_prompt":"abc","verifier_command":["python","-V"],"allowed_paths":["src/b.py"]}]',
        encoding='utf-8',
    )
    tasks = load_manifest(manifest)
    with pytest.raises(ValueError, match='duplicate task id'):
        validate_manifest(tasks)


def test_all_fixture_directories_exist_and_are_safe():
    tasks = load_manifest(ROOT / 'tasks' / 'manifest.json')
    for task in tasks:
        fixture = ROOT / task.fixture_dir
        assert fixture.is_dir(), task.id
        assert (fixture / 'fixture.json').is_file(), task.id
        assert not any(p.name in {'.env', 'credentials.json'} for p in fixture.rglob('*'))
        assert all(not p.is_symlink() for p in fixture.rglob('*'))


def test_every_fixture_declares_hidden_verifier_and_expected_starter_state():
    import json
    tasks = load_manifest(ROOT / 'tasks' / 'manifest.json')
    for task in tasks:
        payload = json.loads((ROOT / task.fixture_dir / 'fixture.json').read_text(encoding='utf-8'))
        assert isinstance(payload.get('files'), dict) and payload['files'], task.id
        assert isinstance(payload.get('hidden_verifier'), str) and payload['hidden_verifier'].strip(), task.id
        assert isinstance(payload.get('starter_expected_pass'), bool), task.id
