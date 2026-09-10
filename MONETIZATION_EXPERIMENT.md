# GodPrompt Revenue Shot — Frozen Monetization Experiment

Status: **FROZEN BEFORE T0**

Experiment ID: `godprompt-revenue-shot-2026-09`
Frozen hypothesis ID: `GP-RS1-AGENT-HARNESS-REVIEW`
Fixed window: **2026-09-11 02:00 Europe/Ljubljana through 2026-09-18 02:00 Europe/Ljubljana**
Payment rail: **GitHub Sponsors only**
Attribution campaign: `godprompt_rs1`

## Frozen hypothesis

Developers and small engineering teams already using coding agents will pay a small one-time amount for a concrete review of the repository-level instructions and control harness that govern those agents, because failures around context, scope, autonomy, verification, and handoff create real engineering cost even when the underlying model is capable.

The seven-day experiment sells exactly one bounded service: **GodPrompt Agent Harness Review**.

## Target payer

An independent developer, technical founder, or small software team that:

- actively uses Claude Code, Codex, Cursor, GitHub Copilot, or another coding agent on a real repository;
- already has, or is trying to create, repository-level agent instructions such as `AGENTS.md`, `CLAUDE.md`, project rules, skills, or equivalent control text; and
- has a concrete problem with agent context, scope creep, unsafe autonomy, verification discipline, repeated mistakes, handoff, or inconsistent execution.

This is not positioned as generic prompt engineering and is not a security incident-response service.

## Offer and price

**GodPrompt Agent Harness Review — US$49 one-time.**

The buyer pays exactly US$49 as a one-time GitHub Sponsors sponsorship to `AKzar1el`, then sends the review inputs to `info@tomiseregi.si` with subject `[GP-RS1] Agent Harness Review`.

Experiment-controlled Sponsor links use:

`https://github.com/sponsors/AKzar1el?metadata_campaign=godprompt_rs1&metadata_offer=agent_harness_review`

Where a source-specific controlled link is used, it may additionally add `metadata_source=<approved_source>` without changing the campaign or offer marker.

GitHub Sponsors is the frozen payment rail. Its approval/public-availability state is a market sensor, not permission to create or switch to another payment processor.

## What the buyer receives

For one repository, the buyer may provide a public repository URL or the relevant instruction text directly. The review may cover up to three agent-control artifacts (for example `AGENTS.md`, `CLAUDE.md`, project rules, or one skill/instruction file) plus one short example of a task where the agent behaved badly.

Within a target of 24 hours after payment and usable inputs are received, Tomi delivers one concise Markdown review containing:

1. the five highest-priority concrete failure risks or control gaps;
2. findings mapped to context, authority/autonomy, scope, verification, tooling, and handoff where applicable;
3. one proposed revised instruction block or patch for the supplied agent-control layer; and
4. a short acceptance/verification checklist the buyer can use on the next real coding task.

One clarification exchange needed to understand the supplied material is included. Ongoing implementation, production deployment, incident response, broad architecture consulting, guaranteed productivity gains, and unlimited revisions are outside this frozen offer.

The free MIT GodPrompt and GodPrompt MCP products remain free and are not degraded or paywalled.

## Intake and privacy

After sponsoring, the buyer emails:

- GitHub username used for the sponsorship;
- repository URL if public, or only the instruction text they want reviewed;
- the relevant agent instruction files/text (maximum three artifacts); and
- one concise example of the failure or friction they want reduced.

Do not request or retain passwords, API keys, recovery codes, private credentials, regulated personal data, or unrelated private repository content. If the buyer cannot provide sufficient non-secret material, request narrower sanitized inputs or decline the review.

## Success, failure, and attribution

**SUCCESS** = before the fixed end, independently verify a real GitHub Sponsors monetary event greater than US$0 that is attributable to this experiment. Strong attribution is the `campaign=godprompt_rs1` transaction metadata and/or an independently linkable buyer intake using `[GP-RS1]` plus the matching sponsorship.

**UNVERIFIED** = material sponsorship/payment evidence exists during the window but receipt or experiment attribution cannot be independently established.

**FAIL** = at the fixed end, after final reconciliation, no attributable monetary event greater than US$0 was received.

Stars, views, clones, downloads, installs, Sponsor-page visits, emails, replies, promises, and intent are diagnostics only.

## Frozen funnel diagnostics

The experiment may observe, without redefining success:

1. attributable money and buyer intake;
2. qualified buyer replies/inbound;
3. Sponsor/payment friction;
4. offer and CTA exposure on owned surfaces;
5. GitHub traffic/referrers/popular paths;
6. npm/package/install evidence;
7. MCP Registry/Glama/marketplace exposure;
8. trust/proof objections;
9. offer-page or scope comprehension; and
10. repository/package/CI health when it affects the funnel.

## Hypotheses considered before freeze

Scores are 1–5; higher is better. `7d` means probability of obtaining real money inside this fixed seven-day experiment. `Ease` rewards low delivery/implementation risk.

| Candidate | WTP evidence | GodPrompt fit | 7d | Ease | Distribution leverage | Free-product preservation | Total / 30 | Decision |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| **US$49 Agent Harness Review** | 5 | 5 | 5 | 4 | 4 | 5 | **28** | **FROZEN** |
| US$49 repository instruction-pack setup | 4 | 5 | 4 | 3 | 4 | 5 | 25 | Rejected: more implementation/support burden before value is proven |
| US$99 coding-agent incident/reliability review | 5 | 5 | 3 | 3 | 3 | 5 | 24 | Rejected: higher intake friction and narrower trigger event |
| US$199 team AI-coding governance starter | 5 | 5 | 2 | 2 | 3 | 5 | 22 | Rejected: strong market fit but too much buying/delivery friction for first seven-day payment |
| US$29 MCP install/configuration concierge | 2 | 3 | 3 | 5 | 4 | 5 | 22 | Rejected: npm/MCP install is already intentionally simple and free |
| US$5–10 pure OSS supporter tier | 2 | 3 | 3 | 5 | 3 | 5 | 21 | Rejected: lowest buyer value differentiation; tests goodwill rather than GodPrompt's commercial utility |
| US$99 custom coding-agent eval setup review | 4 | 4 | 2 | 2 | 3 | 4 | 19 | Rejected: larger setup burden and GodPrompt's paid reference benchmark was intentionally waived |

## Evidence used for the freeze

Current evidence was gathered immediately before the freeze rather than inferred from repository activity alone.

- **Live Upwork demand — AI coding governance / agent harness:** an active `Senior AI Coding Governance & Agent Harness Engineer` posting explicitly requests agent harness engineering, context engineering, risk-based autonomy, guardrails, scope control, coding-agent evals, Definition of Done/task contracts, multi-layer code review, bounded autonomy, and testable deliverables for Codex/Claude Code/Copilot-class workflows. Marketplace job ID `2097500892929233413`, retrieved 2026-09-11.
- **Live Upwork demand — customized Claude agent workflows:** an active US posting offers US$30–60/hour for an engineer to customize Claude, build skills/agents, connect MCP, and define a practical project process. Marketplace job ID `2097791659976307287`, retrieved 2026-09-11.
- **Live Upwork pain — Claude Code/MCP diagnosis:** an active buyer seeks hands-on help distinguishing normal vs misconfigured Claude Code/Desktop behavior across MCP, permissions, configuration, processes, and integrations. Marketplace job ID `2097581231765126639`, retrieved 2026-09-11.
- **Current community workflow pain:** recent Claude Code discussions describe splitting giant sessions into focused sessions and repository-scoped instructions after long-context sessions began losing orientation or hallucinating paths; other recent workflow discussion uses persistent files to preserve decisions and abandoned approaches across sessions.
- **First-party coding-agent guidance:** OpenAI documents `AGENTS.md` as a persistent repository instruction layer and describes Codex consuming scoped repository instructions; Anthropic's prompting guidance for long-horizon agentic workflows recommends explicit state preservation across context windows when the harness supports it.
- **Payment mechanics:** GitHub Sponsors supports one-time USD tiers and customizable benefits, and GitHub documents `metadata_*` parameters that persist through checkout and appear in transaction exports. This makes the US$49 one-time value exchange and `metadata_campaign=godprompt_rs1` attribution path compatible with the frozen payment rail.

### Source references

- Upwork — Senior AI Coding Governance & Agent Harness Engineer: https://www.upwork.com/jobs/~022097500892929233413
- Upwork — Claude Agent Creation: https://www.upwork.com/jobs/~022097791659976307287
- Upwork — Claude Code/Cowork security diagnosis: https://www.upwork.com/jobs/~022097581231765126639
- Reddit — current Claude Code workflow discussion: https://www.reddit.com/r/ClaudeAI/comments/1vsfygs/how_has_your_claude_code_workflow_evolved_in_the/
- OpenAI — Codex and repository `AGENTS.md`: https://openai.com/index/introducing-codex/
- Anthropic — prompting best practices / long-horizon state tracking: https://docs.anthropic.com/en/docs/build-with-claude/prompt-engineering/prompt-templates-and-variables
- GitHub Sponsors — sponsorship tiers: https://docs.github.com/en/sponsors/receiving-sponsorships-through-github-sponsors/managing-your-sponsorship-tiers
- GitHub Sponsors — attribution metadata: https://docs.github.com/en/sponsors/receiving-sponsorships-through-github-sponsors/viewing-your-sponsors-and-sponsorships
## Commercial invariants for all 169 wakes

- Do not pivot to another payer, offer, price, payment rail, or business model to escape negative evidence.
- Commercial wording, placement, examples, reliability, and fulfillment mechanics may improve only while remaining inside this exact hypothesis and terms.
- Maximum three proactive warm first-touch Gmail messages during the whole experiment, only inside genuinely existing relevant human relationships, with full-thread/SENT deduplication and the control-plane Gmail circuit breaker.
- No cold-email campaign, mass DM/posting, bought traffic, paid ads, fake evidence, fake users, fake testimonials, review manipulation, or unrelated third-party mutation.
- No external API/model spend without separate explicit authorization.
- No public benchmark superiority claim unless a real frozen full benchmark run with raw evidence supports it.
- Local repository/filesystem/shell/Git/package/test/Cloudflare work uses Codexify/God only. Never use Privatizmo.
- The Scheduled Task must never modify, recreate, enable, disable, reschedule, or duplicate itself.

## Fixed terminal time

The experiment starts at **2026-09-11 02:00 Europe/Ljubljana** and ends at **2026-09-18 02:00 Europe/Ljubljana**. The scheduler must contain exactly 169 hourly occurrences including both endpoints. The window must not be extended, silently restarted, or moved because of negative results or Sponsor availability.
