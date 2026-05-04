import re

from django.db import connection

MAX_SEARCH_TERMS = 8
MAX_PAGE_SIZE = 100
SEARCH_TYPES = {"request", "comment", "attachment"}


class SearchValidationError(ValueError):
    pass


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
              AND CONTAINS((r.Title, r.Description), %s)
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
              AND CONTAINS(c.MessageMd, %s)
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
              AND CONTAINS(a.Filename, %s)
              {filters}
            """
        )
        params.extend([str(tenant_id), fts_query, *filter_params])

    sql = f"""
    WITH matched AS (
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
        MatchSources,
        COUNT(*) OVER() AS TotalCount
    FROM grouped
    ORDER BY Rank DESC, UpdatedAt DESC
    OFFSET %s ROWS FETCH NEXT %s ROWS ONLY;
    """
    params.extend([offset, page_size])

    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        rows = cursor.fetchall()

    total = int(rows[0][11]) if rows else 0
    return {
        "count": total,
        "page": page,
        "page_size": page_size,
        "results": [serialize_search_row(row) for row in rows],
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
        params.append(created_from)
    if created_to:
        filters.append("AND r.CreatedAt <= %s")
        params.append(created_to)
    if updated_from:
        filters.append("AND r.UpdatedAt >= %s")
        params.append(updated_from)
    if updated_to:
        filters.append("AND r.UpdatedAt <= %s")
        params.append(updated_to)
    return "\n              ".join(filters), params


def serialize_search_row(row):
    match_sources = sorted({item for item in row[10].split(",") if item})
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
