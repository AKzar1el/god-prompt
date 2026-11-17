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
