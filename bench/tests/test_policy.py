from godprompt_bench.policy import classify_shell_command, validate_workspace_path


def test_workspace_paths_stay_relative():
    assert validate_workspace_path('src/app.py') is True
    assert validate_workspace_path('nested/test.mjs') is True
    assert validate_workspace_path('../secret') is False
    assert validate_workspace_path('/etc/hostname') is False
    assert validate_workspace_path('src/../../secret') is False


def test_shell_policy_rejects_network_and_host_mutations():
    assert classify_shell_command('python3 test_visible.py').allowed is True
    assert classify_shell_command('node --test').allowed is True
    assert classify_shell_command('curl https://example.com').allowed is False
    assert classify_shell_command('wget https://example.com').allowed is False
    assert classify_shell_command('git config --global user.name x').allowed is False
    assert classify_shell_command('find / -name package.json').allowed is False
    assert classify_shell_command('cat /etc/hostname').allowed is False
    assert classify_shell_command('touch /tmp/godprompt-bench-marker').allowed is False


def test_tool_call_policy_covers_bash_and_editor_paths():
    from godprompt_bench.policy import classify_tool_call

    assert classify_tool_call('bash', {'cmd': 'python3 test_visible.py'}).allowed is True
    assert classify_tool_call('bash', {'cmd': 'curl https://example.com'}).reason == 'network-command'
    assert classify_tool_call('text_editor', {'path': 'src/app.py'}).allowed is True
    assert classify_tool_call('text_editor', {'path': '../outside.txt'}).reason == 'outside-workspace'
    assert classify_tool_call('text_editor', {'path': '/tmp/marker'}).reason == 'outside-workspace'
    assert classify_tool_call('unknown_tool', {}).reason == 'unsupported-tool'


def test_shell_policy_rejects_forbidden_commands_hidden_in_compound_shell():
    assert classify_shell_command('python3 test_visible.py && curl https://example.com').reason == 'network-command'
    assert classify_shell_command('echo ok > /tmp/marker').reason == 'absolute-path'
    assert classify_shell_command('echo ok && git config --global user.name x').reason == 'global-git-config'
    assert classify_shell_command('echo ok && find / -name package.json').reason == 'root-filesystem-search'


def test_shell_policy_rejects_nested_interpreters_and_inline_programs():
    assert classify_shell_command("bash -c 'echo ok'").reason == 'nested-shell-interpreter'
    assert classify_shell_command("env sh -c 'echo ok'").reason == 'nested-shell-interpreter'
    assert classify_shell_command("eval 'echo ok'").reason == 'nested-shell-interpreter'
    assert classify_shell_command("source ./local-script.sh").reason == 'nested-shell-interpreter'
    assert classify_shell_command("python3 -c 'print(1)'").reason == 'inline-interpreter'
    assert classify_shell_command("node -e 'console.log(1)'").reason == 'inline-interpreter'
    assert classify_shell_command('echo $(date)').reason == 'dynamic-shell-syntax'
    assert classify_shell_command('echo `date`').reason == 'dynamic-shell-syntax'


def test_shell_policy_rejects_compound_commands_without_spaces():
    assert classify_shell_command('echo ok;echo done').reason == 'compound-shell-command'
    assert classify_shell_command('echo ok&&echo done').reason == 'compound-shell-command'
    assert classify_shell_command('echo ok;curl example.com').reason == 'network-command'
    assert classify_shell_command('echo ok\necho done').reason == 'dynamic-shell-syntax'
    assert classify_shell_command('python3 test_visible.py').allowed is True
    assert classify_shell_command('node --test').allowed is True
    assert classify_shell_command('echo ok > output.txt').allowed is True
