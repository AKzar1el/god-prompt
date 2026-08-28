from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_sandbox_is_network_isolated_and_version_pinned():
    dockerfile = (ROOT / 'sandbox' / 'Dockerfile').read_text(encoding='utf-8')
    compose = (ROOT / 'sandbox' / 'compose.yaml').read_text(encoding='utf-8')
    assert 'node:22.18.0-bookworm-slim' in dockerfile
    assert 'python3' in dockerfile
    assert 'network_mode: none' in compose
    assert 'working_dir: /workspace' in compose


def test_sandbox_runs_as_unprivileged_user_with_reduced_privileges():
    dockerfile = (ROOT / 'sandbox' / 'Dockerfile').read_text(encoding='utf-8')
    compose = (ROOT / 'sandbox' / 'compose.yaml').read_text(encoding='utf-8')
    assert 'USER bench' in dockerfile
    assert 'cap_drop:' in compose and '- ALL' in compose
    assert 'no-new-privileges:true' in compose
