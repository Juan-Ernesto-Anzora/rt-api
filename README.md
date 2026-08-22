# rt-api scaffold (Django + DRF + SimpleJWT + Swagger + MinIO presign)

## Quick start
```bash
# Python 3.12 + Poetry
poetry install
cp .env.example .env
## Replace every replace-with-... value using local softdev-infra credentials.
poetry run python manage.py migrate   # (no models yet; this sets up Django tables only)
poetry run python manage.py createsuperuser
poetry run python manage.py runserver 0.0.0.0:8000
```

For an existing RT database, apply the idempotent Sprint 3 scripts in the order
listed in `docs/sprint-3-api-verification.md`. Do not use
`db/create-rt-database.sql` as an upgrade script. Canonical roles, permissions,
SLA demo policies, settings, flags, and templates are inserted only when
missing; administrator changes are not overwritten.

## Endpoints
- `GET /api/health`
- `POST /api/auth/jwt/create` (username/password -> access/refresh)
- `POST /api/auth/jwt/refresh`
- `POST /api/auth/jwt/verify`
- `GET /api/docs` (Swagger UI)
- `POST /api/storage/presign` (JWT required) body: `{ "filename": "a.png", "content_type": "image/png" }`
- `POST /api/attachments/init` (JWT + `X-Tenant` required) body: `{ "request_id": "<uuid>", "files": [{ "filename": "a.png", "content_type": "image/png" }] }`
- `POST /api/attachments/finalize` (JWT + `X-Tenant` required) creates one grouped comment bubble plus attachment rows with `scanstatus=pending`
- `GET /api/search?q=password` (JWT + `X-Tenant` required) searches request title/description, comment text, and attachment filenames with SQL Server Full-Text Search. Supports `types`, `status_id`, `assignee_id`, `flow_id`, `created_from`, `created_to`, `updated_from`, `updated_to`, `page`, and `page_size`.

## Notes
- DB: SQL Server via `mssql-django` + `pyodbc`. Update env for your instance.
- MinIO: pre-signed PUT URLs using boto3 S3 client.
- CORS: open in dev; tighten later.
- Sprint 3 verification and database instructions:
  `docs/sprint-3-api-verification.md`.
- Known release follow-ups: `docs/sprint-3-known-issues.md`.

## Sprint 1 Smoke Test
1. Start API
2. Login
3. Set TOKEN
4. Create request
5. Add comment
6. Upload attachments
7. Search
