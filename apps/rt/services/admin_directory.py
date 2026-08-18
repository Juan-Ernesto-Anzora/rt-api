import uuid

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.rt.models import (
    Membership,
    Membershiprole,
    Permission,
    Role,
    Rolepermission,
    User,
)
from apps.rt.services.admin_audit import write_admin_audit
from apps.rt.services.admin_permissions import ADMIN_ACCESS_PERMISSION

CANONICAL_ADMIN_ROLE = "RT Admin"
CANONICAL_ROLE_NAMES = {
    CANONICAL_ADMIN_ROLE,
    "RT Manager",
    "RT Agent",
    "RT Requester",
    "RT Viewer",
}


class AdminDirectoryError(Exception):
    def __init__(self, code, message, status_code=400, details=None):
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or []
        super().__init__(message)


def conflict(message, field=""):
    details = [{"field": field, "message": message}] if field else []
    return AdminDirectoryError("conflict", message, 409, details)


def not_found(resource):
    return AdminDirectoryError(
        "not_found", f"{resource} not found for this tenant.", 404
    )


def admin_lockout(message):
    return AdminDirectoryError("admin_lockout", message, 409)


def shared_user_conflict():
    return AdminDirectoryError(
        "shared_user_conflict",
        "This domain user belongs to another tenant and cannot be changed here.",
        409,
    )


def tenant_membership(tenant_id, membership_id, lock=False):
    queryset = Membership.objects
    if lock:
        queryset = queryset.select_for_update()
    try:
        return queryset.select_related("userid").get(
            membershipid=membership_id,
            tenantid_id=tenant_id,
        )
    except Membership.DoesNotExist as exc:
        raise not_found("Membership") from exc


def tenant_role(tenant_id, role_id, lock=False):
    queryset = Role.objects
    if lock:
        queryset = queryset.select_for_update()
    try:
        return queryset.get(roleid=role_id, tenantid_id=tenant_id)
    except Role.DoesNotExist as exc:
        raise not_found("Role") from exc


def tenant_user(tenant_id, user_id, lock=False):
    membership = Membership.objects
    if lock:
        membership = membership.select_for_update()
    try:
        link = membership.select_related("userid").get(
            tenantid_id=tenant_id,
            userid_id=user_id,
        )
    except Membership.DoesNotExist as exc:
        raise not_found("User") from exc
    return link.userid, link


def membership_roles(membership_id):
    return Role.objects.filter(membershiprole__membershipid_id=membership_id).order_by(
        "name"
    )


def role_permissions(role_id):
    return Permission.objects.filter(rolepermission__roleid_id=role_id).order_by("code")


def membership_is_effective_admin(
    membership,
    excluded_role_id=None,
    excluded_permission=None,
):
    if not membership.userid.isactive:
        return False
    role_ids = list(
        Membershiprole.objects.select_for_update()
        .filter(membershipid_id=membership.membershipid)
        .exclude(roleid_id=excluded_role_id)
        .values_list("roleid_id", flat=True)
    )
    if not role_ids:
        return False
    canonical_role_ids = set(
        Role.objects.filter(
            roleid__in=role_ids,
            tenantid_id=membership.tenantid_id,
            name=CANONICAL_ADMIN_ROLE,
        ).values_list("roleid", flat=True)
    )
    if not canonical_role_ids:
        return False
    links = Rolepermission.objects.select_for_update().filter(
        roleid_id__in=canonical_role_ids, permissioncode_id=ADMIN_ACCESS_PERMISSION
    )
    if excluded_permission:
        role_id, permission_code = excluded_permission
        links = links.exclude(
            roleid_id=role_id,
            permissioncode_id=permission_code,
        )
    return links.exists()


def ensure_admin_survives(
    tenant_id,
    actor_user_id,
    excluded_membership_id=None,
    excluded_role=None,
    excluded_permission=None,
    deactivated_user_id=None,
):
    memberships = list(
        Membership.objects.select_for_update()
        .filter(tenantid_id=tenant_id)
        .select_related("userid")
    )

    def remains_admin(membership):
        if membership.membershipid == excluded_membership_id:
            return False
        if membership.userid_id == deactivated_user_id:
            return False
        ignored_role = None
        if excluded_role and membership.membershipid == excluded_role[0]:
            ignored_role = excluded_role[1]
        return membership_is_effective_admin(
            membership,
            excluded_role_id=ignored_role,
            excluded_permission=excluded_permission,
        )

    actor_memberships = [
        membership
        for membership in memberships
        if str(membership.userid_id).lower() == str(actor_user_id).lower()
    ]
    if actor_memberships and not any(remains_admin(item) for item in actor_memberships):
        raise admin_lockout("You cannot remove your own final admin access.")
    if not any(remains_admin(item) for item in memberships):
        raise admin_lockout("The tenant must retain at least one active RT Admin.")


def create_user_with_membership(tenant_id, actor_id, data):
    if User.objects.filter(email__iexact=data["email"]).exists():
        raise conflict("A domain user with this email already exists.", "email")
    now = timezone.now()
    try:
        with transaction.atomic():
            user = User.objects.create(
                userid=uuid.uuid4(),
                email=data["email"],
                displayname=data["display_name"],
                employeecode=data.get("employee_code"),
                avatarurl=data.get("avatar_url"),
                isactive=True,
                createdat=now,
                updatedat=None,
            )
            membership = Membership.objects.create(
                membershipid=uuid.uuid4(),
                tenantid_id=tenant_id,
                userid=user,
                isdefaulttenant=data.get("is_default_tenant", False),
                createdat=now,
            )
            write_admin_audit(
                tenant_id,
                actor_id,
                "admin.user.created",
                {"user_id": user.userid, "membership_id": membership.membershipid},
            )
    except IntegrityError as exc:
        raise conflict(
            "A domain user with this email already exists.", "email"
        ) from exc
    return user, membership


def update_user(tenant_id, actor_id, user_id, data):
    try:
        with transaction.atomic():
            user, membership = tenant_user(tenant_id, user_id, lock=True)
            if (
                Membership.objects.filter(userid_id=user.userid)
                .exclude(tenantid_id=tenant_id)
                .exists()
            ):
                raise shared_user_conflict()
            changed_fields = []
            field_map = {
                "email": "email",
                "display_name": "displayname",
                "employee_code": "employeecode",
                "avatar_url": "avatarurl",
                "is_active": "isactive",
            }
            for public_field, model_field in field_map.items():
                if (
                    public_field in data
                    and getattr(user, model_field) != data[public_field]
                ):
                    setattr(user, model_field, data[public_field])
                    changed_fields.append(model_field)
            if not changed_fields:
                return user
            if "isactive" in changed_fields and not user.isactive:
                ensure_admin_survives(
                    tenant_id,
                    actor_id,
                    deactivated_user_id=user.userid,
                )
            user.updatedat = timezone.now()
            changed_fields.append("updatedat")
            user.save(update_fields=changed_fields)
            activity_type = (
                "admin.user.deactivated"
                if "isactive" in changed_fields and not user.isactive
                else "admin.user.updated"
            )
            write_admin_audit(
                tenant_id,
                actor_id,
                activity_type,
                {
                    "user_id": user.userid,
                    "membership_id": membership.membershipid,
                    "changed_fields": changed_fields,
                },
            )
            return user
    except IntegrityError as exc:
        raise conflict(
            "A domain user with this email already exists.", "email"
        ) from exc


def create_membership(tenant_id, actor_id, user, is_default_tenant=False):
    if not user.isactive:
        raise AdminDirectoryError(
            "inactive_user", "Inactive users cannot receive a membership.", 400
        )
    if Membership.objects.filter(tenantid_id=tenant_id, userid_id=user.userid).exists():
        raise conflict("This user is already a member of the tenant.", "user_id")
    try:
        with transaction.atomic():
            membership = Membership.objects.create(
                membershipid=uuid.uuid4(),
                tenantid_id=tenant_id,
                userid=user,
                isdefaulttenant=is_default_tenant,
                createdat=timezone.now(),
            )
            if is_default_tenant:
                Membership.objects.filter(userid_id=user.userid).exclude(
                    membershipid=membership.membershipid
                ).update(isdefaulttenant=False)
            write_admin_audit(
                tenant_id,
                actor_id,
                "admin.membership.created",
                {"membership_id": membership.membershipid, "user_id": user.userid},
            )
            return membership
    except IntegrityError as exc:
        raise conflict(
            "This user is already a member of the tenant.", "user_id"
        ) from exc


def update_membership(tenant_id, actor_id, membership_id, is_default_tenant):
    with transaction.atomic():
        membership = tenant_membership(tenant_id, membership_id, lock=True)
        if membership.isdefaulttenant == is_default_tenant:
            return membership
        if is_default_tenant:
            Membership.objects.filter(userid_id=membership.userid_id).exclude(
                membershipid=membership.membershipid
            ).update(isdefaulttenant=False)
        elif (
            not Membership.objects.filter(
                userid_id=membership.userid_id, isdefaulttenant=True
            )
            .exclude(membershipid=membership.membershipid)
            .exists()
        ):
            raise AdminDirectoryError(
                "default_tenant_required",
                "Select another default tenant before clearing this one.",
                409,
            )
        membership.isdefaulttenant = is_default_tenant
        membership.save(update_fields=["isdefaulttenant"])
        write_admin_audit(
            tenant_id,
            actor_id,
            "admin.membership.updated",
            {
                "membership_id": membership.membershipid,
                "is_default_tenant": is_default_tenant,
            },
        )
        return membership


def remove_membership(tenant_id, actor_id, membership_id):
    with transaction.atomic():
        membership = tenant_membership(tenant_id, membership_id, lock=True)
        if (
            membership.isdefaulttenant
            and Membership.objects.filter(userid_id=membership.userid_id)
            .exclude(membershipid=membership.membershipid)
            .exists()
        ):
            raise AdminDirectoryError(
                "default_tenant_required",
                "Select another default tenant before removing this membership.",
                409,
            )
        ensure_admin_survives(
            tenant_id,
            actor_id,
            excluded_membership_id=membership.membershipid,
        )
        payload = {
            "membership_id": membership.membershipid,
            "user_id": membership.userid_id,
        }
        membership.delete()
        write_admin_audit(tenant_id, actor_id, "admin.membership.removed", payload)


def create_role(tenant_id, actor_id, data):
    if Role.objects.filter(tenantid_id=tenant_id, name__iexact=data["name"]).exists():
        raise conflict("A role with this name already exists.", "name")
    try:
        with transaction.atomic():
            role = Role.objects.create(
                roleid=uuid.uuid4(),
                tenantid_id=tenant_id,
                name=data["name"],
                description=data.get("description"),
                createdat=timezone.now(),
            )
            write_admin_audit(
                tenant_id,
                actor_id,
                "admin.role.created",
                {"role_id": role.roleid, "name": role.name},
            )
            return role
    except IntegrityError as exc:
        raise conflict("A role with this name already exists.", "name") from exc


def update_role(tenant_id, actor_id, role_id, data):
    try:
        with transaction.atomic():
            role = tenant_role(tenant_id, role_id, lock=True)
            if (
                role.name in CANONICAL_ROLE_NAMES
                and data.get("name", role.name) != role.name
            ):
                raise AdminDirectoryError(
                    "canonical_role",
                    "Canonical role names cannot be changed.",
                    409,
                )
            changed_fields = []
            for field in ("name", "description"):
                if field in data and getattr(role, field) != data[field]:
                    setattr(role, field, data[field])
                    changed_fields.append(field)
            if changed_fields:
                role.save(update_fields=changed_fields)
                write_admin_audit(
                    tenant_id,
                    actor_id,
                    "admin.role.updated",
                    {"role_id": role.roleid, "changed_fields": changed_fields},
                )
            return role
    except IntegrityError as exc:
        raise conflict("A role with this name already exists.", "name") from exc


def assign_role(tenant_id, actor_id, membership_id, role_id):
    try:
        with transaction.atomic():
            membership = tenant_membership(tenant_id, membership_id, lock=True)
            role = tenant_role(tenant_id, role_id, lock=True)
            if not membership.userid.isactive:
                raise AdminDirectoryError(
                    "inactive_user", "Inactive users cannot receive a role.", 400
                )
            if Membershiprole.objects.filter(
                membershipid_id=membership.membershipid, roleid_id=role.roleid
            ).exists():
                raise conflict("This role is already assigned.", "role_id")
            link = Membershiprole.objects.create(
                membershipid=membership,
                roleid=role,
            )
            write_admin_audit(
                tenant_id,
                actor_id,
                "admin.membership.role_assigned",
                {"membership_id": membership.membershipid, "role_id": role.roleid},
            )
            return link
    except IntegrityError as exc:
        raise conflict("This role is already assigned.", "role_id") from exc


def remove_role(tenant_id, actor_id, membership_id, role_id):
    with transaction.atomic():
        membership = tenant_membership(tenant_id, membership_id, lock=True)
        role = tenant_role(tenant_id, role_id, lock=True)
        link = (
            Membershiprole.objects.select_for_update()
            .filter(
                membershipid_id=membership.membershipid,
                roleid_id=role.roleid,
            )
            .first()
        )
        if not link:
            raise not_found("Role assignment")
        if role.name == CANONICAL_ADMIN_ROLE:
            ensure_admin_survives(
                tenant_id,
                actor_id,
                excluded_role=(membership.membershipid, role.roleid),
            )
        link.delete()
        write_admin_audit(
            tenant_id,
            actor_id,
            "admin.membership.role_removed",
            {"membership_id": membership.membershipid, "role_id": role.roleid},
        )


def assign_permission(tenant_id, actor_id, role_id, permission_code):
    try:
        with transaction.atomic():
            role = tenant_role(tenant_id, role_id, lock=True)
            try:
                permission = Permission.objects.get(code=permission_code)
            except Permission.DoesNotExist as exc:
                raise AdminDirectoryError(
                    "validation_error",
                    "Unknown permission code.",
                    400,
                    [{"field": "permission_code", "message": "Unknown permission."}],
                ) from exc
            if Rolepermission.objects.filter(
                roleid_id=role.roleid, permissioncode_id=permission.code
            ).exists():
                raise conflict(
                    "This permission is already assigned.", "permission_code"
                )
            link = Rolepermission.objects.create(
                roleid=role,
                permissioncode=permission,
            )
            write_admin_audit(
                tenant_id,
                actor_id,
                "admin.role.permission_assigned",
                {"role_id": role.roleid, "permission_code": permission.code},
            )
            return link
    except IntegrityError as exc:
        raise conflict(
            "This permission is already assigned.", "permission_code"
        ) from exc


def remove_permission(tenant_id, actor_id, role_id, permission_code):
    with transaction.atomic():
        role = tenant_role(tenant_id, role_id, lock=True)
        link = (
            Rolepermission.objects.select_for_update()
            .filter(
                roleid_id=role.roleid,
                permissioncode_id=permission_code,
            )
            .first()
        )
        if not link:
            raise not_found("Permission assignment")
        if (
            role.name == CANONICAL_ADMIN_ROLE
            and permission_code == ADMIN_ACCESS_PERMISSION
        ):
            ensure_admin_survives(
                tenant_id,
                actor_id,
                excluded_permission=(role.roleid, permission_code),
            )
        link.delete()
        write_admin_audit(
            tenant_id,
            actor_id,
            "admin.role.permission_removed",
            {"role_id": role.roleid, "permission_code": permission_code},
        )
