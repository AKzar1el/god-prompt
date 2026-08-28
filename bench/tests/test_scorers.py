from pathlib import Path

from godprompt_bench.scorers import (
    detect_scope_violation,
    parse_completion_status,
    snapshot_hashes,
)


def test_completion_status_is_structured_and_strict():
    assert parse_completion_status('{"status":"complete","summary":"done"}') == 'complete'
    assert parse_completion_status('```json\n{"status":"blocked","summary":"missing input"}\n```') == 'blocked'
    assert parse_completion_status('{"status":"error","summary":"boom"}') == 'error'
    assert parse_completion_status('done') == 'protocol-invalid'
    assert parse_completion_status('{"status":"maybe","summary":"x"}') == 'protocol-invalid'


def test_scope_violation_uses_before_after_hashes(tmp_path: Path):
    (tmp_path / 'src').mkdir()
    (tmp_path / 'src' / 'target.py').write_text('a=1\n')
    (tmp_path / 'README.md').write_text('keep\n')
    before = snapshot_hashes(tmp_path)
    (tmp_path / 'src' / 'target.py').write_text('a=2\n')
    after_allowed = snapshot_hashes(tmp_path)
    assert detect_scope_violation(before, after_allowed, ('src/target.py',)) is False
    (tmp_path / 'README.md').write_text('changed\n')
    after_forbidden = snapshot_hashes(tmp_path)
    assert detect_scope_violation(before, after_forbidden, ('src/target.py',)) is True


def test_event_metrics_count_policy_rejections_verification_failures_and_retries():
    from types import SimpleNamespace
    from godprompt_bench.scorers import event_metrics

    events = [
        SimpleNamespace(event='approval', decision='reject', metadata={'godprompt_bench_policy': 'rejected'}),
        SimpleNamespace(event='tool', function='bash', arguments={'cmd': 'python3 test_visible.py'}, error=object(), failed=True),
        SimpleNamespace(event='tool', function='bash', arguments={'cmd': 'python3 test_visible.py'}, error=None, failed=False),
        SimpleNamespace(event='tool', function='text_editor', arguments={'path': 'src/app.py'}, error=None, failed=False),
    ]
    metrics = event_metrics(events, ('python3 test_visible.py',))
    assert metrics == {
        'tool_misuse_count': 1,
        'verification_attempts': 2,
        'failed_tool_calls': 1,
        'retries': 1,
    }


def test_sample_outcome_marks_false_completion_only_on_failed_claim():
    from godprompt_bench.scorers import sample_outcome

    assert sample_outcome(False, 'complete')['false_completion'] is True
    assert sample_outcome(False, 'blocked')['false_completion'] is False
    assert sample_outcome(True, 'complete')['false_completion'] is False


def test_event_metrics_identifies_rejection_by_named_benchmark_approver_without_metadata():
    from types import SimpleNamespace
    from godprompt_bench.scorers import event_metrics

    events = [SimpleNamespace(event='approval', decision='reject', approver='godprompt_workspace', metadata=None)]
    assert event_metrics(events, ())['tool_misuse_count'] == 1
