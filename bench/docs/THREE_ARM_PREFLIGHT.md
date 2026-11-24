# Bench 2.0: three-arm held-out plan preflight

Use this **offline metadata check** before considering a paired experiment.
The existing frozen 40-task two-arm benchmark and all its headline results
remain unchanged. The new CLI cannot execute a model, MCP tool, verifier
or Docker sandbox, and does not register the third arm.

## Inputs

Keep the private held-out task manifest, failure-mode sidecar and plan JSON
outside this repository. Start by validating the held-out corpus:

```sh
cd bench
python -m godprompt_bench.heldout --heldout ../private-heldout/tasks.json --modes ../private-heldout/modes.json
```

Use its exact three SHA-256 manifest fingerprints in the plan:

```json
{
  "schema": "godprompt.three_arm_plan.v1",
  "arms": ["baseline", "godprompt", "godprompt_mcp_contract"],
  "corpus": {
    "reference_sha256": "sha256:<64 lowercase hex>",
    "heldout_sha256": "sha256:<64 lowercase hex>",
    "modes_sha256": "sha256:<64 lowercase hex>"
  },
  "model": {
    "provider": "mockllm",
    "id": "mockllm/test",
    "temperature": 0,
    "seed": 1234
  },
  "limits": {
    "epochs": 1,
    "max_messages": 30,
    "max_time_seconds": 300,
    "max_output_tokens": 8192
  },
  "controls": {
    "source_commit": "<40 lowercase Git commit hex>",
    "sandbox_compose_sha256": "sha256:<64 lowercase hex>",
    "tool_inventory_sha256": "sha256:<64 lowercase hex>",
    "approval_policy_sha256": "sha256:<64 lowercase hex>",
    "baseline_prompt_sha256": "sha256:<64 lowercase hex>",
    "godprompt_prompt_sha256": "sha256:<64 lowercase hex>",
    "mcp_release_sha": "5934340cd4279d7ce103f344279058f54e0c6668"
  }
}
```

Replace every angle-bracket placeholder with a digest computed from the
**exact frozen source, prompt, Compose file or policy bytes** for the proposed
run. The MCP release SHA must equal the already qualified version in
`mcp_contract_adapter.py`. All arms share one model/provider, generation
settings, sandbox, tool inventory, approval policy and budgets; the baseline
uses its neutral prompt, and the other arms share the GodPrompt prompt.
Per-arm overrides and additional execution switches are not supported.
Only the held-out manifest, not the frozen 40-task corpus, is scheduled.

Run the read-only preview:

```sh
python -m godprompt_bench.three_arm --plan ../private-heldout/plan.json --heldout ../private-heldout/tasks.json --modes ../private-heldout/modes.json
```

The report provides held-out task count, epochs, **three arms**, planned
per-arm/total sample counts, uncovered failure modes and hashes of the input
JSON files. It never prints task prompts, verifier code, model IDs, tool
inventories or policy details. Invalid or changed plan/corpus files fail
closed, including duplicate keys and mismatched reference/held-out hashes.

## What a passing preview does not prove

- Source/policy SHA strings are declarations. A qualified experiment owner
  must independently verify the declared bytes, actual Git origin and source
  revision, tool approval behavior, model/runtime settings, and corpus
  isolation against the machine that will execute the run.
- The current native Inspect ToolCall-ID provenance gate and per-sample
  three-arm execution/receipt review integration remain separate unfinished
  work. There is no claim of independent verifier success, sample results,
  model quality improvement or commercial uplift.
- Real model evaluations require explicit provider access, spending
  authorization, held-out novelty checks and validated artifact provenance.
  Do **not** infer permission to run them from a passing preview.
