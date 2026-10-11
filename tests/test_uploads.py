import uuid

from test_request_workspace import MemoryS3, context_request, fixture_request

from apps.rt.serializers import AttachmentFinalizeRequestSerializer
from apps.rt.views import AttachmentFinalizeView, AttachmentInitView


def test_attachment_init_returns_grouped_presigned_uploads(monkeypatch):
    item, bob = fixture_request()
    client = MemoryS3()
    monkeypatch.setattr(
        "apps.rt.services.request_uploads.storage_client", lambda: client
    )
    monkeypatch.setattr("apps.rt.views.get_object_or_404", lambda *args, **kwargs: item)
    request = context_request(item, bob)
    request.data = {
        "request_id": str(item.requestid),
        "files": [
            {"filename": "screen.png", "content_type": "image/png", "size_bytes": 123},
            {"filename": "notes.txt", "content_type": "text/plain"},
        ],
    }
    response = AttachmentInitView().post(request)
    assert response.status_code == 200
    assert response.data["request_id"] == str(item.requestid)
    assert len(response.data["uploads"]) == 2
    assert response.data["uploads"][0]["method"] == "PUT"
    assert response.data["uploads"][0]["headers"] == {"Content-Type": "image/png"}
    assert all(call[1]["Bucket"] == "rt-attachments" for call in client.presigns)


def test_attachment_finalize_retry_response_keeps_legacy_shape(monkeypatch):
    item, bob = fixture_request()
    request = context_request(item, bob)
    group_id = uuid.uuid4()
    request.data = {
        "request_id": str(item.requestid),
        "group_id": str(group_id),
        "message": "Files",
        "files": [{"object_key": "issued/key", "filename": "a.txt"}],
    }
    captured = {}

    def finalized(req, data, actor):
        captured.update(request=req, data=data, actor=actor)
        return {
            "request_id": str(req.requestid),
            "group_id": str(group_id),
            "comment_id": str(uuid.uuid4()),
            "attachments": [],
        }, False

    monkeypatch.setattr("apps.rt.views.get_object_or_404", lambda *args, **kwargs: item)
    monkeypatch.setattr("apps.rt.views.finalize_upload", finalized)
    response = AttachmentFinalizeView().post(request)
    assert response.status_code == 200
    assert response.data["group_id"] == str(group_id)
    assert captured["actor"] == bob != item.requesterid


def test_attachment_finalize_accepts_postman_object_payload():
    serializer = AttachmentFinalizeRequestSerializer(
        data={
            "request_id": str(uuid.uuid4()),
            "group_id": str(uuid.uuid4()),
            "comment_markdown": "Finalized Postman upload.",
            "objects": [
                {
                    "object_key": "issued/key",
                    "filename": "postman-vpn-smoke.txt",
                    "content_type": "text/plain",
                    "size_bytes": 128,
                }
            ],
            "idempotency_key": "postman-finalize-123",
        }
    )
    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data["message"] == "Finalized Postman upload."
    assert serializer.validated_data["files"][0]["filename"] == "postman-vpn-smoke.txt"
