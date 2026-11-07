from __future__ import annotations

import csv
import json
import re
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable

from .aggregate import aggregate
from .models import SampleRecord

_SECRET_KEY = re.compile(
    r"(?:api[_-]?key|authorization|access[_-]?key[_-]?id|access[_-]?token|refresh[_-]?token|"
    r"session[_-]?token|id[_-]?token|(?:auth|oauth|client)[_-]?token|private[_-]?key|secret|password|^token$|"
    r"^(?:cookie|set[_-]?cookie|sig|signature|awsaccesskeyid|googleaccessid|"
    r"x-amz-(?:signature|credential|security-token)|"
    r"x-goog-(?:signature|credential))$)",
    re.IGNORECASE,
)
_INLINE_CREDENTIAL = re.compile(
    r"(?i)(\b(?:[a-z][a-z0-9]*[_-])*(?:api[_-]?key|authorization|"
    r"access[_-]?key[_-]?id|access[_-]?token|refresh[_-]?token|secret[_-]access[_-]?key|"
    r"secret[_-]?key|github[_-]?token|(?:auth|oauth|client)[_-]?token|token|secret|password)\s*[:=]\s*)"
    r"(?:\"[^\"\r\n]*\"|'[^'\r\n]*'|[^\s,;&]+)"
)
_BEARER_TOKEN = re.compile(r"(?i)(\bBearer\s+)[a-z0-9._~+/=-]+")
_HTTP_BASIC_TOKEN = re.compile(
    r"(?i)(\b(?:proxy-)?authorization[ \t]*[:=][ \t]*basic[ \t]+)[a-z0-9+/_=-]+"
)
_HTTP_DIGEST_HEADER = re.compile(
    r"(?i)(\b(?:proxy-)?authorization[ \t]*[:=][ \t]*)digest\b[^\r\n]*"
)
_HTTP_NAMED_TOKEN = re.compile(
    r"(?i)(\b(?:proxy-)?authorization[ \t]*[:=][ \t]*)"
    r"(?:token|api[_-]?key)[ \t]+[^\s,;]+"
)
_HTTP_AUTH_HEADER = re.compile(
    r"(?i)(\b(?:proxy-)?authorization[ \t]*:[ \t]*)[^\r\n]*?"
    r"(?=;[ \t]*(?:proxy-)?authorization[ \t]*[:=]|\r|\n|$)"
)
_COOKIE_HEADER = re.compile(r"(?i)(\b(?:set-cookie|cookie)[ \t]*:[ \t]*)(?=[^\r\n]*=)[^\r\n]+")
_KNOWN_TOKEN = re.compile(r"\b(?:sk-(?:proj-)?[A-Za-z0-9_-]{8,}|gh[pousr]_[A-Za-z0-9_]{12,}|github_pat_[A-Za-z0-9_]{12,})\b")
_URL_USERINFO = re.compile(r"(?i)(\b[a-z][a-z0-9+.-]*://)[^\s/?#@]+@")
_SIGNED_URL_QUERY = re.compile(
    r"(?i)((?:[?&]|&amp;)(?:x-amz-(?:credential|signature|security-token)|"
    r"x-goog-(?:credential|signature)|awsaccesskeyid|googleaccessid|signature|sig)=)"
    r"[^\s&#\"'<>]+"
)


def _redact_text(text: str) -> str:
    """Redact credential-shaped substrings even inside otherwise public text."""
    text = _URL_USERINFO.sub(lambda match: f"{match.group(1)}[REDACTED]@", text)
    # Presigned storage URLs carry credentials in query parameter values.
    text = _SIGNED_URL_QUERY.sub(lambda match: f"{match.group(1)}[REDACTED]", text)
    # Authentication schemes can carry comma-separated signed credentials;
    # mask the whole header, preserving a semicolon-separated peer header.
    text = _HTTP_AUTH_HEADER.sub(lambda match: f"{match.group(1)}[REDACTED]", text)
    # Digest credentials are comma-separated; masking only the scheme leaks its
    # username, nonce and response hash into the exported trace.
    text = _HTTP_DIGEST_HEADER.sub(lambda match: f"{match.group(1)}[REDACTED]", text)
    text = _COOKIE_HEADER.sub(lambda match: f"{match.group(1)}[REDACTED]", text)
    text = _HTTP_BASIC_TOKEN.sub(lambda match: f"{match.group(1)}[REDACTED]", text)
    text = _HTTP_NAMED_TOKEN.sub(lambda match: f"{match.group(1)}[REDACTED]", text)
    text = _BEARER_TOKEN.sub(lambda match: f"{match.group(1)}[REDACTED]", text)
    text = _INLINE_CREDENTIAL.sub(lambda match: f"{match.group(1)}[REDACTED]", text)
    return _KNOWN_TOKEN.sub("[REDACTED]", text)


def redact_secrets(value: Any) -> Any:
    if isinstance(value, str):
        return _redact_text(value)
    if isinstance(value, dict):
        return {
            (_redact_text(key) if isinstance(key, str) else key):
                "[REDACTED]" if _SECRET_KEY.search(str(key)) else redact_secrets(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_secrets(item) for item in value]
    if isinstance(value, tuple):
        return [redact_secrets(item) for item in value]
    return value


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(redact_secrets(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _spreadsheet_safe_cell(value: Any) -> Any:
    """Keep untrusted text from becoming a formula when scores.csv is opened."""
    if isinstance(value, str) and value.lstrip(" \t\r\n").startswith(("=", "+", "-", "@")):
        return "'" + value
    if isinstance(value, str) and value.startswith(("\t", "\r", "\n")):
        return "'" + value
    return value


def export_run(
    output_dir: Path,
    manifest: dict[str, Any],
    records: Iterable[SampleRecord],
    trajectories: Iterable[dict[str, Any]],
) -> None:
    records_list = list(records)
    trajectories_list = list(trajectories)
    summary = aggregate(records_list)
    output_dir.mkdir(parents=True, exist_ok=True)

    _write_json(output_dir / "manifest.json", manifest)
    _write_json(output_dir / "summary.json", summary)

    fieldnames = list(SampleRecord.__dataclass_fields__.keys())
    with (output_dir / "scores.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for record in records_list:
            writer.writerow({key: _spreadsheet_safe_cell(redact_secrets(value)) for key, value in asdict(record).items()})

    with (output_dir / "trajectories.jsonl").open("w", encoding="utf-8") as handle:
        for trajectory in trajectories_list:
            handle.write(json.dumps(redact_secrets(trajectory), sort_keys=True) + "\n")
