from dataclasses import replace
import json
import pytest

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


@pytest.mark.parametrize('condition', ['godpromt', '', 'baseline ', None, 123])
def test_aggregate_rejects_unknown_conditions_instead_of_dropping_samples(condition):
    records = [rec('baseline', True), rec(condition, True)]
    with pytest.raises(ValueError, match='unknown benchmark condition'):
        aggregate(records)


def test_scope_violations_never_count_as_passes_even_in_previous_score_records():
    unsafe = replace(rec('baseline', True), scope_violation=True)
    safe = rec('baseline', True)
    summary = aggregate([unsafe, safe])
    assert summary['baseline']['model_samples'] == 2
    assert summary['baseline']['passed'] == 1
    assert summary['baseline']['pass_rate'] == 0.5
    assert summary['baseline']['scope_violations'] == 1
    assert summary['by_category']['implementation']['baseline']['passed'] == 1


def test_legacy_scope_violations_also_count_as_false_completion_claims():
    # Historic records can have a stale passed=True / false_completion=False pair.
    unsafe_claim = replace(rec('baseline', True), scope_violation=True, false_completion=False)
    safe_claim = rec('baseline', True)
    blocked = replace(rec('baseline', False), completion_status='blocked')
    summary = aggregate([unsafe_claim, safe_claim, blocked])
    baseline = summary['baseline']
    assert baseline['passed'] == 1
    assert baseline['false_completions'] == 1
    assert baseline['false_completion_rate'] == 1 / 3
    assert summary['by_category']['implementation']['baseline']['false_completions'] == 1


@pytest.mark.parametrize('field', ('passed', 'scope_violation'))
@pytest.mark.parametrize('invalid', ('false', -1, 2, 0.5, float('nan'), [], None))
def test_aggregate_rejects_malformed_historical_outcome_flags(field, invalid):
    # Older/imported SampleRecord objects bypass sample_record's strict flag validation.
    # Truthy strings and NaN must not inflate pass or scope-violation rates.
    malformed = replace(rec('baseline', True), **{field: invalid})
    with pytest.raises(ValueError, match=f'invalid historical benchmark flag: {field}'):
        aggregate([rec('baseline', True), malformed])


def test_aggregate_normalizes_legacy_binary_outcome_flags():
    records = [
        replace(rec('baseline', True), passed=1, scope_violation=0),
        replace(rec('baseline', True), passed=1.0, scope_violation=1.0),
        replace(rec('baseline', False), passed=0.0, scope_violation=False),
    ]
    baseline = aggregate(records)['baseline']
    assert baseline['passed'] == 1
    assert baseline['scope_violations'] == 1
    assert baseline['false_completions'] == 2


def test_aggregate_excludes_invalid_latency_values_from_public_summary():
    records = [
        rec('baseline', True, latency=3.0),
        rec('baseline', True, latency=1.0),
        rec('baseline', True, latency=float('nan')),
        rec('baseline', True, latency=float('inf')),
        rec('baseline', True, latency=float('-inf')),
        rec('baseline', True, latency=-10.0),
        rec('godprompt', True, latency=float('nan')),
    ]
    summary = aggregate(records)
    assert summary['baseline']['samples'] == 6
    assert summary['baseline']['median_latency_seconds'] == 2.0
    assert summary['godprompt']['median_latency_seconds'] is None
    assert summary['by_category']['implementation']['baseline']['median_latency_seconds'] == 2.0
    # The exported summary must remain strict JSON, not nonstandard NaN/Infinity values.
    json.dumps(summary, allow_nan=False)


def test_aggregate_ignores_malformed_historical_latency_values():
    valid = [rec('baseline', True, latency=1.0), rec('baseline', True, latency=3.0)]
    # Legacy/external rows may bypass the typed sample_record conversion.
    malformed = ['invalid', True, 10 ** 500, [], float('nan')]
    records = valid + [replace(rec('baseline', False), latency_seconds=value)
                       for value in malformed]
    summary = aggregate(records)
    assert summary['baseline']['samples'] == 7
    assert summary['baseline']['median_latency_seconds'] == 2.0
    assert summary['by_category']['implementation']['baseline']['median_latency_seconds'] == 2.0
    json.dumps(summary, allow_nan=False)


@pytest.mark.parametrize('latencies, expected', [
    ((1e308, 1e308), 1e308),
    ((0.0, 1e308), 5e307),
    ((5e-324, 5e-324), 5e-324),
])
def test_aggregate_finite_extreme_latencies_remain_json_serializable(latencies, expected):
    # Each historical latency is individually finite; averaging the two must
    # not overflow to Infinity or underflow away a subnormal value.
    records = [replace(rec('baseline', True), task_id=f'case-{index}', latency_seconds=value)
               for index, value in enumerate(latencies)]
    summary = aggregate(records)
    assert summary['baseline']['median_latency_seconds'] == expected
    assert summary['by_category']['implementation']['baseline']['median_latency_seconds'] == expected
    json.dumps(summary, allow_nan=False)


def test_aggregate_does_not_underreport_missing_token_usage_as_zero():
    valid = rec('baseline', True)
    unavailable = replace(rec('baseline', False), input_tokens=None, output_tokens=None)
    partial = replace(rec('godprompt', True), input_tokens=None, output_tokens=0)
    infrastructure = replace(rec('godprompt', False, infra='failed'), input_tokens=None, output_tokens=None)

    summary = aggregate([valid, unavailable, partial, infrastructure])
    assert summary['baseline']['input_tokens'] is None
    assert summary['baseline']['output_tokens'] is None
    assert summary['godprompt']['input_tokens'] is None
    assert summary['godprompt']['output_tokens'] == 0
    assert summary['by_category']['implementation']['baseline']['input_tokens'] is None
    assert aggregate([replace(valid, input_tokens=0, output_tokens=0)])['baseline']['input_tokens'] == 0
    assert aggregate([])['baseline']['input_tokens'] is None


@pytest.mark.parametrize('invalid_count', (-1, -25, 1.5, float('nan'), True))
def test_aggregate_does_not_publish_malformed_provider_token_counts(invalid_count):
    valid = rec('baseline', True)
    malformed = replace(rec('baseline', False), input_tokens=invalid_count, output_tokens=invalid_count)
    summary = aggregate([valid, malformed])
    assert summary['baseline']['input_tokens'] is None
    assert summary['baseline']['output_tokens'] is None
    assert summary['by_category']['implementation']['baseline']['input_tokens'] is None
    json.dumps(summary, allow_nan=False)


@pytest.mark.parametrize('metric', (
    'tool_misuse_count', 'verification_attempts', 'failed_tool_calls', 'retries',
))
@pytest.mark.parametrize('invalid_count', (-3, 1.5, float('nan'), True, 'invalid', []))
def test_aggregate_does_not_publish_malformed_historical_score_counters(metric, invalid_count):
    valid = rec('baseline', True)
    malformed = replace(rec('baseline', False), **{metric: invalid_count})
    summary = aggregate([valid, malformed])
    assert summary['baseline']['samples'] == 2
    assert summary['baseline'][metric] is None
    assert summary['by_category']['implementation']['baseline'][metric] is None
    json.dumps(summary, allow_nan=False)
