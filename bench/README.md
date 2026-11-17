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

`configs/half.json` runs 20 tasks for three epochs per condition (120 samples).

`configs/full.json` runs all 40 tasks for three epochs per condition:

```text
40 tasks × 2 conditions × 3 epochs = 240 samples
```

The full profile is the reference-run shape. Multiple epochs are retained as individual observations rather than hiding variance behind one score.

## Install

Python 3.11+ and Docker are required. Node.js is provided inside the task sandbox.

On macOS or Linux:

```bash
cd bench
python -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
pip install -e '.[test,openai]'
python -m pytest -q
```

On Windows PowerShell, start at the repository root and use the virtual environment's Python directly. No script activation or execution-policy change is required:

```powershell
cd bench
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e '.[test,openai]'
.\.venv\Scripts\python.exe -m pytest -q
```

The benchmark pins `inspect-ai==0.3.260` so a benchmark commit resolves to a specific evaluation framework version.

After installing the benchmark dependencies, check local prerequisites without starting a model evaluation:

```bash
python -m godprompt_bench.doctor
```

From Windows PowerShell inside `bench/`, use `.\.venv\Scripts\python.exe -m godprompt_bench.doctor` instead. The doctor command is standard-library-only, so it can also report a missing Inspect AI installation before the benchmark runner can import it. It checks Python 3.11+, the exact pinned Inspect AI version, and the installed Docker **CLI** version, returning structured JSON with a nonzero exit status when prerequisites are absent. It runs only `docker --version`; it never contacts the Docker daemon or a model provider, reads credentials, starts a sandbox, or writes benchmark results. Passing this check **does not prove** the daemon, Docker images, credentials, provider access, or live evaluation will work.

## Run

Inspect model names include their provider prefix, such as `openai/gpt-5.6-sol`. This is an example model ID, not a claim that it is the latest flagship model. Confirm that your account has access to the selected model before a live evaluation; smoke and full runs may incur provider charges.

Before spending provider tokens, preview the selected profile and verify its fixture files offline:

```bash
python -m godprompt_bench.run --list-profiles
python -m godprompt_bench.run --profile smoke --list-tasks
python -m godprompt_bench.run --profile smoke --dry-run
```

`--list-profiles` compares the bundled smoke, half and full profiles in one validated JSON report: task counts, epochs, total planned samples, category coverage and a fixture fingerprint for each. It does not require a model, start Docker, call a provider or write result files. Use it to choose a profile before running the more detailed `--dry-run` preview.

`--list-tasks` shows the selected profile's task IDs, categories and runtimes in their configured order, plus its validated fixture fingerprint. It helps you inspect the task mix before choosing a potentially paid evaluation. Only public task metadata is shown, never fixture contents or hidden verifiers; like the other preview commands, it makes no model or Docker calls and writes no results. Choose another set with `--profile half` or `--profile full`.

`--dry-run` does not require a model; its JSON `model` field is `null` until you optionally supply `--model` to preview a particular selection. It prints planned sample counts, categories, per-sample limits, requested controls and the selected fixture-bundle fingerprint. It makes **no model calls**, starts no Docker sandbox and creates no result directory. It does not prove provider credentials, Docker readiness or model compatibility, and deliberately gives no dollar-cost estimate: actual token usage and provider pricing are not known from the profile limits alone. A live evaluation still requires an explicit `--model` and may incur provider charges.

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

For Windows PowerShell, run from `bench/` with the virtual environment at `.venv`:

```powershell
.\.venv\Scripts\python.exe -m godprompt_bench.run --help
.\.venv\Scripts\python.exe -m godprompt_bench.run --profile smoke --model openai/gpt-5.6-sol --seed 7 --reasoning-effort medium --reasoning-mode standard
.\.venv\Scripts\python.exe -m godprompt_bench.run --profile full --model openai/gpt-5.6-sol --seed 7 --reasoning-effort medium --reasoning-mode standard
```

The `--help` preflight lists CLI options without making a model request or incurring provider charges; it does not verify Docker or provider credentials. The backslashes ending the Bash examples are not PowerShell line continuations. The smoke and full commands run model evaluations and may incur provider charges; checking their syntax does not execute them.

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

The runner fingerprints selected fixtures before evaluation and checks them again before public export. If they change during a run, it refuses to publish a misleading result manifest; Inspect's raw diagnostic logs remain available. This does not prevent provider charges for samples already evaluated, so avoid editing fixtures while a live run is in progress.

The treatment prompt is also checked before and after evaluation. If `GodPrompt.md` changes while tasks are constructed or evaluated, the run refuses to attribute results to an inconsistent prompt; a successful manifest records the fingerprint captured for the evaluated prompt. Do not modify the prompt during a live run. Already-incurred provider charges cannot be reversed.

The sandbox provenance includes SHA-256 hashes for both `sandbox/Dockerfile` and the actual `sandbox/compose.yaml` supplied to Inspect. These identify the checked-in isolation settings (including networking and capabilities), but do not attest to the resolved base-image digest on the execution host.

`scores.csv` contains one row per task/condition/epoch. `summary.json` can be regenerated from those rows. `trajectories.jsonl` contains observable non-system messages plus tool/approval events. System prompts are reproducible from the recorded commit hashes and are not duplicated into every trajectory. Reasoning-content blocks are excluded; the benchmark does not request, reconstruct, or publish hidden chain-of-thought.

To inspect an **existing** public result directory without re-running a potentially billable evaluation, run from `bench/`:

```bash
python -m godprompt_bench.review results/<run-id>
```

This read-only command recomputes baseline, GodPrompt and per-category counts/rates from `scores.csv`, checks that `summary.json` agrees, and checks recorded sample/infrastructure totals against `manifest.json`. Its JSON output includes explicit denominators, run/commit provenance, coverage completeness and cautions for non-full, mocked, incomplete or dirty-source evidence. `within_run_condition_pairs` also counts same-task/epoch baseline-versus-GodPrompt outcomes (both passed, both failed, or only one passed), overall and by category. Only pairs with both model-evaluable conditions and matching categories are counted; `unpaired_task_epochs` records missing, infrastructure-failed or mismatched pairs without exposing task IDs. A zero paired denominator is insufficient evidence, not evidence of parity. Missing, inconsistent or malformed public artifacts fail closed. It does not read trajectories, write results, start Docker or make provider/model calls. A consistent local export **does not** independently authenticate the model run, prove provenance, validate the benchmark methodology or authorize a performance or commercial claim.

For a concise, copyable Markdown evidence summary, add `--format markdown` to the same offline review command. The default remains machine-readable JSON. The Markdown view displays run, coverage, per-condition and per-category rates, matched within-run outcome counts, visible cautions and an explicit warning that a locally consistent export is not independently verified performance evidence. These descriptive outcomes do not establish causality or justify selective performance claims. It never submits or publishes the report.

Credential-like fields are recursively redacted from public JSON/JSONL exports.

## CI

`.github/workflows/bench-verify.yml` is offline and runs on pull requests and `main`. It:

1. installs the pinned benchmark dependencies;
2. validates the existing GodPrompt build sync;
3. runs the complete benchmark unit/corpus suite;
4. builds the Docker sandbox.

It performs **no paid model calls**.

`.github/workflows/bench-run.yml` is `workflow_dispatch` only. It requires a configured provider credential and uploads all run output even when the benchmark command fails, so failed runs remain inspectable.

## Comparing saved results offline

To compare two saved runs without another model call:

```bash
python -m godprompt_bench.review results/<earlier-run-id> --compare results/<later-run-id>
```

Both exports are checked independently. A mismatch in selected fixtures, model, evaluation controls, sandbox, baseline prompt, scored task/condition/epoch/category identities, model-evaluable sample coverage or required metadata suppresses comparison deltas and appears in `comparison_cautions`. Matching manifest fingerprints alone do not establish that the same samples were scored. With aligned metadata and samples, JSON includes condition-level and per-category pass-rate differences, aggregated per-condition paired outcome transitions (`condition_pass_transitions`) and a per-category/condition transition breakdown (`category_pass_transitions`). Each transition counts `fail_to_pass`, `pass_to_fail`, `pass_to_pass`, `fail_to_fail` and `paired_samples`; no task IDs or sample contents are exposed in the transition totals. Infrastructure-failed samples are excluded from paired outcomes. A category/condition with zero model-evaluable paired samples has zero transition counts and a `null` rate difference, not evidence of no change. All differences are descriptive only, not proof of a causal improvement; mocked and non-full runs retain their cautions. The comparison does not modify artifacts, start Docker or call providers.

Add `--format markdown` to render a human-readable comparison with condition/category percentage-point changes, aggregate and per-category paired pass/fail transitions, observed per-condition input/output token, failed-tool-call and retry count changes, and caution labels. Missing provider token usage remains `n/a`, not zero; no provider price or efficiency benefit is estimated. If local metadata or scored samples are not comparable, the Markdown report suppresses all change tables rather than presenting misleading deltas. The default JSON comparison includes nullable `condition_resource_delta`, `condition_pass_transitions` and `category_pass_transitions` data. This is for inspection and review drafts, not an independently validated performance claim.

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
