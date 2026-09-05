# Sprint 3 API Demo Script

## 1. Start and Verify

1. Start SQL Server, MinIO, Redis, MailHog, and the API.
2. Run `poetry run python manage.py check`.
3. Open `/api/docs` and confirm API version `0.2.0`.
4. Use the secret-free Postman environment and enter JWT credentials locally.

## 2. Authentication and Admin Context

1. Login and verify the JWT.
2. Call `/api/admin/me/permissions/` for ACME.
3. Show RT Admin roles and effective permissions.
4. Call `/api/admin/audit/?page=1&page_size=10` and demonstrate filters.

## 3. Administration

1. Open workflow list/detail and show statuses and transitions.
2. Show paginated users, memberships, roles, and permission catalogue.
3. Demonstrate final-admin protection using disposable data only.
4. Show four SLA policies and report summary.
5. Download CSV export and verify its filename and columns.

## 4. Tenant Configuration

1. Show tenant settings and sensitive-value masking.
2. Show the four feature flags.
3. Show the four notification templates and supported placeholders.
4. Use reversible PATCH requests only, then restore original values.

## 5. Request Lifecycle

1. Open a request detail bundle.
2. Add a comment and grouped attachment on disposable/demo data.
3. Search by title, comment text, and attachment filename.
4. Show available transitions, transition the request, close it, and reopen it.
5. Inspect request activity after each action.

## 6. Notifications and Finish

1. Inspect MailHog for created, assigned, comment-added, and closed messages.
2. Confirm Human ID, title, request ID, tenant URL, recipients, and fallback.
3. Restore reversible values and leave `allow_mutation=false`.
4. Show `docs/release-readiness.md` and state the current go/no-go decision.
