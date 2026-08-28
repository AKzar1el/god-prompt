import json
import os
import subprocess
import sys
from pathlib import Path

from godprompt_bench.corpus import load_manifest

ROOT = Path(__file__).parents[1]


def materialize(tmp_path: Path, payload: dict) -> None:
    for relative, content in payload['files'].items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')
    (tmp_path / '.godprompt_verifier.py').write_text(payload['hidden_verifier'], encoding='utf-8')


def test_all_hidden_verifiers_execute_and_match_declared_starter_state(tmp_path: Path):
    tasks = load_manifest(ROOT / 'tasks' / 'manifest.json')
    for task in tasks:
        payload = json.loads((ROOT / task.fixture_dir / 'fixture.json').read_text(encoding='utf-8'))
        workspace = tmp_path / task.id
        workspace.mkdir()
        materialize(workspace, payload)
        result = subprocess.run(
            [sys.executable, '.godprompt_verifier.py'],
            cwd=workspace,
            text=True,
            capture_output=True,
            env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'},
            timeout=10,
        )
        actual = result.returncode == 0
        assert actual is payload['starter_expected_pass'], (
            task.id,
            result.stdout,
            result.stderr,
        )
