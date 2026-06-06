import uuid
from types import SimpleNamespace

from django.test import Client
from django.urls import resolve

from apps.rt.serializers import DashboardSummarySerializer
from apps.rt.views import (
    DashboardSummaryView,
    build_dashboard_summary,
    count_assigned_to_me,
)


class FakeDashboardQuerySet:
    def __init__(self, operations=None):
        self.operations = operations or []

    def filter(self, **kwargs):
        return FakeDashboardQuerySet(self.operations + [("filter", kwargs)])

    def exclude(self, **kwargs):
        return FakeDashboardQuerySet(self.operations + [("exclude", kwargs)])

    def count(self):
        filters = [
            kwargs for operation, kwargs in self.operations if operation == "filter"
        ]
        excludes = [
            kwargs for operation, kwargs in self.operations if operation == "exclude"
        ]

        if {"statusid__category__iexact": "open"} in filters:
            return 4
        if {"statusid__category__iexact": "in_progress"} in filters:
            return 3
        if {"statusid__category__iexact": "waiting"} in filters:
            return 2
        if {"statusid__category__iexact": "closed"} in filters:
            return 5
        if {"dueat__date": self.today} in filters:
            return 6
        if {"dueat__date__lt": self.today} in filters:
            return 7
        if {"assigneeid_id": self.user_id} in filters:
            return 8
        if {"assigneeid__isnull": True} in filters:
            assert {"statusid__category__iexact": "closed"} in excludes
            assert {"statusid__isterminal": True} in excludes
            return 9
        return 0


def test_dashboard_summary_routes_resolve():
    assert resolve("/api/dashboard/summary").url_name == "dashboard-summary"
    assert resolve("/api/dashboard/summary/").url_name == "dashboard-summary-slash"


def test_dashboard_summary_serializer_public_fields():
    data = DashboardSummarySerializer(
        {
            "open": 1,
            "in_progress": 2,
            "waiting": 3,
            "closed": 4,
            "due_today": 5,
            "overdue": 6,
            "assigned_to_me": 7,
            "unassigned": 8,
        }
    ).data

    assert data == {
        "open": 1,
        "in_progress": 2,
        "waiting": 3,
        "closed": 4,
        "due_today": 5,
        "overdue": 6,
        "assigned_to_me": 7,
        "unassigned": 8,
    }


def test_build_dashboard_summary_counts_tenant_queryset(monkeypatch):
    user_id = uuid.uuid4()
    today = object()
    FakeDashboardQuerySet.today = today
    FakeDashboardQuerySet.user_id = user_id
    monkeypatch.setattr("apps.rt.views.timezone.localdate", lambda: today)

    summary = build_dashboard_summary(FakeDashboardQuerySet(), user_id=user_id)

    assert summary == {
        "open": 4,
        "in_progress": 3,
        "waiting": 2,
        "closed": 5,
        "due_today": 6,
        "overdue": 7,
        "assigned_to_me": 8,
        "unassigned": 9,
    }


def test_count_assigned_to_me_returns_zero_for_non_uuid_user_id():
    assert count_assigned_to_me(FakeDashboardQuerySet(), user_id=1) == 0
    assert count_assigned_to_me(FakeDashboardQuerySet(), user_id=None) == 0


def test_dashboard_summary_view_requires_tenant_context():
    request = SimpleNamespace(tenant_id=None, user=SimpleNamespace(id=uuid.uuid4()))

    response = DashboardSummaryView().get(request)

    assert response.status_code == 400
    assert response.data == {
        "code": "tenant_required",
        "message": "Tenant context missing.",
        "details": [],
    }


def test_dashboard_summary_view_uses_tenant_scoped_request_queryset(monkeypatch):
    tenant_id = uuid.uuid4()
    user_id = uuid.uuid4()
    fake_qs = FakeDashboardQuerySet()
    captured_filter = {}
    captured_summary = {}

    def fake_request_filter(**kwargs):
        captured_filter.update(kwargs)
        return fake_qs

    def fake_summary(**kwargs):
        captured_summary.update(kwargs)
        return {
            "open": 1,
            "in_progress": 2,
            "waiting": 3,
            "closed": 4,
            "due_today": 5,
            "overdue": 6,
            "assigned_to_me": 7,
            "unassigned": 8,
        }

    monkeypatch.setattr("apps.rt.views.Request.objects.filter", fake_request_filter)
    monkeypatch.setattr("apps.rt.views.build_dashboard_summary", fake_summary)
    request = SimpleNamespace(tenant_id=tenant_id, user=SimpleNamespace(id=user_id))

    response = DashboardSummaryView().get(request)

    assert response.status_code == 200
    assert response.data["open"] == 1
    assert captured_filter == {"tenantid": tenant_id}
    assert captured_summary == {"queryset": fake_qs, "user_id": user_id}


def test_openapi_schema_includes_dashboard_summary_path():
    response = Client().get("/api/schema")

    assert response.status_code == 200
    assert b"/api/dashboard/summary/" in response.content
