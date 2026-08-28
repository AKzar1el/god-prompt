from __future__ import annotations

import csv
import json
import re
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable

from .aggregate import aggregate
from .models import SampleRecord

_SECRET_KEY = re.compile(r"(?:api_?key|authorization|access_?token|refresh_?token|secret|password)", re.IGNORECASE)


def redact_secrets(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if _SECRET_KEY.search(str(key)) else redact_secrets(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_secrets(item) for item in value]
    if isinstance(value, tuple):
        return [redact_secrets(item) for item in value]
    return value


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(redact_secrets(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def export_run(
    output_dir: Path,
    manifest: dict[str, Any],
    records: Iterable[SampleRecord],
    trajectories: Iterable[dict[str, Any]],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    records_list = list(records)
    trajectories_list = list(trajectories)

    _write_json(output_dir / "manifest.json", manifest)
    _write_json(output_dir / "summary.json", aggregate(records_list))

    fieldnames = list(SampleRecord.__dataclass_fields__.keys())
    with (output_dir / "scores.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for record in records_list:
            writer.writerow(asdict(record))

    with (output_dir / "trajectories.jsonl").open("w", encoding="utf-8") as handle:
        for trajectory in trajectories_list:
            handle.write(json.dumps(redact_secrets(trajectory), sort_keys=True) + "\n")
