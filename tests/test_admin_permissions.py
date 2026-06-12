import uuid
from types import SimpleNamespace

from django.contrib.auth.models import AnonymousUser
from django.test import Client
from django.urls import resolve
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.rt.models import Membership, Permission, Role, Tenant, User
from apps.rt.services.admin_permissions import (
    ADMIN_ACCESS_PERMISSION,
    ADMIN_AUDIT_READ_PERMISSION,
    AdminPermissionError,
    get_admin_context,
)
from apps.rt.views import AdminPermissionsView


class FakeLinkQuerySet:
    def __init__(self, items):
        self.items = items
        self.select_related_args = None

    def select_related(self, *fields):
        self.select_related_args = fields
        return self

    def __iter__(self):
        return iter(self.items)


def build_admin_objects():
    tenant = Tenant(tenantid=uuid.uuid4(), code="ACME", name="ACME")
    user = User(
        userid=uuid.uuid4(),
        email="admin@example.com",
        displayname="Admin User",
        isactive=True,
    )
    membership = Membership(
        membershipid=uuid.uuid4(),
        tenantid=tenant,
        userid=user,
        isdefaulttenant=True,
    )
    role = Role(
        roleid=uuid.uuid4(),
        tenantid=tenant,
        name="Tenant Admin",
        description="Can administer tenant.",
    )
    return tenant, user, membership, role


def patch_admin_context_lookups(
    monkeypatch,
    tenant,
    user,
    membership,
    role,
    permissions=None,
    user_exists=True,
    membership_exists=True,
):
    permissions = permissions or [ADMIN_ACCESS_PERMISSION, ADMIN_AUDIT_READ_PERMISSION]
    captured = {
        "user": None,
        "membership": None,
        "role_links": None,
        "permissions": None,
    }

    def user_get(**kwargs):
        captured["user"] = kwargs
        if not user_exists:
            raise User.DoesNotExist
        return user

    def membership_get(**kwargs):
        captured["membership"] = kwargs
        if not membership_exists:
            raise Membership.DoesNotExist
        return membership

    def membership_role_filter(**kwargs):
        captured["role_links"] = kwargs
        return FakeLinkQuerySet([SimpleNamespace(roleid=role, roleid_id=role.roleid)])

    def role_permission_filter(**kwargs):
        captured["permissions"] = kwargs
        return FakeLinkQuerySet(
            [
                SimpleNamespace(
                    permissioncode=Permission(code=permission),
                    permissioncode_id=permission,
                )
                for permission in permissions
            ]
        )

    monkeypatch.setattr("apps.rt.services.admin_permissions.User.objects.get", user_get)
    monkeypatch.setattr(
        "apps.rt.services.admin_permissions.Membership.objects.get", membership_get
    )
    monkeypatch.setattr(
        "apps.rt.services.admin_permissions.Membershiprole.objects.filter",
        membership_role_filter,
    )
    monkeypatch.setattr(
        "apps.rt.services.admin_permissions.Rolepermission.objects.filter",
        role_permission_filter,
    )
    return captured


def test_admin_routes_resolve():
    assert resolve("/api/admin/me/permissions/").url_name == "admin-me-permissions"
    assert resolve("/api/admin/audit/").url_name == "admin-audit"


def test_admin_context_resolves_roles_and_permissions(monkeypatch):
    tenant, user, membership, role = build_admin_objects()
    captured = patch_admin_context_lookups(monkeypatch, tenant, user, membership, role)
    request = SimpleNamespace(
        tenant_id=tenant.tenantid,
        user=SimpleNamespace(
            is_authenticated=True,
            email="admin@example.com",
            username="admin",
        ),
    )

    context = get_admin_context(request, required_permission=ADMIN_ACCESS_PERMISSION)

    assert context.tenant_id == str(tenant.tenantid)
    assert context.user.user_id == str(user.userid)
    assert context.user.display_name == "Admin User"
    assert context.roles == ["Tenant Admin"]
    assert context.permissions == sorted(
        [ADMIN_ACCESS_PERMISSION, ADMIN_AUDIT_READ_PERMISSION]
    )
    assert context.is_admin is True
    assert context.can_read_audit is True
    assert captured["user"] == {"email__iexact": "admin@example.com"}
    assert captured["membership"] == {
        "userid_id": user.userid,
        "tenantid_id": tenant.tenantid,
    }
    assert captured["role_links"] == {"membershipid_id": membership.membershipid}
    assert captured["permissions"] == {"roleid_id__in": [role.roleid]}


def test_admin_context_denies_unmapped_user(monkeypatch):
    tenant, user, membership, role = build_admin_objects()
    patch_admin_context_lookups(
        monkeypatch,
        tenant,
        user,
        membership,
        role,
        user_exists=False,
    )
    request = SimpleNamespace(
        tenant_id=tenant.tenantid,
        user=SimpleNamespace(
            is_authenticated=True,
            email="missing@example.com",
            username="missing",
        ),
    )

    try:
        get_admin_context(request, required_permission=ADMIN_ACCESS_PERMISSION)
    except AdminPermissionError as exc:
        assert exc.code == "permission_denied"
        assert exc.status_code == 403
    else:
        raise AssertionError("Expected AdminPermissionError")


def test_admin_context_denies_user_without_tenant_membership(monkeypatch):
    tenant, user, membership, role = build_admin_objects()
    patch_admin_context_lookups(
        monkeypatch,
        tenant,
        user,
        membership,
        role,
        membership_exists=False,
    )
    request = SimpleNamespace(
        tenant_id=tenant.tenantid,
        user=SimpleNamespace(
            is_authenticated=True,
            email="admin@example.com",
            username="admin",
        ),
    )

    try:
        get_admin_context(request, required_permission=ADMIN_ACCESS_PERMISSION)
    except AdminPermissionError as exc:
        assert exc.code == "permission_denied"
    else:
        raise AssertionError("Expected AdminPermissionError")


def test_admin_context_denies_missing_required_permission(monkeypatch):
    tenant, user, membership, role = build_admin_objects()
    patch_admin_context_lookups(
        monkeypatch,
        tenant,
        user,
        membership,
        role,
        permissions=[ADMIN_ACCESS_PERMISSION],
    )
    request = SimpleNamespace(
        tenant_id=tenant.tenantid,
        user=SimpleNamespace(
            is_authenticated=True,
            email="admin@example.com",
            username="admin",
        ),
    )

    try:
        get_admin_context(request, required_permission=ADMIN_AUDIT_READ_PERMISSION)
    except AdminPermissionError as exc:
        assert exc.code == "permission_denied"
    else:
        raise AssertionError("Expected AdminPermissionError")


def test_admin_permissions_endpoint_returns_public_fields(monkeypatch):
    tenant, user, membership, role = build_admin_objects()
    patch_admin_context_lookups(monkeypatch, tenant, user, membership, role)
    auth_user = SimpleNamespace(
        is_authenticated=True,
        email="admin@example.com",
        username="admin",
    )
    request = APIRequestFactory().get("/api/admin/me/permissions/")
    request.tenant_id = tenant.tenantid
    force_authenticate(request, user=auth_user)

    response = AdminPermissionsView.as_view()(request)

    assert response.status_code == 200
    assert response.data == {
        "tenant_id": str(tenant.tenantid),
        "user": {
            "user_id": str(user.userid),
            "display_name": "Admin User",
            "email": "admin@example.com",
        },
        "roles": ["Tenant Admin"],
        "permissions": sorted([ADMIN_ACCESS_PERMISSION, ADMIN_AUDIT_READ_PERMISSION]),
        "is_admin": True,
        "can_read_audit": True,
    }
    assert "userid" not in response.data["user"]


def test_admin_permissions_endpoint_requires_auth():
    request = APIRequestFactory().get("/api/admin/me/permissions/")
    request.tenant_id = uuid.uuid4()
    force_authenticate(request, user=AnonymousUser())

    response = AdminPermissionsView.as_view()(request)

    assert response.status_code in {401, 403}


def test_admin_permissions_endpoint_missing_tenant_returns_json(monkeypatch):
    request = APIRequestFactory().get("/api/admin/me/permissions/")
    force_authenticate(
        request,
        user=SimpleNamespace(
            is_authenticated=True,
            email="admin@example.com",
            username="admin",
        ),
    )

    response = AdminPermissionsView.as_view()(request)

    assert response.status_code == 400
    assert response.data == {
        "code": "tenant_required",
        "message": "Tenant context missing.",
        "details": [],
    }


def test_admin_permissions_endpoint_denies_missing_access_permission(monkeypatch):
    tenant, user, membership, role = build_admin_objects()
    patch_admin_context_lookups(
        monkeypatch,
        tenant,
        user,
        membership,
        role,
        permissions=[ADMIN_AUDIT_READ_PERMISSION],
    )
    request = APIRequestFactory().get("/api/admin/me/permissions/")
    request.tenant_id = tenant.tenantid
    force_authenticate(
        request,
        user=SimpleNamespace(
            is_authenticated=True,
            email="admin@example.com",
            username="admin",
        ),
    )

    response = AdminPermissionsView.as_view()(request)

    assert response.status_code == 403
    assert response.data["code"] == "permission_denied"


def test_openapi_schema_includes_admin_permission_path():
    response = Client().get("/api/schema")

    assert response.status_code == 200
    assert b"/api/admin/me/permissions/" in response.content
