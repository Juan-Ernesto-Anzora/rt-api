# Sprint 3 API Verification

## Environment

Copy `.env.example` to `.env` and replace every `replace-with-...` value with
the matching local `softdev-infra` credential. `.env` is ignored by Git.

Start SQL Server, MinIO, Redis, and MailHog, then start the API:

```powershell
poetry install
poetry run python manage.py check
poetry run python manage.py runserver 0.0.0.0:8000
```

## Database Upgrade Order

Back up the database before applying scripts. Existing databases use this
rerunnable order:

```text
db/upgrade-sprint3-admin-workflows.sql
db/upgrade-sprint3-admin-users-roles.sql
db/upgrade-sprint3-sla-reports.sql
db/upgrade-sprint3-admin-settings.sql
db/upgrade-sprint3-api-polish.sql
```

Run each script through the approved `rt-infra` SQL deployment path. Do not run
`db/create-rt-database.sql` against an existing database because it is a clean
build script. Seed upgrades add only missing rows and do not overwrite tenant
customizations.

Verify that `SlaPolicy` includes `Priority`, `ResponseMinutes`,
`ResolutionMinutes`, `IsActive`, and `UpdatedAt`, and that Activity has
`IX_Activity_TenantCreated`.

## Automated Checks

```powershell
poetry run python manage.py check
poetry run pytest -q
poetry run ruff check .
poetry run black . --check
poetry run isort . --check --diff
poetry run python manage.py spectacular --file .agent/tmp/rt-openapi.yaml --validate
git diff --check
```

## Postman Smoke

Use `Authorization: Bearer {{TOKEN}}` and `X-Tenant: {{tenant_code}}`.

1. Verify `/api/admin/me/permissions/` and `/api/admin/audit/`.
2. Verify workflow, user, membership, role, SLA, settings, flag, and template
   reads and one reversible write in each area.
3. Verify reports summary and CSV export with their exact permissions.
4. Verify audit filters including `entity_id`, date range, `page`, and
   `page_size`.
5. Repeat representative requests without JWT/tenant, with malformed UUIDs,
   cross-tenant IDs, duplicates, and insufficient permissions.
6. Trigger created, assigned, comment-added, and closed emails and inspect
   MailHog. SMTP failure must not break the originating request action.

## Release Evidence

Record the database backup, script checksums, generated OpenAPI result, pytest
count, Postman environment/collection version, MailHog evidence, commit, PR,
and release tag before publishing `0.2.0`.
