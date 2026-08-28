# GodPrompt Bench — Design Specification

Date: 2026-08-28
Status: Approved design; implementation pending
Primary repository: `AKzar1el/god-prompt`
Related repository: `AKzar1el/god-prompt-mcp`

## 1. Objective

Add a reproducible evaluation subsystem that measures GodPrompt against a neutral baseline on small deterministic software-engineering tasks.

The benchmark exists to replace unsupported performance claims with inspectable evidence. It is not a new prompt, not a marketing-only scorecard, and not runtime logic for the MCP server.

Primary question:

> Under a frozen model, tool set, generation configuration, task set, and resource budget, does adding GodPrompt improve deterministic software-engineering task outcomes relative to the same agent without GodPrompt?

The benchmark must remain credible if GodPrompt loses overall, wins only on some categories, or regresses on cost/latency.

## 2. Scope

### In scope

- A benchmark subsystem under `bench/` in `god-prompt`.
- 40 deterministic task fixtures.
- A baseline condition and a GodPrompt condition using the same agent scaffold.
- Deterministic task grading wherever possible.
- Metrics for correctness, false completion, scope discipline, tool behavior, retries, tokens, and latency.
- Raw machine-readable result export.
- Offline CI for benchmark infrastructure.
- A manually triggered real-model benchmark workflow that runs only when credentials are explicitly configured.
- README claim cleanup so empirical statements match published evidence.
- A small `god-prompt-mcp` follow-up that links benchmark evidence and fixes the stale content-generator source paths.

### Out of scope

- Changing the actual GodPrompt behavioral protocol merely to make it sound less assertive.
- Changing MCP transport/runtime architecture.
- Automatically running paid model evaluations on every pull request.
- Publishing a single composite "GodPrompt score" that hides metric trade-offs.
- Claiming superiority before a real frozen benchmark run exists.
- Cross-model leaderboard claims in the first release.
- LLM-as-judge scoring for tasks that can be graded deterministically.

## 3. Repository boundaries

### `AKzar1el/god-prompt`

Owns:

- benchmark tasks and fixtures;
- benchmark harness;
- scorers;
- aggregation/export logic;
- benchmark CI;
- reference results;
- benchmark methodology documentation;
- public claims about GodPrompt benchmark performance.

### `AKzar1el/god-prompt-mcp`

Owns only:

- distribution/access to GodPrompt content;
- MCP-specific tests and metadata;
- a link to published GodPrompt benchmark evidence;
- maintenance of generated embedded content.

No benchmark engine or benchmark task corpus should be duplicated into the MCP repository.

## 4. Evaluation framework

Use the UK AI Security Institute's open-source Inspect AI framework rather than a custom agent-evaluation framework.

Reasons:

- provider abstraction;
- datasets and reusable eval tasks;
- agent/tool support;
- deterministic scorers;
- sandbox support;
- token/time/message limits;
- multiple epochs;
- structured logs and transcripts;
- less custom infrastructure that itself would require validation.

The dependency must be version-bounded in benchmark project metadata so a published benchmark run records the exact evaluation framework version.

## 5. Conditions

Every benchmark sample runs under one of two conditions.

### Baseline

The benchmark agent receives:

- the same task request;
- the same repository fixture;
- the same available tools;
- the same model and generation settings;
- the same token/turn/time budgets;
- a short neutral software-engineering system instruction that does not encode GodPrompt-specific workflows.

### GodPrompt

Identical to baseline except the system instruction includes the current compiled `GodPrompt.md` from the checked-out repository revision.

No condition-specific tools, hidden hints, extra retries, or larger budgets are allowed.

## 6. Benchmark corpus

Version 1 contains exactly 40 small tasks:

- 8 implementation/correctness tasks;
- 8 debugging tasks;
- 6 behavior-preserving refactor tasks;
- 6 scope-control tasks;
- 6 verification/false-completion tasks;
- 6 tool-discipline tasks.

Tasks should use small Python and JavaScript fixtures and prefer standard-library/runtime functionality so environment setup remains deterministic and inexpensive.

Each task must include:

- stable unique task ID;
- category;
- user-facing task description;
- starter repository tree;
- hidden deterministic verifier;
- explicit allowed-change paths;
- explicit forbidden-change paths or workspace boundary where applicable;
- expected verification command(s) where applicable;
- task metadata needed for aggregation.

Hidden verifier logic must not be exposed in the model-visible task prompt.

## 7. Task design rules

A task is valid only if:

1. its success criteria are objectively testable;
2. the starter state is deterministic;
3. the task is small enough to complete within the frozen benchmark budget;
4. baseline and GodPrompt see equivalent task context;
5. task success does not depend on internet access;
6. the scorer can distinguish task failure from infrastructure failure;
7. task wording does not mention GodPrompt or encourage a specific benchmark condition;
8. the task is not trivially solved by reading hidden grader files.

Task fixtures run without outbound network access.

## 8. Metrics

### Primary metric

**Task pass rate**

A task passes only when its hidden deterministic verifier succeeds after the agent finishes.

This metric is preregistered as primary and must not be replaced after results are observed.

### Secondary metrics

**False-completion rate**

The agent explicitly reports the task as complete/successful while the hidden deterministic verifier fails.

**Scope-violation rate**

The final workspace contains unauthorized changes outside task-defined allowed paths.

**Tool misuse**

Rejected or prohibited tool operations, including attempts to escape the workspace or use unavailable capabilities.

**Verification attempts**

Count of relevant build/test/lint/check commands invoked before completion.

**Failed tool calls**

Tool invocations returning failure/error status.

**Retry count**

Repeated attempt after a previous failed execution of an equivalent operation.

**Input/output tokens**

Provider-reported token usage, recorded separately for input and output where available.

**Wall-clock latency**

End-to-end sample duration. It must be labeled infrastructure-sensitive and never presented as a pure model-quality metric.

**Completion status**

At minimum: `complete`, `blocked`, `error`, `timeout`.

## 9. False-completion detection

False completion must not depend on an LLM judge.

The agent's terminal response is classified using a small explicit completion-status protocol exposed equally to both conditions. The benchmark records whether the agent claimed completion and compares that state to the deterministic hidden verifier outcome.

If the agent does not emit a structured status, the sample is marked as protocol-invalid rather than silently inferred as successful.

## 10. Tool policy and sandboxing

Each task runs in an isolated sandbox with outbound network disabled.

The benchmark tool surface should stay intentionally small:

- read files;
- write/edit files inside the task workspace;
- execute approved shell commands inside the task workspace;
- report completion status.

Policy must reject operations that target paths outside the workspace. Rejections are recorded for the tool-misuse metric.

No benchmark task may require credentials or external services.

## 11. Reproducibility manifest

Every real benchmark run must write a manifest containing at least:

- run ID;
- timestamp;
- provider;
- exact model identifier returned/configured;
- generation temperature where supported;
- seed where supported;
- reasoning/effort setting where supported;
- maximum output tokens;
- turn/message limit;
- wall-time limit;
- exact available tool set;
- Inspect AI version;
- Python version;
- GodPrompt commit SHA;
- benchmark commit SHA;
- SHA-256 of the task manifest/corpus definition;
- epoch count;
- requested sample count;
- successfully completed sample count;
- infrastructure-failure count.

Unsupported model controls must be written as `null`/`unsupported`, not implied to be frozen.

## 12. Epochs and variance

A reference run uses 3 epochs per task per condition.

For 40 tasks:

- 40 tasks;
- 2 conditions;
- 3 epochs;
- 240 total model samples.

The aggregation layer must report raw counts in addition to rates. Results should preserve per-task/per-epoch observations so variance is inspectable.

The first release does not require sophisticated inferential statistics, but it must avoid reporting a single percentage without numerator/denominator context.

## 13. Result artifacts

A published reference run uses a structure equivalent to:

```text
bench/results/<run-id>/
├── manifest.json
├── summary.json
├── scores.csv
└── trajectories.jsonl
```

### `manifest.json`

Frozen configuration and provenance.

### `summary.json`

Aggregate and category-level metrics for baseline and GodPrompt, including raw counts.

### `scores.csv`

One row per sample with task ID, category, condition, epoch, deterministic score outcomes, token counts, retry/tool metrics, latency, and completion state.

### `trajectories.jsonl`

Observable model messages and tool-call trajectory needed to audit the result. Hidden chain-of-thought/reasoning is not required and must not be invented or exported.

Secret values, API keys, authorization headers, and environment secrets must never be written to result artifacts.

## 14. Aggregation and reporting

Reports must show:

- overall baseline vs GodPrompt primary metric;
- category-level primary metric;
- secondary metrics side by side;
- token and latency cost differences;
- sample counts;
- failed/incomplete infrastructure samples separately from model failures.

The reporting layer must not:

- drop failed benchmark tasks after observing results;
- exclude GodPrompt regressions from aggregate results;
- collapse all metrics into a custom weighted score by default;
- describe correlation as proof of causation beyond the controlled benchmark conditions.

## 15. README claim policy

Before a real reference run exists, README language must describe GodPrompt behavior as intended/enforced behavior rather than proven universal outcomes.

Examples of language to remove or qualify when unsupported:

- "verified output — every time";
- "loads the wrong skill ... half the time";
- "risk of using wrong workflow: none";
- other empirical superiority percentages or absolutes without public evidence.

Behavioral directives inside `SKILL.md` such as requiring verification are not automatically rewritten: they are instructions, not benchmark claims.

After a real run exists, README performance claims must link directly to the corresponding immutable benchmark result directory/manifest and state the tested model/configuration.

## 16. CI

### Standard pull-request/main CI

Must remain offline and free of paid model calls.

It validates:

- GodPrompt build sync via existing `python build.py --check`;
- benchmark Python package import/type/syntax integrity;
- task-manifest schema;
- exact task count and intended category distribution;
- fixture setup determinism;
- deterministic scorers against known-good and known-bad fixture states;
- scope-violation scorer;
- completion-status parser/protocol;
- result aggregation and exporter behavior;
- no accidental committed secrets in benchmark fixtures/results under known sensitive field names.

### Manual benchmark workflow

A separate `workflow_dispatch` workflow may perform paid model calls only when the required provider credential exists.

Inputs should include at least model and run profile (`smoke` or `full`).

The workflow uploads generated result artifacts even when some samples fail, so failures remain inspectable.

A `smoke` profile should exercise a tiny representative subset for operational validation. A `full` profile performs the frozen reference configuration.

No scheduled or automatic paid benchmark run is required for v1.

## 17. Initial file layout

Target layout:

```text
bench/
├── README.md
├── pyproject.toml
├── configs/
│   ├── smoke.yaml
│   └── full.yaml
├── godprompt_bench/
│   ├── __init__.py
│   ├── eval.py
│   ├── agent.py
│   ├── scorers.py
│   ├── policy.py
│   ├── aggregate.py
│   └── export.py
├── tasks/
│   ├── manifest.json
│   └── <40 deterministic task fixture directories>
└── tests/
    ├── test_manifest.py
    ├── test_scorers.py
    ├── test_policy.py
    ├── test_aggregate.py
    └── test_export.py
```

Exact internal module names may change during implementation if Inspect AI APIs make a smaller layout cleaner, but repository boundaries and evaluation semantics must not change without an explicit design update.

## 18. MCP follow-up

`god-prompt-mcp` requires two narrow follow-up changes after the benchmark core is implemented.

### Content generator maintenance fix

`scripts/generate-content.mjs` currently references the older source layout:

- `core/00-THE-SKILL.md`;
- `core/01-PROTOCOLS.md`;
- `core/02-GATES.md`;
- `core/03-ANTI-PATTERNS.md`.

It must instead read the current source repository layout:

- `SKILL.md`;
- `references/01-PROTOCOLS.md`;
- `references/02-GATES.md`;
- `references/03-ANTI-PATTERNS.md`.

After changing paths, regenerate `src/content.ts`, verify generated content corresponds to the same GodPrompt version, then run the full existing MCP verification suite.

### Benchmark evidence link

README/server-facing descriptive language should link to the benchmark documentation/results and avoid unsupported empirical absolutes. This must not add new MCP tools merely for benchmarking.

## 19. Commit strategy

Planned logical commits in `god-prompt`:

1. `docs: qualify unverified performance claims`
2. `feat: add reproducible GodPrompt benchmark suite`
3. `ci: validate GodPrompt benchmark infrastructure`

Planned logical commits in `god-prompt-mcp`:

1. `fix: align content generator with current GodPrompt layout`
2. `docs: link GodPrompt benchmark evidence`

Implementation may split the benchmark feature commit if the resulting diff becomes too large to review safely, but unrelated work must not be bundled.

## 20. Verification gates

Before `god-prompt` changes are considered complete:

- existing GodPrompt sync check passes;
- all new benchmark unit/infrastructure tests pass;
- all 40 task fixtures validate;
- category counts exactly match the design;
- an offline/mock benchmark run exercises baseline and GodPrompt paths through aggregation/export;
- generated artifacts contain no credentials/secrets;
- diff review confirms `SKILL.md` behavior was not unintentionally modified;
- GitHub Actions for the feature branch is green.

Before `god-prompt-mcp` changes are considered complete:

- `npm ci` passes;
- `npx tsc --noEmit` passes;
- `npm test` passes;
- repaired `npm run generate-content` succeeds against the current GodPrompt layout;
- generated-content diff is reviewed for unintended semantic changes;
- MCP tool list and stdio initialization behavior remain unchanged unless an independently justified defect is found;
- GitHub Actions is green.

## 21. Reference-run publication gate

The repository must not publish a claim that GodPrompt beats baseline unless a real-model benchmark run was actually executed under a recorded frozen configuration.

If credentials are unavailable during implementation, the benchmark subsystem may still ship as production-ready infrastructure with language equivalent to:

> Benchmark infrastructure is available; no reference model result has been published yet.

When a real reference run is performed, both positive and negative results are published without cherry-picking.

## 22. Industry-standard basis

The design follows current evaluation practice reflected in:

- Inspect AI documentation for eval tasks, scorers, agents/tools, epochs, limits, sandboxing, logs, and model-provider abstraction: https://inspect.aisi.org.uk/
- OpenAI evaluation guidance emphasizing representative evals, explicit criteria, reproducible data sources/configuration, and continuous evaluation of model/system changes: https://platform.openai.com/docs/guides/evals
- GitHub Actions workflow-dispatch and artifact mechanisms for manually triggered benchmark runs and retained machine-readable outputs: https://docs.github.com/actions

These references guide methodology; the benchmark remains provider-neutral in its architecture.

## 23. Success criteria

Version 1 is successful when a third party can:

1. inspect all 40 visible task definitions and benchmark methodology;
2. understand exactly what baseline and GodPrompt conditions differ on;
3. verify deterministic scorer behavior locally without API credentials;
4. execute a smoke or full benchmark with a supported model/provider;
5. inspect raw per-sample trajectories and scores;
6. reproduce the aggregate report from raw exported data;
7. trace any public performance claim to a specific run manifest and commit;
8. see regressions and cost trade-offs rather than only favorable results.
