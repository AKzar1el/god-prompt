import csv
import json
import os
from dataclasses import replace
from pathlib import Path
import pytest

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


def test_public_json_artifacts_never_emit_nonstandard_nan_or_infinity(tmp_path: Path):
    # Provider/tool telemetry can carry nonfinite floats, but public JSON is strict.
    export_run(
        tmp_path,
        {'latency': float('nan'), 'nested': {'durations': [float('inf'), 1.25]}},
        [record()],
        [{'events': [{'duration': float('-inf')}, {'duration': 0.0}]}],
    )

    def reject_nonstandard(value: str):
        raise ValueError(f'nonstandard JSON number: {value}')

    manifest = json.loads((tmp_path / 'manifest.json').read_text(encoding='utf-8'),
                          parse_constant=reject_nonstandard)
    trajectory = json.loads((tmp_path / 'trajectories.jsonl').read_text(encoding='utf-8'),
                            parse_constant=reject_nonstandard)
    json.loads((tmp_path / 'summary.json').read_text(encoding='utf-8'),
               parse_constant=reject_nonstandard)
    assert manifest['latency'] is None
    assert manifest['nested']['durations'] == [None, 1.25]
    assert trajectory['events'] == [{'duration': None}, {'duration': 0.0}]


def test_export_serializes_mixed_type_telemetry_mapping_keys(tmp_path: Path):
    # Provider diagnostics may index samples by number alongside named fields.
    export_run(
        tmp_path,
        {'metrics': {1: 'first', 'status': 'ok'}},
        [record()],
        [{'tool_output': {0: 'zero', 'status': 'done'}}],
    )
    manifest = json.loads((tmp_path / 'manifest.json').read_text(encoding='utf-8'))
    trajectory = json.loads((tmp_path / 'trajectories.jsonl').read_text(encoding='utf-8'))
    assert manifest['metrics'] == {'1': 'first', 'status': 'ok'}
    assert trajectory['tool_output'] == {'0': 'zero', 'status': 'done'}


def test_redactor_rejects_ambiguous_mapping_keys_after_stringification():
    with pytest.raises(ValueError, match='ambiguous JSON object key'):
        redact_secrets({1: 'integer', '1': 'string'})


def test_export_overwrites_only_known_files_not_arbitrary_output(tmp_path: Path):
    marker = tmp_path / 'keep.txt'
    marker.write_text('keep')
    export_run(tmp_path, {'run_id': 'r1'}, [record()], [])
    assert marker.read_text() == 'keep'


@pytest.mark.parametrize('filename', ('manifest.json', 'summary.json', 'scores.csv', 'trajectories.jsonl'))
def test_export_refuses_existing_hardlinked_artifact_before_any_write(tmp_path: Path, filename: str):
    output = tmp_path / 'public'
    output.mkdir()
    protected = tmp_path / 'protected.txt'
    protected.write_text('preserve original', encoding='utf-8')
    os.link(protected, output / filename)

    with pytest.raises(ValueError, match='linked public artifact'):
        export_run(output, {'run_id': 'unsafe'}, [record()], [])
    assert protected.read_text(encoding='utf-8') == 'preserve original'
    assert {path.name for path in output.iterdir()} == {filename}


@pytest.mark.parametrize('nested', (False, True))
def test_export_refuses_symlinked_output_directory_or_parent_before_any_write(tmp_path: Path, nested: bool):
    outside = tmp_path / 'outside'
    outside.mkdir()
    link = tmp_path / 'linked-output'
    try:
        os.symlink(outside, link, target_is_directory=True)
    except OSError:
        pytest.skip('directory symlink creation unavailable on this host')

    output = link / 'public' if nested else link
    with pytest.raises(ValueError, match='linked output directory'):
        export_run(output, {'run_id': 'synthetic-only'}, [record()], [])
    assert list(outside.iterdir()) == []


def test_export_allows_replacing_ordinary_unlinked_artifacts(tmp_path: Path):
    export_run(tmp_path, {'run_id': 'old'}, [record()], [])
    export_run(tmp_path, {'run_id': 'new'}, [record()], [])
    assert json.loads((tmp_path / 'manifest.json').read_text(encoding='utf-8'))['run_id'] == 'new'


def test_export_rejects_unknown_conditions_without_creating_public_artifacts(tmp_path: Path):
    output = tmp_path / 'invalid-benchmark'
    invalid = replace(record(), condition='godpromt')
    with pytest.raises(ValueError, match='unknown benchmark condition'):
        export_run(output, {'run_id': 'invalid'}, [invalid], [])
    assert not output.exists()


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


def test_public_exports_redact_credentials_in_json_encoded_diagnostics(tmp_path: Path):
    # Diagnostics often contain JSON as text, sometimes escaped one layer deeper.
    secret = 'SYNTHETIC_JSON_SECRET_EXAMPLE_12345'
    diagnostic = json.dumps({'api_key': secret, 'detail': 'safe'})
    escaped = json.dumps(diagnostic)
    export_run(
        tmp_path,
        {'diagnostic': diagnostic, 'escaped': escaped},
        [replace(record(), infrastructure_error=diagnostic)],
        [{'output': escaped}],
    )
    for name in ('manifest.json', 'scores.csv', 'trajectories.jsonl'):
        assert secret not in (tmp_path / name).read_text(encoding='utf-8'), name
    manifest = json.loads((tmp_path / 'manifest.json').read_text(encoding='utf-8'))
    assert json.loads(manifest['diagnostic']) == {'api_key': '[REDACTED]', 'detail': 'safe'}
    assert json.loads(json.loads(manifest['escaped'])) == {'api_key': '[REDACTED]', 'detail': 'safe'}


def test_public_exports_redact_numeric_credentials_in_json_encoded_diagnostics(tmp_path: Path):
    # Synthetic numeric secrets can appear in JSON logs without surrounding quotes.
    password = 98765432112345
    token = 24681357913579
    diagnostic = json.dumps({'password': password, 'nested': {'access_token': token}, 'attempts': 3})
    escaped = json.dumps(diagnostic)
    export_run(
        tmp_path,
        {'diagnostic': diagnostic, 'escaped': escaped},
        [replace(record(), infrastructure_error=diagnostic)],
        [{'output': escaped}],
    )
    for name in ('manifest.json', 'scores.csv', 'trajectories.jsonl'):
        exported = (tmp_path / name).read_text(encoding='utf-8')
        assert str(password) not in exported, name
        assert str(token) not in exported, name
    manifest = json.loads((tmp_path / 'manifest.json').read_text(encoding='utf-8'))
    expected = {'password': '[REDACTED]', 'nested': {'access_token': '[REDACTED]'}, 'attempts': 3}
    assert json.loads(manifest['diagnostic']) == expected
    assert json.loads(json.loads(manifest['escaped'])) == expected


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


def test_public_exports_redact_api_token_key_variants_and_inline_assignment(tmp_path: Path):
    # These are synthetic values, not credentials. Both structured telemetry
    # keys and free-text diagnostics can use common apiToken spelling.
    tokens = {
        'apiToken': 'syntheticApiValueAlpha42',
        'api_token': 'syntheticApiValueBeta42',
        'api-token': 'syntheticApiValueGamma42',
    }
    diagnostic = 'apiToken=syntheticInlineApiValue42'
    export_run(
        tmp_path,
        {'config': tokens, 'note': diagnostic},
        [replace(record(), infrastructure_error=diagnostic)],
        [{'telemetry': tokens, 'detail': diagnostic}],
    )
    for name in ('manifest.json', 'scores.csv', 'trajectories.jsonl'):
        exported = (tmp_path / name).read_text(encoding='utf-8')
        for secret in (*tokens.values(), 'syntheticInlineApiValue42'):
            assert secret not in exported, (name, secret)
    assert '[REDACTED]' in (tmp_path / 'manifest.json').read_text(encoding='utf-8')


def test_public_exports_redact_spaced_api_key_and_token_labels(tmp_path: Path):
    # Human-readable diagnostics and telemetry keys often spell API Key with a space.
    synthetic_key = 'SYNTHETIC_SPACED_KEY_123'
    synthetic_token = 'SYNTHETIC_SPACED_TOKEN_456'
    diagnostic = f'API Key: {synthetic_key}; API Token={synthetic_token}'
    export_run(
        tmp_path,
        {'API Key': synthetic_key, 'api token': synthetic_token, 'note': diagnostic},
        [replace(record(), infrastructure_error=diagnostic)],
        [{'headers': {'API Key': synthetic_key}, 'output': diagnostic}],
    )
    for name in ('manifest.json', 'scores.csv', 'trajectories.jsonl'):
        output = (tmp_path / name).read_text(encoding='utf-8')
        assert synthetic_key not in output, name
        assert synthetic_token not in output, name
    assert redact_secrets('API key usage is measured') == 'API key usage is measured'


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


def test_public_exports_redact_digest_authorization_parameters(tmp_path: Path):
    # Synthetic Digest challenge responses are credentials, not public telemetry.
    headers = (
        'Authorization: Digest username="FAKE_USER_123", nonce="FAKE_NONCE_456", '
        'uri="/private", response="FAKE_RESPONSE_789"\n'
        'Proxy-Authorization: Digest username="FAKE_PROXY_USER_234", '
        'response="FAKE_PROXY_RESPONSE_567"'
    )
    export_run(
        tmp_path,
        {'note': headers, 'description': 'Digest authentication uses a nonce'},
        [replace(record(), infrastructure_error=headers)],
        [{'output': headers}],
    )
    for filename in ('manifest.json', 'scores.csv', 'trajectories.jsonl'):
        exported = (tmp_path / filename).read_text(encoding='utf-8')
        for secret in (
            'FAKE_USER_123', 'FAKE_NONCE_456', 'FAKE_RESPONSE_789',
            'FAKE_PROXY_USER_234', 'FAKE_PROXY_RESPONSE_567',
        ):
            assert secret not in exported, (filename, secret)
        assert 'Authorization: [REDACTED]' in exported
        assert 'Proxy-Authorization: [REDACTED]' in exported
    manifest = json.loads((tmp_path / 'manifest.json').read_text(encoding='utf-8'))
    assert manifest['description'] == 'Digest authentication uses a nonce'


def test_public_exports_redact_cookie_headers_and_structured_cookie_fields(tmp_path: Path):
    # Synthetic cookie values must not become public benchmark artifacts.
    cookie = 'Cookie: sessionid=FAKE_SESSION_123; csrftoken=FAKE_CSRF_456'
    set_cookie = 'Set-Cookie: sid=FAKE_SET_COOKIE_789; HttpOnly; Secure'
    headers = f'request headers:\n{cookie}\n{set_cookie}\nstatus: 200'
    export_run(
        tmp_path,
        {'note': headers, 'Cookie': 'sid=FAKE_STRUCTURED_987', 'cookie_enabled': True},
        [replace(record(), infrastructure_error=headers)],
        [{'events': [{'output': headers, 'set-cookie': 'sid=FAKE_EVENT_654'}]}],
    )
    for name in ('manifest.json', 'scores.csv', 'trajectories.jsonl'):
        exported = (tmp_path / name).read_text(encoding='utf-8')
        for secret in (
            'FAKE_SESSION_123', 'FAKE_CSRF_456', 'FAKE_SET_COOKIE_789',
            'FAKE_STRUCTURED_987', 'FAKE_EVENT_654',
        ):
            assert secret not in exported, (name, secret)
        assert 'status: 200' in exported
    manifest = json.loads((tmp_path / 'manifest.json').read_text(encoding='utf-8'))
    assert manifest['Cookie'] == '[REDACTED]'
    assert manifest['cookie_enabled'] is True
    assert 'Cookie: [REDACTED]' in manifest['note']
    assert 'Set-Cookie: [REDACTED]' in manifest['note']
    assert redact_secrets('Cookie recipes are popular') == 'Cookie recipes are popular'


def test_public_exports_redact_url_userinfo_credentials(tmp_path: Path):
    db_url = 'postgresql://db-user:FAKEDB123@db.example.invalid:5432/app'
    http_url = 'https://viewer:FAKEWEB456@api.example.invalid/v1'
    redis_url = 'rediss://:FAKEREDIS789@cache.example.invalid:6380/0'
    text = f'connection={db_url} endpoint {http_url} cache {redis_url}'
    export_run(
        tmp_path,
        {'note': text, 'public_url': 'https://api.example.invalid/v1'},
        [replace(record(), infrastructure_error=text)],
        [{'events': [{'output': text}]}],
    )
    for name in ('manifest.json', 'scores.csv', 'trajectories.jsonl'):
        exported = (tmp_path / name).read_text(encoding='utf-8')
        for secret in ('FAKEDB123', 'FAKEWEB456', 'FAKEREDIS789', 'db-user'):
            assert secret not in exported, (name, secret)
        assert exported.count('[REDACTED]@') == 3, name
    manifest = json.loads((tmp_path / 'manifest.json').read_text(encoding='utf-8'))
    assert manifest['public_url'] == 'https://api.example.invalid/v1'
    assert redact_secrets('Contact ops@example.invalid') == 'Contact ops@example.invalid'


@pytest.mark.parametrize('url, expected, secret', (
    ('https://alice@team:FAKEPASS123@api.example.invalid/v1',
     'https://[REDACTED]@api.example.invalid/v1', 'FAKEPASS123'),
    ('postgresql://tenant@org:FAKEDB456@db.example.invalid/app',
     'postgresql://[REDACTED]@db.example.invalid/app', 'FAKEDB456'),
))
def test_public_exports_redact_multiple_at_signs_in_url_userinfo(tmp_path: Path, url: str, expected: str, secret: str):
    assert redact_secrets(url) == expected
    export_run(tmp_path, {'note': url}, [replace(record(), infrastructure_error=url)], [{'output': url}])
    for filename in ('manifest.json', 'scores.csv', 'trajectories.jsonl'):
        exported = (tmp_path / filename).read_text(encoding='utf-8')
        assert secret not in exported, filename
        assert expected in exported, filename


def test_public_exports_redact_signed_url_query_credentials(tmp_path: Path):
    cases = (
        ('https://r2.example.invalid/object?X-Amz-Credential=FAKE_AWS_CRED_123'
         '&X-Amz-Signature=FAKE_AWS_SIG_456&X-Amz-Security-Token=FAKE_AWS_SESSION_789&partNumber=1',
         ('FAKE_AWS_CRED_123', 'FAKE_AWS_SIG_456', 'FAKE_AWS_SESSION_789'),
         ('X-Amz-Credential', 'X-Amz-Signature', 'X-Amz-Security-Token')),
        ('https://gcs.example.invalid/object?X-Goog-Credential=FAKE_GOOG_CRED_123'
         '&X-Goog-Signature=FAKE_GOOG_SIG_456&partNumber=1',
         ('FAKE_GOOG_CRED_123', 'FAKE_GOOG_SIG_456'),
         ('X-Goog-Credential', 'X-Goog-Signature')),
        ('https://blob.example.invalid/file?sv=2024-01-01&sig=FAKE_AZURE_SIG_123&partNumber=1',
         ('FAKE_AZURE_SIG_123',), ('sig',)),
        ('https://s3.example.invalid/object?AWSAccessKeyId=FAKE_AWS_V2_KEY_123'
         '&Signature=FAKE_AWS_V2_SIG_456&partNumber=1',
         ('FAKE_AWS_V2_KEY_123', 'FAKE_AWS_V2_SIG_456'), ('AWSAccessKeyId', 'Signature')),
        ('https://storage.example.invalid/object?GoogleAccessId=FAKE_GCS_V2_ID_123'
         '&Signature=FAKE_GCS_V2_SIG_456&partNumber=1',
         ('FAKE_GCS_V2_ID_123', 'FAKE_GCS_V2_SIG_456'), ('GoogleAccessId', 'Signature')),
    )
    for i, (url, secrets, names) in enumerate(cases):
        directory = tmp_path / str(i)
        export_run(directory,
                   {'note': url, 'public_url': 'https://public.example.invalid/obj?partNumber=1'},
                   [replace(record(), infrastructure_error=url)],
                   [{'events': [{'output': url}]}])
        for filename in ('manifest.json', 'scores.csv', 'trajectories.jsonl'):
            text = (directory / filename).read_text(encoding='utf-8')
            assert all(secret not in text for secret in secrets), filename
            for name in names:
                assert f'{name}=[REDACTED]' in text, (filename, name)
            assert 'partNumber=1' in text
        manifest = json.loads((directory / 'manifest.json').read_text(encoding='utf-8'))
        assert manifest['public_url'] == 'https://public.example.invalid/obj?partNumber=1'


def test_public_exports_redact_structured_signed_url_keys():
    fields = {
        'X-Amz-Signature': 'FAKE_AWS_SIG', 'X-Goog-Credential': 'FAKE_GOOG_CRED',
        'sig': 'FAKE_AZURE_SIG', 'AWSAccessKeyId': 'FAKE_AWS_V2_ID',
        'GoogleAccessId': 'FAKE_GCS_V2_ID', 'Signature': 'FAKE_V2_SIG',
    }
    assert redact_secrets(fields) == {name: '[REDACTED]' for name in fields}


def test_public_exports_redact_percent_encoded_query_parameter_names(tmp_path: Path):
    url = (
        'https://storage.example.invalid/object?api%5Fkey=FAKE_API_KEY_123'
        '&X-Amz%2DSignature=FAKE_AWS_SIG_456'
        '&session%5Ftoken=FAKE_SESSION_789'
        '&part%5Fnumber=7'
    )
    expected = (
        'https://storage.example.invalid/object?api%5Fkey=[REDACTED]'
        '&X-Amz%2DSignature=[REDACTED]'
        '&session%5Ftoken=[REDACTED]'
        '&part%5Fnumber=7'
    )
    assert redact_secrets(url) == expected
    export_run(tmp_path, {'note': url},
               [replace(record(), infrastructure_error=url)],
               [{'events': [{'output': url}]}])
    for name in ('manifest.json', 'scores.csv', 'trajectories.jsonl'):
        exported = (tmp_path / name).read_text(encoding='utf-8')
        assert all(secret not in exported for secret in (
            'FAKE_API_KEY_123', 'FAKE_AWS_SIG_456', 'FAKE_SESSION_789'
        )), name
        assert 'part%5Fnumber=7' in exported


def test_public_exports_redact_html_escaped_signed_url_query(tmp_path: Path):
    # HTML attribute values can encode query separators as &amp;.
    url = (
        'https://storage.example.invalid/object?partNumber=1'
        '&amp;X-Amz-Signature=FAKE_HTML_AWS_SIG_123'
        '&amp;X-Goog-Credential=FAKE_HTML_GCS_CRED_456'
        '&amp;sig=FAKE_HTML_AZURE_SIG_789'
    )
    export_run(
        tmp_path, {'note': url},
        [replace(record(), infrastructure_error=url)],
        [{'output': url}],
    )
    for filename in ('manifest.json', 'scores.csv', 'trajectories.jsonl'):
        exported = (tmp_path / filename).read_text(encoding='utf-8')
        assert 'FAKE_HTML_' not in exported, filename
        for name in ('X-Amz-Signature', 'X-Goog-Credential', 'sig'):
            assert f'&amp;{name}=[REDACTED]' in exported, (filename, name)
        assert 'partNumber=1' in exported


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


def test_public_exports_redact_aws_access_key_identifiers(tmp_path: Path):
    # Made-up identifiers only; an access key ID is credential material too.
    fake_access_key_id = 'AKIASYNTHETICONLY1234'
    export_run(
        tmp_path,
        {
            'note': f'AWS_ACCESS_KEY_ID={fake_access_key_id}',
            'aws_access_key_id': fake_access_key_id,
            'aws_account_id': '123456789012',
        },
        [replace(record(), infrastructure_error=f'accessKeyId: {fake_access_key_id}')],
        [{'events': [{'accessKeyId': fake_access_key_id}]}],
    )
    for filename in ('manifest.json', 'scores.csv', 'trajectories.jsonl'):
        assert fake_access_key_id not in (tmp_path / filename).read_text(encoding='utf-8')
    manifest = json.loads((tmp_path / 'manifest.json').read_text(encoding='utf-8'))
    assert manifest['aws_access_key_id'] == '[REDACTED]'
    assert manifest['aws_account_id'] == '123456789012'


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


def test_public_exports_redact_token_auth_schemes_and_credential_bearing_keys(tmp_path: Path):
    # Synthetic strings only: neither header values nor dynamic JSON keys may publish credentials.
    header_token = 'FAKE_HEADER_TOKEN_123'
    proxy_token = 'FAKE_PROXY_TOKEN_456'
    embedded_key = 'FAKE_KEY_VALUE_789'
    headers = f'Authorization: Token {header_token}; Proxy-Authorization: ApiKey {proxy_token}'
    export_run(
        tmp_path,
        {'note': headers, f'request token={embedded_key}': {'safe': 'public'}},
        [replace(record(), infrastructure_error=headers)],
        [{'events': [{f'header api_key={embedded_key}': 'public', 'output': headers}]}],
    )
    for filename in ('manifest.json', 'scores.csv', 'trajectories.jsonl'):
        text = (tmp_path / filename).read_text(encoding='utf-8')
        for secret in (header_token, proxy_token, embedded_key):
            assert secret not in text, (filename, secret)
    manifest = json.loads((tmp_path / 'manifest.json').read_text(encoding='utf-8'))
    assert manifest['note'] == 'Authorization: [REDACTED]; Proxy-Authorization: [REDACTED]'
    assert manifest['request token=[REDACTED]'] == {'safe': 'public'}


def test_public_exports_redact_signature_auth_headers_without_losing_peer_headers(tmp_path: Path):
    # Credentials are synthetic; SigV4 and Hawk headers carry secrets after the scheme.
    headers = (
        'Authorization: AWS4-HMAC-SHA256 Credential=FAKE_AWS_KEY_123/region/service, '
        'SignedHeaders=host, Signature=FAKE_SIG_456; '
        'Proxy-Authorization: Hawk id="FAKE_HAWK_ID_789", mac="FAKE_HAWK_MAC_987"\n'
        'X-Request-ID: public-id'
    )
    export_run(
        tmp_path,
        {'note': headers},
        [replace(record(), infrastructure_error=headers)],
        [{'output': headers}],
    )
    for filename in ('manifest.json', 'scores.csv', 'trajectories.jsonl'):
        text = (tmp_path / filename).read_text(encoding='utf-8')
        assert not any(secret in text for secret in (
            'FAKE_AWS_KEY_123', 'FAKE_SIG_456', 'FAKE_HAWK_ID_789', 'FAKE_HAWK_MAC_987',
        )), filename
    note = json.loads((tmp_path / 'manifest.json').read_text(encoding='utf-8'))['note']
    assert note == ('Authorization: [REDACTED]; Proxy-Authorization: [REDACTED]\n'
                    'X-Request-ID: public-id')

def test_public_exports_redact_camel_case_auth_tokens_in_text_and_metadata(tmp_path: Path):
    fake_auth = 'FAKE_AUTH_TOKEN_VALUE_123'
    fake_oauth = 'FAKE_OAUTH_TOKEN_VALUE_456'
    fake_client = 'FAKE_CLIENT_TOKEN_VALUE_789'
    note = f'authToken={fake_auth} oauthToken: {fake_oauth} clientToken="{fake_client}"'
    export_run(
        tmp_path,
        {'authToken': fake_auth, 'oauthToken': fake_oauth, 'token_count': 3, 'note': note},
        [replace(record(), infrastructure_error=note)],
        [{'clientToken': fake_client, 'message': note}],
    )
    for name in ('manifest.json', 'trajectories.jsonl', 'scores.csv'):
        exported = (tmp_path / name).read_text(encoding='utf-8')
        assert all(value not in exported for value in (fake_auth, fake_oauth, fake_client)), name
        assert '[REDACTED]' in exported
    manifest = json.loads((tmp_path / 'manifest.json').read_text(encoding='utf-8'))
    assert manifest['authToken'] == '[REDACTED]'
    assert manifest['oauthToken'] == '[REDACTED]'
    assert manifest['token_count'] == 3


def test_public_exports_redact_inline_secret_aliases_without_masking_counts(tmp_path: Path):
    secrets = ('FAKE_CLIENT_SECRET_123', 'FAKE_API_SECRET_456', 'FAKE_ACCESS_KEY_789')
    note = (
        f'clientSecret={secrets[0]} apiSecret: {secrets[1]} '
        f'accessKey="{secrets[2]}" accessKeyCount=3'
    )
    export_run(
        tmp_path,
        {'note': note, 'clientSecret': secrets[0], 'accessKey': secrets[2],
         'accessKeyIdentifier': secrets[2], 'accessKeyCount': 3},
        [replace(record(), infrastructure_error=note)],
        [{'output': note}],
    )
    for filename in ('manifest.json', 'scores.csv', 'trajectories.jsonl'):
        exported = (tmp_path / filename).read_text(encoding='utf-8')
        assert all(secret not in exported for secret in secrets), filename
        assert 'accessKeyCount=3' in exported
    manifest = json.loads((tmp_path / 'manifest.json').read_text(encoding='utf-8'))
    assert manifest['clientSecret'] == '[REDACTED]'
    assert manifest['accessKey'] == '[REDACTED]'
    assert manifest['accessKeyIdentifier'] == '[REDACTED]'
    assert manifest['accessKeyCount'] == 3
