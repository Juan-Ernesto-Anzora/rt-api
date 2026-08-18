import uuid
from types import SimpleNamespace

from django.test import Client
from django.urls import resolve
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.rt.models import Membership, User
from apps.rt.services.admin_directory import AdminDirectoryError
from apps.rt.services.admin_permissions import (
    ADMIN_ACCESS_PERMISSION,
    ADMIN_USERS_PERMISSION,
)
from apps.rt.views import (
    AdminMembershipListCreateView,
    AdminUserDetailView,
    AdminUserListCreateView,
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


def admin_context(*permissions):
    return SimpleNamespace(
        user=SimpleNamespace(user_id=str(uuid.uuid4())),
        permissions=list(permissions),
    )


def make_user():
    now = timezone.now()
    return User(
        userid=uuid.uuid4(),
        email="agent@example.com",
        displayname="Example Agent",
        employeecode="A-100",
        avatarurl=None,
        isactive=True,
        createdat=now,
        updatedat=now,
    )


def make_membership(user, tenant_id):
    return Membership(
        membershipid=uuid.uuid4(),
        tenantid_id=tenant_id,
        userid=user,
        userid_id=user.userid,
        isdefaulttenant=False,
        createdat=timezone.now(),
    )


def test_admin_user_and_membership_routes_resolve():
    user_id = uuid.uuid4()
    membership_id = uuid.uuid4()

    assert resolve("/api/admin/users/").url_name == "admin-users"
    assert resolve(f"/api/admin/users/{user_id}/").url_name == "admin-user-detail"
    assert resolve("/api/admin/memberships/").url_name == "admin-memberships"
    assert (
        resolve(f"/api/admin/memberships/{membership_id}/").url_name
        == "admin-membership-detail"
    )


def test_admin_user_create_returns_only_public_fields(monkeypatch):
    tenant_id = uuid.uuid4()
    user = make_user()
    membership = make_membership(user, tenant_id)
    monkeypatch.setattr(
        "apps.rt.views.get_admin_context",
        lambda request, required_permission: admin_context(
            ADMIN_ACCESS_PERMISSION, ADMIN_USERS_PERMISSION
        ),
    )
    monkeypatch.setattr(
        "apps.rt.views.create_user_with_membership",
        lambda tenant_id, actor_id, data: (user, membership),
    )
    monkeypatch.setattr(
        "apps.rt.services.admin_directory.membership_roles", lambda membership_id: []
    )

    response = AdminUserListCreateView.as_view()(
        authenticated_request(
            "post",
            "/api/admin/users/",
            tenant_id,
            {"email": user.email, "display_name": user.displayname},
        )
    )

    assert response.status_code == 201
    assert response.data["user"]["user_id"] == str(user.userid)
    assert response.data["user"]["display_name"] == user.displayname
    assert response.data["membership"]["tenant_id"] == str(tenant_id)
    assert "userid" not in response.data["user"]
    assert "membershipid" not in response.data["membership"]


def test_admin_user_requires_specific_permission(monkeypatch):
    monkeypatch.setattr(
        "apps.rt.views.get_admin_context",
        lambda request, required_permission: admin_context(ADMIN_ACCESS_PERMISSION),
    )

    response = AdminUserListCreateView.as_view()(
        authenticated_request("get", "/api/admin/users/", uuid.uuid4())
    )

    assert response.status_code == 403
    assert response.data["code"] == "permission_denied"


def test_admin_user_endpoint_requires_jwt():
    request = APIRequestFactory().get("/api/admin/users/")
    request.tenant_id = uuid.uuid4()

    response = AdminUserListCreateView.as_view()(request)

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_admin_user_endpoint_requires_tenant():
    request = APIRequestFactory().get("/api/admin/users/")
    force_authenticate(
        request,
        user=SimpleNamespace(
            is_authenticated=True,
            email="admin@example.com",
            username="admin@example.com",
        ),
    )

    response = AdminUserListCreateView.as_view()(request)

    assert response.status_code == 400
    assert response.data["code"] == "tenant_required"


def test_admin_user_cross_tenant_id_returns_404(monkeypatch):
    monkeypatch.setattr(
        "apps.rt.views.get_admin_context",
        lambda request, required_permission: admin_context(
            ADMIN_ACCESS_PERMISSION, ADMIN_USERS_PERMISSION
        ),
    )
    monkeypatch.setattr(
        "apps.rt.views.tenant_user",
        lambda tenant_id, user_id: (_ for _ in ()).throw(
            AdminDirectoryError("not_found", "User not found for this tenant.", 404)
        ),
    )

    response = AdminUserDetailView.as_view()(
        authenticated_request("get", "/api/admin/users/missing/", uuid.uuid4()),
        user_id=uuid.uuid4(),
    )

    assert response.status_code == 404
    assert response.data["code"] == "not_found"


def test_membership_invalid_user_uuid_returns_400(monkeypatch):
    monkeypatch.setattr(
        "apps.rt.views.get_admin_context",
        lambda request, required_permission: admin_context(
            ADMIN_ACCESS_PERMISSION, ADMIN_USERS_PERMISSION
        ),
    )

    response = AdminMembershipListCreateView.as_view()(
        authenticated_request(
            "post",
            "/api/admin/memberships/",
            uuid.uuid4(),
            {"user_id": "not-a-uuid"},
        )
    )

    assert response.status_code == 400
    assert response.data["code"] == "validation_error"
    assert response.data["details"][0]["field"] == "user_id"


def test_shared_user_update_returns_clean_conflict(monkeypatch):
    monkeypatch.setattr(
        "apps.rt.views.get_admin_context",
        lambda request, required_permission: admin_context(
            ADMIN_ACCESS_PERMISSION, ADMIN_USERS_PERMISSION
        ),
    )
    monkeypatch.setattr(
        "apps.rt.views.update_user",
        lambda *args: (_ for _ in ()).throw(
            AdminDirectoryError(
                "shared_user_conflict", "Shared user cannot be changed.", 409
            )
        ),
    )

    response = AdminUserDetailView.as_view()(
        authenticated_request(
            "patch",
            "/api/admin/users/user/",
            uuid.uuid4(),
            {"display_name": "Changed"},
        ),
        user_id=uuid.uuid4(),
    )

    assert response.status_code == 409
    assert response.data["code"] == "shared_user_conflict"


def test_openapi_schema_includes_admin_user_paths():
    response = Client().get("/api/schema")

    assert response.status_code == 200
    assert b"/api/admin/users/" in response.content
    assert b"/api/admin/memberships/" in response.content
