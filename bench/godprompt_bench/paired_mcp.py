"""Offline paired evaluation of baseline vs GodPrompt vs GodPrompt+MCP.

Consumes caller-supplied, frozen outcome rows. Never invokes a model, tool,
network endpoint, Docker, or the existing benchmark runner.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import json
from math import isfinite
from pathlib import Path
import re
from statistics import median
import sys
from typing import Any

SCHEMA = "godprompt.paired_mcp_outcome.v1"
ARMS = ("baseline", "godprompt", "godprompt_mcp")
MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_ROWS = 20000

REQUIRED = frozenset({
    "schema", "task_id", "category", "epoch", "seed", "condition",
    "model_id", "fixture_sha256", "controls_sha256", "toolset_sha256",
    "passed", "scope_violation", "completion_status",
    "verification_attempts", "input_tokens", "output_tokens",
    "latency_seconds", "infrastructure_error", "contract_id",
})

_IDENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$")
_MODEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_./:-]{0,119}$")
_SHA = re.compile(r"^[0-9a-f]{64}$")
_CONTRACT = re.compile(r"^sha256:[0-9a-f]{64}$")


def _check_string(value: object, field: str, pattern: re.Pattern[str]) -> str:
    if type(value) is not str or not pattern.fullmatch(value):
        raise ValueError("invalid " + field)
    return value


def _nonnegative(value: object, field: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError("invalid nonnegative integer: " + field)
    return value


def _optional_count(value: object, field: str) -> int | None:
    return None if value is None else _nonnegative(value, field)


def _latency(value: object) -> float | None:
    if value is None:
        return None
    if type(value) not in (int, float):
        raise ValueError("latency_seconds must be finite and nonnegative or null")
    try:
        seconds = float(value)
    except OverflowError as error:
        raise ValueError("latency_seconds must be finite and nonnegative or null") from error
    if not isfinite(seconds) or seconds < 0:
        raise ValueError("latency_seconds must be finite and nonnegative or null")
    return seconds


def validate_row(value: object) -> dict[str, Any]:
    if type(value) is not dict or set(value) != REQUIRED:
        raise ValueError("paired outcome must contain exactly the v1 allowlisted fields")
    row = dict(value)
    if row["schema"] != SCHEMA:
        raise ValueError("unknown paired outcome schema")
    _check_string(row["task_id"], "task_id", _IDENT)
    _check_string(row["category"], "category", _IDENT)
    _check_string(row["model_id"], "model_id", _MODEL)
    for key in ("fixture_sha256", "controls_sha256", "toolset_sha256"):
        _check_string(row[key], key, _SHA)
    if row["condition"] not in ARMS or type(row["condition"]) is not str:
        raise ValueError("unknown benchmark arm")
    if _nonnegative(row["epoch"], "epoch") < 1:
        raise ValueError("epoch must be at least 1")
    _nonnegative(row["seed"], "seed")
    for key in ("passed", "scope_violation"):
        if type(row[key]) is not bool:
            raise ValueError(key + " must be a boolean")
    if row["completion_status"] not in ("complete", "partial", "blocked", "stopped"):
        raise ValueError("invalid completion_status")
    _nonnegative(row["verification_attempts"], "verification_attempts")
    row["input_tokens"] = _optional_count(row["input_tokens"], "input_tokens")
    row["output_tokens"] = _optional_count(row["output_tokens"], "output_tokens")
    row["latency_seconds"] = _latency(row["latency_seconds"])
    error = row["infrastructure_error"]
    if error is not None and (type(error) is not str or not 1 <= len(error) <= 200):
        raise ValueError("invalid infrastructure_error")
    contract = row["contract_id"]
    if row["condition"] == "godprompt_mcp":
        _check_string(contract, "contract_id", _CONTRACT)
    elif contract is not None:
        raise ValueError("non-MCP condition cannot claim a task contract")
    return row


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key: " + key)
        result[key] = value
    return result


def _no_constants(value: str) -> None:
    raise ValueError("non-finite JSON value: " + value)


def read_jsonl(filename: str | Path) -> list[dict[str, Any]]:
    path = Path(filename)
    if path.is_symlink():
        raise ValueError("input must not be a symlink")
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError("input exceeds the 5 MiB safety limit")
    data = path.read_bytes()
    if len(data) > MAX_FILE_BYTES:
        raise ValueError("input exceeds the 5 MiB safety limit")
    lines = data.decode("utf-8").splitlines()
    if not lines or len(lines) > MAX_ROWS:
        raise ValueError("expected 1-20000 JSONL outcome rows")
    records: list[dict[str, Any]] = []
    for index, line in enumerate(lines, 1):
        if not line or len(line.encode("utf-8")) > 4096:
            raise ValueError("empty or oversized JSONL row at line " + str(index))
        try:
            value = json.loads(
                line,
                object_pairs_hook=_no_duplicate_keys,
                parse_constant=_no_constants,
            )
            records.append(validate_row(value))
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            raise ValueError("invalid paired outcome at line " + str(index) + ": " + str(error)) from error
    return records


def _effective_pass(row: dict[str, Any]) -> bool:
    return row["passed"] and not row["scope_violation"]


def _rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _arm_summary(rows: list[dict[str, Any]], planned: int) -> dict[str, Any]:
    n = len(rows)
    passed = sum(_effective_pass(row) for row in rows)
    false_completions = sum(
        row["completion_status"] == "complete" and not _effective_pass(row)
        for row in rows
    )
    scope = sum(row["scope_violation"] for row in rows)
    tokens_in = (
        sum(row["input_tokens"] for row in rows)
        if n and all(row["input_tokens"] is not None for row in rows) else None
    )
    tokens_out = (
        sum(row["output_tokens"] for row in rows)
        if n and all(row["output_tokens"] is not None for row in rows) else None
    )
    known_latency = [row["latency_seconds"] for row in rows if row["latency_seconds"] is not None]
    return {
        "scheduled_pairs": planned,
        "evaluated_pairs": n,
        "infrastructure_excluded_pairs": planned - n,
        "effective_passes": passed,
        "pass_rate": _rate(passed, n),
        "false_completions": false_completions,
        "false_completion_rate": _rate(false_completions, n),
        "scope_violations": scope,
        "scope_violation_rate": _rate(scope, n),
        "verification_attempts": sum(row["verification_attempts"] for row in rows),
        "input_tokens_total": tokens_in,
        "output_tokens_total": tokens_out,
        "reported_latency_samples": len(known_latency),
        "median_latency_seconds": median(known_latency) if known_latency else None,
    }


def _paired_delta(
    left_rows: list[dict[str, Any]], right_rows: list[dict[str, Any]]
) -> dict[str, int | float | None]:
    n = len(left_rows)
    improved = sum(
        not _effective_pass(left) and _effective_pass(right)
        for left, right in zip(left_rows, right_rows, strict=True)
    )
    regressed = sum(
        _effective_pass(left) and not _effective_pass(right)
        for left, right in zip(left_rows, right_rows, strict=True)
    )
    return {
        "matched_pairs": n,
        "improved_only": improved,
        "regressed_only": regressed,
        "net_pass_rate_delta": _rate(improved - regressed, n),
    }


def analyze(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows or len(rows) > MAX_ROWS:
        raise ValueError("expected 1-20000 paired outcomes")
    groups: dict[tuple[str, int, int], dict[str, dict[str, Any]]] = defaultdict(dict)
    toolsets: dict[str, str] = {}
    for supplied in rows:
        row = validate_row(supplied)
        condition = row["condition"]
        if condition in toolsets and toolsets[condition] != row["toolset_sha256"]:
            raise ValueError("toolset fingerprint drift within one condition")
        toolsets[condition] = row["toolset_sha256"]
        key = (row["task_id"], row["epoch"], row["seed"])
        if condition in groups[key]:
            raise ValueError("duplicate outcome for a task/epoch/seed/condition")
        groups[key][condition] = row

    matched: list[dict[str, dict[str, Any]]] = []
    for key, arm_rows in sorted(groups.items()):
        if set(arm_rows) != set(ARMS):
            raise ValueError("missing comparison arm for task/epoch/seed: " + repr(key))
        compare = {(row["model_id"], row["fixture_sha256"], row["controls_sha256"], row["category"])
                   for row in arm_rows.values()}
        if len(compare) != 1:
            raise ValueError("model, fixture, generation controls or category mismatch across paired arms")
        matched.append(arm_rows)

    eligible = [group for group in matched
                if all(group[arm]["infrastructure_error"] is None for arm in ARMS)]
    by_arm = {arm: [group[arm] for group in eligible] for arm in ARMS}
    comparisons = {}
    for left, right in (("baseline", "godprompt"), ("baseline", "godprompt_mcp"),
                        ("godprompt", "godprompt_mcp")):
        comparisons[left + "_vs_" + right] = _paired_delta(by_arm[left], by_arm[right])

    return {
        "schema": "godprompt.paired_mcp_report.v1",
        "source_schema": SCHEMA,
        "model_evaluations_run": False,
        "caller_supplied_results": True,
        "pairs_total": len(matched),
        "pairs_evaluated": len(eligible),
        "pairs_excluded_infrastructure": len(matched) - len(eligible),
        "arms": {arm: _arm_summary(by_arm[arm], len(matched)) for arm in ARMS},
        "paired_comparisons": comparisons,
        "toolset_fingerprints": toolsets,
        "warnings": [
            "This report evaluates caller-supplied outcomes; it does not authenticate model runs or source evidence.",
            "No claim of agent quality uplift or statistical significance follows from fixture tests or a small sample.",
            "Toolset fingerprints can differ by arm because MCP adds capabilities; review this treatment difference.",
            "Missing token/latency values are not silently converted to zero.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Offline, free paired baseline/GodPrompt/GodPrompt+MCP outcome analyzer."
    )
    parser.add_argument("--input", required=True, help="Path to v1 paired outcome JSONL")
    args = parser.parse_args(argv)
    try:
        result = analyze(read_jsonl(args.input))
    except (OSError, UnicodeError, ValueError, TypeError) as error:
        print("paired-mcp: " + str(error), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
