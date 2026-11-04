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


def test_shell_policy_allows_harmless_command_names_as_literal_output():
    for command in (
        'echo curl',
        'echo bash',
        'echo python3',
        'printf %s wget',
        'printf %s node',
        'echo git config --global',
    ):
        assert classify_shell_command(command).allowed is True, command

    # Literal output never excuses a real second command or dynamic execution.
    assert classify_shell_command('echo curl;curl https://example.com').reason == 'network-command'
    assert classify_shell_command('printf %s bash && bash -c true').reason == 'nested-shell-interpreter'
    assert classify_shell_command('echo $(curl example.com)').reason == 'dynamic-shell-syntax'
    assert classify_shell_command('echo curl > /tmp/output').reason == 'absolute-path'
    assert classify_shell_command('env bash -c true').reason == 'nested-shell-interpreter'
    assert classify_shell_command('python3 -c pass').reason == 'inline-interpreter'


def test_shell_policy_rejects_split_string_env_and_delayed_inline_programs():
    # Only classify these payloads; never execute them.
    for command in (
        "env -S 'sh -c whoami'",
        "env --split-string='bash -c whoami'",
        "env -i -S 'sh -c whoami'",
        "echo ok && env -S 'sh -c whoami'",
        "env -S 'sh -c whoami' || echo denied",
        "python3 -I -B -q -W ignore -c 'print(1)'",
        "node --no-warnings --trace-uncaught --input-type=commonjs --title=x --eval 'console.log(1)'",
        "python3 -I -B -q -W ignore -cprint(1)",
        "node --no-warnings --eval=console.log(1)",
    ):
        assert not classify_shell_command(command).allowed, command

    for command in (
        'python3 -I -B test_visible.py',
        'python3 test_visible.py -c',
        'node script.js --eval',
        'node --test',
        'echo env -S',
    ):
        assert classify_shell_command(command).allowed, command


def test_shell_policy_rejects_subshell_grouping_without_running_payloads():
    for command in (
        '(curl https://example.invalid)',
        '(bash -c whoami)',
        '(python3 -c pass)',
        '(echo ok)',
        'echo ok && (curl https://example.invalid)',
    ):
        assert not classify_shell_command(command).allowed, command

    # Quoted parentheses remain ordinary literal output, not shell grouping.
    assert classify_shell_command('echo "(curl)"').allowed
    assert classify_shell_command("printf '%s' '(bash)'").allowed
