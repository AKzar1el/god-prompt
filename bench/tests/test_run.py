import hashlib
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from godprompt_bench.run import execute_benchmark, load_profile, public_trajectory, sample_record, validate_sample_coverage, fixture_fingerprints, condition_batches, build_manifest, _condition_for_log
from godprompt_bench.models import RunProfile

ROOT = Path(__file__).parents[1]


@pytest.mark.parametrize('from_repo_root', (False, True))
def test_main_default_output_is_bench_results_from_any_working_directory(monkeypatch, from_repo_root):
    import sys
    import godprompt_bench.run as run_module

    captured = []
    monkeypatch.chdir(ROOT.parent if from_repo_root else ROOT)
    monkeypatch.setattr(sys, 'argv', ['godprompt-bench', '--model', 'mockllm/model'])
    monkeypatch.setattr(
        run_module,
        'execute_benchmark',
        lambda *args, **kwargs: captured.append(kwargs['output_dir']) or Path('mock-result'),
    )

    run_module.main()

    assert captured == [ROOT / 'results']


def test_main_preserves_explicit_relative_output_directory(monkeypatch, tmp_path):
    import sys
    import godprompt_bench.run as run_module

    captured = []
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, 'argv', ['godprompt-bench', '--model', 'mockllm/model', '--output', 'my-results'])
    monkeypatch.setattr(
        run_module,
        'execute_benchmark',
        lambda *args, **kwargs: captured.append(kwargs['output_dir']) or Path('mock-result'),
    )

    run_module.main()

    assert captured == [Path('my-results')]


def test_cli_dry_run_reports_offline_plan_without_executing_or_writing(monkeypatch, capsys, tmp_path):
    import godprompt_bench.run as run_module

    output_dir = tmp_path / 'not-created'
    monkeypatch.setattr(sys, 'argv', [
        'godprompt_bench.run', '--profile', 'smoke', '--model', 'mockllm/test',
        '--output', str(output_dir), '--dry-run',
    ])
    monkeypatch.setattr(run_module, 'execute_benchmark',
                        lambda *args, **kwargs: pytest.fail('dry run must not execute a model'))

    run_module.main()
    plan = json.loads(capsys.readouterr().out)
    assert plan['preview_only'] is True
    assert plan['profile'] == 'smoke'
    assert plan['model'] == 'mockllm/test'
    assert plan['tasks_per_condition'] == 6
    assert plan['planned_samples'] == 12
    assert sum(plan['categories'].values()) == 6
    assert len(plan['fixture_bundles_sha256']) == 64
    assert plan['cost_estimate_usd'] is None
    assert not output_dir.exists()


def test_preview_plan_fingerprint_is_stable_and_binds_run_controls():
    from godprompt_bench.run import preview_benchmark

    profile = load_profile(ROOT / 'configs' / 'smoke.json')
    plan = preview_benchmark(ROOT, profile, model='mockllm/test', seed=42)
    assert len(plan['plan_sha256']) == 64
    assert plan['plan_sha256'] == preview_benchmark(
        ROOT, profile, model='mockllm/test', seed=42,
    )['plan_sha256']
    assert plan['plan_sha256'] != preview_benchmark(
        ROOT, profile, model='mockllm/other', seed=42,
    )['plan_sha256']
    assert plan['plan_sha256'] != preview_benchmark(
        ROOT, profile, model='mockllm/test', seed=43,
    )['plan_sha256']
    changed_profile = RunProfile(
        name=profile.name, task_ids=profile.task_ids,
        epochs=profile.epochs, max_messages=profile.max_messages + 1,
        max_time_seconds=profile.max_time_seconds,
        max_output_tokens=profile.max_output_tokens,
    )
    assert plan['plan_sha256'] != preview_benchmark(
        ROOT, changed_profile, model='mockllm/test', seed=42,
    )['plan_sha256']


def test_preview_plan_fingerprint_binds_godprompt_source(monkeypatch):
    import godprompt_bench.run as run_module

    profile = load_profile(ROOT / 'configs' / 'smoke.json')
    before = run_module.preview_benchmark(ROOT, profile, model='mockllm/test')['plan_sha256']
    original_hash = run_module._sha256
    monkeypatch.setattr(run_module, '_sha256', lambda path:
                        'f' * 64 if path.name == 'GodPrompt.md' else original_hash(path))
    after = run_module.preview_benchmark(ROOT, profile, model='mockllm/test')['plan_sha256']
    assert before != after


def test_cli_required_plan_fingerprint_fails_before_model_on_mismatch(monkeypatch, capsys):
    import godprompt_bench.run as run_module

    monkeypatch.setattr(sys, 'argv', [
        'godprompt_bench.run', '--profile', 'smoke', '--model', 'mockllm/test',
        '--require-plan-sha256', '0' * 64,
    ])
    monkeypatch.setattr(run_module, 'execute_benchmark',
                        lambda *args, **kwargs: pytest.fail('mismatched plan ran a model'))
    with pytest.raises(SystemExit) as exc:
        run_module.main()
    assert exc.value.code == 2
    assert 'plan fingerprint mismatch' in capsys.readouterr().err


@pytest.mark.parametrize('invalid_sha', ('not-a-sha', 'A' * 64))
def test_cli_required_plan_fingerprint_rejects_malformed_input_without_model(
    monkeypatch, capsys, invalid_sha,
):
    import godprompt_bench.run as run_module

    monkeypatch.setattr(sys, 'argv', [
        'godprompt_bench.run', '--model', 'mockllm/test',
        '--require-plan-sha256', invalid_sha,
    ])
    monkeypatch.setattr(run_module, 'execute_benchmark',
                        lambda *args, **kwargs: pytest.fail('invalid plan ran a model'))
    with pytest.raises(SystemExit) as exc:
        run_module.main()
    assert exc.value.code == 2
    assert '64 lowercase hexadecimal characters' in capsys.readouterr().err


def test_cli_required_matching_plan_fingerprint_allows_existing_run(monkeypatch, capsys):
    import godprompt_bench.run as run_module

    approved = run_module.preview_benchmark(
        ROOT, load_profile(ROOT / 'configs' / 'smoke.json'),
        model='mockllm/test', seed=42,
    )['plan_sha256']
    captured = []
    monkeypatch.setattr(sys, 'argv', [
        'godprompt_bench.run', '--profile', 'smoke', '--model', 'mockllm/test',
        '--seed', '42', '--require-plan-sha256', approved,
    ])
    monkeypatch.setattr(run_module, 'execute_benchmark',
                        lambda *args, **kwargs: captured.append(kwargs) or Path('mock-only'))
    run_module.main()
    assert len(captured) == 1
    assert captured[0]['seed'] == 42
    assert 'mock-only' in capsys.readouterr().out


def test_cli_experimental_mcp_arm_is_opt_in_offline_and_preserves_reference(monkeypatch, capsys, tmp_path):
    import godprompt_bench.run as run_module

    output_dir = tmp_path / 'never-written'
    monkeypatch.setattr(sys, 'argv', [
        'godprompt_bench.run', '--profile', 'smoke', '--model', 'mockllm/test',
        '--dry-run', '--experimental-mcp-contract', '--output', str(output_dir),
    ])
    monkeypatch.setattr(run_module, 'execute_benchmark',
                        lambda *args, **kwargs: pytest.fail('experimental preview ran a model'))
    run_module.main()
    preview = json.loads(capsys.readouterr().out)
    assert preview['preview_only'] is True
    assert preview['plan_sha256'] is None
    assert preview['conditions'] == ['baseline', 'godprompt']
    assert preview['planned_samples'] == 12
    extra = preview['experimental_arm']
    assert extra['name'] == 'godprompt_mcp_contract'
    assert extra['planned_additional_samples'] == 6
    assert extra['reference_conditions_unchanged'] is True
    assert extra['live_execution_enabled'] is False
    assert extra['requires_separate_provider_spend_approval'] is True
    assert len(extra['mcp_release_sha']) == 40
    assert not output_dir.exists()


def test_cli_experimental_mcp_arm_refuses_live_model_even_with_explicit_model(monkeypatch, capsys):
    import godprompt_bench.run as run_module

    monkeypatch.setattr(sys, 'argv', [
        'godprompt_bench.run', '--experimental-mcp-contract', '--model', 'mockllm/test',
    ])
    monkeypatch.setattr(run_module, 'execute_benchmark',
                        lambda *args, **kwargs: pytest.fail('experimental arm must be blocked'))
    with pytest.raises(SystemExit) as exc:
        run_module.main()
    assert exc.value.code == 2
    assert 'requires --dry-run' in capsys.readouterr().err


def test_cli_experimental_mcp_arm_markdown_discloses_gate(monkeypatch, capsys):
    import godprompt_bench.run as run_module

    monkeypatch.setattr(sys, 'argv', [
        'godprompt_bench.run', '--dry-run', '--experimental-mcp-contract',
        '--format', 'markdown',
    ])
    monkeypatch.setattr(run_module, 'execute_benchmark',
                        lambda *args, **kwargs: pytest.fail('markdown preview ran a model'))
    run_module.main()
    text = capsys.readouterr().out
    assert 'Experimental MCP task-contract arm (preview only)' in text
    assert 'No live-run plan SHA is offered' in text
    assert 'Live execution is disabled' in text
    assert 'Reference baseline and GodPrompt conditions are unchanged' in text


def test_cli_dry_run_without_model_previews_fixtures_offline(monkeypatch, capsys, tmp_path):
    import godprompt_bench.run as run_module

    output_dir = tmp_path / 'never-created'
    monkeypatch.setattr(sys, 'argv', [
        'godprompt_bench.run', '--profile', 'smoke', '--output', str(output_dir), '--dry-run',
    ])
    monkeypatch.setattr(run_module, 'execute_benchmark',
                        lambda *args, **kwargs: pytest.fail('preview must not execute the evaluator'))

    run_module.main()
    plan = json.loads(capsys.readouterr().out)
    assert plan['preview_only'] is True
    assert plan['model'] is None
    assert plan['planned_samples'] == 12
    assert len(plan['fixture_bundles_sha256']) == 64
    assert not output_dir.exists()


def _custom_profile_file(tmp_path, *, name='one-off', task_count=2, epochs=1, max_output_tokens=4096):
    profile = json.loads((ROOT / 'configs' / 'smoke.json').read_text(encoding='utf-8'))
    profile.update(name=name, task_ids=profile['task_ids'][:task_count],
                   epochs=epochs, max_output_tokens=max_output_tokens)
    path = tmp_path / 'local-profile.json'
    path.write_text(json.dumps(profile), encoding='utf-8')
    return path


def test_cli_custom_profile_preview_and_task_list_are_offline(monkeypatch, capsys, tmp_path):
    import godprompt_bench.run as run_module

    path = _custom_profile_file(tmp_path)
    output = tmp_path / 'never-created'
    monkeypatch.setattr(run_module, 'execute_benchmark',
                        lambda *args, **kwargs: pytest.fail('custom preview must not run models'))
    monkeypatch.setattr(sys, 'argv', [
        'godprompt_bench.run', '--profile-file', str(path), '--dry-run',
        '--output', str(output),
    ])
    run_module.main()
    plan = json.loads(capsys.readouterr().out)
    assert plan['profile'] == 'custom-one-off'
    assert plan['tasks_per_condition'] == 2
    assert plan['planned_samples'] == 4
    assert not output.exists()

    monkeypatch.setattr(sys, 'argv', [
        'godprompt_bench.run', '--profile-file', str(path), '--list-tasks',
    ])
    run_module.main()
    tasks = json.loads(capsys.readouterr().out)
    assert tasks['profile'] == 'custom'
    assert tasks['profile_id'] == 'custom-one-off'
    assert len(tasks['tasks']) == 2
    assert not output.exists()


def test_cli_custom_profile_live_requires_model_and_preserves_selected_limits(
    monkeypatch, capsys, tmp_path,
):
    import godprompt_bench.run as run_module

    path = _custom_profile_file(tmp_path, task_count=1, epochs=2)
    calls = []
    monkeypatch.setattr(run_module, 'execute_benchmark',
                        lambda *args, **kwargs: calls.append((args, kwargs)) or Path('mock-output'))
    monkeypatch.setattr(sys, 'argv', ['godprompt_bench.run', '--profile-file', str(path)])
    with pytest.raises(SystemExit) as exc:
        run_module.main()
    assert exc.value.code == 2
    assert not calls
    capsys.readouterr()

    monkeypatch.setattr(sys, 'argv', [
        'godprompt_bench.run', '--profile-file', str(path), '--model', 'mockllm/test',
    ])
    run_module.main()
    assert len(calls) == 1
    assert calls[0][0][2].name == 'custom-one-off'
    assert calls[0][0][2].task_ids == ('impl-py-slugify',)
    assert calls[0][0][2].epochs == 2
    assert calls[0][1]['model'] == 'mockllm/test'


@pytest.mark.parametrize('invalid', [
    {'epochs': 4},
    {'max_messages': 31},
    {'max_time_seconds': 301},
    {'max_output_tokens': 8193},
    {'name': 'full'},
])
def test_cli_custom_profile_rejects_unbounded_or_reference_claims(
    monkeypatch, capsys, tmp_path, invalid,
):
    import godprompt_bench.run as run_module

    path = _custom_profile_file(tmp_path)
    profile = json.loads(path.read_text(encoding='utf-8'))
    profile.update(invalid)
    path.write_text(json.dumps(profile), encoding='utf-8')
    monkeypatch.setattr(sys, 'argv', [
        'godprompt_bench.run', '--profile-file', str(path), '--dry-run',
    ])
    monkeypatch.setattr(run_module, 'execute_benchmark',
                        lambda *args, **kwargs: pytest.fail('invalid profile must not evaluate'))
    with pytest.raises(SystemExit) as exc:
        run_module.main()
    assert exc.value.code == 2
    assert 'custom profile' in capsys.readouterr().err


def test_cli_custom_profile_cannot_override_builtin_or_profile_list(monkeypatch, capsys, tmp_path):
    import godprompt_bench.run as run_module

    path = _custom_profile_file(tmp_path)
    for extra in (['--profile', 'smoke'], ['--list-profiles']):
        monkeypatch.setattr(sys, 'argv', [
            'godprompt_bench.run', '--profile-file', str(path), *extra,
        ])
        with pytest.raises(SystemExit) as exc:
            run_module.main()
        assert exc.value.code == 2
        capsys.readouterr()


def test_cli_dry_run_markdown_produces_copyable_offline_plan(monkeypatch, capsys, tmp_path):
    import godprompt_bench.run as run_module

    output_dir = tmp_path / 'must-not-exist'
    monkeypatch.setattr(sys, 'argv', [
        'godprompt_bench.run', '--dry-run', '--format', 'markdown',
        '--profile', 'smoke', '--output', str(output_dir),
    ])
    monkeypatch.setattr(run_module, 'execute_benchmark',
                        lambda *args, **kwargs: pytest.fail('preview must not execute evaluator'))

    run_module.main()
    report = capsys.readouterr().out
    assert report.startswith('# GodPrompt Bench evaluation plan')
    assert 'Preview only' in report
    assert 'Model: not selected' in report
    assert 'Planned samples: 12' in report
    assert 'Tasks per condition: 6' in report
    assert 'Epochs: 1' in report
    assert 'baseline' in report and 'godprompt' in report
    assert 'Fixture SHA256:' in report
    assert 'provider cost cannot be inferred' in report.lower()
    assert 'No Docker, model or provider calls' in report
    assert not output_dir.exists()


def test_cli_dry_run_markdown_escapes_user_model_and_shows_controls(monkeypatch, capsys):
    import godprompt_bench.run as run_module

    monkeypatch.setattr(sys, 'argv', [
        'godprompt_bench.run', '--dry-run', '--format', 'markdown',
        '--model', 'mockllm/a|b\n# fake heading', '--temperature', '0.25',
        '--seed', '42', '--reasoning-effort', 'high', '--reasoning-mode', 'pro',
    ])
    monkeypatch.setattr(run_module, 'execute_benchmark',
                        lambda *args, **kwargs: pytest.fail('preview must not evaluate'))
    run_module.main()
    report = capsys.readouterr().out
    assert 'mockllm/a\\|b # fake heading' in report
    assert '\n# fake heading' not in report
    assert 'Temperature: 0.25' in report
    assert 'Seed: 42' in report
    assert 'Reasoning effort: high' in report
    assert 'Reasoning mode: pro' in report


def test_cli_markdown_format_rejects_live_run_without_execution(monkeypatch, capsys):
    import godprompt_bench.run as run_module

    monkeypatch.setattr(sys, 'argv', [
        'godprompt_bench.run', '--model', 'mockllm/test',
        '--format', 'markdown',
    ])
    monkeypatch.setattr(run_module, 'execute_benchmark',
                        lambda *args, **kwargs: pytest.fail('format selection must not evaluate'))
    with pytest.raises(SystemExit) as exc:
        run_module.main()
    assert exc.value.code == 2
    assert '--format markdown requires an offline action' in capsys.readouterr().err


@pytest.mark.parametrize(('discovery_args', 'expected_heading', 'expected_row'), (
    (['--list-profiles'], '# GodPrompt Bench profiles', '| smoke |'),
    (['--profile', 'smoke', '--list-tasks'], '# GodPrompt Bench tasks', '| impl-py-slugify |'),
))
def test_cli_markdown_discovery_is_copyable_offline_and_does_not_write(
    monkeypatch, capsys, tmp_path, discovery_args, expected_heading, expected_row,
):
    import godprompt_bench.run as run_module

    output_dir = tmp_path / 'must-not-exist'
    monkeypatch.setattr(sys, 'argv', [
        'godprompt_bench.run', *discovery_args, '--format', 'markdown',
        '--output', str(output_dir),
    ])
    monkeypatch.setattr(run_module, 'execute_benchmark',
                        lambda *args, **kwargs: pytest.fail('discovery ran a model'))

    run_module.main()
    report = capsys.readouterr().out
    assert expected_heading in report
    assert expected_row in report
    assert '**Preview only**' in report
    assert 'Fixture SHA256' in report
    assert 'hidden_verifier' not in report
    assert not output_dir.exists()


def test_cli_paid_run_still_requires_explicit_model(monkeypatch, capsys):
    import godprompt_bench.run as run_module

    monkeypatch.setattr(sys, 'argv', ['godprompt_bench.run', '--profile', 'smoke'])
    monkeypatch.setattr(run_module, 'execute_benchmark',
                        lambda *args, **kwargs: pytest.fail('no model must never start evaluator'))

    with pytest.raises(SystemExit) as exc:
        run_module.main()
    assert exc.value.code == 2
    assert '--model is required unless --dry-run, --list-profiles, or --list-tasks is specified' in capsys.readouterr().err


def test_cli_lists_validated_profiles_offline_without_model_or_output(monkeypatch, capsys, tmp_path):
    import godprompt_bench.run as run_module

    output_dir = tmp_path / 'must-not-exist'
    monkeypatch.setattr(sys, 'argv', [
        'godprompt_bench.run', '--list-profiles', '--output', str(output_dir),
    ])
    monkeypatch.setattr(run_module, 'execute_benchmark',
                        lambda *args, **kwargs: pytest.fail('profile list must not execute the evaluator'))

    run_module.main()
    report = json.loads(capsys.readouterr().out)
    assert report['preview_only'] is True
    assert [(p['profile'], p['tasks_per_condition'], p['epochs'], p['planned_samples'])
            for p in report['profiles']] == [
                ('smoke', 6, 1, 12), ('half', 20, 3, 120), ('full', 40, 3, 240),
            ]
    assert report['profiles'][1]['profile_id'] == 'half-frozen-2026-08-29'
    assert all(sum(p['categories'].values()) == p['tasks_per_condition']
               and len(p['fixture_bundles_sha256']) == 64 for p in report['profiles'])
    assert not output_dir.exists()


def test_cli_rejects_combining_profile_list_with_dry_run(monkeypatch, capsys):
    import godprompt_bench.run as run_module

    monkeypatch.setattr(sys, 'argv', ['godprompt_bench.run', '--list-profiles', '--dry-run'])
    with pytest.raises(SystemExit) as exc:
        run_module.main()
    assert exc.value.code == 2
    assert 'not allowed with argument' in capsys.readouterr().err


@pytest.mark.parametrize(('profile_name', 'expected_count'), (
    ('smoke', 6), ('half', 20), ('full', 40),
))
def test_cli_lists_selected_task_metadata_offline_without_model_or_output(
    monkeypatch, capsys, tmp_path, profile_name, expected_count,
):
    import godprompt_bench.run as run_module

    output_dir = tmp_path / 'must-not-exist'
    monkeypatch.setattr(sys, 'argv', [
        'godprompt_bench.run', '--profile', profile_name, '--list-tasks',
        '--output', str(output_dir),
    ])
    monkeypatch.setattr(run_module, 'execute_benchmark',
                        lambda *args, **kwargs: pytest.fail('task discovery must not execute the evaluator'))

    run_module.main()
    report = json.loads(capsys.readouterr().out)
    profile = load_profile(ROOT / 'configs' / f'{profile_name}.json')
    assert report['preview_only'] is True
    assert report['profile'] == profile_name
    assert report['profile_id'] == profile.name
    assert report['tasks_per_condition'] == expected_count
    assert len(report['fixture_bundles_sha256']) == 64
    assert [task['id'] for task in report['tasks']] == list(profile.task_ids)
    assert {task['category'] for task in report['tasks']} == {
        'implementation', 'debugging', 'refactor', 'scope-control', 'verification', 'tool-discipline',
    }
    assert {task['runtime'] for task in report['tasks']} == {'python', 'javascript'}
    assert all(set(task) == {'id', 'category', 'runtime'} for task in report['tasks'])
    assert 'hidden_verifier' not in json.dumps(report)
    assert not output_dir.exists()


@pytest.mark.parametrize('conflicting', ('--dry-run', '--list-profiles'))
def test_cli_task_discovery_is_exclusive_with_other_offline_actions(monkeypatch, capsys, conflicting):
    import godprompt_bench.run as run_module

    monkeypatch.setattr(sys, 'argv', ['godprompt_bench.run', '--list-tasks', conflicting])
    with pytest.raises(SystemExit) as exc:
        run_module.main()
    assert exc.value.code == 2
    assert 'not allowed with argument' in capsys.readouterr().err


def test_offline_preview_rejects_unknown_profile_task():
    from godprompt_bench.run import preview_benchmark

    profile = RunProfile(
        name='unrecognized', task_ids=('not-in-manifest',), epochs=1,
        max_messages=10, max_time_seconds=30, max_output_tokens=1000,
    )
    with pytest.raises(ValueError, match='unknown task IDs.*not-in-manifest'):
        preview_benchmark(ROOT, profile, model='mockllm/test')


@pytest.mark.parametrize('nested', (False, True))
def test_inspect_raw_log_directory_rejects_symlinked_roots_before_writing(tmp_path: Path, nested: bool):
    # Only a disposable temp directory is involved; no provider or Inspect eval runs.
    from godprompt_bench.run import _create_raw_log_directory

    outside = tmp_path / 'outside'
    outside.mkdir()
    link = tmp_path / 'linked-results'
    try:
        os.symlink(outside, link, target_is_directory=True)
    except OSError:
        pytest.skip('directory symlink creation unavailable on this host')

    raw_dir = (link / 'batch' if nested else link) / 'inspect-logs'
    with pytest.raises(ValueError, match='linked raw log directory'):
        _create_raw_log_directory(raw_dir)
    assert list(outside.iterdir()) == []


def test_inspect_log_condition_rejects_conflicting_or_ambiguous_identity():
    # Synthetic log metadata must not silently swap baseline and treatment samples.
    def log(task, metadata):
        return SimpleNamespace(eval=SimpleNamespace(task=task), metadata=metadata)

    assert _condition_for_log(log('godprompt_bench_baseline', {'condition': 'baseline'})) == 'baseline'
    assert _condition_for_log(log('godprompt_bench_godprompt', {})) == 'godprompt'
    with pytest.raises(RuntimeError, match='condition.*conflict'):
        _condition_for_log(log('godprompt_bench_godprompt', {'condition': 'baseline'}))
    with pytest.raises(RuntimeError, match='condition'):
        _condition_for_log(log('godprompt_bench_baseline', {'condition': 'unexpected'}))
    with pytest.raises(RuntimeError, match='condition'):
        _condition_for_log(log('prefix_godprompt_bench_godprompt_suffix', {}))


@pytest.mark.parametrize('condition', ('baseline', 'godprompt'))
def test_inspect_log_condition_rejects_unrecognized_task_even_with_metadata(condition):
    # Metadata alone must not authorize samples from another Inspect task.
    log = SimpleNamespace(eval=SimpleNamespace(task='unrelated_eval'), metadata={'condition': condition})
    with pytest.raises(RuntimeError, match='task identity'):
        _condition_for_log(log)


def test_run_manifest_fingerprints_actual_compose_isolation_configuration():
    profile = load_profile(ROOT / 'configs' / 'smoke.json')
    manifest = build_manifest(
        ROOT.parent, ROOT, profile,
        requested_model='mockllm/model', actual_models=['mockllm/model'],
        temperature=None, seed=7, reasoning_effort=None, reasoning_mode=None,
        records=[], benchmark_commit_sha='benchmark-sha',
        godprompt_commit_sha='prompt-sha', working_tree_dirty=False,
    )
    config = ROOT / 'sandbox' / 'compose.yaml'
    assert manifest['sandbox_compose_sha256'] == hashlib.sha256(config.read_bytes()).hexdigest()
    assert manifest['sandbox_compose_sha256'] != manifest['sandbox_dockerfile_sha256']


def test_run_manifest_uses_evaluated_prompt_fingerprint():
    profile = load_profile(ROOT / 'configs' / 'smoke.json')
    evaluated_hash = 'f' * 64
    manifest = build_manifest(
        ROOT.parent, ROOT, profile,
        requested_model='mockllm/model', actual_models=['mockllm/model'],
        temperature=None, seed=7, reasoning_effort=None, reasoning_mode=None,
        records=[], benchmark_commit_sha='benchmark-sha',
        godprompt_commit_sha='prompt-sha', working_tree_dirty=False,
        evaluated_godprompt_sha256=evaluated_hash,
    )
    assert manifest['godprompt_system_prompt_sha256'] == evaluated_hash


def test_execute_benchmark_exports_plan_fingerprint_for_later_review(monkeypatch, tmp_path):
    import inspect_ai
    import godprompt_bench.run as run_module

    profile = load_profile(ROOT / 'configs' / 'smoke.json')
    expected = run_module.preview_benchmark(
        ROOT, profile, model='mockllm/model', seed=7,
    )['plan_sha256']
    exported = []
    monkeypatch.setattr(run_module, 'build_task', lambda *args, **kwargs: object())
    monkeypatch.setattr(run_module, 'validate_sample_coverage', lambda *args: None)
    monkeypatch.setattr(inspect_ai, 'eval', lambda *args, **kwargs: [])
    monkeypatch.setattr(
        run_module, 'export_run',
        lambda directory, manifest, records, trajectories: exported.append(manifest),
    )

    execute_benchmark(
        ROOT.parent, ROOT, profile, model='mockllm/model',
        output_dir=tmp_path, seed=7, required_plan_sha256=expected,
    )
    assert len(exported) == 1
    assert exported[0]['plan_sha256'] == expected
    assert exported[0]['plan_sha256_schema'] == 'godprompt.bench.plan.v1'


def test_execute_benchmark_rechecks_required_digest_at_provider_boundary(monkeypatch, tmp_path):
    import inspect_ai
    import godprompt_bench.run as run_module

    profile = load_profile(ROOT / 'configs' / 'smoke.json')
    monkeypatch.setattr(
        inspect_ai, 'eval',
        lambda *args, **kwargs: pytest.fail('mismatched digest must not call provider'),
    )
    monkeypatch.setattr(
        run_module, 'export_run',
        lambda *args, **kwargs: pytest.fail('mismatched digest must not export'),
    )

    with pytest.raises(ValueError, match='plan fingerprint mismatch before evaluation'):
        execute_benchmark(
            ROOT.parent, ROOT, profile, model='mockllm/model',
            output_dir=tmp_path, required_plan_sha256='0' * 64,
        )


def test_execute_benchmark_refuses_plan_input_drift_before_export(monkeypatch, tmp_path):
    import inspect_ai
    import godprompt_bench.run as run_module

    profile = load_profile(ROOT / 'configs' / 'smoke.json')
    fingerprints = iter(('a' * 64, 'b' * 64))
    monkeypatch.setattr(run_module, '_plan_sha256', lambda *args: next(fingerprints))
    monkeypatch.setattr(run_module, 'build_task', lambda *args, **kwargs: object())
    monkeypatch.setattr(run_module, 'validate_sample_coverage', lambda *args: None)
    monkeypatch.setattr(inspect_ai, 'eval', lambda *args, **kwargs: [])
    monkeypatch.setattr(
        run_module, 'export_run',
        lambda *args, **kwargs: pytest.fail('changed plan must not be publicly exported'),
    )

    with pytest.raises(ValueError, match='plan inputs changed during evaluation'):
        execute_benchmark(
            ROOT.parent, ROOT, profile, model='mockllm/model', output_dir=tmp_path,
        )


def test_condition_batches_counterbalance_order_without_additional_samples():
    task_ids = tuple(f'task-{i}' for i in range(6))
    batches = condition_batches(task_ids)
    assert batches == [
        ('baseline', ('task-0', 'task-2', 'task-4')),
        ('godprompt', ('task-0', 'task-2', 'task-4')),
        ('godprompt', ('task-1', 'task-3', 'task-5')),
        ('baseline', ('task-1', 'task-3', 'task-5')),
    ]
    assert condition_batches(task_ids) == batches
    for condition in ('baseline', 'godprompt'):
        assert sorted(task for label, group in batches if label == condition for task in group) == sorted(task_ids)
    assert condition_batches(('solo',)) == [('baseline', ('solo',)), ('godprompt', ('solo',))]


def test_fixture_fingerprints_cover_selected_bundles_and_hidden_verifiers(tmp_path: Path):
    tasks = tmp_path / 'tasks'
    tasks.mkdir()
    manifest = [
        {'id': 'task-b', 'fixture_dir': 'tasks/b'},
        {'id': 'task-a', 'fixture_dir': 'tasks/a'},
    ]
    (tasks / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    for name in ('a', 'b'):
        directory = tasks / name
        directory.mkdir()
        (directory / 'fixture.json').write_text(json.dumps({'hidden_verifier': f'check {name}', 'files': {'x': '1'}}), encoding='utf-8')

    first = fixture_fingerprints(tmp_path, ('task-a', 'task-b'))
    reverse = fixture_fingerprints(tmp_path, ('task-b', 'task-a'))
    assert first == reverse
    assert set(first['fixture_bundle_sha256']) == {'task-a', 'task-b'}
    assert all(len(value) == 64 for value in first['fixture_bundle_sha256'].values())
    assert len(first['fixture_bundles_sha256']) == 64
    assert 'check a' not in repr(first)

    (tasks / 'a' / 'fixture.json').write_text(json.dumps({'hidden_verifier': 'changed secret verifier', 'files': {'x': '1'}}), encoding='utf-8')
    changed = fixture_fingerprints(tmp_path, ('task-a', 'task-b'))
    assert changed['fixture_bundle_sha256']['task-a'] != first['fixture_bundle_sha256']['task-a']
    assert changed['fixture_bundle_sha256']['task-b'] == first['fixture_bundle_sha256']['task-b']
    assert changed['fixture_bundles_sha256'] != first['fixture_bundles_sha256']

    with pytest.raises(ValueError, match='missing fixture'):
        fixture_fingerprints(tmp_path, ('task-unknown',))


def test_fixture_fingerprints_reject_duplicate_manifest_keys(tmp_path: Path):
    tasks = tmp_path / 'tasks'
    tasks.mkdir()
    (tasks / 'manifest.json').write_text(
        '[{"id":"task-a","fixture_dir":"tasks/a","fixture_dir":"tasks/b"}]',
        encoding='utf-8',
    )
    with pytest.raises(ValueError, match='duplicate JSON key: fixture_dir'):
        fixture_fingerprints(tmp_path, ('task-a',))


def test_sample_coverage_rejects_missing_duplicate_and_extra_samples():
    profile = RunProfile(name='tiny', task_ids=('task-a', 'task-b'), epochs=2,
                         max_messages=10, max_time_seconds=30, max_output_tokens=1000)
    expected = [(condition, task_id, epoch)
                for condition in ('baseline', 'godprompt')
                for task_id in profile.task_ids for epoch in (1, 2)]
    categories = {'task-a': 'implementation', 'task-b': 'debugging'}
    records = [SimpleNamespace(condition=c, task_id=t, epoch=e, category=categories[t])
               for c, t, e in expected]
    validate_sample_coverage(profile, records, categories)

    with pytest.raises(ValueError, match='missing.*godprompt.*task-b'):
        validate_sample_coverage(profile, records[:-1], categories)
    with pytest.raises(ValueError, match='duplicate.*baseline.*task-a'):
        validate_sample_coverage(profile, records + [records[0]], categories)
    with pytest.raises(ValueError, match='unexpected.*baseline.*task-a'):
        validate_sample_coverage(profile, records + [SimpleNamespace(
            condition='baseline', task_id='task-a', epoch=3, category='implementation')], categories)


def test_sample_coverage_rejects_misattributed_categories():
    profile = RunProfile(name='tiny', task_ids=('task-a', 'task-b'), epochs=1,
                         max_messages=10, max_time_seconds=30, max_output_tokens=1000)
    categories = {'task-a': 'implementation', 'task-b': 'debugging'}
    records = [SimpleNamespace(condition=c, task_id=t, epoch=1, category=categories[t])
               for c in ('baseline', 'godprompt') for t in profile.task_ids]
    validate_sample_coverage(profile, records, categories)

    # A swapped but valid category would otherwise silently corrupt by_category.
    records[0].category = 'debugging'
    with pytest.raises(ValueError, match='category.*task-a'):
        validate_sample_coverage(profile, records, categories)


def test_execute_benchmark_rejects_incomplete_samples_before_export(monkeypatch, tmp_path):
    import inspect_ai
    import godprompt_bench.run as run_module

    profile = load_profile(ROOT / 'configs' / 'smoke.json')
    logs = [SimpleNamespace(metadata={'condition': condition}, eval=SimpleNamespace(model='mockllm/model'), samples=[])
            for condition in ('baseline', 'godprompt')]
    monkeypatch.setattr(run_module, 'build_task', lambda *args, **kwargs: object())
    monkeypatch.setattr(inspect_ai, 'eval', lambda *args, **kwargs: logs)
    monkeypatch.setattr(run_module, 'export_run', lambda *args, **kwargs: pytest.fail('must not publish incomplete benchmark'))
    with pytest.raises(ValueError, match='missing'):
        execute_benchmark(ROOT.parent, ROOT, profile, model='mockllm/model', output_dir=tmp_path)


def test_execute_benchmark_rejects_wrong_category_before_export(monkeypatch, tmp_path):
    import inspect_ai
    import godprompt_bench.run as run_module
    from godprompt_bench.corpus import load_manifest

    profile = load_profile(ROOT / 'configs' / 'smoke.json')
    canonical = {spec.id: spec.category for spec in load_manifest(ROOT / 'tasks' / 'manifest.json')}
    logs = [SimpleNamespace(
        metadata={'condition': condition}, eval=SimpleNamespace(model='mockllm/model'),
        samples=[SimpleNamespace(id=task_id, epoch=1) for task_id in profile.task_ids],
    ) for condition in ('baseline', 'godprompt')]
    monkeypatch.setattr(run_module, 'build_task', lambda *args, **kwargs: object())
    monkeypatch.setattr(inspect_ai, 'eval', lambda *args, **kwargs: logs)
    monkeypatch.setattr(run_module, 'sample_record', lambda sample, condition: SimpleNamespace(
        condition=condition, task_id=sample.id, epoch=sample.epoch,
        category='debugging' if sample.id == profile.task_ids[0] else canonical[sample.id],
    ))
    monkeypatch.setattr(run_module, 'public_trajectory', lambda *args: {})
    monkeypatch.setattr(run_module, 'export_run', lambda *args: pytest.fail('must not export misattributed categories'))
    with pytest.raises(ValueError, match='category.*impl-py-slugify'):
        execute_benchmark(ROOT.parent, ROOT, profile, model='mockllm/model', output_dir=tmp_path)


def test_execute_benchmark_refuses_fixture_drift_before_public_export(monkeypatch, tmp_path):
    import inspect_ai
    import godprompt_bench.run as run_module

    profile = load_profile(ROOT / 'configs' / 'smoke.json')
    before, after = 'a' * 64, 'b' * 64
    current = {'fingerprint': before}
    events = []

    def snapshot(*args):
        events.append(('snapshot', current['fingerprint']))
        return {'fixture_bundles_sha256': current['fingerprint'], 'fixture_bundle_sha256': {}}

    def fake_eval(*args, **kwargs):
        events.append(('evaluate', None))
        current['fingerprint'] = after
        return []

    monkeypatch.setattr(run_module, 'fixture_fingerprints', snapshot)
    monkeypatch.setattr(run_module, 'build_task', lambda *args, **kwargs: object())
    monkeypatch.setattr(run_module, 'validate_sample_coverage', lambda *args: None)
    monkeypatch.setattr(inspect_ai, 'eval', fake_eval)
    monkeypatch.setattr(run_module, 'build_manifest',
                        lambda *args, **kwargs: pytest.fail('drifted fixture must not enter public manifest'))
    monkeypatch.setattr(run_module, 'export_run',
                        lambda *args, **kwargs: pytest.fail('drifted fixture must not be exported'))

    with pytest.raises(ValueError, match='fixture.*changed during evaluation'):
        execute_benchmark(ROOT.parent, ROOT, profile, model='mockllm/model', output_dir=tmp_path)
    assert events == [
        ('snapshot', before), ('snapshot', before),
        ('evaluate', None), ('snapshot', after),
    ]


def test_execute_benchmark_refuses_prompt_drift_before_public_export(monkeypatch, tmp_path):
    import inspect_ai
    import godprompt_bench.run as run_module

    profile = load_profile(ROOT / 'configs' / 'smoke.json')
    prompt = {'value': 'GodPrompt before evaluation'}
    observed_prompts = []

    def read_prompt(condition, _repo_root):
        if condition == 'godprompt':
            observed_prompts.append(prompt['value'])
            return prompt['value']
        return 'baseline'

    def fake_eval(*args, **kwargs):
        prompt['value'] = 'GodPrompt after evaluation'
        return []

    monkeypatch.setattr(run_module, 'condition_prompt', read_prompt)
    monkeypatch.setattr(run_module, 'build_task', lambda *args, **kwargs: object())
    monkeypatch.setattr(run_module, 'validate_sample_coverage', lambda *args: None)
    monkeypatch.setattr(inspect_ai, 'eval', fake_eval)
    monkeypatch.setattr(run_module, 'build_manifest',
                        lambda *args, **kwargs: pytest.fail('changed prompt must not enter public manifest'))
    monkeypatch.setattr(run_module, 'export_run',
                        lambda *args, **kwargs: pytest.fail('changed prompt must not be exported'))

    with pytest.raises(ValueError, match='GodPrompt.*changed during evaluation'):
        execute_benchmark(ROOT.parent, ROOT, profile, model='mockllm/model', output_dir=tmp_path)
    assert observed_prompts[0] == 'GodPrompt before evaluation'
    assert observed_prompts[-1] == 'GodPrompt after evaluation'


def test_execute_benchmark_refuses_prompt_change_during_task_construction(monkeypatch, tmp_path):
    import inspect_ai
    import godprompt_bench.run as run_module

    profile = load_profile(ROOT / 'configs' / 'smoke.json')
    prompt = {'value': 'before'}

    def fake_build_task(*args, **kwargs):
        prompt['value'] = 'after'
        return object()

    monkeypatch.setattr(run_module, 'condition_prompt', lambda condition, root: (
        prompt['value'] if condition == 'godprompt' else 'baseline'))
    monkeypatch.setattr(run_module, 'build_task', fake_build_task)
    monkeypatch.setattr(inspect_ai, 'eval',
                        lambda *args, **kwargs: pytest.fail('changed prompt must not call provider'))

    with pytest.raises(ValueError, match='GodPrompt.*changed during task construction'):
        execute_benchmark(ROOT.parent, ROOT, profile, model='mockllm/model', output_dir=tmp_path)


def test_profiles_are_frozen_and_full_is_240_samples():
    smoke = load_profile(ROOT / 'configs' / 'smoke.json')
    full = load_profile(ROOT / 'configs' / 'full.json')
    assert len(smoke.task_ids) == 6 and smoke.epochs == 1
    assert len(full.task_ids) == 40 and full.epochs == 3
    assert len(full.task_ids) * full.epochs * 2 == 240


def test_profile_rejects_duplicate_ids_before_any_evaluation(tmp_path: Path):
    profile = json.loads((ROOT / 'configs' / 'smoke.json').read_text(encoding='utf-8'))
    profile['task_ids'].append(profile['task_ids'][0])
    path = tmp_path / 'duplicate.json'
    path.write_text(json.dumps(profile), encoding='utf-8')
    with pytest.raises(ValueError, match='duplicate task id.*impl-py-slugify'):
        load_profile(path)


def test_profile_rejects_duplicate_json_budget_keys(tmp_path: Path):
    path = tmp_path / 'duplicate-budget.json'
    path.write_text(
        '{"name":"test","task_ids":["task-a"],"epochs":1,"epochs":2,'
        '"max_messages":10,"max_time_seconds":30,"max_output_tokens":1000}',
        encoding='utf-8',
    )
    with pytest.raises(ValueError, match='duplicate JSON key: epochs'):
        load_profile(path)


@pytest.mark.parametrize('invalid_root', ([], None, 'smoke', 42))
def test_profile_rejects_nonobject_root_with_actionable_error(tmp_path: Path, invalid_root):
    path = tmp_path / 'malformed.json'
    path.write_text(json.dumps(invalid_root), encoding='utf-8')
    with pytest.raises(ValueError, match='profile root must be an object'):
        load_profile(path)


@pytest.mark.parametrize('invalid_id', ('', '  \t'))
def test_profile_rejects_blank_task_ids_before_evaluation(tmp_path: Path, invalid_id):
    profile = json.loads((ROOT / 'configs' / 'smoke.json').read_text(encoding='utf-8'))
    profile['task_ids'][0] = invalid_id
    path = tmp_path / 'blank-id.json'
    path.write_text(json.dumps(profile), encoding='utf-8')
    with pytest.raises(ValueError, match='profile task_ids must be non-empty strings'):
        load_profile(path)


def test_profile_rejects_unknown_resource_limit_fields(tmp_path: Path):
    # A misspelled budget key must not silently leave the default cap in effect.
    profile = json.loads((ROOT / 'configs' / 'smoke.json').read_text(encoding='utf-8'))
    profile['max_output_token'] = 100
    path = tmp_path / 'misspelled-budget.json'
    path.write_text(json.dumps(profile), encoding='utf-8')
    with pytest.raises(ValueError, match='unknown profile fields.*max_output_token'):
        load_profile(path)


@pytest.mark.parametrize('invalid_name', (None, 12, {}, [], '', '  \t '))
def test_profile_requires_nonempty_string_name(tmp_path: Path, invalid_name):
    # Do not mislabel exported benchmark results using str(None) or repr(dict).
    profile = json.loads((ROOT / 'configs' / 'smoke.json').read_text(encoding='utf-8'))
    profile['name'] = invalid_name
    path = tmp_path / 'invalid-name.json'
    path.write_text(json.dumps(profile), encoding='utf-8')
    with pytest.raises(ValueError, match='profile name must be a non-empty string'):
        load_profile(path)


@pytest.mark.parametrize(('field', 'invalid'), (
    ('epochs', True),
    ('epochs', 1.5),
    ('max_messages', '10'),
    ('max_time_seconds', False),
    ('max_output_tokens', 0),
))
def test_profile_rejects_non_integer_or_nonpositive_budgets(tmp_path: Path, field, invalid):
    # Reject silently coerced configuration before running any paid evaluations.
    profile = json.loads((ROOT / 'configs' / 'smoke.json').read_text(encoding='utf-8'))
    profile[field] = invalid
    path = tmp_path / 'invalid-budget.json'
    path.write_text(json.dumps(profile), encoding='utf-8')
    with pytest.raises(ValueError, match='profile numeric limits must be positive integers'):
        load_profile(path)


def test_sample_record_uses_score_and_sums_provider_usage():
    score = SimpleNamespace(
        value={'passed': 1, 'false_completion': 0, 'scope_violation': 0, 'tool_misuse_count': 1, 'verification_attempts': 2, 'failed_tool_calls': 1, 'retries': 1},
        metadata={'completion_status': 'complete'},
    )
    usage = SimpleNamespace(input_tokens=10, input_tokens_cache_read=3, input_tokens_cache_write=2, output_tokens=7)
    sample = SimpleNamespace(
        id='x', epoch=2, metadata={'category': 'debugging'}, scores={'godprompt_bench': score},
        model_usage={'m': usage}, total_time=1.5, error=None, limit=None,
    )
    record = sample_record(sample, 'godprompt')
    assert record.input_tokens == 15
    assert record.output_tokens == 7
    assert record.tool_misuse_count == 1
    assert record.infrastructure_error is None


@pytest.mark.parametrize('invalid_score', (None, 1, 0.0, True, 'passed', []))
def test_sample_record_rejects_non_mapping_scorer_payload(invalid_score):
    # An invalid score must not silently become a valid-looking failed sample.
    score = SimpleNamespace(value=invalid_score, metadata={'completion_status': 'complete'})
    sample = SimpleNamespace(
        id='synthetic', epoch=1, metadata={}, scores={'godprompt_bench': score},
        model_usage=None, total_time=1.0, error=None, limit=None,
    )
    with pytest.raises(ValueError, match='invalid benchmark score value'):
        sample_record(sample, 'baseline')


@pytest.mark.parametrize('invalid_epoch', (0, -1, True, 1.9, '1', None, float('nan')))
def test_sample_record_and_public_trajectory_reject_invalid_epochs(invalid_epoch):
    # Truncating a fractional epoch can falsely satisfy expected sample coverage.
    sample = SimpleNamespace(
        id='synthetic', epoch=invalid_epoch, metadata={}, scores={}, model_usage={},
        total_time=1.0, error=None, limit=None, messages=[], events=[],
    )
    with pytest.raises(ValueError, match='invalid sample epoch'):
        sample_record(sample, 'baseline')
    with pytest.raises(ValueError, match='invalid sample epoch'):
        public_trajectory(sample, 'baseline')


@pytest.mark.parametrize('invalid_id', (123, True, None, '', '   '))
def test_sample_record_and_public_trajectory_reject_noncanonical_task_ids(invalid_id):
    # Coercing an Inspect numeric ID to str can match a different manifest task.
    sample = SimpleNamespace(
        id=invalid_id, epoch=1, metadata={}, scores={}, model_usage={},
        total_time=1.0, error=None, limit=None, messages=[], events=[],
    )
    with pytest.raises(ValueError, match='invalid sample task id'):
        sample_record(sample, 'baseline')
    with pytest.raises(ValueError, match='invalid sample task id'):
        public_trajectory(sample, 'baseline')


@pytest.mark.parametrize('latency', [
    '1.5', True, -1.0, float('nan'), float('inf'), 10 ** 400,
])
def test_sample_record_rejects_invalid_latency_telemetry(latency):
    sample = SimpleNamespace(
        id='synthetic', epoch=1, metadata={}, scores={}, model_usage={},
        total_time=latency, error=None, limit=None,
    )
    with pytest.raises(ValueError, match='invalid sample latency'):
        sample_record(sample, 'baseline')


def test_sample_record_accepts_missing_and_zero_latency():
    sample = SimpleNamespace(
        id='synthetic', epoch=1, metadata={}, scores={}, model_usage={},
        total_time=None, error=None, limit=None,
    )
    assert sample_record(sample, 'baseline').latency_seconds is None
    sample.total_time = 0
    assert sample_record(sample, 'baseline').latency_seconds == 0.0


@pytest.mark.parametrize('field,value', [
    ('passed', 'false'),
    ('passed', -1),
    ('passed', 2),
    ('false_completion', '0'),
    ('false_completion', float('nan')),
    ('scope_violation', 0.5),
    ('scope_violation', []),
])
def test_sample_record_rejects_invalid_binary_score_flags(field, value):
    score = SimpleNamespace(value={field: value}, metadata={'completion_status': 'complete'})
    sample = SimpleNamespace(
        id='synthetic', epoch=1, metadata={}, scores={'godprompt_bench': score},
        model_usage=None, total_time=1.0, error=None, limit=None,
    )
    with pytest.raises(ValueError, match=f'invalid benchmark score flag: {field}'):
        sample_record(sample, 'baseline')


def test_sample_record_accepts_boolean_and_binary_numeric_score_flags():
    score = SimpleNamespace(
        value={'passed': True, 'false_completion': 0.0, 'scope_violation': 1.0},
        metadata={'completion_status': 'complete'},
    )
    sample = SimpleNamespace(
        id='synthetic', epoch=1, metadata={}, scores={'godprompt_bench': score},
        model_usage=None, total_time=1.0, error=None, limit=None,
    )
    record = sample_record(sample, 'godprompt')
    assert (record.passed, record.false_completion, record.scope_violation) == (True, False, True)


@pytest.mark.parametrize('field,value', [
    ('tool_misuse_count', True),
    ('verification_attempts', -1),
    ('failed_tool_calls', 1.5),
    ('retries', '2'),
    ('retries', float('nan')),
    ('tool_misuse_count', float('inf')),
])
def test_sample_record_rejects_invalid_score_counters(field, value):
    score = SimpleNamespace(value={field: value}, metadata={'completion_status': 'complete'})
    sample = SimpleNamespace(
        id='synthetic', epoch=1, metadata={}, scores={'godprompt_bench': score},
        model_usage=None, total_time=1.0, error=None, limit=None,
    )
    with pytest.raises(ValueError, match=f'invalid benchmark counter: {field}'):
        sample_record(sample, 'baseline')


def test_sample_record_score_counters_accept_missing_and_integral_float():
    score = SimpleNamespace(
        value={'retries': 2.0, 'failed_tool_calls': None},
        metadata={'completion_status': 'complete'},
    )
    sample = SimpleNamespace(
        id='synthetic', epoch=1, metadata={}, scores={'godprompt_bench': score},
        model_usage=None, total_time=1.0, error=None, limit=None,
    )
    record = sample_record(sample, 'baseline')
    assert record.retries == 2
    assert record.failed_tool_calls == 0


@pytest.mark.parametrize('field,value', [
    ('input_tokens', -3),
    ('input_tokens', True),
    ('input_tokens_cache_read', '7'),
    ('input_tokens_cache_write', 2.5),
    ('output_tokens', float('nan')),
    ('output_tokens', float('inf')),
])
def test_usage_totals_rejects_invalid_token_telemetry(field, value):
    from godprompt_bench.run import _usage_totals

    usage = SimpleNamespace(
        input_tokens=10, input_tokens_cache_read=2, input_tokens_cache_write=1,
        output_tokens=5,
    )
    setattr(usage, field, value)
    with pytest.raises(ValueError, match='invalid model usage token count'):
        _usage_totals({'synthetic-model': usage})


def test_usage_totals_accepts_integral_floats_and_missing_optional_counts():
    from godprompt_bench.run import _usage_totals

    usage = SimpleNamespace(input_tokens=5.0, input_tokens_cache_read=None, output_tokens=3.0)
    assert _usage_totals({'synthetic-model': usage}) == (5, 3)


def test_usage_totals_counts_serialized_model_usage_and_rejects_invalid_values():
    from godprompt_bench.run import _usage_totals

    usage = {'input_tokens': 8, 'input_tokens_cache_read': 4,
             'input_tokens_cache_write': 2, 'output_tokens': 3}
    assert _usage_totals({'serialized-model': usage}) == (14, 3)
    usage['output_tokens'] = -1
    with pytest.raises(ValueError, match='invalid model usage token count: output_tokens'):
        _usage_totals({'serialized-model': usage})


@pytest.mark.parametrize('usage', [
    {'provider_metadata': 'no usage reported'},
    {'input_tokens': None, 'output_tokens': None},
    SimpleNamespace(model='unavailable'),
])
def test_usage_totals_does_not_report_unknown_usage_as_zero(usage):
    from godprompt_bench.run import _usage_totals

    assert _usage_totals({'synthetic-model': usage}) == (None, None)
    assert _usage_totals({'synthetic-model': {'input_tokens': 0, 'output_tokens': 0}}) == (0, 0)


def test_usage_totals_preserves_partially_available_and_multimodel_usage():
    from godprompt_bench.run import _usage_totals

    assert _usage_totals({'m': {'input_tokens': 3}}) == (3, None)
    assert _usage_totals({'m': {'output_tokens': 5}}) == (None, 5)
    assert _usage_totals({'m': {'input_tokens': 3, 'output_tokens': 5}, 'n': {}}) == (None, None)


def test_public_trajectory_excludes_system_and_reasoning_content():
    messages = [
        SimpleNamespace(role='system', model_dump=lambda **kwargs: {'role': 'system', 'content': 'secret prompt'}),
        SimpleNamespace(role='user', model_dump=lambda **kwargs: {'role': 'user', 'content': 'task'}),
        SimpleNamespace(role='assistant', model_dump=lambda **kwargs: {'role': 'assistant', 'content': [
            {'type': 'reasoning', 'reasoning': 'private'},
            {'type': 'thinking', 'thinking': 'synthetic private thought'},
            {'type': 'redacted_thinking', 'data': 'synthetic opaque block'},
            {'type': 'text', 'text': 'public', 'thinking': 'synthetic private field'},
        ]}),
    ]
    event = SimpleNamespace(event='tool', model_dump=lambda **kwargs: {'event': 'tool', 'function': 'bash', 'arguments': {'cmd': 'python test.py'}, 'result': 'ok'})
    sample = SimpleNamespace(id='x', epoch=1, messages=messages, events=[event])
    trajectory = public_trajectory(sample, 'baseline')
    assert [m['role'] for m in trajectory['messages']] == ['user', 'assistant']
    assert trajectory['messages'][1]['content'] == [{'type': 'text', 'text': 'public'}]
    assert trajectory['events'][0]['event'] == 'tool'


def test_public_trajectory_rejects_conflicting_original_event_type():
    private_event = SimpleNamespace(
        event='model',
        model_dump=lambda **kwargs: {'event': 'tool', 'content': 'SYNTHETIC_PRIVATE_EVENT'},
    )
    public_event = SimpleNamespace(
        event='tool',
        model_dump=lambda **kwargs: {'event': 'tool', 'function': 'bash'},
    )
    sample = SimpleNamespace(id='synthetic', epoch=1, messages=[], events=[private_event, public_event])
    assert public_trajectory(sample, 'baseline')['events'] == [{'event': 'tool', 'function': 'bash'}]


def test_public_trajectory_excludes_private_analysis_channel_messages_and_blocks():
    # Some adapters tag reasoning by channel rather than by content block type.
    sample = SimpleNamespace(
        id='synthetic', epoch=1,
        messages=[
            {'role': 'assistant', 'channel': 'analysis', 'content': 'SYNTHETIC_PRIVATE_MESSAGE'},
            {'role': 'assistant', 'channel': 'final', 'content': 'public answer'},
            {'role': 'assistant', 'content': [
                {'channel': 'reasoning', 'text': 'SYNTHETIC_PRIVATE_BLOCK'},
                {'type': 'text', 'text': 'public text'},
            ]},
        ],
        events=[{'event': 'tool', 'output': [
            {'channel': 'thinking', 'text': 'SYNTHETIC_PRIVATE_EVENT'},
            {'channel': 'final', 'text': 'public result'},
        ]}],
    )
    trajectory = public_trajectory(sample, 'baseline')
    assert 'SYNTHETIC_PRIVATE' not in json.dumps(trajectory)
    assert trajectory['messages'] == [
        {'role': 'assistant', 'channel': 'final', 'content': 'public answer'},
        {'role': 'assistant', 'content': [{'type': 'text', 'text': 'public text'}]},
    ]
    assert trajectory['events'][0]['output'] == [{'channel': 'final', 'text': 'public result'}]


def test_public_trajectory_redacts_analysis_fields_and_typed_blocks():
    # Reasoning may be serialized as an analysis field, type, or channel alias.
    sample = SimpleNamespace(
        id='synthetic', epoch=1,
        messages=[{'role': 'assistant', 'analysis': 'SYNTHETIC_PRIVATE_FIELD', 'content': [
            {'type': 'analysis', 'text': 'SYNTHETIC_PRIVATE_BLOCK'},
            {'type': 'analysis_text', 'text': 'SYNTHETIC_PRIVATE_ALIAS'},
            {'type': 'text', 'text': 'visible answer'},
        ]}],
        events=[{'event': 'tool', 'output': [
            {'channel': 'analysis_text', 'text': 'SYNTHETIC_PRIVATE_EVENT'},
            {'status': 'ok'},
        ]}],
    )
    trajectory = public_trajectory(sample, 'baseline')
    assert 'SYNTHETIC_PRIVATE' not in json.dumps(trajectory)
    assert trajectory['messages'][0]['content'] == [{'type': 'text', 'text': 'visible answer'}]
    assert trajectory['events'][0]['output'] == [{'status': 'ok'}]


def test_public_trajectory_redacts_provider_reasoning_field_variants():
    # Provider-specific field names can carry private reasoning in otherwise public messages.
    sample = SimpleNamespace(
        id='synthetic', epoch=1,
        messages=[{
            'role': 'assistant',
            'reasoning_content': 'SYNTHETIC_PRIVATE_UNDERSCORE',
            'reasoningContent': 'SYNTHETIC_PRIVATE_CAMEL',
            'content': [
                {'type': 'reasoning_content', 'text': 'SYNTHETIC_PRIVATE_BLOCK'},
                {'type': 'text', 'text': 'visible answer', 'thinkingContent': 'SYNTHETIC_PRIVATE_NESTED'},
            ],
        }],
        events=[{'event': 'tool', 'output': {
            'reasoning_details': 'SYNTHETIC_PRIVATE_EVENT', 'status': 'ok',
        }}],
    )
    trajectory = public_trajectory(sample, 'baseline')
    assert 'SYNTHETIC_PRIVATE' not in json.dumps(trajectory)
    assert trajectory['messages'][0]['content'] == [{'type': 'text', 'text': 'visible answer'}]
    assert trajectory['events'][0]['output'] == {'status': 'ok'}


def test_public_trajectory_redacts_streaming_private_reasoning_deltas():
    # Streaming adapters can serialize private thought chunks as delta fields
    # or content-block types inside otherwise public assistant/tool records.
    sample = SimpleNamespace(
        id='synthetic', epoch=1,
        messages=[{'role': 'assistant', 'analysis_delta': 'SYNTHETIC_PRIVATE_FIELD',
                   'content': [
                       {'type': 'reasoning_delta', 'text': 'SYNTHETIC_PRIVATE_BLOCK'},
                       {'type': 'thinking.delta', 'text': 'SYNTHETIC_PRIVATE_TYPED'},
                       {'type': 'text', 'text': 'public answer'},
                   ]}],
        events=[{'event': 'tool', 'output': [
            {'channel': 'thinking_delta', 'text': 'SYNTHETIC_PRIVATE_EVENT'},
            {'thinkingDelta': 'SYNTHETIC_PRIVATE_NESTED', 'status': 'ok'},
        ]}],
    )
    trajectory = public_trajectory(sample, 'baseline')
    assert 'SYNTHETIC_PRIVATE' not in json.dumps(trajectory)
    assert trajectory['messages'][0]['content'] == [{'type': 'text', 'text': 'public answer'}]
    assert trajectory['events'][0]['output'] == [{'status': 'ok'}]


def test_public_trajectory_redacts_delimited_reasoning_and_padded_channels():
    # Provider serializers may use spaced/dotted aliases or padded channel labels.
    # Never export the private content merely because the delimiter differs.
    sample = SimpleNamespace(
        id='synthetic', epoch=1,
        messages=[
            {'role': 'assistant', 'reasoning content': 'SYNTHETIC_PRIVATE_FIELD',
             'content': [
                 {'type': 'reasoning.details', 'text': 'SYNTHETIC_PRIVATE_BLOCK'},
                 {'type': 'text', 'text': 'visible answer'},
             ]},
            {'role': 'assistant', 'channel': ' analysis ', 'content': 'SYNTHETIC_PRIVATE_MESSAGE'},
            {'role': 'assistant', 'channel': 'final', 'content': 'public answer'},
        ],
        events=[{'event': 'tool', 'output': [
            {'channel': ' Thinking ', 'text': 'SYNTHETIC_PRIVATE_EVENT'},
            {'reasoning.details': 'SYNTHETIC_PRIVATE_NESTED', 'status': 'ok'},
            {'channel': 'final', 'text': 'public result'},
        ]}],
    )
    trajectory = public_trajectory(sample, 'baseline')
    assert 'SYNTHETIC_PRIVATE' not in json.dumps(trajectory)
    assert trajectory['messages'] == [
        {'role': 'assistant', 'content': [{'type': 'text', 'text': 'visible answer'}]},
        {'role': 'assistant', 'channel': 'final', 'content': 'public answer'},
    ]
    assert trajectory['events'][0]['output'] == [
        {'status': 'ok'}, {'channel': 'final', 'text': 'public result'},
    ]


def test_public_trajectory_redacts_reasoning_blocks_in_mapping_positions():
    sample = SimpleNamespace(
        id='synthetic', epoch=1,
        messages=[
            {'role': 'assistant', 'content': {
                'type': 'reasoning', 'text': 'SYNTHETIC_PRIVATE_CONTENT',
            }, 'status': 'ok'},
            {'role': 'assistant', 'type': 'thinking',
             'text': 'SYNTHETIC_PRIVATE_TOP_LEVEL'},
            {'role': 'assistant', 'content': {
                'type': 'text', 'text': 'visible answer',
            }},
        ],
        events=[{'event': 'tool', 'output': {
            'private_block': {'type': 'redacted_thinking', 'data': 'SYNTHETIC_PRIVATE_EVENT'},
            'result': 'public result',
        }}],
    )
    trajectory = public_trajectory(sample, 'baseline')
    assert 'SYNTHETIC_PRIVATE' not in json.dumps(trajectory)
    assert trajectory['messages'] == [
        {'role': 'assistant', 'status': 'ok'},
        {'role': 'assistant', 'content': {'type': 'text', 'text': 'visible answer'}},
    ]
    assert trajectory['events'][0]['output'] == {'result': 'public result'}


def test_public_trajectory_redacts_private_reasoning_inside_tuple_sequences():
    # Some tool/provider adapters use tuples; JSON export still serializes them as arrays.
    sample = SimpleNamespace(
        id='synthetic', epoch=1,
        messages=[{'role': 'assistant', 'content': (
            {'type': 'thinking', 'thinking': 'SYNTHETIC_PRIVATE_MESSAGE'},
            {'type': 'text', 'text': 'visible answer', 'reasoning': 'SYNTHETIC_PRIVATE_FIELD'},
        )}],
        events=[{'event': 'tool', 'output': (
            {'type': 'reasoning', 'text': 'SYNTHETIC_PRIVATE_EVENT'},
            {'result': 'public result'},
        )}],
    )
    trajectory = public_trajectory(sample, 'baseline')
    assert 'SYNTHETIC_PRIVATE' not in json.dumps(trajectory)
    assert trajectory['messages'][0]['content'] == [{'type': 'text', 'text': 'visible answer'}]
    assert trajectory['events'][0]['output'] == [{'result': 'public result'}]


@pytest.mark.parametrize('field', ('reasoning_text', 'reasoningText', 'thinking_text', 'thinkingText'))
def test_public_trajectory_redacts_provider_reasoning_text_aliases(field):
    # Private model reasoning must not survive under a provider's text alias.
    sample = SimpleNamespace(
        id='synthetic', epoch=1,
        messages=[{'role': 'assistant', 'content': [
            {'type': 'text', 'text': 'public answer', field: 'SYNTHETIC_PRIVATE_NESTED'},
            {'type': field, 'text': 'SYNTHETIC_PRIVATE_BLOCK'},
        ]}],
        events=[{'event': 'tool', 'output': {
            field: 'SYNTHETIC_PRIVATE_EVENT', 'status': 'ok',
        }}],
    )
    trajectory = public_trajectory(sample, 'baseline')
    assert 'SYNTHETIC_PRIVATE' not in json.dumps(trajectory)
    assert trajectory['messages'][0]['content'] == [{'type': 'text', 'text': 'public answer'}]
    assert trajectory['events'][0]['output'] == {'status': 'ok'}


@pytest.mark.parametrize('field', ('chain_of_thought', 'chainOfThought', 'chain-of-thought', 'chainofthought'))
def test_public_trajectory_redacts_chain_of_thought_aliases(field):
    # Some providers label private reasoning as chain-of-thought rather than thinking.
    sample = SimpleNamespace(
        id='synthetic', epoch=1,
        messages=[{'role': 'assistant', 'content': [
            {'type': 'text', 'text': 'public answer', field: 'SYNTHETIC_PRIVATE_FIELD'},
            {'type': field, 'text': 'SYNTHETIC_PRIVATE_BLOCK'},
        ]}],
        events=[{'event': 'tool', 'output': {
            field: 'SYNTHETIC_PRIVATE_EVENT', 'status': 'ok',
        }}],
    )
    trajectory = public_trajectory(sample, 'baseline')
    assert 'SYNTHETIC_PRIVATE' not in json.dumps(trajectory)
    assert trajectory['messages'][0]['content'] == [{'type': 'text', 'text': 'public answer'}]
    assert trajectory['events'][0]['output'] == {'status': 'ok'}


def test_public_trajectory_filters_privileged_mapping_messages_and_keeps_mapping_events():
    sample = SimpleNamespace(
        id='fixture', epoch=1,
        messages=[
            {'role': 'system', 'content': 'SYNTHETIC_SYSTEM_PRIVATE'},
            {'role': 'developer', 'content': 'SYNTHETIC_DEVELOPER_PRIVATE'},
            SimpleNamespace(role='developer', model_dump=lambda **kwargs: {
                'role': 'developer', 'content': 'SYNTHETIC_OBJECT_PRIVATE',
            }),
            {'role': 'user', 'content': 'public task'},
        ],
        events=[
            {'event': 'tool', 'function': 'bash', 'arguments': {'cmd': 'echo harmless'}},
            {'event': 'approval', 'decision': 'approve'},
            {'event': 'message', 'content': 'not a tool event'},
        ],
    )
    trajectory = public_trajectory(sample, 'baseline')
    assert trajectory['messages'] == [{'role': 'user', 'content': 'public task'}]
    assert [event['event'] for event in trajectory['events']] == ['tool', 'approval']
    assert 'PRIVATE' not in json.dumps(trajectory)


def test_public_trajectory_fails_closed_on_conflicting_or_unknown_message_roles():
    sample = SimpleNamespace(
        id='fixture', epoch=1,
        messages=[
            {'role': 'SYSTEM', 'content': 'SYNTHETIC_UPPERCASE_PRIVATE'},
            {'role': 'admin', 'content': 'SYNTHETIC_UNKNOWN_PRIVATE'},
            SimpleNamespace(role='developer', model_dump=lambda **kwargs: {
                'role': 'user', 'content': 'SYNTHETIC_DISGUISED_PRIVATE',
            }),
            SimpleNamespace(role='system', model_dump=lambda **kwargs: {
                'role': None, 'content': 'SYNTHETIC_NULL_PRIVATE',
            }),
            {'role': 'user', 'content': 'public task'},
            {'role': 'assistant', 'content': 'public answer'},
            {'role': 'tool', 'content': 'public tool response'},
        ],
        events=[],
    )
    trajectory = public_trajectory(sample, 'baseline')
    assert [message['role'] for message in trajectory['messages']] == ['user', 'assistant', 'tool']
    assert 'PRIVATE' not in json.dumps(trajectory)


def test_public_trajectory_excludes_private_channels_even_when_dump_disagrees():
    sample = SimpleNamespace(
        id='synthetic', epoch=1,
        messages=[
            {'role': 'assistant', 'channel': 'private', 'content': 'SYNTHETIC_PRIVATE_MESSAGE'},
            SimpleNamespace(role='assistant', channel='analysis', model_dump=lambda **kwargs: {
                'role': 'assistant', 'channel': 'final',
                'content': 'SYNTHETIC_PRIVATE_DISGUISED',
            }),
            {'role': 'assistant', 'channel': 'final', 'content': [
                {'channel': 'reasoning', 'text': 'SYNTHETIC_PRIVATE_NESTED'},
                {'type': 'text', 'text': 'public answer'},
            ]},
        ],
        events=[
            {'event': 'tool', 'channel': 'thinking', 'result': 'SYNTHETIC_PRIVATE_EVENT'},
            {'event': 'tool', 'output': {
                'channel': 'analysis', 'text': 'SYNTHETIC_PRIVATE_OUTPUT',
            }, 'status': 'ok'},
            {'event': 'tool', 'channel': 'commentary', 'result': 'public result'},
        ],
    )
    trajectory = public_trajectory(sample, 'baseline')
    assert 'SYNTHETIC_PRIVATE' not in json.dumps(trajectory)
    assert trajectory['messages'] == [
        {'role': 'assistant', 'channel': 'final',
         'content': [{'type': 'text', 'text': 'public answer'}]},
    ]
    assert trajectory['events'] == [
        {'event': 'tool', 'status': 'ok'},
        {'event': 'tool', 'channel': 'commentary', 'result': 'public result'},
    ]


def test_public_trajectory_excludes_private_channels_serialized_as_objects():
    sample = SimpleNamespace(
        id='synthetic', epoch=1,
        messages=[
            {'role': 'assistant', 'channel': {'value': 'analysis'},
             'content': 'SYNTHETIC_PRIVATE_MESSAGE'},
            {'role': 'assistant', 'channel': {'name': 'thinking'},
             'content': 'SYNTHETIC_PRIVATE_NAMED'},
            {'role': 'assistant', 'channel': {'value': 'final'}, 'content': [
                {'channel': {'value': 'reasoning'}, 'text': 'SYNTHETIC_PRIVATE_NESTED'},
                {'type': 'text', 'text': 'public answer'},
            ]},
        ],
        events=[
            {'event': 'tool', 'channel': {'value': 'analysis'},
             'result': 'SYNTHETIC_PRIVATE_EVENT'},
            {'event': 'tool', 'output': [
                {'channel': {'name': 'thinking'}, 'text': 'SYNTHETIC_PRIVATE_OUTPUT'},
                {'channel': {'name': 'commentary'}, 'text': 'public output'},
            ]},
        ],
    )
    trajectory = public_trajectory(sample, 'baseline')
    assert 'SYNTHETIC_PRIVATE' not in json.dumps(trajectory)
    assert trajectory['messages'] == [
        {'role': 'assistant', 'channel': {'value': 'final'},
         'content': [{'type': 'text', 'text': 'public answer'}]},
    ]
    assert trajectory['events'] == [
        {'event': 'tool', 'output': [
            {'channel': {'name': 'commentary'}, 'text': 'public output'},
        ]},
    ]


def test_public_trajectory_excludes_private_block_types_serialized_as_objects():
    sample = SimpleNamespace(
        id='synthetic', epoch=1,
        messages=[
            {'role': 'assistant', 'channel': 'final', 'content': [
                {'type': {'value': 'reasoning'}, 'text': 'SYNTHETIC_PRIVATE_TYPE'},
                {'type': {'name': 'thinking'}, 'text': 'SYNTHETIC_PRIVATE_NAMED_TYPE'},
                {'type': {'value': 'text'}, 'text': 'public answer'},
            ]},
        ],
        events=[
            {'event': 'tool', 'output': [
                {'type': {'name': 'analysis'}, 'text': 'SYNTHETIC_PRIVATE_EVENT_TYPE'},
                {'type': 'text', 'text': 'public output'},
            ]},
        ],
    )
    trajectory = public_trajectory(sample, 'baseline')
    assert 'SYNTHETIC_PRIVATE' not in json.dumps(trajectory)
    assert trajectory['messages'][0]['content'] == [
        {'type': {'value': 'text'}, 'text': 'public answer'},
    ]
    assert trajectory['events'][0]['output'] == [
        {'type': 'text', 'text': 'public output'},
    ]


def test_execute_benchmark_reads_actual_model_from_eval_spec(monkeypatch, tmp_path):
    import inspect_ai
    import godprompt_bench.run as run_module

    profile = load_profile(ROOT / 'configs' / 'smoke.json')
    logs = [
        SimpleNamespace(metadata={'condition': 'baseline'}, eval=SimpleNamespace(model='mockllm/model'), samples=[]),
        SimpleNamespace(metadata={'condition': 'godprompt'}, eval=SimpleNamespace(model='mockllm/model'), samples=[]),
    ]
    captured = {}

    monkeypatch.setattr(run_module, 'build_task', lambda *args, **kwargs: object())
    monkeypatch.setattr(inspect_ai, 'eval', lambda *args, **kwargs: logs)

    def fake_manifest(*args, actual_models, **kwargs):
        captured['actual_models'] = actual_models
        return {'run_id': 'test-run'}

    monkeypatch.setattr(run_module, 'build_manifest', fake_manifest)
    monkeypatch.setattr(run_module, 'export_run', lambda *args, **kwargs: None)
    monkeypatch.setattr(run_module, 'validate_sample_coverage', lambda *args: None)

    result = execute_benchmark(
        ROOT.parent,
        ROOT,
        profile,
        model='mockllm/model',
        output_dir=tmp_path,
    )

    assert captured['actual_models'] == ['mockllm/model', 'mockllm/model']
    assert result == tmp_path / 'test-run'


@pytest.mark.parametrize('temperature', (float('nan'), float('inf'), float('-inf')))
def test_execute_benchmark_rejects_nonfinite_temperature_before_eval(monkeypatch, tmp_path, temperature):
    import inspect_ai
    import godprompt_bench.run as run_module

    def reject_evaluation(*args, **kwargs):
        raise AssertionError('model evaluation must not start with invalid temperature')

    monkeypatch.setattr(run_module, '_git', lambda *args: 'abc123')
    monkeypatch.setattr(run_module, 'build_task', lambda *args, **kwargs: object())
    monkeypatch.setattr(inspect_ai, 'eval', reject_evaluation)

    with pytest.raises(ValueError, match='temperature must be finite'):
        execute_benchmark(
            ROOT.parent, ROOT, load_profile(ROOT / 'configs' / 'smoke.json'),
            model='mockllm/model', output_dir=tmp_path, temperature=temperature,
        )


def test_execute_benchmark_captures_git_state_before_eval(monkeypatch, tmp_path):
    import inspect_ai
    import godprompt_bench.run as run_module

    profile = load_profile(ROOT / 'configs' / 'smoke.json')
    logs = [
        SimpleNamespace(metadata={'condition': 'baseline'}, eval=SimpleNamespace(model='mockllm/model'), samples=[]),
        SimpleNamespace(metadata={'condition': 'godprompt'}, eval=SimpleNamespace(model='mockllm/model'), samples=[]),
    ]
    events = []

    monkeypatch.setattr(run_module, 'build_task', lambda *args, **kwargs: object())

    def fake_git(repo_root, *args):
        events.append(('git', args))
        if args[0] == 'status':
            return ''
        return 'abc123'

    def fake_eval(*args, **kwargs):
        events.append(('eval', ()))
        return logs

    monkeypatch.setattr(run_module, '_git', fake_git)
    monkeypatch.setattr(inspect_ai, 'eval', fake_eval)
    monkeypatch.setattr(run_module, 'export_run', lambda *args, **kwargs: None)
    monkeypatch.setattr(run_module, 'validate_sample_coverage', lambda *args: None)

    execute_benchmark(
        ROOT.parent,
        ROOT,
        profile,
        model='mockllm/model',
        output_dir=tmp_path,
    )

    assert events[0][0] == 'git'
    assert next(i for i, event in enumerate(events) if event[0] == 'git') < next(
        i for i, event in enumerate(events) if event[0] == 'eval'
    )
