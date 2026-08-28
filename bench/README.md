# GodPrompt Bench

GodPrompt Bench is a reproducible evaluation harness for testing whether adding `GodPrompt.md` changes software-engineering agent outcomes under controlled conditions.

It compares two conditions:

- **baseline** — a short neutral coding-agent instruction;
- **godprompt** — the same agent with the repository's exact `GodPrompt.md` prepended.

The task prompt, model, tools, sandbox, generation controls, message/time/token budgets, task fixtures, and scorers are otherwise identical. The benchmark is designed to remain useful if GodPrompt wins, loses, or improves only selected categories.

> **Benchmark status:** the evaluation infrastructure and deterministic corpus are published. No reference-model superiority claim should be made until a real frozen run and its raw artifacts are published.

## Corpus

Version 1 contains exactly 40 small deterministic tasks:

| Category | Tasks |
| --- | ---: |
| Implementation / correctness | 8 |
| Debugging | 8 |
| Behavior-preserving refactor | 6 |
| Scope control | 6 |
| Verification / false completion | 6 |
| Tool discipline | 6 |

Python and JavaScript fixtures use standard-library/runtime features only. Each task stores its model-visible files separately from its hidden deterministic verifier. The verifier is materialized only after the agent finishes.

## Metrics

**Primary metric:** hidden deterministic task pass rate.

Secondary metrics are reported separately rather than collapsed into a weighted score:

- false-completion rate;
- scope-violation rate;
- rejected benchmark-policy tool calls;
- verification attempts;
- failed tool calls;
- retries after failed commands;
- provider-reported input/output tokens;
- wall-clock latency (explicitly infrastructure-sensitive);
- completion state and infrastructure failures.

Infrastructure failures are reported separately from model failures. Aggregate output always includes raw counts and denominators.

## Isolation

Tasks run in an Inspect AI Docker sandbox with outbound networking disabled (`network_mode: none`). The model receives only `bash` and `text_editor` tools. An approval policy rejects network commands, absolute/parent-path access, root filesystem searches, and global Git configuration changes.

Tool-policy rejection is itself measured; it does not silently disappear from the run.

## Profiles

`configs/smoke.json` runs six representative tasks once per condition for operational validation.

`configs/full.json` runs all 40 tasks for three epochs per condition:

```text
40 tasks × 2 conditions × 3 epochs = 240 samples
```

The full profile is the reference-run shape. Multiple epochs are retained as individual observations rather than hiding variance behind one score.

## Install

Python 3.11+ and Docker are required. Node.js is provided inside the task sandbox.

```bash
cd bench
python -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
pip install -e '.[test,openai]'
python -m pytest -q
```

The benchmark pins `inspect-ai==0.3.260` so a benchmark commit resolves to a specific evaluation framework version.

## Run

Inspect model names include their provider prefix. For example, the current OpenAI flagship model can be addressed as `openai/gpt-5.6-sol`.

Smoke run:

```bash
python -m godprompt_bench.run \
  --profile smoke \
  --model openai/gpt-5.6-sol \
  --seed 7 \
  --reasoning-effort medium \
  --reasoning-mode standard
```

Full run:

```bash
python -m godprompt_bench.run \
  --profile full \
  --model openai/gpt-5.6-sol \
  --seed 7 \
  --reasoning-effort medium \
  --reasoning-mode standard
```

Generation controls are optional because providers do not expose identical knobs. Unspecified/unsupported controls are recorded as null rather than falsely described as frozen. For a reference run, choose supported controls explicitly and keep them unchanged across both conditions.

The runner disables Inspect response caching and provider prompt caching where the provider exposes that control. It also serializes samples (`max_samples=1`, `max_connections=1`) to reduce cross-sample timing interference. Latency remains infrastructure-sensitive.

## Output

A run writes raw Inspect logs plus a public result directory containing:

```text
<run-id>/
├── manifest.json
├── summary.json
├── scores.csv
└── trajectories.jsonl
```

`manifest.json` records the requested and actual model identifiers, supported generation controls, resource limits, exact Inspect/Python versions, benchmark and GodPrompt commit provenance, corpus and sandbox hashes, task counts, and infrastructure failures.

`scores.csv` contains one row per task/condition/epoch. `summary.json` can be regenerated from those rows. `trajectories.jsonl` contains observable non-system messages plus tool/approval events. System prompts are reproducible from the recorded commit hashes and are not duplicated into every trajectory. Reasoning-content blocks are excluded; the benchmark does not request, reconstruct, or publish hidden chain-of-thought.

Credential-like fields are recursively redacted from public JSON/JSONL exports.

## CI

`.github/workflows/bench-verify.yml` is offline and runs on pull requests and `main`. It:

1. installs the pinned benchmark dependencies;
2. validates the existing GodPrompt build sync;
3. runs the complete benchmark unit/corpus suite;
4. builds the Docker sandbox.

It performs **no paid model calls**.

`.github/workflows/bench-run.yml` is `workflow_dispatch` only. It requires a configured provider credential and uploads all run output even when the benchmark command fails, so failed runs remain inspectable.

## Publishing results

Do not publish a claim such as “GodPrompt beats baseline” from harness tests, mocked data, a smoke run, or a selectively filtered run. A published performance claim must identify and link the corresponding full run, model/configuration, commit SHA, raw scores, and run manifest.

Negative or mixed results are valid results. Do not remove losing tasks after observing them; corpus changes require a new benchmark version.

## Methodology references

The harness uses the current Inspect AI APIs for agents, approval policies, deterministic scoring, epochs, sample limits, sandboxing, and evaluation logs:

- https://inspect.aisi.org.uk/
- https://inspect.aisi.org.uk/agents.html
- https://inspect.aisi.org.uk/scoring.html
- https://inspect.aisi.org.uk/sandboxing.html
- https://inspect.aisi.org.uk/approval.html

For OpenAI model configuration, use the current model documentation rather than assuming parameter support across model families:

- https://developers.openai.com/api/docs/models
- https://developers.openai.com/api/docs/guides/latest-model
