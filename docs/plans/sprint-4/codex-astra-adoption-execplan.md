# Codex GPT-6 Astra Workflow Adoption

## Purpose and Scope

Make development instructions and handoffs usable with GPT-6 Astra while
preserving RT behavior, quality gates, managed controls, and explicit user scope.
Sprint 4 is an organizational label only. No product, SQL, dependency, credential,
or application-level model integration changes are authorized by this plan.

Source: [OpenAI GPT-6 Astra guidance](https://developers.openai.com/api/docs/guides/latest-model),
read on 2026-09-07. Apply its instruction-audit and testing guidance to Codex;
do not copy Responses API request parameters into Codex configuration.

## Repository Orientation and Baseline

- `AGENTS.md`, `.agent/PLANS.md`, and `.agent/code_review.md` govern work and review.
- `docs/codex-prompts.md` contains reusable entry prompts;
  `.codex/config.toml.example` supplies optional project defaults.
- `README.md` documents actual setup and checks; `.github/workflows/ci-api.yml`
  currently runs Ruff, isort, Black, and mocked/static pytest, not live services.
- `docs/plans/sprint-3/api-admin-configuration-execplan.md`,
  `docs/sprint-3-api-verification.md`, `docs/sprint-3-known-issues.md`, and
  `docs/release-readiness.md` hold historical completion and limitation evidence.
- Branch: `docs/codex-astra-adoption`, from `origin/main` at `6ce40df`, the merge
  of API PR #22 containing Day 10 commit `89765ee`. Initial worktree was clean.

The user reports Sprint 3 Day 10 hardening and infrastructure SQL validation
complete. Checked-in reports record 189 pytest cases, Sprint 3 Postman 69 requests /
178 assertions, Sprint 2 8 / 17, and schema/seed/MailHog verification. These are
historical results, not reruns for adoption. Old unchecked boxes do not reopen
completed milestones. Production deployment, release tag, and comprehensive
SQL double-application evidence remain unverified by this change.

No application OpenAI SDK, custom agent, or model-call integration was found in
`apps/`, `rt_api/`, or `pyproject.toml`. A future discovery is a separate migration
surface requiring its own scope; no API key is needed for this Codex switch.

## Implementation Plan

1. Reconcile real instruction paths, API contracts, and check commands in
   `AGENTS.md` and `README.md`; retain coverage, type-check, review, and CI gates.
2. Replace obsolete entry prompts with context, implementation, review, and
   handoff prompts naming the selected plan. Add scope/hierarchy and authorized
   follow-through rules to existing instruction documents.
3. Set the example model to `gpt-6-astra`, retain supported medium reasoning,
   and merge only model fields into an existing active config if necessary.
   Inspect non-secret fields only. Preserve MCP/auth/approval/sandbox settings.
4. Add a dated Sprint 3 reconciliation note; preserve historical evidence.
5. Validate TOML and documentation references, run focused checks during
   iteration and the required full gate once the diff is ready. Record failures
   or missing tooling; do not install dependencies or weaken requirements.
6. Prepare a PR description and next handoff prompt. Commit/push/publication
   are not part of this request.

## Verification and Acceptance

Use existing Python 3.12 `tomllib` to parse the example, project manifest, and
the selected non-secret active model fields without printing secrets. Verify referenced repository files exist
and only instruction/configuration/documentation paths changed.

Run from repository root at the PR gate:

```powershell
poetry run python manage.py check
poetry run pytest -q
poetry run ruff check .
poetry run black . --check
poetry run isort . --check --diff
poetry run python manage.py spectacular --validate --file "$env:TEMP/rt-astra-openapi.yaml"
git diff --check
```

Coverage >=85% and mypy/pyright remain required by AGENTS. The manifest has no
configured coverage/type-check runner or FactoryBoy dependency; record those
gaps rather than claiming the requirements pass. Existing tests use mocks and
in-process schema checks; no SQL/MinIO/MailHog/Newman run is needed for this
documentation/configuration-only adoption. Do not replay historical collections.

Done means reusable prompts select the intended plan, source paths match the
checkout, config parses, managed settings are retained, completion evidence is
dated, and every check is labeled passed/failed/blocked with its actual scope.
No active-model claim may be inferred from prose or a configured default; use
client-visible status when available, otherwise report unknown.

## Progress

- [x] Read governing instructions, relevant OpenAI Docs skill, official guidance,
  Sprint 3 plan/verification, configuration example, manifest, and CI.
- [x] Create adoption branch from merged main; inspect model-only local settings.
- [x] Reconcile instructions, prompts, example, and baseline note.
- [x] Validate references/TOML and run available required checks.
- [x] Record outcomes, limitations, PR description, and next prompt.

## Surprises & Discoveries

- Global local config already selects `gpt-6-astra` with `medium` reasoning;
  no repo-local active config exists. A no-op merge preserves all other settings.
- No nested AGENTS override was found in applicable source/instruction paths.
- Static OpenAPI, root design tokens, Compose, and seed.sh references are stale.
- Poetry fails in the restricted account but works as Poetry 2.1.4 under the
  normal account with an existing project environment. No installation needed.
- CI does not trigger for docs/TOML-example-only PRs and has no coverage/type
  check or live-service jobs. This adoption records rather than expands CI scope.
- The existing Python environment lacks pytest-cov, coverage, mypy, pyright,
  and FactoryBoy. These are unresolved tooling gaps, not passing gates.
- The protected `.codex` directory required managed write escalation for the
  checked-in example. Only that example was changed; global config was retained.

## Decision Log

- 2026-09-07: Keep the supported current reasoning effort (`medium`) and change
  only the model example; active local settings already match the target.
- 2026-09-07: Preserve instruction hierarchy and managed controls. Routine
  reversible choices within authorization need no repeated confirmation.
- 2026-09-07: Reconcile Sprint 3 via a dated note, not blanket checkbox edits.
- 2026-09-07: No runtime/dependency/CI behavior changes and no invented runners.

## Outcomes & Retrospective

Completed the bounded development-workflow edits. Eight files changed:
`AGENTS.md`, `.agent/PLANS.md`, `.agent/code_review.md`, `docs/codex-prompts.md`,
`.codex/config.toml.example`, `README.md`, the Sprint 3 reconciliation note, and
this adoption plan. No application, SQL, dependency, CI workflow, or secret changed.

Fresh validation on the existing Poetry 2.1.4 / Python 3.12.10 environment:

| Check | Outcome |
| --- | --- |
| `poetry run python manage.py check` | Passed, zero issues |
| `poetry run pytest -q` | Passed, 189 cases; mocks/static and in-process contracts |
| `poetry run ruff check .` | Passed |
| `poetry run black . --check` | Passed, 52 files unchanged |
| `poetry run isort . --check --diff` | Passed |
| `poetry run python manage.py spectacular --validate --file "$env:TEMP/rt-astra-openapi.yaml"` | Passed, no emitted warnings/errors |
| Python `tomllib`: manifest, example, selected local model fields | Passed |
| Repository/sibling source reference existence | Passed, 21 paths |
| `git diff --check` | Passed |
| Coverage >=85%, mypy/pyright | Blocked: runners/configuration absent; no waiver |
| PR CI and required human review | Pending publication/review; docs-only path filter may skip CI |

The local default already equals `model = "gpt-6-astra"` and
`model_reasoning_effort = "medium"`. No local patch is required; all existing
MCP/auth/permission settings were left untouched. No client-visible runtime
model status was available, so active task model is unknown. No dependencies
were installed, live collections replayed, or SQL executed. Deployment and
release tagging remain unverified; historical completion was not overwritten.

## Prepared PR Description

Title: `docs(codex): adopt Astra development workflow`

Obsolete Sprint 2 entry prompts and nonexistent source paths could direct Codex
back into completed work. This change makes plan selection explicit, reconciles
the completed Sprint 3 baseline, and supplies the GPT-6 Astra model example with
the existing medium reasoning effort. It clarifies authorized follow-through,
instruction hierarchy, and focused iteration versus full PR checks.

Validation: 189 tests, Django check, Ruff, Black, isort, OpenAPI, TOML/reference
checks, and whitespace checks passed. Coverage/type-check tooling remains absent;
required reviewer/CI gates are retained. Local active model defaults already
match, and MCP/auth/managed settings are untouched. No application integration
surface was found; a future API-model migration requires separate scope.

## Next Prompt

Read AGENTS.md, .agent/PLANS.md, .agent/code_review.md, and the selected active
plan docs/plans/sprint-4/codex-astra-adoption-execplan.md. Review the adoption
diff against origin/main without editing. Verify scope/hierarchy, source paths,
model example, preserved gates, and reported-versus-fresh evidence. Report
findings and missing quality tooling; do not reopen completed Sprint 2/3 work.
