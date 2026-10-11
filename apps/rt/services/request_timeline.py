import json
import logging
import uuid
from datetime import timezone as dt_timezone

from django.db import DatabaseError, connection
from django.db.models import Q
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import APIException

from apps.rt.models import Activity, Attachment, Comment, Status
from apps.rt.serializers import (
    StatusSummarySerializer,
    UserLookupSerializer,
    WorkspaceAttachmentSerializer,
)

LINKED_TYPES = "'attachments.finalized','request.transitioned','request.closed','request.reopened','comment.added'"
KINDS = {
    "request.created": "request_created",
    "comment.added": "comment",
    "attachments.finalized": "attachments",
    "request.assigned": "assignment",
    "request.transitioned": "transition",
    "request.closed": "request_closed",
    "request.reopened": "request_reopened",
}
logger = logging.getLogger(__name__)


class TimelineUnavailable(APIException):
    status_code = 503
    default_code = "history_unavailable"
    default_detail = "Request history is temporarily unavailable."


# A valid same-request comment link is the dedupe key, never its timestamp.
TIMELINE_CTE = f"""
;WITH comments AS (
 SELECT * FROM dbo.Comment WHERE TenantId=%s AND RequestId=%s
), files AS (
 SELECT * FROM dbo.Attachment WHERE TenantId=%s AND RequestId=%s
), raw_activity AS (
 SELECT *, CASE WHEN ISJSON(Payload)=1 THEN Payload ELSE NCHAR(123)+NCHAR(125) END AS SafePayload
 FROM dbo.Activity WHERE TenantId=%s AND RequestId=%s
), linked AS (
 SELECT a.*, CASE WHEN a.Type IN ({LINKED_TYPES}) THEN c.CommentId END AS LinkedComment,
 TRY_CONVERT(uniqueidentifier,JSON_VALUE(a.SafePayload,'$.group_id')) AS LinkedGroup,
 ROW_NUMBER() OVER (
  PARTITION BY CASE WHEN a.Type IN ({LINKED_TYPES}) AND c.CommentId IS NOT NULL
   THEN 'c:'+CONVERT(varchar(36),c.CommentId) ELSE 'a:'+CONVERT(varchar(36),a.ActivityId) END
  ORDER BY CASE WHEN a.Type='attachments.finalized' THEN 0
   WHEN a.Type='comment.added' THEN 2 ELSE 1 END, a.ActivityId ASC
 ) AS DuplicateOrder
 FROM raw_activity a LEFT JOIN comments c
 ON c.CommentId=TRY_CONVERT(uniqueidentifier,JSON_VALUE(a.SafePayload,'$.comment_id'))
), events AS (
 SELECT 'activity' AS Source, 'activity:'+CONVERT(varchar(36),ActivityId) AS EventId,
 CONVERT(varchar(36),ActivityId) AS Id, CreatedAt FROM linked WHERE DuplicateOrder=1
 UNION ALL
 SELECT 'comment','comment:'+CONVERT(varchar(36),c.CommentId),CONVERT(varchar(36),c.CommentId),c.CreatedAt
 FROM comments c WHERE NOT EXISTS (
  SELECT 1 FROM linked a WHERE a.LinkedComment=c.CommentId
 )
 UNION ALL
 SELECT 'attachments','attachments:'+COALESCE(CONVERT(varchar(36),f.GroupId),CONVERT(varchar(36),f.AttachmentId)),
 COALESCE(CONVERT(varchar(36),f.GroupId),CONVERT(varchar(36),f.AttachmentId)), MIN(f.CreatedAt)
 FROM files f WHERE NOT EXISTS (SELECT 1 FROM comments c WHERE c.CommentId=f.CommentId)
 AND NOT EXISTS (SELECT 1 FROM linked a WHERE a.LinkedGroup=f.GroupId AND a.Type='attachments.finalized')
 GROUP BY COALESCE(CONVERT(varchar(36),f.GroupId),CONVERT(varchar(36),f.AttachmentId))
)
"""


def payload_dict(value):
    try:
        data = json.loads(value or "{}")
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def uuid_value(value):
    try:
        return uuid.UUID(str(value)) if value else None
    except (ValueError, TypeError):
        return None


def actor_summary(actor):
    return UserLookupSerializer(actor).data if actor else None


def timestamp(value):
    if timezone.is_naive(value):
        value = timezone.make_aware(value, dt_timezone.utc)
    return serializers.DateTimeField().to_representation(value)


def comment_summary(item):
    if item is None:
        return None
    return {
        "comment_id": str(item.commentid),
        "body": item.messagemd,
        "visibility": item.visibility,
        "created_at": timestamp(item.createdat),
        "author": actor_summary(item.authorid),
    }


def snapshot_user(value):
    if (
        not isinstance(value, dict)
        or not uuid_value(value.get("user_id"))
        or not isinstance(value.get("display_name"), str)
        or not isinstance(value.get("email"), str)
    ):
        return None
    return {
        "user_id": str(uuid_value(value["user_id"])),
        "display_name": str(value.get("display_name") or "")[:200],
        "email": str(value.get("email") or "")[:320],
    }


def event_status(payload, key, fallback):
    value = payload.get(key)
    if (
        fallback
        and isinstance(value, dict)
        and str(uuid_value(value.get("status_id"))) == fallback["status_id"]
        and isinstance(value.get("name"), str)
        and isinstance(value.get("category"), str)
        and isinstance(value.get("is_terminal"), bool)
    ):
        return {
            "status_id": fallback["status_id"],
            "name": value["name"][:50],
            "category": value["category"][:20],
            "is_terminal": value["is_terminal"],
        }
    return fallback


def timeline_page(*, tenant_id, request_id, page=1, page_size=25):
    try:
        return _timeline_page(
            tenant_id=tenant_id, request_id=request_id, page=page, page_size=page_size
        )
    except DatabaseError as exc:
        logger.exception("Request timeline database read failed.")
        raise TimelineUnavailable() from exc


def _timeline_page(*, tenant_id, request_id, page=1, page_size=25):
    scope = {"tenantid": tenant_id, "requestid": request_id}
    params = [str(tenant_id), str(request_id)] * 3
    with connection.cursor() as cursor:
        cursor.execute(TIMELINE_CTE + "SELECT COUNT(*) FROM events;", params)
        count = int(cursor.fetchone()[0])
        if (page - 1) * page_size >= count:
            return count, []
        cursor.execute(
            TIMELINE_CTE
            + "SELECT Source,EventId,Id,CreatedAt FROM events ORDER BY CreatedAt DESC,EventId ASC OFFSET %s ROWS FETCH NEXT %s ROWS ONLY;",
            [*params, (page - 1) * page_size, page_size],
        )
        rows = cursor.fetchall()
    activity_ids = [row[2] for row in rows if row[0] == "activity"]
    activities = (
        {
            a.activityid: a
            for a in Activity.objects.filter(
                **scope, activityid__in=activity_ids
            ).select_related("actorid")
        }
        if activity_ids
        else {}
    )
    payloads = {
        key: payload_dict(a.payload) if a.type in KINDS else {}
        for key, a in activities.items()
    }
    comment_ids = {uuid_value(row[2]) for row in rows if row[0] == "comment"}
    comment_ids.update(
        uuid_value(p.get("comment_id"))
        for key, p in payloads.items()
        if activities[key].type in KINDS
    )
    comment_ids.discard(None)
    comments = (
        {
            c.commentid: c
            for c in Comment.objects.filter(
                **scope, commentid__in=comment_ids
            ).select_related("authorid")
        }
        if comment_ids
        else {}
    )
    groups = {uuid_value(p.get("group_id")) for p in payloads.values()}
    groups.update(uuid_value(row[2]) for row in rows if row[0] == "attachments")
    groups.discard(None)
    files = (
        list(
            Attachment.objects.filter(**scope)
            .filter(
                Q(commentid_id__in=comment_ids)
                | Q(groupid__in=groups)
                | Q(attachmentid__in=groups)
            )
            .order_by("createdat", "attachmentid")
        )
        if comment_ids or groups
        else []
    )
    status_ids = {
        uuid_value(p.get(field))
        for p in payloads.values()
        for field in ("from_status_id", "to_status_id")
    }
    status_ids.discard(None)
    statuses = (
        {
            s.statusid: StatusSummarySerializer(s).data
            for s in Status.objects.filter(tenantid=tenant_id, statusid__in=status_ids)
        }
        if status_ids
        else {}
    )
    result = []
    for source, event_id, raw_id, created in rows:
        identity = uuid_value(raw_id)
        activity = activities.get(identity) if source == "activity" else None
        if source == "activity" and activity is None:
            continue
        payload = payloads.get(identity, {}) if activity else {}
        comment_id = (
            uuid_value(payload.get("comment_id"))
            if activity and activity.type in KINDS
            else identity if source == "comment" else None
        )
        comment = comments.get(comment_id)
        group_id = (
            uuid_value(payload.get("group_id"))
            if activity and activity.type == "attachments.finalized"
            else identity if source == "attachments" else None
        )
        attached = [
            file
            for file in files
            if (
                comment is not None
                and file.commentid_id == comment.commentid
                and (group_id is None or uuid_value(file.groupid) == group_id)
            )
            or (
                comment is None
                and group_id
                and (
                    uuid_value(file.groupid) == group_id
                    or file.attachmentid == group_id
                )
            )
        ]
        kind = (
            KINDS.get(activity.type, "system")
            if activity
            else "attachments" if attached else "comment"
        )
        if kind == "assignment" and (
            not {"old_assignee", "new_assignee"}.issubset(payload)
            or any(
                value is not None and snapshot_user(value) is None
                for value in (payload.get("old_assignee"), payload.get("new_assignee"))
            )
        ):
            kind = "system"
        to_status = event_status(
            payload, "to_status", statuses.get(uuid_value(payload.get("to_status_id")))
        )
        from_status = event_status(
            payload,
            "from_status",
            statuses.get(uuid_value(payload.get("from_status_id"))),
        )
        if (
            kind == "transition"
            and to_status
            and to_status["category"].lower() == "closed"
        ):
            kind = "request_closed"
        elif (
            kind == "transition"
            and to_status
            and from_status
            and to_status["category"].lower() == "open"
            and (
                from_status["category"].lower() == "closed"
                or from_status["is_terminal"]
            )
        ):
            kind = "request_reopened"
        summaries = {
            "request_created": "Request created",
            "comment": "Comment added",
            "attachments": "Attachments added",
            "assignment": "Assignment changed",
            "transition": "Status changed",
            "request_closed": "Request closed",
            "request_reopened": "Request reopened",
            "system": "Event recorded",
        }
        result.append(
            {
                "event_id": event_id.lower(),
                "kind": kind,
                "activity_type": activity.type if activity else None,
                "created_at": timestamp(created),
                "actor": actor_summary(
                    activity.actorid
                    if activity
                    else comment.authorid if comment else None
                ),
                "summary": summaries[kind],
                "comment": comment_summary(comment),
                "attachments": WorkspaceAttachmentSerializer(attached, many=True).data,
                "from_status": from_status,
                "to_status": to_status,
                "old_assignee": (
                    snapshot_user(payload.get("old_assignee"))
                    if kind == "assignment"
                    else None
                ),
                "new_assignee": (
                    snapshot_user(payload.get("new_assignee"))
                    if kind == "assignment"
                    else None
                ),
            }
        )
    return count, result
