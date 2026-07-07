# Anti-Patterns Reference — What Goes Wrong and How to Prevent It

## Red Flags — STOP Immediately If You Catch Yourself Doing These

### Execution Red Flags

- Making changes outside the defined scope
- "Improving" code that wasn't part of the task
- Skipping the understand phase because "it's a small change"
- Not running build/dev before claiming done
- Changing shared components without checking what else uses them
- Adding new dependencies without the task requiring them
- Guessing instead of asking when something is unclear
- Bundling multiple unrelated changes in one commit
- Removing functionality "nobody uses" without asking
- Disabling or weakening security features to make something work
- Leaving console.logs or debug code in the final commit
- Stacking multiple untested changes before verifying any of them

### Debugging Red Flags

- Proposing fixes before investigating root cause
- "Quick fix for now, investigate later"
- "Just try changing X and see if it works"
- Adding multiple changes at once, then running tests
- "It's probably X, let me fix that" (without evidence)
- Pattern says X but adapting it differently without understanding
- Listing fixes without investigation
- "One more fix attempt" when already tried 2+
- Each fix reveals a new problem in a different place

### Verification Red Flags

- Using "should", "probably", "seems to" about work status
- Expressing satisfaction before verification ("Great!", "Perfect!", "Done!")
- About to commit without running verification
- Relying on partial verification
- "Just this once" for skipping checks
- ANY wording implying success without having run proof

### Design Red Flags

- Defaulting to safe, generic aesthetics
- Using Inter, Roboto, or Arial
- Purple gradients on white backgrounds
- Every element in a rounded-corner card
- Predictable header → hero → 3-column cards → footer
- No distinctive personality or point of view
- "It looks clean" (clean is not a design decision)

### Content Red Flags

- AI slop words (delve, tapestry, holistic, synergy, robust, leverage, elevate, unlock, embark, supercharge, nestled)
- Hedging language when confidence is appropriate
- Wall-of-text paragraphs
- Keyword stuffing
- Claims without verification
- Generic advice that could apply to anything
- No information gain over existing content

---

## Rationalization Prevention

The most dangerous moment is when you KNOW the right process but talk yourself out of it. Here's every excuse you'll encounter and why it's wrong.

### "It's Too Simple to Need Process"

| Excuse | Reality |
|--------|---------|
| "Too simple to need the full protocol" | Simple tasks break production. The protocol IS fast for simple tasks. |
| "I can see the obvious fix" | Seeing symptoms ≠ understanding root cause. |
| "Just a one-line change" | One-line changes break everything when they touch shared code. |
| "It's just a typo fix" | Even for typos: verify the build passes after. 5 seconds. |

### "I'm Saving Time"

| Excuse | Reality |
|--------|---------|
| "No time for full process" | Systematic is FASTER than guess-and-check thrashing. |
| "I'll test after implementing" | Tests written after pass immediately — proves nothing. |
| "Quick fix now, proper fix later" | "Later" never comes. Quick fix becomes permanent tech debt. |
| "Multiple fixes at once saves time" | Can't isolate what worked. Causes new bugs. Costs more time. |
| "Skip the audit, I know this codebase" | You know what you remember. Not what changed since. |
| "TDD slows me down" | TDD is faster than debugging. Always. |

### "This Is Different"

| Excuse | Reality |
|--------|---------|
| "This situation is unique" | Every situation feels unique. The protocol handles all of them. |
| "The user is waiting" | Delivering broken work wastes MORE of their time. |
| "It's a prototype" | Prototypes become production. Start with discipline. |
| "I already manually tested" | Ad-hoc ≠ systematic. No record, can't re-run, easy to miss cases. |
| "Reference is too long, I'll adapt" | Partial understanding guarantees bugs. Read it completely. |
| "Keep code as reference, write tests first" | You'll adapt it. That's testing-after. Delete means delete. |

### "I'm Being Helpful"

| Excuse | Reality |
|--------|---------|
| "While I'm here, I'll also fix Y" | Scope creep. Y gets its own task. File it for later. |
| "This dependency would make it easier" | Every dependency is a liability. Justify it. |
| "Let me refactor this while I'm in the file" | Refactoring is a separate task with its own protocol. |
| "I'll add error handling for edge cases the user didn't mention" | Good instinct, but verify scope first. Don't gold-plate. |
| "I'll improve the code style since I'm touching this file" | Match existing style. Don't impose new conventions. |

---

## Partner Signals — When Your Human Is Telling You Something

Watch for these patterns in feedback. They mean your process has failed:

| Signal | What It Means | Action |
|--------|---------------|--------|
| "Is that not happening?" | You assumed without verifying | Go back to Phase 1 |
| "Will it show us...?" | You should have added evidence gathering | Add diagnostics |
| "Stop guessing" | You're proposing fixes without understanding | Return to root cause |
| "Did you actually test this?" | You claimed without verifying | Run the verification NOW |
| "That broke something else" | You didn't check scope impact | Revert. Audit. Try again. |
| "That's not what I asked for" | You misunderstood the requirement | Return to Phase 1 |
| "Be careful" / "Don't break X" | They're worried about your approach | Add safety: branch, backup, smaller changes |
| Silence after delivery | Review the output yourself. Something might be off. | Re-read your work as the user would |

---

## The Three Most Expensive Mistakes

These cause the most damage, every time:

### 1. Fixing Symptoms Instead of Root Causes

**Cost:** Hours of whack-a-mole debugging. Each "fix" creates new bugs.
**Prevention:** Root Cause Investigation protocol. Trace backward through call chain. Fix at source.

### 2. Making Changes Without Understanding the System

**Cost:** Breaking features you didn't know existed. Cascading failures.
**Prevention:** Phase 1 (UNDERSTAND) is mandatory. Read the code. Trace connections. Identify what must NOT change.

### 3. Claiming Completion Without Verification

**Cost:** Broken deployments. Lost trust. Rework cycles.
**Prevention:** Phase 4 (VERIFY) is mandatory. Evidence before claims. Always.

---

## Test Writing Anti-Patterns

When writing or changing tests, NEVER:

- **Test mock behavior instead of real code.** If your test only proves the mock works correctly, it's worthless.
- **Add test-only methods to production code.** Production code should never contain `_testHelper()` or `isTestMode()` paths.
- **Mock without understanding what you're mocking.** If you can't explain why the mock is necessary, you don't understand the dependency.
- **Write tests that pass immediately.** If you didn't watch the test fail first, you don't know if it tests the right thing.
- **Test implementation details.** Test BEHAVIOR (what it does), not IMPLEMENTATION (how it does it). Tests should survive refactoring.

### The Test Quality Check

Before committing any test, verify:
1. Did I watch this test FAIL before making it pass?
2. Does this test break if I remove the feature it's testing?
3. Does this test survive a refactor of the implementation?
4. Am I testing real code or testing a mock?
5. Is there exactly ONE reason this test could fail?

---

## Timing Anti-Patterns

For tests with async operations, network calls, or state changes:

- **NEVER use fixed timeouts:** `await sleep(2000)` — brittle, slow, and environment-dependent
- **ALWAYS poll for conditions:** Wait for the actual state change, not an arbitrary time

```typescript
// BAD: Fixed timeout
await sleep(2000);
expect(element).toBeVisible();

// GOOD: Condition polling
await waitFor(() => expect(element).toBeVisible(), { timeout: 5000 });
```

---

## Recovery Playbook

When things go wrong (and they will), here's the decision tree:

```
Something broke?
  ├── I know what I changed → git revert <hash> → verify → investigate
  ├── Build fails → read the FULL error → fix that specific error
  ├── Tests fail → which test? → read the assertion → trace the failure
  ├── Works locally, fails in CI → environment difference → check versions, config
  ├── User says "that's wrong" → stop → re-read the requirement → understand the gap
  └── No idea what happened → git stash → verify clean state works → binary search changes
```

The rule is always the same: **don't panic, don't guess, investigate systematically.**
