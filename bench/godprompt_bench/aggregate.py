from __future__ import annotations

from collections import defaultdict
from statistics import median
from typing import Iterable

from .models import SampleRecord


def _rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _summarize(records: list[SampleRecord]) -> dict[str, int | float | None]:
    model_records = [record for record in records if record.infrastructure_error is None]
    latencies = [record.latency_seconds for record in model_records if record.latency_seconds is not None]
    passed = sum(record.passed for record in model_records)
    false_completions = sum(record.false_completion for record in model_records)
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
        "tool_misuse_count": sum(record.tool_misuse_count for record in model_records),
        "verification_attempts": sum(record.verification_attempts for record in model_records),
        "failed_tool_calls": sum(record.failed_tool_calls for record in model_records),
        "retries": sum(record.retries for record in model_records),
        "input_tokens": sum(record.input_tokens or 0 for record in model_records),
        "output_tokens": sum(record.output_tokens or 0 for record in model_records),
        "median_latency_seconds": median(latencies) if latencies else None,
    }


def aggregate(records: Iterable[SampleRecord]) -> dict:
    items = list(records)
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
