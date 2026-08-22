import csv
from datetime import UTC, datetime, time, timedelta

from django.db.models import Count, Q
from django.db.models.expressions import RawSQL
from django.utils import timezone

from apps.rt.models import Flow, Membership, Request, Status
from apps.rt.search import build_fts_query
from apps.rt.services.admin_directory import AdminDirectoryError

CSV_COLUMNS = [
    "request_id",
    "human_id",
    "title",
    "flow",
    "status",
    "priority",
    "requester",
    "assignee",
    "due_at",
    "created_at",
    "updated_at",
]
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def build_report_queryset(tenant_id, filters):
    validate_tenant_filters(tenant_id, filters)
    queryset = Request.objects.filter(tenantid_id=tenant_id).select_related(
        "flowid", "statusid", "requesterid", "assigneeid"
    )

    field_map = {
        "status_id": "statusid_id",
        "status_category": "statusid__category__iexact",
        "priority": "priority",
        "flow_id": "flowid_id",
        "requester_id": "requesterid_id",
        "assignee_id": "assigneeid_id",
        "created_from": "createdat__gte",
        "created_to": "createdat__lte",
        "updated_from": "updatedat__gte",
        "updated_to": "updatedat__lte",
        "due_from": "dueat__gte",
        "due_to": "dueat__lte",
    }
    for public_field, lookup in field_map.items():
        if public_field in filters:
            queryset = queryset.filter(**{lookup: filters[public_field]})

    query = filters.get("q")
    if query:
        queryset = queryset.filter(
            requestid__in=RawSQL(
                """
                SELECT matches.RequestId
                FROM (
                    SELECT r.RequestId
                    FROM dbo.Request r
                    WHERE r.TenantId = %s
                      AND CONTAINS((r.Title, r.Description), %s)
                    UNION
                    SELECT c.RequestId
                    FROM dbo.Comment c
                    WHERE c.TenantId = %s
                      AND CONTAINS(c.MessageMd, %s)
                    UNION
                    SELECT a.RequestId
                    FROM dbo.Attachment a
                    WHERE a.TenantId = %s
                      AND CONTAINS(a.Filename, %s)
                ) matches
                """,
                [
                    str(tenant_id),
                    build_fts_query(query),
                    str(tenant_id),
                    build_fts_query(query),
                    str(tenant_id),
                    build_fts_query(query),
                ],
            )
        )
    return queryset


def validate_tenant_filters(tenant_id, filters):
    if (
        "flow_id" in filters
        and not Flow.objects.filter(
            tenantid_id=tenant_id, flowid=filters["flow_id"]
        ).exists()
    ):
        raise filter_not_found("flow_id", "Flow")

    if (
        "status_id" in filters
        and not Status.objects.filter(
            tenantid_id=tenant_id, statusid=filters["status_id"]
        ).exists()
    ):
        raise filter_not_found("status_id", "Status")

    for field in ("requester_id", "assignee_id"):
        if (
            field in filters
            and not Membership.objects.filter(
                tenantid_id=tenant_id, userid_id=filters[field]
            ).exists()
        ):
            raise filter_not_found(field, "User")


def filter_not_found(field, resource):
    return AdminDirectoryError(
        "not_found",
        f"{resource} filter not found for this tenant.",
        404,
        [{"field": field, "message": "Not found for this tenant."}],
    )


def build_report_summary(queryset, current_user_id):
    now = timezone.now().astimezone(UTC)
    start_of_today = datetime.combine(now.date(), time.min, tzinfo=UTC)
    start_of_tomorrow = start_of_today + timedelta(days=1)
    active = ~Q(statusid__category__iexact="closed") & Q(statusid__isterminal=False)

    counts = queryset.aggregate(
        total=Count("requestid"),
        open=Count("requestid", filter=Q(statusid__category__iexact="open")),
        in_progress=Count(
            "requestid", filter=Q(statusid__category__iexact="in_progress")
        ),
        waiting=Count("requestid", filter=Q(statusid__category__iexact="waiting")),
        closed=Count("requestid", filter=Q(statusid__category__iexact="closed")),
        due_today=Count(
            "requestid",
            filter=active & Q(dueat__gte=start_of_today, dueat__lt=start_of_tomorrow),
        ),
        overdue=Count("requestid", filter=active & Q(dueat__lt=start_of_today)),
        unassigned=Count("requestid", filter=active & Q(assigneeid__isnull=True)),
        assigned_to_me=Count("requestid", filter=Q(assigneeid_id=current_user_id)),
    )
    counts["by_priority"] = list(
        queryset.values("priority")
        .annotate(count=Count("requestid"))
        .order_by("priority")
    )
    counts["by_status"] = [
        {
            "status_id": row["statusid_id"],
            "name": row["statusid__name"],
            "category": row["statusid__category"],
            "count": row["count"],
        }
        for row in queryset.values(
            "statusid_id", "statusid__name", "statusid__category"
        )
        .annotate(count=Count("requestid"))
        .order_by("statusid__name", "statusid_id")
    ]
    return counts


def normalized_audit_filters(filters):
    return {
        key: value.isoformat() if hasattr(value, "isoformat") else str(value)
        for key, value in sorted(filters.items())
        if key != "format" and value not in (None, "")
    }


class CsvEcho:
    def write(self, value):
        return value


def iter_request_csv(queryset):
    writer = csv.writer(CsvEcho(), lineterminator="\r\n")
    yield writer.writerow(CSV_COLUMNS)
    for rt_request in queryset.iterator(chunk_size=1000):
        yield writer.writerow(request_csv_row(rt_request))


def request_csv_row(rt_request):
    values = [
        rt_request.requestid,
        rt_request.humanid,
        rt_request.title,
        rt_request.flowid.name,
        rt_request.statusid.name,
        rt_request.priority,
        rt_request.requesterid.displayname,
        rt_request.assigneeid.displayname if rt_request.assigneeid else "",
        format_utc(rt_request.dueat),
        format_utc(rt_request.createdat),
        format_utc(rt_request.updatedat),
    ]
    return [csv_safe_cell(value) for value in values]


def csv_safe_cell(value):
    if value is None:
        return ""
    text = str(value)
    if text.startswith(FORMULA_PREFIXES):
        return f"'{text}"
    return text


def format_utc(value):
    if value is None:
        return ""
    if timezone.is_naive(value):
        value = timezone.make_aware(value, UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
