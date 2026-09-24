# M5B Dashboard request list contract

## Purpose

`GET /api/requests/` must supply readable Dashboard row labels and honor the
existing Web queue/filter query parameters. After Web M5C removes its per-row
Detail requests, one list request should supply one queue page. This plan is
limited to the API; deployed behavior is not established by this checkout.

## Repository orientation

- `apps/rt/serializers.py`: request write/detail/list and filter serializers.
- `apps/rt/views.py`: tenant-scoped RequestViewSet, summary and OpenAPI source.
- `apps/rt/models.py`: unmanaged Request, Flow, Status and User relations.
- `apps/rt/services/admin_permissions.py`: authoritative tenant user mapping.
- `apps/common/pagination.py`: page/page_size, default 25, maximum 100.
- `tests/test_dashboard_request_list.py`: focused list contract/filter tests.
- `../rt-web-skeleton/docs/plans/sprint-4/m5-dashboard-data-contract.md` and
  `../rt-web-skeleton/src/api/dashboard.ts`: read-only M5A consumer evidence.

## Current behavior

The list already returns `request_id`, `human_id`, `title`, `description`,
`priority`, `flow_id`, `status_id`, `requester_id`, `assignee_id`,
`custom_fields`, `due_at`, `created_at`, and `updated_at`. Its tenant queryset
already joins flow, status, requester and assignee. It did not interpret Web's
`mine`, `requested_by_me`, `closed`, `priority`, `assignee`, or `sort`; Web
loaded Detail for each row to obtain labels. The separate summary counts four
current KPIs without list-filter coupling.

## Desired behavior and scope

Keep existing fields and write/detail behavior. Add list-only `status`
(`status_id`, `name`, `category`, `is_terminal`), `requester` and nullable
`assignee` (`user_id`, `display_name`, `email`), and `flow` (`flow_id`, `name`).
No comments, attachments, activity, tags, new route, KPI, permission, SQL,
schema change, Web edit, or Search optimization belongs to M5B.

## Query contract

All predicates apply to the existing tenant queryset before pagination and
combine by AND:

| Parameter | Predicate |
| --- | --- |
| omitted / `mine=true` | Unfiltered / assignee is current tenant RT user |
| `mine=false` | Assignee differs from current tenant RT user or is null |
| `requested_by_me=true` | Requester is current tenant RT user; false is unfiltered |
| `closed=true` | Status category is closed or status is terminal |
| `closed=false` | Neither closed category nor terminal |
| `priority=low\|normal\|high\|urgent` | Exact stored priority; `high` excludes urgent |
| `assignee=unassigned` | Assignee is null |
| `sort=-updated_at` / `updated_at` | Descending / ascending updated time; request ID breaks ties |

Default order for list is `-updated_at, request_id`; explicit ascending is
`updated_at, request_id`. Absent filters retain tenant-wide access under the
current JWT policy. Invalid structured values return 400. Self filters with
no tenant RT user return 403. The existing Web `my_tasks`, `other_tasks`,
`my_requests`, and `recently_updated` labels map respectively to `mine=true`,
`mine=false`, `requested_by_me=true`, and no self filter with recency sort.
Web's My Open currently overrides `mine=false` with `mine=true`; M5C should
select My Tasks plus `closed=false` visibly. High Priority, Closed and
Unassigned use the corresponding filters above. Recently Updated quick action
should select that queue. Page/page_size preserve the DRF envelope
`{count,next,previous,results}`; Web sends page 1, size 10.

## Implementation and verification

1. Add list-only read fields and filter contract in `apps/rt/serializers.py`.
2. Apply validated tenant-scoped queryset predicates, stable ordering, and
   list OpenAPI annotation in `apps/rt/views.py`.
3. Check focused serializer/filter/auth/tenant tests in
   `tests/test_dashboard_request_list.py`. The list's existing `select_related`
   fetches all four related rows; measure bounded 0/1/10-row serialization
   against configured SQL Server separately from mocked unit tests.
4. Run `poetry run pytest tests/test_dashboard_request_list.py -q`, then the
   full `AGENTS.md` gate: Django check, full pytest, Ruff, Black, isort,
   `poetry run python manage.py spectacular --validate --file
   "$env:TEMP/rt-openapi.yaml"`, and `git diff --check`.
5. In a live SQL Server test environment, verify 0/1/10-row query counts,
   cross-tenant fixtures, actual generated schema, pagination, and JWT/tenant
   negatives. Do not equate mocked tests with this evidence.

## Acceptance criteria

- Existing list clients retain every old field and pagination shape.
- All four queues and current quick filters return correct tenant-scoped pages.
- Invalid values return 400; missing self identity returns 403.
- Related labels and null assignee serialize without per-row ORM queries.
- Generated OpenAPI names new fields and parameters.
- Full available gate passes before PR; unavailable gates are reported.

## Progress

- [x] Read API instructions, code, Sprint 3 evidence, and Web M5A contract.
- [x] Add list-only summaries, validated filters, ordering, and OpenAPI source.
- [x] Add focused contract and filter tests.
- [x] Run focused and full API tests and generated-schema validation in Poetry.
- [x] Measure 0/1/10-row list query and serialization on local SQL Server.
- [ ] Run live cross-tenant checks when a disposable second tenant is available.

## Surprises & Discoveries

- Web's quick My Open currently rewrites `mine=false` to `mine=true`, so it can
  disagree with a visible Other Tasks tab. API honors the actual sent query;
  M5C must align visible queue state.
- Initial `poetry` calls failed because the sandbox denied execution of the
  pipx launcher's existing Python 3.12 executable. `Test-Path` and `Get-Item`
  confirmed the interpreter exists; direct launch returned `Acceso denegado`.
  Approved execution escalation ran Poetry 2.1.4 and the existing valid
  `rt-api-jcEUa3Im-py3.12` virtualenv with Python 3.12.10. No workstation or
  dependency repair, lockfile change, or repository compatibility change was
  needed.
- First focused run exposed a `NameError`: `RequestListSerializer` referenced
  `UserLookupSerializer` before its definition. Moving the list serializer
  below the lookup class fixed collection. Schema inspection then exposed an
  inaccurate non-nullable nested `assignee` annotation; `allow_null=True`
  fixed the generated contract.
- Local SQL Server responded to SELECT-only connectivity checks. ACME list
  samples executed 0 queries for 0 rows, 1 for 1 row, and 1 for 10 rows,
  including serialization with `select_related`. The DB has only one tenant,
  so live cross-tenant negatives are unavailable without disposable fixtures.

## Decision Log

- Extend the existing list route with a list-only serializer; retain the write
  serializer and Detail contract.
- Reuse the existing tenant RT user resolver for self filters. Return 403 when
  identity/membership cannot be resolved, including `mine=false`.
- Use status category or terminal flag for closed and its complement for active,
  matching the existing due KPI active predicate.
- Retain the historical descending updated-time default and add request ID as
  a stable tie-breaker. Only support the Web's existing sort and its inverse.
- Use existing pipx Poetry/virtualenv through approved execution escalation;
  no machine-level reinstall was justified after confirming sandbox denial.
- Keep cross-tenant tests at the tenant-queryset boundary and report the lack
  of a second live tenant explicitly. Do not write test fixtures into `rt`.

## Outcomes & Retrospective

Implementation is verified locally on `feat/dashboard-request-list-contract`:

- Focused M5B: 34 passed. Full pytest: 223 passed. Existing dashboard summary
  regressions remain green. Django check (0 issues), Ruff, Black (53 unchanged),
  isort, generated OpenAPI validation, and `git diff --check` passed.
- Focused tests cover list fields/nulls, endpoint pagination, tenant-first
  filtering for every queue/quick-filter shape, authoritative self identity,
  400/401/403 behavior, deterministic order construction, OpenAPI enums and
  nullability, and no cursor use for 0/1/10 preloaded serialized rows.
- SQL Server read-only evidence: 0/1/10 rows resulted in 0/1/1 list-plus-
  serialization queries. Bounded live ORM samples for `mine=true/false`,
  `requested_by_me=true`, `closed=true/false`, `priority=high`, unassigned,
  and `mine=true&closed=false` executed and returned only ACME rows. The
  selected user had no My Tasks/My Requests rows. Only one tenant exists, so
  live cross-tenant negatives and populated self-queue behavior remain
  unverified. No mutation, hosted CI, or deployed verification ran.
- M5C must consume `status`, `requester`, `assignee`, and `flow` from list
  results; retain `request_id`, `human_id`, priority, due/updated timestamps,
  and the paginated envelope; remove every Home per-row Detail fetch. Use
  `mine=true` for My Tasks, `mine=false` for Other Tasks,
  `requested_by_me=true` for My Requests, and no self filter for Recently
  Updated. Quick filters use `mine=true&closed=false`, `priority=high`,
  `closed=true`, or `assignee=unassigned`; `sort=-updated_at` and
  `page=1&page_size=10` are the current Web defaults. My Open must visibly
  select My Tasks when it overrides another queue.
