"""Read-only qualification of a held-out, three-arm Bench 2.0 run plan.

The existing two-condition benchmark remains unchanged. A passing preview
means only that declared controls, sample coverage and manifest fingerprints
are internally consistent; it never executes a model, MCP call or sandbox.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from math import isfinite
from pathlib import Path
import re
from typing import Any

from .corpus import _reject_duplicate_json_keys
from .heldout import preflight_heldout_corpus
from .mcp_contract_adapter import MCP_RELEASE_SHA
from .run import load_profile

SCHEMA = "godprompt.three_arm_plan.v1"
ARMS = ("baseline", "godprompt", "godprompt_mcp_contract")
_SHA256 = re.compile(r"sha256:[0-9a-f]{64}\Z")
_COMMIT = re.compile(r"[0-9a-f]{40}\Z")
_MODEL_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}\Z")
_MAX_PLAN_BYTES = 65536
_FINGERPRINT_FIELDS = (
    "sandbox_compose_sha256", "tool_inventory_sha256",
    "approval_policy_sha256", "baseline_prompt_sha256",
    "godprompt_prompt_sha256",
)
_LIMIT_FIELDS = ("epochs", "max_messages", "max_time_seconds", "max_output_tokens")


def _keys(value: Any, expected: set[str], field: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError(f"{field} has missing or unknown fields")
    return value


def _read_plan(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file() or path.suffix.lower() != ".json":
        raise ValueError("plan must be a regular JSON file, not a symlink")
    if path.stat().st_size > _MAX_PLAN_BYTES:
        raise ValueError("plan exceeds the 64 KiB limit")
    raw = path.read_bytes()
    if len(raw) > _MAX_PLAN_BYTES:
        raise ValueError("plan exceeds the 64 KiB limit")
    return raw


def preflight_three_arm_plan(
    plan_path: Path, reference_manifest: Path, heldout_manifest: Path,
    mode_manifest: Path,
) -> dict[str, Any]:
    """Check one fixed three-arm design against actual, distinct corpus files.

    Input hashes are compared with the *bytes read now*, not trusted from a
    caller's report. Model settings and execution controls are single shared
    values by schema, so a per-arm change cannot silently alter the comparison.
    This does not authenticate claimed source/policy digests or enable execution.
    """
    paths = tuple(Path(p) for p in (
        plan_path, reference_manifest, heldout_manifest, mode_manifest,
    ))
    if len({p.resolve() for p in paths}) != 4:
        raise ValueError("plan and corpus manifests must be distinct")
    raw = _read_plan(paths[0])
    plan = json.loads(raw, object_pairs_hook=_reject_duplicate_json_keys)
    plan = _keys(plan, {
        "schema", "arms", "corpus", "model", "limits", "controls",
    }, "plan")
    if plan["schema"] != SCHEMA:
        raise ValueError("unsupported three-arm plan schema")
    if plan["arms"] != list(ARMS):
        raise ValueError("plan arms must contain exactly three ordered conditions")

    corpus_pins = _keys(plan["corpus"], {
        "reference_sha256", "heldout_sha256", "modes_sha256",
    }, "corpus")
    if any(not isinstance(value, str) or not _SHA256.fullmatch(value)
           for value in corpus_pins.values()):
        raise ValueError("invalid corpus fingerprint")

    model = _keys(plan["model"], {
        "provider", "id", "temperature", "seed",
    }, "model")
    if any(
        not isinstance(model[field], str)
        or not _MODEL_NAME.fullmatch(model[field])
        for field in ("provider", "id")
    ):
        raise ValueError("model/provider names must be nonsecret identifiers")
    temperature, seed = model["temperature"], model["seed"]
    if (
        type(temperature) not in (int, float)
        or not isfinite(temperature)
        or not 0 <= temperature <= 2
    ):
        raise ValueError("model temperature must be finite in [0, 2]")
    if type(seed) is not int or not 0 <= seed < 2**32:
        raise ValueError("model seed must be a bounded integer")

    limits = _keys(plan["limits"], set(_LIMIT_FIELDS), "limits")
    bench_root = Path(__file__).resolve().parents[1]
    maximum = load_profile(bench_root / "configs" / "full.json")
    for field in _LIMIT_FIELDS:
        value = limits[field]
        if type(value) is not int or not 0 < value <= getattr(maximum, field):
            raise ValueError(f"limit {field} is invalid or above the full-profile budget")

    controls = _keys(plan["controls"], {
        "source_commit", "mcp_release_sha", *_FINGERPRINT_FIELDS,
    }, "controls")
    if not isinstance(controls["source_commit"], str) or not _COMMIT.fullmatch(
        controls["source_commit"]
    ):
        raise ValueError("controls source_commit must be a full lowercase Git SHA")
    if controls["mcp_release_sha"] != MCP_RELEASE_SHA:
        raise ValueError("MCP release SHA differs from the pinned adapter source")
    if any(
        not isinstance(controls[field], str)
        or not _SHA256.fullmatch(controls[field])
        for field in _FINGERPRINT_FIELDS
    ):
        raise ValueError("controls require full lowercase SHA-256 fingerprints")

    corpus = preflight_heldout_corpus(*paths[1:])
    expected_pins = {
        "reference_sha256": corpus["reference_manifest_sha256"],
        "heldout_sha256": corpus["heldout_manifest_sha256"],
        "modes_sha256": corpus["mode_manifest_sha256"],
    }
    if corpus_pins != expected_pins:
        raise ValueError("corpus fingerprint does not match current manifest bytes")
    if _read_plan(paths[0]) != raw:
        raise ValueError("plan changed during validation")

    per_arm = corpus["heldout_task_count"] * limits["epochs"]
    return {
        "schema": "godprompt.three_arm_preview.v1",
        "preview_only": True,
        "arms": list(ARMS),
        "heldout_task_count": corpus["heldout_task_count"],
        "epochs": limits["epochs"],
        "samples_per_arm": per_arm,
        "total_planned_samples": per_arm * len(ARMS),
        "uncovered_failure_modes": corpus["uncovered_failure_modes"],
        "plan_sha256": "sha256:" + hashlib.sha256(raw).hexdigest(),
        "reference_manifest_sha256": expected_pins["reference_sha256"],
        "heldout_manifest_sha256": expected_pins["heldout_sha256"],
        "mode_manifest_sha256": expected_pins["modes_sha256"],
        "cost_estimate_usd": None,
        "note": (
            "Metadata-only preflight: source/policy pins are declarations, not "
            "authenticated provenance. No provider, MCP, sandbox or verifier "
            "execution, third-arm registration, outcome or uplift proof."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Preflight one held-out three-arm experiment plan offline",
    )
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument(
        "--reference", type=Path,
        default=Path(__file__).resolve().parents[1] / "tasks" / "manifest.json",
    )
    parser.add_argument("--heldout", type=Path, required=True)
    parser.add_argument("--modes", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = preflight_three_arm_plan(
            args.plan, args.reference, args.heldout, args.modes,
        )
    except (OSError, ValueError, UnicodeError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
