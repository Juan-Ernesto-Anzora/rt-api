import re

from django.core.exceptions import ObjectDoesNotExist
from django.db import connection
from rest_framework.exceptions import APIException

from .models import Request
from .serializers import (
    FlowLookupSerializer,
    StatusSummarySerializer,
    UserLookupSerializer,
)

MAX_SEARCH_TERMS = 8
MAX_PAGE_SIZE = 100
SEARCH_TYPES = {"request", "comment", "attachment"}


class SearchValidationError(ValueError):
    pass


class SearchMetadataError(APIException):
    status_code = 500
    default_detail = "Search result metadata is unavailable."
    default_code = "server_error"


def normalize_search_types(value):
    if not value:
        return sorted(SEARCH_TYPES)

    requested = {item.strip().lower() for item in value.split(",") if item.strip()}
    invalid = requested - SEARCH_TYPES
    if invalid:
        raise SearchValidationError(
            f"Unsupported search type(s): {', '.join(sorted(invalid))}."
        )
    if not requested:
        return sorted(SEARCH_TYPES)
    return sorted(requested)


def build_fts_query(raw_query):
    tokens = re.findall(r"[\w]+", raw_query or "", flags=re.UNICODE)
    tokens = [token for token in tokens if token]
    if not tokens:
        raise SearchValidationError("Search query must include at least one term.")

    terms = []
    for token in tokens[:MAX_SEARCH_TERMS]:
        escaped = token.replace('"', '""')
        terms.append(f'"{escaped}*"')
    return " AND ".join(terms)


def search_requests(
    *,
    tenant_id,
    raw_query,
    page=1,
    page_size=25,
    types=None,
    status_id=None,
    assignee_id=None,
    flow_id=None,
    created_from=None,
    created_to=None,
    updated_from=None,
    updated_to=None,
    created_to_exclusive=False,
    updated_to_exclusive=False,
):
    page = max(int(page), 1)
    page_size = min(max(int(page_size), 1), MAX_PAGE_SIZE)
    offset = (page - 1) * page_size
    fts_query = build_fts_query(raw_query)
    search_types = normalize_search_types(types)
    filters, filter_params = build_request_filters(
        status_id=status_id,
        assignee_id=assignee_id,
        flow_id=flow_id,
        created_from=created_from,
        created_to=created_to,
        updated_from=updated_from,
        updated_to=updated_to,
        created_to_exclusive=created_to_exclusive,
        updated_to_exclusive=updated_to_exclusive,
    )

    selects = []
    params = []
    if "request" in search_types:
        selects.append(
            f"""
            SELECT
                r.RequestId,
                r.HumanId,
                r.Title,
                r.Priority,
                r.StatusId,
                r.AssigneeId,
                r.FlowId,
                r.CreatedAt,
                r.UpdatedAt,
                'request' AS MatchSource,
                30 AS MatchRank
            FROM dbo.Request r
            WHERE r.TenantId = %s
              AND CONTAINS((Title, Description), %s)
              {filters}
            """
        )
        params.extend([str(tenant_id), fts_query, *filter_params])

    if "comment" in search_types:
        selects.append(
            f"""
            SELECT
                r.RequestId,
                r.HumanId,
                r.Title,
                r.Priority,
                r.StatusId,
                r.AssigneeId,
                r.FlowId,
                r.CreatedAt,
                r.UpdatedAt,
                'comment' AS MatchSource,
                20 AS MatchRank
            FROM dbo.Comment c
            JOIN dbo.Request r
              ON r.RequestId = c.RequestId
             AND r.TenantId = c.TenantId
            WHERE c.TenantId = %s
              AND CONTAINS(MessageMd, %s)
              {filters}
            """
        )
        params.extend([str(tenant_id), fts_query, *filter_params])

    if "attachment" in search_types:
        selects.append(
            f"""
            SELECT
                r.RequestId,
                r.HumanId,
                r.Title,
                r.Priority,
                r.StatusId,
                r.AssigneeId,
                r.FlowId,
                r.CreatedAt,
                r.UpdatedAt,
                'attachment' AS MatchSource,
                10 AS MatchRank
            FROM dbo.Attachment a
            JOIN dbo.Request r
              ON r.RequestId = a.RequestId
             AND r.TenantId = a.TenantId
            WHERE a.TenantId = %s
              AND CONTAINS(Filename, %s)
              {filters}
            """
        )
        params.extend([str(tenant_id), fts_query, *filter_params])

    cte = f"""
    ;WITH matched AS (
        {" UNION ALL ".join(selects)}
    ),
    grouped AS (
        SELECT
            RequestId,
            HumanId,
            Title,
            Priority,
            StatusId,
            AssigneeId,
            FlowId,
            CreatedAt,
            UpdatedAt,
            MAX(MatchRank) AS Rank,
            STRING_AGG(MatchSource, ',') AS MatchSources
        FROM matched
        GROUP BY
            RequestId,
            HumanId,
            Title,
            Priority,
            StatusId,
            AssigneeId,
            FlowId,
            CreatedAt,
            UpdatedAt
    )
    """
    sql = (
        cte
        + """
    SELECT
        RequestId,
        HumanId,
        Title,
        Priority,
        StatusId,
        AssigneeId,
        FlowId,
        CreatedAt,
        UpdatedAt,
        Rank,
        MatchSources
    FROM grouped
    ORDER BY Rank DESC, UpdatedAt DESC, RequestId ASC
    OFFSET %s ROWS FETCH NEXT %s ROWS ONLY;
    """
    )
    with connection.cursor() as cursor:
        cursor.execute(cte + "SELECT COUNT(*) FROM grouped;", params)
        total = int(cursor.fetchone()[0])
        rows = []
        if offset < total:
            cursor.execute(sql, [*params, offset, page_size])
            rows = cursor.fetchall()

    return {
        "count": total,
        "page": page,
        "page_size": page_size,
        "results": hydrate_search_rows(rows, tenant_id),
    }


def build_request_filters(
    *,
    status_id=None,
    assignee_id=None,
    flow_id=None,
    created_from=None,
    created_to=None,
    updated_from=None,
    updated_to=None,
    created_to_exclusive=False,
    updated_to_exclusive=False,
):
    filters = []
    params = []
    if status_id:
        filters.append("AND r.StatusId = %s")
        params.append(str(status_id))
    if assignee_id:
        filters.append("AND r.AssigneeId = %s")
        params.append(str(assignee_id))
    if flow_id:
        filters.append("AND r.FlowId = %s")
        params.append(str(flow_id))
    if created_from:
        filters.append("AND r.CreatedAt >= %s")
        params.append(connection.ops.adapt_datetimefield_value(created_from))
    if created_to:
        operator = "<" if created_to_exclusive else "<="
        filters.append(f"AND r.CreatedAt {operator} %s")
        params.append(connection.ops.adapt_datetimefield_value(created_to))
    if updated_from:
        filters.append("AND r.UpdatedAt >= %s")
        params.append(connection.ops.adapt_datetimefield_value(updated_from))
    if updated_to:
        operator = "<" if updated_to_exclusive else "<="
        filters.append(f"AND r.UpdatedAt {operator} %s")
        params.append(connection.ops.adapt_datetimefield_value(updated_to))
    return "\n              ".join(filters), params


def serialize_search_row(row):
    match_sources = sorted(set(row[10].split(",")) & SEARCH_TYPES)
    return {
        "request_id": str(row[0]),
        "human_id": row[1],
        "title": row[2],
        "priority": row[3],
        "status_id": str(row[4]),
        "assignee_id": str(row[5]) if row[5] else None,
        "flow_id": str(row[6]),
        "created_at": row[7].isoformat() if hasattr(row[7], "isoformat") else row[7],
        "updated_at": row[8].isoformat() if hasattr(row[8], "isoformat") else row[8],
        "rank": row[9],
        "match_sources": match_sources,
    }


def hydrate_search_rows(rows, tenant_id):
    if not rows:
        return []
    requests = Request.objects.filter(
        tenantid_id=tenant_id, requestid__in=[row[0] for row in rows]
    ).select_related("statusid", "requesterid", "assigneeid", "flowid")
    by_id = {str(item.requestid).lower(): item for item in requests}
    results = []
    for row in rows:
        item = by_id.get(str(row[0]).lower())
        if item is None:
            continue
        try:
            flow, status, requester, assignee = (
                item.flowid,
                item.statusid,
                item.requesterid,
                item.assigneeid,
            )
        except ObjectDoesNotExist as exc:
            raise SearchMetadataError() from exc
        if (
            flow is None
            or status is None
            or requester is None
            or (item.assigneeid_id and assignee is None)
        ):
            raise SearchMetadataError()
        expected_tenant = str(tenant_id).lower()
        if (
            any(
                str(value).lower() != expected_tenant
                for value in (item.tenantid_id, flow.tenantid_id, status.tenantid_id)
            )
            or item.statusid.flowid_id != item.flowid_id
        ):
            raise SearchMetadataError()
        result = serialize_search_row(row)
        result.update(
            status=StatusSummarySerializer(status).data,
            requester=UserLookupSerializer(requester).data,
            assignee=(
                UserLookupSerializer(assignee).data if item.assigneeid_id else None
            ),
            flow=FlowLookupSerializer(flow).data,
        )
        results.append(result)
    return results
