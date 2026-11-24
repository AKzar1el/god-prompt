import json
import subprocess
import sys
from types import SimpleNamespace

import pytest


def _mock_prerequisites(monkeypatch, doctor, *, inspect_version="0.3.260", docker_path="docker"):
    monkeypatch.setattr(doctor.sys, "version_info", (3, 13, 5))
    monkeypatch.setattr(doctor.metadata, "version", lambda name: inspect_version)
    monkeypatch.setattr(doctor.shutil, "which", lambda name: docker_path)


def test_doctor_reports_local_prerequisites_without_model_or_daemon_calls(monkeypatch):
    from godprompt_bench import doctor

    _mock_prerequisites(monkeypatch, doctor)
    calls = []

    def run(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=0, stdout="Docker version 27.4.1, build abcdef")

    monkeypatch.setattr(doctor.subprocess, "run", run)
    report = doctor.check_local_runtime()
    assert report["local_prerequisites_present"] is True
    assert report["checks"]["python"]["status"] == "ok"
    assert report["checks"]["inspect_ai"]["version"] == "0.3.260"
    assert report["checks"]["docker_cli"]["version"] == "27.4.1"
    assert report["docker_daemon_checked"] is False
    assert report["provider_credentials_checked"] is False
    assert report["provider_calls_made"] is False
    assert len(calls) == 1
    assert calls[0][0] == ["docker", "--version"]
    assert calls[0][1]["timeout"] <= 5
    assert calls[0][1].get("shell") is not True


def test_doctor_fails_closed_when_inspect_is_missing_and_docker_unavailable(monkeypatch):
    from godprompt_bench import doctor

    _mock_prerequisites(monkeypatch, doctor, docker_path=None)

    def missing(_name):
        raise doctor.metadata.PackageNotFoundError("inspect-ai")

    monkeypatch.setattr(doctor.metadata, "version", missing)
    monkeypatch.setattr(doctor.subprocess, "run", lambda *_a, **_k: pytest.fail("no Docker executable"))
    report = doctor.check_local_runtime()
    assert report["local_prerequisites_present"] is False
    assert report["checks"]["inspect_ai"]["status"] == "missing"
    assert report["checks"]["docker_cli"]["status"] == "missing"


def test_doctor_rejects_wrong_inspect_version_without_claiming_readiness(monkeypatch):
    from godprompt_bench import doctor

    _mock_prerequisites(monkeypatch, doctor, inspect_version="0.3.261", docker_path=None)
    report = doctor.check_local_runtime()
    assert report["local_prerequisites_present"] is False
    assert report["checks"]["inspect_ai"]["status"] == "version_mismatch"
    assert report["checks"]["inspect_ai"]["required"] == "0.3.260"


def test_doctor_rejects_unsupported_python(monkeypatch):
    from godprompt_bench import doctor

    _mock_prerequisites(monkeypatch, doctor, docker_path=None)
    monkeypatch.setattr(doctor.sys, "version_info", (3, 10, 12))
    report = doctor.check_local_runtime()
    assert report["local_prerequisites_present"] is False
    assert report["checks"]["python"]["status"] == "unsupported"
    assert report["checks"]["python"]["minimum"] == "3.11"


@pytest.mark.parametrize("failure", [
    SimpleNamespace(returncode=1, stdout="failure with possible secret=abc"),
    subprocess.TimeoutExpired(cmd=["docker", "--version"], timeout=3),
    OSError("host-specific credential/path string"),
])
def test_doctor_does_not_reveal_raw_docker_errors(monkeypatch, failure):
    from godprompt_bench import doctor

    _mock_prerequisites(monkeypatch, doctor)

    def failing_run(*_args, **_kwargs):
        if isinstance(failure, BaseException):
            raise failure
        return failure

    monkeypatch.setattr(doctor.subprocess, "run", failing_run)
    report = doctor.check_local_runtime()
    assert report["local_prerequisites_present"] is False
    assert report["checks"]["docker_cli"]["status"] != "ok"
    output = json.dumps(report)
    assert "secret=abc" not in output
    assert "credential/path" not in output


def test_doctor_cli_prints_json_and_nonzero_when_prerequisites_fail(monkeypatch, capsys):
    from godprompt_bench import doctor

    monkeypatch.setattr(sys, "argv", ["godprompt_bench.doctor"])
    monkeypatch.setattr(doctor, "check_local_runtime", lambda: {
        "local_prerequisites_present": False, "provider_calls_made": False,
    })
    with pytest.raises(SystemExit) as exc:
        doctor.main()
    assert exc.value.code == 1
    assert json.loads(capsys.readouterr().out)["local_prerequisites_present"] is False


def test_doctor_cli_success_is_machine_readable(monkeypatch, capsys):
    from godprompt_bench import doctor

    monkeypatch.setattr(sys, "argv", ["godprompt_bench.doctor"])
    monkeypatch.setattr(doctor, "check_local_runtime", lambda: {
        "local_prerequisites_present": True, "provider_calls_made": False,
    })
    doctor.main()
    assert json.loads(capsys.readouterr().out) == {
        "local_prerequisites_present": True, "provider_calls_made": False,
    }


@pytest.mark.parametrize(
    "component,status,expected",
    [
        ("python", "unsupported", "Python 3.11 or newer"),
        ("inspect_ai", "missing", "pip install -e"),
        ("inspect_ai", "version_mismatch", "pinned Inspect AI"),
        ("docker_cli", "missing", "Docker CLI"),
        ("docker_cli", "timeout", "docker --version"),
        ("docker_cli", "unverifiable", "docker --version"),
    ],
)
def test_doctor_text_gives_actionable_local_remediation(monkeypatch, capsys, component, status, expected):
    from godprompt_bench import doctor

    checks = {
        "python": {"status": "ok", "version": "3.13.5", "minimum": "3.11"},
        "inspect_ai": {"status": "ok", "version": "0.3.260", "required": "0.3.260"},
        "docker_cli": {"status": "ok", "version": "27.4.1"},
    }
    checks[component]["status"] = status
    monkeypatch.setattr(sys, "argv", ["godprompt_bench.doctor", "--format", "text"])
    monkeypatch.setattr(doctor, "check_local_runtime", lambda: {
        "local_prerequisites_present": False,
        "checks": checks,
        "docker_daemon_checked": False,
        "provider_calls_made": False,
    })

    with pytest.raises(SystemExit) as exc:
        doctor.main()
    assert exc.value.code == 1
    output = capsys.readouterr().out
    assert expected in output
    assert "NOT READY" in output
    assert "not verify Docker daemon" in output


@pytest.mark.parametrize("inspect_status", ["missing", "version_mismatch"])
@pytest.mark.parametrize(
    "platform,install_command",
    [
        ("win32", r".\.venv\Scripts\python.exe -m pip install -e '.[test,openai]'"),
        ("linux", "python -m pip install -e '.[test,openai]'"),
    ],
)
def test_doctor_inspect_remediation_uses_platform_venv_python(
    monkeypatch, inspect_status, platform, install_command
):
    from godprompt_bench import doctor

    report = {
        "local_prerequisites_present": False,
        "checks": {
            "python": {"status": "ok"},
            "inspect_ai": {"status": inspect_status},
            "docker_cli": {"status": "ok"},
        },
    }
    with monkeypatch.context() as patch:
        patch.setattr(doctor.sys, "platform", platform)
        output = doctor.format_text(report)

    assert install_command in output
    assert "pinned Inspect AI 0.3.260" in output
    assert "No model/provider calls were made" in output


def test_doctor_text_success_and_default_json_stay_distinct(monkeypatch, capsys):
    from godprompt_bench import doctor

    report = {
        "local_prerequisites_present": True,
        "checks": {
            "python": {"status": "ok", "version": "3.13.5", "minimum": "3.11"},
            "inspect_ai": {"status": "ok", "version": "0.3.260", "required": "0.3.260"},
            "docker_cli": {"status": "ok", "version": "27.4.1"},
        },
        "docker_daemon_checked": False,
        "provider_calls_made": False,
    }
    monkeypatch.setattr(doctor, "check_local_runtime", lambda: report)
    monkeypatch.setattr(sys, "argv", ["godprompt_bench.doctor", "--format", "text"])
    doctor.main()
    output = capsys.readouterr().out
    assert "Local prerequisites: PASS" in output
    assert "not verify Docker daemon" in output
    assert not output.startswith("{")

    monkeypatch.setattr(sys, "argv", ["godprompt_bench.doctor"])
    doctor.main()
    assert json.loads(capsys.readouterr().out) == report


def test_doctor_text_uses_only_known_statuses_not_raw_error_text(monkeypatch, capsys):
    from godprompt_bench import doctor

    monkeypatch.setattr(sys, "argv", ["godprompt_bench.doctor", "--format", "text"])
    monkeypatch.setattr(doctor, "check_local_runtime", lambda: {
        "local_prerequisites_present": False,
        "checks": {"docker_cli": {
            "status": "unverifiable", "version": "sensitive-host-error-do-not-print",
        }},
    })
    with pytest.raises(SystemExit):
        doctor.main()
    assert "sensitive-host-error-do-not-print" not in capsys.readouterr().out


def test_doctor_rejects_unknown_output_format_without_probe(monkeypatch, capsys):
    from godprompt_bench import doctor

    monkeypatch.setattr(sys, "argv", ["godprompt_bench.doctor", "--format", "yaml"])
    monkeypatch.setattr(doctor, "check_local_runtime", lambda: pytest.fail("not called"))
    with pytest.raises(SystemExit) as exc:
        doctor.main()
    assert exc.value.code == 2
    assert capsys.readouterr().out == ""
