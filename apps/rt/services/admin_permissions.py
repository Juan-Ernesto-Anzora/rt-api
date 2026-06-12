from dataclasses import dataclass

from apps.rt.models import Membership, Membershiprole, Rolepermission, User

ADMIN_ACCESS_PERMISSION = "admin.read"
ADMIN_AUDIT_READ_PERMISSION = "admin.audit.read"


class AdminPermissionError(Exception):
    def __init__(self, code, message, status_code=403):
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


@dataclass(frozen=True)
class AdminUserContext:
    user_id: str
    display_name: str
    email: str


@dataclass(frozen=True)
class AdminContext:
    tenant_id: str
    user: AdminUserContext
    roles: list[str]
    permissions: list[str]

    @property
    def is_admin(self):
        return ADMIN_ACCESS_PERMISSION in self.permissions

    @property
    def can_read_audit(self):
        return ADMIN_AUDIT_READ_PERMISSION in self.permissions


def get_admin_context(request, required_permission=ADMIN_ACCESS_PERMISSION):
    tenant_id = getattr(request, "tenant_id", None)
    if not tenant_id:
        raise AdminPermissionError(
            code="tenant_required",
            message="Tenant context missing.",
            status_code=400,
        )

    rt_user = resolve_request_user(getattr(request, "user", None))
    try:
        membership = Membership.objects.get(
            userid_id=rt_user.userid,
            tenantid_id=tenant_id,
        )
    except Membership.DoesNotExist as exc:
        raise permission_denied() from exc

    roles, permissions = resolve_membership_permissions(membership)
    context = AdminContext(
        tenant_id=str(tenant_id),
        user=AdminUserContext(
            user_id=str(rt_user.userid),
            display_name=rt_user.displayname,
            email=rt_user.email,
        ),
        roles=roles,
        permissions=permissions,
    )
    if required_permission and required_permission not in permissions:
        raise permission_denied()
    return context


def resolve_request_user(auth_user):
    if not auth_user or not getattr(auth_user, "is_authenticated", False):
        raise permission_denied()

    email = (getattr(auth_user, "email", "") or "").strip()
    username = (getattr(auth_user, "username", "") or "").strip()
    lookup_email = email or (username if "@" in username else "")
    if not lookup_email:
        raise permission_denied()

    try:
        return User.objects.get(email__iexact=lookup_email)
    except User.DoesNotExist as exc:
        raise permission_denied() from exc


def resolve_membership_permissions(membership):
    role_links = Membershiprole.objects.filter(
        membershipid_id=membership.membershipid
    ).select_related("roleid")
    role_names = sorted({link.roleid.name for link in role_links})
    role_ids = [link.roleid_id for link in role_links]

    if not role_ids:
        return role_names, []

    permission_links = Rolepermission.objects.filter(
        roleid_id__in=role_ids
    ).select_related("permissioncode")
    permission_codes = sorted({link.permissioncode_id for link in permission_links})
    return role_names, permission_codes


def permission_denied():
    return AdminPermissionError(
        code="permission_denied",
        message="You do not have permission to access this admin resource.",
        status_code=403,
    )
