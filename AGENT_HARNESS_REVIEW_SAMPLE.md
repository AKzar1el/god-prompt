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

1. **Authority boundaries are implicit.** "Edit the repo" does not say which paths, external systems, destructive actions, or privileged operations are allowed, whether an approval applies only to the exact named action/resource and material call arguments, or which effective account/principal an external connector will act as.
2. **Scope has no fence.** There is no rule requiring the agent to distinguish task-owned changes from unrelated existing work.
3. **Verification is optional.** "When needed" lets the agent decide whether tests or other checks can be skipped.
4. **Completion evidence is undefined.** The agent can claim success without naming commands, results, changed files, or unresolved gaps.
5. **Handoff/recovery is missing.** There is no durable rule for partial work, blocked work, interrupted runs, or changed repository state.

## Proposed revised instruction block

```md
Before editing, restate the requested outcome, list the files or areas you expect to touch, and identify any action that would modify external systems, credentials, billing, deployment, or destructive state. Do not perform those higher-risk actions unless the task explicitly authorizes them.

If the user says they will personally perform a consequential or destructive step, reserve that step to the user. Do not execute it in parallel, pre-empt it, or perform a conflicting operation against the same state/resource. Wait for the user to confirm completion or explicitly delegate it back, then re-read the affected state before continuing.
If the user requests a draft or preview for review before a later send, publish, merge, or deployment, preserve that review artifact and stop before the external action. The user's explicit review and specific authorization for the resulting effect are required; a finished draft or broad earlier task authorization is not sufficient. Reconcile any changed content or recipient before execution.

Treat each approval as scoped only to the exact named action, tool, resource, account, and destination. Before any external write, verify the effective connected account/principal and confirm that the intended guard or approval mechanism actually applies to the tool family being invoked; do not infer either from task intent.

An approval is specific only when the approval evidence includes the material call arguments and effect scope. If a permission prompt, event, or policy decision exposes only the tool name or omits parameters that determine the destination, resource, account, or effect, do not treat it as authorization for that consequential call; fail closed and require a parameter-complete approval.

Before destructive shell or tool actions, resolve the actual execution root and effective target paths after arguments, variables, globs, and shell expansion. Confirm every target stays within the authorized scope and that the intended policy guard covers the exact invocation path. If target expansion or guard coverage is uncertain, stop. Keep destructive cleanup in the foreground and do not terminate an executor with uncertain ownership.

When asked to roll back a change, reverse only effects attributable to that change. Preserve pre-existing backups, snapshots, object versions, restore points, and audit/recovery evidence even if they belong to the same resource. Do not purge them without separate explicit authorization naming those recovery artifacts; if the current effects cannot be separated from historical recovery state, stop for reconciliation.

Before installing or updating a plugin, skill, extension, or host integration that registers lifecycle or event hooks, compare its trusted source and effective hook commands, arguments, execution identity, and resources before and after. Treat newly added or changed host-side hook effects as consequential even when the model-visible tool list is unchanged. Do not activate the hook until its real effects and authorization are reconciled; stop when the effective hooks cannot be inspected or verified.

Treat tool availability as a separate authority boundary. Before execution, verify that the live model-visible and executable tool set matches the intended allowlist; inherited user/plugin tools and built-in write or execution capabilities outside that set must be absent, not merely assumed to require a later approval.

Resolve security-relevant policy before consequential capabilities start. If the controlling allowlist, deny rules, or approval policy is still loading or cannot be resolved, fail closed; if a later policy narrows authority, re-evaluate and revoke or disconnect already-live capabilities before any further consequential work.

Before each consequential action, verify the live permission/approval mode, effective policy, execution identity, and receiving thread or session for the actual call. Recheck after turn changes, handoffs, resumes, delegation, and cross-thread messages. Neither a settings label nor the sender's model/effort is evidence that the receiving session kept its user-selected controls; if the live authority differs or cannot be inspected, stop for reconciliation rather than assuming approval.

Child agents, delegated sessions, and resumed sessions must inherit the parent's effective authority ceiling. A child-specific policy may preserve or narrow that ceiling, but it must never restore a tool, resource, account, or operation that the parent was not allowed to use.

Child agents must treat ancestor and peer session administration as a separate control-plane authority boundary. Do not archive, terminate, revoke, or reconfigure the coordinator or sibling merely because the API lists it or a self-target operation was rejected. Require explicit delegation for the exact action and target, verify session identity, and stop rather than redirecting the effect when authority is uncertain.

Treat delegated execution state and result delivery as separate verification requirements. A parent view showing `running`, `idle`, or `completed`, a missing notification, or an interim returned message is not proof that the child has actually quiesced or that its final result was delivered. Before restarting, duplicating, cleaning up, or claiming delegated work complete, verify current child/session liveness and ownership plus the final result or expected artifact receipt; if that state cannot be reconciled, do not duplicate consequential work.

For a release or deployment, bind the build to a verified declared source revision and explicitly reconcile any dirty, untracked, or generated build inputs. Verify that the built artifact digest identifies the artifact actually published or receiving traffic, and retrieve/install/safely canary each claimed platform through its real consumer path. A green CI job, version label, or deployment-success badge alone does not prove the released bytes or installability. If provenance or a claimed platform artifact is uncertain, stop traffic movement and report the precise unverified step instead of claiming successful shipment.

Keep changes inside the requested scope. Preserve unrelated existing changes and stop for reconciliation if repository state changes unexpectedly while you work.

Before claiming completion, run the repository's documented verification commands that apply to the change. Report the exact checks run and whether each passed. If a required check cannot run, state that limitation instead of treating the task as verified.

For interrupted or blocked work, leave a concise handoff containing the current branch/commit, completed work, outstanding verification, blockers, and the next safe action.
```

## Next-task verification checklist

- [ ] The requested outcome and edit scope are explicit before mutation.
- [ ] Unrelated pre-existing changes remain untouched.
- [ ] Risky external or destructive actions require explicit authority.
- [ ] A consequential/destructive step the user reserves for manual execution is not raced, duplicated, or pre-empted; affected state is re-read after the user completes it or delegates it back.
- [ ] A user-required draft/review checkpoint is completed and the exact downstream external effect is specifically authorized before execution; no premature send or publication.
- [ ] Each approval is limited to the named action/resource and does not silently grant unrelated trust.
- [ ] Consequential approvals expose and bind the material call arguments/effect scope; tool-name-only permission evidence is not treated as specific authorization.
- [ ] Child agents do not administer ancestor or peer sessions without explicit action-and-target delegation; rejection of a self-target action is not authority to redirect it.
- [ ] Destructive targets are resolved against the effective execution root after shell expansion, guard coverage applies to the real tool path, and uncertain/background cleanup is blocked.
- [ ] Rollback removes only attributable current effects; pre-existing backups, snapshots, and version history remain recoverable unless separately and specifically authorized for destruction.
- [ ] Lifecycle/event hook updates are source-verified and checked against effective host-side commands, identity, and resources; new effects require explicit authorization even if visible tools do not change.
- [ ] External writes verify the effective account/principal and applicable guard path before mutation.
- [ ] The live model-visible/executable tool inventory matches the authorized allowlist, with inherited/default capabilities outside scope absent rather than only approval-gated.
- [ ] Security-relevant policy is resolved before capabilities start, and later restrictions revoke or re-evaluate already-live capabilities before further consequential work.
- [ ] The actual receiving session's live permission mode, policy, and execution identity match authorized scope after handoff/turn changes; sender settings or UI labels are not mistaken for approval.
- [ ] Child, delegated, and resumed execution cannot widen the parent session's effective tool/authority ceiling.
- [ ] Delegated/background work verifies real child/session liveness and final result/artifact receipt before duplicate execution, cleanup, or completion.
- [ ] Released/deployed artifact provenance is bound to a verified source revision and built/published digest; each claimed platform artifact is retrievable and safely canaried.
- [ ] Applicable repository checks run before a completion claim.
- [ ] The final report names checks/results and any unresolved gap.
- [ ] Interrupted work leaves enough state for another operator or agent to continue safely.

## What a paid review adds

The real review applies this structure to **your supplied repository controls and one concrete failure example**. It returns five repository-specific priority risks, one proposed instruction block or patch, and a next-task verification checklist. Up to three control artifacts are reviewed; one clarification exchange is included when needed.

During the current experiment, send repository artifacts only after making the US$49 one-time GitHub Sponsors payment and include the sponsoring GitHub username so the payment can be independently verified and attributed before delivery begins. The full frozen terms are in [MONETIZATION_EXPERIMENT.md](MONETIZATION_EXPERIMENT.md).
