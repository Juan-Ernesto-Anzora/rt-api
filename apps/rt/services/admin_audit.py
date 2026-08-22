import json
import uuid

from django.utils import timezone

from apps.rt.models import Activity


def write_admin_audit(tenant_id, actor_id, activity_type, payload):
    payload = dict(payload)
    entity_type, entity_id = infer_entity(activity_type, payload)
    if entity_type and entity_id:
        payload.setdefault("entity_type", entity_type)
        payload.setdefault("entity_id", str(entity_id))
    return Activity.objects.create(
        activityid=uuid.uuid4(),
        tenantid_id=tenant_id,
        requestid_id=None,
        actorid_id=actor_id,
        type=activity_type,
        payload=json.dumps(payload, default=str),
        createdat=timezone.now(),
    )


def infer_entity(activity_type, payload):
    candidates = [
        ("notification_template", "notification_template_id"),
        ("sla_policy", "sla_policy_id"),
        ("transition", "transition_id"),
        ("status", "status_id"),
        ("workflow", "flow_id"),
        ("membership", "membership_id"),
        ("role", "role_id"),
        ("user", "user_id"),
    ]
    for entity_type, key in candidates:
        if payload.get(key):
            return entity_type, payload[key]
    return None, None
