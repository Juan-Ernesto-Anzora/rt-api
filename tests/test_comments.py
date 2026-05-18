import uuid
from types import SimpleNamespace

from django.urls import resolve

from apps.rt.models import Flow, Request, Status, Tenant, User
from apps.rt.serializers import CommentSerializer
from apps.rt.views import CommentViewSet

UPPER_REQUEST_ID = "9DC80633-F354-44D3-A4CE-B3B78A027D33"


def test_uppercase_request_id_matches_comments_route():
    match = resolve(f"/api/requests/{UPPER_REQUEST_ID}/comments")

    assert match.url_name == "request-comments"
    assert match.kwargs["request_pk"] == UPPER_REQUEST_ID


def test_uppercase_request_id_matches_attachments_route():
    match = resolve(f"/api/requests/{UPPER_REQUEST_ID}/attachments")

    assert match.url_name == "request-attachments"
    assert match.kwargs["request_pk"] == UPPER_REQUEST_ID


def test_comment_serializer_accepts_body_alias_and_defaults_visibility():
    serializer = CommentSerializer(data={"body": "Postman comment"})

    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data["messagemd"] == "Postman comment"
    assert serializer.validated_data["visibility"] == "public"


def test_comment_create_uses_tenant_scoped_request_and_requester(monkeypatch):
    tenant_id = uuid.uuid4()
    request_id = uuid.UUID(UPPER_REQUEST_ID)
    tenant = Tenant(tenantid=tenant_id)
    requester = User(userid=uuid.uuid4())
    rt_request = Request(
        requestid=request_id,
        tenantid=tenant,
        humanid="RT-2026-000001",
        title="Comment test",
        flowid=Flow(flowid=uuid.uuid4(), tenantid=tenant),
        statusid=Status(statusid=uuid.uuid4(), tenantid=tenant),
        priority="normal",
        requesterid=requester,
    )
    captured_get = {}
    captured_save = {}

    def fake_get(**kwargs):
        captured_get.update(kwargs)
        return rt_request

    class FakeSerializer:
        def save(self, **kwargs):
            captured_save.update(kwargs)

    monkeypatch.setattr("apps.rt.views.Request.objects.get", fake_get)
    view = CommentViewSet()
    view.request = SimpleNamespace(tenant_id=tenant_id)
    view.kwargs = {"request_pk": UPPER_REQUEST_ID}

    view.perform_create(FakeSerializer())

    assert captured_get == {"requestid": request_id, "tenantid": tenant_id}
    assert isinstance(captured_save["commentid"], uuid.UUID)
    assert captured_save["tenantid"] == tenant
    assert captured_save["requestid"] == rt_request
    assert captured_save["authorid"] == requester
