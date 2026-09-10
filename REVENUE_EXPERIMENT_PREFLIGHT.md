# GodPrompt Revenue Shot — Preflight Contract

Status: **PRELAUNCH — DO NOT START THE SEVEN-DAY CLOCK**

This document defines the bounded authority and launch gates for one future seven-day GodPrompt revenue experiment. It is preflight authority only; it does not freeze a monetization hypothesis and does not start the experiment.

## Hard scope

The experiment is one product spanning exactly two public repositories:

- primary/source: `AKzar1el/god-prompt`
- companion/distribution: `AKzar1el/god-prompt-mcp`

Repository mutations are allowed only in those two repositories and their isolated Codexify-managed local worktrees/workspaces. Local computer execution must use the Codexify/God tool surface available to the run.

**Privatizmo is explicitly outside authority.** The experiment must not call Privatizmo tools, read or mutate Privatizmo task/state data, change the Privatizmo repository, or use Privatizmo as an execution substrate. Absence of a Codexify capability is not permission to fall back to Privatizmo.

Public-web research may be broad. Gmail may be read for attributable inbound/payment evidence and, only if the frozen experiment later authorizes it, for the bounded warm-outreach rule below. No other repository or production surface may be mutated.

## Product relationship

`god-prompt` is the canonical source for GodPrompt content, protocols, verification gates, anti-patterns, and GodPrompt Bench. `god-prompt-mcp` packages/distributes that product through MCP transports and marketplaces.

A source change that materially affects bundled GodPrompt content is not fully shipped until the companion repository is synchronized, regenerated when required, qualified, and its relevant distribution surfaces are reconciled. The two repositories therefore share one experiment lease and one experiment generation; they must never run independent Revenue Shot controllers.

## Preflight technical baseline

Baseline captured on 2026-09-10 before Revenue Shot launch.

### `AKzar1el/god-prompt`

Initial preflight main SHA: `8ce490ce470cda15bfe66c651a314b6e3689cadb`.

Verified in a clean Codexify scratch clone:

- `python build.py --check` — PASS
- benchmark test environment created with Python venv
- `python -m pytest bench/tests -q` — **35 passed**
- existing GitHub main verification workflows were green at the baseline SHA

A paid/reference benchmark run has **not** been executed as part of this preflight. The repository correctly forbids superiority claims until a real frozen full run and raw artifacts exist.

### `AKzar1el/god-prompt-mcp`

Initial preflight main SHA: `ff371af55749f8b6cfaa3282992d9f3ccb8b27fe`.

Windows preflight exposed release-path defects that were repaired before launch:

1. the distribution test assumed LF-only shebang line endings and failed on a CRLF checkout;
2. the stdio integration test used a 5-second request timeout despite reproduced healthy Windows handshakes exceeding 5 seconds;
3. runtime `SERVER_INFO.version` reported `1.0.1` while package/distribution metadata reported `1.0.2`;
4. package/MCPB CI hard-coded release version/hash literals, increasing release drift risk.

The repair used a proper patch release rather than mutating historical v1.0.2 provenance. Follow-up preflight also found and fixed two production/release orchestration defects:

5. the MCP Registry workflow created a GitHub release using `GITHUB_TOKEN`, so the old `release: published` npm workflow could not be triggered by that release; the flow now explicitly dispatches the exact-SHA npm workflow and skips cleanly before first-package bootstrap;
6. the Cloudflare Worker exposed the `GodPromptMCP` Durable Object binding, while `McpAgent.serve()` expected the default `MCP_OBJECT` binding, causing production `/mcp` requests to return HTTP 500.

All companion repairs were merged through qualified PRs. The final prelaunch companion main SHA is `d75672f34d1d032bd2ae0f673ed4f689c04c4f3f`. Its required GitHub checks are green, and the production Worker was independently smoke-tested after deployment: `initialize` returned 200, `notifications/initialized` returned 202, `tools/list` returned 200, and all seven expected GodPrompt MCP tools were present.

### Windows execution rule

On this host PowerShell resolves bare `npm` to `npm.ps1`, which is blocked by the current execution policy. Scheduled/local Windows execution must use **`npm.cmd`** for npm commands (or another independently verified executable path). A failed PowerShell command must never be treated as success merely because later commands in a command string returned zero.

## Public/distribution baseline

Observed before launch:

### Core repository

GitHub 14-day traffic snapshot:

- views: 62 total / 17 unique visitors
- clones: 112 total / 54 unique cloners
- major referrers included GitHub, Google, Glama, DuckDuckGo, and ChatGPT
- repository overview was the dominant observed content path

### MCP repository

GitHub 14-day traffic snapshot:

- views: 53 total / 6 unique visitors
- clones: 598 total / 169 unique cloners
- major referrers included GitHub, Claude, and Glama
- repository overview was the dominant observed content path

Current distribution includes Glama, MCPB/GitHub Releases, Cursor/Kiro-compatible install metadata, GHCR, the production Cloudflare Worker, and official MCP Registry publication automation. GitHub Release `v1.0.3` exists with MCPB SHA-256 `0890e9cece882b689599a3212a4ff69f43240493acbb980e906881356b2f874b`, matching `server.json`. The official MCP Registry still reports v1.0.2 as latest until npm bootstrap allows the v1.0.3 registry publication chain to complete.

The npm package name `god-prompt-mcp` remains unclaimed/unpublished at final prelaunch reconciliation. The local npm account is authenticated as `akzar1el`, but initial publication was rejected because npm requires account 2FA or a bypass-enabled granular token for package creation/publishing. This experiment deliberately does not use a bypass token. Bootstrap publication is therefore an interactive prelaunch gate. The repository-side future release flow is already OIDC-ready and exact-SHA fenced; after the package exists, configure npm Trusted Publishing for `.github/workflows/publish-npm.yml` and prove one OIDC publication before launch.

## GitHub Sponsors payment path

The experiment will use the same native GitHub Sponsors identity used by `mcp-geo`:

```yaml
github: AKzar1el
```

Both GodPrompt repositories should carry `.github/FUNDING.yml` with that value.

At preflight, the logged-in GitHub Sponsors dashboard states that the profile is **pending staff approval and is not live yet**, and that it will go live automatically after approval. Therefore GitHub Sponsors is not yet a usable payment path and must not be counted as such.

The experiment must not create Stripe, another payment processor, a new financial account, or change banking/tax/payout settings.

### Attribution

Because the GitHub Sponsors identity is shared across repositories, timing alone is insufficient attribution. Experiment-controlled sponsor links should use a deterministic campaign marker when supported by GitHub Sponsors, reserved as:

`metadata_campaign=godprompt_rs1`

Additional source metadata may distinguish `core`, `mcp`, `readme`, or other approved repo-controlled surfaces.

A sponsorship counts as Revenue Shot SUCCESS only when actual money is independently verified and attributable to this experiment. A sponsor event without the campaign marker or another strong independent attribution chain remains `UNVERIFIED`; it must not be claimed as GodPrompt revenue merely because it occurred during the seven-day window.

## Benchmark / proof gate

GodPrompt Bench is part of the product's trust surface. Its full reference profile is 40 tasks × 2 conditions × 3 epochs = 240 model samples. A full frozen run may materially improve or falsify the product's proof story, but it incurs external model/API usage.

Current preflight facts:

- `python build.py --check` passes on the final core baseline;
- after installing the repository-declared test dependency `inspect-ai==0.3.260`, `python -m pytest bench/tests -q` passes **35/35**;
- the frozen `full` profile contains exactly 40 tasks and 3 epochs; with two benchmark conditions this is 240 model samples;
- benchmark unit/corpus infrastructure is qualified;
- the workflow exists for `workflow_dispatch` on GitHub Actions;
- it expects an `OPENAI_API_KEY` repository Actions secret for an OpenAI run;
- no such repository Actions secret was present when checked during this preflight;
- local Docker is not installed on this Windows host, so the isolated full reference run should use the GitHub Actions sandbox path if authorized;
- no superiority claim may be published unless a real frozen full run and its raw artifacts support it.

The experiment must never game the benchmark, remove losing tasks after seeing results, publish a smoke result as proof, or claim improvement unsupported by the full run.

## Prelaunch launch gates

The seven-day timer may start only after all hard gates are reconciled against external reality:

1. **Core baseline:** canonical `god-prompt/main` clean and required qualification green.
2. **MCP baseline:** canonical `god-prompt-mcp/main` clean; Windows/release defects fixed; required CI green.
3. **Distribution:** MCPB/release/official MCP Registry/Glama paths verified; npm package bootstrap complete and clean-install stdio smoke passes.
4. **Future npm publishing:** GitHub OIDC/trusted-publishing path configured and proven or, if npm account constraints make that impossible, recorded as an explicit non-critical limitation with no false claim that it works.
5. **Payment:** GitHub Sponsors profile publicly live and capable of accepting a real sponsorship. Pending approval does not pass.
6. **Attribution:** deterministic GodPrompt Revenue Shot sponsor marker/path defined and independently testable without making a fake payment.
7. **Benchmark:** full frozen reference run completed and honestly published, **or** explicitly and durably waived before launch with the public no-superiority-claim constraint preserved. No silent assumption.
8. **Dual-repo control:** generation-0 control branch/state exists on the primary repository, has no active lease, and records exact preflight SHAs for both canonical mains.
9. **No experiment clock yet:** no Revenue Shot schedule exists before gates 1–8 are satisfied/explicitly resolved.

## Revenue Shot v3 orchestration contract

When later launched, the scheduled task is one durable experiment. Hourly invocations are wake sources, not independent attempts.

### Finite scheduler

Use exactly 169 hourly occurrences from the chosen T0 in `Europe/Ljubljana`, including the first wake and the final wake exactly seven days later. The scheduler itself must terminate; do not create an infinite hourly schedule that merely relies on model instructions to stop.

### Single global lease

One control branch in the primary repository:

`experiment/godprompt-revenue-control`

Control file:

`.revenue-shot/state.json`

At most one run may hold mutation authority across either repository at a time.

Use generation fencing plus a unique `active_run_id`. Maximum ordinary lease should be approximately **45–50 minutes**, shorter than the hourly wake interval. A run that intentionally checkpoints/exits must immediately clear its lease. Heartbeat only while genuinely doing long work.

Immediately before merge, release/publication, outbound email, terminal verdict, remote-branch deletion, or other important side effects, re-read the control branch and prove the exact current generation/run fence.

After crash/lease expiry, reconcile real Git/GitHub/npm/MCP Registry/Glama/Gmail/Sponsors state before taking over. External reality is authoritative; checkpoint JSON is recovery metadata. Side effects must be idempotent.

### First authorized experimental wake

If and only if there is no frozen hypothesis:

1. research current buyer pain, alternatives, pricing, community discussion, developer/team workflow demand, existing GodPrompt capabilities, benchmark/proof state, and current distribution signals;
2. generate at least five materially different monetization hypotheses;
3. score willingness-to-pay evidence, fit, probability of actual money inside seven days, implementation time/risk, dependence on new accounts, distribution leverage, trust/proof requirements, preservation of the MIT/free products, and legal/provider constraints;
4. choose exactly one hypothesis;
5. freeze payer, offer/value exchange, price/terms, Sponsor/payment route, attribution markers, success/failure criteria, fixed end time, and diagnostics in `MONETIZATION_EXPERIMENT.md` through the normal PR/CI path.

Do not run multiple business models in parallel and do not pivot the frozen offer later to escape negative evidence. Implementation, wording, placement, reliability, examples, and lawful channel usage may change based on evidence while remaining inside the frozen hypothesis.

### Revenue-relevant improvement rule

Product work is allowed only when there is a defensible causal path to revenue probability or protection of the commercial/product path. Examples include benchmark evidence, install friction, npm/MCP compatibility, source-to-MCP synchronization, release reliability, truthful proof presentation, conversion placement, examples/onboarding, marketplace metadata, Sponsor friction, and defects affecting the live offer.

Do not escape into generic refactoring, unrelated roadmap work, arbitrary prompt expansion, SEO churn, benchmark gaming, or new unrelated products.

### Market loop

Each authorized market wake should inspect new evidence in approximately this order where available:

1. independently verified attributable money;
2. qualified buyer/sponsor/inbound evidence;
3. sponsorship/payment conversion friction;
4. offer/CTA exposure;
5. GitHub views/unique visitors/referrers/popular paths;
6. package/download/install evidence;
7. Glama/MCP Registry/marketplace exposure;
8. benchmark/proof engagement or trust friction;
9. proposition/scope/price presentation;
10. product/CI health.

Diagnose the bottleneck before changing anything. Do not manufacture PRs merely because an hourly wake occurred.

### Commercial-change cooldown

Absent a proven defect or materially new buyer evidence, do not make another commercial copy/placement experiment less than roughly four hours after the previous material commercial intervention.

For each material commercial intervention, retain a compact durable record:

- change/fingerprint;
- timestamp;
- evidence before change;
- causal hypothesis;
- expected signal;
- evaluation condition;
- later observed evidence.

This does not block urgent reliability/correctness fixes.

### Bounded warm outreach

If the frozen hypothesis and first-run evidence justify it, at most **three total warm Gmail messages** may be sent during the entire seven-day experiment. Each must be inside an existing relevant human relationship/thread with clear GodPrompt/coding-agent/MCP/software-engineering fit. Read the full thread first; obey opt-outs; never create a cold-prospect list; never mass-send; independently verify each message in Gmail SENT and increment the durable counter exactly once.

Cold campaigns, mass DMs/posts, bought traffic, ads, spam, impersonation, fake testimonials/users/revenue, review manipulation, and unrelated third-party mutation are forbidden.

## Money truth / terminal criterion

The hard objective, once the experiment is launched, is at least one **real, independently verified, attributable monetary event greater than EUR 0** caused by the frozen GodPrompt experiment during the fixed seven-day window.

Stars, views, clones, downloads, installs, favorites, replies, sponsor-page visits, commitments, promises, invoices, or projected value are diagnostics only.

Terminal verdict is exactly:

- **SUCCESS** — attributable money > EUR 0 is independently verified;
- **FAIL** — deadline reached, no attributable money was received, and evidence is unambiguous;
- **UNVERIFIED** — material payment evidence exists but receipt and/or attribution cannot be independently established.

On early SUCCESS, preserve the proven mechanism and stop speculative commercial changes. At the deadline, perform final reconciliation, write the evidence-backed postmortem, clean temporary experiment branches/worktrees, preserve legitimate merged product improvements, and do not silently extend or restart the experiment.
