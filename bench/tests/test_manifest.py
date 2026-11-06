import json
from collections import Counter
from dataclasses import replace
from pathlib import Path

import pytest

from godprompt_bench.corpus import load_fixture_bundle, load_manifest, validate_manifest

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


@pytest.mark.parametrize('field,invalid', [
    ('id', 123), ('category', ['implementation']), ('runtime', True),
    ('fixture_dir', 42), ('user_prompt', {'text': 'run'}),
])
def test_manifest_rejects_non_string_required_scalars(tmp_path: Path, field: str, invalid: object):
    source = json.loads((ROOT / 'tasks' / 'manifest.json').read_text(encoding='utf-8'))[0]
    source[field] = invalid
    manifest = tmp_path / 'manifest.json'
    manifest.write_text(json.dumps([source]), encoding='utf-8')
    with pytest.raises(ValueError, match=f'{field} must be a string'):
        load_manifest(manifest)


@pytest.mark.parametrize('original,typo', [
    ('forbidden_paths', 'forbiden_paths'),
    ('expected_verification_commands', 'expected_verfication_commands'),
])
def test_manifest_rejects_misspelled_optional_security_fields(tmp_path: Path, original: str, typo: str):
    source = json.loads((ROOT / 'tasks' / 'manifest.json').read_text(encoding='utf-8'))[0]
    source[typo] = source.pop(original)
    manifest = tmp_path / 'manifest.json'
    manifest.write_text(json.dumps([source]), encoding='utf-8')
    with pytest.raises(ValueError, match='unknown fields'):
        load_manifest(manifest)


@pytest.mark.parametrize('payload', ([], None, 42, 'invalid'))
def test_fixture_bundle_rejects_non_object_root(tmp_path: Path, payload: object):
    fixture = tmp_path / 'fixture.json'
    fixture.write_text(json.dumps(payload), encoding='utf-8')
    with pytest.raises(ValueError, match='fixture root must be an object'):
        load_fixture_bundle(fixture)


def test_fixture_bundle_rejects_unknown_fields(tmp_path: Path):
    fixture = tmp_path / 'fixture.json'
    fixture.write_text(json.dumps({
        'files': {'src/main.py': 'print("ok")'},
        'hidden_verifier': 'print("safe")',
        'starter_expected_pass': False,
        'starter_expeced_pass': True,
    }), encoding='utf-8')
    with pytest.raises(ValueError, match='fixture unknown fields:'):
        load_fixture_bundle(fixture)


@pytest.mark.parametrize('unsafe', [
    r'..\outside', r'C:\private\fixture', r'C:relative', r'\rooted',
    r'tasks\..\private', '../outside', '/absolute', '.', '',
])
def test_manifest_and_fixture_reject_nonportable_or_escaping_paths(tmp_path: Path, unsafe: str):
    task = load_manifest(ROOT / 'tasks' / 'manifest.json')[0]
    for altered in (
        replace(task, fixture_dir=unsafe),
        replace(task, allowed_paths=(unsafe,)),
        replace(task, forbidden_paths=(unsafe,)),
    ):
        with pytest.raises(ValueError, match='safe relative path'):
            validate_manifest([altered])

    fixture = tmp_path / 'fixture.json'
    fixture.write_text(json.dumps({
        'files': {unsafe: 'content'},
        'hidden_verifier': 'print("safe")',
        'starter_expected_pass': False,
    }), encoding='utf-8')
    with pytest.raises(ValueError, match='safe relative path'):
        load_fixture_bundle(fixture)


@pytest.mark.parametrize('alias', ('src/./a.py', 'src//a.py', './src/a.py'))
def test_fixture_rejects_paths_that_alias_after_normalization(tmp_path: Path, alias: str):
    fixture = tmp_path / 'fixture.json'
    fixture.write_text(json.dumps({
        'files': {'src/a.py': 'first', alias: 'overwrites the same file'},
        'hidden_verifier': 'print("safe")',
        'starter_expected_pass': False,
    }), encoding='utf-8')
    with pytest.raises(ValueError, match='safe relative path'):
        load_fixture_bundle(fixture)


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
