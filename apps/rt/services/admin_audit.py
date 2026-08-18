import json
import uuid

from django.utils import timezone

from apps.rt.models import Activity


def write_admin_audit(tenant_id, actor_id, activity_type, payload):
    return Activity.objects.create(
        activityid=uuid.uuid4(),
        tenantid_id=tenant_id,
        requestid_id=None,
        actorid_id=actor_id,
        type=activity_type,
        payload=json.dumps(payload, default=str),
        createdat=timezone.now(),
    )
