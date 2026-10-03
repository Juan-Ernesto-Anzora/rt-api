import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
import yaml
from django.test import Client, override_settings
from django.urls import resolve
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.rt.models import Flow, Request, Status, Tenant, User
from apps.rt.search import (
    SearchMetadataError,
    SearchValidationError,
    build_fts_query,
    build_request_filters,
    hydrate_search_rows,
    search_requests,
    serialize_search_row,
)
from apps.rt.serializers import SearchQuerySerializer
from apps.rt.views import SearchView


class FakeCursor:
    def __init__(self, rows, total=None):
        self.rows = rows
        self.total = len(rows) if total is None else total
        self.queries = []
        self.sql = None
        self.params = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params):
        self.sql = sql
        self.params = params
        self.queries.append((sql, params))

    def fetchone(self):
        return (self.total,)

    def fetchall(self):
        return self.rows


def test_search_requests_postman_route_alias_resolves():
    match = resolve("/api/search/requests")

    assert match.url_name == "search-requests"


def test_build_fts_query_uses_prefix_terms_and_strips_symbols():
    query = build_fts_query('reset password"; DROP TABLE dbo.Request;')

    assert (
        query
        == '"reset*" AND "password*" AND "DROP*" AND "TABLE*" AND "dbo*" AND "Request*"'
    )
    assert ";" not in query


def test_build_fts_query_rejects_empty_terms():
    with pytest.raises(SearchValidationError):
        build_fts_query("!!!")


def test_search_requests_builds_tenant_scoped_combined_fts_sql(monkeypatch):
    tenant_id = uuid.uuid4()
    status_id = uuid.uuid4()
    request_id = uuid.uuid4()
    flow_id = uuid.uuid4()
    updated = datetime(2026, 5, 3, 12, 0, tzinfo=timezone.utc)
    row = (
        request_id,
        "RT-2026-000123",
        "Reset payroll password",
        "normal",
        status_id,
        None,
        flow_id,
        updated,
        updated,
        30,
        "request,comment,attachment",
        1,
    )
    fake_cursor = FakeCursor([row], total=20)

    monkeypatch.setattr("apps.rt.search.connection.cursor", lambda: fake_cursor)
    monkeypatch.setattr(
        "apps.rt.search.hydrate_search_rows",
        lambda rows, tenant: [serialize_search_row(item) for item in rows],
    )

    results = search_requests(
        tenant_id=tenant_id,
        raw_query="reset password",
        types="request,attachment",
        status_id=status_id,
        created_from=updated,
        page=2,
        page_size=10,
    )

    assert "FROM dbo.Request r" in fake_cursor.sql
    assert "FROM dbo.Attachment a" in fake_cursor.sql
    assert "FROM dbo.Comment c" not in fake_cursor.sql
    assert fake_cursor.sql.lstrip().startswith(";WITH matched AS")
    assert "CONTAINS((Title, Description), %s)" in fake_cursor.sql
    assert "CONTAINS(Filename, %s)" in fake_cursor.sql
    assert fake_cursor.sql.count("r.TenantId = %s") == 1
    assert fake_cursor.sql.count("a.TenantId = %s") == 1
    assert str(tenant_id) in fake_cursor.params
    assert str(status_id) in fake_cursor.params
    assert updated in fake_cursor.params
    assert fake_cursor.params[-2:] == [10, 10]
    assert results["count"] == 20
    assert results["page"] == 2
    assert results["results"][0]["request_id"] == str(request_id)
    assert results["results"][0]["match_sources"] == [
        "attachment",
        "comment",
        "request",
    ]


def test_search_requests_rejects_unknown_type():
    with pytest.raises(SearchValidationError):
        search_requests(tenant_id=uuid.uuid4(), raw_query="reset", types="ticket")


def test_search_view_returns_validation_error_for_blank_query():
    request = SimpleNamespace(query_params={"q": ""}, tenant_id=uuid.uuid4())

    response = SearchView().get(request)

    assert response.status_code == 400
    assert response.data["code"] == "validation_error"


def test_search_view_dispatches_to_search_service(monkeypatch):
    tenant_id = uuid.uuid4()
    captured = {}

    def fake_search_requests(**kwargs):
        captured.update(kwargs)
        return {"count": 0, "page": 1, "page_size": 25, "results": []}

    monkeypatch.setattr("apps.rt.views.search_requests", fake_search_requests)
    request = SimpleNamespace(query_params={"q": "reset"}, tenant_id=tenant_id)

    response = SearchView().get(request)

    assert response.status_code == 200
    assert response.data["count"] == 0
    assert captured["tenant_id"] == tenant_id
    assert captured["raw_query"] == "reset"


def request_fixture(tenant_id=None, assigned=False):
    tenant = Tenant(tenantid=tenant_id or uuid.uuid4())
    flow = Flow(flowid=uuid.uuid4(), tenantid=tenant, name="Support")
    status = Status(
        statusid=uuid.uuid4(),
        tenantid=tenant,
        flowid=flow,
        name="Open",
        category="open",
        isterminal=False,
    )
    user = User(userid=uuid.uuid4(), displayname="Owner", email="owner@example.test")
    now = datetime(2026, 10, 1, 12, tzinfo=timezone.utc)
    return Request(
        requestid=uuid.uuid4(),
        tenantid=tenant,
        humanid="RT-1",
        title="VPN",
        priority="high",
        flowid=flow,
        statusid=status,
        requesterid=user,
        assigneeid=user if assigned else None,
        createdat=now,
        updatedat=now,
    )


def search_row(item, sources="request,comment,attachment", rank=30):
    return (
        item.requestid,
        item.humanid,
        item.title,
        item.priority,
        item.statusid_id,
        item.assigneeid_id,
        item.flowid_id,
        item.createdat,
        item.updatedat,
        rank,
        sources,
    )


def patch_hydration(monkeypatch, items):
    calls = []

    class JoinedRows(list):
        def select_related(self, *relations):
            assert set(relations) == {"statusid", "requesterid", "assigneeid", "flowid"}
            return self

    def scoped_filter(**kwargs):
        calls.append(kwargs)
        return JoinedRows(
            item
            for item in items
            if item.tenantid_id == kwargs["tenantid_id"]
            and item.requestid in kwargs["requestid__in"]
        )

    monkeypatch.setattr("apps.rt.search.Request.objects.filter", scoped_filter)
    return calls


@pytest.mark.parametrize("assigned", [False, True])
def test_additive_hydration_contract_and_nulls(monkeypatch, assigned):
    item = request_fixture(assigned=assigned)
    patch_hydration(monkeypatch, [item])
    result = hydrate_search_rows([search_row(item)], item.tenantid_id)[0]
    assert set(serialize_search_row(search_row(item))) <= result.keys()
    assert result["status"] == {
        "status_id": str(item.statusid_id),
        "name": "Open",
        "category": "open",
        "is_terminal": False,
    }
    assert result["requester"]["display_name"] == "Owner"
    assert result["flow"] == {"flow_id": str(item.flowid_id), "name": "Support"}
    assert result["assignee"] == (result["requester"] if assigned else None)
    assert result["rank"] == 30 and result["priority"] == "high"
    assert (
        not {
            "description",
            "comments",
            "attachments",
            "activity",
            "tags",
            "custom_fields",
        }
        & result.keys()
    )


def test_hydration_rejects_foreign_ids_and_restores_ranked_order(monkeypatch):
    first = request_fixture()
    second = request_fixture(tenant_id=first.tenantid_id)
    foreign = request_fixture()
    calls = patch_hydration(monkeypatch, [second, foreign, first])
    results = hydrate_search_rows(
        [search_row(first), search_row(foreign), search_row(second)], first.tenantid_id
    )
    assert [r["request_id"] for r in results] == [
        str(first.requestid),
        str(second.requestid),
    ]
    assert calls[0]["tenantid_id"] == first.tenantid_id
    assert len(calls) == 1
    assert hydrate_search_rows([], first.tenantid_id) == []
    assert len(calls) == 1


@pytest.mark.parametrize("relation", ["statusid", "flowid"])
def test_hydration_never_exposes_foreign_related_labels(monkeypatch, relation):
    item = request_fixture()
    getattr(item, relation).tenantid_id = uuid.uuid4()
    patch_hydration(monkeypatch, [item])
    with pytest.raises(SearchMetadataError):
        hydrate_search_rows([search_row(item)], item.tenantid_id)


@pytest.mark.parametrize("size", [0, 1, 10, 25])
def test_service_query_budget_is_bounded(monkeypatch, size):
    tenant_id = uuid.uuid4()
    items = [request_fixture(tenant_id=tenant_id) for _ in range(size)]
    cursor = FakeCursor([search_row(item) for item in items])
    monkeypatch.setattr("apps.rt.search.connection.cursor", lambda: cursor)
    hydration = patch_hydration(monkeypatch, items)
    result = search_requests(tenant_id=tenant_id, raw_query="vpn", page_size=25)
    assert result["count"] == size
    assert len(result["results"]) == size
    assert len(cursor.queries) == (2 if size else 1)
    assert len(hydration) == (1 if size else 0)


def test_out_of_range_page_keeps_total_and_skips_hydration(monkeypatch):
    cursor = FakeCursor([], total=26)
    monkeypatch.setattr("apps.rt.search.connection.cursor", lambda: cursor)
    calls = patch_hydration(monkeypatch, [])
    result = search_requests(
        tenant_id=uuid.uuid4(), raw_query="vpn", page=3, page_size=25
    )
    assert result == {"count": 26, "page": 3, "page_size": 25, "results": []}
    assert len(cursor.queries) == 1 and not calls


@pytest.mark.parametrize(
    "source,weight,column,tenant_alias",
    [
        ("request", 30, "CONTAINS((Title, Description)", "r"),
        ("comment", 20, "CONTAINS(MessageMd", "c"),
        ("attachment", 10, "CONTAINS(Filename", "a"),
    ],
)
def test_each_source_count_is_scoped_filtered_and_weighted(
    monkeypatch, source, weight, column, tenant_alias
):
    tenant_id = uuid.uuid4()
    cursor = FakeCursor([])
    monkeypatch.setattr("apps.rt.search.connection.cursor", lambda: cursor)
    search_requests(
        tenant_id=tenant_id, raw_query="vpn", types=source, status_id=uuid.uuid4()
    )
    sql, params = cursor.queries[0]
    assert f"{tenant_alias}.TenantId = %s" in sql
    assert str(tenant_id) in params
    assert column in sql and f"{weight} AS MatchRank" in sql
    assert "AND r.StatusId = %s" in sql
    assert "MAX(MatchRank)" in sql
    if source != "request":
        assert f"r.TenantId = {tenant_alias}.TenantId" in sql
    # Current Detail/list metadata policy does not restrict these flags.
    assert "Visibility" not in sql and "ScanStatus" not in sql


def test_fixed_order_and_validated_match_sources(monkeypatch):
    item = request_fixture()
    cursor = FakeCursor([search_row(item, "comment,comment,attachment,invalid", 20)])
    monkeypatch.setattr("apps.rt.search.connection.cursor", lambda: cursor)
    patch_hydration(monkeypatch, [item])
    result = search_requests(tenant_id=item.tenantid_id, raw_query="vpn")
    assert "ORDER BY Rank DESC, UpdatedAt DESC, RequestId ASC" in cursor.queries[1][0]
    assert result["results"][0]["match_sources"] == ["attachment", "comment"]
    assert result["results"][0]["rank"] == 20


def test_token_limit_and_unicode():
    assert (
        build_fts_query("contraseña áéí VPN") == '"contraseña*" AND "áéí*" AND "VPN*"'
    )
    assert (
        len(
            build_fts_query("one two three four five six seven eight nine").split(
                " AND "
            )
        )
        == 8
    )


@override_settings(TIME_ZONE="America/El_Salvador")
@pytest.mark.parametrize("prefix", ["created", "updated"])
def test_date_only_bounds_use_configured_calendar_day(prefix):
    serializer = SearchQuerySerializer(
        data={"q": "vpn", f"{prefix}_from": "2026-10-01", f"{prefix}_to": "2026-10-01"}
    )
    assert serializer.is_valid(), serializer.errors
    data = serializer.validated_data
    assert data[f"{prefix}_from"].astimezone(timezone.utc) == datetime(
        2026, 10, 1, 6, tzinfo=timezone.utc
    )
    assert data[f"{prefix}_to"].astimezone(timezone.utc) == datetime(
        2026, 10, 2, 6, tzinfo=timezone.utc
    )
    assert data[f"{prefix}_to_exclusive"] is True
    sql, params = build_request_filters(
        **{k: v for k, v in data.items() if k != "q" and k not in {"page", "page_size"}}
    )
    assert f"r.{prefix.capitalize()}At < %s" in sql
    assert params[-1] == datetime(2026, 10, 2, 6, tzinfo=timezone.utc)


def test_explicit_datetime_preserves_inclusive_instant():
    serializer = SearchQuerySerializer(
        data={"q": "vpn", "updated_to": "2026-10-01T14:00:00+02:00"}
    )
    assert serializer.is_valid(), serializer.errors
    data = serializer.validated_data
    assert data["updated_to"].astimezone(timezone.utc) == datetime(
        2026, 10, 1, 12, tzinfo=timezone.utc
    )
    assert data["updated_to_exclusive"] is False
    sql, _ = build_request_filters(updated_to=data["updated_to"])
    assert "r.UpdatedAt <= %s" in sql


@pytest.mark.parametrize(
    "params",
    [
        {"updated_from": "2026-10-02", "updated_to": "2026-10-01"},
        {"created_from": "2026-10-01T13:00:00Z", "created_to": "2026-10-01T12:00:00Z"},
        {"created_to": "2026-02-30"},
        {"status_id": "bad"},
        {"flow_id": "bad"},
        {"assignee_id": "bad"},
        {"page": 0},
        {"page_size": 101},
    ],
)
def test_invalid_structured_filters_return_canonical_400(params):
    result = SearchView().get(
        SimpleNamespace(query_params={"q": "vpn", **params}, tenant_id=uuid.uuid4())
    )
    assert result.status_code == 400
    assert result.data["code"] == "validation_error"
    assert result.data["details"]


def test_all_metadata_filters_before_pagination(monkeypatch):
    ids = [uuid.uuid4() for _ in range(3)]
    now = datetime(2026, 10, 1, tzinfo=timezone.utc)
    cursor = FakeCursor([], total=0)
    monkeypatch.setattr("apps.rt.search.connection.cursor", lambda: cursor)
    search_requests(
        tenant_id=uuid.uuid4(),
        raw_query="vpn",
        status_id=ids[0],
        assignee_id=ids[1],
        flow_id=ids[2],
        created_from=now,
        created_to=now,
        updated_from=now,
        updated_to=now,
    )
    sql, params = cursor.queries[0]
    for column in ("StatusId", "AssigneeId", "FlowId", "CreatedAt", "UpdatedAt"):
        assert f"AND r.{column}" in sql
    for identity in ids:
        assert params.count(str(identity)) == 3


def test_auth_and_missing_tenant():
    response = SearchView.as_view()(
        APIRequestFactory().get("/api/search/requests?q=vpn")
    )
    assert response.status_code == 401
    response = Client().get("/api/search/requests?q=vpn")
    assert response.status_code == 400 and response.json()["code"] == "tenant_required"


def test_search_openapi_reuses_summaries_and_only_supported_parameters():
    schema = yaml.safe_load(Client().get("/api/schema").content)
    names = {
        p["name"] for p in schema["paths"]["/api/search/requests"]["get"]["parameters"]
    }
    assert names == {
        "q",
        "page",
        "page_size",
        "types",
        "status_id",
        "assignee_id",
        "flow_id",
        "created_from",
        "created_to",
        "updated_from",
        "updated_to",
    }
    fields = schema["components"]["schemas"]["SearchResult"]["properties"]
    assert fields["assignee"]["nullable"] is True
    for key, component in (
        ("status", "StatusSummary"),
        ("requester", "UserLookup"),
        ("flow", "FlowLookup"),
    ):
        assert component in str(fields[key])


def test_count_and_page_share_identical_matching_scope(monkeypatch):
    item = request_fixture()
    cursor = FakeCursor([search_row(item)], total=50)
    monkeypatch.setattr("apps.rt.search.connection.cursor", lambda: cursor)
    patch_hydration(monkeypatch, [item])
    result = search_requests(
        tenant_id=item.tenantid_id,
        raw_query="vpn",
        page=2,
        page_size=25,
        flow_id=item.flowid_id,
        types="COMMENT,request,comment",
    )
    assert result["count"] == 50 and result["page"] == 2
    count_sql, count_params = cursor.queries[0]
    page_sql, page_params = cursor.queries[1]
    assert (
        count_sql.split("SELECT COUNT(*)")[0].strip()
        == page_sql.split("    SELECT\n        RequestId,")[0].strip()
    )
    assert count_params == page_params[:-2]
    assert page_params[-2:] == [25, 25]
    assert "FROM dbo.Attachment" not in page_sql
    assert page_sql.count("'comment' AS MatchSource") == 1


def test_unsupported_web_labels_are_not_aliased(monkeypatch):
    captured = {}

    def search(**kwargs):
        captured.update(kwargs)
        return {"count": 0, "page": 1, "page_size": 25, "results": []}

    monkeypatch.setattr("apps.rt.views.search_requests", search)
    response = SearchView().get(
        SimpleNamespace(
            query_params={
                "q": "vpn",
                "status": "Open",
                "assignee": "Agent",
                "flow": "Support",
                "tag": "vpn",
                "sort": "-updated_at",
            },
            tenant_id=uuid.uuid4(),
        )
    )
    assert response.status_code == 200
    assert not {"status", "assignee", "flow", "tag", "sort"} & captured.keys()
    assert captured["status_id"] is None and captured["assignee_id"] is None


def test_invalid_tenant_middleware_returns_404(monkeypatch):
    cursor = FakeCursor([], total=0)
    monkeypatch.setattr(cursor, "fetchone", lambda: None)
    monkeypatch.setattr("apps.core.middleware.connection.cursor", lambda: cursor)
    response = Client().get("/api/search/requests?q=vpn", HTTP_X_TENANT="UNKNOWN")
    assert response.status_code == 404
    assert response.json()["code"] == "tenant_not_found"


def test_unknown_types_and_symbol_only_query_use_canonical_error():
    for params in ({"q": "vpn", "types": "ticket"}, {"q": "!!!"}):
        response = SearchView().get(
            SimpleNamespace(query_params=params, tenant_id=uuid.uuid4())
        )
        assert response.status_code == 400
        assert set(response.data) == {"code", "message", "details"}


def test_inconsistent_metadata_returns_canonical_500(monkeypatch):
    def fail(**kwargs):
        raise SearchMetadataError()

    monkeypatch.setattr("apps.rt.views.search_requests", fail)
    request = APIRequestFactory().get("/api/search/requests?q=vpn")
    request.tenant_id = uuid.uuid4()
    force_authenticate(request, user=SimpleNamespace(is_authenticated=True))
    response = SearchView.as_view()(request)
    assert response.status_code == 500
    assert response.data == {
        "code": "server_error",
        "message": "Search result metadata is unavailable.",
        "details": [],
    }
