from godprompt_bench.aggregate import aggregate
from godprompt_bench.models import SampleRecord


def rec(condition, passed, *, category='implementation', false=False, infra=None, latency=1.0):
    return SampleRecord(
        task_id=f'{condition}-{passed}-{false}-{infra}', category=category, condition=condition, epoch=1,
        passed=passed, completion_status='complete', false_completion=false, scope_violation=False,
        tool_misuse_count=0, verification_attempts=1, failed_tool_calls=0, retries=0,
        input_tokens=10, output_tokens=5, latency_seconds=latency, infrastructure_error=infra,
    )


def test_aggregate_reports_raw_counts_rates_and_categories():
    records = [
        rec('baseline', True, latency=1.0),
        rec('baseline', False, false=True, latency=3.0),
        rec('godprompt', True, category='debugging', latency=2.0),
        rec('godprompt', False, category='debugging', infra='sandbox failed', latency=None),
    ]
    summary = aggregate(records)
    assert summary['baseline']['samples'] == 2
    assert summary['baseline']['model_samples'] == 2
    assert summary['baseline']['passed'] == 1
    assert summary['baseline']['pass_rate'] == 0.5
    assert summary['baseline']['false_completions'] == 1
    assert summary['baseline']['median_latency_seconds'] == 2.0
    assert summary['godprompt']['samples'] == 2
    assert summary['godprompt']['model_samples'] == 1
    assert summary['godprompt']['infrastructure_failures'] == 1
    assert summary['godprompt']['pass_rate'] == 1.0
    assert summary['by_category']['debugging']['godprompt']['samples'] == 2


def test_aggregate_never_emits_weighted_composite_score():
    summary = aggregate([rec('baseline', True), rec('godprompt', True)])
    assert 'score' not in summary
    assert 'composite' not in summary
