import uuid
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from apps.rt.models import Membership, Membershiprole, Role, User
from apps.rt.services import admin_directory
from apps.rt.services.admin_directory import AdminDirectoryError


class ExistsQuerySet:
    def __init__(self, exists):
        self._exists = exists

    def exists(self):
        return self._exists


def make_user(is_active=True):
    return User(
        userid=uuid.uuid4(),
        email="agent@example.com",
        displayname="Agent",
        isactive=is_active,
    )


def make_membership(tenant_id, user):
    return Membership(
        membershipid=uuid.uuid4(),
        tenantid_id=tenant_id,
        userid=user,
        userid_id=user.userid,
        isdefaulttenant=False,
    )


def make_role(tenant_id, name="RT Agent"):
    return Role(roleid=uuid.uuid4(), tenantid_id=tenant_id, name=name)


def test_duplicate_membership_is_rejected_cleanly(monkeypatch):
    monkeypatch.setattr(
        "apps.rt.services.admin_directory.Membership.objects.filter",
        lambda **kwargs: ExistsQuerySet(True),
    )

    with pytest.raises(AdminDirectoryError) as caught:
        admin_directory.create_membership(
            uuid.uuid4(), uuid.uuid4(), make_user(), False
        )

    assert caught.value.code == "conflict"
    assert caught.value.status_code == 409
    assert caught.value.details[0]["field"] == "user_id"


def test_inactive_user_cannot_receive_membership():
    with pytest.raises(AdminDirectoryError) as caught:
        admin_directory.create_membership(
            uuid.uuid4(), uuid.uuid4(), make_user(is_active=False), False
        )

    assert caught.value.code == "inactive_user"
    assert caught.value.status_code == 400


def test_duplicate_role_assignment_is_rejected(monkeypatch):
    tenant_id = uuid.uuid4()
    membership = make_membership(tenant_id, make_user())
    role = make_role(tenant_id)
    monkeypatch.setattr(admin_directory.transaction, "atomic", lambda: nullcontext())
    monkeypatch.setattr(
        admin_directory, "tenant_membership", lambda *args, **kwargs: membership
    )
    monkeypatch.setattr(admin_directory, "tenant_role", lambda *args, **kwargs: role)
    monkeypatch.setattr(
        "apps.rt.services.admin_directory.Membershiprole.objects.filter",
        lambda **kwargs: ExistsQuerySet(True),
    )

    with pytest.raises(AdminDirectoryError) as caught:
        admin_directory.assign_role(
            tenant_id, uuid.uuid4(), membership.membershipid, role.roleid
        )

    assert caught.value.code == "conflict"
    assert caught.value.details[0]["field"] == "role_id"


def test_successful_role_assignment_writes_one_audit(monkeypatch):
    tenant_id = uuid.uuid4()
    actor_id = uuid.uuid4()
    membership = make_membership(tenant_id, make_user())
    role = make_role(tenant_id)
    audits = []
    monkeypatch.setattr(admin_directory.transaction, "atomic", lambda: nullcontext())
    monkeypatch.setattr(
        admin_directory, "tenant_membership", lambda *args, **kwargs: membership
    )
    monkeypatch.setattr(admin_directory, "tenant_role", lambda *args, **kwargs: role)
    monkeypatch.setattr(
        "apps.rt.services.admin_directory.Membershiprole.objects.filter",
        lambda **kwargs: ExistsQuerySet(False),
    )
    monkeypatch.setattr(
        "apps.rt.services.admin_directory.Membershiprole.objects.create",
        lambda **kwargs: SimpleNamespace(**kwargs),
    )
    monkeypatch.setattr(
        admin_directory,
        "write_admin_audit",
        lambda *args: audits.append(args),
    )

    link = admin_directory.assign_role(
        tenant_id, actor_id, membership.membershipid, role.roleid
    )

    assert isinstance(link, SimpleNamespace)
    assert len(audits) == 1
    assert audits[0][2] == "admin.membership.role_assigned"


def test_final_admin_removal_is_blocked(monkeypatch):
    tenant_id = uuid.uuid4()
    membership = make_membership(tenant_id, make_user())
    role = make_role(tenant_id, name="RT Admin")
    link = SimpleNamespace(delete=lambda: None)
    monkeypatch.setattr(admin_directory.transaction, "atomic", lambda: nullcontext())
    monkeypatch.setattr(
        admin_directory, "tenant_membership", lambda *args, **kwargs: membership
    )
    monkeypatch.setattr(admin_directory, "tenant_role", lambda *args, **kwargs: role)
    monkeypatch.setattr(
        "apps.rt.services.admin_directory.Membershiprole.objects.select_for_update",
        lambda: SimpleNamespace(
            filter=lambda **kwargs: SimpleNamespace(first=lambda: link)
        ),
    )
    monkeypatch.setattr(
        admin_directory,
        "ensure_admin_survives",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AdminDirectoryError(
                "admin_lockout", "The tenant must retain an admin.", 409
            )
        ),
    )

    with pytest.raises(AdminDirectoryError) as caught:
        admin_directory.remove_role(
            tenant_id, uuid.uuid4(), membership.membershipid, role.roleid
        )

    assert caught.value.code == "admin_lockout"
    assert caught.value.status_code == 409


def test_role_removal_uses_sql_server_safe_composite_delete(monkeypatch):
    tenant_id = uuid.uuid4()
    membership = make_membership(tenant_id, make_user())
    role = make_role(tenant_id, name="RT Agent")
    link = SimpleNamespace()
    deleted = []
    audits = []
    monkeypatch.setattr(admin_directory.transaction, "atomic", lambda: nullcontext())
    monkeypatch.setattr(
        admin_directory, "tenant_membership", lambda *args, **kwargs: membership
    )
    monkeypatch.setattr(admin_directory, "tenant_role", lambda *args, **kwargs: role)
    monkeypatch.setattr(
        "apps.rt.services.admin_directory.Membershiprole.objects.select_for_update",
        lambda: SimpleNamespace(
            filter=lambda **kwargs: SimpleNamespace(first=lambda: link)
        ),
    )
    monkeypatch.setattr(
        admin_directory,
        "delete_composite_link",
        lambda model, **filters: deleted.append((model, filters)),
    )
    monkeypatch.setattr(
        admin_directory, "write_admin_audit", lambda *args: audits.append(args)
    )

    admin_directory.remove_role(
        tenant_id, uuid.uuid4(), membership.membershipid, role.roleid
    )

    assert deleted[0][0] is Membershiprole
    assert deleted[0][1] == {
        "membershipid_id": membership.membershipid,
        "roleid_id": role.roleid,
    }
    assert audits[0][2] == "admin.membership.role_removed"


def test_membership_role_model_uses_composite_identity():
    field_names = {field.name for field in Membershiprole._meta.fields}

    assert {"membershipid", "roleid"}.issubset(field_names)
