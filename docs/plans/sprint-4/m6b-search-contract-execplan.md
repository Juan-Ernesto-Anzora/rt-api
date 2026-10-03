# M6B Unified Search API contract

## Purpose

Search result rows become self-sufficient so Web M6C can remove every per-row
Request Detail read. Preserve SQL Server FTS, source weighting, tenant context,
primitive fields, existing routes and the specialized pagination envelope.

## Repository orientation and current behavior

`apps/rt/search.py` matches Request title/description, Comment MessageMd and
Attachment Filename with bound CONTAINS prefix terms. It ANDs at most eight
Unicode word tokens, groups Requests with MAX weights 30/20/10, and orders by
rank then updated time. A window count read from the first row incorrectly
returns zero on an out-of-range page. No related labels are returned.
`apps/rt/serializers.py` contains the Search contracts and reusable M5B
StatusSummarySerializer, UserLookupSerializer and FlowLookupSerializer.
`apps/rt/views.py` validates and dispatches SearchView. `tests/test_search.py`
currently has seven tests, mainly FakeCursor assertions. Generated OpenAPI is
the schema authority. The read-only consumer requirement is
`../rt-web-skeleton/docs/plans/sprint-4/m6-search-data-contract.md` and
`../rt-web-skeleton/docs/design/07-search.md`.

## Desired behavior and scope

Preserve primitive Search fields and add status, requester, nullable assignee,
and flow with exact M5B compact serializers. Preserve the custom response
`{count,page,page_size,results}`. Correct total on empty pages and append
RequestId ASC to Rank DESC, UpdatedAt DESC. Hydrate only page IDs through one
tenant-scoped joined ORM query, restoring FTS order. Do not change Web, request
list/detail/create, admin, routes, RBAC, database schema, matching surfaces,
weights, or expose sort/tags/snippets/extra filters.

## Implementation plan

1. Extend Search schema and validation in `apps/rt/serializers.py` and
   `apps/rt/views.py`: existing UUID/source/page filters; date-only lower bound
   inclusive day start and upper bound exclusive next-day start in configured
   Django TIME_ZONE; explicit datetimes retain instant comparisons. Reject
   reversed bounds. Declare summaries by reusing M5B serializers.
2. In `apps/rt/search.py`, reuse identical tenant-scoped CTE matching/filtering
   for an independent total and page selection. Fetch page Requests in one
   tenant-filtered select_related query, serialize shared compact summaries,
   validate/deduplicate source identifiers and preserve ranking order.
3. Expand `tests/test_search.py` for sources, filters, dates, count, order,
   hydration isolation, nulls, shape, auth/errors, schema and query budget.
4. Run focused tests, then the AGENTS full gate. Run actual SQL Server FTS
   with bounded read-only existing data or disposable authorized fixtures.
   Never mutate original `rt` for live verification. If live FTS is unavailable,
   close out BLOCKED and record the exact limitation.

## Privacy and tenancy

Comment.Visibility and Attachment.ScanStatus exist. Current comment,
attachment and Detail reads return every tenant-scoped record without
visibility/scan-status restrictions. Search metadata preserves that same
policy; this does not certify upload scanning or private-comment security.
No new RBAC can be inferred from unused flags. Audit this behavior with tests
and record it as a product-policy limitation. FTS branches bind TenantId;
child joins require parent and child tenant equality. Hydration independently
filters TenantId. Missing hydration rows are omitted, never fetched globally.
Missing mandatory related records or foreign/inconsistent joined status/flow
metadata fail with canonical `500 server_error`, without labels or technical
details. User is a shared domain table without TenantId; summaries use the
association on the tenant-scoped Request. Assignee null is genuine null.

## Tests and verification

From repo root, using the existing Poetry environment through approved
execution escalation when sandbox launch is denied:

```powershell
poetry run pytest tests/test_search.py tests/test_openapi.py -q
poetry run python manage.py check
poetry run pytest -q
poetry run ruff check .
poetry run black . --check
poetry run isort . --check --diff
poetry run python manage.py spectacular --validate --file "$env:TEMP/rt-openapi.yaml"
git diff --check
```

Coverage/type runners remain repository tooling gaps. Hosted CI/deployment is
unverified until actual evidence exists. Live query counts exclude tenant/auth
middleware and initial connection setup. Expect a count query and, for
nonempty in-range pages, page selection plus one joined hydration query,
independent of page length. Capture representative 0/1/10/25 row counts.

## Acceptance criteria

Compact additive fields and nulls match M5B; old primitives remain. Search
source matching and weights are unchanged. Tenant-safe count/page/hydration,
stable order, correct out-of-range count, date semantics, canonical errors,
generated schema and focused/full gates pass. Real SQL Server FTS evidence is
required; mocked SQL tests alone are insufficient.

## Progress

- [x] Inspect instructions, API code and read-only M6A consumer contract.
- [x] Update schema and date validation before service behavior.
- [x] Implement count, stable order and bounded metadata hydration.
- [x] Expand focused negative/contract tests and run full available gate.
- [x] Capture actual SQL Server FTS evidence and query counts.
- [x] Record final M6C handoff and limitations.

## Surprises & Discoveries

- Visibility and scan flags currently do not constrain tenant-scoped metadata
  reads. Matching metadata is distinct from serving uploaded file bytes.
- Existing Poetry 2.1.4 / Python 3.12.10 works through the established approved
  execution escalation. No dependency/environment/schema change was needed.
- SQL Server's raw UUID strings can be uppercase while ORM UUIDs are lowercase;
  hydration keys compare normalized UUID strings and preserve primitive output.
- The configured local DB has one tenant and 11 requests, 8 comments and 3
  attachments. The broadest sampled prefix yielded 9 requests, so requested
  page sizes 10 and 25 were measured at 9 actual rows. Exact 10/25-row live
  fixtures were not introduced into original `rt`.

## Decision Log

- Use an independent count over the same grouped FTS CTE. Empty/out-of-range
  pages return the real total; skip unused selection/hydration when possible.
- Preserve explicit DateTime upper bounds as inclusive instants; use exclusive
  upper bounds only for date-only input. Apply Django configured timezone,
  never tenant-specific settings.
- Reuse M5B summary serializers without importing broader Detail data.
- Convert SQL date parameters with the existing backend datetime adapter;
  calendar-day bounds in America/El_Salvador normalize to UTC correctly.
- Keep count independent of page rows. An empty/out-of-range result needs only
  count; a populated page uses count + ranked page + one ORM hydration query.
- Reject cross-tenant status/flow metadata with a generic canonical server error.
  Do not synthesize labels or introduce per-user membership queries per row.

## Outcomes & Retrospective

M6B is complete for local API verification on `feat/search-result-contract`
(2026-10-01). Changed `apps/rt/search.py`, `apps/rt/serializers.py`,
`apps/rt/views.py`, `tests/test_search.py`, `CHANGELOG.md`, and this plan.

Verification evidence:

- Search suite: 41 passed; with `tests/test_openapi.py`: 42 passed. Full pytest:
  257 passed. Django check: 0 issues. Ruff, Black (53 unchanged), isort,
  generated OpenAPI validation and `git diff --check` passed.
- Permanent tests cover additive primitive/summary shape, null/assigned users,
  tenant-isolated hydration, foreign metadata denial, identical count/page
  predicates, all three source branches/weights/joins, filters, source dedup,
  fixed stable order, day/instant bounds and timezone, malformed UUID/ranges,
  page bounds, unknown tenant, 401/missing tenant, canonical errors and schema.
  Mocked service budgets for 0/1/10/25 rows are 1/3/3/3 queries; these are not
  claimed as SQL Server performance measurements.
- Actual local SQL Server FTS SELECT-only checks passed request, comment and
  attachment matching with weights 30/20/10; mixed-source MAX/source union;
  UUID filters; date-only and instant bounds; empty/out-of-range total; and
  empty count/results for unknown tenant IDs across all three sources.

| Requested page size | Actual result rows | Service SQL queries | Total |
| --- | --- | --- | --- |
| 1 | 1 | 3 | 9 |
| 10 | 9 | 3 | 9 |
| 25 | 9 | 3 | 9 |
| No matches | 0 | 1 | 0 |
| Page 9999 | 0 | 1 | 9 |

Counts exclude connection initialization, middleware, auth and fixture
discovery reads. No production/test data was changed; the temporary SELECT-only
verifier was removed. A real second-tenant fixture and exact 10/25-match live
samples remain unavailable. Hosted CI/deployment and missing coverage/type
runners are not passed or waived. Separate count/page/hydration statements do
not promise a concurrent-write snapshot: deleted rows may disappear between
stages, producing a sparse page while retaining the measured total.

Exact Web M6C handoff:

- Consume existing primitive identity/title/priority/timestamps, rank and
  match_sources plus `status` (status_id/name/category/is_terminal), `requester`
  and nullable `assignee` (user_id/display_name/email), and `flow` (flow_id/name).
- Remove `enrichSearchResultsWithDetail` and every per-result Detail read;
  remove the fallback that uses full description as a fake matched snippet.
- Stop sending ignored `status`, `assignee`, `flow`, `tag`, and `sort` keys.
  Use single `status_id`, `assignee_id`, and `flow_id` UUIDs, never label aliases
  or an Unassigned sentinel. Existing catalogs are `/api/flows/`,
  `/api/flows/{flow_id}/statuses/`, and `/api/users/?search=...` with their
  existing pagination; no new catalog was added.
- Send required `q`, `page` and `page_size` (default 25, max 100). Optional
  `types=request,comment,attachment` and created/updated ranges remain API
  capabilities. Order is fixed MAX source weight descending, updated time
  descending, RequestId ascending; no sort control is supported.
- Send date-only From/To as YYYY-MM-DD for whole calendar days in configured
  API TIME_ZONE (not tenant timezone). From is inclusive day start; To is
  exclusive next-day start. Explicit DateTime bounds retain inclusive instant
  comparisons. Keep the custom `{count,page,page_size,results}` envelope.

Scope review: no Web/Dashboard/Detail/Create/Admin/AppShell change; no route,
RBAC, Human ID FTS, tags, snippets/highlights, selectable sort, priority/requester/
due filter, saved view, command palette, dependency or schema migration added.
