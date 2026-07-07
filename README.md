# GodPrompt

Default AI is lazy. It hallucinates, it skips verification, and it says "Let's delve" while writing bad code. GodPrompt is an 800+ line behavioral override. Drop this single file into your AI, and it transforms from a helpful assistant into a ruthless, production-grade Senior Engineer.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Claude Code](https://img.shields.io/badge/Claude-Code-blueviolet)](https://docs.anthropic.com)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](https://github.com/AKzar1el/god-prompt/issues)
[![Version](https://img.shields.io/badge/version-1.0.0-blue.svg)](CHANGELOG.md)

> One skill to replace them all. Drop it in, describe what you want, get production-grade output.

## What Is This?

A single Claude Code skill that replaces 30+ individual skills with one unified system. Auto-detects task type, applies the right production-grade workflow, and delivers verified output — every time.

**The problem:** Skill-based systems like gstack ship 34 separate skills. You have to know which one to use, when to switch, how they interact. Nobody reads 34 SKILL.md files. Nobody remembers to invoke the right one at the right time. It's a toolbox without a craftsman.

**The solution:** GodPrompt is one skill that's always active. It auto-detects what kind of work you're doing and routes to the right protocol internally. You describe what you want. It handles the rest.

## Quick Start

**Option A — One-shot paste (fastest)**
```
Copy the contents of GodPrompt.md into:
→ CLAUDE.md in your repo, OR
→ Claude Project Instructions on claude.ai
```

**Option B — Folder install (recommended for Claude Code)**
```bash
# Clone into your project's skill directory
git clone https://github.com/AKzar1el/GodPrompt.git .claude/skills/god-prompt
```

**Option C — Claude.ai Projects**
1. Create a new Claude Project
2. Add `SKILL.md` as Project Instructions
3. Upload the three reference files (`references/01-PROTOCOLS.md`, `references/02-GATES.md`, `references/03-ANTI-PATTERNS.md`) as Project Knowledge

If you want a single paste target, use `GodPrompt.md`. If you want progressive disclosure and a smaller always-on context footprint, use the folder layout (`SKILL.md` and the `references/` folder).

**Then just use Claude normally.** No special commands, no mode switching, no skill invocations. GodPrompt activates automatically on every task.

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
├── SKILL.md                  # Core protocol loaded every message
├── references/
│   ├── 01-PROTOCOLS.md       # Deep execution guides per task type
│   ├── 02-GATES.md           # Verification checklists and report templates
│   └── 03-ANTI-PATTERNS.md   # Red flags, rationalizations, and recovery
├── index.html                # Static landing page
├── .github/workflows/deploy.yml
├── README.md
├── CHANGELOG.md
├── LICENSE
└── VERSION
```

**Single-file payload:** about 42 KB / 800+ lines in `GodPrompt.md` — synthesized from 30+ battle-tested skills and hundreds of real coding sessions.

### Progressive Disclosure Architecture

This is the key design advantage over multi-skill systems:

- **SKILL.md** stays in the hot path → low token cost, covers the universal protocol and task routing
- **references/01-PROTOCOLS.md**, **references/02-GATES.md**, **references/03-ANTI-PATTERNS.md** load only when deeper execution detail is needed → saves tokens on simpler tasks
- **GodPrompt.md** exists as a combined single file for environments that don't support folder structures

A 34-skill system loads the wrong skill (or none) half the time. GodPrompt loads the right rules every time, and only goes deep when the task requires it.

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
| **User needs to pick the right skill** | No — auto-detects | Yes — manual selection |
| **Context window cost** | Lean base context via `SKILL.md` | Varies per skill loaded |
| **Covers mixed tasks** | Yes — handles BUILD+DEBUG+SHIP in one session | Requires switching between skills |
| **Learning curve** | Zero — just use Claude | Must learn when to invoke each skill |
| **Risk of using wrong workflow** | None — routing is automatic | High — wrong skill = wrong process |
| **Setup** | Copy one file | Install and configure 34 skills |

## Philosophy

> gstack gives you 34 tools and expects you to know which wrench to grab.
> GodPrompt gives you one tool that becomes the right wrench automatically.

Three design insights:

1. **Every task follows the same discipline** — understand, plan, execute, verify, deliver. The depth varies. The discipline doesn't.

2. **Quality failures have patterns** — they're almost always: skipping the understand phase, changing things outside scope, or claiming completion without verification. The Three Iron Laws prevent all three.

3. **Progressive disclosure beats upfront complexity** — keep the core in context, pull in depth only when needed. Never all-or-nothing.

## Roadmap

- [ ] Community-contributed protocol extensions
- [ ] Benchmark suite comparing output quality with/without GodPrompt
- [ ] Model-specific tuning (Opus vs Sonnet vs Haiku behavior differences)
- [ ] Integration examples for popular frameworks (Next.js, Django, Rails)

## License

[MIT](LICENSE) — do whatever you want with it. Credit appreciated but not required.
