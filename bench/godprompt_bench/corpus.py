from __future__ import annotations

import json
from pathlib import Path, PurePosixPath

from dataclasses import dataclass

from .models import TaskSpec

CATEGORIES = {
    "implementation",
    "debugging",
    "refactor",
    "scope-control",
    "verification",
    "tool-discipline",
}
RUNTIMES = {"python", "javascript"}


def _tuple(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{field} must be a list of strings")
    return tuple(value)


def load_manifest(path: Path) -> list[TaskSpec]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("manifest root must be a list")
    tasks: list[TaskSpec] = []
    required = {
        "id",
        "category",
        "runtime",
        "fixture_dir",
        "user_prompt",
        "verifier_command",
        "allowed_paths",
    }
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"task {index} must be an object")
        missing = required - item.keys()
        if missing:
            raise ValueError(f"task {index} missing fields: {sorted(missing)}")
        tasks.append(
            TaskSpec(
                id=str(item["id"]),
                category=str(item["category"]),
                runtime=str(item["runtime"]),
                fixture_dir=str(item["fixture_dir"]),
                user_prompt=str(item["user_prompt"]),
                verifier_command=_tuple(item["verifier_command"], "verifier_command"),
                allowed_paths=_tuple(item["allowed_paths"], "allowed_paths"),
                forbidden_paths=_tuple(item.get("forbidden_paths", []), "forbidden_paths"),
                expected_verification_commands=_tuple(
                    item.get("expected_verification_commands", []),
                    "expected_verification_commands",
                ),
            )
        )
    return tasks


def _validate_relative(path: str, field: str, task_id: str) -> None:
    parsed = PurePosixPath(path)
    if parsed.is_absolute() or ".." in parsed.parts:
        raise ValueError(f"{task_id}: {field} must be a safe relative path")


def validate_manifest(tasks: list[TaskSpec]) -> None:
    seen: set[str] = set()
    for task in tasks:
        if not task.id.strip():
            raise ValueError("task id must not be empty")
        if task.id in seen:
            raise ValueError(f"duplicate task id: {task.id}")
        seen.add(task.id)
        if task.category not in CATEGORIES:
            raise ValueError(f"{task.id}: unknown category {task.category}")
        if task.runtime not in RUNTIMES:
            raise ValueError(f"{task.id}: unknown runtime {task.runtime}")
        if not task.user_prompt.strip():
            raise ValueError(f"{task.id}: user_prompt must not be empty")
        if not task.verifier_command:
            raise ValueError(f"{task.id}: verifier_command must not be empty")
        if not task.allowed_paths:
            raise ValueError(f"{task.id}: allowed_paths must not be empty")
        _validate_relative(task.fixture_dir, "fixture_dir", task.id)
        for path in (*task.allowed_paths, *task.forbidden_paths):
            _validate_relative(path, "workspace path", task.id)


@dataclass(frozen=True)
class FixtureBundle:
    files: dict[str, str]
    hidden_verifier: str
    starter_expected_pass: bool


def load_fixture_bundle(path: Path) -> FixtureBundle:
    raw = json.loads(path.read_text(encoding="utf-8"))
    files = raw.get("files")
    verifier = raw.get("hidden_verifier")
    expected = raw.get("starter_expected_pass")
    if not isinstance(files, dict) or not files or not all(isinstance(k, str) and isinstance(v, str) for k, v in files.items()):
        raise ValueError("fixture files must be a non-empty string map")
    for relative in files:
        _validate_relative(relative, "fixture file", path.parent.name)
    if not isinstance(verifier, str) or not verifier.strip():
        raise ValueError("fixture hidden_verifier must be non-empty")
    if not isinstance(expected, bool):
        raise ValueError("fixture starter_expected_pass must be boolean")
    return FixtureBundle(files=dict(files), hidden_verifier=verifier, starter_expected_pass=expected)
