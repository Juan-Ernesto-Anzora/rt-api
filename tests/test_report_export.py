import csv
import io
import uuid
from types import SimpleNamespace

from django.test import Client, override_settings
from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.rt.models import Flow, Request, Status, Tenant, User
from apps.rt.services.admin_permissions import REPORTS_EXPORT_PERMISSION
from apps.rt.services.report_service import CSV_COLUMNS, csv_safe_cell, iter_request_csv
from apps.rt.views import ReportRequestExportView


class FakeExportQuerySet:
    def __init__(self, rows):
        self.rows = rows
        self.ordering = None

    def order_by(self, *fields):
        self.ordering = fields
        return self

    def count(self):
        return len(self.rows)

    def iterator(self, chunk_size):
        assert chunk_size == 1000
        return iter(self.rows)


def make_request(title='VPN, "quoted"\nline'):
    tenant = Tenant(tenantid=uuid.uuid4())
    flow = Flow(flowid=uuid.uuid4(), tenantid=tenant, name="IT Support")
    status = Status(
        statusid=uuid.uuid4(),
        tenantid=tenant,
        flowid=flow,
        name="Open",
        category="open",
        isterminal=False,
    )
    requester = User(
        userid=uuid.uuid4(), displayname="Requester", email="r@example.com"
    )
    now = timezone.now()
    return Request(
        requestid=uuid.uuid4(),
        tenantid=tenant,
        humanid="RT-2026-000001",
        title=title,
        flowid=flow,
        statusid=status,
        priority="normal",
        requesterid=requester,
        assigneeid=None,
        dueat=None,
        createdat=now,
        updatedat=now,
    )


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


def export_context():
    return SimpleNamespace(
        user=SimpleNamespace(user_id=str(uuid.uuid4())),
        permissions=[REPORTS_EXPORT_PERMISSION],
    )


def test_csv_writer_escapes_commas_quotes_and_line_breaks():
    content = "".join(iter_request_csv(FakeExportQuerySet([make_request()])))
    rows = list(csv.reader(io.StringIO(content)))

    assert rows[0] == CSV_COLUMNS
    assert rows[1][2] == 'VPN, "quoted"\nline'
    assert len(rows[1]) == len(CSV_COLUMNS)


def test_csv_formula_prefixes_are_neutralized():
    for value in ("=SUM(A1:A2)", "+cmd", "-1+2", "@lookup", "\tvalue", "\rvalue"):
        assert csv_safe_cell(value) == f"'{value}"
    assert csv_safe_cell("ordinary") == "ordinary"


def test_export_requires_format_csv(monkeypatch):
    monkeypatch.setattr(
        "apps.rt.views.get_admin_context",
        lambda request, required_permission: export_context(),
    )
    response = ReportRequestExportView.as_view()(
        authenticated_request("/api/reports/requests/export/", uuid.uuid4())
    )
    assert response.status_code == 400
    assert response.data["code"] == "validation_error"


@override_settings(REPORT_EXPORT_MAX_ROWS=10)
def test_export_is_downloadable_safe_csv_and_audited(monkeypatch):
    tenant_id = uuid.uuid4()
    queryset = FakeExportQuerySet([make_request(title="=formula")])
    audits = []
    checked = []

    def fake_context(request, required_permission):
        checked.append(required_permission)
        return export_context()

    monkeypatch.setattr("apps.rt.views.get_admin_context", fake_context)
    monkeypatch.setattr(
        "apps.rt.views.build_report_queryset", lambda tenant_id, filters: queryset
    )
    monkeypatch.setattr(
        "apps.rt.views.write_admin_audit", lambda *args: audits.append(args)
    )

    response = ReportRequestExportView.as_view()(
        authenticated_request("/api/reports/requests/export/?format=csv", tenant_id)
    )
    content = b"".join(response.streaming_content).decode("utf-8")

    assert response.status_code == 200
    assert response["Content-Type"] == "text/csv; charset=utf-8"
    assert response["Content-Disposition"].startswith(
        'attachment; filename="rt-requests-'
    )
    assert response["Content-Disposition"].endswith('Z.csv"')
    assert checked == [REPORTS_EXPORT_PERMISSION]
    assert queryset.ordering == ("-updatedat", "requestid")
    assert "'=formula" in content
    assert len(audits) == 1
    assert audits[0][2] == "report.requests.exported"
    assert audits[0][3]["row_count"] == 1


@override_settings(REPORT_EXPORT_MAX_ROWS=0)
def test_export_limit_rejects_without_audit(monkeypatch):
    audits = []
    monkeypatch.setattr(
        "apps.rt.views.get_admin_context",
        lambda request, required_permission: export_context(),
    )
    monkeypatch.setattr(
        "apps.rt.views.build_report_queryset",
        lambda tenant_id, filters: FakeExportQuerySet([make_request()]),
    )
    monkeypatch.setattr(
        "apps.rt.views.write_admin_audit", lambda *args: audits.append(args)
    )

    response = ReportRequestExportView.as_view()(
        authenticated_request("/api/reports/requests/export/?format=csv", uuid.uuid4())
    )

    assert response.status_code == 400
    assert response.data["code"] == "export_limit_exceeded"
    assert audits == []


def test_openapi_includes_csv_export_media_type():
    response = Client().get("/api/schema")
    assert response.status_code == 200
    assert b"/api/reports/requests/export/" in response.content
    assert b"text/csv" in response.content
