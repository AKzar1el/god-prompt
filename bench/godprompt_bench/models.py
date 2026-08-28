from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TaskSpec:
    id: str
    category: str
    runtime: str
    fixture_dir: str
    user_prompt: str
    verifier_command: tuple[str, ...]
    allowed_paths: tuple[str, ...]
    forbidden_paths: tuple[str, ...] = ()
    expected_verification_commands: tuple[str, ...] = ()


@dataclass(frozen=True)
class RunProfile:
    name: str
    task_ids: tuple[str, ...]
    epochs: int
    max_messages: int
    max_time_seconds: int
    max_output_tokens: int


@dataclass(frozen=True)
class SampleRecord:
    task_id: str
    category: str
    condition: str
    epoch: int
    passed: bool
    completion_status: str
    false_completion: bool
    scope_violation: bool
    tool_misuse_count: int
    verification_attempts: int
    failed_tool_calls: int
    retries: int
    input_tokens: int | None
    output_tokens: int | None
    latency_seconds: float | None
    infrastructure_error: str | None
