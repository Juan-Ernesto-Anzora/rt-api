import uuid
from types import SimpleNamespace

from apps.rt.models import Comment, Flow, Request, Status, Tenant, User
from apps.rt.views import AttachmentFinalizeView, AttachmentInitView


class FakeS3Client:
    def __init__(self):
        self.calls = []

    def generate_presigned_url(self, method, Params, ExpiresIn):
        self.calls.append(
            {
                "method": method,
                "params": Params,
                "expires_in": ExpiresIn,
            }
        )
        return f"https://minio.local/{Params['Bucket']}/{Params['Key']}"


def test_attachment_init_returns_grouped_presigned_uploads(monkeypatch):
    request_id = uuid.uuid4()
    tenant_id = uuid.uuid4()
    fake_s3 = FakeS3Client()

    def fake_get(**kwargs):
        assert kwargs == {"requestid": request_id, "tenantid": tenant_id}
        return SimpleNamespace(requestid=request_id)

    monkeypatch.setattr("apps.rt.views.Request.objects.get", fake_get)
    monkeypatch.setattr("apps.rt.views.boto3.client", lambda *args, **kwargs: fake_s3)

    request = SimpleNamespace(
        tenant_id=tenant_id,
        data={
            "request_id": str(request_id),
            "files": [
                {
                    "filename": "screen.png",
                    "content_type": "image/png",
                    "size_bytes": 123,
                    "checksum": "abc123",
                },
                {
                    "filename": "notes.txt",
                    "content_type": "text/plain",
                },
            ],
        },
    )

    response = AttachmentInitView().post(request)

    assert response.status_code == 200
    assert response.data["request_id"] == str(request_id)
    assert response.data["group_id"]
    assert len(response.data["uploads"]) == 2
    assert response.data["uploads"][0]["method"] == "PUT"
    assert response.data["uploads"][0]["headers"] == {"Content-Type": "image/png"}
    assert response.data["uploads"][0]["object_key"].startswith("uploads/")
    assert fake_s3.calls[0]["params"]["Bucket"] == "rt-attachments"


def test_attachment_finalize_creates_one_comment_and_grouped_attachments(monkeypatch):
    tenant_id = uuid.uuid4()
    request_id = uuid.uuid4()
    user_id = uuid.uuid4()
    group_id = uuid.uuid4()
    tenant = Tenant(tenantid=tenant_id)
    requester = User(userid=user_id)
    rt_request = Request(
        requestid=request_id,
        tenantid=tenant,
        humanid="RT-2026-000001",
        title="Upload test",
        flowid=Flow(flowid=uuid.uuid4(), tenantid=tenant),
        statusid=Status(statusid=uuid.uuid4(), tenantid=tenant),
        priority="normal",
        requesterid=requester,
    )
    comment = Comment(commentid=uuid.uuid4())
    created_comments = []
    created_attachments = []
    created_activities = []

    def fake_get(**kwargs):
        assert kwargs == {"requestid": request_id, "tenantid": tenant_id}
        return rt_request

    def fake_create_comment(**kwargs):
        created_comments.append(kwargs)
        return comment

    def fake_bulk_create(attachments):
        created_attachments.extend(attachments)

    def fake_create_activity(**kwargs):
        created_activities.append(kwargs)

    monkeypatch.setattr("apps.rt.views.Request.objects.get", fake_get)
    monkeypatch.setattr("apps.rt.views.Comment.objects.create", fake_create_comment)
    monkeypatch.setattr(
        "apps.rt.views.Attachment.objects.bulk_create", fake_bulk_create
    )
    monkeypatch.setattr("apps.rt.views.Activity.objects.create", fake_create_activity)

    request = SimpleNamespace(
        tenant_id=tenant_id,
        data={
            "request_id": str(request_id),
            "group_id": str(group_id),
            "message": "Uploaded two files",
            "files": [
                {
                    "object_key": f"uploads/{group_id}/screen.png",
                    "filename": "screen.png",
                    "content_type": "image/png",
                    "size_bytes": 123,
                    "checksum": "abc123",
                },
                {
                    "object_key": f"uploads/{group_id}/notes.txt",
                    "filename": "notes.txt",
                    "content_type": "text/plain",
                },
            ],
        },
    )
    post = AttachmentFinalizeView.post.__wrapped__

    response = post(AttachmentFinalizeView(), request)

    assert response.status_code == 201
    assert response.data["group_id"] == str(group_id)
    assert response.data["comment_id"] == str(comment.commentid)
    assert len(response.data["attachments"]) == 2
    assert isinstance(created_comments[0]["commentid"], uuid.UUID)
    assert created_comments[0]["groupid"] == str(group_id)
    assert created_comments[0]["messagemd"] == "Uploaded two files"
    assert len(created_attachments) == 2
    assert created_attachments[0].groupid == str(group_id)
    assert created_attachments[0].scanstatus == "pending"
    assert created_attachments[0].storageurl.endswith(
        f"rt-attachments/uploads/{group_id}/screen.png"
    )
    assert created_activities[0]["type"] == "attachments.finalized"


def test_attachment_finalize_accepts_postman_object_payload(monkeypatch):
    tenant_id = uuid.uuid4()
    request_id = uuid.uuid4()
    group_id = uuid.uuid4()
    tenant = Tenant(tenantid=tenant_id)
    requester = User(userid=uuid.uuid4())
    rt_request = Request(
        requestid=request_id,
        tenantid=tenant,
        humanid="RT-2026-000001",
        title="Postman upload test",
        flowid=Flow(flowid=uuid.uuid4(), tenantid=tenant),
        statusid=Status(statusid=uuid.uuid4(), tenantid=tenant),
        priority="normal",
        requesterid=requester,
    )
    comment = Comment(commentid=uuid.uuid4())
    created_comments = []
    created_attachments = []

    monkeypatch.setattr(
        "apps.rt.views.Request.objects.get",
        lambda **kwargs: rt_request,
    )
    monkeypatch.setattr(
        "apps.rt.views.Comment.objects.create",
        lambda **kwargs: created_comments.append(kwargs) or comment,
    )
    monkeypatch.setattr(
        "apps.rt.views.Attachment.objects.bulk_create",
        lambda attachments: created_attachments.extend(attachments),
    )
    monkeypatch.setattr("apps.rt.views.Activity.objects.create", lambda **kwargs: None)

    request = SimpleNamespace(
        tenant_id=tenant_id,
        data={
            "request_id": str(request_id),
            "group_id": str(group_id),
            "comment_markdown": "Finalized Postman upload.",
            "objects": [
                {
                    "object_key": f"uploads/{group_id}/postman-vpn-smoke.txt",
                    "filename": "postman-vpn-smoke.txt",
                    "content_type": "text/plain",
                    "size_bytes": 128,
                }
            ],
            "idempotency_key": "postman-finalize-123",
        },
    )
    post = AttachmentFinalizeView.post.__wrapped__

    response = post(AttachmentFinalizeView(), request)

    assert response.status_code == 201
    assert created_comments[0]["messagemd"] == "Finalized Postman upload."
    assert created_attachments[0].filename == "postman-vpn-smoke.txt"
