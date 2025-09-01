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

## Notes
- DB: SQL Server via `mssql-django` + `pyodbc`. Update env for your instance.
- MinIO: pre-signed PUT URLs using boto3 S3 client.
- CORS: open in dev; tighten later.
