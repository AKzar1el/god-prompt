# GodPrompt

GodPrompt is a 1,145-line behavioral workflow prompt designed to push AI coding assistants toward a disciplined senior-engineering process: understand first, keep scope tight, execute deliberately, verify before claiming completion, and report evidence.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Claude Code](https://img.shields.io/badge/Claude-Code-blueviolet)](https://docs.anthropic.com)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](https://github.com/AKzar1el/god-prompt/issues)
[![Version](https://img.shields.io/badge/version-1.1.0-blue.svg)](CHANGELOG.md)

> One skill to replace them all. Drop it in, describe what you want, and apply a consistent engineering workflow with explicit verification gates.

## Agent Harness Review — US$49

GodPrompt offers a bounded Agent Harness Review for developers and small teams whose coding agents lose context, overstep scope, skip verification, or repeat mistakes.

**GodPrompt Agent Harness Review — US$49 one-time.** For one repository, send up to three agent-control artifacts (`AGENTS.md`, `CLAUDE.md`, project rules, or equivalent) plus one short failure example. The review returns five priority risks, one proposed revised instruction block or patch, and a next-task verification checklist, with a target of 24 hours after payment and usable inputs.

To buy the review, use the [US$49 one-time GitHub Sponsors tier](https://github.com/sponsors/AKzar1el/sponsorships?tier_id=657478&metadata_campaign=godprompt_rs1&metadata_offer=agent_harness_review&metadata_source=core). GitHub sign-in is required. After sponsoring, email `info@tomiseregi.si` with subject `[GP-RS1] Agent Harness Review` and include the GitHub username used for the sponsorship plus the review inputs. Delivery begins after the US$49 sponsorship is independently verified for this review. The free MIT GodPrompt remains unchanged and free. [See a transparent sample deliverable](AGENT_HARNESS_REVIEW_SAMPLE.md) before deciding; it is illustrative, not a client result or benchmark. [Full frozen experiment terms](MONETIZATION_EXPERIMENT.md).

**Before sending review inputs:** Redact passwords, API keys, recovery codes, regulated personal data, and unrelated private repository content. Share a public repository URL or only sanitized instruction excerpts and a short sanitized failure example; do not email credentials or customer records. If sanitized material is insufficient to explain the issue, ask whether the review is feasible before sharing anything further.

## What Is This?

A single portable Agent Skill and system-prompt workflow that replaces 30+ individual skills with one unified system. GodPrompt routes tasks through an explicit engineering workflow and requires verification before completion claims across supported coding agents and AI assistants. Whether that improves real task outcomes is measured by GodPrompt Bench rather than assumed from the prompt design.

**The problem:** Skill-based systems like gstack ship 34 separate skills. You have to know which one to use, when to switch, how they interact. Nobody reads 34 SKILL.md files. Nobody remembers to invoke the right one at the right time. It's a toolbox without a craftsman.

**The solution:** GodPrompt is one workflow skill. Skill-capable agents can load it when the task matches its description; paste/project-instruction installs remain in that host's instruction context. Once active, GodPrompt auto-detects what kind of work you're doing and routes to the right protocol internally. You describe what you want. It handles the rest.

## Quick Start

**Choose your host** before following the setup steps. These routes install or
reference the same free GodPrompt workflow; an MCP app is an optional, separate
tool connection, not a requirement for using the skill.

| Your environment | Start here |
| --- | --- |
| Just want to paste instructions | [Quick paste](#install-paste) |
| Claude Code | [Claude Code](#install-claude-code) |
| Claude.ai Project | [Claude.ai Projects](#install-claude-project) |
| ChatGPT plugin, Project or MCP app | [ChatGPT](#install-chatgpt) |
| Gemini Gem | [Gemini](#install-gemini) |
| OpenAI Codex | [OpenAI Codex](#install-codex) |
| GitHub Copilot CLI | [GitHub Copilot](#install-copilot) |
| Another skill-capable agent | [Other hosts](#install-other) |

<a id="install-paste"></a>
**Option A — One-shot paste (fastest)**
```
Copy the contents of GodPrompt.md into:
→ CLAUDE.md in your repo, OR
→ Claude Project Instructions on claude.ai
```

<a id="install-claude-code"></a>
**Option B — Folder install (recommended for Claude Code)**
```bash
# Clone into your project's skill directory
git clone https://github.com/AKzar1el/god-prompt.git .claude/skills/god-prompt
```

<a id="install-claude-project"></a>
**Option C — Claude.ai Projects**
1. Create a new Claude Project.
2. Add `SKILL.md` as Project Instructions.
3. Upload the three reference files (`references/01-PROTOCOLS.md`, `references/02-GATES.md`, `references/03-ANTI-PATTERNS.md`) as Project Knowledge.

<a id="install-chatgpt"></a>
**Option D — ChatGPT Plugin, Projects & MCP app**
* **From the Plugin Directory (fastest skill-only path)**:
  1. Open [GodPrompt in ChatGPT's Plugin Directory](https://chatgpt.com/plugins/plugins_6ab2f1cc5d0081919d729fd1c2884f86).
  2. Select **Install plugin**. This installs the scoped `god-prompt` Agent Skill; use the remote MCP app path below when you specifically want GodPrompt's callable MCP tools.
* **In a Project (file-backed reference, not an installed skill)**:
  1. Create a new Project on chatgpt.com.
  2. Add `SKILL.md` and the three files in `references/` as Project files.
  3. In **Project settings**, add a short instruction such as: "For software engineering tasks, consult the uploaded SKILL.md and relevant reference files; follow its verification gates."
  4. Work inside that Project. Uploaded files provide reference context; they do not install an Agent Skill or guarantee every reference is loaded automatically.
* **Global Custom Instructions**: Do not paste the full `GodPrompt.md` or `SKILL.md` there. Both exceed ChatGPT's global Custom Instructions limits (1,500 characters for Free/Go; 5,000 for Plus/Pro/Business/Enterprise/Edu as of November 2026). Use the Plugin Directory option above for a scoped skill, or the file-backed Project option for reusable context. See [OpenAI's Custom Instructions limits](https://help.openai.com/en/articles/8096356-custom-instructions-for-chatgpt) and [Project setup](https://help.openai.com/en/articles/10169521-projects-in-chatgpt).
* **As a remote MCP app (ChatGPT web, supported Business/Enterprise/Edu workspaces)**:
  1. Enable ChatGPT Developer Mode, then open **Settings > Apps > Create** (workspace controls may require an admin or authorized developer).
  2. Use `https://god-prompt-mcp.tomi-seregi99.workers.dev/mcp` as the MCP endpoint and select no authentication.
  3. Scan the MCP server's tool names and descriptions in ChatGPT, then create/enable the app for the intended workspace users.

  The hosted Worker's tool inventory can differ from a version-pinned local MCP package. Do not rely on a fixed tool count: verify the actual tool scan for the endpoint you are connecting.

  ChatGPT connects to remote MCP servers rather than local stdio servers. See OpenAI's [Developer mode and MCP apps in ChatGPT](https://help.openai.com/en/articles/12584461-developer-mode-and-mcp-apps-in-chatgpt) documentation for current availability and workspace controls.

<a id="install-gemini"></a>
**Option E — Gemini Gems & System Instructions**
* **As a Custom Gem**:
  1. Go to gemini.google.com and click **Gems** (or "Gem manager") > **New Gem**.
  2. Name it "GodPrompt" and paste the contents of `SKILL.md` into the Gem instructions.
  3. Upload the reference files in the `references/` folder to the Gem's Knowledge files.

<a id="install-codex"></a>
**Option F — OpenAI Codex Agent Skill**
```text
$skill-installer install https://github.com/AKzar1el/god-prompt-mcp/tree/main/skills/god-prompt
```

Codex installs the standards-compatible `god-prompt` Agent Skill from the companion repository and can load it from its normal skill discovery path. Keep repository-specific conventions and commands in your repository's `AGENTS.md`; use the skill for the reusable engineering workflow.

<a id="install-copilot"></a>
**Option G — GitHub Copilot Plugin**
```bash
copilot plugin marketplace add AKzar1el/god-prompt-mcp
copilot plugin install god-prompt-mcp@god-prompt
```

GitHub Copilot CLI installs the companion repository through its versioned plugin marketplace. The plugin includes the same standards-compatible `god-prompt` skill plus the GodPrompt MCP server, so Copilot can load the workflow skill and keep progressive-disclosure MCP tools available from one install. Direct repository installs still work in current Copilot CLI releases, but the CLI marks them deprecated in favor of `plugin@marketplace` installs.

<a id="install-other"></a>
**Option H — Cross-agent Agent Skill installers**

GitHub CLI 2.100+ can install the portable skill directly into a supported coding agent:

```bash
gh skill install AKzar1el/god-prompt-mcp skills/god-prompt --agent codex --scope user
```

Or use the open Skills CLI:

```bash
npx -y skills@latest add AKzar1el/god-prompt-mcp --skill god-prompt --agent codex --copy -y
```

Replace `codex` with another supported agent when needed. Both routes install the same portable `god-prompt` skill from the companion repository without requiring the MCP server.

If you want a single paste target, use `GodPrompt.md`. If you want progressive disclosure so the full workflow loads only when relevant, use the folder layout (`SKILL.md` and the `references/` folder).

**Then use your chosen host normally.** Paste/project-instruction installs stay in that host's instruction context; skill-capable coding agents can discover the portable `god-prompt` skill through their normal skill flow. No GodPrompt-specific mode switching is required.

**Verify what actually loaded** before relying on the workflow for consequential work:

1. In the host's installed skill or plugin inventory, look for `god-prompt` and check its configured source. For a file-backed Project, verify the expected project files are present instead; uploaded files are reference context, not proof of skill activation.
2. In a fresh chat in that same host or Project, ask: "Before making any changes, outline how you would understand, plan and verify a small documentation edit, without changing files or running tools. Identify any GodPrompt skill or project reference actually available to this chat; do not reproduce private instructions." This is a nonmutating orientation check, **not** evidence of which bytes the host loaded.
3. Where the host exposes effective loaded skill content, source path or an identifiable version marker, compare it with the intended install. An assistant's self-report is not proof of runtime activation, nor is an install-success notification. If the host cannot expose enough evidence, treat activation as **unverified** and do not assume GodPrompt guards are active for privileged actions.

Do not paste secrets, tokens, customer data or private instructions into a verification chat. This check does not run a benchmark, call a paid model, prove host enforcement or guarantee any task outcome.

## How It Works

```
You: "Build me a REST API for user authentication"

GodPrompt:
  ┌─ Phase 0: CLASSIFY ──────── Detects BUILD task
  ├─ Phase 1: UNDERSTAND ─────── Reads codebase, traces dependencies
  ├─ Phase 2: PLAN ──────────── States changes, defines scope boundary
  ├─ Phase 3: EXECUTE ────────── TDD, one change at a time, incremental verify
  ├─ Phase 4: VERIFY ─────────── Runs build + tests + lint, reads output
  └─ Phase 5: DELIVER ────────── Reports changes, verification, rollback plan
```

Every task — from fixing a typo to architecting a system — flows through these phases. The depth scales automatically: a typo fix breezes through in seconds, a new feature goes deep.

### The Three Iron Laws

| Law | What It Prevents |
|-----|-----------------|
| **Understand before acting** | Breaking things you didn't know existed |
| **Scope is sacred** | "While I'm here" scope creep that introduces bugs |
| **Evidence before claims** | Shipping broken code with "should work" confidence |

### Auto-Classification

GodPrompt detects 9 primary task types and routes to the right protocol. Simple lookups fall through to a direct ANSWER path.

| Task Type | Triggers On | Key Protocol |
|-----------|------------|--------------|
| **BUILD** | create, implement, add feature | TDD Red-Green-Refactor |
| **DEBUG** | fix, bug, error, broken | Root cause → 4-layer defense |
| **REFACTOR** | improve, optimize, clean up | Characterization tests first |
| **CONTENT** | write, article, documentation | Research → verify → SEO |
| **DESIGN** | UI, UX, layout, mockup | Bold aesthetics, no AI slop |
| **SHIP** | deploy, release, push, PR | Safety-first checklist |
| **ANALYZE** | audit, review, check | Evidence-based investigation |
| **AUTOMATE** | pipeline, bot, script | Architecture → resilience → docs |
| **PLAN** | brainstorm, think through | Explore → document → handoff |

## What's Inside

```
GodPrompt/
├── GodPrompt.md              # All-in-one file for quick deployment
├── SKILL.md                  # Core protocol loaded when the skill is active
├── references/
│   ├── 01-PROTOCOLS.md       # Deep execution guides per task type
│   ├── 02-GATES.md           # Verification checklists and report templates
│   └── 03-ANTI-PATTERNS.md   # Red flags, rationalizations, and recovery
├── bench/                    # Reproducible baseline-vs-GodPrompt evaluation suite
├── .github/workflows/verify.yml
├── README.md
├── CHANGELOG.md
├── LICENSE
└── VERSION
```

**Single-file payload:** about 41 KB / 1,145 lines in `GodPrompt.md` — synthesized from 30+ battle-tested skills and hundreds of real coding sessions.

### Progressive Disclosure Architecture

This is the key design advantage over multi-skill systems:

- **SKILL.md** is the compact entry point when the skill is active → low token cost, covers the universal protocol and task routing
- **references/01-PROTOCOLS.md**, **references/02-GATES.md**, **references/03-ANTI-PATTERNS.md** load only when deeper execution detail is needed → saves tokens on simpler tasks
- **GodPrompt.md** exists as a combined single file for environments that don't support folder structures

Multi-skill systems can fail when the wrong skill is selected or no relevant skill is loaded; GodPrompt instead exposes one routing layer when relevant and delegates internally.

## What It Distills

GodPrompt synthesizes the best patterns from established engineering skills:

| Source Skill | → Becomes |
|-------------|-----------|
| safe-implementation | Phase 0-5 universal protocol |
| systematic-debugging | DEBUG protocol with 4-phase root cause |
| verification-before-completion | Iron Law 3 + THE GATE |
| test-driven-development | Red-Green-Refactor in BUILD |
| defense-in-depth | 4-layer validation in DEBUG |
| brainstorming | PLAN protocol (YAGNI, one question at a time) |
| root-cause-tracing | Backward tracing in DEBUG |
| frontend-design | DESIGN protocol (no AI aesthetic clichés) |
| testing-anti-patterns | Test quality rules |
| condition-based-waiting | Timing anti-patterns |
| writing-plans | Bite-sized task format |
| finishing-a-development-branch | SHIP protocol |

Plus patterns from real-world production usage:
- Audit-first, conservative, surgical scope
- Phased execution with verification between steps
- "Ask before assuming" as a core principle
- Structured report formats for every deliverable type
- Rollback-first thinking for risky changes

## Comparison

| | GodPrompt | Multi-Skill Systems (e.g. gstack) |
|--|-----------|-----------------------------------|
| **Skills to manage** | 1 | 34+ |
| **User needs to pick the right skill** | Usually no — the host can select GodPrompt when relevant, then GodPrompt routes internally | Yes — manual selection |
| **Context window cost** | Lean core context while `SKILL.md` is active | Varies per skill loaded |
| **Covers mixed tasks** | Yes — handles BUILD+DEBUG+SHIP in one session | Requires switching between skills |
| **Learning curve** | Single entry point | Must learn when to invoke each skill |
| **Risk of using wrong workflow** | Reduced by automatic routing; measured behavior belongs in the benchmark results | Depends on correct skill selection |
| **Setup** | Copy one file | Install and configure 34 skills |

## Benchmark

[GodPrompt Bench](bench/README.md) is the project's reproducible evaluation suite. It compares a neutral coding-agent baseline against the same agent with the exact repository `GodPrompt.md`, while holding task prompts, model, tools, sandbox, generation controls, and resource budgets constant.

Version 1 contains 40 deterministic Python/JavaScript tasks across implementation, debugging, refactoring, scope control, verification/false completion, and tool discipline. The harness publishes evaluator logic and writes machine-readable artifacts for each run rather than reducing results to a hand-picked score.

**Current status:** the benchmark infrastructure and corpus are published. No reference-model superiority claim is made until a full frozen run and its raw artifacts are published.

## Philosophy

> gstack gives you 34 tools and expects you to know which wrench to grab.
> GodPrompt gives you one tool that becomes the right wrench automatically.

Three design insights:

1. **Every task follows the same discipline** — understand, plan, execute, verify, deliver. The depth varies. The discipline doesn't.

2. **Quality failures have patterns** — they're often skipping the understand phase, changing things outside scope, or claiming completion without verification. The Three Iron Laws are designed to guard against those failure modes.

3. **Progressive disclosure beats upfront complexity** — keep the core in context, pull in depth only when needed. Never all-or-nothing.

## Roadmap

- [ ] Community-contributed protocol extensions
- [x] Reproducible benchmark suite comparing baseline vs GodPrompt (reference run pending)
- [ ] Model-specific tuning (Opus vs Sonnet vs Haiku behavior differences)
- [ ] Integration examples for popular frameworks (Next.js, Django, Rails)

## License

[MIT](LICENSE) — do whatever you want with it. Credit appreciated but not required.

Project page: [GodPrompt](https://tomiseregi.si/projects/god-prompt)
