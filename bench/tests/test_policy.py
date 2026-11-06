from godprompt_bench.policy import classify_shell_command, validate_workspace_path


def test_workspace_paths_stay_relative():
    assert validate_workspace_path('src/app.py') is True
    assert validate_workspace_path('nested/test.mjs') is True
    assert validate_workspace_path('../secret') is False
    assert validate_workspace_path('/etc/hostname') is False
    assert validate_workspace_path('src/../../secret') is False


def test_text_editor_paths_reject_windows_escapes_and_workspace_root():
    from godprompt_bench.policy import classify_tool_call

    # These are classified only; no host paths or editor tools are accessed.
    for path in (
        r'..\secret.txt',
        r'src\..\secret.txt',
        r'C:\secret.txt',
        r'C:secret.txt',
        r'\\server\share\secret.txt',
        r'\Windows\win.ini',
        '.',
        './',
    ):
        assert not validate_workspace_path(path), path
        assert classify_tool_call('text_editor', {'path': path}).reason == 'outside-workspace', path

    for path in ('src/app.py', 'nested/test.mjs', './src/app.py'):
        assert validate_workspace_path(path), path
        assert classify_tool_call('text_editor', {'path': path}).allowed, path


def test_shell_policy_rejects_network_and_host_mutations():
    assert classify_shell_command('python3 test_visible.py').allowed is True
    assert classify_shell_command('node --test').allowed is True
    assert classify_shell_command('curl https://example.com').allowed is False
    assert classify_shell_command('wget https://example.com').allowed is False
    assert classify_shell_command('git config --global user.name x').allowed is False
    assert classify_shell_command('find / -name package.json').allowed is False
    assert classify_shell_command('cat /etc/hostname').allowed is False
    assert classify_shell_command('touch /tmp/godprompt-bench-marker').allowed is False


def test_shell_policy_rejects_paths_hidden_in_option_assignments():
    # Classification only: these GNU options would write outside the workspace.
    for command, reason in (
        ('cp src.txt --target-directory=/tmp', 'absolute-path'),
        ('sort --output=/tmp/result.txt input.txt', 'absolute-path'),
        ('cp --target-directory=../outside src.txt', 'parent-path'),
        ('sort --output=../../result.txt src.txt', 'parent-path'),
    ):
        assert classify_shell_command(command).reason == reason, command

    # Ordinary workspace-relative option values must remain allowed.
    assert classify_shell_command('sort --output=results.txt input.txt').allowed
    assert classify_shell_command('git -c color.ui=always status').allowed


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


def test_shell_policy_rejects_versioned_inline_interpreter_aliases():
    # Classify adversarial commands as strings; never execute the payload.
    for command in (
        "python3.11 -c 'print(1)'",
        "python3.12 -I -c 'print(1)'",
        "env python3.13 -c 'print(1)'",
        "pypy3 -c 'print(1)'",
        "nodejs --eval 'console.log(1)'",
        "nodejs -p '1 + 1'",
        "node --print '1 + 1'",
        "perl5.36 -e 'print(1)'",
        "perl5.36 -E 'say 1'",
        "ruby3.2 -e 'puts 1'",
        "php -r 'echo 1;'",
        "php8.3 -r 'echo 1;'",
        "echo ok && python3.12 -c 'print(1)'",
        "echo ok && nodejs --print '1 + 1'",
    ):
        assert classify_shell_command(command).reason == 'inline-interpreter', command

    # Invoking an ordinary local script must remain possible.
    for command in (
        'python3.12 test_visible.py',
        'nodejs --test',
        'pypy3 test_visible.py',
        'perl5.36 test_visible.pl',
        'echo python3.12',
    ):
        assert classify_shell_command(command).allowed, command

    for argv in (
        ['python3.12', '-c', 'print(1)'],
        ['/usr/bin/python3.11', '-I', '-c', 'print(1)'],
        ['nodejs', '-p', '1 + 1'],
        ['php8.3', '-r', 'echo 1;'],
    ):
        assert classify_shell_command(argv).reason == 'inline-interpreter', argv


def test_shell_policy_rejects_inline_code_after_interpreter_option_operands():
    # These are data-only classifier inputs; no code payload is executed.
    for command in (
        "php -d display_errors=1 -r 'echo 1;'",
        "php8.3 -d display_errors=1 -r 'echo 1;'",
        "php -ddisplay_errors=1 -r 'echo 1;'",
        "ruby -I lib -e 'puts 1'",
        "ruby3.2 -I lib -e 'puts 1'",
        "perl -I lib -e 'print 1'",
        "perl5.36 -I lib -E 'say 1'",
    ):
        assert classify_shell_command(command).reason == 'inline-interpreter', command

    for argv in (
        ['php', '-d', 'display_errors=1', '-r', 'echo 1;'],
        ['ruby', '-I', 'lib', '-e', 'puts 1'],
        ['perl', '-I', 'lib', '-e', 'print 1'],
    ):
        assert classify_shell_command(argv).reason == 'inline-interpreter', argv

    for command in (
        'php -d display_errors=1 script.php',
        'ruby -I lib script.rb',
        'perl -I lib script.pl',
    ):
        assert classify_shell_command(command).allowed, command


def test_shell_policy_rejects_python_timeit_module_inline_code():
    # The timeit module evaluates a supplied statement; classify only, never run it.
    for command in (
        "python3 -m timeit 'print(1)'",
        "python3.12 -I -m timeit -s 'print(1)'",
        "pypy3 -mtimeit 'print(1)'",
        "env python3 -m timeit 'print(1)'",
    ):
        assert classify_shell_command(command).reason == 'inline-interpreter', command

    for command in (
        'python3 -m pytest -q',
        'python3 script.py -m timeit',
    ):
        assert classify_shell_command(command).allowed, command


def test_shell_policy_rejects_python_debugger_module_entry_points():
    # pdb can execute debugger commands including Python statements. Data-only strings.
    for command in (
        'python3 -m pdb test_visible.py',
        "python3.12 -I -m pdb -c '!print(1)' test_visible.py",
        'pypy3 -mpdb test_visible.py',
        'env python3 -m pdb test_visible.py',
    ):
        assert classify_shell_command(command).reason == 'inline-interpreter', command

    assert classify_shell_command(['python3', '-m', 'pdb', 'test_visible.py']).reason == 'inline-interpreter'

    # Do not reject harmless module names after the actual script operand.
    for command in ('python3 -m pytest -q', 'python3 test_visible.py -m pdb', 'echo pdb'):
        assert classify_shell_command(command).allowed, command


def test_shell_policy_rejects_python_interactive_module_entry_points():
    # These inputs are classified as data; no interactive modules are launched.
    for command in (
        'python3 -m code',
        'python3.12 -I -m asyncio',
        'pypy3 -mcode',
        'env python3 -masyncio',
        'echo ok && python3 -m code',
    ):
        assert classify_shell_command(command).reason == 'inline-interpreter', command

    assert classify_shell_command(['python3', '-m', 'asyncio']).reason == 'inline-interpreter'

    # Noninteractive modules and module-looking script arguments remain allowed.
    for command in (
        'python3 -m pytest -q',
        'python3 -m json.tool data.json',
        'python3 test_visible.py -m code',
    ):
        assert classify_shell_command(command).allowed, command


def test_shell_policy_rejects_network_capable_python_module_entry_points():
    # Classify only: these strings must never start a server or install packages.
    for command in (
        'python3 -m http.server 8000',
        'python3.12 -I -m http.server',
        'pypy3 -mhttp.server',
        'env python3 -m pip install example-package',
        'python3 -mpip download example-package',
        'echo ok && python3 -m http.server',
    ):
        assert classify_shell_command(command).reason == 'network-command', command

    assert classify_shell_command(['python3', '-m', 'http.server']).reason == 'network-command'
    for command in (
        'python3 -m pytest -q',
        'python3 -m json.tool data.json',
        'python3 test_visible.py -m http.server',
        'echo python3 -m pip install',
    ):
        assert classify_shell_command(command).allowed, command


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
        '(( 1 + 1 ))',
        '((echo ok))',
    ):
        assert not classify_shell_command(command).allowed, command

    # Quoted parentheses remain ordinary literal output, not shell grouping.
    assert classify_shell_command('echo "(curl)"').allowed
    assert classify_shell_command("printf '%s' '(bash)'").allowed


def test_shell_policy_rejects_dynamic_dollar_expansions_without_running_payloads():
    # Classification only: a shell would expand these command names at runtime.
    for command in (
        "$SHELL -c 'echo test'",
        "${SHELL} -c 'echo test'",
        "c$'url' https://example.invalid",
        "p$'ython3' -c 'print(1)'",
        "echo ${USER}",
        'echo "$PATH"',
    ):
        assert classify_shell_command(command).reason == 'dynamic-shell-syntax', command

    # Literal dollars must not become a gratuitous command approval regression.
    for command in (
        "echo 'price $5'",
        "printf '%s' '$PATH'",
        r'echo \$PATH',
        r'echo "\$PATH"',
    ):
        assert classify_shell_command(command).allowed, command
