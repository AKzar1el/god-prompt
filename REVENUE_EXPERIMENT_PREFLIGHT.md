# GodPrompt Revenue Shot — Preflight Contract

Status: **PRELAUNCH — COMMERCIAL CONTRACT FROZEN; SCHEDULER PENDING**

This document defines the bounded authority and launch gates for one seven-day GodPrompt revenue experiment. The commercial hypothesis is now frozen separately in `MONETIZATION_EXPERIMENT.md`; this preflight update still does not itself start the experiment or its scheduler.

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

## Durable orchestration control plane

Primary orchestration authority is the native Google Doc `GodPrompt Revenue Shot — Goal, Maintainer & Docs` (document ID `1y-dqQIWmd7FpzSpSHZGj75eSWryB9Z1bi9qj9QcXID8`):

`https://docs.google.com/document/d/1y-dqQIWmd7FpzSpSHZGj75eSWryB9Z1bi9qj9QcXID8/edit`

Authority order is independently verified external reality > GOAL > MAINTAINER > DOCS > scheduler/task text. GOAL is frozen mission authority. MAINTAINER is compact mutable current state and handoff. DOCS is append-only durable history for research, attempted approaches, failures/root causes, successful side effects, independent verification, decisions/rejections, exact identifiers, lessons, do-not-repeat facts, and continuation state.

The Git control branch `experiment/godprompt-revenue-control` is intentionally a small concurrency/recovery fence only. `.revenue-shot/state.json` must not become a second narrative control plane. Every scheduled wake, manual rerun, and same-thread continuation should boot from the Google Doc rather than conversational memory, and the scheduler/task prompt should not duplicate mutable commercial/orchestration state.

Google Doc writes use fresh revision IDs and fail closed on conflict. MAINTAINER replacement and DOCS append are separate transactions. After every write, re-read the document and prove exactly one MAINTAINER start marker, one MAINTAINER end marker, and one DOCS append marker. Missing or duplicate anchors forbid external mutation until the control plane is repaired/reconciled.

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

The repair used proper patch releases rather than mutating historical provenance. Follow-up preflight also found and fixed additional production/release defects:

5. the MCP Registry workflow created a GitHub release using `GITHUB_TOKEN`, so the old `release: published` npm workflow could not be triggered by that release; the flow now explicitly dispatches the exact-SHA npm workflow and skips cleanly before first-package bootstrap;
6. the Cloudflare Worker exposed the `GodPromptMCP` Durable Object binding, while `McpAgent.serve()` expected the default `MCP_OBJECT` binding, causing production `/mcp` requests to return HTTP 500.
7. the public npm package included the Cloudflare-only `agents` runtime dependency even though the stdio package does not ship the Worker entrypoint; `agents` is now development-only and a clean consumer install of v1.0.4 resolves zero production audit vulnerabilities;
8. MCPB SHA reproducibility was host-dependent because the packer preserved OS-specific ZIP attributes, checkout/generated line endings, and unsorted filesystem enumeration order; the release normalizer and build inputs now produce the same bundle bytes across Windows and Linux;
9. npm Trusted Publishing initially failed because the publish workflow's setup-node/npmrc path interfered with OIDC authentication; the release workflow now leaves registry authentication to npm's OIDC exchange, and v1.0.4 was published by GitHub Actions with signed provenance and no long-lived npm publishing token;
10. workflow-only changes to npm/Registry automation could start a Registry release from a main SHA different from the existing version tag; workflow-only push triggers were removed from release execution while PR validation remains active.

All companion repairs were merged through qualified PRs. The final prelaunch companion main SHA is `5c84fd4b1314aa459a096eb2fad703c9127c40b7`. Its required GitHub verification is green. The production Worker was independently smoke-tested after deployment: `initialize` returned 200, `notifications/initialized` returned 202, `tools/list` returned 200, the server reported v1.0.4, and all seven expected GodPrompt MCP tools were present.

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

Current distribution includes Glama, npm, MCPB/GitHub Releases, Cursor/Kiro-compatible install metadata, GHCR, the production Cloudflare Worker, and the official MCP Registry. GitHub Release `v1.0.4` is pinned to release source SHA `59acbd400761a8f1a21592dc191af6cae7eec4a3` with MCPB SHA-256 `e8e9e0d4f7865b44022af1649064a2b9fccd293345fedba46f4037562ce996d6`, matching the published release asset digest and `server.json`. The official MCP Registry reports v1.0.4 active and `isLatest: true`, with both the verified MCPB artifact and `npm: god-prompt-mcp@1.0.4`.

The npm package `god-prompt-mcp` is public at v1.0.4 and `latest` resolves to v1.0.4. A clean install using a fresh npm cache resolves 95 runtime packages, zero production audit vulnerabilities, does not install the Worker-only `agents` dependency, and passes an outside-in stdio `initialize`/`tools/list` smoke with all seven expected tools. npm Trusted Publishing is configured for GitHub Actions workflow `publish-npm.yml` and was proven by the successful v1.0.4 publication; npm emitted signed GitHub provenance for that publish. The temporary bootstrap token is not part of the release path and must remain revoked/unused.

## GitHub Sponsors payment path

The experiment will use the same native GitHub Sponsors identity used by `mcp-geo`:

```yaml
github: AKzar1el
```

Both GodPrompt repositories should carry `.github/FUNDING.yml` with that value.

At preflight, the logged-in GitHub Sponsors dashboard stated that the profile was pending staff approval. The operator later explicitly froze GitHub Sponsors as the experiment payment rail and waived public-availability/approval state as a scheduler-start gate. Sponsor availability remains a market/conversion sensor only. This does not relax money truth: SUCCESS still requires independently verified attributable money greater than zero, and the experiment must not create or switch to another payment rail.

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
- the user explicitly waived the paid/full reference run for this launch and authorized no external API/model spend; synthetic/self-simulated exercises are internal debugging evidence only and are not reference evidence;
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
5. **Payment rail:** GitHub Sponsors / `AKzar1el` is frozen as the only payment rail. The operator explicitly resolved pending/public-availability state as a nonblocking market sensor; no alternate payment processor/account may be created. SUCCESS still requires independently verified attributable money.
6. **Attribution:** deterministic GodPrompt Revenue Shot sponsor marker/path defined and independently testable without making a fake payment.
7. **Benchmark:** full frozen reference run completed and honestly published, **or** explicitly and durably waived before launch with the public no-superiority-claim constraint preserved. No silent assumption.
8. **Dual-repo control + commercial freeze:** the native GOAL/MAINTAINER/DOCS Google Doc exists and records exact preflight state/SHAs; the generation-0 Git control branch/state exists with no active lease and only the small concurrency/recovery fence plus Doc identity; and canonical `MONETIZATION_EXPERIMENT.md` freezes the single commercial hypothesis and exact T0/end before scheduler creation.
9. **No experiment clock yet:** no Revenue Shot schedule exists before gates 1-8 are satisfied/explicitly resolved.

## Revenue Shot v4 orchestration contract

When later launched, the scheduled task is one durable experiment. Hourly invocations are wake sources, not independent attempts.

### Finite scheduler

Use exactly 169 hourly occurrences from the chosen T0 in `Europe/Ljubljana`, including the first wake and the final wake exactly seven days later. The scheduler itself must terminate; do not create an infinite hourly schedule that merely relies on model instructions to stop.

### Single global lease

One control branch in the primary repository:

`experiment/godprompt-revenue-control`

Control file:

`.revenue-shot/state.json`

At most one run may hold mutation authority across either repository at a time.

The Git fence is deliberately small: experiment ID, generation, active run ID, short lease/heartbeat fields, execution backend, wake source, orchestration Doc ID/URL, Doc revision at acquire, terminal state, and update timestamp.

Use generation fencing plus a unique `active_run_id`. Git lease TTL is approximately **8 minutes**, with heartbeat every 3-4 minutes only while substantive work is active. The MAINTAINER Doc claim uses a lease roughly **10 minutes** ahead and is renewed under a fresh revision fence. A run that intentionally checkpoints/exits must clear Doc ownership and immediately release the Git lease.

A fresh wake must not mutate until both the Git fence and revision-fenced MAINTAINER claim succeed. Immediately before merge, release/publication, outbound email, terminal verdict, remote-branch deletion, or another critical sink, re-fetch and prove the exact current generation/run ownership.

After crash/lease expiry, reconcile real Git/GitHub/npm/MCP Registry/Glama/Gmail/Sponsors state before taking over. External reality is authoritative; MAINTAINER/DOCS are durable continuation memory; Git state is only the concurrency fence. Side effects must be idempotent.

### Control state machine and mutation firewall

The Google Doc MAINTAINER state is explicit: `CONTROL_STATE` is `READY` or `OWNED`. `ACTIVE_RUN_ID != NONE` if and only if `CONTROL_STATE=OWNED`. Every owned state has `LAST_RELEASE_REASON=PENDING`; completed release reasons are valid only when all owner/lease fields are cleared.

**Pre-claim write firewall:** until both the tiny Git fence and a fresh revision-fenced MAINTAINER claim succeed for the same run/generation, ALL external mutation is forbidden. Read-only reconciliation is allowed. This includes repository/filesystem writes, GitHub writes, Gmail sends, package/release/deploy mutations, web-form submissions, and third-party writes.

If a prior owner is still recorded but its lease is expired, the next fresh wake first performs a revision-fenced recovery to `READY/NONE` with `LAST_RELEASE_REASON=RECOVERED_EXPIRED_LEASE`, then re-reads and verifies that recovery before constructing a new run ID. A crash or platform cutoff is never retroactively described as a normal handoff.

On every normal owned exit, DOCS append happens first when needed. Then one fresh revision-fenced MAINTAINER transaction atomically writes the final verified snapshot, sets `CONTROL_STATE=READY`, clears owner/source/lease fields, and sets the final release reason. Only after that Doc release is independently re-read and verified may the tiny Git fence be released.

### Research depth and work-session rule

When no immediately executable mutation is justified, do not manufacture a PR and do not end after one shallow search. A normal research-only handoff requires at least three materially different source/angle sweeps, at least five distinct current external sources when available, classification of 3–7 candidate hypotheses/actions, and an explicit search for at least one concrete reversible `IN_SCOPE_TESTABLE` move. If none survives, perform one additional materially different sweep and record `NO_ACTIONABLE_HYPOTHESIS_YET`, the searched source classes, and the next unsearched angle. Record compact source/query fingerprints in DOCS so later wakes do not rediscover the same ground.

Owned wakes target roughly 45–55 useful minutes when positive-EV work and platform runtime permit. Waiting for CI, indexing, Gmail, Sponsors, or marketplace review is a lane state, not a whole-wake stop reason; switch to another independent positive-EV lane. Platform pause/approval/policy/user-stop boundaries always win. Never act merely to consume time or keep the run alive.

### Gmail circuit breaker and human control

For any authorized proactive warm message, read the full relevant thread and deduplicate against SENT before writing. Send at most once, then perform exactly one independent SENT verification. No match means `SEND_UNCONFIRMED` and no retry that wake. Duplicate evidence means `GMAIL_DUPLICATION_INCIDENT`: freeze Gmail writes for that wake and continue only safe non-Gmail lanes. Never send automatic correction/apology messages to repair a duplicate.

A Revenue Shot invocation must never modify, recreate, enable, disable, reschedule, or duplicate its own Scheduled Task; never resist or bypass a platform pause, approval request, policy stop, or user stop; and never auto-resume itself. Persistence is the Doc plus future operator/scheduled wakes, not self-preservation.

### Checkpoint transactions

After a material external side effect, independently verify external reality first. Then update MAINTAINER in its own fresh revision-fenced transaction. If durable history is needed, re-fetch the Doc/revision and append DOCS immediately before the unique append marker in a second transaction. Never combine a DOCS index insertion with MAINTAINER replacement or another length-changing Docs edit in one batch.

On normal exit: final-reconcile external reality; update MAINTAINER with exact current state and next actions; append durable DOCS history if needed in a second transaction; re-read the Doc to verify unique anchors and cleared ownership; then release the Git fence. A finished run must never intentionally leave a live lease.

### Prelaunch commercial freeze

The hypothesis is selected and frozen **before T0**, so all 169 scheduled wakes spend the fixed window executing and measuring one business model rather than deciding which business model to run.

The prelaunch research considered at least five materially different models and selected `GP-RS1-AGENT-HARNESS-REVIEW`: a **US$49 one-time GodPrompt Agent Harness Review** for an independent developer, technical founder, or small engineering team already using coding agents. Exact payer, scope, deliverable, intake, GitHub Sponsors metadata, success/failure criteria, fixed window, diagnostics, evidence, rejected alternatives, and no-pivot rules are frozen in `MONETIZATION_EXPERIMENT.md`.

The fixed window is **2026-09-11 02:00 Europe/Ljubljana through 2026-09-18 02:00 Europe/Ljubljana**. Before scheduler creation, the frozen artifact must pass the normal PR/CI path and its exact canonical commit/reference must be mirrored into MAINTAINER and DOCS.

Do not run multiple business models in parallel and do not pivot the frozen payer, offer, price, payment rail, or commercial model later to escape negative evidence. Implementation, wording, placement, reliability, examples, and lawful channel usage may change based on evidence while remaining inside the exact frozen hypothesis.

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
