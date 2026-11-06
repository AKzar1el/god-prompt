import csv
import json
from dataclasses import replace
from pathlib import Path

from godprompt_bench.export import export_run, redact_secrets
from godprompt_bench.models import SampleRecord


def record():
    return SampleRecord(
        task_id='impl-py-slugify', category='implementation', condition='baseline', epoch=1,
        passed=True, completion_status='complete', false_completion=False, scope_violation=False,
        tool_misuse_count=0, verification_attempts=1, failed_tool_calls=0, retries=0,
        input_tokens=10, output_tokens=5, latency_seconds=1.25, infrastructure_error=None,
    )


def test_export_writes_exact_public_artifact_set_and_redacts_secrets(tmp_path: Path):
    export_run(
        tmp_path,
        {'run_id': 'r1', 'api_key': 'secret-value', 'nested': {'Authorization': 'Bearer nope'}},
        [record()],
        [{'task_id': 'impl-py-slugify', 'events': [{'tool': 'bash', 'access_token': 'nope'}]}],
    )
    assert {p.name for p in tmp_path.iterdir()} == {
        'manifest.json', 'summary.json', 'scores.csv', 'trajectories.jsonl'
    }
    manifest = json.loads((tmp_path / 'manifest.json').read_text())
    assert manifest['api_key'] == '[REDACTED]'
    assert manifest['nested']['Authorization'] == '[REDACTED]'
    trajectory = json.loads((tmp_path / 'trajectories.jsonl').read_text().strip())
    assert trajectory['events'][0]['access_token'] == '[REDACTED]'
    rows = list(csv.DictReader((tmp_path / 'scores.csv').open(newline='', encoding='utf-8')))
    assert rows[0]['task_id'] == 'impl-py-slugify'
    summary = json.loads((tmp_path / 'summary.json').read_text())
    assert summary['baseline']['passed'] == 1


def test_export_overwrites_only_known_files_not_arbitrary_output(tmp_path: Path):
    marker = tmp_path / 'keep.txt'
    marker.write_text('keep')
    export_run(tmp_path, {'run_id': 'r1'}, [record()], [])
    assert marker.read_text() == 'keep'


def test_export_quotes_formula_like_csv_text_without_changing_numeric_fields(tmp_path: Path):
    malicious = replace(record(), task_id='=HYPERLINK("https://example.invalid")', completion_status='  @SUM(1)', infrastructure_error='\t+1+1')
    export_run(tmp_path, {'run_id': 'safe'}, [malicious], [])
    with (tmp_path / 'scores.csv').open(newline='', encoding='utf-8') as handle:
        row = next(csv.DictReader(handle))
    assert row['task_id'] == "'" + malicious.task_id
    assert row['completion_status'] == "'" + malicious.completion_status
    assert row['infrastructure_error'] == "'" + malicious.infrastructure_error
    assert row['epoch'] == '1'
    assert row['passed'] == 'True'


def test_export_leaves_normal_csv_text_unchanged(tmp_path: Path):
    export_run(tmp_path, {'run_id': 'normal'}, [record()], [])
    with (tmp_path / 'scores.csv').open(newline='', encoding='utf-8') as handle:
        row = next(csv.DictReader(handle))
    assert row['task_id'] == 'impl-py-slugify'
    assert row['completion_status'] == 'complete'


def test_public_artifacts_redact_credentials_embedded_in_text_values(tmp_path: Path):
    """A secret inside an innocent-looking message/error key must not leak."""
    synthetic_key = 'sk-proj-EXAMPLEONLY1234567890'
    synthetic_bearer = 'syntheticBearer1234567890'
    synthetic_github = 'ghp_SYNTHETICEXAMPLE1234567890'
    source = {
        'run_id': 'test',
        'note': f'OPENAI_API_KEY={synthetic_key} and Authorization: Bearer {synthetic_bearer}',
    }
    trajectory = {
        'task_id': 'fixture',
        'messages': [{'role': 'assistant', 'content': f'Bearer {synthetic_bearer}'}],
        'events': [{'output': f'GITHUB_TOKEN: {synthetic_github}'}],
    }
    damaged = replace(record(), infrastructure_error=f'failed with token={synthetic_key}; gh={synthetic_github}')
    export_run(tmp_path, source, [damaged], [trajectory])

    for name in ('manifest.json', 'trajectories.jsonl', 'scores.csv'):
        text = (tmp_path / name).read_text(encoding='utf-8')
        for secret in (synthetic_key, synthetic_bearer, synthetic_github):
            assert secret not in text, (name, secret)
    assert '[REDACTED]' in (tmp_path / 'scores.csv').read_text(encoding='utf-8')
    assert 'failed with token=' in (tmp_path / 'scores.csv').read_text(encoding='utf-8')


def test_public_exports_redact_short_bearer_credentials(tmp_path: Path):
    # Bearer tokens need not be eight characters long to be credentials.
    synthetic_token = 'abc123'
    text = f'Bearer {synthetic_token}'
    export_run(
        tmp_path,
        {'note': text},
        [replace(record(), infrastructure_error=text)],
        [{'output': text}],
    )
    for name in ('manifest.json', 'scores.csv', 'trajectories.jsonl'):
        exported = (tmp_path / name).read_text(encoding='utf-8')
        assert synthetic_token not in exported, name
        assert 'Bearer [REDACTED]' in exported, name


def test_public_exports_redact_http_basic_authorization_payloads(tmp_path: Path):
    # Base64 payloads are synthetic test values, never live credentials.
    encoded_user = 'dXNlcjp0ZXN0LW9ubHk='
    encoded_proxy = 'cHJveHk6dGVzdC1vbmx5'
    headers = f'Authorization: Basic {encoded_user}; Proxy-Authorization=basic {encoded_proxy}'
    export_run(
        tmp_path,
        {'note': headers, 'description': 'Basic authentication is documented'},
        [replace(record(), infrastructure_error=headers)],
        [{'events': [{'output': headers}]}],
    )
    for name in ('manifest.json', 'scores.csv', 'trajectories.jsonl'):
        exported = (tmp_path / name).read_text(encoding='utf-8')
        assert encoded_user not in exported, name
        assert encoded_proxy not in exported, name
        assert '[REDACTED]' in exported, name
    manifest = json.loads((tmp_path / 'manifest.json').read_text(encoding='utf-8'))
    assert manifest['description'] == 'Basic authentication is documented'


def test_public_exports_redact_provider_prefixed_environment_secrets(tmp_path: Path):
    # All values are made-up placeholders, not credentials; plain text must still be sanitized.
    entries = (
        ('OPENAI_API_KEY', 'FAKE_OPENAI_VALUE_123'),
        ('ANTHROPIC_API_KEY', 'FAKE_ANTHROPIC_VALUE_234'),
        ('AWS_SECRET_ACCESS_KEY', 'FAKE_AWS_VALUE_345'),
        ('POSTGRES_PASSWORD', 'FAKE_DATABASE_VALUE_456'),
        ('CLOUDFLARE_API_TOKEN', 'FAKE_CLOUDFLARE_VALUE_567'),
    )
    text = ' '.join(f'{key}={value}' for key, value in entries)
    export_run(
        tmp_path,
        {'run_id': 'synthetic-only', 'note': text},
        [replace(record(), infrastructure_error=text)],
        [{'events': [{'output': text}]}],
    )
    for name in ('manifest.json', 'scores.csv', 'trajectories.jsonl'):
        exported = (tmp_path / name).read_text(encoding='utf-8')
        assert '[REDACTED]' in exported
        for key, value in entries:
            assert value not in exported, (name, key)
            assert key in exported
    assert redact_secrets('USER_NAME=example TOKENIZER=bert') == 'USER_NAME=example TOKENIZER=bert'


def test_public_exports_redact_structured_session_tokens_and_private_keys(tmp_path: Path):
    # Synthetic placeholders expose sensitive key-name gaps without using real credentials.
    fake_values = ('FAKE_SESSION_678', 'FAKE_ID_TOKEN_987', 'FAKE_PRIVATE_123', 'FAKE_AUTH_456')
    source = {
        'session_token': fake_values[0],
        'nested': {'id_token': fake_values[1], 'privateKey': fake_values[2]},
        'tokenizer': 'bert',
        'token_count': 17,
    }
    trajectory = {'events': [{'token': fake_values[3], 'token_count': 3}]}
    export_run(tmp_path, source, [record()], [trajectory])

    manifest = json.loads((tmp_path / 'manifest.json').read_text(encoding='utf-8'))
    event = json.loads((tmp_path / 'trajectories.jsonl').read_text(encoding='utf-8'))['events'][0]
    assert manifest['session_token'] == '[REDACTED]'
    assert manifest['nested'] == {'id_token': '[REDACTED]', 'privateKey': '[REDACTED]'}
    assert event == {'token': '[REDACTED]', 'token_count': 3}
    assert manifest['tokenizer'] == 'bert'
    assert manifest['token_count'] == 17
    for name in ('manifest.json', 'trajectories.jsonl'):
        exported = (tmp_path / name).read_text(encoding='utf-8')
        assert not any(value in exported for value in fake_values)
