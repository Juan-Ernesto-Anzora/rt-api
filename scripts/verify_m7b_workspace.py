"""Opt-in verification: copy-only SQL clone + owned MinIO bucket, always cleaned up."""

import argparse
import json
import logging
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def require_local_services(settings):
    loopback = {"localhost", "127.0.0.1", "::1"}
    host = settings.DATABASES["default"]["HOST"].split(",", 1)[0].lower()
    endpoints = [settings.MINIO_ENDPOINT, settings.MINIO_PUBLIC_URL]
    if host not in loopback or any(
        urlsplit(endpoint).hostname not in loopback
        for endpoint in endpoints
        if endpoint
    ):
        raise RuntimeError("Disposable verification requires local loopback services.")


def configure(database=None, bucket=None):
    if database:
        if (
            not re.fullmatch(r"rt_m7b_[0-9a-f]{12}", database)
            or bucket != database.replace("_", "-")
            or os.environ.get("RT_M7B_OWNED_TARGET") != f"{database}/{bucket}"
        ):
            raise RuntimeError("Refusing an unowned database name.")
        os.environ["DB_NAME"] = database
    if bucket:
        os.environ["MINIO_BUCKET"] = bucket
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "rt_api.settings")
    import django

    django.setup()
    from django.conf import settings

    require_local_services(settings)
    logging.getLogger("django.db.backends").setLevel(logging.WARNING)


def exercise(database, bucket):
    configure(database, bucket)
    from concurrent.futures import ThreadPoolExecutor
    from urllib.request import Request as HTTPRequest, urlopen

    from django.conf import settings
    from django.contrib.auth import get_user_model
    from django.db import connection, connections
    from django.test.utils import CaptureQueriesContext
    from django.utils import timezone
    from rest_framework.test import APIClient
    from rest_framework_simplejwt.tokens import AccessToken

    from apps.rt.models import (
        Activity,
        Attachment,
        Comment,
        Flow,
        Membership,
        Membershiprole,
        Permission,
        Request,
        Role,
        Rolepermission,
        Status,
        Tenant,
        Transition,
        User,
    )
    from apps.rt.services.request_timeline import timeline_page
    from apps.rt.services.request_uploads import storage_client

    assert settings.DATABASES["default"]["NAME"] == database and database != "rt"
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    s3 = storage_client()
    s3.create_bucket(Bucket=bucket)
    now = timezone.now()
    tenant = Tenant.objects.get(code="ACME")

    def user(name, role):
        person = User.objects.create(
            userid=uuid.uuid4(),
            displayname=name,
            email=f"m7b-{name}-{uuid.uuid4().hex}@example.invalid",
            isactive=True,
            createdat=now,
        )
        membership = Membership.objects.create(
            membershipid=uuid.uuid4(),
            tenantid=tenant,
            userid=person,
            isdefaulttenant=True,
            createdat=now,
        )
        Membershiprole.objects.create(
            membershipid=membership, roleid=Role.objects.get(tenantid=tenant, name=role)
        )
        auth = get_user_model().objects.create_user(
            username=person.email, email=person.email, password=uuid.uuid4().hex
        )
        token = str(AccessToken.for_user(auth))
        return person, token

    alice, _ = user("Alice", "RT Requester")
    bob, token = user("Bob", "RT Agent")
    _, viewer_token = user("Viewer", "RT Viewer")
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}", HTTP_X_TENANT="ACME")
    viewer = APIClient()
    viewer.credentials(
        HTTP_AUTHORIZATION=f"Bearer {viewer_token}", HTTP_X_TENANT="ACME"
    )
    flow = Flow.objects.create(
        flowid=uuid.uuid4(), tenantid=tenant, name="M7B Live", createdat=now
    )

    def status(name, category, terminal=False):
        return Status.objects.create(
            statusid=uuid.uuid4(),
            tenantid=tenant,
            flowid=flow,
            name=name,
            category=category,
            isterminal=terminal,
            createdat=now,
        )

    opened, progress, closed = (
        status("Open", "open"),
        status("Progress", "in_progress"),
        status("Closed", "closed", True),
    )
    transitions = [
        Transition.objects.create(
            transitionid=uuid.uuid4(),
            flowid=flow,
            fromstatusid=source,
            tostatusid=target,
            createdat=now,
        )
        for source, target in ((opened, progress), (progress, closed), (closed, opened))
    ]

    def request(status_obj=opened, parent_tenant=tenant, parent_flow=flow):
        return Request.objects.create(
            requestid=uuid.uuid4(),
            tenantid=parent_tenant,
            humanid="M7B-" + uuid.uuid4().hex[:12],
            title="M7B live workspace",
            priority="normal",
            flowid=parent_flow,
            statusid=status_obj,
            requesterid=alice,
            createdat=now,
            updatedat=now,
        )

    restricted_role = Role.objects.create(
        roleid=uuid.uuid4(),
        tenantid=tenant,
        name="M7B File and Action Only",
        createdat=now,
    )
    for code in ("requests.read", "attachments.write", "requests.transition"):
        Rolepermission.objects.create(
            roleid=restricted_role, permissioncode=Permission.objects.get(code=code)
        )
    restricted_actor, restricted_token = user("Restricted", restricted_role.name)
    restricted = APIClient()
    restricted.credentials(
        HTTP_AUTHORIZATION=f"Bearer {restricted_token}", HTTP_X_TENANT="ACME"
    )
    isolated = request()
    isolated_base = f"/api/requests/{isolated.requestid}/"
    flags = restricted.get(isolated_base).data["capabilities"]
    assert flags["can_upload"] and flags["can_transition"] and not flags["can_comment"]
    assert (
        restricted.post(
            isolated_base + "comments/", {"body": "Denied"}, format="json"
        ).status_code
        == 403
    )
    for action, data in (
        ("transition", {"transition_id": str(transitions[0].transitionid)}),
        ("close", {}),
        ("reopen", {}),
    ):
        assert (
            restricted.post(
                isolated_base + action + "/",
                {**data, "comment": "Denied"},
                format="json",
            ).status_code
            == 403
        )
        assert (
            restricted.post(
                isolated_base + action + "/", data, format="json"
            ).status_code
            == 200
        )
    assert not Comment.objects.filter(requestid=isolated).exists()
    issued = restricted.post(
        "/api/attachments/init",
        {
            "request_id": str(isolated.requestid),
            "files": [
                {
                    "filename": "file-only.txt",
                    "content_type": "text/plain",
                    "size_bytes": 3,
                }
            ],
        },
        format="json",
    )
    assert issued.status_code == 200, issued.data
    upload = issued.data["uploads"][0]
    with urlopen(
        HTTPRequest(upload["url"], data=b"abc", headers=upload["headers"], method="PUT")
    ) as response:
        assert response.status == 200
    file_only = {
        "request_id": str(isolated.requestid),
        "group_id": issued.data["group_id"],
        "files": [
            {
                key: upload[key]
                for key in ("object_key", "filename", "content_type", "size_bytes")
            }
        ],
    }
    assert (
        restricted.post(
            "/api/attachments/finalize",
            {**file_only, "comment_markdown": "Denied"},
            format="json",
        ).status_code
        == 403
    )
    assert not Comment.objects.filter(requestid=isolated).exists()
    committed = restricted.post("/api/attachments/finalize", file_only, format="json")
    assert committed.status_code == 201, committed.data
    structural = Comment.objects.get(commentid=committed.data["comment_id"])
    assert (
        structural.messagemd == "" and structural.authorid_id == restricted_actor.userid
    )
    assert (
        Activity.objects.get(
            requestid=isolated, type="attachments.finalized"
        ).actorid_id
        == restricted_actor.userid
    )
    assert (
        restricted.post(
            "/api/attachments/finalize", file_only, format="json"
        ).status_code
        == 200
    )

    item = request()
    base = f"/api/requests/{item.requestid}/"
    Activity.objects.create(
        activityid=uuid.uuid4(),
        tenantid=tenant,
        requestid=item,
        actorid=alice,
        type="request.created",
        payload="{}",
        createdat=now,
    )
    assert client.get(base).status_code == 200
    assert all(client.get(base).data["capabilities"].values())
    directory = client.get("/api/users/?is_active=true&search=Bob")
    assert directory.status_code == 200 and str(bob.userid) in {
        row["user_id"] for row in directory.data["results"]
    }
    assert viewer.get(base).data["capabilities"]["can_comment"] is False
    assert (
        viewer.post(base + "comments/", {"body": "Denied"}, format="json").status_code
        == 403
    )
    assert (
        viewer.patch(base, {"assignee_id": str(bob.userid)}, format="json").status_code
        == 403
    )
    assert viewer.get(base + "available-transitions/").status_code == 403
    assert (
        viewer.post(
            "/api/attachments/init",
            {"request_id": str(item.requestid), "files": []},
            format="json",
        ).status_code
        == 403
    )
    response = client.post(base + "comments/", {"body": "Bob update"}, format="json")
    assert response.status_code == 201, response.data
    comment = Comment.objects.get(commentid=response.data["comment_id"])
    assert comment.authorid_id == bob.userid != alice.userid
    audit = Activity.objects.get(tenantid=tenant, requestid=item, type="comment.added")
    assert audit.actorid_id == bob.userid
    assert (
        client.patch(
            base, {"assignee_id": str(alice.userid)}, format="json"
        ).status_code
        == 200
    )
    assert (
        client.patch(
            base, {"assignee_id": str(alice.userid)}, format="json"
        ).status_code
        == 200
    )
    assert Activity.objects.filter(requestid=item, type="request.assigned").count() == 1
    assert client.patch(base, {"assignee_id": None}, format="json").status_code == 200
    assert Activity.objects.filter(requestid=item, type="request.assigned").count() == 2
    assert (
        client.patch(
            base, {"status_id": str(closed.statusid)}, format="json"
        ).status_code
        == 400
    )
    choices = client.get(base + "available-transitions/")
    assert choices.status_code == 200 and choices.data[0]["from_status"][
        "status_id"
    ] == str(opened.statusid)
    for transition in transitions:
        response = client.post(
            base + "transition/",
            {
                "transition_id": str(transition.transitionid),
                "comment": "Workflow update",
            },
            format="json",
        )
        assert response.status_code == 200, response.data
    assert (
        client.post(
            base + "transition/",
            {"transition_id": str(transitions[1].transitionid)},
            format="json",
        ).status_code
        == 400
    )

    def start_upload(names):
        files = [
            {"filename": name, "content_type": "text/plain", "size_bytes": 3}
            for name in names
        ]
        response = client.post(
            "/api/attachments/init",
            {"request_id": str(item.requestid), "files": files},
            format="json",
        )
        assert response.status_code == 200, response.data
        payload = {
            "request_id": str(item.requestid),
            "group_id": response.data["group_id"],
            "comment_markdown": "Grouped files",
            "files": [
                {
                    key: row[key]
                    for key in ("object_key", "filename", "content_type", "size_bytes")
                }
                for row in response.data["uploads"]
            ],
        }
        return response.data, payload

    def put(row):
        with urlopen(
            HTTPRequest(row["url"], data=b"abc", headers=row["headers"], method="PUT")
        ) as response:
            assert response.status == 200

    initialized, payload = start_upload(["one.txt", "two.txt"])
    put(initialized["uploads"][0])
    response = client.post("/api/attachments/finalize", payload, format="json")
    assert (
        response.status_code == 400
        and not Comment.objects.filter(groupid=payload["group_id"]).exists()
    )
    put(initialized["uploads"][1])
    first = client.post("/api/attachments/finalize", payload, format="json")
    assert first.status_code == 201, first.data
    retry = client.post(
        "/api/attachments/finalize",
        {**payload, "idempotency_key": "retry"},
        format="json",
    )
    assert retry.status_code == 200 and retry.data == first.data
    incompatible = client.post(
        "/api/attachments/finalize",
        {**payload, "comment_markdown": "Changed"},
        format="json",
    )
    assert incompatible.status_code == 409
    group_comment = Comment.objects.get(commentid=first.data["comment_id"])
    assert group_comment.authorid_id == bob.userid
    group_activity = Activity.objects.get(type="attachments.finalized", requestid=item)
    assert group_activity.actorid_id == bob.userid
    attachment = Attachment.objects.get(
        attachmentid=first.data["attachments"][0]["attachment_id"]
    )
    download = base + f"attachments/{attachment.attachmentid}/download/"
    assert client.get(download).status_code == 409
    # Controlled disposable scan state tests the gate, not a scanner.
    attachment.scanstatus = "blocked"
    attachment.save(update_fields=["scanstatus"])
    assert client.get(download).status_code == 409
    attachment.scanstatus = "clean"
    attachment.save(update_fields=["scanstatus"])
    response = client.get(download)
    assert response.status_code == 200 and response.data["expires_at"]
    with urlopen(response.data["url"]) as storage_response:
        assert storage_response.read() == b"abc"
    s3.put_object(
        Bucket=bucket,
        Key=payload["files"][0]["object_key"],
        Body=b"changed",
        ContentType="text/plain",
    )
    immutable = client.get(download)
    with urlopen(immutable.data["url"]) as storage_response:
        assert storage_response.read() == b"abc"
    another = request()
    assert (
        client.get(
            f"/api/requests/{another.requestid}/attachments/{attachment.attachmentid}/download/"
        ).status_code
        == 404
    )
    foreign_tenant = Tenant.objects.create(
        tenantid=uuid.uuid4(),
        code="M7BFOREIGN",
        name="Disposable",
        isactive=True,
        createdat=now,
    )
    foreign_flow = Flow.objects.create(
        flowid=uuid.uuid4(), tenantid=foreign_tenant, name="Foreign", createdat=now
    )
    foreign_status = Status.objects.create(
        statusid=uuid.uuid4(),
        tenantid=foreign_tenant,
        flowid=foreign_flow,
        name="Open",
        category="open",
        isterminal=False,
        createdat=now,
    )
    foreign_request = request(foreign_status, foreign_tenant, foreign_flow)
    assert client.get(f"/api/requests/{foreign_request.requestid}/").status_code == 404
    assert (
        client.get(f"/api/requests/{foreign_request.requestid}/timeline/").status_code
        == 404
    )
    assert (
        client.patch(
            base,
            {
                "assignee_id": str(
                    User.objects.create(
                        userid=uuid.uuid4(),
                        displayname="Foreign",
                        email=f"{uuid.uuid4().hex}@example.invalid",
                        isactive=True,
                        createdat=now,
                    ).userid
                )
            },
            format="json",
        ).status_code
        == 400
    )

    initialized2, payload2 = start_upload(["concurrent.txt"])
    put(initialized2["uploads"][0])

    def finalize_in_thread(_):
        thread_client = APIClient()
        thread_client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {token}", HTTP_X_TENANT="ACME"
        )
        try:
            response = thread_client.post(
                "/api/attachments/finalize", payload2, format="json"
            )
            return response.status_code, response.data
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        concurrent = list(pool.map(finalize_in_thread, (1, 2)))
    assert sorted(code for code, _ in concurrent) == [200, 201], concurrent
    assert concurrent[0][1] == concurrent[1][1]
    assert Comment.objects.filter(groupid=payload2["group_id"]).count() == 1
    assert Attachment.objects.filter(groupid=payload2["group_id"]).count() == 1
    assert (
        Activity.objects.filter(requestid=item, type="attachments.finalized").count()
        == 2
    )
    first_page = client.get(base + "timeline/?page_size=100")
    assert first_page.status_code == 200, first_page.data
    events = first_page.data["results"]
    comment_ids = [
        event["comment"]["comment_id"] for event in events if event["comment"]
    ]
    assert len(comment_ids) == len(set(comment_ids))
    assert all(
        event["comment"]["author"]["user_id"] == str(bob.userid)
        for event in events
        if event["comment"]
    )
    assert any(event["kind"] == "request_closed" for event in events)
    assert any(event["kind"] == "request_reopened" for event in events)
    assert any(len(event["attachments"]) == 2 for event in events)
    assert all("storageurl" not in str(event) for event in events)
    tied_time = timezone.now()
    Comment.objects.bulk_create(
        [
            Comment(
                commentid=uuid.uuid4(),
                tenantid=tenant,
                requestid=item,
                authorid=bob,
                messagemd=f"Tie {index}",
                visibility="public",
                createdat=tied_time,
            )
            for index in range(30)
        ]
    )
    Activity.objects.create(
        activityid=uuid.uuid4(),
        tenantid=tenant,
        requestid=item,
        actorid=None,
        type="legacy.unknown",
        payload="{broken}",
        createdat=now,
    )
    complete = client.get(base + "timeline/?page_size=100").data
    collected = []
    for page in range(1, (complete["count"] + 9) // 10 + 1):
        response = client.get(base + f"timeline/?page={page}&page_size=10")
        assert response.status_code == 200
        collected.extend(event["event_id"] for event in response.data["results"])
    assert collected == [event["event_id"] for event in complete["results"]]
    assert len(collected) == len(set(collected)) == complete["count"]
    out = client.get(base + "timeline/?page=9999&page_size=10")
    assert out.data["count"] == complete["count"] and out.data["results"] == []
    assert client.get(base + "detail/").status_code == 200
    for suffix in ("comments/", "attachments/", "activity/", "activities/"):
        assert client.get(base + suffix).status_code == 200
    query_counts = []
    for size in (1, 10, 25, 100):
        with CaptureQueriesContext(connection) as captured:
            _, rows = timeline_page(
                tenant_id=tenant.tenantid, request_id=item.requestid, page_size=size
            )
        query_counts.append({"rows": len(rows), "queries": len(captured)})
        assert len(captured) <= 6
    empty_request = request()
    with CaptureQueriesContext(connection) as captured:
        zero, rows = timeline_page(
            tenant_id=tenant.tenantid, request_id=empty_request.requestid
        )
    assert zero == 0 and rows == [] and len(captured) == 1
    print(
        json.dumps(
            {
                "live": "SQL Server + MinIO",
                "timeline_count": complete["count"],
                "queries": query_counts,
                "empty_queries": len(captured),
                "concurrent_statuses": sorted(code for code, _ in concurrent),
                "authors": "Bob != requester Alice",
                "downloads": "pending/blocked denied; controlled clean GET passed",
                "legacy_reads": "passed",
                "permission_crossovers": "file-only and note-free actions allowed; upload/transition/close/reopen/plain text denied without comments.write",
                "scanner": "not tested or implemented",
            }
        )
    )


def disposable():
    configure()
    from django.conf import settings
    from django.db import connection

    from apps.rt.services.request_uploads import storage_client

    if settings.DATABASES["default"]["NAME"] != "rt":
        raise RuntimeError("Expected original rt connection for COPY_ONLY clone.")
    suffix = uuid.uuid4().hex[:12]
    database, bucket = f"rt_m7b_{suffix}", f"rt-m7b-{suffix}"
    backup = f"/var/opt/mssql/data/{database}.bak"
    with connection.cursor() as cursor:
        cursor.execute("SELECT name FROM sys.databases WHERE name=%s", [database])
        if cursor.fetchone():
            raise RuntimeError("Refusing a pre-existing disposable database name.")
    storage = storage_client()
    try:
        storage.head_bucket(Bucket=bucket)
    except storage.exceptions.ClientError as exc:
        if str(exc.response.get("Error", {}).get("Code")) not in {
            "404",
            "NoSuchBucket",
            "NotFound",
        }:
            raise
    else:
        raise RuntimeError("Refusing a pre-existing bucket name.")
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                f"BACKUP DATABASE [rt] TO DISK=N'{backup}' WITH COPY_ONLY, INIT;"
            )
            while cursor.nextset():
                pass
            cursor.execute(f"RESTORE FILELISTONLY FROM DISK=N'{backup}';")
            files = cursor.fetchall()
            columns = [column[0] for column in cursor.description]
            names = [
                (row[columns.index("LogicalName")], row[columns.index("Type")])
                for row in files
            ]
            while cursor.nextset():
                pass
            moves = ", ".join(
                f"MOVE N'{name.replace(chr(39), chr(39)*2)}' TO N'/var/opt/mssql/data/{database}_{index}.{'ldf' if kind == 'L' else 'mdf'}'"
                for index, (name, kind) in enumerate(names)
            )
            cursor.execute(
                f"RESTORE DATABASE [{database}] FROM DISK=N'{backup}' WITH {moves};"
            )
            while cursor.nextset():
                pass
        result = subprocess.run(
            [sys.executable, __file__, "--exercise", database, "--bucket", bucket],
            capture_output=True,
            text=True,
            env={**os.environ, "RT_M7B_OWNED_TARGET": f"{database}/{bucket}"},
        )
        print(result.stdout)
        if result.returncode:
            print(result.stderr, file=sys.stderr)
            raise RuntimeError("Disposable M7B verification failed.")
    finally:
        connection.close()
        with connection.cursor() as cursor:
            cursor.execute("SELECT name FROM sys.databases WHERE name=%s", [database])
            if cursor.fetchone():
                cursor.execute(
                    f"ALTER DATABASE [{database}] SET SINGLE_USER WITH ROLLBACK IMMEDIATE;"
                )
                cursor.execute(f"DROP DATABASE [{database}];")
        s3 = storage_client()
        try:
            for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket):
                for obj in page.get("Contents", []):
                    s3.delete_object(Bucket=bucket, Key=obj["Key"])
            s3.delete_bucket(Bucket=bucket)
        except s3.exceptions.NoSuchBucket:
            pass
        result = subprocess.run(
            ["docker", "exec", "rt_sqlserver", "rm", "-f", backup],
            capture_output=True,
            text=True,
        )
        if result.returncode:
            raise RuntimeError(f"Disposable backup needs manual cleanup: {backup}")
        print(
            "Owned disposable database, bucket and backup removed; original rt was never a row-mutation target."
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--disposable", action="store_true")
    parser.add_argument("--exercise")
    parser.add_argument("--bucket")
    args = parser.parse_args()
    if args.disposable:
        disposable()
    elif (
        args.exercise and args.bucket and args.bucket == args.exercise.replace("_", "-")
    ):
        exercise(args.exercise, args.bucket)
    else:
        parser.error(
            "Use --disposable; writes are restricted to a generated owned clone."
        )
