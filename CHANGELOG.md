# Changelog

## [Unreleased]

- Unified Search now includes compact status, requester, assignee and flow
  summaries without per-result Detail reads. Existing fields remain available.
- Search totals remain correct on empty pages; tied results use stable request
  ID ordering. Date-only ranges include whole days in the API timezone.

## [0.2.0] - 2026-08-22

### Added

- Tenant-scoped administration for workflows, users, memberships, roles,
  permissions, SLA policies, settings, feature flags, and notification templates.
- Request reporting summary, safe CSV export, admin audit filters, and generated
  OpenAPI examples.

### Changed

- API errors now use the stable `code`, `message`, and `details` envelope.
- Workflow administration requires `admin.read` and `admin.workflows`.
- Dashboard assignment counts resolve the RT domain user for the active tenant.

### Compatibility

- Sprint 2 successful response fields, status codes, and slash/no-slash route
  aliases remain available.
- Database upgrades are required in the order documented in
  `docs/sprint-3-api-verification.md`.
