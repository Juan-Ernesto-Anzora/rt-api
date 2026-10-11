import hashlib
import io
import json
import uuid
from datetime import timedelta
from types import SimpleNamespace

import pytest
import yaml
from botocore.exceptions import ClientError
from django.test import Client
from django.urls import resolve
from django.utils import timezone
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.rt.models import (
    Activity,
    Attachment,
    Comment,
    Flow,
    Request,
    Status,
    Tenant,
    User,
)
from apps.rt.serializers import (
    AttachmentFinalizeRequestSerializer,
    AttachmentSerializer,
    CommentSerializer,
    RequestDetailSerializer,
    RequestSerializer,
    TimelineQuerySerializer,
)
from apps.rt.services import request_timeline as timeline, request_uploads as uploads
from apps.rt.services.request_workspace import (
    WorkspaceConflict,
    capabilities,
    require_workspace,
)
from apps.rt.views import (
    AttachmentDownloadView,
    AttachmentFinalizeView,
    AttachmentInitView,
    CommentViewSet,
    RequestViewSet,
)

PERMISSIONS = [
    "requests.read",
    "requests.write",
    "requests.transition",
    "comments.write",
    "attachments.write",
]


def fixture_request():
    now = timezone.now()
    tenant = Tenant(tenantid=uuid.uuid4())
    alice = User(
        userid=uuid.uuid4(),
        displayname="Alice",
        email="alice@example.test",
        isactive=True,
    )
    bob = User(
        userid=uuid.uuid4(), displayname="Bob", email="bob@example.test", isactive=True
    )
    flow = Flow(flowid=uuid.uuid4(), tenantid=tenant, name="Support")
    status = Status(
        statusid=uuid.uuid4(),
        tenantid=tenant,
        flowid=flow,
        name="Open",
        category="open",
        isterminal=False,
    )
    item = Request(
        requestid=uuid.uuid4(),
        tenantid=tenant,
        humanid="RT-1",
        title="Workspace",
        priority="normal",
        flowid=flow,
        statusid=status,
        requesterid=alice,
        assigneeid=None,
        createdat=now,
        updatedat=now,
    )
    return item, bob


def context_request(item, bob, permissions=PERMISSIONS):
    return SimpleNamespace(
        tenant_id=item.tenantid_id,
        rt_workspace_context=SimpleNamespace(actor=bob, permissions=list(permissions)),
    )


class Rows(list):
    def filter(self, *args, **kwargs):
        def matches(obj):
            for key, value in kwargs.items():
                if key == "upload_group":
                    actual = json.loads(obj.payload).get("group_id")
                else:
                    field = key.removesuffix("__in")
                    actual = getattr(obj, field + "_id", getattr(obj, field, None))
                if key.endswith("__in"):
                    if str(actual) not in {str(v) for v in value}:
                        return False
                elif str(actual) != str(value):
                    return False
            return True

        return Rows(obj for obj in self if matches(obj))

    def select_related(self, *fields):
        return self

    def annotate(self, **kwargs):
        return self

    def order_by(self, *fields):
        return self

    def first(self):
        return self[0] if self else None

    def exists(self):
        return bool(self)


class MemoryS3:
    def __init__(self):
        self.objects = {}
        self.presigns = []

    def put_object(self, Bucket, Key, Body, ContentType):
        self.objects[Key] = (Body, ContentType)

    def get_object(self, Bucket, Key):
        if Key not in self.objects:
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
        return {"Body": io.BytesIO(self.objects[Key][0])}

    def head_object(self, Bucket, Key):
        if Key not in self.objects:
            raise ClientError({"Error": {"Code": "404"}}, "HeadObject")
        body, content_type = self.objects[Key]
        return {
            "ContentLength": len(body),
            "ContentType": content_type,
            "ETag": hashlib.md5(body).hexdigest(),
        }

    def copy_object(self, Bucket, Key, CopySource, CopySourceIfMatch):
        body, content_type = self.objects[CopySource["Key"]]
        assert hashlib.md5(body).hexdigest() == CopySourceIfMatch
        self.objects[Key] = (body, content_type)

    def generate_presigned_url(self, method, Params, ExpiresIn):
        self.presigns.append((method, Params, ExpiresIn))
        return "http://localhost:9000/signed"


@pytest.fixture
def upload_case(monkeypatch):
    item, bob = fixture_request()
    client = MemoryS3()
    comments, files, activities = Rows(), Rows(), Rows()
    locks = []
    monkeypatch.setattr(uploads, "storage_client", lambda: client)
    monkeypatch.setattr(uploads, "lock_group", lambda *args: locks.append(args))
    monkeypatch.setattr(
        uploads.Comment.objects, "filter", lambda **kwargs: comments.filter(**kwargs)
    )
    monkeypatch.setattr(
        uploads.Activity.objects, "filter", lambda **kwargs: activities.filter(**kwargs)
    )
    monkeypatch.setattr(
        uploads.Attachment.objects, "filter", lambda **kwargs: files.filter(**kwargs)
    )

    def create_comment(**kwargs):
        obj = Comment(**kwargs)
        comments.append(obj)
        return obj

    def create_activity(**kwargs):
        obj = Activity(**kwargs)
        activities.append(obj)
        return obj

    monkeypatch.setattr(uploads.Comment.objects, "create", create_comment)
    monkeypatch.setattr(uploads.Activity.objects, "create", create_activity)
    monkeypatch.setattr(
        uploads.Attachment.objects, "bulk_create", lambda values: files.extend(values)
    )
    monkeypatch.setattr(uploads.transaction, "on_commit", lambda callback: None)
    initiated = uploads.initiate_upload(
        item,
        [
            {"filename": "one.txt", "content_type": "text/plain", "size_bytes": 3},
            {"filename": "two.txt", "content_type": "text/plain", "size_bytes": 3},
        ],
        bob,
    )
    data = {
        "group_id": uuid.UUID(initiated["group_id"]),
        "message": "Files",
        "files": [],
    }
    for entry in initiated["uploads"]:
        client.put_object(
            Bucket="rt-attachments",
            Key=entry["object_key"],
            Body=b"abc",
            ContentType="text/plain",
        )
        data["files"].append(
            {
                key: entry[key]
                for key in ("object_key", "filename", "content_type", "size_bytes")
            }
        )
    return SimpleNamespace(
        item=item,
        bob=bob,
        client=client,
        comments=comments,
        files=files,
        activities=activities,
        locks=locks,
        data=data,
        initiated=initiated,
    )


def test_init_manifest_is_request_scoped_and_presigned_put(upload_case):
    case = upload_case
    manifest = json.loads(
        case.client.objects[uploads.manifest_key(case.item, case.data["group_id"])][0]
    )
    assert manifest["tenant_id"] == str(case.item.tenantid_id)
    assert manifest["request_id"] == str(case.item.requestid)
    assert all(
        item["object_key"].startswith(f"uploads/{case.data['group_id']}/")
        for item in manifest["files"]
    )
    assert all(
        call[0] == "put_object" and call[2] == 3600 for call in case.client.presigns
    )


def test_finalize_groups_once_uses_bob_and_retries_identically(upload_case):
    case = upload_case
    first, created = uploads.finalize_upload.__wrapped__(case.item, case.data, case.bob)
    second, repeated = uploads.finalize_upload.__wrapped__(
        case.item, case.data, case.bob
    )
    assert created and not repeated and first == second
    assert (
        len(case.comments) == 1 and len(case.files) == 2 and len(case.activities) == 1
    )
    assert case.comments[0].authorid == case.bob != case.item.requesterid
    assert case.activities[0].actorid == case.bob
    assert all(item.scanstatus == "pending" for item in case.files)
    assert len(case.locks) == 2


def test_finalize_conflicting_retry_is_409(upload_case):
    case = upload_case
    uploads.finalize_upload.__wrapped__(case.item, case.data, case.bob)
    case.data["message"] = "Different"
    with pytest.raises(WorkspaceConflict):
        uploads.finalize_upload.__wrapped__(case.item, case.data, case.bob)
    assert len(case.comments) == 1


def test_issued_put_cannot_overwrite_finalized_attachment(upload_case):
    case = upload_case
    uploads.finalize_upload.__wrapped__(case.item, case.data, case.bob)
    original = case.data["files"][0]["object_key"]
    saved = uploads.object_key(case.files[0])
    assert saved != original and saved.startswith(
        f"attachments/{case.item.tenantid_id}/{case.item.requestid}/"
    )
    case.client.put_object(
        Bucket="rt-attachments",
        Key=original,
        Body=b"replacement",
        ContentType="text/plain",
    )
    assert case.client.objects[saved][0] == b"abc"


def test_retry_can_omit_known_optional_metadata(upload_case):
    case = upload_case
    first, _ = uploads.finalize_upload.__wrapped__(case.item, case.data, case.bob)
    retry = {
        **case.data,
        "files": [
            {"object_key": item["object_key"], "filename": item["filename"]}
            for item in reversed(case.data["files"])
        ],
    }
    response, created = uploads.finalize_upload.__wrapped__(case.item, retry, case.bob)
    assert response == first and not created


def test_expired_first_finalize_is_rejected_but_committed_retry_remains_valid(
    upload_case,
):
    case = upload_case
    key = uploads.manifest_key(case.item, case.data["group_id"])
    body, content_type = case.client.objects[key]
    manifest = json.loads(body)
    manifest["expires_at"] = (timezone.now() - timedelta(hours=1)).isoformat()
    case.client.objects[key] = (json.dumps(manifest).encode(), content_type)
    with pytest.raises(WorkspaceConflict):
        uploads.finalize_upload.__wrapped__(case.item, case.data, case.bob)
    assert not case.comments
    manifest["expires_at"] = (timezone.now() + timedelta(hours=1)).isoformat()
    case.client.objects[key] = (json.dumps(manifest).encode(), content_type)
    first, _ = uploads.finalize_upload.__wrapped__(case.item, case.data, case.bob)
    del case.client.objects[key]
    repeated, created = uploads.finalize_upload.__wrapped__(
        case.item, case.data, case.bob
    )
    assert repeated == first and not created


def test_group_manifest_cannot_be_reused_for_other_request(upload_case):
    case = upload_case
    other, _ = fixture_request()
    other.tenantid = case.item.tenantid
    with pytest.raises(NotFound):
        uploads.checked_objects(case.client, other, case.data["group_id"], case.data)
    assert not case.comments


@pytest.mark.parametrize(
    "failure", ["missing", "size", "type", "keys", "duplicate", "filename"]
)
def test_finalize_integrity_fails_before_metadata(upload_case, failure):
    case = upload_case
    entry = case.data["files"][0]
    if failure == "missing":
        del case.client.objects[entry["object_key"]]
    elif failure == "size":
        entry["size_bytes"] = 5
    elif failure == "type":
        entry["content_type"] = "image/png"
    elif failure == "keys":
        entry["object_key"] = "uploads/other/arbitrary.txt"
    elif failure == "duplicate":
        case.data["files"] = [entry, entry]
    else:
        entry["filename"] = "wrong.txt"
    with pytest.raises(ValidationError):
        uploads.finalize_upload.__wrapped__(case.item, case.data, case.bob)
    assert not case.comments and not case.files and not case.activities


@pytest.mark.parametrize("state", ["pending", "blocked", None])
def test_unclean_download_has_no_presign(monkeypatch, state):
    client = MemoryS3()
    monkeypatch.setattr(uploads, "storage_client", lambda: client)
    with pytest.raises(WorkspaceConflict):
        uploads.download_url(Attachment(scanstatus=state))
    assert not client.presigns


def test_clean_download_short_lived_and_storage_scoped(monkeypatch):
    client = MemoryS3()
    monkeypatch.setattr(uploads, "storage_client", lambda: client)
    key = "uploads/group/a.txt"
    client.put_object(
        Bucket="rt-attachments", Key=key, Body=b"abc", ContentType="text/plain"
    )
    result = uploads.download_url(
        Attachment(
            scanstatus="clean", filename="a.txt", storageurl=uploads.storage_url(key)
        )
    )
    assert result["url"] and result["expires_at"] > timezone.now()
    assert client.presigns[0][0] == "get_object" and client.presigns[0][2] == 300


@pytest.mark.parametrize(
    "permission,capability",
    [
        ("comments.write", "can_comment"),
        ("attachments.write", "can_upload"),
        ("requests.write", "can_assign"),
        ("requests.transition", "can_transition"),
        ("requests.read", "can_download_attachments"),
    ],
)
def test_capabilities_match_server_permission_policy(permission, capability):
    item, bob = fixture_request()
    request = context_request(item, bob, ["requests.read", permission])
    assert capabilities(request.rt_workspace_context)[capability]
    assert require_workspace(request, permission).actor == bob
    request.rt_workspace_context.permissions = []
    assert not any(capabilities(request.rt_workspace_context).values())
    with pytest.raises(PermissionDenied):
        require_workspace(request, permission)


def test_inactive_actor_is_denied_even_with_role_permissions():
    item, bob = fixture_request()
    bob.isactive = False
    with pytest.raises(PermissionDenied):
        require_workspace(context_request(item, bob))


@pytest.mark.parametrize(
    "action,method,data",
    [
        ("retrieve", "get", None),
        ("timeline", "get", None),
        ("partial_update", "patch", {"assignee_id": None}),
        ("transition", "post", {"transition_id": str(uuid.uuid4())}),
        ("available_transitions", "get", None),
    ],
)
def test_workspace_missing_permissions_denied_before_object_read(
    monkeypatch, action, method, data
):
    item, bob = fixture_request()
    request = getattr(APIRequestFactory(), method)(
        "/api/requests/x/", data=data, format="json"
    )
    request.tenant_id = item.tenantid_id
    request.rt_workspace_context = SimpleNamespace(actor=bob, permissions=[])
    force_authenticate(request, user=SimpleNamespace(is_authenticated=True))
    monkeypatch.setattr(
        RequestViewSet,
        "get_object",
        lambda self: pytest.fail("Unauthorized object read"),
    )
    response = RequestViewSet.as_view({method: action})(request, pk=str(item.requestid))
    assert response.status_code == 403


@pytest.mark.parametrize(
    "view,path,method",
    [
        (AttachmentInitView, "/api/attachments/init", "post"),
        (AttachmentFinalizeView, "/api/attachments/finalize", "post"),
        (AttachmentDownloadView, "/api/requests/x/attachments/y/download/", "get"),
    ],
)
def test_upload_and_download_require_current_permission(view, path, method):
    item, bob = fixture_request()
    request = getattr(APIRequestFactory(), method)(path, {}, format="json")
    request.tenant_id = item.tenantid_id
    request.rt_workspace_context = SimpleNamespace(actor=bob, permissions=[])
    force_authenticate(request, user=SimpleNamespace(is_authenticated=True))
    kwargs = (
        {"request_pk": str(item.requestid), "attachment_pk": str(uuid.uuid4())}
        if method == "get"
        else {}
    )
    response = view.as_view()(request, **kwargs)
    assert response.status_code == 403


@pytest.mark.parametrize("note", ["", "   ", "Authored note"])
@pytest.mark.parametrize("allow_comments", [False, True])
@pytest.mark.parametrize("legacy", [False, True])
def test_finalize_text_permission_boundary(
    monkeypatch, upload_case, note, allow_comments, legacy
):
    case = upload_case
    grants = ["requests.read", "attachments.write"]
    if allow_comments:
        grants.append("comments.write")
    flags = capabilities(
        context_request(case.item, case.bob, grants).rt_workspace_context
    )
    assert flags["can_upload"] and flags["can_comment"] == allow_comments
    monkeypatch.setattr("apps.rt.views.get_object_or_404", lambda *a, **kw: case.item)
    monkeypatch.setattr(
        "apps.rt.views.finalize_upload", uploads.finalize_upload.__wrapped__
    )
    data = {
        "request_id": str(case.item.requestid),
        "group_id": str(case.data["group_id"]),
        "comment_markdown" if legacy else "message": note,
        "objects" if legacy else "files": case.data["files"],
    }
    request = APIRequestFactory().post("/api/attachments/finalize", data, format="json")
    request.tenant_id = case.item.tenantid_id
    request.rt_workspace_context = context_request(
        case.item, case.bob, grants
    ).rt_workspace_context
    force_authenticate(request, user=SimpleNamespace(is_authenticated=True))
    response = AttachmentFinalizeView.as_view()(request)
    denied = bool(note.strip()) and not allow_comments
    assert response.status_code == (403 if denied else 201)
    if denied:
        assert (
            not case.comments
            and not case.files
            and not case.activities
            and not case.locks
        )
        assert not any(key.startswith("attachments/") for key in case.client.objects)
    else:
        assert len(case.comments) == len(case.activities) == 1
        assert case.comments[0].messagemd == note.strip()
        assert case.comments[0].authorid == case.activities[0].actorid == case.bob


@pytest.mark.parametrize("action", ["transition", "close", "reopen"])
@pytest.mark.parametrize("note", ["", "   ", "Authored note"])
@pytest.mark.parametrize("allow_comments", [False, True])
def test_transition_text_permission_boundary(monkeypatch, action, note, allow_comments):
    item, bob = fixture_request()
    grants = ["requests.read", "requests.transition"]
    if allow_comments:
        grants.append("comments.write")
    flags = capabilities(context_request(item, bob, grants).rt_workspace_context)
    assert flags["can_transition"] and flags["can_comment"] == allow_comments
    chosen = SimpleNamespace(transitionid=uuid.uuid4())
    monkeypatch.setattr(RequestViewSet, "get_object", lambda self: item)
    monkeypatch.setattr(
        "apps.rt.views.get_available_transitions",
        lambda obj: SimpleNamespace(get=lambda **kw: chosen),
    )
    monkeypatch.setattr(
        "apps.rt.views.find_transition_by_target_category", lambda *a, **kw: chosen
    )
    writes = []

    def apply(**kwargs):
        writes.append(kwargs)
        return item

    monkeypatch.setattr("apps.rt.views.apply_transition", apply)
    request = APIRequestFactory().post(
        f"/api/requests/{item.requestid}/{action}/",
        {"transition_id": str(chosen.transitionid), "comment": note},
        format="json",
    )
    request.tenant_id = item.tenantid_id
    request.rt_workspace_context = context_request(
        item, bob, grants
    ).rt_workspace_context
    force_authenticate(request, user=SimpleNamespace(is_authenticated=True))
    response = RequestViewSet.as_view({"post": action})(request, pk=str(item.requestid))
    denied = bool(note.strip()) and not allow_comments
    assert response.status_code == (403 if denied else 200)
    assert len(writes) == int(not denied)
    if writes:
        assert writes[0]["comment"] == note.strip() and writes[0]["actor"] == bob


def test_download_wrong_request_scoped_lookup_never_presigns(monkeypatch):
    from django.http import Http404

    item, bob = fixture_request()
    captured = []

    def lookup(model, **kwargs):
        captured.append(kwargs)
        if model is Request:
            return item
        raise Http404()

    monkeypatch.setattr("apps.rt.views.get_object_or_404", lookup)
    monkeypatch.setattr(
        "apps.rt.views.download_url",
        lambda item: pytest.fail("Foreign attachment presigned"),
    )
    request = APIRequestFactory().get("/api/requests/x/attachments/y/download/")
    request.tenant_id = item.tenantid_id
    request.rt_workspace_context = context_request(item, bob).rt_workspace_context
    force_authenticate(request, user=SimpleNamespace(is_authenticated=True))
    response = AttachmentDownloadView.as_view()(
        request, request_pk=str(item.requestid), attachment_pk=str(uuid.uuid4())
    )
    assert response.status_code == 404
    assert (
        captured[-1]["requestid"] == item.requestid
        and captured[-1]["tenantid"] == item.tenantid_id
    )


def test_comment_bob_author_and_activity_actor(monkeypatch):
    item, bob = fixture_request()
    view = CommentViewSet()
    view.request = context_request(item, bob)
    view.get_request = lambda: item
    activities = []

    class Save:
        def save(self, **kwargs):
            self.kwargs = kwargs
            return Comment(**kwargs, messagemd="Bob's update", visibility="public")

    save = Save()
    monkeypatch.setattr(
        "apps.rt.views.Activity.objects.create",
        lambda **kwargs: activities.append(kwargs),
    )
    monkeypatch.setattr("apps.rt.views.transaction.on_commit", lambda callback: None)
    view.perform_create.__wrapped__(view, save)
    assert save.kwargs["authorid"] == bob != item.requesterid
    assert activities[0]["actorid"] == bob


def test_comment_author_input_ignored_and_private_semantics_not_invented():
    serializer = CommentSerializer(
        data={"body": "Update", "authorid": str(uuid.uuid4())}
    )
    assert serializer.is_valid() and "authorid" not in serializer.validated_data
    assert not CommentSerializer(
        data={"body": "Update", "visibility": "private"}
    ).is_valid()


@pytest.mark.parametrize("changed", [False, True])
def test_assignment_audit_only_on_change(monkeypatch, changed):
    item, bob = fixture_request()
    view = RequestViewSet()
    view.request = context_request(item, bob)
    audits, notices = [], []
    monkeypatch.setattr(
        "apps.rt.views.Request.objects.select_for_update",
        lambda: SimpleNamespace(get=lambda **kwargs: item),
    )
    monkeypatch.setattr(
        "apps.rt.views.Activity.objects.create", lambda **kwargs: audits.append(kwargs)
    )
    monkeypatch.setattr(
        "apps.rt.views.notify_request_assigned", lambda obj: notices.append(obj)
    )

    class Save:
        instance = item

        def save(self, **kwargs):
            if changed:
                item.assigneeid = bob
            item.updatedat = kwargs["updatedat"]
            return item

    view.perform_update.__wrapped__(view, Save())
    assert len(audits) == int(changed) and len(notices) == int(changed)
    if changed:
        assert audits[0]["actorid"] == bob
        assert json.loads(audits[0]["payload"])["new_assignee"]["user_id"] == str(
            bob.userid
        )


def test_status_cannot_bypass_transition_via_patch():
    item, _ = fixture_request()
    serializer = RequestSerializer(
        item,
        data={"status_id": str(uuid.uuid4())},
        partial=True,
        context={"tenant_id": item.tenantid_id},
    )
    assert not serializer.is_valid()
    assert "status_id" in serializer.errors


class TimelineCursor:
    def __init__(self, count, rows):
        self.count, self.rows, self.calls = count, rows, []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, params):
        self.calls.append((sql, params))

    def fetchone(self):
        return (self.count,)

    def fetchall(self):
        return self.rows


def timeline_case(
    monkeypatch,
    item,
    rows,
    activities=(),
    comments=(),
    files=(),
    statuses=(),
    count=None,
):
    cursor = TimelineCursor(len(rows) if count is None else count, rows)
    monkeypatch.setattr(timeline.connection, "cursor", lambda: cursor)
    scopes = []
    for model, values in (
        (Activity, activities),
        (Comment, comments),
        (Attachment, files),
        (Status, statuses),
    ):

        def filtered(values=values, **kwargs):
            scopes.append(kwargs)
            return Rows(values).filter(**kwargs)

        monkeypatch.setattr(model.objects, "filter", filtered)
    return cursor, scopes


def test_transition_comment_and_upload_group_are_one_semantic_event(monkeypatch):
    item, bob = fixture_request()
    comment = Comment(
        commentid=uuid.uuid4(),
        tenantid=item.tenantid,
        requestid=item,
        authorid=bob,
        messagemd="Done",
        visibility="public",
        createdat=timezone.now(),
    )
    group = uuid.uuid4()
    attachment = Attachment(
        attachmentid=uuid.uuid4(),
        tenantid=item.tenantid,
        requestid=item,
        commentid=comment,
        groupid=str(group),
        filename="a.txt",
        scanstatus="pending",
        createdat=comment.createdat,
    )
    activity = Activity(
        activityid=uuid.uuid4(),
        tenantid=item.tenantid,
        requestid=item,
        actorid=bob,
        type="attachments.finalized",
        createdat=comment.createdat,
        payload=json.dumps(
            {"comment_id": str(comment.commentid), "group_id": str(group)}
        ),
    )
    row = (
        "activity",
        f"activity:{activity.activityid}",
        str(activity.activityid),
        activity.createdat,
    )
    cursor, scopes = timeline_case(
        monkeypatch, item, [row], [activity], [comment], [attachment]
    )
    count, events = timeline.timeline_page(
        tenant_id=item.tenantid_id, request_id=item.requestid
    )
    assert count == len(events) == 1
    assert events[0]["kind"] == "attachments" and events[0]["comment"]["body"] == "Done"
    assert len(events[0]["attachments"]) == 1 and events[0]["actor"]["user_id"] == str(
        bob.userid
    )
    assert "storageurl" not in str(events[0])
    assert all(str(scope["tenantid"]) == str(item.tenantid_id) for scope in scopes)
    assert "LinkedComment=c.CommentId" in cursor.calls[0][0]
    assert "DuplicateOrder=1" in cursor.calls[0][0]
    assert "'{}'" not in cursor.calls[0][0]
    assert "NCHAR(123)+NCHAR(125)" in cursor.calls[0][0]


def test_unknown_activity_does_not_dump_payload(monkeypatch):
    item, _ = fixture_request()
    activity = Activity(
        activityid=uuid.uuid4(),
        tenantid=item.tenantid,
        requestid=item,
        actorid=None,
        type="legacy.event",
        payload="{broken: secret}",
        createdat=timezone.now(),
    )
    row = (
        "activity",
        f"activity:{activity.activityid}",
        str(activity.activityid),
        activity.createdat,
    )
    timeline_case(monkeypatch, item, [row], [activity])
    _, events = timeline.timeline_page(
        tenant_id=item.tenantid_id, request_id=item.requestid
    )
    assert events[0]["kind"] == "system" and events[0]["actor"] is None
    assert events[0]["activity_type"] == "legacy.event"
    assert "secret" not in str(events)


@pytest.mark.parametrize(
    "category,from_category,kind",
    [
        ("closed", "open", "request_closed"),
        ("open", "closed", "request_reopened"),
        ("waiting", "open", "transition"),
    ],
)
def test_generic_transition_comment_semantics(
    monkeypatch, category, from_category, kind
):
    item, bob = fixture_request()
    source = item.statusid
    source.category = from_category
    target = Status(
        statusid=uuid.uuid4(),
        tenantid=item.tenantid,
        flowid=item.flowid,
        name="Target",
        category=category,
        isterminal=category == "closed",
    )
    comment = Comment(
        commentid=uuid.uuid4(),
        tenantid=item.tenantid,
        requestid=item,
        authorid=bob,
        messagemd="Moving",
        visibility="public",
        createdat=timezone.now(),
    )
    activity = Activity(
        activityid=uuid.uuid4(),
        tenantid=item.tenantid,
        requestid=item,
        actorid=bob,
        type="request.transitioned",
        createdat=comment.createdat,
        payload=json.dumps(
            {
                "comment_id": str(comment.commentid),
                "from_status_id": str(source.statusid),
                "to_status_id": str(target.statusid),
            }
        ),
    )
    row = (
        "activity",
        f"activity:{activity.activityid}",
        str(activity.activityid),
        activity.createdat,
    )
    timeline_case(
        monkeypatch, item, [row], [activity], [comment], statuses=[source, target]
    )
    _, events = timeline.timeline_page(
        tenant_id=item.tenantid_id, request_id=item.requestid
    )
    assert events[0]["kind"] == kind and events[0]["comment"]["body"] == "Moving"
    assert events[0]["to_status"]["status_id"] == str(target.statusid)


def test_transition_snapshot_survives_later_status_label_change():
    identity = str(uuid.uuid4())
    historical = {
        "status_id": identity,
        "name": "Closed then",
        "category": "closed",
        "is_terminal": True,
    }
    current = {
        "status_id": identity,
        "name": "Edited",
        "category": "waiting",
        "is_terminal": False,
    }
    assert (
        timeline.event_status({"to_status": historical}, "to_status", current)
        == historical
    )
    assert timeline.event_status({"to_status": historical}, "to_status", None) is None


def test_timeline_error_does_not_block_core(monkeypatch):
    item, bob = fixture_request()
    monkeypatch.setattr(RequestViewSet, "get_object", lambda self: item)

    def fail(**kwargs):
        raise timeline.TimelineUnavailable()

    monkeypatch.setattr("apps.rt.views.timeline_page", fail)
    factory = APIRequestFactory()

    def dispatch(action):
        request = factory.get("/api/requests/x/")
        request.tenant_id = item.tenantid_id
        request.rt_workspace_context = context_request(item, bob).rt_workspace_context
        force_authenticate(request, user=SimpleNamespace(is_authenticated=True))
        return RequestViewSet.as_view({"get": action})(request, pk=str(item.requestid))

    assert dispatch("timeline").status_code == 503
    assert dispatch("retrieve").status_code == 200


@pytest.mark.parametrize("count,page", [(0, 1), (26, 3)])
def test_timeline_empty_and_out_of_range_keep_count(monkeypatch, count, page):
    item, _ = fixture_request()
    cursor, _ = timeline_case(monkeypatch, item, [], count=count)
    total, events = timeline.timeline_page(
        tenant_id=item.tenantid_id, request_id=item.requestid, page=page
    )
    assert total == count and events == [] and len(cursor.calls) == 1


@pytest.mark.parametrize("data", [{"page": 0}, {"page_size": 101}, {"page_size": 0}])
def test_timeline_page_limits(data):
    assert not TimelineQuerySerializer(data=data).is_valid()


def test_workspace_routes_and_openapi():
    request_id, attachment_id = uuid.uuid4(), uuid.uuid4()
    assert (
        resolve(f"/api/requests/{request_id}/timeline/").url_name == "requests-timeline"
    )
    assert (
        resolve(
            f"/api/requests/{request_id}/attachments/{attachment_id}/download/"
        ).url_name
        == "request-attachment-download"
    )
    schema = yaml.safe_load(Client().get("/api/schema").content)
    assert "/api/requests/{requestid}/timeline/" in schema["paths"]
    assert (
        "/api/requests/{request_pk}/attachments/{attachment_pk}/download/"
        in schema["paths"]
    )
    assert schema["paths"]["/api/requests/{requestid}/detail/"]["get"]["deprecated"]
    assert (
        "capabilities" in schema["components"]["schemas"]["RequestDetail"]["properties"]
    )
    assert (
        "requires_comment"
        not in schema["components"]["schemas"]["TransitionLookup"]["properties"]
    )


def test_detail_capabilities_additive_and_core_independent():
    item, bob = fixture_request()
    context = context_request(item, bob).rt_workspace_context
    data = RequestDetailSerializer(
        item, context={"capabilities": capabilities(context)}
    ).data
    assert data["request_id"] == str(item.requestid)
    assert data["capabilities"]["can_comment"] and data["flow"]["name"] == "Support"


def test_legacy_attachment_fields_and_new_aliases(upload_case):
    case = upload_case
    uploads.finalize_upload.__wrapped__(case.item, case.data, case.bob)
    data = AttachmentSerializer(case.files[0]).data
    assert data["attachmentid"] == data["attachment_id"]
    assert data["scanstatus"] == data["scan_status"] == "pending"
    assert data["createdat"] == data["created_at"]


def test_finalize_legacy_aliases_still_validate():
    item, _ = fixture_request()
    serializer = AttachmentFinalizeRequestSerializer(
        data={
            "request_id": str(item.requestid),
            "group_id": str(uuid.uuid4()),
            "comment_markdown": "Files",
            "objects": [{"object_key": "uploads/group/a.txt", "filename": "a.txt"}],
            "idempotency_key": "legacy",
        }
    )
    assert serializer.is_valid(), serializer.errors
    assert (
        serializer.validated_data["message"] == "Files"
        and serializer.validated_data["files"]
    )


@pytest.mark.parametrize(
    "host,endpoint",
    [
        ("production", "http://localhost:9000"),
        ("localhost", "https://storage.example.test"),
    ],
)
def test_live_verifier_rejects_nonlocal_services(host, endpoint):
    from scripts.verify_m7b_workspace import require_local_services

    with pytest.raises(RuntimeError, match="loopback"):
        require_local_services(
            SimpleNamespace(
                DATABASES={"default": {"HOST": host}},
                MINIO_ENDPOINT=endpoint,
                MINIO_PUBLIC_URL="",
            )
        )


def test_live_verifier_child_requires_parent_owned_target(monkeypatch):
    from scripts.verify_m7b_workspace import configure

    monkeypatch.delenv("RT_M7B_OWNED_TARGET", raising=False)
    with pytest.raises(RuntimeError, match="unowned"):
        configure("rt_m7b_123456abcdef", "rt-m7b-123456abcdef")
