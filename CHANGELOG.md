# Changelog

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
