import csv
import json
from pathlib import Path

from godprompt_bench.export import export_run
from godprompt_bench.models import SampleRecord


def record():
    return SampleRecord(
        task_id='impl-py-slugify', category='implementation', condition='baseline', epoch=1,
        passed=True, completion_status='complete', false_completion=False, scope_violation=False,
        tool_misuse_count=0, verification_attempts=1, failed_tool_calls=0, retries=0,
        input_tokens=10, output_tokens=5, latency_seconds=1.25, infrastructure_error=None,
    )


def test_export_writes_exact_public_artifact_set_and_redacts_secrets(tmp_path: Path):
    export_run(
        tmp_path,
        {'run_id': 'r1', 'api_key': 'secret-value', 'nested': {'Authorization': 'Bearer nope'}},
        [record()],
        [{'task_id': 'impl-py-slugify', 'events': [{'tool': 'bash', 'access_token': 'nope'}]}],
    )
    assert {p.name for p in tmp_path.iterdir()} == {
        'manifest.json', 'summary.json', 'scores.csv', 'trajectories.jsonl'
    }
    manifest = json.loads((tmp_path / 'manifest.json').read_text())
    assert manifest['api_key'] == '[REDACTED]'
    assert manifest['nested']['Authorization'] == '[REDACTED]'
    trajectory = json.loads((tmp_path / 'trajectories.jsonl').read_text().strip())
    assert trajectory['events'][0]['access_token'] == '[REDACTED]'
    rows = list(csv.DictReader((tmp_path / 'scores.csv').open(newline='', encoding='utf-8')))
    assert rows[0]['task_id'] == 'impl-py-slugify'
    summary = json.loads((tmp_path / 'summary.json').read_text())
    assert summary['baseline']['passed'] == 1


def test_export_overwrites_only_known_files_not_arbitrary_output(tmp_path: Path):
    marker = tmp_path / 'keep.txt'
    marker.write_text('keep')
    export_run(tmp_path, {'run_id': 'r1'}, [record()], [])
    assert marker.read_text() == 'keep'
