# Protocols Reference — Deep Execution Guides Per Task Type

## BUILD Protocol

**For: New features, implementations, applications, components, APIs**

### Pre-Build

1. **Create a rollback point:**
   ```bash
   git add -A && git commit -m "checkpoint: pre-implementation state"
   ```
   (Skip if working tree is clean)

2. **For complex work, branch:**
   ```bash
   git checkout -b feat/short-description
   ```

3. **If task is vague or exploratory:**
   - Don't start coding. Brainstorm first.
   - Ask one question at a time. Prefer multiple-choice when possible.
   - Propose 2-3 approaches with trade-offs. Lead with your recommendation.
   - Present design in small sections (200-300 words). Validate each.
   - YAGNI ruthlessly — cut unnecessary features from every design.

### Build Execution

**Ordering:** Quick wins → Moderate complexity → Complex/risky changes

**Per change:**
1. Write the failing test first (TDD Red)
2. Watch it fail — confirm it fails for the right reason
3. Write minimal code to pass (TDD Green)
4. Run tests — confirm pass, no regressions
5. Refactor if needed — keep tests green
6. Commit with descriptive message

**If no test framework exists or testing isn't practical:**
- Still write code incrementally
- Verify after each logical step (build, run, manual check)
- Never stack multiple untested changes

### Build Verification

```bash
npm run build         # Must exit 0
npm run dev           # Must load clean
npm test              # Must all pass
npm run lint          # If available
```

**For web apps:** Open in browser → check console → test the flow → check responsive

---

## DEBUG Protocol

**For: Bug fixes, error resolution, unexpected behavior, performance issues**

### The Iron Law of Debugging

```
NO FIXES WITHOUT ROOT CAUSE INVESTIGATION FIRST
```

If you haven't completed root cause analysis, you CANNOT propose fixes.

### Phase D1: Root Cause Investigation

1. **Read error messages COMPLETELY.** Don't skip. They often contain the exact solution.

2. **Reproduce consistently.** What are the exact steps? Does it happen every time?

3. **Check recent changes.** `git log --oneline -10`, `git diff`. What changed?

4. **Trace data flow backward:**
   - Where does the bad value appear? (symptom)
   - What called this with the bad value?
   - Keep tracing UP until you find the source
   - Fix at SOURCE, not at symptom

5. **For multi-component systems, add diagnostics:**
   ```
   At EACH component boundary:
     - Log what enters
     - Log what exits
     - Verify environment/config propagation
   Run once → analyze WHERE it breaks → investigate THAT component
   ```

### Phase D2: Pattern Analysis

1. Find working examples of similar code in the same codebase
2. Compare working vs. broken — list every difference
3. Don't assume "that can't matter" — small differences cause bugs
4. Read reference implementations COMPLETELY, not just the parts you think matter

### Phase D3: Hypothesis and Test

1. Form ONE hypothesis: "I think X is the root cause because Y"
2. Make the SMALLEST possible change to test it
3. ONE variable at a time — never fix multiple things at once
4. If it didn't work → form NEW hypothesis. Don't stack fixes on top.

### Phase D4: Fix

1. Write a failing test that reproduces the bug
2. Fix the root cause — ONE change
3. Verify: test passes, no regressions, issue actually resolved
4. **If 3+ fixes have failed:** STOP. Question the architecture. This is not a failed hypothesis — it's a wrong design. Discuss before attempting more fixes.

### Defense-in-Depth (after fixing)

Add validation at EVERY layer the data passes through:
- **Layer 1:** Entry point validation (reject bad input at API boundary)
- **Layer 2:** Business logic validation (ensure data makes sense for operation)
- **Layer 3:** Environment guards (prevent dangerous operations in specific contexts)
- **Layer 4:** Debug instrumentation (capture context for forensics)

Single validation: "We fixed the bug." Four layers: "We made the bug impossible."

---

## REFACTOR Protocol

**For: Code cleanup, performance optimization, pattern improvement**

### Pre-Refactor

1. **Ensure full test coverage on the area being refactored.** If tests don't exist, write them FIRST (characterization tests that capture current behavior).
2. **Define the refactor goal.** What's the specific improvement? Not "make it better" — concrete: "reduce duplication in X", "extract shared logic into Y", "improve Z performance by N%".
3. **Set the boundary.** What files/components? What is explicitly OUT of scope?

### Refactor Execution

1. One logical refactor step at a time
2. Run tests after EVERY step — must stay green
3. If tests fail → revert immediately, rethink approach
4. Never change behavior during refactoring — only structure
5. If you discover a bug during refactoring → FILE IT, don't fix it now (unless it's blocking)

---

## CONTENT Protocol

**For: Articles, documentation, guides, prompts, copy, reports**

### Research Phase

1. **Web search to verify** all claims, stats, prices, and current state
2. **Check "People Also Ask"** for the primary topic — address these in content
3. **Identify information gain** — what does this content offer that competitors don't?
4. **Check competitor content** — find gaps to fill, not patterns to copy

### Writing Standards

**Structure:**
- Hook in first sentence — create tension or curiosity
- Front-load key information (inverted pyramid)
- H2s as standalone answer blocks (first 40-60 words after heading should answer the question)
- Paragraphs: 2-4 sentences. Never wall-of-text.
- One idea per paragraph
- Transition naturally between sections

**Voice:**
- Active voice by default
- Confident and direct — no hedging ("might", "perhaps", "it's possible that")
- Personality welcome, substance mandatory
- Match the audience — technical for devs, accessible for consumers
- Zero banned AI words: delve, tapestry, holistic, synergy, leverage, unlock, elevate, robust, comprehensive (unless truly warranted), nestled, game-changer, embark, supercharge

**SEO (when applicable):**
- Primary keyword in title, H1, first paragraph, meta description
- Natural keyword usage — never stuffed
- Internal links to related content
- Image alt text (descriptive, not keyword-stuffed)
- Meta description: 120-155 chars, front-load important info
- Structured data (FAQ schema, HowTo schema, Article schema)

**Affiliate/Product Content (when applicable):**
- FTC disclosure above the fold
- Honest pros AND cons — minimum 2 criticisms per product
- First affiliate link at least 40% into content (excluding quick picks)
- rel="sponsored nofollow" on all affiliate links
- Prices and features verified by web search against primary sources

### Content Verification

- Every fact checked against a source
- Word count matches target
- Format matches requirements
- No orphaned links or broken references
- Spell check, grammar check

---

## DESIGN Protocol

**For: UI/UX, visual design, frontend implementation, design systems**

### Design Thinking

Before coding, commit to a direction:
1. **Purpose:** What problem does this interface solve? Who uses it?
2. **Tone:** Pick an extreme. Bold maximalism OR refined minimalism. Never generic middle ground.
3. **Differentiation:** What's the ONE thing someone will remember?
4. **Constraints:** Framework, performance, accessibility requirements

### Design Execution

**Typography:** Choose distinctive, characterful fonts. Never default (Arial, Inter, Roboto). Pair a display font with a refined body font.

**Color:** Commit to a cohesive palette. Use CSS variables. Dominant color + sharp accents > timid, evenly-distributed palettes.

**Layout:** Unexpected compositions. Asymmetry. Generous negative space OR controlled density. Break the grid when intentional.

**Motion:** Focus on high-impact moments — a well-orchestrated page load with staggered reveals. CSS-only when possible. Don't scatter random micro-interactions.

**Visual depth:** Gradient meshes, noise textures, geometric patterns, layered transparencies, dramatic shadows. Create atmosphere, not just containers.

**NEVER:** Generic AI aesthetics — purple gradients on white, card grids, Inter font, predictable header-hero-cards-footer layout, cookie-cutter components.

### Design Verification

- Responsive: test at 320px, 768px, 1024px, 1440px
- Accessibility: contrast ratios, touch targets (48x48px min), semantic HTML
- Performance: no layout shifts, optimized images, fast paint
- Dark mode: if supported, verify all states
- Empty states: what does it look like with no data?

---

## SHIP Protocol

**For: Deployment, release, PR creation, version management**

### Pre-Ship Checklist

1. All tests pass (run them, don't assume)
2. Build succeeds (run it, don't assume)
3. No console errors in dev mode
4. Review the diff: `git diff main` — sanity check everything
5. No debug artifacts, TODOs, or commented-out code

### Ship Execution

```bash
# 1. Ensure clean state
git status

# 2. Merge latest base
git fetch origin main && git merge origin/main

# 3. Run full verification
npm run build && npm test && npm run lint

# 4. Commit with descriptive message
git add -A && git commit -m "type: summary

- Change 1
- Change 2"

# 5. Push
git push

# 6. Create PR (if applicable)
```

### Post-Ship

- Update documentation if behavior changed
- Verify deployment (visit the URL, test the feature)
- Monitor for errors in first 15 minutes
- Have rollback ready: `git revert <hash>`

---

## ANALYZE Protocol

**For: Audits, code review, performance analysis, SEO checks, security review**

### Analysis Execution

1. **Investigate BEFORE recommending.** Never prescribe without diagnosis.
2. **Structured report format:**
   - What was checked
   - What was found (with evidence)
   - Severity/priority ranking
   - Recommended actions (ordered by impact)
   - What was NOT checked (scope boundary)
3. **Evidence-based findings.** Every finding has a specific example, file path, or measurement.
4. **No vague recommendations.** Not "improve performance" — specific: "reduce bundle size by lazy-loading X component (currently 143KB)."

---

## AUTOMATE Protocol

**For: Pipelines, bots, scripts, automation workflows, integrations**

### Architecture First

1. **Map the full pipeline:** input → processing stages → output
2. **Identify failure points:** what can go wrong at each stage?
3. **Design error handling:** retry logic, fallback behavior, alerting
4. **Plan observability:** logging at each stage, structured output

### Automation Standards

- **Configurable:** Environment variables for all settings (API keys, URLs, thresholds)
- **Resilient:** Retry with exponential backoff for network operations
- **Observable:** Structured logging with timestamps, stage identifiers, and outcome
- **Testable:** Each stage independently testable
- **Documented:** README with setup, usage, environment variables, troubleshooting
- **Idempotent:** Safe to re-run without duplicating work

```python
# Pattern: Resilient stage execution
async def execute_stage(name, fn, max_retries=3):
    for attempt in range(max_retries):
        try:
            result = await fn()
            logger.info(f"[{name}] Success on attempt {attempt + 1}")
            return result
        except Exception as e:
            logger.error(f"[{name}] Attempt {attempt + 1} failed: {e}")
            if attempt == max_retries - 1:
                raise
            await asyncio.sleep(2 ** attempt)  # Exponential backoff
```

---

## PLAN Protocol

**For: Brainstorming, architecture decisions, project planning, design documents**

### Exploration Phase

1. One question at a time — don't overwhelm
2. Multiple choice preferred — easier to answer
3. Propose 2-3 approaches with trade-offs
4. Lead with your recommendation and why

### Plan Output

Write to `docs/plans/YYYY-MM-DD-<topic>.md` with:
- **Goal:** One sentence
- **Architecture:** 2-3 sentences
- **Approach options:** With trade-offs and recommendation
- **Task breakdown:** Bite-sized, ordered by dependency
- **Success criteria:** What does done look like?
- **Risks and mitigations**

### YAGNI Ruthlessly

In every plan, actively cut:
- Features nobody asked for
- Abstractions for hypothetical future requirements
- Premature optimization
- "Nice to have" that delays the core value

---

## ANSWER Protocol

**For: Questions, lookups, explanations, recommendations**

1. Answer directly first — lead with the answer, not the context
2. Keep it concise — match response length to question complexity
3. Use web search for anything that could have changed since training cutoff
4. Cite sources for factual claims
5. If the question is really asking for a different task type (BUILD, DEBUG, etc.) — recognize that and route to the appropriate protocol
