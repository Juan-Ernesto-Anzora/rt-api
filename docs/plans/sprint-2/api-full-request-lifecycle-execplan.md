# Sprint 2 API ExecPlan — Full Request Lifecycle

## Purpose

This plan completes the backend side of the request lifecycle. After the change, users can create a request with clean public API fields, open a full request detail payload, transition or close the request, see dashboard summary counts, and trigger baseline notification events.

## Repository orientation

This plan applies to `rt-api`. Relevant areas: `apps/rt/models.py`, `apps/rt/serializers/`, `apps/rt/views/`, `apps/rt/services/`, `rt_api/urls.py`, OpenAPI files, `AGENTS.md`, and `.agent/PLANS.md`.

## Current behavior

Sprint 1 has JWT auth, tenant enforcement, request models, comments, grouped uploads, search, and dashboard usage. Some APIs may still expose internal Django field names like `flowid_id`.

## Desired behavior

Expose clean public JSON fields: `request_id`, `human_id`, `flow_id`, `status_id`, `requester_id`, `assignee_id`, `created_at`, and `updated_at`. Add request detail, create flow hardening, transitions, dashboard summary, and notification baseline.

## Scope

In scope: API field cleanup, request detail endpoint, create request hardening, transition/close/reopen endpoints, dashboard summary endpoint, notification service, tests, OpenAPI updates. Out of scope: OIDC/AD, Channels, SLA engine, full admin workflow UI.

## Implementation plan

### Milestone 1: Public API naming cleanup

Update serializers so inputs and outputs use clean snake_case fields. Keep internal model names private. Add tests for invalid GUIDs returning 400 instead of 500.

### Milestone 2: Request detail payload

Add or harden `GET /api/requests/{id}/detail/` or equivalent detail response. Include request header, requester, assignee, flow, status, comments, attachments, activity, and tags.

### Milestone 3: Create request full API flow

Validate flow/status relationship, generate `HumanId`, assign tenant, create `Activity` type `request.created`, and return clean JSON.

### Milestone 4: Workflow transitions

Add `available-transitions`, `transition`, `close`, and `reopen` endpoints. Validate allowed transitions, create optional comment, and create activity.

### Milestone 5: Dashboard summary

Add `GET /api/dashboard/summary/` returning open, in_progress, waiting, closed, due_today, overdue, assigned_to_me, and unassigned.

### Milestone 6: Notification baseline

Add `apps/rt/services/notification_service.py`. Send Mailhog-visible emails for request created, assigned, comment added, and closed. Email failure must not break the main action.

## Tests and verification

Run `poetry run pytest`. Manually verify Postman create request, request detail, transition/close, dashboard summary, and Mailhog email.

## Acceptance criteria

Public API no longer requires internal fields; request detail supports web; transitions work; dashboard summary exists; notifications work locally; OpenAPI is updated; tests pass.

## Progress

- [ ] Milestone 1 completed.
- [ ] Milestone 2 completed.
- [ ] Milestone 3 completed.
- [ ] Milestone 4 completed.
- [ ] Milestone 5 completed.
- [ ] Milestone 6 completed.

## Surprises & Discoveries

Record findings here.

## Decision Log

Record decisions here.

## Outcomes & Retrospective

Complete after merge.
