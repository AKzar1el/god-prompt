# Agent Harness Review — Sample Deliverable

This is a transparent **illustrative sample**, not a client result, testimonial, benchmark, or claim that GodPrompt improves model performance. It shows the format and level of specificity used for the frozen US$49 `GP-RS1` Agent Harness Review.

## Illustrative input

Assume a small repository has these agent instructions:

```md
You may edit the repo to finish the task.
Run tests when needed.
Do not break anything.
```

The team reports one recurring failure: the coding agent sometimes edits unrelated files and says a task is complete without showing which checks passed.

## Five priority risks

1. **Authority is implicit.** "Edit the repo" does not say which paths, external systems, destructive actions, or privileged operations are allowed.
2. **Scope has no fence.** There is no rule requiring the agent to distinguish task-owned changes from unrelated existing work.
3. **Verification is optional.** "When needed" lets the agent decide whether tests or other checks can be skipped.
4. **Completion evidence is undefined.** The agent can claim success without naming commands, results, changed files, or unresolved gaps.
5. **Handoff/recovery is missing.** There is no durable rule for partial work, blocked work, interrupted runs, or changed repository state.

## Proposed revised instruction block

```md
Before editing, restate the requested outcome, list the files or areas you expect to touch, and identify any action that would modify external systems, credentials, billing, deployment, or destructive state. Do not perform those higher-risk actions unless the task explicitly authorizes them.

Keep changes inside the requested scope. Preserve unrelated existing changes and stop for reconciliation if repository state changes unexpectedly while you work.

Before claiming completion, run the repository's documented verification commands that apply to the change. Report the exact checks run and whether each passed. If a required check cannot run, state that limitation instead of treating the task as verified.

For interrupted or blocked work, leave a concise handoff containing the current branch/commit, completed work, outstanding verification, blockers, and the next safe action.
```

## Next-task verification checklist

- [ ] The requested outcome and edit scope are explicit before mutation.
- [ ] Unrelated pre-existing changes remain untouched.
- [ ] Risky external or destructive actions require explicit authority.
- [ ] Applicable repository checks run before a completion claim.
- [ ] The final report names checks/results and any unresolved gap.
- [ ] Interrupted work leaves enough state for another operator or agent to continue safely.

## What a paid review adds

The real review applies this structure to **your supplied repository controls and one concrete failure example**. It returns five repository-specific priority risks, one proposed instruction block or patch, and a next-task verification checklist. Up to three control artifacts are reviewed; one clarification exchange is included when needed.

During the current experiment, do not send repository artifacts until the GitHub Sponsors checkout is publicly available and a US$49 sponsorship has been independently verified. The full frozen terms are in [MONETIZATION_EXPERIMENT.md](MONETIZATION_EXPERIMENT.md).