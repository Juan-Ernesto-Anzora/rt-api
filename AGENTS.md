# AGENTS.md — Request Tracker (RT)

> **Read this file in full before making any code changes.** Agents and contributors must follow these rules when proposing or committing changes.

## 1. Tech stack & architecture
- **Frontend**: React (TypeScript), Vite, Tailwind (tokens mapped from `design-tokens.json`), shadcn/ui for primitives.
- **Backend**: Django + Django REST Framework; `djangorestframework-simplejwt` for local JWT during dev; path to OIDC kept ready.
- **DB**: SQL Server (primary). Use Full-Text Search for keyword queries.
- **Storage**: MinIO (S3-compatible) with **pre-signed uploads**.
- **Async**: Celery + Redis (email, notifications, file scans). Realtime: **polling MVP**, **Django Channels** later.
- **Tenancy**: single DB with `tenant_id` discriminator. All queries must be tenant-scoped.
- **Spec-first**: `openapi-rt-with-examples.yaml` is the source of truth for endpoints, auth, pagination, and error shapes.

## 2. Design system
- **Tokens**: See `/design-tokens.json`. Never hardcode colors/spacing/typography.
- **Accessibility**: WCAG AA contrast, focus-visible outlines, tab order, ARIA labels for controls.
- **Density**: compact by default; components support comfortable density.
- **Status colors**: open/indigo, in-progress/indigo, waiting/amber, closed/neutral (see UI kit).

## 3. UI conventions
- **Global app bar**: left = product name; right = **user menu** (avatar/name).  
  - Menu items (initial set): **Profile & Preferences**, **Keyboard Shortcuts**, **Saved Views**, **Notifications**, **Switch Company/Tenant**, **Log out**.
- **Left rail**: New Request, My Tasks, Other Tasks, My Requests, Search, Settings.
- **Tables**: left-aligned text, fixed header, zebra rows off, hover highlight on, 48px row height.
- **Forms**: label top, helper text below, error text red/danger-500, required = asterisk.
- **Attachments**: grouped multi-upload → one comment bubble.
- **Search**: single unified page for open/closed; facets for status, assignee, flow, tag, date ranges.

## 4. API usage rules
- Include `Authorization: Bearer <jwt>` and `X-Tenant: <tenant_code>` on every request.
- Pagination: `page`, `page_size` (default 25). Sorting: `sort` (e.g., `-updated_at`).
- Errors: return JSON with `code`, `message`, `details[]`. Never leak stack traces.
- Don’t invent endpoints—extend the OpenAPI first.

## 5. Security & data
- Enforce tenant isolation on every queryset.
- AuthZ: RBAC via roles and permissions. Never rely on client flags for permission.
- Validate and virus-scan file uploads asynchronously; block serving until scan=clean.
- Log auditable events to `Activity` (who, what, when, request_id, payload).

## 6. Tests & quality (required before commit)
- **Frontend**: unit tests (Vitest), component tests (Playwright or React Testing Library).
- **Backend**: pytest + coverage ≥ 85%. FactoryBoy + pytest-django for data setup.
- **Linters/formatters**: ESLint+Prettier (web), Ruff+Black+isort (api). Type-check with mypy/pyright.
- All tests and linters **must pass locally** and in CI **before** a PR is merged.

## 7. Git & branching (trunk-based)
- Default branch: `main` (protected).
- Branch from `main` using:  
  - `feat/<scope>-<short-desc>` new feature  
  - `fix/<scope>-<short-desc>` bugfix  
  - `chore/<scope>-<short-desc>` tooling or infrastructure  
  - `docs/<scope>-<short-desc>` docs only  
  - `refactor/<scope>-<short-desc>` behavior-preserving changes
- Keep PRs **small** (≤ 400 lines changed ideally). Larger changes must be split.

## 8. Commit messages — Conventional Commits
- Format: `<type>(<scope>): <short summary>`
- Types: `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `chore`
- Add `!` for breaking changes, describe them in the body.
- Examples:  
  - `feat(requests): add grouped multi-file upload`  
  - `fix(search): escape special chars in FTS query`

## 9. Pull requests
- Open against `main`. Draft until all checks pass.
- PR title mirrors Conventional Commit format when squash-merging.
- **Checklist (must pass):**
  - [ ] Unit/integration tests added/updated and green
  - [ ] Lint/type checks pass
  - [ ] OpenAPI updated (if API changed)
  - [ ] UI matches design tokens & accessibility
  - [ ] Changelog entry (if user-visible change)
- Reviewers: auto-assigned by `CODEOWNERS`. Two approvals required for sensitive areas (auth, tenancy, file uploads).

## 10. Release & versioning
- Semantic Versioning (`MAJOR.MINOR.PATCH`).
- Squash merge with Conventional Commit title to auto-generate changelog.
- Tag releases from CI on `main` after passing smoke E2E.

## 11. Local dev & scripts
- `docker compose up` brings API + SQL Server + MinIO + Redis.
- Seed data script: `./scripts/seed.sh` (tenants, users, flows).
- Run web: `pnpm dev` (or `npm run dev`). Run API: `poetry run python manage.py runserver`.

## 12. Agent workflow (how to operate)
1) Read **this file end-to-end** and the current ticket.  
2) Propose a short plan with acceptance criteria.  
3) Update the OpenAPI or design tokens **first** if needed.  
4) Implement incrementally, write tests as you go.  
5) Run full lint+test locally.  
6) Open a small PR with clear title/body and checklist.  
7) Respond to review feedback and keep the PR up to date with `main`.

## 13. Ownership
- See `CODEOWNERS` for paths and required reviewers.
- Security-sensitive code paths: `/api/auth/**`, `/api/tenancy/**`, `/api/uploads/**`, `/infra/**`.

## 14. Notes for future phases
- Switch polling → WebSockets (Channels) for live comments/counters.
- Optional OpenSearch backend for search with query DSL.
- SSO/OIDC path with well-known discovery; keep JWT as fallback for dev.

---

*This AGENTS.md reflects the design and constraints agreed for the Request Tracker modernization project.*