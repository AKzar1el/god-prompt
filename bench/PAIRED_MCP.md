# Paired three-arm GodPrompt+MCP evaluation (offline)

> **Source feature under review.** This adds a reproducible **analysis tool**, not a new live agent runner or a measured performance claim. No model calls, API keys, Docker, GPU, remote telemetry, or extra Python packages are required to analyze an existing file.

## Why three arms?

The frozen v1 GodPrompt Bench currently compares:

- **baseline**: neutral instructions;
- **godprompt**: the full fixed GodPrompt instructions.

The optional third condition is **godprompt_mcp**: GodPrompt plus task-contract/evidence-review tools. The effect of adding MCP tools is a separate experimental question, not automatically implied by GodPrompt's original two-arm results.

The existing frozen 40-task corpus, original runner, aggregation logic, and export files remain unchanged. This is a separate, opt-in analyzer, so it does not conflict with in-progress benchmark export hardening.

## How to use

Generate a **real, independently evaluated** v1 JSONL file with one outcome row for each condition at each matched task/epoch/seed. Do not fabricate runs or replace hidden-verifier outcomes with agent assertions. Keep the same model, task fixture and generation controls across all three arms. Toolset fingerprints **may differ by arm** because adding MCP is the intervention, but must remain stable within each arm.

Run from the bench directory:

~~~shell
python -m godprompt_bench.paired_mcp --input paired-outcomes.jsonl
~~~

It prints strict JSON to standard output and writes nothing. You may redirect that output to a user-chosen file if needed. Any malformed, incomplete, duplicated, mismatched or oversized input causes a nonzero exit rather than a misleading partial result.

### Row schema: godprompt.paired_mcp_outcome.v1

Each line is one JSON object with **exactly** these fields:

| Field | Value |
| --- | --- |
| schema | The literal godprompt.paired_mcp_outcome.v1 |
| task_id | Bounded nonempty task identifier (not a file path or task text) |
| category | Bounded task category |
| epoch | Positive integer |
| seed | Nonnegative integer |
| condition | baseline, godprompt, or godprompt_mcp |
| model_id | Same provider/model ID in all arms of a pair |
| fixture_sha256 | SHA-256 fingerprint of the exact task fixture, identical across arms |
| controls_sha256 | SHA-256 fingerprint of frozen generation and execution controls, identical across arms |
| toolset_sha256 | SHA-256 fingerprint of tools enabled for the arm, stable within each arm |
| passed | Boolean hidden-verifier result, not an agent's assertion |
| scope_violation | Boolean from independent scope checks |
| completion_status | complete, partial, blocked, or stopped |
| verification_attempts | Nonnegative integer |
| input_tokens, output_tokens | Nonnegative integer or null if unavailable |
| latency_seconds | Finite nonnegative number or null |
| infrastructure_error | Null, or a bounded error classification (never raw secrets/logs) |
| contract_id | SHA-256 contract ID for godprompt_mcp, null in the other two arms |

**Every field is required**, including fields whose value may be null. Unknown fields, raw transcripts and hidden verifier content are rejected.

Each task/epoch/seed group **must have exactly one row in each of the three arms**. If any arm has infrastructure failure, that entire triple is excluded from the main paired denominator and counted separately. Incomplete triples fail outright. Conditions and fingerprints are validated so comparisons do not silently mix models, tasks or controls.

## Output and interpretation

For each arm, the analyzer reports matched pair count, independently **claimed** pass rates, false-completion counts (derived from completion status and effective pass), scope violations, verification attempts, token totals when complete, and latency medians with reported-sample counts.

It also reports matched discordance counts and net pass-rate deltas for:

- baseline vs godprompt;
- baseline vs godprompt_mcp;
- godprompt vs godprompt_mcp.

A task passes effectively **only if** the hidden-verifier result is true **and** the scope check reports no violation. Non-finite numbers, duplicate JSON keys, invalid types, mismatched controls, changing toolsets and incomplete arms are rejected. Large inputs are bounded at 5 MiB and 20,000 rows.

**These outputs are not independent attestations or evidence of statistical significance.** The analyzer trusts that an authorized source supplied truthful, held-out task outcomes. Tests using synthetic rows verify only the math and failure handling, not agent-performance uplift. A meaningful three-arm experiment still requires a controlled, budget-approved model run and inspectable run artifacts. Never start one without explicit authorization.

## Status and next step

This analyzer is the free offline measurement foundation for [GodPrompt Bench 2.0 issue #348](https://github.com/AKzar1el/god-prompt/issues/348). It deliberately does not add third-arm execution to Inspect AI or claim that the existing 40-task benchmark has been rerun.

The future runner adapter must pin the provider/model, fixture fingerprints, tool manifests, generation controls, random seeds and source receipts, then materialize rows in this exact schema. It must also preserve the original frozen v1 experiment and its published results rather than silently rewriting them.
