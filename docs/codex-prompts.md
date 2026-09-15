# Codex prompts — rt-api

## Select the active plan

For this adoption, select `docs/plans/sprint-4/codex-astra-adoption-execplan.md`.
For later work, replace `<selected-plan>` in the prompts with the full existing
repository-relative path named by the user. Resolve it before acting; do not
infer the task from historical unchecked boxes. Sprint 3 Day 10 and infrastructure
SQL validation are reported complete; see the dated reconciliation in its plan.

## Context (read-only)

Read AGENTS.md and .agent/PLANS.md fully, applicable overrides, relevant installed
skills, .agent/code_review.md, and `<selected-plan>`. Inspect Git state, current
contracts, build/CI commands, verification docs, and local model-only settings.
Report completed behavior with evidence, stale instructions, tooling gaps,
unverified deployment state, and the next bounded task. Do not edit or read
secrets. Treat history as evidence rather than new authorization.

## Implementation

Selected active plan: `<selected-plan>`. Read governing instructions and that plan;
implement only its explicitly approved scope. Preserve existing work. Finish
authorized work, make routine reversible choices, and ask only for material
ambiguity or a real permission barrier. Preserve instruction hierarchy, managed
controls, and user limits. If blocked by an instruction, name its file/rule and
explain applicability while continuing independent work. Keep Progress,
Surprises & Discoveries, Decision Log, and Outcomes current. Run focused checks
during iteration and the required full gate before commit/PR; repeat for relevant
changes or failures, not without cause. Report missing runners as blocked. Do
not introduce dependencies, keys, SQL, or product work for a coding-model switch.

## Review

Selected active plan: `<selected-plan>`. Read AGENTS.md, applicable overrides,
.agent/PLANS.md, .agent/code_review.md, and the selected plan. Review the diff
against the verified main base without editing. Prioritize correctness, tenant
isolation, auth/SQL/upload safety, contracts, regressions, and missing tests.
Separate source facts, user reports, historical checks, and fresh results.
Preserve existing coverage/type/reviewer gates; skipped CI is not a pass.

## Handoff (read-only)

Selected active plan: `<selected-plan>`. Report repository/branch/HEAD/worktree,
approved scope, implemented behavior and evidence dates, remaining limitations,
actual check commands/results (mocked versus live), unverified deployments, and
the next bounded prompt. Reconcile stale boxes without reopening completed work.
Describe model defaults separately from client-visible active-model status;
otherwise report active model unknown. Record any application OpenAI integration
as a separate migration surface. Do not include secrets or alter local controls.
