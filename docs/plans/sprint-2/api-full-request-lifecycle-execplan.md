# Sprint 2 API ExecPlan — Full Request Lifecycle

## Purpose

This plan completes the backend side of the request lifecycle. After the change, users can create a request with clean public API fields, open a full request detail payload, transition or close the request, see dashboard summary counts, and trigger baseline notification events.

## Repository orientation

This plan applies to `rt-api`. Relevant areas:

- `apps/rt/models.py`: unmanaged SQL Server models for `Tenant`, `User`, `Flow`, `Status`, `Request`, `Comment`, `Attachment`, `Activity`, and workflow tables.
- `apps/rt/serializers.py`: current request, detail, comment, upload, activity, and search serializers.
- `apps/rt/views.py`: `RequestViewSet`, nested comments/attachments, uploads, search, and current `generate_human_id` helper.
- `apps/rt/search.py`: SQL Server FTS search service.
- `rt_api/urls.py`: DRF router for `/api/requests/`, nested request routes, auth, uploads, search, schema, and Swagger UI.
- `tests/`: pytest coverage for auth/docs, health, comments, uploads, search, and request detail.
- `AGENTS.md` and `.agent/PLANS.md`: contributor and ExecPlan rules.

There is no checked-in `openapi-rt-with-examples.yaml` or other OpenAPI source file at the time this plan was updated. The repository currently exposes generated OpenAPI through drf-spectacular at `GET /api/schema` and Swagger UI at `GET /api/docs`.

## Current behavior

Sprint 1 has JWT auth, tenant enforcement, request models, comments, grouped uploads, search, and dashboard usage. Day 1-2 request detail work added:

- `GET /api/requests/{id}/detail/` with request, comments, attachments, and activity.
- `GET /api/requests/{id}/activities/` as an alias to activity timeline.
- Trailing-slash aliases for nested comments and attachments.
- `RequestDetailSerializer` with public fields such as `request_id`, `human_id`, `flow_id`, `status_id`, `requester_id`, `assignee_id`, `due_at`, `created_at`, and `updated_at`.

Request creation is not yet clean enough for Day 3-4. `RequestSerializer` still accepts and returns internal Django field names: `requestid`, `humanid`, `flowid_id`, `statusid_id`, `requesterid_id`, `assigneeid_id`, `dueat`, `createdat`, and `updatedat`. `RequestViewSet.perform_create` generates `HumanId` and assigns tenant, but it does not yet validate flow/status/requester/assignee tenant ownership, does not validate that `status_id` belongs to `flow_id`, and does not create `Activity` type `request.created`.

## Desired behavior

Expose clean public JSON fields: `request_id`, `human_id`, `flow_id`, `status_id`, `requester_id`, `assignee_id`, `created_at`, and `updated_at`. Add request detail, create flow hardening, transitions, dashboard summary, and notification baseline.

For Day 3-4, `POST /api/requests/` must accept only public field names, enforce tenant-scoped IDs, validate the flow/status relationship, generate `HumanId`, create an auditable `Activity`, and return the same clean request shape used by detail reads.

## Scope

In scope: API field cleanup, request detail endpoint, create request hardening, transition/close/reopen endpoints, dashboard summary endpoint, notification service, tests, OpenAPI updates. Out of scope: OIDC/AD, Channels, SLA engine, full admin workflow UI.

## Implementation plan

### Milestone 1: Public API naming cleanup

Update serializers so inputs and outputs use clean snake_case fields. Keep internal model names private. Add tests for invalid GUIDs returning 400 instead of 500.

### Milestone 2: Request detail payload

Add or harden `GET /api/requests/{id}/detail/` or equivalent detail response. Include request header, requester, assignee, flow, status, comments, attachments, activity, and tags.

### Milestone 3: Create request full API flow

Day 3-4 target branch: `feat/api-create-request-flow`.

Update only API code and tests needed for robust request creation. The next implementation pass must cover:

1. Clean public API fields.
   - Edit `apps/rt/serializers.py`.
   - Add or replace the create/list request serializer so request writes use `flow_id`, `status_id`, `requester_id`, optional `assignee_id`, optional `due_at`, and optional `custom_fields`.
   - Stop requiring client payloads to send `flowid_id`, `statusid_id`, `requesterid_id`, `assigneeid_id`, or `dueat`.
   - Return public response fields: `request_id`, `human_id`, `title`, `description`, `priority`, `flow_id`, `status_id`, `requester_id`, `assignee_id`, `custom_fields`, `due_at`, `created_at`, and `updated_at`.
   - Preserve existing `RequestDetailSerializer` shape for `GET /api/requests/{id}/` and `/detail/`.

2. Request creation validation.
   - Validate `title` is present and non-blank.
   - Validate `priority` is present and one of the accepted local values: `low`, `normal`, `high`, or `urgent`.
   - Validate `flow_id`, `status_id`, and `requester_id` are valid UUIDs.
   - Validate optional `assignee_id` is either null/omitted or a valid UUID.
   - Validate `flow_id`, `status_id`, `requester_id`, and optional `assignee_id` all belong to the active `request.tenant_id`.
   - Validate `status_id` belongs to the provided `flow_id`.
   - Return JSON validation errors with `code`, `message`, and `details[]`; never return SQL Server integrity errors or Django stack traces for bad input.

3. HumanId generation.
   - Keep `generate_human_id` behavior using `dbo.IdSequence` with `UPDLOCK` and `HOLDLOCK`.
   - Ensure creation remains atomic so `Request` insert, `HumanId` sequence update/insert, and `Activity` creation succeed or fail together.
   - Verify generated IDs keep the current format `RT-{year}-{sequence:06d}`.

4. Tenant enforcement.
   - Continue deriving tenant from `X-Tenant` middleware as `request.tenant_id`.
   - Ignore any tenant field in client payload if provided; clients must not be able to choose another tenant.
   - All lookup queries during create must filter by `tenantid=request.tenant_id`.
   - Negative tests must prove cross-tenant `flow_id`, `status_id`, `requester_id`, or `assignee_id` cannot create a request.

5. Activity creation.
   - Create one `Activity` row with type `request.created`.
   - Set `tenantid` to the request tenant, `requestid` to the created request, `actorid` to the requester until auth-user to `dbo.User` mapping exists, and `createdat` to the same creation timestamp.
   - Include a compact JSON payload with at least `human_id`, `title`, `flow_id`, `status_id`, `requester_id`, and `assignee_id`.
   - Add tests that assert exactly one `request.created` activity is attempted on successful create.

6. OpenAPI/schema handling.
   - Because no static OpenAPI source file currently exists, update serializer names and drf-spectacular annotations only as needed so `GET /api/schema` reflects public create fields.
   - If a static OpenAPI source file is later added, update it before code implementation per `AGENTS.md`.

Implementation files expected for this milestone:

- `apps/rt/serializers.py`
- `apps/rt/views.py`
- optional new `apps/rt/services/request_service.py` if create logic becomes too large for `RequestViewSet.perform_create`
- `tests/test_request_create.py`
- optional updates to `tests/test_request_detail.py` if shared serializers change

### Milestone 4: Workflow transitions

Add `available-transitions`, `transition`, `close`, and `reopen` endpoints. Validate allowed transitions, create optional comment, and create activity.

### Milestone 5: Dashboard summary

Add `GET /api/dashboard/summary/` returning open, in_progress, waiting, closed, due_today, overdue, assigned_to_me, and unassigned.

### Milestone 6: Notification baseline

Add `apps/rt/services/notification_service.py`. Send Mailhog-visible emails for request created, assigned, comment added, and closed. Email failure must not break the main action.

## Tests and verification

### Automated checks for every milestone

Run these from repository root:

```bash
poetry run python manage.py check
poetry run pytest -q
poetry run ruff check .
poetry run black . --check
poetry run isort . --check --diff
git diff --check
```

### Day 3-4 pytest coverage

Add `tests/test_request_create.py` with tests for:

- `RequestSerializer` or create serializer accepts public fields: `flow_id`, `status_id`, `requester_id`, optional `assignee_id`, `due_at`, and `custom_fields`.
- Serializer rejects legacy/internal-only payload names for create, or maps them only if explicit backward compatibility is intentionally chosen and documented in the Decision Log.
- `RequestViewSet.perform_create` or request service saves:
  - `tenantid_id` from `request.tenant_id`
  - generated `humanid`
  - `createdat` and `updatedat`
  - `flowid_id`, `statusid_id`, `requesterid_id`, optional `assigneeid_id`
- `generate_human_id` keeps `RT-{year}-{sequence:06d}` and updates/inserts `dbo.IdSequence`.
- Successful create attempts `Activity.objects.create(...)` with `type="request.created"`.
- Status from a different flow returns validation error.
- Flow/status/requester/assignee from another tenant returns validation error.
- Missing tenant context returns a JSON error, not an insert attempt.
- Invalid UUID input returns 400 validation error, not 500.

### Day 3-4 Postman smoke verification

Environment:

```text
base_url=http://localhost:8000
tenant_code=ACME
TOKEN=<JWT access token>
flow_id=<GUID from ACME dbo.Flow>
status_id=<GUID from ACME dbo.Status belonging to flow_id>
requester_id=<GUID from ACME dbo.User>
assignee_id=<GUID from ACME dbo.User or null>
```

Headers for all protected calls:

```text
Authorization: Bearer {{TOKEN}}
X-Tenant: {{tenant_code}}
Content-Type: application/json
```

1. Create request with assignee:

```http
POST {{base_url}}/api/requests/
```

```json
{
  "title": "Sprint 2 Postman create smoke",
  "description": "Created from Postman during Sprint 2 Day 3-4.",
  "flow_id": "{{flow_id}}",
  "status_id": "{{status_id}}",
  "requester_id": "{{requester_id}}",
  "assignee_id": "{{assignee_id}}",
  "priority": "normal",
  "due_at": "2026-05-29T17:00:00Z",
  "custom_fields": "{\"source\":\"postman\"}"
}
```

Expected:

```text
201 Created
response has request_id, human_id, title, flow_id, status_id, requester_id,
assignee_id, priority, due_at, created_at, updated_at
response does not require or expose flowid_id/statusid_id/requesterid_id/assigneeid_id
human_id matches RT-2026-000001 style
```

Save `request_id` from the response.

2. Verify detail:

```http
GET {{base_url}}/api/requests/{{request_id}}/detail/
```

Expected:

```text
200 OK
request.human_id matches create response
request.flow_id/status_id/requester_id/assignee_id match create payload
comments, attachments, and activity arrays are present
activity includes request.created
```

3. Verify activities alias:

```http
GET {{base_url}}/api/requests/{{request_id}}/activities/
```

Expected:

```text
200 OK
at least one item has type=request.created
```

4. Negative: status from another flow:

```http
POST {{base_url}}/api/requests/
```

Use a valid `flow_id` and a `status_id` that belongs to another flow.

Expected:

```text
400 Bad Request
JSON error has code, message, details[]
details identify status_id or flow/status mismatch
```

5. Negative: cross-tenant lookup:

Use `X-Tenant: ACME` with a `flow_id`, `status_id`, requester, or assignee from another tenant.

Expected:

```text
400 Bad Request or 404 Not Found with JSON error
no request is created
no Activity is created
```

6. Negative: invalid UUID:

```json
{
  "title": "Bad UUID smoke",
  "description": "Should fail cleanly.",
  "flow_id": "not-a-guid",
  "status_id": "{{status_id}}",
  "requester_id": "{{requester_id}}",
  "priority": "normal"
}
```

Expected:

```text
400 Bad Request
JSON error, no stack trace
```

## Acceptance criteria

Sprint-level acceptance: public API no longer requires internal fields; request detail supports web; transitions work; dashboard summary exists; notifications work locally; OpenAPI/schema is updated; tests pass.

Day 3-4 acceptance:

- `POST /api/requests/` accepts clean public JSON field names.
- `POST /api/requests/` returns clean public JSON field names.
- Legacy internal create fields are not required by frontend or Postman.
- Tenant is always derived from `X-Tenant`; tenant payload values cannot override it.
- Flow, status, requester, and assignee are tenant-scoped.
- Status must belong to the selected flow.
- `HumanId` is generated server-side with the existing sequence table.
- Successful create writes `Activity` type `request.created`.
- Validation failures return JSON errors with no SQL Server or Django stack traces.
- Pytest and Postman steps in this plan pass.

## Progress

- [ ] Milestone 1 completed.
- [x] Milestone 2 completed.
- [x] Milestone 3 completed.
  - [x] Postman regression fixed: requester/assignee tenant checks use `Membership`, not `User.tenantid`.
- [ ] Milestone 4 completed.
- [ ] Milestone 5 completed.
- [ ] Milestone 6 completed.

## Surprises & Discoveries

- No checked-in OpenAPI source file was found during Day 3-4 planning; current schema is generated by drf-spectacular at `/api/schema`.
- There is no `apps/rt/services/` package yet. Create request logic currently lives in `RequestViewSet.perform_create`.
- Day 1-2 request detail code is present on the current branch, including `RequestDetailSerializer` and `/api/requests/{id}/detail/`.
- Before Milestone 3, create request still used internal serializer fields and did not create `request.created` activity.
- Milestone 3 was small enough to keep in `RequestSerializer` and `RequestViewSet`; no new service module was needed.
- Existing unit-test style avoids live SQL Server calls by monkeypatching model managers and `generate_human_id`.
- Postman found a real create-request bug: `User` has no `tenantid` field, so validating `requester_id` or `assignee_id` with `User.objects.get(..., tenantid=...)` raises `FieldError` and returns 500.
- Tenant membership for users is represented by `Membership.userid` and `Membership.tenantid`; Django lookup fields are `userid_id` and `tenantid_id`.

## Decision Log

- Keep `GET /api/requests/{id}/detail/` for the web request detail page and focus Day 3-4 on `POST /api/requests/`.
- Treat drf-spectacular generated schema as the current OpenAPI surface until a static OpenAPI source file is added.
- Use requester as `Activity.actorid` for request creation until auth-user to `dbo.User` mapping is introduced.
- Accept create-request priorities `low`, `normal`, `high`, and `urgent`, normalizing input to lowercase.
- Keep backward-incompatible internal create field names out of the public create contract; tests assert `flowid_id`, `statusid_id`, and related names are not accepted as the required API fields.
- Validate `requester_id` and optional `assignee_id` against `Membership.objects.filter(userid_id=<user_id>, tenantid_id=<tenant_id>).exists()` instead of filtering `User` by tenant.
- Return serializer `ValidationError` on public fields `requester_id` and `assignee_id` when a user is not a member of the active tenant.

## Outcomes & Retrospective

Milestone 3 complete on `feat/api-create-request-flow`:

- `POST /api/requests/` now uses public request fields and returns public response fields.
- Create validation enforces tenant-scoped `flow_id`, `status_id`, `requester_id`, optional `assignee_id`, and status-to-flow ownership.
- User tenant enforcement now checks `Membership`, preventing the SQL/Django `FieldError` seen in Postman.
- Request creation remains server-owned for `tenantid`, `HumanId`, `createdat`, and `updatedat`.
- Successful create writes `Activity` type `request.created`.
- Focused and full pytest verification passed locally.
