import uuid
from types import SimpleNamespace

from django.test import Client
from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.rt.models import Activity, Tenant, User
from apps.rt.services.admin_permissions import (
    ADMIN_AUDIT_READ_PERMISSION,
    AdminPermissionError,
)
from apps.rt.views import AdminAuditView


class FakeActivityQuerySet(list):
    def __init__(self, items=None):
        super().__init__(items or [])
        self.calls = []

    def order_by(self, *fields):
        self.calls.append(("order_by", fields))
        return self

    def filter(self, **kwargs):
        self.calls.append(("filter", kwargs))
        return self


def make_activity(tenant, activity_type="request.created"):
    actor = User(
        userid=uuid.uuid4(),
        email="admin@example.com",
        displayname="Admin User",
    )
    return Activity(
        activityid=uuid.uuid4(),
        tenantid=tenant,
        requestid_id=uuid.uuid4(),
        actorid=actor,
        actorid_id=actor.userid,
        type=activity_type,
        payload='{"source":"pytest"}',
        createdat=timezone.now(),
    )


def authenticated_request(path, tenant_id):
    request = APIRequestFactory().get(path)
    request.tenant_id = tenant_id
    force_authenticate(
        request,
        user=SimpleNamespace(
            is_authenticated=True,
            email="admin@example.com",
            username="admin",
        ),
    )
    return request


def test_admin_audit_endpoint_requires_audit_permission(monkeypatch):
    tenant_id = uuid.uuid4()
    checked_permissions = []

    def fake_get_admin_context(request, required_permission):
        checked_permissions.append(required_permission)
        return SimpleNamespace()

    monkeypatch.setattr("apps.rt.views.get_admin_context", fake_get_admin_context)
    monkeypatch.setattr(
        "apps.rt.views.Activity.objects.filter",
        lambda **kwargs: FakeActivityQuerySet(),
    )

    response = AdminAuditView.as_view()(
        authenticated_request("/api/admin/audit/", tenant_id)
    )

    assert response.status_code == 200
    assert checked_permissions == [ADMIN_AUDIT_READ_PERMISSION]


def test_admin_audit_endpoint_is_tenant_scoped(monkeypatch):
    tenant = Tenant(tenantid=uuid.uuid4(), code="ACME", name="ACME")
    activity = make_activity(tenant)
    fake_qs = FakeActivityQuerySet([activity])
    captured = {}

    monkeypatch.setattr(
        "apps.rt.views.get_admin_context",
        lambda request, required_permission: SimpleNamespace(),
    )

    def fake_filter(**kwargs):
        captured.update(kwargs)
        return fake_qs

    monkeypatch.setattr("apps.rt.views.Activity.objects.filter", fake_filter)

    response = AdminAuditView.as_view()(
        authenticated_request("/api/admin/audit/", tenant.tenantid)
    )

    assert response.status_code == 200
    assert captured == {"tenantid": tenant.tenantid}
    assert fake_qs.calls[0] == ("order_by", ("-createdat",))
    assert response.data["results"][0]["activity_id"] == str(activity.activityid)
    assert response.data["results"][0]["actor_id"] == str(activity.actorid_id)
    assert response.data["results"][0]["type"] == "request.created"


def test_admin_audit_endpoint_applies_safe_filters(monkeypatch):
    tenant_id = uuid.uuid4()
    request_id = uuid.uuid4()
    actor_id = uuid.uuid4()
    fake_qs = FakeActivityQuerySet()
    monkeypatch.setattr(
        "apps.rt.views.get_admin_context",
        lambda request, required_permission: SimpleNamespace(),
    )
    monkeypatch.setattr(
        "apps.rt.views.Activity.objects.filter",
        lambda **kwargs: fake_qs,
    )

    response = AdminAuditView.as_view()(
        authenticated_request(
            "/api/admin/audit/"
            f"?type=request.created&request_id={request_id}&actor_id={actor_id}"
            "&created_from=2026-06-01T00:00:00Z"
            "&created_to=2026-06-10T23:59:59Z",
            tenant_id,
        )
    )

    assert response.status_code == 200
    assert fake_qs.calls == [
        ("order_by", ("-createdat",)),
        ("filter", {"type": "request.created"}),
        ("filter", {"requestid_id": str(request_id)}),
        ("filter", {"actorid_id": str(actor_id)}),
        ("filter", {"createdat__gte": "2026-06-01T00:00:00Z"}),
        ("filter", {"createdat__lte": "2026-06-10T23:59:59Z"}),
    ]


def test_admin_audit_endpoint_denies_missing_audit_permission(monkeypatch):
    def fake_get_admin_context(request, required_permission):
        raise AdminPermissionError(
            code="permission_denied",
            message="You do not have permission to access this admin resource.",
            status_code=403,
        )

    monkeypatch.setattr("apps.rt.views.get_admin_context", fake_get_admin_context)

    response = AdminAuditView.as_view()(
        authenticated_request("/api/admin/audit/", uuid.uuid4())
    )

    assert response.status_code == 403
    assert response.data == {
        "code": "permission_denied",
        "message": "You do not have permission to access this admin resource.",
        "details": [],
    }


def test_openapi_schema_includes_admin_audit_path():
    response = Client().get("/api/schema")

    assert response.status_code == 200
    assert b"/api/admin/audit/" in response.content
