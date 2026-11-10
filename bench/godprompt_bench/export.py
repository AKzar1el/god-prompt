from __future__ import annotations

import csv
import json
import re
import stat
from dataclasses import asdict
from io import StringIO
from math import isfinite
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import unquote

from .aggregate import aggregate
from .models import SampleRecord

_SECRET_KEY = re.compile(
    r"(?:api[ _-]?(?:key|token)|authorization|access[_-]?key[_-]?id|access[_-]?key(?![a-z0-9_])|access[_-]?token|refresh[_-]?token|"
    r"session[_-]?token|id[_-]?token|(?:auth|oauth|client)[_-]?token|private[_-]?key|secret|password|^token$|"
    r"^(?:cookie|set[_-]?cookie|sig|signature|awsaccesskeyid|googleaccessid|"
    r"x-amz-(?:signature|credential|security-token)|"
    r"x-goog-(?:signature|credential))$)",
    re.IGNORECASE,
)
_INLINE_CREDENTIAL = re.compile(
    r"(?i)(\b(?:[a-z][a-z0-9]*[_-])*(?:api[ _-]?(?:key|token)|authorization|"
    r"access[_-]?key(?:[_-]?id)?|access[_-]?token|refresh[_-]?token|(?:client|api)[_-]?secret|secret[_-]access[_-]?key|"
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
# Match through the last @ in the URL authority, not the first: userinfo can
# itself contain @, including in malformed-but-observed diagnostic strings.
_URL_USERINFO = re.compile(r"(?i)(\b[a-z][a-z0-9+.-]*://)[^\s/?#]+@")
_SIGNED_URL_QUERY = re.compile(
    r"(?i)((?:[?&]|&amp;)(?:x-amz-(?:credential|signature|security-token)|"
    r"x-goog-(?:credential|signature)|awsaccesskeyid|googleaccessid|signature|sig)=)"
    r"[^\s&#\"'<>]+"
)
_ENCODED_QUERY_KEY_VALUE = re.compile(
    r"(&amp;|[?&])([^?&=\s#\"'<>]*%[0-9a-fA-F]{2}[^?&=\s#\"'<>]*)(=)([^\s&#\"'<>]+)"
)
_JSON_QUOTED_FIELD = re.compile(
    r'(?P<prefix>(?P<key_quote>\\?")(?P<key>(?:\\(?:u[0-9a-fA-F]{4}|[\\/bfnrt])|[^"\\\r\n]){1,128})(?P=key_quote)[ \t]*:[ \t]*)'
    r'(?P<value_quote>\\?")(?P<value>(?:\\.|[^"\\\r\n])*?)(?P=value_quote)'
)
_JSON_SCALAR_FIELD = re.compile(
    r'(?P<prefix>(?P<key_quote>\\?")(?P<key>(?:\\(?:u[0-9a-fA-F]{4}|[\\/bfnrt])|[^"\\\r\n]){1,128})(?P=key_quote)[ \t]*:[ \t]*)'
    r'(?:-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?|true|false|null)'
    r'(?=[ \t]*[,}\]\r\n]|$)'
)
_CSV_FORMULA = re.compile(r"^[\s\u200b\ufeff]*[=+\-@]")


def _redact_encoded_query_key(match: re.Match[str]) -> str:
    # Decode only for classification; preserve the original URL key spelling.
    if _SECRET_KEY.search(unquote(match.group(2))):
        return f"{match.group(1)}{match.group(2)}{match.group(3)}[REDACTED]"
    return match.group(0)


def _json_key_is_secret(key: str) -> bool:
    # Nested diagnostic JSON can escape a Unicode key more than once.
    for _ in range(3):
        if _SECRET_KEY.search(key):
            return True
        try:
            decoded = json.loads(f'"{key}"')
        except json.JSONDecodeError:
            return False
        if decoded == key:
            return False
        key = decoded
    return bool(_SECRET_KEY.search(key))


def _redact_json_quoted_field(match: re.Match[str]) -> str:
    if _json_key_is_secret(match.group("key")):
        quote = match.group("value_quote")
        return f'{match.group("prefix")}{quote}[REDACTED]{quote}'
    return match.group(0)


def _redact_json_scalar_field(match: re.Match[str]) -> str:
    if _json_key_is_secret(match.group("key")):
        # Quote the replacement to keep embedded JSON and escaped JSON parseable.
        quote = match.group("key_quote")
        return f'{match.group("prefix")}{quote}[REDACTED]{quote}'
    return match.group(0)


def _redact_text(text: str) -> str:
    """Redact credential-shaped substrings even inside otherwise public text."""
    text = _URL_USERINFO.sub(lambda match: f"{match.group(1)}[REDACTED]@", text)
    # Inspect diagnostics can embed raw JSON or an escaped JSON string; keep
    # quotation delimiters intact so the redacted text remains parseable.
    text = _JSON_QUOTED_FIELD.sub(_redact_json_quoted_field, text)
    text = _JSON_SCALAR_FIELD.sub(_redact_json_scalar_field, text)
    text = _ENCODED_QUERY_KEY_VALUE.sub(_redact_encoded_query_key, text)
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
    if isinstance(value, float) and not isfinite(value):
        # Nonfinite provider diagnostics must not become invalid public JSON.
        return None
    if isinstance(value, dict):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            raw_key = str(key)
            safe_key = _redact_text(raw_key)
            # JSON member names are strings; avoid silently collapsing keys
            # such as the integer 1 and the string "1" during conversion.
            if safe_key in normalized:
                raise ValueError("ambiguous JSON object key after redaction")
            normalized[safe_key] = (
                "[REDACTED]" if _SECRET_KEY.search(raw_key) else redact_secrets(item)
            )
        return normalized
    if isinstance(value, list):
        return [redact_secrets(item) for item in value]
    if isinstance(value, tuple):
        return [redact_secrets(item) for item in value]
    return value


def _serialize_json(payload: Any) -> str:
    return json.dumps(redact_secrets(payload), indent=2, sort_keys=True, allow_nan=False) + "\n"


def _spreadsheet_safe_cell(value: Any) -> Any:
    """Keep untrusted text from becoming a formula when scores.csv is opened."""
    # Spreadsheets can ignore leading whitespace and invisible format markers.
    if isinstance(value, str) and _CSV_FORMULA.match(value):
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
    # Validate public JSON before creating a directory or replacing artifacts.
    # Malformed later input must not leave a partial or mixed-run export.
    serialized_manifest = _serialize_json(manifest)
    serialized_summary = _serialize_json(summary)
    serialized_trajectories = [
        json.dumps(redact_secrets(trajectory), sort_keys=True, allow_nan=False)
        for trajectory in trajectories_list
    ]
    fieldnames = list(SampleRecord.__dataclass_fields__.keys())
    scores_buffer = StringIO(newline="")
    scores_writer = csv.DictWriter(scores_buffer, fieldnames=fieldnames)
    scores_writer.writeheader()
    for record in records_list:
        scores_writer.writerow({
            key: _spreadsheet_safe_cell(redact_secrets(value))
            for key, value in asdict(record).items()
        })
    serialized_scores = scores_buffer.getvalue()
    # StringIO accepts lone surrogates that the final UTF-8 file cannot encode.
    serialized_scores.encode("utf-8")
    # Check each existing component before mkdir: a symlinked parent can
    # redirect every public artifact outside the chosen output directory.
    for candidate in (output_dir, *output_dir.parents):
        try:
            entry = candidate.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(entry.st_mode) or (
            getattr(entry, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        ):
            raise ValueError(f"refusing linked output directory: {candidate}")
    output_dir.mkdir(parents=True, exist_ok=True)

    # Refuse pre-existing links before writing any public artifact. Otherwise
    # a linked output filename can overwrite a file outside the export folder.
    for name in ("manifest.json", "summary.json", "scores.csv", "trajectories.jsonl"):
        target = output_dir / name
        if target.is_symlink() or (target.exists() and target.stat().st_nlink > 1):
            raise ValueError(f"refusing linked public artifact: {name}")

    (output_dir / "manifest.json").write_text(serialized_manifest, encoding="utf-8")
    (output_dir / "summary.json").write_text(serialized_summary, encoding="utf-8")

    with (output_dir / "scores.csv").open("w", newline="", encoding="utf-8") as handle:
        handle.write(serialized_scores)

    with (output_dir / "trajectories.jsonl").open("w", encoding="utf-8") as handle:
        for trajectory in serialized_trajectories:
            handle.write(trajectory + "\n")
