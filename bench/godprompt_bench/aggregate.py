from __future__ import annotations

from collections import defaultdict
from math import isfinite
from statistics import median
from typing import Iterable

from .models import SampleRecord


def _rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _complete_token_total(counts: Iterable[int | None]) -> int | None:
    total = 0
    seen = False
    for count in counts:
        # Provider usage is untrusted: a negative, fractional or non-finite
        # value must not reduce the reported total or escape into JSON.
        if type(count) is not int or count < 0:
            return None
        total += count
        seen = True
    return total if seen else None


def _nonnegative_counter_total(counts: Iterable[int]) -> int | None:
    total = 0
    for count in counts:
        # An unvalidated historical row must not corrupt a reported total.
        if type(count) is not int or count < 0:
            return None
        total += count
    return total


def _summarize(records: list[SampleRecord]) -> dict[str, int | float | None]:
    model_records = [record for record in records if record.infrastructure_error is None]
    latencies: list[float] = []
    for record in model_records:
        value = record.latency_seconds
        if type(value) not in (int, float):
            continue
        try:
            seconds = float(value)
        except OverflowError:
            continue
        if isfinite(seconds) and seconds >= 0:
            latencies.append(seconds)
    # Correct historic records whose stored outcome flags predate scope-aware scoring.
    passed = sum(record.passed and not record.scope_violation for record in model_records)
    false_completions = sum(
        record.completion_status == "complete" and (not record.passed or record.scope_violation)
        for record in model_records
    )
    scope_violations = sum(record.scope_violation for record in model_records)
    return {
        "samples": len(records),
        "model_samples": len(model_records),
        "infrastructure_failures": len(records) - len(model_records),
        "passed": passed,
        "pass_rate": _rate(passed, len(model_records)),
        "false_completions": false_completions,
        "false_completion_rate": _rate(false_completions, len(model_records)),
        "scope_violations": scope_violations,
        "scope_violation_rate": _rate(scope_violations, len(model_records)),
        "tool_misuse_count": _nonnegative_counter_total(record.tool_misuse_count for record in model_records),
        "verification_attempts": _nonnegative_counter_total(record.verification_attempts for record in model_records),
        "failed_tool_calls": _nonnegative_counter_total(record.failed_tool_calls for record in model_records),
        "retries": _nonnegative_counter_total(record.retries for record in model_records),
        "input_tokens": _complete_token_total(record.input_tokens for record in model_records),
        "output_tokens": _complete_token_total(record.output_tokens for record in model_records),
        "median_latency_seconds": median(latencies) if latencies else None,
    }


def aggregate(records: Iterable[SampleRecord]) -> dict:
    items = list(records)
    for record in items:
        if record.condition not in ("baseline", "godprompt"):
            raise ValueError(f"unknown benchmark condition: {record.condition!r}")
    result: dict = {}
    for condition in ("baseline", "godprompt"):
        result[condition] = _summarize([r for r in items if r.condition == condition])

    categories: dict[str, list[SampleRecord]] = defaultdict(list)
    for record in items:
        categories[record.category].append(record)
    result["by_category"] = {
        category: {
            condition: _summarize([r for r in category_records if r.condition == condition])
            for condition in ("baseline", "godprompt")
        }
        for category, category_records in sorted(categories.items())
    }
    return result
