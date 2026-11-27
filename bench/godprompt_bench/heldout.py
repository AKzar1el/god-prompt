"""Read-only preflight for a separate, opt-in Bench 2.0 held-out corpus.

The reference corpus is never edited, and neither prompts nor hidden verifier
contents are returned. This checks manifest provenance and failure-mode
coverage, NOT whether a corpus is truly unseen by a model or ready to run.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import re
from pathlib import Path, PurePosixPath
from typing import Any

from .corpus import (
    _parse_fixture_bundle, _parse_manifest, _reject_duplicate_json_keys,
    validate_manifest,
)

SCHEMA = "godprompt.heldout_modes.v1"
FAILURE_MODES = (
    "false_completion",
    "scope_creep",
    "missing_verification",
    "multi_session_handoff",
    "misleading_receipt",
    "negative_instructions",
    "hidden_dependency_changes",
    "stale_context",
)
_MAX_MANIFEST_BYTES = 1024 * 1024
_MAX_FIXTURE_BYTES = 1024 * 1024
_MAX_TOTAL_FIXTURE_BYTES = 64 * 1024 * 1024
_FROZEN_INPUT_HASHES = (
    "reference_manifest_sha256", "heldout_manifest_sha256",
    "mode_manifest_sha256", "fixture_bundle_sha256",
)


def _read_small(path: Path) -> bytes:
    with path.open("rb") as handle:
        raw = handle.read(_MAX_MANIFEST_BYTES + 1)
    if len(raw) > _MAX_MANIFEST_BYTES:
        raise ValueError("held-out preflight manifest is too large")
    return raw


def _fingerprint(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _linked(path: Path) -> bool:
    return path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction())


def _bounded_fixture_bytes(path: Path) -> bytes:
    with path.open("rb") as handle:
        raw = handle.read(_MAX_FIXTURE_BYTES + 1)
    if len(raw) > _MAX_FIXTURE_BYTES:
        raise ValueError("held-out fixture bundle is too large")
    return raw


def _fixture_bundle_fingerprint(fixture_root: Path, tasks: list[Any]) -> str:
    """Freeze bytes of private fixture.json bundles without disclosing their contents."""
    root = Path(fixture_root)
    if _linked(root) or not root.is_dir():
        raise ValueError("fixture root must be an existing unlinked directory")
    resolved_root = root.resolve()
    entries: list[tuple[str, str]] = []
    total_bytes = 0
    for task in sorted(tasks, key=lambda item: item.id.casefold()):
        bundle = root
        for component in (*PurePosixPath(task.fixture_dir).parts, "fixture.json"):
            bundle = bundle / component
            if _linked(bundle):
                raise ValueError("linked fixture bundle or directory is not allowed")
        if not bundle.resolve().is_relative_to(resolved_root):
            raise ValueError("held-out fixture escaped its root")
        if not bundle.is_file():
            raise ValueError("missing fixture bundle")
        raw = _bounded_fixture_bytes(bundle)
        total_bytes += len(raw)
        if total_bytes > _MAX_TOTAL_FIXTURE_BYTES:
            raise ValueError("total held-out fixture bundles are too large")
        try:
            _parse_fixture_bundle(raw.decode("utf-8"), bundle.parent.name)
        except (ValueError, OSError, UnicodeError) as exc:
            raise ValueError("invalid held-out fixture bundle") from exc
        if _bounded_fixture_bytes(bundle) != raw:
            raise ValueError("held-out fixture bundle changed during validation")
        entries.append((task.id.casefold(), _fingerprint(raw)))
    encoded = json.dumps(entries, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return _fingerprint(encoded)


def _verify_frozen_report(report: dict[str, Any], expected_path: Path) -> None:
    """Compare all input fingerprints to a previously saved, owner-controlled report."""
    raw = _read_small(Path(expected_path))
    try:
        expected = json.loads(raw, object_pairs_hook=_reject_duplicate_json_keys)
    except (ValueError, UnicodeError) as exc:
        raise ValueError("invalid expected report JSON") from exc
    if (
        not isinstance(expected, dict)
        or expected.get("schema") != report["schema"]
        or expected.get("preview_only") is not True
        or type(expected.get("fixture_bundle_count")) is not int
        or expected["fixture_bundle_count"] < 1
    ):
        raise ValueError("invalid expected report schema or fixture count")
    for key in _FROZEN_INPUT_HASHES:
        digest = expected.get(key)
        if not isinstance(digest, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
            raise ValueError(f"expected report missing or invalid {key}")
        if digest != report[key]:
            raise ValueError(f"held-out input fingerprint mismatch: {key}")
    if expected["fixture_bundle_count"] != report["fixture_bundle_count"]:
        raise ValueError("held-out input fingerprint mismatch: fixture_bundle_count")
    if _read_small(Path(expected_path)) != raw:
        raise ValueError("expected report changed during verification")
    report["input_fingerprints_match"] = True


def preflight_heldout_corpus(
    reference_manifest: Path, heldout_manifest: Path, mode_manifest: Path,
    *, min_cases_per_mode: int | None = None,
    fixture_root: Path | None = None,
    expected_report: Path | None = None,
) -> dict[str, Any]:
    """Validate disjoint held-out task metadata without invoking models or tools.

    The held-out task manifest uses the existing Bench TaskSpec schema; the
    separate mode sidecar contains ONLY case IDs and failure-mode labels.
    Validity of private fixtures, hidden verifiers, novelty and statistical
    independence must be established separately by the evaluation owner.
    """
    if min_cases_per_mode is not None and (
        type(min_cases_per_mode) is not int
        or not 1 <= min_cases_per_mode <= 10000
    ):
        raise ValueError("min_cases_per_mode must be an integer from 1 to 10000")
    if expected_report is not None and fixture_root is None:
        raise ValueError("expected_report requires fixture_root for complete input verification")
    paths = tuple(Path(path).resolve() for path in (
        reference_manifest, heldout_manifest, mode_manifest,
    ))
    if len(set(paths)) != len(paths):
        raise ValueError("reference, held-out and failure-mode manifests must be distinct")

    reference_raw, heldout_raw, mode_raw = tuple(_read_small(path) for path in paths)
    # Validate the snapshots that are hashed, rather than reopening the files.
    reference_tasks = _parse_manifest(reference_raw.decode("utf-8"))
    heldout_tasks = _parse_manifest(heldout_raw.decode("utf-8"))
    validate_manifest(reference_tasks)
    validate_manifest(heldout_tasks)
    if not heldout_tasks:
        raise ValueError("held-out corpus must contain at least one task")

    reference_ids = {task.id.casefold() for task in reference_tasks}
    heldout_ids = {task.id.casefold() for task in heldout_tasks}
    if reference_ids & heldout_ids:
        raise ValueError("held-out task ID overlaps a reference task ID")

    reference_fixtures = {task.fixture_dir.casefold() for task in reference_tasks}
    heldout_fixtures = [task.fixture_dir.casefold() for task in heldout_tasks]
    if reference_fixtures.intersection(heldout_fixtures):
        raise ValueError("held-out fixture overlaps a reference fixture")
    if len(set(heldout_fixtures)) != len(heldout_fixtures):
        raise ValueError("held-out fixture directory is reused")

    modes = json.loads(mode_raw, object_pairs_hook=_reject_duplicate_json_keys)
    if not isinstance(modes, dict) or modes.get("schema") != SCHEMA:
        raise ValueError("unsupported held-out failure-mode schema")
    if set(modes) != {"schema", "cases"}:
        raise ValueError("failure-mode manifest has unknown fields")
    cases = modes["cases"]
    if not isinstance(cases, list):
        raise ValueError("failure-mode cases must be a list")
    seen: set[str] = set()
    counts: Counter[str] = Counter()
    for i, case in enumerate(cases):
        if not isinstance(case, dict) or set(case) != {"id", "failure_mode"}:
            raise ValueError(f"case {i} has unknown fields or missing fields")
        task_id, mode = case["id"], case["failure_mode"]
        if not isinstance(task_id, str):
            raise ValueError("failure-mode case ID must be a string")
        folded = task_id.casefold()
        if folded in seen:
            raise ValueError("duplicate case ID")
        seen.add(folded)
        if not isinstance(mode, str) or mode not in FAILURE_MODES:
            raise ValueError("unknown failure mode")
        counts[mode] += 1
    if seen != heldout_ids:
        raise ValueError("failure-mode cases must exactly match held-out task IDs")

    # Partial pilots are allowed by default; formal coverage gates opt in.
    if min_cases_per_mode is not None:
        missing = [
            mode for mode in FAILURE_MODES if counts[mode] < min_cases_per_mode
        ]
        if missing:
            raise ValueError(
                "minimum failure-mode coverage not met: "
                + ", ".join(f"{mode}={counts[mode]}" for mode in missing)
            )

    # The fingerprint must describe the exact manifest bytes that were validated,
    # not a stale snapshot if another process changed an input during this read.
    if any(_read_small(path) != raw for path, raw in zip(paths, (
        reference_raw, heldout_raw, mode_raw,
    ))):
        raise ValueError("preflight manifest changed during validation")

    report = {
        "schema": "godprompt.heldout_preflight.v1",
        "preview_only": True,
        "reference_task_count": len(reference_tasks),
        "heldout_task_count": len(heldout_tasks),
        "failure_mode_counts": dict(sorted(counts.items())),
        "uncovered_failure_modes": sorted(set(FAILURE_MODES) - counts.keys()),
        "reference_manifest_sha256": _fingerprint(reference_raw),
        "heldout_manifest_sha256": _fingerprint(heldout_raw),
        "mode_manifest_sha256": _fingerprint(mode_raw),
        "cost_estimate_usd": None,
        "note": (
            "Metadata-only preflight. No fixture/verifier execution, provider call, "
            "third-arm registration, novelty proof or independent result verification."
        ),
    }
    if fixture_root is not None:
        report["fixture_bundle_count"] = len(heldout_tasks)
        report["fixture_bundle_sha256"] = _fixture_bundle_fingerprint(fixture_root, heldout_tasks)
    if expected_report is not None:
        _verify_frozen_report(report, expected_report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate a separate Bench 2.0 held-out task/mode pair offline"
    )
    parser.add_argument(
        "--reference",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "tasks" / "manifest.json",
        help="frozen 40-task reference manifest (read only)",
    )
    parser.add_argument("--heldout", type=Path, required=True)
    parser.add_argument("--modes", type=Path, required=True)
    parser.add_argument(
        "--fixture-root", type=Path, default=None,
        help="opt-in private fixture root; verify and hash fixture.json bytes without executing them",
    )
    parser.add_argument(
        "--expected-report", type=Path, default=None,
        help="fail if any current input fingerprint differs from a saved full preflight report; requires --fixture-root",
    )
    parser.add_argument(
        "--min-cases-per-mode", type=int, default=None,
        help="optional strict coverage gate: require N cases for every supported failure mode",
    )
    args = parser.parse_args()
    try:
        result = preflight_heldout_corpus(
            args.reference, args.heldout, args.modes,
            min_cases_per_mode=args.min_cases_per_mode,
            fixture_root=args.fixture_root,
            expected_report=args.expected_report,
        )
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
