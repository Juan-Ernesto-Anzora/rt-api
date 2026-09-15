# code_review.md — Codex Review Standard

Use this checklist when asking Codex to review a branch, PR diff, uncommitted changes, or a commit.

## Review priorities

1. Correctness: Does the change implement the requested behavior?
2. Tenant isolation: Can one tenant access another tenant's data?
3. Security: Are auth, permissions, uploads, SQL, and secrets handled safely?
4. API contract: Does public JSON use clean fields like `request_id`, `flow_id`, `created_at`?
5. Error handling: Are client mistakes returned as 400/401/403/404 instead of 500?
6. Tests: Are relevant tests added or updated?
7. Maintainability: Is logic in the correct service/component layer?
8. UX: Are loading, empty, error, and success states handled?
9. Documentation: Are OpenAPI, README, or demo docs updated?
10. Regression risk: What existing behavior might break?

## Codex review prompt

Review this branch against the verified current main base. Read `AGENTS.md`, applicable nested instructions, `.agent/PLANS.md`, and the explicitly selected active plan first. Use `docs/codex-prompts.md` to identify that plan. Do not edit. Return prioritized findings with file/line evidence, suggested fixes, and missing verification. Separate historical reported results from fresh checks and mocks from live tests. Missing coverage/type runners and skipped CI are not passes. Do not reopen completed sprints from historical checkboxes. Preserve all existing quality gates and required reviewer approvals.
