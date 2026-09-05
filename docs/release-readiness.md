# Release Readiness - RT API 0.2.0

## Decision

Status: **GO for merge and release-candidate CI**.

Day 10 completed against a COPY_ONLY clone named `rt_day10`. A BETA workflow
and unassigned domain user existed only in that clone. The disposable database,
API container, backup, and runner image were removed after evidence capture.
SELECT-only checks confirm the original `rt` database contains zero Day10
flows, roles, users, or requests and retains exactly four SLA defaults.

## Automated Verification

| Check | Result |
| --- | --- |
| Django system check | Passed, 0 issues |
| Targeted tests | Passed, 27 |
| Complete pytest | Passed, 189 |
| Ruff / Black / isort | Passed |
| OpenAPI 0.2.0 validation | Passed, 0 errors/warnings |
| Postman contract tests | Passed, 5 |
| SQL release checks | Passed |
| Secret scan | Passed; tracked environment secrets are empty |

## Postman Verification

| Collection | Mode | Result |
| --- | --- | --- |
| RT Sprint 3 API Verification | guarded read-only | 32 requests, 92 assertions, 0 failures |
| RT Sprint 2 Regression | read-only | 8 requests, 17 assertions, 0 failures |
| RT Sprint 3 API Verification | disposable mutation | 69 requests, 178 assertions, 0 skips/failures |

Verified endpoint families: health/JWT, tenant errors, effective permissions,
audit pagination/filters, workflow/status/transition admin, users, memberships,
roles, role/permission assignments/removals, final-admin safeguards, SLA,
reports, CSV, settings, feature flags, templates, lookups, request list/detail/
create, comments, attachments, MinIO PUT/finalize, FTS, available transitions,
transition, close, and reopen.

## Database Evidence

- Expected Sprint 2/3 tables and upgraded SLA columns are present.
- Permission catalogue contains the approved 18 exact codes.
- ACME RT Admin has all 18 permissions; canonical role counts are 18/9/5/4/2.
- Duplicate seed groups and tested relational tenant mismatches are zero.
- Major list/report/audit indexes and FTS AUTO tracking are present.
- Only one tenant exists, so live cross-tenant API evidence remains incomplete.

Disposable BETA verification returned tenant-scoped 404 for an ACME request to
the BETA workflow. Post-run duplicate and tenant-mismatch checks remained zero.

MailHog contained request-created, request-assigned, custom comment-added, and
request-closed notifications. Recipient headers were unique, and baseline
messages contained required request identifiers and links.

## Confirmed Defect Fixed

`MembershipRole` and `RolePermission` use composite primary keys. Django's
instance `delete()` generated tuple-`IN` SQL unsupported by SQL Server, causing
permission removal to return 500. Both removals now use a filtered `_raw_delete`
inside their existing transactions. Focused tests and the mutation collection
prove both paths return 204 while final-admin protection still returns 409.

## Remaining Limitations

- `rt_sqlserver` MCP still times out at `host.docker.internal:1433`; approved
  SELECT-only sqlcmd produced the release evidence.
- The normal local database has only ACME; cross-tenant verification requires
  the disposable fixture process documented here.
- SLA compliance metrics remain deferred because timer/response/resolution data
  does not exist.
- Spanish/neutral FTS tuning and SMTP failure simulation remain automated-test
  coverage rather than final-demo actions.

## Recommended Commit

`fix(admin): harden composite removals and add release verification`

No secrets or local credentials are committed. `.env` remains ignored; the
tracked Postman environment has empty username, password, TOKEN, and refresh
token values. Disposable credentials and presigned URLs existed only in process
memory or ignored `.agent/tmp` reports.
