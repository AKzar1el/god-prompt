from __future__ import annotations

import csv
import json
import re
import shutil
import stat
import tempfile
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
_JSON_FRAGMENT_START = re.compile(r'[\[{"]')
_MAX_JSON_TEXT = 1024 * 1024
_MAX_JSON_FRAGMENTS = 256
_MAX_JSON_ENCODING_LAYERS = 12


def _redact_encoded_query_key(match: re.Match[str]) -> str:
    # Nested encodings occur in captured URLs; decode only for classification.
    key = match.group(2)
    for _ in range(3):
        key = unquote(key)
        if _SECRET_KEY.search(key):
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


def _redact_inline_text(text: str) -> str:
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


def _unique_json_members(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("ambiguous embedded JSON object key")
        result[key] = value
    return result


def _redact_text(text: str, encoding_depth: int = 0) -> str:
    """Redact complete JSON fragments before applying free-text heuristics."""
    if not _JSON_FRAGMENT_START.search(text):
        return _redact_inline_text(text)
    if len(text) > _MAX_JSON_TEXT or encoding_depth >= _MAX_JSON_ENCODING_LAYERS:
        return "[REDACTED]"

    decoder = json.JSONDecoder(object_pairs_hook=_unique_json_members)
    parts: list[str] = []
    cursor = search_from = attempts = 0
    while match := _JSON_FRAGMENT_START.search(text, search_from):
        start = match.start()
        attempts += 1
        if attempts > _MAX_JSON_FRAGMENTS:
            return "[REDACTED]"
        try:
            decoded, end = decoder.raw_decode(text, start)
        except json.JSONDecodeError:
            search_from = start + 1
            continue
        except (ValueError, RecursionError):
            # Duplicate keys or excessive nesting are ambiguous, not safe.
            return "[REDACTED]"
        search_from = end
        # Ordinary quoted values belong to the free-text redactor so inline
        # assignments such as api_key="value" retain their surrounding label.
        if isinstance(decoded, str) and not (
            (not text[:start].strip() and not text[end:].strip())
            or _JSON_FRAGMENT_START.search(decoded)
        ):
            continue
        if not isinstance(decoded, (dict, list, str)):
            continue
        try:
            safe = _redact_value(decoded, encoding_depth + 1)
            fragment = (text[start:end] if safe == decoded else
                        json.dumps(safe, allow_nan=False))
        except (ValueError, RecursionError):
            return "[REDACTED]"
        prefix = text[cursor:start]
        # Preserve credential context across a JSON boundary. For example,
        # password={"value":...} is a sensitive assignment as a whole.
        boundary = "GODPROMPT_JSON_FRAGMENT_BOUNDARY"
        checked_prefix = _redact_inline_text(prefix + boundary)
        if checked_prefix.endswith(boundary):
            parts.extend((_redact_inline_text(prefix), fragment))
        else:
            parts.append(checked_prefix)
        cursor = end
    parts.append(_redact_inline_text(text[cursor:]))
    return "".join(parts)


def _redact_value(value: Any, encoding_depth: int) -> Any:
    if isinstance(value, str):
        return _redact_text(value, encoding_depth)
    if isinstance(value, float) and not isfinite(value):
        # Nonfinite provider diagnostics must not become invalid public JSON.
        return None
    if isinstance(value, dict):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            raw_key = str(key)
            safe_key = _redact_text(raw_key, encoding_depth)
            # JSON member names are strings; avoid silently collapsing keys
            # such as the integer 1 and the string "1" during conversion.
            if safe_key in normalized:
                raise ValueError("ambiguous JSON object key after redaction")
            normalized[safe_key] = (
                "[REDACTED]" if _json_key_is_secret(raw_key) else _redact_value(item, encoding_depth)
            )
        return normalized
    if isinstance(value, list):
        return [_redact_value(item, encoding_depth) for item in value]
    if isinstance(value, tuple):
        return [_redact_value(item, encoding_depth) for item in value]
    return value


def redact_secrets(value: Any) -> Any:
    return _redact_value(value, 0)


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
        if target.is_symlink():
            raise ValueError(f"refusing linked public artifact: {name}")
        if target.exists() and not target.is_file():
            # A directory at a later filename must not leave earlier report
            # files overwritten before the export fails.
            raise ValueError(f"refusing non-file public artifact: {name}")
        if target.exists() and target.stat().st_nlink > 1:
            raise ValueError(f"refusing linked public artifact: {name}")

    # Keep temporary report and rollback copies OUTSIDE the public run folder.
    # Use a same-filesystem sibling so Path.replace remains an atomic file
    # operation; tempfile.mkdtemp creates an unpredictable, owner-only
    # directory on POSIX. The completed public files remain intentionally
    # readable; this is not a crash-atomic multi-file transaction.
    stage = Path(tempfile.mkdtemp(prefix=".godprompt-export-", dir=output_dir.parent))
    # The manifest is the provenance marker; replace it only after data files.
    names = ("scores.csv", "trajectories.jsonl", "summary.json", "manifest.json")
    promoted: list[str] = []
    existing: set[str] = set()
    preserve_recovery = False
    try:
        (stage / "manifest.json").write_text(serialized_manifest, encoding="utf-8")
        (stage / "summary.json").write_text(serialized_summary, encoding="utf-8")
        with (stage / "scores.csv").open("w", newline="", encoding="utf-8") as handle:
            handle.write(serialized_scores)
        (stage / "trajectories.jsonl").write_text(
            "".join(trajectory + "\n" for trajectory in serialized_trajectories), encoding="utf-8"
        )

        backups = stage / "backups"
        backups.mkdir()
        for name in names:
            target = output_dir / name
            if target.exists():
                shutil.copy2(target, backups / name)
                existing.add(name)

        for name in names:
            (stage / name).replace(output_dir / name)
            promoted.append(name)
    except Exception as error:
        rollback_errors: list[OSError] = []
        for name in reversed(promoted):
            try:
                if name in existing:
                    (stage / "backups" / name).replace(output_dir / name)
                else:
                    (output_dir / name).unlink()
            except OSError as rollback_error:
                rollback_errors.append(rollback_error)
        if rollback_errors:
            preserve_recovery = True
            raise RuntimeError(
                f"public export rollback incomplete; recovery files preserved at {stage}"
            ) from error
        raise
    finally:
        if not preserve_recovery:
            shutil.rmtree(stage)
