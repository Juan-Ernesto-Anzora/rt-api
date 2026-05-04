# rt-api scaffold (Django + DRF + SimpleJWT + Swagger + MinIO presign)

## Quick start
```bash
# Python 3.12 + Poetry
poetry install
cp .env.example .env
poetry run python manage.py migrate   # (no models yet; this sets up Django tables only)
poetry run python manage.py createsuperuser
poetry run python manage.py runserver 0.0.0.0:8000
```

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
