import uuid
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest
from django.test import Client
from django.urls import resolve
from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.rt.models import Slapolicy
from apps.rt.serializers import AdminSlaPolicySerializer, AdminSlaPolicyWriteSerializer
from apps.rt.services import sla_service
from apps.rt.services.admin_directory import AdminDirectoryError
from apps.rt.services.admin_permissions import (
    ADMIN_ACCESS_PERMISSION,
    SLA_MANAGE_PERMISSION,
)
from apps.rt.views import AdminSlaPolicyDetailView, AdminSlaPolicyListCreateView


class ExistsQuerySet:
    def __init__(self, exists):
        self._exists = exists

    def exists(self):
        return self._exists


def make_policy(tenant_id=None, is_active=True):
    now = timezone.now()
    return Slapolicy(
        policyid=uuid.uuid4(),
        tenantid_id=tenant_id or uuid.uuid4(),
        name="Normal",
        priority="normal",
        responseminutes=120,
        resolutionminutes=1440,
        isactive=is_active,
        appliesto=None,
        targets=None,
        createdat=now,
        updatedat=None,
    )


def admin_context(*permissions):
    return SimpleNamespace(
        user=SimpleNamespace(user_id=str(uuid.uuid4())),
        permissions=list(permissions),
    )


def authenticated_request(method, path, tenant_id, data=None):
    request = getattr(APIRequestFactory(), method)(path, data or {}, format="json")
    request.tenant_id = tenant_id
    force_authenticate(
        request,
        user=SimpleNamespace(
            is_authenticated=True,
            email="admin@example.com",
            username="admin@example.com",
        ),
    )
    return request


def test_sla_routes_resolve_without_delete_route():
    policy_id = uuid.uuid4()
    assert resolve("/api/admin/sla-policies/").url_name == "admin-sla-policies"
    match = resolve(f"/api/admin/sla-policies/{policy_id}/")
    assert match.url_name == "admin-sla-policy-detail"
    assert not hasattr(AdminSlaPolicyDetailView, "delete")


def test_sla_serializer_uses_public_fields():
    policy = make_policy()
    data = AdminSlaPolicySerializer(policy).data

    assert data["sla_policy_id"] == str(policy.policyid)
    assert data["response_minutes"] == 120
    assert data["resolution_minutes"] == 1440
    assert data["is_active"] is True
    assert "policyid" not in data
    assert "appliesto" not in data
    assert "targets" not in data


@pytest.mark.parametrize("value", [0, -1])
def test_sla_serializer_rejects_non_positive_minutes(value):
    serializer = AdminSlaPolicyWriteSerializer(
        data={
            "name": "Normal",
            "priority": "normal",
            "response_minutes": value,
            "resolution_minutes": 120,
        }
    )

    assert not serializer.is_valid()
    assert "response_minutes" in serializer.errors


def test_sla_serializer_normalizes_priority_and_rejects_target_order():
    serializer = AdminSlaPolicyWriteSerializer(
        data={
            "name": " Normal ",
            "priority": "URGENT",
            "response_minutes": 121,
            "resolution_minutes": 120,
        }
    )

    assert not serializer.is_valid()
    assert serializer.errors["response_minutes"][0].startswith("Response minutes")


def test_sla_endpoint_requires_baseline_and_sla_permission(monkeypatch):
    monkeypatch.setattr(
        "apps.rt.views.get_admin_context",
        lambda request, required_permission: admin_context(ADMIN_ACCESS_PERMISSION),
    )

    response = AdminSlaPolicyListCreateView.as_view()(
        authenticated_request("get", "/api/admin/sla-policies/", uuid.uuid4())
    )

    assert response.status_code == 403
    assert response.data["code"] == "permission_denied"


def test_sla_create_endpoint_returns_public_policy(monkeypatch):
    tenant_id = uuid.uuid4()
    policy = make_policy(tenant_id)
    captured = {}
    monkeypatch.setattr(
        "apps.rt.views.get_admin_context",
        lambda request, required_permission: admin_context(
            ADMIN_ACCESS_PERMISSION, SLA_MANAGE_PERMISSION
        ),
    )

    def fake_create(tenant_id, actor_id, data):
        captured.update({"tenant_id": tenant_id, "data": data})
        return policy

    monkeypatch.setattr("apps.rt.views.create_sla_policy", fake_create)

    response = AdminSlaPolicyListCreateView.as_view()(
        authenticated_request(
            "post",
            "/api/admin/sla-policies/",
            tenant_id,
            {
                "name": "Normal",
                "priority": "NORMAL",
                "response_minutes": 120,
                "resolution_minutes": 1440,
            },
        )
    )

    assert response.status_code == 201
    assert captured["tenant_id"] == tenant_id
    assert captured["data"]["priority"] == "normal"
    assert response.data["sla_policy_id"] == str(policy.policyid)


def test_sla_cross_tenant_detail_returns_404(monkeypatch):
    monkeypatch.setattr(
        "apps.rt.views.get_admin_context",
        lambda request, required_permission: admin_context(
            ADMIN_ACCESS_PERMISSION, SLA_MANAGE_PERMISSION
        ),
    )
    monkeypatch.setattr(
        "apps.rt.views.tenant_sla_policy",
        lambda *args: (_ for _ in ()).throw(
            AdminDirectoryError("not_found", "SLA policy not found.", 404)
        ),
    )

    response = AdminSlaPolicyDetailView.as_view()(
        authenticated_request("get", "/api/admin/sla-policies/x/", uuid.uuid4()),
        sla_policy_id=uuid.uuid4(),
    )

    assert response.status_code == 404
    assert response.data["code"] == "not_found"


def test_sla_create_service_writes_one_audit(monkeypatch):
    tenant_id = uuid.uuid4()
    audits = []
    monkeypatch.setattr(sla_service.transaction, "atomic", lambda: nullcontext())
    monkeypatch.setattr(
        "apps.rt.services.sla_service.Slapolicy.objects.filter",
        lambda **kwargs: ExistsQuerySet(False),
    )
    monkeypatch.setattr(
        "apps.rt.services.sla_service.Slapolicy.objects.create",
        lambda **kwargs: Slapolicy(**kwargs),
    )
    monkeypatch.setattr(
        sla_service, "write_admin_audit", lambda *args: audits.append(args)
    )

    policy = sla_service.create_sla_policy(
        tenant_id,
        uuid.uuid4(),
        {
            "name": "Normal",
            "priority": "normal",
            "response_minutes": 120,
            "resolution_minutes": 1440,
        },
    )

    assert policy.tenantid_id == tenant_id
    assert len(audits) == 1
    assert audits[0][2] == "admin.sla_policy.created"


def test_sla_deactivation_audits_and_noop_does_not(monkeypatch):
    tenant_id = uuid.uuid4()
    policy = make_policy(tenant_id)
    audits = []
    saved = []
    monkeypatch.setattr(sla_service.transaction, "atomic", lambda: nullcontext())
    monkeypatch.setattr(
        sla_service, "tenant_sla_policy", lambda *args, **kwargs: policy
    )
    monkeypatch.setattr(policy, "save", lambda **kwargs: saved.append(kwargs))
    monkeypatch.setattr(
        sla_service, "write_admin_audit", lambda *args: audits.append(args)
    )

    updated, changed = sla_service.update_sla_policy(
        tenant_id, uuid.uuid4(), policy.policyid, {"is_active": False}
    )
    noop, noop_changed = sla_service.update_sla_policy(
        tenant_id, uuid.uuid4(), policy.policyid, {"is_active": False}
    )

    assert updated.isactive is False
    assert changed is True
    assert noop is policy
    assert noop_changed is False
    assert len(audits) == 1
    assert audits[0][2] == "admin.sla_policy.deactivated"
    assert saved[0]["update_fields"] == ["isactive", "updatedat"]


def test_sla_schema_upgrade_is_additive_and_never_overwrites_values():
    upgrade = Path("db/upgrade-sprint3-sla-reports.sql").read_text(encoding="utf-8")
    create = Path("db/create-rt-database.sql").read_text(encoding="utf-8")

    assert Slapolicy._meta.managed is False
    assert "CREATE TABLE dbo.SlaPolicy" in create
    assert "Priority NVARCHAR(20)" in create
    assert "AppliesTo NVARCHAR(MAX) NULL" in create
    assert "Targets NVARCHAR(MAX) NULL" in create
    for values in (
        "(N''Low'', N''low'', 240, 4320)",
        "(N''Normal'', N''normal'', 120, 1440)",
        "(N''High'', N''high'', 30, 480)",
        "(N''Urgent'', N''urgent'', 15, 120)",
    ):
        assert values in upgrade
    assert "WHEN NOT MATCHED THEN" in upgrade
    assert "WHEN MATCHED" not in upgrade


def test_openapi_includes_sla_routes():
    response = Client().get("/api/schema")
    assert response.status_code == 200
    assert b"/api/admin/sla-policies/" in response.content
    assert b"/api/admin/sla-policies/{sla_policy_id}/" in response.content
