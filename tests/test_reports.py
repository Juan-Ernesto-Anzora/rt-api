import uuid
from types import SimpleNamespace

import pytest
from django.db.models.expressions import RawSQL
from django.test import Client
from django.urls import resolve
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.rt.serializers import ReportFilterSerializer
from apps.rt.services.admin_directory import AdminDirectoryError
from apps.rt.services.admin_permissions import REPORTS_READ_PERMISSION
from apps.rt.services.report_service import build_report_queryset
from apps.rt.views import ReportSummaryView


def authenticated_request(path, tenant_id):
    request = APIRequestFactory().get(path)
    request.tenant_id = tenant_id
    force_authenticate(
        request,
        user=SimpleNamespace(
            is_authenticated=True,
            email="manager@example.com",
            username="manager@example.com",
        ),
    )
    return request


def report_context():
    return SimpleNamespace(
        user=SimpleNamespace(user_id=str(uuid.uuid4())),
        permissions=[REPORTS_READ_PERMISSION],
    )


def test_report_routes_resolve():
    assert resolve("/api/reports/summary/").url_name == "report-summary"
    assert resolve("/api/reports/requests/export/").url_name == "report-request-export"


@pytest.mark.parametrize(
    ("field", "value"),
    [("priority", "critical"), ("status_category", "resolved")],
)
def test_report_filter_rejects_unknown_enums(field, value):
    serializer = ReportFilterSerializer(data={field: value})
    assert not serializer.is_valid()
    assert field in serializer.errors


def test_report_filter_rejects_reversed_date_range():
    serializer = ReportFilterSerializer(
        data={
            "created_from": "2026-08-02T00:00:00Z",
            "created_to": "2026-08-01T00:00:00Z",
        }
    )
    assert not serializer.is_valid()
    assert "created_to" in serializer.errors


def test_report_summary_requires_exact_permission(monkeypatch):
    checked = []

    def fake_context(request, required_permission):
        checked.append(required_permission)
        return report_context()

    monkeypatch.setattr("apps.rt.views.get_admin_context", fake_context)
    monkeypatch.setattr(
        "apps.rt.views.build_report_queryset", lambda tenant_id, filters: object()
    )
    monkeypatch.setattr(
        "apps.rt.views.build_report_summary",
        lambda queryset, user_id: {
            "total": 0,
            "open": 0,
            "in_progress": 0,
            "waiting": 0,
            "closed": 0,
            "due_today": 0,
            "overdue": 0,
            "unassigned": 0,
            "assigned_to_me": 0,
            "by_priority": [],
            "by_status": [],
        },
    )

    response = ReportSummaryView.as_view()(
        authenticated_request("/api/reports/summary/", uuid.uuid4())
    )

    assert response.status_code == 200
    assert checked == [REPORTS_READ_PERMISSION]


def test_report_summary_uses_domain_user_uuid(monkeypatch):
    context = report_context()
    captured = {}
    monkeypatch.setattr(
        "apps.rt.views.get_admin_context",
        lambda request, required_permission: context,
    )
    monkeypatch.setattr(
        "apps.rt.views.build_report_queryset", lambda tenant_id, filters: object()
    )

    def fake_summary(queryset, user_id):
        captured["user_id"] = user_id
        return {
            "total": 0,
            "open": 0,
            "in_progress": 0,
            "waiting": 0,
            "closed": 0,
            "due_today": 0,
            "overdue": 0,
            "unassigned": 0,
            "assigned_to_me": 0,
            "by_priority": [],
            "by_status": [],
        }

    monkeypatch.setattr("apps.rt.views.build_report_summary", fake_summary)

    ReportSummaryView.as_view()(
        authenticated_request("/api/reports/summary/", uuid.uuid4())
    )

    assert captured["user_id"] == context.user.user_id
    assert isinstance(uuid.UUID(captured["user_id"]), uuid.UUID)


def test_report_cross_tenant_filter_returns_clean_404(monkeypatch):
    monkeypatch.setattr(
        "apps.rt.views.get_admin_context",
        lambda request, required_permission: report_context(),
    )
    monkeypatch.setattr(
        "apps.rt.views.build_report_queryset",
        lambda tenant_id, filters: (_ for _ in ()).throw(
            AdminDirectoryError(
                "not_found",
                "Flow filter not found for this tenant.",
                404,
                [{"field": "flow_id", "message": "Not found."}],
            )
        ),
    )

    response = ReportSummaryView.as_view()(
        authenticated_request(
            f"/api/reports/summary/?flow_id={uuid.uuid4()}", uuid.uuid4()
        )
    )

    assert response.status_code == 404
    assert response.data["code"] == "not_found"
    assert response.data["details"][0]["field"] == "flow_id"


def test_report_queryset_is_tenant_scoped_select_related_and_parameterized_fts():
    tenant_id = uuid.uuid4()
    queryset = build_report_queryset(tenant_id, {"q": "vpn"})
    tenant_lookup, fts_lookup = queryset.query.where.children

    assert tenant_lookup.rhs == tenant_id
    assert isinstance(fts_lookup.rhs, RawSQL)
    assert "CONTAINS" in fts_lookup.rhs.sql
    assert fts_lookup.rhs.params.count(str(tenant_id)) == 3
    assert fts_lookup.rhs.params.count('"vpn*"') == 3
    assert queryset.query.select_related == {
        "flowid": {},
        "statusid": {},
        "requesterid": {},
        "assigneeid": {},
    }


def test_report_summary_requires_jwt():
    request = APIRequestFactory().get("/api/reports/summary/")
    request.tenant_id = uuid.uuid4()
    response = ReportSummaryView.as_view()(request)
    assert response.status_code == 401


def test_openapi_includes_report_summary_filters():
    response = Client().get("/api/schema")
    assert response.status_code == 200
    assert b"/api/reports/summary/" in response.content
    assert b"status_category" in response.content
    assert b"due_from" in response.content
