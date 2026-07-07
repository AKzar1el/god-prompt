# Quality Gates Reference — Verification Checklists and Output Standards

## Universal Gate (EVERY task, no exceptions)

Before claiming ANY task is complete:

- [ ] I ran the verification command in THIS message (not relying on memory)
- [ ] I read the FULL output (not skimming for "success")
- [ ] The exit code was 0 (or equivalent success indicator)
- [ ] My claim matches what the output actually says
- [ ] I did NOT use "should", "probably", or "seems to" about the result

**If you can't check all 5 boxes, you are not done.**

---

## BUILD Quality Gate

### Before First Commit

- [ ] Task requirements re-read and understood
- [ ] Scope boundary defined (what's in, what's out)
- [ ] Rollback point created (commit or branch)
- [ ] Existing code audited (files read, connections traced)

### Per Change

- [ ] Change is within defined scope
- [ ] Only ONE logical change in this step
- [ ] No unrelated "improvements" included
- [ ] Matches existing code style and conventions
- [ ] No new dependencies added (unless task requires)
- [ ] No debug artifacts (console.log, commented-out code)

### Before Declaring Done

- [ ] `npm run build` (or equivalent) exits 0
- [ ] `npm run dev` (or equivalent) loads without errors
- [ ] `npm run lint` (or equivalent) passes
- [ ] `npm test` (or equivalent) all pass, no regressions
- [ ] Feature works as specified (tested manually or via browser)
- [ ] Adjacent features still work (spot-check related functionality)
- [ ] No console errors in browser (if web app)
- [ ] Responsive on mobile (if UI change)
- [ ] Commit message is descriptive and follows convention
- [ ] Rollback instructions documented (if non-trivial)

### Commit Message Format

```
type: concise summary of what changed

- Specific change 1
- Specific change 2
- What was NOT changed and why (if relevant)
```

Types: `fix:` `feat:` `style:` `refactor:` `perf:` `chore:` `docs:`

---

## DEBUG Quality Gate

### Before Proposing Fix

- [ ] Error message read COMPLETELY (including stack trace)
- [ ] Bug reproduced consistently (exact steps documented)
- [ ] Recent changes checked (`git log`, `git diff`)
- [ ] Data flow traced (source of bad value identified)
- [ ] Root cause stated as a clear hypothesis
- [ ] Root cause is CONFIRMED, not assumed

### After Fix

- [ ] Failing test exists that reproduces the original bug
- [ ] Fix addresses root cause, not symptom
- [ ] Test passes with fix applied
- [ ] Test FAILS when fix is reverted (Red-Green verified)
- [ ] All other tests still pass
- [ ] No new bugs introduced (spot-check related features)
- [ ] Defense-in-depth: validation added at multiple layers

### Fix Report Format

```
## Bug Fix Report

### Symptom
What was observed: [exact error/behavior]

### Root Cause
What actually caused it: [specific source]
Evidence: [how you confirmed this]

### Fix Applied
What was changed: [specific code change]
Files: [list of files modified]

### Verification
- Test reproducing bug: [test name/file]
- Red-Green confirmed: ✅ (test fails without fix, passes with)
- Regression check: ✅ (all N tests pass)
- Build: ✅ (exits 0)

### Defense Layers Added
- Layer 1: [entry validation]
- Layer 2: [business logic check]
- Layer 3: [environment guard] (if applicable)
```

---

## REFACTOR Quality Gate

### Before Starting

- [ ] Characterization tests exist for current behavior
- [ ] Specific refactor goal stated (not vague "improvement")
- [ ] Scope boundary defined
- [ ] All affected tests are GREEN before starting

### Per Step

- [ ] Tests still GREEN after this step
- [ ] No behavior changed — only structure
- [ ] If tests fail → REVERT immediately

### After Completion

- [ ] All tests pass (same count as before, or more)
- [ ] No behavior changed
- [ ] Refactor goal achieved (measurable improvement)
- [ ] Build succeeds

---

## CONTENT Quality Gate

### Research Verification

- [ ] Key facts verified by web search (prices, dates, stats)
- [ ] "People Also Ask" questions addressed
- [ ] Competitor content checked for gaps
- [ ] Information gain identified (what makes this unique)

### Writing Quality

- [ ] Hook in first sentence (tension, curiosity, or value)
- [ ] Active voice throughout (passive < 10% of sentences)
- [ ] Zero AI slop words used
- [ ] Paragraphs are 2-4 sentences
- [ ] H2s function as standalone answers
- [ ] Front-loaded important information
- [ ] Appropriate for target audience

### SEO (when applicable)

- [ ] Primary keyword in: title, H1, first paragraph, meta description
- [ ] Meta description: 120-155 characters, compelling, front-loaded
- [ ] Heading hierarchy: H1 → H2 → H3 (no skipped levels)
- [ ] Alt text on all images (descriptive, not keyword-stuffed)
- [ ] Internal links to related content
- [ ] Structured data: Article, FAQ, HowTo schema (as applicable)

### Format Verification

- [ ] Word count matches target (±10%)
- [ ] Formatting matches requested output (JSON, Markdown, HTML)
- [ ] All links work and are properly formatted
- [ ] No orphaned references or broken cross-links

### Affiliate Content (when applicable)

- [ ] FTC disclosure present and above the fold
- [ ] Every product has minimum 2 honest criticisms
- [ ] First affiliate link at least 40% into content
- [ ] All affiliate links have `rel="sponsored nofollow"`
- [ ] Prices and features verified against primary sources
- [ ] `data-partner` attributes on all affiliate elements

---

## DESIGN Quality Gate

### Visual Quality

- [ ] Clear, intentional aesthetic direction (not generic)
- [ ] Consistent design language (colors, type, spacing)
- [ ] Typography: distinctive, not default (no Inter/Arial/Roboto)
- [ ] Color palette: cohesive with clear dominant + accent
- [ ] At least ONE memorable visual element

### Responsiveness

- [ ] 320px (small phone): no horizontal scroll, readable text
- [ ] 768px (tablet): layout adapts appropriately
- [ ] 1024px (small laptop): full layout works
- [ ] 1440px (desktop): content doesn't stretch absurdly

### Accessibility

- [ ] Contrast ratio: ≥4.5:1 for normal text, ≥3:1 for large text
- [ ] Touch targets: ≥48x48px with ≥8px spacing
- [ ] Semantic HTML: proper heading hierarchy, landmarks, roles
- [ ] Alt text on all meaningful images
- [ ] Keyboard navigable (tab order makes sense)
- [ ] Focus indicators visible

### Performance

- [ ] No layout shifts during load
- [ ] Images optimized (proper sizing, lazy loading)
- [ ] CSS-only animations where possible
- [ ] First meaningful paint < 2 seconds

---

## SHIP Quality Gate

### Pre-Ship

- [ ] All tests pass (run NOW, not "they passed earlier")
- [ ] Build succeeds (run NOW)
- [ ] No lint errors
- [ ] Diff reviewed: `git diff main` — everything looks intentional
- [ ] No debug artifacts, TODOs, or commented-out code
- [ ] No sensitive data (API keys, passwords, tokens)
- [ ] Commit messages are clean and descriptive
- [ ] Documentation updated (if behavior changed)

### Post-Ship

- [ ] Deployment succeeded (check build logs)
- [ ] Feature works in production (visit the URL, test it)
- [ ] No new console errors
- [ ] No performance regressions
- [ ] Rollback plan ready if issues arise

---

## AUTOMATE Quality Gate

### Architecture

- [ ] Full pipeline mapped: input → stages → output
- [ ] Failure points identified at each stage
- [ ] Error handling covers each failure point
- [ ] Retry logic for network operations (with backoff)

### Code Quality

- [ ] All config via environment variables (.env file)
- [ ] Structured logging at each pipeline stage
- [ ] Each stage independently testable
- [ ] Idempotent: safe to re-run without duplicating work
- [ ] Type hints throughout (Python) or TypeScript types
- [ ] Docstrings/JSDoc on all public functions

### Documentation

- [ ] README with: installation, usage, environment variables, troubleshooting
- [ ] Example invocations with expected output
- [ ] Error codes/messages documented
- [ ] .env.example file with all required variables

---

## Delivery Report Template

Use this for the final Phase 5 (DELIVER) output:

```
## Task Complete

### What Changed
- [file/component]: [what was changed and why]
- [file/component]: [what was changed and why]

### What Was Verified
- Build: ✅ (exit 0)
- Tests: ✅ (N/N pass)
- Lint: ✅ (0 errors)
- [Manual check]: ✅ [what was tested]

### What Was NOT Changed
- [component/area]: [why it was out of scope]

### Rollback
```bash
git revert <commit-hash>
```

### Follow-ups (if any)
- [Future task]: [brief description]
```

---

## The One Rule That Rules Them All

If you take nothing else from this entire system, take this:

```
RUN THE COMMAND.
READ THE OUTPUT.
THEN — AND ONLY THEN — MAKE YOUR CLAIM.
```

That's it. That's the whole game. Everything else is just making sure you do this every time.
