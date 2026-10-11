# M7B Request workspace API contract

## Purpose

Support a Request workspace with independent core, bounded timeline and workflow
reads, authenticated domain actors, reliable grouped uploads and clean-only
downloads. Web M7C is separate. Keep legacy routes and public fields.

## Repository orientation and current behavior

`apps/rt/views.py` owns RequestViewSet, comments, upload init/finalize and
transition helpers. `apps/rt/serializers.py` defines core and legacy contracts.
Domain models in `apps/rt/models.py` are unmanaged SQL Server tables. Existing
membership permission resolution is in `apps/rt/services/admin_permissions.py`.
Current writes use requester as comment/transition/upload actor; assignment
has no audit; finalize trusts object keys and is not idempotent. Legacy detail
bundle and activity are unpaginated. No scan-gated download action exists.
Read-only Web evidence: `../rt-web-skeleton/docs/plans/sprint-4/m7-request-detail-contract.md`
and `../rt-web-skeleton/docs/design/08-request-detail.md`.

## Scope and desired contracts

Add only M7B API contracts, services, tests and docs. Preserve Search, Dashboard,
Create, Admin and Web. Add `/api/requests/{id}/timeline/` and nested attachment
download; retain core and legacy bundle/comments/attachments/activity/actions.
Core gains capabilities matching enforced permissions. Timeline uses standard
count/next/previous/results, page default 1, page_size default 25/max 100, and
created_at DESC/event_id ASC. Out-of-range pages retain total and empty results.

## Permission and compatibility decision

Reuse membership context (no admin.read prerequisite) for requests.read,
requests.write, requests.transition, comments.write and attachments.write.
Read is prerequisite for workspace operations. Derive can_comment/can_upload/
can_assign/can_transition/can_download_attachments from the same policy. No
missing-role fallback. On 2026-10-10 SELECT-only inspection confirmed all five
codes, canonical role maps and 8/8 memberships with roles. Existing Sprint 3
seed upgrade already adds missing canonical maps without replacing custom maps;
no new SQL upgrade is justified. Deployments must verify those seeds before
enforcement; membership provisioning remains an explicit administrator action.

GuardRolesJson, GuardPermsJson and AutoRules have no documented runtime AND/OR
semantics; current local guards are empty. Do not interpret them speculatively.
GET and POST transitions enforce the same global requests.transition policy,
current flow/status and tenant targets. Comments remain optional. Direct status
update is rejected; actions use transition authority.

Closeout text policy (2026-10-10): repository code stores both finalize messages
and transition notes as ordinary public Comment rows, not intrinsic operation
metadata. No contrary product policy was found. Apply least privilege:
requests.read + attachments.write permits init and file-only finalize; a
non-empty message additionally requires comments.write. The comment_markdown
alias follows the same rule. Finalize still creates one empty structural Comment
for grouped files, attributed to the authenticated actor, and one
attachments.finalized Activity with that actor. This is not permission to post
text. requests.read + requests.transition permits note-free transition, close
and reopen; non-empty optional comment additionally requires comments.write.
Absent, empty and whitespace-only text normalize to empty through the existing
serializers. Denial happens before storage copying or domain writes. Retry
authorization checks current grants, including text permission, before returning
the committed result. Plain comments still require comments.write.

Capabilities use exactly the same effective grants and requests.read
prerequisite as the corresponding operations. can_upload/can_transition describe
the base operation only; optional text additionally needs can_comment. can_assign
requires requests.write; can_download_attachments requires requests.read plus
per-file clean state/ownership/existence. Capabilities are not a substitute for
server checks or a promise that a particular transition is available.

Local SELECT-only role evidence from the implementation preflight, without
personal identities (no grants changed):

| Canonical role | Read/download eligibility | Comment | Upload | Assign | Transition |
| --- | --- | --- | --- | --- | --- |
| RT Admin | yes | yes | yes | yes | yes |
| RT Manager | yes | yes | yes | yes | yes |
| RT Agent | yes | yes | yes | yes | yes |
| RT Requester | yes | yes | yes | yes | no |
| RT Viewer | yes | no | no | no | no |

All five permission codes exist and 8/8 sampled local memberships have roles.
All canonical upload/transition roles already have comments.write. Custom roles
may omit it; tests explicitly cover that case. No seed migration is needed.

## Implementation plan

1. Extend serializers/OpenAPI with capability, timeline, canonical aliases,
   transition summaries and safe download contracts before route behavior.
2. Add `apps/rt/services/request_workspace.py` for reused permission context
   and capability policy; enforce scoped core/legacy reads and workspace writes.
   Correct authors and assignment Activity without rewriting historical rows.
3. Add `apps/rt/services/request_timeline.py`: SQL Server union/count/page IDs,
   then batched event/comment/attachment/status hydration. Suppress Comments
   referenced by meaningful Activity comment_id; grouped finalize is one event,
   transitions carry their comment once. Never dedupe by timestamps. Unknown
   events retain type/time with neutral text, never raw payload dumps.
4. Add `apps/rt/services/request_uploads.py`: durable storage manifest issued at
   init; exact keys/group/request metadata; HEAD validation before metadata;
   group identity and transaction-owned SQL Server applock for serialized
   finalize. Equivalent retry returns original result; incompatible retry 409.
   Preserve presigned PUT and idempotency_key input. Download requires read,
   tenant/request ownership and scan clean, returning a 300-second GET URL.
5. Extend focused tests; run existing regressions and full available API gate.
   Verify real SQL Server/MinIO only with disposable data, never original rt.

## Upload and operational rules

Init manifest is private server metadata in the configured bucket, with a
tenant/request/group key and 1-hour expiry. Finalize rechecks current permission;
requires every issued file and verifies object existence, size and content type.
The manifest and response expose expires_at. Verified staging bytes are copied
server-side with CopySourceIfMatch into an unissued namespace:
`attachments/{tenant_id}/{request_id}/{group_id}/{nonce}-{filename}`. An issued
PUT URL cannot overwrite a published attachment. All verification/copying
precedes database metadata; partial storage failure creates no DB rows.
Group is the authoritative durable retry identity; idempotency_key stays accepted.
Partial PUT failure finalizes nothing; retry failed PUTs before expiry, otherwise
new init. No orphan cleanup or scanner is introduced. Legacy storage URLs remain
for compatibility, but workspace uses canonical file summaries and download.
Private bucket policy remains an infrastructure requirement.
Declared checksums remain metadata, not a cryptographic verification claim.
Staging objects, manifests and failed-transaction copies may remain; no cleanup
worker is implemented. Do not blindly expire the legacy uploads prefix because
historical published attachments can still reference it. Existing pre-M7B
in-flight sessions without manifests require new init; committed legacy groups
without retry fingerprints return 409 rather than creating duplicates.
MINIO_PUBLIC_URL, when configured, is used to sign client URLs; internal storage
operations still use MINIO_ENDPOINT. Legacy URI origins must match one of those
configured origins. Both are accepted when extracting an existing object key.

## Tests and verification

`tests/test_request_workspace.py` will cover permissions, actors, assignment,
timeline semantics/pagination, storage integrity/retries/download and schema.
Update affected legacy tests to supply intended authenticated actors explicitly.

```powershell
poetry run pytest tests/test_request_workspace.py tests/test_comments.py tests/test_uploads.py tests/test_transitions.py tests/test_notifications.py -q
poetry run python manage.py check
poetry run pytest -q
poetry run ruff check .
poetry run black . --check
poetry run isort . --check --diff
poetry run python manage.py spectacular --validate --file "$env:TEMP/rt-m7b-openapi.yaml"
git diff --check
```

Use the existing Poetry/Python environment with approved execution escalation.
Separate mocks from SQL Server/MinIO, connection/auth from service query counts,
and simulated clean fixture state from actual scanner evidence. Coverage/type
runners and hosted/deployed evidence remain explicit limitations.

## Acceptance criteria

Server permission/capability parity, tenant isolation, correct actors, one
assignment audit per change, generic transition parity, bounded stable timeline,
one operation event, HEAD-before-metadata integrity, concurrency-safe equivalent
retry, clean-only scoped download, legacy shapes/routes, OpenAPI and full
available checks pass. No Web work or production data changes.

## Progress

- [x] Read instructions, current contracts, Web M7A and role/guard evidence.
- [x] Extend schema and implement workspace authority/actor fixes.
- [x] Implement bounded timeline and grouping.
- [x] Implement manifest integrity, serialized finalize and download.
- [x] Run focused/full gate and disposable live verification.
- [x] Record results, operational limits and exact M7C handoff.
- [x] Review text permission crossover and add positive/negative API tests.
- [x] Classify verifier as permanent and harden local/owned-resource safety.
- [x] Record final closeout gate and permanent live-verifier results.

## Surprises & Discoveries

- All local memberships already have seeded roles; activation need not assign
  users any new permission. Missing roles must deny, not silently allow.
- Read-only compatibility evidence: five required permission codes exist,
  canonical RT Admin/Manager/Agent/Requester/Viewer maps match the prior seed,
  all 8 memberships have roles, and the single active Django login sampled
  maps to an active RT member with requests.read. No production grants changed.
- SQL Server's backend rewrites parameterized GROUP BY statements using Python
  formatting; a literal empty-JSON brace string caused IndexError. The timeline
  uses NCHAR(123)+NCHAR(125) instead, with permanent regression coverage.
- Generic transition close/reopen history needs semantic normalization; new
  transition Activity includes status snapshots so later label/category edits
  do not rewrite those events. Historical IDs use current tenant-safe lookups.
- Issued PUT URLs remain valid after finalize. Server-only conditional copies
  are necessary to prevent them replacing bytes after a clean decision.
- Upload and transition text both create ordinary Comment records; base operation
  permissions alone previously bypassed a custom role's comments.write denial.
  The closeout adds one shared optional-text guard to all four entry points.
- The first closeout live run rejected a verifier fixture using permissionid;
  the actual composite RolePermission model uses permissioncode. Corrected only
  the disposable fixture. Its failure path removed the clone/bucket/backup.

## Decision Log

- Reuse existing effective-permission resolution for ordinary operations,
  independently of admin.read. Derive capabilities from those exact checks.
- Preserve stored guard JSON without guessed runtime semantics.
- Use storage manifests plus transaction applocks and Activity fingerprints;
  no unmanaged-table schema migration is expected.
- Reuse the effective-permission resolver with a tenant-filtered role join and
  a cached RT actor, not a second RBAC implementation. Workspace rejects inactive
  actors. Assignment validates supplied targets (active for a changed assignee)
  without rejecting unchanged historical requester/assignee associations.
- Users catalogue requires requests.read and supports optional is_active;
  omit the filter to preserve the full historical catalogue. Assignment loads
  is_active=true lazily. No account/password provisioning is added to API.
- New comments are public-only. Historical visibility flags remain factual
  metadata with no private/internal policy claim. Historical authors are not
  changed; creation endpoint attribution is outside this milestone.
- Timeline dedupe uses valid same-request comment IDs and prioritizes finalized
  uploads, then transitions, then comment.added when legacy duplicate Activity
  refers to one comment. Unrelated same-time events remain distinct. Standalone
  comments (including file-linked comments) and orphan file groups are included.
- Unknown or malformed assignment history uses neutral system events with
  machine activity_type/time/actor, never raw JSON or fabricated assignees.
- Retain scripts/verify_m7b_workspace.py as a permanent opt-in integration
  verifier, not a one-off harness. It exercises real SQL Server timeline queries,
  transaction locking, retry concurrency and signed MinIO IO which mocks cannot
  prove. No additional dependency or normal CI service requirement is introduced.
- Both upload notes and transition/close/reopen notes require comments.write
  when non-empty after existing serializer normalization. No requires_comment
  rule is added. can_upload and can_transition remain independent of can_comment.

## Outcomes & Retrospective

M7B passes local available verification on feat/request-workspace-contract
(2026-10-10). No database schema or permission seed migration was required.

Implementation gate: 83 focused tests passed, 310 full tests passed; Django check
reported 0 issues, Ruff/Black/isort passed, generated OpenAPI validated without
warnings, and git diff --check passed. Existing request-create, Dashboard,
Search and Admin regression suites remain green. Missing coverage/type runners
are still unverified requirements, not passed or waived. Hosted CI and deployed
API/browser verification have not run.

Final closeout gate (2026-10-10): 116 focused tests passed and 343 full tests
passed (86 workspace tests, including 33 new crossover/verifier guard cases).
Django check: 0 issues; Ruff: passed; Black: 58 files unchanged; isort: passed
with one configured skip; generated OpenAPI: validated without warnings;
git diff --check: passed. Collection confirmed the exact counts. New tests use
mocked ORM/storage, with real DRF dispatch for permission boundaries; the retained
integration verifier separately passed real SQL Server and MinIO. The failed
fixture run was corrected and rerun, not counted as passing evidence.

The final permanent live run verified a cloned custom role with read/upload/
transition but no comments.write: init, file-only finalize and identical retry
succeed; optional upload text (including the legacy alias), plain comments, and
transition/close/reopen text return 403. Note-free actions succeed without creating
text Comments; the file container's empty Comment and Activity use the caller.
Existing full-grant text paths also pass. Timeline count remains 40, query counts
remain 4/4/4/6 for 1/10/25/40 rows and 1 for empty, and concurrent first finalize
returns [200,201] with identical result. Owned clone/bucket/backup cleanup passed.
No schema, seed, Web or unrelated product change was made during closeout.
Local available M7B closeout is PASS; merge readiness remains unverified/blocked
by hosted CI, missing configured coverage/type gates and required sensitive-area
reviews. The original implementation's deployment/scanner limitations remain.

`poetry run python scripts/verify_m7b_workspace.py --disposable` is the repeatable
opt-in integration command. It requires the local SQL Server COPY_ONLY/restore
permissions, rt_sqlserver Docker container and MinIO credentials. It checks
generated resource names do not already exist, creates an owned rt_m7b_* clone
and rt-m7b-* bucket, and cleans the clone/bucket/backup in finally. It never
targets original rt for row mutations and does not print credentials. Email
uses locmem. Only a controlled cloned record changes scan state to exercise the
gate, following the existing disposable-test convention; this is not scanner
evidence.

Permanent verifier prerequisites/safety: use an already configured local Poetry
environment, a running rt_sqlserver Docker container, ODBC Driver 18, the seeded
rt database including Django auth tables/canonical roles, and a local private
MinIO service. Credentials are consumed from existing configuration, never
printed or checked in. The verifier rejects non-loopback SQL/MinIO/public URLs
before database or storage operations. Only --disposable is the operator command;
the internal child requires the exact parent-owned database/bucket marker and
matching generated names. No arbitrary existing target is accepted. This is an
explicitly mutation-capable integration check, not read-only SQL inspection.
Original rt is only backed up COPY_ONLY; rows are mutated only in the clone.
Random resource names avoid collisions; assertions and fixture sizes are fixed
and do not depend on personal account data. finally removes generated resources
on success/failure; process termination or cleanup failure can still require an
operator to remove the reported owned resources. It must not be run on production,
even if production is forwarded through a loopback endpoint.

Live SQL Server + MinIO evidence:

- Alice requester / Bob caller: plain and grouped upload Comment.author and
  related Activity.actor are Bob. Changed/unassigned assignments produce one
  audit each; identical assignment does not duplicate. Viewer writes/actions
  deny while read/core capabilities are accurate; ordinary RT Agent works
  without admin.read. Cross-tenant requests/timeline and wrong-parent downloads
  return 404; nonmember assignee returns 400; status PATCH is rejected.
- Real init, signed PUTs, missing-PUT rejection, grouped finalize 201, equivalent
  retry 200 with identical IDs, incompatible retry 409, and concurrent first
  finalize [200,201] passed with one Comment/Attachment/Activity per group.
- Pending/blocked downloads deny; controlled clean presigned GET returns the
  expected bytes. Overwriting the issued staging object does not change the
  published attachment. The bucket and all staged/published objects were removed.
- A 40-event history includes created/comment/assignment/transitions/closed/
  reopened/grouped files/unknown fallback. Thirty equal-time standalone comments
  paginate with no skipped or repeated IDs, and linked comments appear once.
  Out-of-range page retains total 40. All legacy reads still work.

| Actual timeline rows | Service DB queries |
| --- | --- |
| 0 | 1 |
| 1 | 4 |
| 10 | 4 |
| 25 | 4 |
| 40 mixed | 6 |

These are real SQL Server measurements excluding connection, authentication
and parent lookup. Actor joins, file hydration and status batches are bounded,
not per-event queries. Numbered pagination has stable ties, but does not promise
a multi-request snapshot under concurrent inserts/deletes; reset continuation
after mutations and use event_id as the client identity.

Cleanup confirmation: zero rt_m7b_* databases and rt-m7b-* buckets remain.
Original rt still has 11 Requests / 8 Comments / 3 Attachments. No original rows
or normal storage objects were mutation targets.

Operational limits: scanner and garbage collection are absent; new uploads stay
pending until a trusted scanner/process changes state. Group file-count/total
size quotas are not introduced. Bucket must remain private because legacy URI
fields are retained; they are not authorized downloads. Previously minted GET
URLs last up to five minutes and are not revocable by this API. Guard-role,
guard-permission and auto-rule semantics remain undefined and unimplemented.
Request list/search/create authority is not generally retrofitted by M7B.
Publish the large change in dependency-ordered reviews (authority/actors,
timeline, upload/download) as required by AGENTS before merge.

Exact M7C handoff:

1. Initial GET `/api/requests/{id}/` and GET `/api/requests/{id}/timeline/`
   (page=1,page_size=25). Read available-transitions only when can_transition.
   Do not call detail bundle or eagerly fetch users/comments/files/activity.
2. Core keeps all old fields and adds capabilities.can_comment/can_upload/
   can_assign/can_transition/can_download_attachments. These are operation
   permission eligibility; clean state is an additional per-file download gate.
3. Timeline envelope is count/next/previous/results. Event fields: event_id,
   kind, activity_type, created_at, actor, summary, comment, attachments,
   from_status/to_status, old_assignee/new_assignee. Kinds are request_created,
   comment, attachments, assignment, transition, request_closed,
   request_reopened, system. Null actor is not a fake User. Comment has
   comment_id/body/visibility/created_at/author; files have attachment_id,
   filename/content_type/size_bytes/scan_status/created_at/comment_id/group_id.
4. Transition array retains transition_id/from_status_id/to_status_id/to_status
   and adds from_status/is_terminal/label (target name). No requires_comment
   exists; comment is optional. Never PATCH a different status_id.
5. Upload init returns group/uploads/expires_at; N PUTs use only supplied
   storage headers; finalize with that same group. Refresh first timeline page
   after success. Retry equivalent finalize on response loss; retry missing PUTs
   before expiry, otherwise new init. Do not treat idempotency_key as authority.
6. Use GET `/api/requests/{id}/attachments/{attachment_id}/download/` only on
   interaction. It returns url/expires_at, valid 300 seconds, only for clean.
   Never map storageurl/storage_url from legacy data to an href.
7. Assignment opens lazy GET `/api/users/?is_active=true&search=...&page=...`;
   follow normal pagination (default 25/max 100) and retain selected labels.
   PATCH assignee_id UUID/null, then refresh core and first timeline page.
8. Plain comment POST {body} refreshes first timeline page only. Transition
   POST {transition_id,comment?} refreshes core, timeline and available actions.
   Each region can fail/retry independently. No mutation repeats all six GETs.
9. Composer separates text permission from files: if can_upload=true and
   can_comment=false, allow file-only init/PUT/finalize with message omitted or
   empty, and hide/disable the text field. Never submit comment_markdown text as
   a bypass. Render its empty grouped Comment as one attachments event, not a
   second blank text bubble. If can_transition=true and can_comment=false,
   allow the action while hiding/disabling optional note input; omit comment or
   send empty. If can_comment=true, optional upload/action text is available
   only alongside the respective base capability. No required-note UI exists.
   Handle server 403 after permission changes; refresh core capabilities rather
   than retrying a denied mutation. Do not implement M7C in this API branch.
