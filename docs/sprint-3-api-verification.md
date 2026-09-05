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

Import:

```text
postman/RT-Sprint-3.postman_collection.json
postman/RT-Sprint-2-Regression.postman_collection.json
postman/RT-Local.postman_environment.json
```

Enter username/password or a short-lived TOKEN only in the local Postman
environment. Never save/export populated secrets. Use `Authorization: Bearer
{{TOKEN}}` and `X-Tenant: {{tenant_code}}`.

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

Run read-only collections:

```powershell
npx newman run postman/RT-Sprint-3.postman_collection.json `
  -e postman/RT-Local.postman_environment.json `
  --env-var TOKEN=$env:RT_TOKEN `
  --env-var allow_mutation=false `
  --bail

npx newman run postman/RT-Sprint-2-Regression.postman_collection.json `
  -e postman/RT-Local.postman_environment.json `
  --env-var TOKEN=$env:RT_TOKEN `
  --bail
```

The complete mutation run requires a disposable/restorable database with a
second tenant and foreign IDs. Set `allow_mutation=true` only there.

Run `db/verify-sprint3-release.sql` through the approved read-only SQL path and
retain its output with the release evidence.

## Release Evidence

Record the database backup, script checksums, generated OpenAPI result, pytest
count, Postman environment/collection version, MailHog evidence, commit, PR,
and release tag before publishing `0.2.0`.

## Day 10 Results

- Targeted tests: 27 passed.
- Complete pytest: 189 passed.
- Django check, Ruff, Black, isort, and OpenAPI validation passed.
- Sprint 3 mutation collection: 69 requests, 178 assertions, zero skips or
  failures against disposable `rt_day10` with ACME/BETA fixtures.
- Sprint 3 guarded read-only run: 32 requests, 92 assertions, zero failures.
- Sprint 2 regression: 8 requests, 17 assertions, zero failures.
- SQL checks: 18 expected tables, 11 SLA columns, 18 permissions, canonical
  role counts 18/9/5/4/2, zero duplicate groups, zero tenant mismatches, 15
  expected indexes, and three AUTO FTS indexes.
- MailHog: created, assigned, custom comment-added, and closed events present;
  recipient headers were unique.
- Confirmed fix: SQL Server-safe composite-key deletes for MembershipRole and
  RolePermission.
- Cleanup: disposable database/container/backup/image removed; original `rt`
  contains zero Day10 test records.
