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


def test_text_editor_rejects_windows_reserved_paths_without_accessing_files():
    from godprompt_bench.policy import classify_tool_call

    # Windows treats these names/streams as devices or aliases, not regular files.
    for path in ('CON', 'src/NUL.txt', 'src/COM1.log', 'src/LPT9',
                 'src/file.txt:stream', 'src/name.', 'src/name '):
        assert not validate_workspace_path(path), path
        assert classify_tool_call('text_editor', {'path': path}).reason == 'outside-workspace', path

    for path in ('src/config.txt', 'src/compile.py', 'src/console.log'):
        assert validate_workspace_path(path), path


def test_shell_policy_rejects_network_and_host_mutations():
    assert classify_shell_command('python3 test_visible.py').allowed is True
    assert classify_shell_command('node --test').allowed is True
    assert classify_shell_command('curl https://example.com').allowed is False
    assert classify_shell_command('wget https://example.com').allowed is False
    assert classify_shell_command('git config --global user.name x').allowed is False
    assert classify_shell_command('find / -name package.json').allowed is False
    assert classify_shell_command('cat /etc/hostname').allowed is False
    assert classify_shell_command('touch /tmp/godprompt-bench-marker').allowed is False


def test_shell_policy_rejects_git_network_and_remote_exec_subcommands_without_execution():
    # Git can open network connections even without invoking curl/ssh directly.
    for command in (
        'git fetch origin',
        'git -C repo pull --ff-only',
        'git push origin HEAD',
        'git clone https://example.invalid/repo.git clone-dir',
        'git ls-remote origin',
        'git remote update',
        'git submodule update --init',
        'env git --no-pager fetch origin',
        'git -c color.ui=always fetch origin',
        'git -C repo -c color.ui=always push origin main',
        'GIT.EXE fetch origin',
        'echo ok && git fetch origin',
        'git archive --remote=origin HEAD',
    ):
        assert classify_shell_command(command).reason == 'network-command', command

    for command in ('git status', 'git -C repo diff --stat', 'git log -1',
                    'git -c color.ui=always status'):
        assert classify_shell_command(command).allowed, command


def test_shell_policy_rejects_windows_network_executables_without_execution():
    # Windows executable names are case-insensitive; classify only, never run them.
    for command in (
        'curl.exe https://example.invalid',
        'CURL.EXE https://example.invalid',
        'Wget.Exe https://example.invalid',
        'SSH.EXE example.invalid',
        'scp.exe local.txt example.invalid:remote',
        'Ncat.EXE example.invalid',
        'env curl.exe https://example.invalid',
    ):
        assert classify_shell_command(command).reason == 'network-command', command

    assert classify_shell_command(['CURL.EXE', 'https://example.invalid']).reason == 'network-command'
    for command in (
        'echo curl.exe',
        'printf %s WGET.EXE',
        'python3 test_visible.py --tool=curl.exe',
        'curl-helper test.txt',
    ):
        assert classify_shell_command(command).allowed, command


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


def test_shell_policy_rejects_dynamic_git_aliases():
    for command in (
        "git -c 'alias.check=!curl https://example.invalid' check",
        "git -calias.check='!sh -c true' check",
        "git -C local -c 'alias.check=!python3 -c pass' check",
        "git -c ALIAS.check=other-command check",
        "git --config-env=alias.check=CHECK_ALIAS check",
        "echo ok && git -c 'alias.check=!curl https://example.invalid' check",
    ):
        assert classify_shell_command(command).reason == "dynamic-git-alias", command
    assert classify_shell_command(
        ["git", "-c", "alias.check=!curl https://example.invalid", "check"]
    ).reason == "dynamic-git-alias"
    assert classify_shell_command("git -c color.ui=always status").allowed
    assert classify_shell_command("echo git -c alias.check=x").allowed


def test_shell_policy_rejects_global_git_config_after_options():
    for command in (
        "git -C repo config --global user.name x",
        "git -c color.ui=always config --global user.email example@example.invalid",
        "git --no-pager config --global user.name x",
        "env git -C repo config --global user.name x",
    ):
        assert classify_shell_command(command).reason == "global-git-config", command
    for command in ("git -C repo status", "git -C repo config --local user.name"):
        assert classify_shell_command(command).allowed, command


def test_shell_policy_rejects_system_git_config_outside_workspace():
    # Only classify these commands: --system writes outside the sandbox repo.
    for command in (
        "git config --system user.name x",
        "git -C repo config --system user.email example@example.invalid",
        "git --no-pager config --system core.hooksPath hooks",
        "env git config --system user.name x",
    ):
        assert classify_shell_command(command).reason == "global-git-config", command

    assert classify_shell_command("git config --local user.name x").allowed


def test_tool_call_policy_covers_bash_and_editor_paths():
    from godprompt_bench.policy import classify_tool_call

    assert classify_tool_call('bash', {'cmd': 'python3 test_visible.py'}).allowed is True
    assert classify_tool_call('bash', {'cmd': 'curl https://example.com'}).reason == 'network-command'
    assert classify_tool_call('text_editor', {'path': 'src/app.py'}).allowed is True
    assert classify_tool_call('text_editor', {'path': '../outside.txt'}).reason == 'outside-workspace'
    assert classify_tool_call('text_editor', {'path': '/tmp/marker'}).reason == 'outside-workspace'
    assert classify_tool_call('unknown_tool', {}).reason == 'unsupported-tool'


def test_inspect_bash_command_argument_uses_current_tool_schema():
    from godprompt_bench.policy import classify_tool_call

    # inspect-ai==0.3.260 exposes bash(command: str), not bash(cmd: str).
    assert classify_tool_call('bash', {'command': 'python3 test_visible.py'}).allowed
    assert classify_tool_call('bash', {'command': 'curl https://example.invalid'}).reason == 'network-command'
    assert classify_tool_call('bash', {'command': 'bash -c true'}).reason == 'nested-shell-interpreter'
    assert classify_tool_call('bash', {
        'cmd': 'python3 test_visible.py',
        'command': 'curl https://example.invalid',
    }).reason == 'invalid-bash-command'


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


def test_shell_policy_rejects_other_shell_interpreters_without_execution():
    # Classifier inputs only; never launch a shell or execute the payload.
    for command in (
        'pwsh -NoProfile -Command Write-Output',
        'powershell.exe -NoProfile -File local.ps1',
        'PowerShell.EXE -NoProfile -Command Write-Output',
        'cmd.exe /c local.cmd',
        'cmd.exe local.cmd',
        'fish -c echo-ok',
        'csh -c echo-ok',
        'tcsh -c echo-ok',
        'env pwsh -NoProfile -Command Write-Output',
    ):
        assert classify_shell_command(command).reason == 'nested-shell-interpreter', command

    assert classify_shell_command(['pwsh', '-NoProfile', '-File', 'local.ps1']).reason == 'nested-shell-interpreter'

    for command in (
        'echo pwsh',
        'printf %s cmd.exe',
        'python3 test_visible.py --shell=pwsh',
        'python3 -m pytest -q',
    ):
        assert classify_shell_command(command).allowed, command


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


def test_shell_policy_rejects_module_package_managers_without_running_them():
    # Python -m can launch installers that are already blocked as standalone binaries.
    for command in (
        'python3 -m uv pip install demo-package',
        'python3.12 -I -m poetry add demo-package',
        'pypy3 -mpipx install demo-package',
        'env python3 -m pdm add demo-package',
        'python -m hatch env create',
        'python -m build',
        'python -m poetry.console add demo-package',
        'echo ok && python3 -m uv pip install demo-package',
    ):
        assert classify_shell_command(command).reason == 'network-command', command
    assert classify_shell_command(['python3', '-m', 'uv', 'pip', 'install']).reason == 'network-command'
    for command in ('python3 -m pytest -q', 'python -m json.tool data.json',
                    'python3 local_script.py -m poetry'):
        assert classify_shell_command(command).allowed, command


def test_shell_policy_rejects_package_manager_network_commands():
    for command in (
        'pip install demo-package',
        'pip3 download demo-package',
        'pip3.12 wheel demo-package',
        'pip --disable-pip-version-check install demo-package',
        'PIP_NO_CACHE_DIR=1 pip install demo-package',
        'env PIP_NO_CACHE_DIR=1 pip3 install demo-package',
        'env -u PIP_INDEX_URL pip download demo-package',
        'npm install',
        'npm ci',
        'NODE_ENV=test npm ci',
        'npm --prefix fixtures ci',
        'npm exec demo-tool',
        'npm x demo-tool',
        'npx --yes demo-tool',
        'command npm install',
        'python3 -m ensurepip',
        'python3 -mpip install demo-package',
        'python3 -m pip._internal install demo-package',
        'python3 -m http.server',
    ):
        assert classify_shell_command(command).reason == 'network-command', command
    for argv in (
        ['pip3', 'install', 'demo-package'],
        ['npm', 'ci'],
        ['env', 'npm', 'install', '--offline'],
        ['/usr/bin/npx', '--yes', 'demo-tool'],
    ):
        assert classify_shell_command(argv).reason == 'network-command', argv
    for command in (
        'pip list', 'npm test', 'npm run test', 'npm run build',
        'node test_visible.js npm install', 'python3 test_visible.py pip install',
        'echo npm install', 'printf %s npx'
    ):
        assert classify_shell_command(command).allowed, command


def test_shell_policy_rejects_package_manager_config_mutations():
    # Classification only: these otherwise write user or system config files.
    for command in (
        'pip config set global.index-url https://example.invalid',
        'pip3 config --user unset global.index-url',
        'npm config set registry https://example.invalid',
        'npm config --global delete proxy',
        'npm set registry https://example.invalid',
    ):
        assert classify_shell_command(command).reason == 'network-command', command

    for command in ('pip config list', 'pip config get global.index-url', 'npm config get registry'):
        assert classify_shell_command(command).allowed, command


def test_shell_policy_denies_modern_package_manager_network_entrypoints():
    for command in (
        'pnpm add demo-package', 'pnpm --dir fixtures install',
        'pnpm dlx demo-tool', 'pnpx demo-tool', 'corepack pnpm add demo-package',
        'corepack prepare pnpm@latest', 'env -u CI pnpm add demo-package',
        'yarn add demo-package', 'yarn --cwd fixtures install',
        'yarn dlx demo-tool', 'yarnpkg add demo-package',
        'command yarn add demo-package', 'corepack yarn add demo-package',
        'bun add demo-package', 'bunx demo-tool',
        'uv pip install demo-package', 'uv pip compile requirements.in',
        'uv tool run demo-tool', 'uv sync', 'uvx demo-tool',
        'pipx install demo-package', 'poetry add demo-package',
        'poetry -C fixtures install',
    ):
        assert classify_shell_command(command).reason == 'network-command', command
    for command in (
        'pnpm test', 'yarn test', 'bun test', 'uv pip list',
        'pipx list', 'poetry show', 'corepack --version',
        'echo pnpm add demo-package',
        'python3 test_visible.py yarn add demo-package',
    ):
        assert classify_shell_command(command).allowed, command


def test_shell_policy_honors_env_chdir_when_classifying_package_commands():
    for command in (
        'env -C fixtures npm install demo-package',
        'env --chdir=fixtures pip download demo-package',
        'env --chdir fixtures npm ci',
        'env -Cfixtures pip3 wheel demo-package',
        'env -i -C fixtures npm exec demo-package',
    ):
        assert classify_shell_command(command).reason == 'network-command', command
    assert classify_shell_command(['env', '-C', 'fixtures', 'npm', 'install']).reason == 'network-command'
    for command in ('env -C fixtures npm test', 'env --chdir=fixtures pip list'):
        assert classify_shell_command(command).allowed, command


def test_shell_policy_denies_attached_chdir_paths_outside_workspace():
    for command in ('env -C/ npm test', 'env -C../ npm test', 'env -C~ npm test'):
        assert not classify_shell_command(command).allowed, command
    assert classify_shell_command('env -Cfixtures npm test').allowed


def test_shell_policy_rejects_compound_commands_without_spaces():
    assert classify_shell_command('echo ok;echo done').reason == 'compound-shell-command'
    assert classify_shell_command('echo ok&&echo done').reason == 'compound-shell-command'
    assert classify_shell_command('echo ok;curl example.com').reason == 'network-command'
    assert classify_shell_command('echo ok\necho done').reason == 'dynamic-shell-syntax'
    assert classify_shell_command('python3 test_visible.py').allowed is True
    assert classify_shell_command('node --test').allowed is True
    assert classify_shell_command('echo ok > output.txt').allowed is True


def test_shell_policy_rejects_here_string_stdin_code_without_running_it():
    for command in (
        "python3 - <<< 'print(1)'",
        "python3 -<<<'print(1)'",
        "node <<< 'console.log(1)'",
        "cat <<< sample",
        "env python3 - <<< 'print(1)'",
        "echo ok && python3 -<<<'print(1)'",
    ):
        assert classify_shell_command(command).reason == 'dynamic-shell-syntax', command

    assert classify_shell_command(['python3', '-', '<<<', 'print(1)']).reason == 'dynamic-shell-syntax'
    assert classify_shell_command(['python3', '-', '<<<print(1)']).reason == 'dynamic-shell-syntax'

    for command in (
        'cat < input.txt',
        'python3 test_visible.py < input.txt',
        "echo '<<<'",
        'printf %s "<<<"',
        r'echo \<\<\<',
    ):
        assert classify_shell_command(command).allowed, command


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


def test_shell_policy_rejects_node_inline_data_url_preloads():
    # Classification only: the encoded URL payloads must NEVER be executed.
    data_url = 'data:text/javascript,process%2Eexit%281%29'
    for command in (
        f'node --import={data_url} --test',
        f'node --import {data_url} --test',
        f'node --loader={data_url} --test',
        f'node --experimental-loader {data_url} --test',
        f'node --import=DATA:text/javascript,process%2Eexit%281%29 --test',
    ):
        assert classify_shell_command(command).reason == 'inline-interpreter', command

    assert classify_shell_command(['node', f'--import={data_url}', '--test']).reason == 'inline-interpreter'
    assert classify_shell_command('node --import=./test-setup.mjs --test').allowed
    assert classify_shell_command('node --loader=./test-loader.mjs --test').allowed
    assert classify_shell_command('node --test').allowed


def test_shell_policy_rejects_node_options_environment_overrides():
    # NODE_OPTIONS allows process-wide preloads invisible to the normal argv scan.
    for command in (
        'NODE_OPTIONS=--import=data:text/javascript,process%2Eexit%281%29 node --test',
        'env NODE_OPTIONS=--import=./setup.mjs node --test',
        'NODE_OPTIONS=--require=./setup.cjs node --test',
    ):
        assert classify_shell_command(command).reason == 'node-options-override', command
    assert classify_shell_command('echo NODE_OPTIONS=--import=./setup.mjs').allowed


def test_shell_policy_rejects_case_variant_node_options_assignments():
    # Windows environment keys are case-insensitive; classify without running a preload.
    for command in (
        'node_options=--import=./setup.mjs node --test',
        'Node_Options=--require=./setup.cjs node --test',
        'env NoDe_OpTiOnS=--import=data:text/javascript,console%2Elog%281%29 node --test',
    ):
        assert classify_shell_command(command).reason == 'node-options-override', command

    assert classify_shell_command(['env', 'node_options=--require=./setup.cjs', 'node', '--test']).reason == 'node-options-override'
    assert classify_shell_command('echo node_options=--import=./setup.mjs').allowed
    assert classify_shell_command('MY_NODE_OPTIONS=plain node --test').allowed
    assert classify_shell_command('node --test').allowed


def test_shell_policy_rejects_interpreter_startup_environment_assignments():
    # Classify only: these variables can load code before the visible test command.
    for command in (
        'LD_PRELOAD=./hook.so python -m pytest',
        'env LD_AUDIT=./audit.so node --test',
        'PYTHONPATH=./helpers python -m pytest',
        'env PYTHONPATH=./helpers python -m pytest',
        'env pythonpath=./helpers python -m pytest',
    ):
        assert classify_shell_command(command).reason == 'interpreter-env-override', command

    assert classify_shell_command(['env', 'LD_PRELOAD=./hook.so', 'python', '-m', 'pytest']).reason == 'interpreter-env-override'
    assert classify_shell_command('echo LD_PRELOAD=./hook.so').allowed
    assert classify_shell_command("printf '%s' PYTHONPATH=./helpers").allowed
    assert classify_shell_command('MY_LD_PRELOAD=plain python -m pytest').allowed
    assert classify_shell_command('python -m pytest').allowed


def test_shell_policy_rejects_other_language_startup_hooks():
    # These inputs are only classified; no startup hooks or interpreters run.
    for command in (
        'RUBYOPT=-r./preload.rb ruby test.rb',
        'env RuByLiB=./alternate ruby test.rb',
        'PERL5OPT=-MTest::Preload perl test.pl',
        'env PERL5LIB=./alternate perl test.pl',
        'PYTHONSTARTUP=./bootstrap.py python3',
        'env PYTHONHOME=./alternate python3 -m pytest',
        'LD_LIBRARY_PATH=./alternate python3 test_visible.py',
    ):
        assert classify_shell_command(command).reason == 'interpreter-env-override', command

    assert classify_shell_command(['env', 'RUBYOPT=-r./preload.rb', 'ruby', 'test.rb']).reason == 'interpreter-env-override'
    assert classify_shell_command('echo PERL5OPT=-MTest::Preload').allowed
    assert classify_shell_command('MY_RUBYOPT=plain ruby test.rb').allowed
    assert classify_shell_command('ruby test.rb').allowed
