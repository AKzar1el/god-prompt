"""Regression guard for untrusted GitHub Actions dispatch inputs.

This test never executes hostile input or launches a benchmark provider.
"""

from pathlib import Path


WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "bench-run.yml"


def test_dispatch_inputs_are_environment_bound_not_interpolated_into_bash():
    source = WORKFLOW.read_text(encoding="utf-8")
    run_step = source.split("- name: Run benchmark", 1)[1].split("- name: Upload benchmark artifacts", 1)[0]
    env, bash = run_step.split("run: |", 1)
    inputs = {
        "profile": "BENCH_PROFILE",
        "model": "BENCH_MODEL",
        "seed": "BENCH_SEED",
        "reasoning_effort": "BENCH_REASONING_EFFORT",
        "reasoning_mode": "BENCH_REASONING_MODE",
    }
    for input_name, variable in inputs.items():
        assert f"{variable}: ${{{{ inputs.{input_name} }}}}" in env
        assert f'--{input_name.replace("_", "-")} "${variable}"' in bash
        assert "${{ inputs." not in bash, "untrusted dispatch expression in shell script"

    # An injected single quote and shell substitution are inert data in quoted
    # environment expansions: not embedded inside the parsed shell source.
    hostile = "model'$(touch /tmp/should-not-exist)"
    assert "$(touch" in hostile
    assert hostile not in bash
