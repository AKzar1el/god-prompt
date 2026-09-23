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

1. **Authority boundaries are implicit.** "Edit the repo" does not say which paths, external systems, destructive actions, or privileged operations are allowed, whether an approval applies only to the exact named action/resource, or which effective account/principal an external connector will act as.
2. **Scope has no fence.** There is no rule requiring the agent to distinguish task-owned changes from unrelated existing work.
3. **Verification is optional.** "When needed" lets the agent decide whether tests or other checks can be skipped.
4. **Completion evidence is undefined.** The agent can claim success without naming commands, results, changed files, or unresolved gaps.
5. **Handoff/recovery is missing.** There is no durable rule for partial work, blocked work, interrupted runs, or changed repository state.

## Proposed revised instruction block

```md
Before editing, restate the requested outcome, list the files or areas you expect to touch, and identify any action that would modify external systems, credentials, billing, deployment, or destructive state. Do not perform those higher-risk actions unless the task explicitly authorizes them.

Treat each approval as scoped only to the exact named action, tool, resource, account, and destination. Before any external write, verify the effective connected account/principal and confirm that the intended guard or approval mechanism actually applies to the tool family being invoked; do not infer either from task intent.

Child agents, delegated sessions, and resumed sessions must inherit the parent's effective authority ceiling. A child-specific policy may preserve or narrow that ceiling, but it must never restore a tool, resource, account, or operation that the parent was not allowed to use.

Keep changes inside the requested scope. Preserve unrelated existing changes and stop for reconciliation if repository state changes unexpectedly while you work.

Before claiming completion, run the repository's documented verification commands that apply to the change. Report the exact checks run and whether each passed. If a required check cannot run, state that limitation instead of treating the task as verified.

For interrupted or blocked work, leave a concise handoff containing the current branch/commit, completed work, outstanding verification, blockers, and the next safe action.
```

## Next-task verification checklist

- [ ] The requested outcome and edit scope are explicit before mutation.
- [ ] Unrelated pre-existing changes remain untouched.
- [ ] Risky external or destructive actions require explicit authority.
- [ ] Each approval is limited to the named action/resource and does not silently grant unrelated trust.
- [ ] External writes verify the effective account/principal and applicable guard path before mutation.
- [ ] Child, delegated, and resumed execution cannot widen the parent session's effective tool/authority ceiling.
- [ ] Applicable repository checks run before a completion claim.
- [ ] The final report names checks/results and any unresolved gap.
- [ ] Interrupted work leaves enough state for another operator or agent to continue safely.

## What a paid review adds

The real review applies this structure to **your supplied repository controls and one concrete failure example**. It returns five repository-specific priority risks, one proposed instruction block or patch, and a next-task verification checklist. Up to three control artifacts are reviewed; one clarification exchange is included when needed.

During the current experiment, send repository artifacts only after making the US$49 one-time GitHub Sponsors payment and include the sponsoring GitHub username so the payment can be independently verified and attributed before delivery begins. The full frozen terms are in [MONETIZATION_EXPERIMENT.md](MONETIZATION_EXPERIMENT.md).
