import json
from pathlib import Path

from godprompt_bench.export import export_run
from godprompt_bench.models import SampleRecord
from godprompt_bench.run import load_profile

ROOT = Path(__file__).parents[1]


def test_offline_smoke_profile_exports_six_samples_per_condition(tmp_path: Path):
    profile = load_profile(ROOT / 'configs' / 'smoke.json')
    records = []
    trajectories = []
    for condition in ('baseline', 'godprompt'):
        for task_id in profile.task_ids:
            records.append(SampleRecord(
                task_id=task_id, category='synthetic', condition=condition, epoch=1,
                passed=True, completion_status='complete', false_completion=False,
                scope_violation=False, tool_misuse_count=0, verification_attempts=1,
                failed_tool_calls=0, retries=0, input_tokens=1, output_tokens=1,
                latency_seconds=0.1, infrastructure_error=None,
            ))
            trajectories.append({'task_id': task_id, 'condition': condition, 'messages': [], 'events': []})
    export_run(tmp_path, {'run_id': 'offline-smoke'}, records, trajectories)
    summary = json.loads((tmp_path / 'summary.json').read_text())
    assert summary['baseline']['samples'] == 6
    assert summary['godprompt']['samples'] == 6
    assert len((tmp_path / 'trajectories.jsonl').read_text().splitlines()) == 12
