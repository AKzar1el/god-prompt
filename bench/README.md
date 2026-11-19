# GodPrompt Bench

GodPrompt Bench is a reproducible evaluation harness for testing whether adding `GodPrompt.md` changes software-engineering agent outcomes under controlled conditions.

It compares two conditions:

- **baseline** — a short neutral coding-agent instruction;
- **godprompt** — the same agent with the repository's exact `GodPrompt.md` prepended.

The task prompt, model, tools, sandbox, generation controls, message/time/token budgets, task fixtures, and scorers are otherwise identical. The benchmark is designed to remain useful if GodPrompt wins, loses, or improves only selected categories.

> **Benchmark status:** the evaluation infrastructure and deterministic corpus are published. No reference-model superiority claim should be made until a real frozen run and its raw artifacts are published.

## Experimental MCP task-contract arm (Bench 2.0 groundwork)

The original two-condition, frozen 40-task reference benchmark is unchanged.
An **opt-in, offline-only** preview shows the additional sample count and the
exact released MCP source that an eventual third arm would use:

```bash
python -m godprompt_bench.run --profile smoke --dry-run --experimental-mcp-contract
python -m godprompt_bench.run --profile smoke --dry-run --experimental-mcp-contract --format markdown
```

The preview pins GodPrompt MCP `v1.1.1` at
`5934340cd4279d7ce103f344279058f54e0c6668` but performs **no**
MCP, model, Docker, provider, or command calls and writes no results. The
optional third arm is **not** yet connected to Inspect AI evaluation, and
non-dry-run use of the experimental flag is rejected even when a model is set.
This is not evidence of model improvement or approval to spend.

The pure-Python `godprompt_bench.mcp_contract_adapter` supplies the
first offline integration boundary for `classify_task`,
`create_work_contract` and `review_work_evidence`.
It accepts an injected MCP client and only accepts verification events from
trusted tool-result instrumentation, **not agent-written command receipts**.
Each captured output is summarized with a digest rather than exposing raw
output; empty output, missing/nonzero checks, duplicate receipts, unscoped
paths and forbidden operations must remain a hold. In-memory receipts are
lost on context reset rather than restored from unverifiable self-report.
The MCP's ready state is *reported ready for independent review*, never an
independent verification, release approval or completed benchmark.
The adapter independently rejects a purported MCP ready response when its own
required verification receipts are missing, nonzero or outputless; MCP review
cannot override those local observations.

For host-side Inspect integration, `EvidenceSession` now has an opt-in
`observe_inspect_exec` method. A trusted caller must bind a
`InspectExecutionScope(sample_id, attempt_id)` when it creates the session,
then supply the matching scope, real Inspect sandbox `ExecResult`, tool-call
ID, exact approved command, and a complete execution-event indicator. The
method reads the actual process return code, refuses missing/inconsistent
status, cross-sample or cross-attempt receipts, cancelled/incomplete events,
non-text output and oversized captures, and forwards only a digest in its
MCP review payload. This **does not** install an Inspect hook or replace
`bash`/`text_editor` or their existing approval policy. The stock Inspect
`bash` ToolEvent omits the sandbox process return code, so feeding it directly
into the evidence bridge would still be unsound. No live third-arm use is
enabled by this helper.

The opt-in `godprompt_bench.inspect_receipt_bash.receipt_bash_tool` now
implements a **bash-named Inspect tool factory** for future third-arm wiring.
It keeps the stock `command` input, executes the same
`bash --login -c` sandbox call, and returns the same stderr/stdout text while
capturing the sandbox's actual `ExecResult.returncode` for commands that
exactly match one contract verification requirement. A failed, missing,
inconsistent, duplicate, or cross-attempt receipt cannot become a passing
check; unrelated commands do not create verification evidence. It sends
only digest summaries to MCP review, not raw command output.
Each sample and attempt needs its own host-created `EvidenceSession` and
`InspectExecutionScope`. The factory generates surrogate invocation IDs,
**not** native Inspect model tool-call IDs; they cannot establish external
trace correlation. It must only be installed in the original
`bash`/`text_editor` approval-controlled ReAct scaffold, never invoked as
an unapproved execution shortcut. No default agent invokes this factory:
it is an offline-tested building block, **not** an enabled live third arm,
an independent approval, or an outcome/uplift result.

An opt-in `godprompt_bench.agent.experimental_contract_coding_agent` now
assembles that receipt-producing `bash` tool alongside the stock `text_editor`
inside a **single** GodPrompt ReAct agent with the same named
`bash`/`text_editor` approval policy, one attempt, timeout, and prompt as the
existing treatment. Its host must supply a fresh `EvidenceSession` with a
matching `InspectExecutionScope` for every sample and attempt. Scope mismatch
is rejected before assembly. The regular `coding_agent` and benchmark
`build_task` still use their original two-arm setup; nothing invokes the
experimental builder automatically or requests a model run. The remaining
per-sample host orchestration and native Inspect ToolCall correlation are
required before this scaffold can produce trustworthy third-arm traces.

For opt-in per-sample assembly, `experimental_contract_sample_agent` accepts
the host's actual Inspect `TaskState` and an already prepared contract. It
rejects mismatched task text, allowed paths, verification commands or contract
fingerprint, then returns an agent and **new** in-memory evidence session scoped
to that sample ID, epoch and the scaffold's single attempt. The host still must
call this separately for each sample and must retain the returned session for
later evidence review. A matching fingerprint detects alteration, **not** MCP
origin or independent proof. This helper does not register a solver or third
arm, attest native ToolCall IDs, run a model or change existing two-arm runs.

For a host that has **not yet prepared the contract**, opt-in
`prepare_experimental_contract_sample_agent` in `godprompt_bench.agent`
accepts a real Inspect `TaskState`, the injected deterministic MCP client,
and explicit **public** success criteria and forbidden actions. It forwards
only `state.input`, `allowed_paths` and
`expected_verification_commands` from the trusted host metadata, not
unrelated metadata or hidden verifiers. It validates sample/epoch identity
and required inputs before calling `classify_task` and
`create_work_contract`, then binds the prepared contract to a new agent
and evidence session. It returns `(agent, session, contract)` so the host
can retain the scope and review receipts later. Ambiguous classifications,
invalid requirements and mismatched contracts hold without creating an
agent. Call it separately for each sample/epoch. This is deterministic
**preparation only**: it does not register a third arm, run the resulting
agent, execute sandbox commands, invoke a model, authenticate the MCP origin,
or establish native Inspect ToolCall-ID provenance.

The remaining work under
[Bench 2.0 issue #348](https://github.com/AKzar1el/god-prompt/issues/348)
is to wire the new tool into an isolated per-sample, approval-controlled
Inspect execution context (including exact tool-call provenance),
freeze a separate held-out corpus and three-arm run manifest, retain
identical sandboxes/controls, and validate paired uncertainty and raw
anonymized trajectories. Live providers remain separately spend-gated.

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

### Held-out failure corpus preflight (Bench 2.0, opt-in)

Keep the reference 40-task `tasks/manifest.json` unchanged. Author a **separate**
private task manifest using the same TaskSpec fields as the reference corpus,
and a failure-mode sidecar that contains only case IDs and public labels:

```json
{
  "schema": "godprompt.heldout_modes.v1",
  "cases": [
    {"id": "heldout-example-001", "failure_mode": "false_completion"}
  ]
}
```

Run the read-only metadata preflight from `bench/`:

```sh
python -m godprompt_bench.heldout --heldout ../private-heldout/tasks.json --modes ../private-heldout/modes.json
```

It rejects duplicate/overlapping reference task IDs and fixture directories,
invalid paths, incomplete case mappings, duplicate JSON keys and unknown
failure modes. Its JSON report includes task/mode counts, missing failure-mode
coverage and SHA-256 fingerprints, **not** prompts, private fixture contents
or verifier code. Supported modes cover false completion, scope creep, missing
verification, multi-session handoff, misleading receipts, negative instructions,
hidden dependency changes and stale context. Partial pilots report missing
categories instead of pretending to provide full coverage.

For a corpus intended to cover **every** supported failure mode, opt into a
fail-closed coverage gate using `--min-cases-per-mode 1` (or a higher positive
minimum up to 10000). The command exits nonzero and names only deficient mode
labels/counts if the manifest is incomplete. Leave the flag off for exploratory
partial pilots. Passing this metadata gate does not establish sufficient
statistical power, fixture integrity, novelty, or measured model improvement.

To freeze the **actual fixture-bundle bytes**, not just manifest metadata,
opt into a read-only check of a private fixture directory:

```sh
python -m godprompt_bench.heldout --heldout ../private-heldout/tasks.json --modes ../private-heldout/modes.json --fixture-root ../private-heldout
```

Each task's `fixture_dir/fixture.json` must exist under this root and pass
the existing bundle schema. The report adds a deterministic aggregate SHA-256
for the fixture bytes (including hidden verifier source), but no private
contents, case paths or per-case hashes. Missing, linked, malformed or oversized
bundles fail closed. Re-run this preflight before both arms of a comparison and
keep identical fingerprints; changing fixture bytes invalidates a frozen run
even when task/mode manifests have not changed. The opt-in check is capped at
1 MiB per bundle and 64 MiB total and never executes the verifier.

For an automated **freeze check**, save the first complete preflight JSON report
outside the public repository, review and retain it under owner control, then
pass its path on every subsequent preflight:

```sh
python -m godprompt_bench.heldout --heldout ../private-heldout/tasks.json --modes ../private-heldout/modes.json --fixture-root ../private-heldout > ../private-heldout/frozen-preflight.json
python -m godprompt_bench.heldout --heldout ../private-heldout/tasks.json --modes ../private-heldout/modes.json --fixture-root ../private-heldout --expected-report ../private-heldout/frozen-preflight.json
```

The second command exits nonzero when the reference manifest, private task
manifest, mode sidecar, or fixture bytes differ, even if the private verifier
alone changed. It requires a valid saved full report with all four SHA-256
fingerprints and an unchanged fixture count; the result includes
`input_fingerprints_match: true` only when those checks pass. Error messages
identify the changed field but never print private fixture content or hashes.
The saved report is **not signed**: this detects drift relative to the supplied
owner-controlled report, not tampering with that report or corpus novelty.

Without `--fixture-root`, the preflight remains metadata-only and does **not**
read private fixture bundles. Neither mode proves that tasks are truly held out
from training, installs the third arm, runs agents, validates verifier
correctness, or calls a model/provider. Keep private corpus files outside the
public repository and independently audit novelty and verifier isolation
before any controlled paired evaluation. Existing two-arm Bench behavior and
publication/export requirements remain unchanged.

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

For a human-readable readiness summary with actionable local setup steps, run `python -m godprompt_bench.doctor --format text` (or `.\.venv\Scripts\python.exe -m godprompt_bench.doctor --format text` on Windows). This optional format preserves the same exit code and local-only checks; the default JSON output remains unchanged for automation. The text advice never includes raw Docker errors or host paths and does not imply the Docker daemon or model provider was tested.

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

For a copyable, human-readable preflight plan, run `python -m godprompt_bench.run --profile smoke --dry-run --format markdown`. This shows the validated profile, sample/limit budget, categories, optional model and controls, and fixture fingerprint without saving files. JSON remains the default for scripts. The Markdown option is deliberately restricted to `--dry-run`; it neither validates Docker/provider readiness nor estimates spend or proves performance.

For an **opt-in reviewed-plan check** before a potentially billable two-condition run,
preview with the *same* model, profile, seed and generation controls you intend to
use live:

```sh
python -m godprompt_bench.run --profile smoke --model openai/gpt-5.6-sol --seed 7 --dry-run
```

Review the sample counts and limits, then copy the returned `plan_sha256` into
the corresponding live command as `--require-plan-sha256` (64 lowercase hex
characters). The runner recomputes that digest **before** starting Inspect or
calling a provider, and refuses a mismatch. The digest binds the selected task
IDs and fixture bytes, task manifest, GodPrompt prompt, sandbox files, benchmark
Python sources and dependency declaration, profile limits, model and generation controls.
It does not depend on the output directory or estimated prices. A changed input
requires a new reviewed preview; omitting the flag preserves existing live-run
behavior. This is a local drift check, **not** a signature, authorization to
spend, guarantee against changes after launch, or verification of Docker/model
readiness. The experimental third MCP arm remains offline-only even when a plan
fingerprint is provided.

To evaluate a smaller, explicitly selected subset of the bundled corpus, copy a JSON file from `configs/smoke.json`, give it a distinct lowercase `name` (for example `my-check`), and edit `task_ids` and the resource limits. Preview it before any potentially paid run:

```bash
python -m godprompt_bench.run --profile-file my-check.json --list-tasks
python -m godprompt_bench.run --profile-file my-check.json --dry-run --format markdown
```

`--profile-file` is mutually exclusive with `--profile`. Custom profiles may only select existing corpus tasks, have no more than three epochs, and may not exceed the bundled full profile's per-sample limits (30 messages, 300 seconds, 8192 output tokens). Files must be regular JSON files of at most 64 KiB. Reports prefix their profile identity with `custom-` to distinguish them from frozen reference runs. For live evaluation, supplying `--model` remains mandatory and **may incur provider charges**; preview and task listing never contact Docker or a model provider. Custom subset results are not the published full-profile reference benchmark.

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

This read-only command recomputes baseline, GodPrompt and per-category counts/rates from `scores.csv`, checks that `summary.json` agrees, and checks recorded sample/infrastructure totals against `manifest.json`. Its JSON output includes explicit denominators, run/commit provenance, coverage completeness and cautions for non-full, mocked, incomplete or dirty-source evidence. Multiple distinct recorded actual model IDs trigger `mixed_actual_models`: without per-sample model attribution, condition parity cannot be established. Such runs remain reviewable, but cross-run aligned deltas are suppressed even if both runs list the same models. `within_run_condition_pairs` also counts same-task/epoch baseline-versus-GodPrompt outcomes (both passed, both failed, or only one passed), overall and by category. Only pairs with both model-evaluable conditions and matching categories are counted; `unpaired_task_epochs` records missing, infrastructure-failed or mismatched pairs without exposing task IDs. A zero paired denominator is insufficient evidence, not evidence of parity. Missing, inconsistent or malformed public artifacts fail closed. It does not read trajectories, write results, start Docker or make provider/model calls. A consistent local export **does not** independently authenticate the model run, prove provenance, validate the benchmark methodology or authorize a performance or commercial claim.

The reviewer also calculates `paired_pass_uncertainty`: the observed GodPrompt-minus-baseline pass-rate difference over matched task-epochs, plus an **exploratory** 95% task-cluster bootstrap percentile interval when the saved run has at least 10 distinct paired tasks, full coverage, no excluded pairs, one recorded actual model, clean/complete source metadata, and no mock or non-full cautions. It uses 2048 deterministic resamples, drawing entire tasks with all their repeated epochs together rather than falsely treating epochs as independent tasks. When evidence is insufficient, the interval is `null` and `limitations` explains why; the descriptive point difference retains its explicit denominator. The JSON and Markdown outputs never reveal task IDs or private trajectories. Scope-violating historical rows count as failures in both paired outcomes and aggregate rates. A narrow, zero-width or positive interval is **not** an authenticated model result, a causal confidence interval, a generalization guarantee or a performance claim: task dependence, selection, hidden fixture leakage and provider variance still require independent evaluation.

For a concise, copyable Markdown evidence summary, add `--format markdown` to the same offline review command. The default remains machine-readable JSON. The Markdown view displays run, coverage, per-condition and per-category rates, matched within-run outcome counts, visible cautions and an explicit warning that a locally consistent export is not independently verified performance evidence. These descriptive outcomes do not establish causality or justify selective performance claims. It never submits or publishes the report.

For an automated offline coverage check, add `--require-evaluable` to review one saved run. This opt-in gate prints the same JSON or Markdown diagnostics and exits 1 if any requested sample is missing or has an infrastructure failure; otherwise it exits 0. With `--compare`, it checks **both** saved runs and can be combined with `--require-aligned`. Default read-only review remains diagnostic and exits 0 for internally consistent partial results. Passing either gate establishes only local artifact coverage/comparability, not authentic model execution, release readiness or performance superiority.

For a conservative, opt-in **within-run CI signal** use `python -m godprompt_bench.review results/<run-id> --require-nondegrading-pairs`. This prints the normal diagnostics and exits 1 if requested samples are missing, an infrastructure error occurred, a task/epoch lacks a matched baseline/GodPrompt pair, no pairs are evaluable, multiple distinct actual models were reported, or baseline-only passes outnumber GodPrompt-only passes. An equal number of one-sided wins passes; both-pass/both-fail pairs are neutral. This flag is for **one** saved run, not `--compare`. It is an observed paired-outcome check, not a statistical significance test, an authenticated run, a causal improvement claim or permission to publish benchmarks; mock/non-full runs retain their explicit cautions. No provider calls or result writes occur.

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

For automated review or CI, add `--require-aligned` to exit with status 1 when
the runs cannot be compared. The JSON or Markdown diagnostics are still printed
(including `comparison_cautions`), so a failed check can explain the mismatch.
Without this flag, an unaligned comparison remains a successful read-only report.
This gate checks local comparability only: a successful exit is not proof of
authentic model execution or performance improvement.

To fail a CI step when the **later GodPrompt condition has a net loss of passed
tasks** relative to the earlier result, add `--require-no-godprompt-regression`
to the comparison command. This opt-in check requires aligned scored samples,
complete model-evaluable coverage in both runs, and at least one fully matched
baseline/GodPrompt task-epoch pair with no exclusions. It exits 1 on insufficient
evidence or when GodPrompt pass-to-fail transitions outnumber fail-to-pass
transitions; equal numbers pass. The normal JSON or Markdown comparison is printed
before the exit status, and neither artifact is modified. This checks **net**
GodPrompt pass changes across matched tasks, not category-by-category guarantees
or causality. A passing mocked, non-full or locally generated comparison is not
independent performance verification or permission to publish a claim.

For a stricter offline CI review, use
`--require-no-godprompt-category-regression` with `--compare`. This returns
status 1 if **any** represented task category has more GodPrompt pass-to-fail
than fail-to-pass transitions, even when gains in other categories make the
overall pass count improve. It also fails closed on unaligned exports, missing
or infrastructure-failed samples, or excluded task-epoch pairs; each category
must have at least one matched model-evaluable sample. Like the existing net
gate, it prints diagnostics before exiting, never calls providers or modifies
artifacts, and does not establish causality or independently verified uplift.

Both exports are checked independently. A mismatch in selected fixtures, model, evaluation controls, sandbox, baseline prompt, scored task/condition/epoch/category identities, model-evaluable sample coverage or required metadata suppresses comparison deltas and appears in `comparison_cautions`. Matching manifest fingerprints alone do not establish that the same samples were scored. With aligned metadata and samples, JSON includes condition-level and per-category pass-rate differences, aggregated per-condition paired outcome transitions (`condition_pass_transitions`) and a per-category/condition transition breakdown (`category_pass_transitions`). Each transition counts `fail_to_pass`, `pass_to_fail`, `pass_to_pass`, `fail_to_fail` and `paired_samples`; no task IDs or sample contents are exposed in the transition totals. The `cross_run_condition_pair_transitions` matrix additionally shows whether the *joint* baseline/GodPrompt outcome for each matching task-epoch stayed the same or moved between both-pass, both-fail and the two single-condition-pass states. Its separate matched/excluded task-epoch counts omit missing, infrastructure-failed and category-mismatched condition pairs; it never reveals task IDs. Infrastructure-failed samples are excluded from paired outcomes. A category/condition with zero model-evaluable paired samples has zero transition counts and a `null` rate difference, not evidence of no change. All differences are descriptive only, not proof of a causal improvement; mocked and non-full runs retain their cautions. The comparison does not modify artifacts, start Docker or call providers.

Aligned comparisons also include `cross_run_paired_uncertainty`: the observed change in each matched task-epoch's GodPrompt-minus-baseline pass difference from earlier to later, plus an exploratory fixed-seed 95% task-cluster bootstrap interval. All epochs belonging to one task are resampled together, not treated as independent tasks. The interval is `null` for fewer than ten distinct tasks, excluded/unpaired/infrastructure-failed samples, mock or non-full runs, or missing provenance/model/coverage evidence; a descriptive point change may still be visible with explicit limitations. Unaligned comparisons suppress this entire field. This interval cannot authenticate model execution, establish causality, justify selective claims, or measure generalization beyond the observed task set.

Add `--format markdown` to render a human-readable comparison with condition/category percentage-point changes, aggregate and per-category paired pass/fail transitions, a joint condition-pair transition matrix, cross-run paired-contrast uncertainty and its limitations, observed per-condition input/output token, failed-tool-call and retry count changes, and caution labels. Missing provider token usage remains `n/a`, not zero; no provider price or efficiency benefit is estimated. If local metadata or scored samples are not comparable, the Markdown report suppresses all change tables rather than presenting misleading deltas. The default JSON comparison includes nullable `condition_resource_delta`, `condition_pass_transitions`, `category_pass_transitions`, `cross_run_condition_pair_transitions`, and `cross_run_paired_uncertainty` data. This is for inspection and review drafts, not an independently validated performance claim.

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
