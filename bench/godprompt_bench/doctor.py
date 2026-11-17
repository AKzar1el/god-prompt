"""Read-only local prerequisite check for the GodPrompt benchmark.

This module intentionally uses only the Python standard library so it can
report a missing Inspect installation before the evaluator can be imported.
It never contacts a Docker daemon or a model provider.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from importlib import metadata


EXPECTED_INSPECT_VERSION = "0.3.260"
MINIMUM_PYTHON = (3, 11)
_DOCKER_VERSION = re.compile(r"\bDocker version\s+([0-9][0-9A-Za-z._+\-]*)")


def check_local_runtime() -> dict:
    python_version = tuple(sys.version_info[:3])
    python_ok = python_version[:2] >= MINIMUM_PYTHON
    checks = {
        "python": {
            "status": "ok" if python_ok else "unsupported",
            "version": ".".join(str(part) for part in python_version),
            "minimum": "3.11",
        }
    }

    try:
        inspect_version = metadata.version("inspect-ai")
    except metadata.PackageNotFoundError:
        inspect_version = None
    inspect_ok = inspect_version == EXPECTED_INSPECT_VERSION
    checks["inspect_ai"] = {
        "status": "ok" if inspect_ok else ("missing" if inspect_version is None else "version_mismatch"),
        "version": inspect_version,
        "required": EXPECTED_INSPECT_VERSION,
    }

    docker_executable = shutil.which("docker")
    docker_version = None
    docker_status = "missing" if docker_executable is None else "unverifiable"
    if docker_executable is not None:
        try:
            # --version inspects only the local CLI; 'docker info' may connect
            # to an unexpected remote context and is deliberately not used.
            process = subprocess.run(
                [docker_executable, "--version"],
                capture_output=True,
                text=True,
                check=False,
                shell=False,
                timeout=3,
            )
            if process.returncode == 0:
                match = _DOCKER_VERSION.search(process.stdout)
                if match is not None:
                    docker_version = match.group(1)
                    docker_status = "ok"
        except subprocess.TimeoutExpired:
            docker_status = "timeout"
        except OSError:
            docker_status = "unverifiable"
    checks["docker_cli"] = {
        "status": docker_status,
        "version": docker_version,
    }

    return {
        "schema_version": 1,
        "local_prerequisites_present": all(item["status"] == "ok" for item in checks.values()),
        "checks": checks,
        "docker_daemon_checked": False,
        "provider_credentials_checked": False,
        "provider_calls_made": False,
        "notes": [
            "Only local Python, pinned Inspect AI and Docker CLI prerequisites were checked.",
            "This does not verify Docker daemon availability, image builds, provider credentials or billable-model access.",
        ],
    }


def main() -> None:
    report = check_local_runtime()
    print(json.dumps(report, indent=2, sort_keys=True))
    if not report["local_prerequisites_present"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
