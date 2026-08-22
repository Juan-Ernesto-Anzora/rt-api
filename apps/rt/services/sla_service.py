import uuid

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.rt.models import Slapolicy
from apps.rt.services.admin_audit import write_admin_audit
from apps.rt.services.admin_directory import AdminDirectoryError, conflict


def tenant_sla_policy(tenant_id, policy_id, lock=False):
    queryset = Slapolicy.objects
    if lock:
        queryset = queryset.select_for_update()
    try:
        return queryset.get(policyid=policy_id, tenantid_id=tenant_id)
    except Slapolicy.DoesNotExist as exc:
        raise AdminDirectoryError(
            "not_found", "SLA policy not found for this tenant.", 404
        ) from exc


def create_sla_policy(tenant_id, actor_id, data):
    if Slapolicy.objects.filter(
        tenantid_id=tenant_id, name__iexact=data["name"]
    ).exists():
        raise conflict("An SLA policy with this name already exists.", "name")

    now = timezone.now()
    try:
        with transaction.atomic():
            policy = Slapolicy.objects.create(
                policyid=uuid.uuid4(),
                tenantid_id=tenant_id,
                name=data["name"],
                priority=data["priority"],
                responseminutes=data["response_minutes"],
                resolutionminutes=data["resolution_minutes"],
                isactive=data.get("is_active", True),
                appliesto=None,
                targets=None,
                createdat=now,
                updatedat=None,
            )
            write_admin_audit(
                tenant_id,
                actor_id,
                "admin.sla_policy.created",
                {
                    "sla_policy_id": policy.policyid,
                    "name": policy.name,
                    "priority": policy.priority,
                },
            )
            return policy
    except IntegrityError as exc:
        raise conflict("An SLA policy with this name already exists.", "name") from exc


def update_sla_policy(tenant_id, actor_id, policy_id, data):
    try:
        with transaction.atomic():
            policy = tenant_sla_policy(tenant_id, policy_id, lock=True)
            field_map = {
                "name": "name",
                "priority": "priority",
                "response_minutes": "responseminutes",
                "resolution_minutes": "resolutionminutes",
                "is_active": "isactive",
            }
            changed_fields = []
            was_active = policy.isactive
            for public_field, model_field in field_map.items():
                if (
                    public_field in data
                    and getattr(policy, model_field) != data[public_field]
                ):
                    setattr(policy, model_field, data[public_field])
                    changed_fields.append(model_field)

            if not changed_fields:
                return policy, False

            policy.updatedat = timezone.now()
            policy.save(update_fields=[*changed_fields, "updatedat"])
            activity_type = (
                "admin.sla_policy.deactivated"
                if was_active and not policy.isactive
                else "admin.sla_policy.updated"
            )
            write_admin_audit(
                tenant_id,
                actor_id,
                activity_type,
                {
                    "sla_policy_id": policy.policyid,
                    "priority": policy.priority,
                    "changed_fields": changed_fields,
                },
            )
            return policy, True
    except IntegrityError as exc:
        raise conflict("An SLA policy with this name already exists.", "name") from exc
