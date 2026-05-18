import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from django.urls import resolve

from apps.rt.search import SearchValidationError, build_fts_query, search_requests
from apps.rt.views import SearchView


class FakeCursor:
    def __init__(self, rows):
        self.rows = rows
        self.sql = None
        self.params = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params):
        self.sql = sql
        self.params = params

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
    fake_cursor = FakeCursor([row])

    monkeypatch.setattr("apps.rt.search.connection.cursor", lambda: fake_cursor)

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
    assert results["count"] == 1
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
