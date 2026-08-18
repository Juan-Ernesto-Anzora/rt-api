import uuid
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest
from django.test import Client
from django.urls import resolve
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.rt.models import Role
from apps.rt.services import admin_directory
from apps.rt.services.admin_directory import AdminDirectoryError
from apps.rt.services.admin_permissions import (
    ADMIN_ACCESS_PERMISSION,
    ADMIN_ROLES_PERMISSION,
)
from apps.rt.views import AdminRoleDetailView, AdminRoleListCreateView

EXACT_PERMISSION_CODES = {
    "admin.audit.read",
    "admin.permissions",
    "admin.read",
    "admin.roles",
    "admin.settings",
    "admin.users",
    "admin.workflows",
    "attachments.write",
    "comments.write",
    "featureflags.manage",
    "notifications.manage",
    "reports.export",
    "reports.read",
    "requests.read",
    "requests.transition",
    "requests.write",
    "sla.manage",
    "tenant.settings.manage",
}


class ExistsQuerySet:
    def __init__(self, exists):
        self._exists = exists

    def exists(self):
        return self._exists


def authenticated_request(path, tenant_id):
    request = APIRequestFactory().get(path)
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


def test_admin_role_permission_routes_resolve():
    role_id = uuid.uuid4()
    membership_id = uuid.uuid4()

    assert resolve("/api/admin/roles/").url_name == "admin-roles"
    assert resolve(f"/api/admin/roles/{role_id}/").url_name == "admin-role-detail"
    assert resolve("/api/admin/permissions/").url_name == "admin-permissions"
    assert (
        resolve(f"/api/admin/memberships/{membership_id}/roles/").url_name
        == "admin-membership-roles"
    )
    assert (
        resolve(f"/api/admin/roles/{role_id}/permissions/admin.read/").url_name
        == "admin-role-permission-detail"
    )


def test_role_endpoint_requires_admin_read_and_admin_roles(monkeypatch):
    monkeypatch.setattr(
        "apps.rt.views.get_admin_context",
        lambda request, required_permission: SimpleNamespace(
            user=SimpleNamespace(user_id=str(uuid.uuid4())),
            permissions=[ADMIN_ACCESS_PERMISSION],
        ),
    )

    response = AdminRoleListCreateView.as_view()(
        authenticated_request("/api/admin/roles/", uuid.uuid4())
    )

    assert response.status_code == 403
    assert response.data["code"] == "permission_denied"


def test_duplicate_tenant_role_name_is_rejected(monkeypatch):
    monkeypatch.setattr(
        "apps.rt.services.admin_directory.Role.objects.filter",
        lambda **kwargs: ExistsQuerySet(True),
    )

    with pytest.raises(AdminDirectoryError) as caught:
        admin_directory.create_role(
            uuid.uuid4(),
            uuid.uuid4(),
            {"name": "RT Agent", "description": "duplicate"},
        )

    assert caught.value.code == "conflict"
    assert caught.value.details[0]["field"] == "name"


def test_admin_role_cross_tenant_id_returns_404(monkeypatch):
    monkeypatch.setattr(
        "apps.rt.views.get_admin_context",
        lambda request, required_permission: SimpleNamespace(
            user=SimpleNamespace(user_id=str(uuid.uuid4())),
            permissions=[ADMIN_ACCESS_PERMISSION, ADMIN_ROLES_PERMISSION],
        ),
    )
    monkeypatch.setattr(
        "apps.rt.views.tenant_role",
        lambda tenant_id, role_id: (_ for _ in ()).throw(
            AdminDirectoryError("not_found", "Role not found for this tenant.", 404)
        ),
    )

    response = AdminRoleDetailView.as_view()(
        authenticated_request("/api/admin/roles/missing/", uuid.uuid4()),
        role_id=uuid.uuid4(),
    )

    assert response.status_code == 404
    assert response.data["code"] == "not_found"


def test_successful_role_create_is_transactional_and_audited(monkeypatch):
    tenant_id = uuid.uuid4()
    actor_id = uuid.uuid4()
    audits = []
    monkeypatch.setattr(admin_directory.transaction, "atomic", lambda: nullcontext())
    monkeypatch.setattr(
        "apps.rt.services.admin_directory.Role.objects.filter",
        lambda **kwargs: ExistsQuerySet(False),
    )

    def fake_create(**kwargs):
        return Role(**kwargs)

    monkeypatch.setattr(
        "apps.rt.services.admin_directory.Role.objects.create", fake_create
    )
    monkeypatch.setattr(
        admin_directory,
        "write_admin_audit",
        lambda *args: audits.append(args),
    )

    role = admin_directory.create_role(
        tenant_id, actor_id, {"name": "Escalation Lead", "description": "Leads"}
    )

    assert role.tenantid_id == tenant_id
    assert len(audits) == 1
    assert audits[0][2] == "admin.role.created"


def test_unknown_permission_returns_400_not_500(monkeypatch):
    role = Role(roleid=uuid.uuid4(), tenantid_id=uuid.uuid4(), name="RT Agent")
    monkeypatch.setattr(admin_directory.transaction, "atomic", lambda: nullcontext())
    monkeypatch.setattr(admin_directory, "tenant_role", lambda *args, **kwargs: role)
    monkeypatch.setattr(
        "apps.rt.services.admin_directory.Permission.objects.get",
        lambda **kwargs: (_ for _ in ()).throw(admin_directory.Permission.DoesNotExist),
    )

    with pytest.raises(AdminDirectoryError) as caught:
        admin_directory.assign_permission(
            role.tenantid_id, uuid.uuid4(), role.roleid, "unknown.permission"
        )

    assert caught.value.code == "validation_error"
    assert caught.value.status_code == 400
    assert caught.value.details[0]["field"] == "permission_code"


def test_seed_sql_is_additive_and_contains_exact_catalogue_and_roles():
    sql = Path("db/upgrade-sprint3-admin-users-roles.sql").read_text(encoding="utf-8")

    for permission_code in EXACT_PERMISSION_CODES:
        assert f"N'{permission_code}'" in sql
    for role_name in (
        "RT Admin",
        "RT Manager",
        "RT Agent",
        "RT Requester",
        "RT Viewer",
    ):
        assert f"N'{role_name}'" in sql
    assert "WHEN NOT MATCHED THEN" in sql
    assert "WHEN MATCHED" not in sql
    assert "WHEN NOT MATCHED BY SOURCE" not in sql


def test_openapi_schema_includes_all_admin_directory_paths():
    response = Client().get("/api/schema")

    assert response.status_code == 200
    for path in (
        b"/api/admin/roles/",
        b"/api/admin/permissions/",
        b"/api/admin/memberships/{membership_id}/roles/",
        b"/api/admin/roles/{role_id}/permissions/",
    ):
        assert path in response.content


def test_admin_roles_constant_does_not_introduce_admin_access():
    assert ADMIN_ROLES_PERMISSION == "admin.roles"
    assert ADMIN_ACCESS_PERMISSION == "admin.read"
    assert "admin.access" not in EXACT_PERMISSION_CODES
