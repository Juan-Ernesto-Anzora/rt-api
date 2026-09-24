import uuid
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import yaml
from django.db import connection
from django.test import Client
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.request import Request as DRFRequest
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.common.pagination import StandardPageNumberPagination
from apps.rt.models import Flow, Request, Status, Tenant, User
from apps.rt.serializers import RequestListSerializer
from apps.rt.services.admin_permissions import AdminPermissionError
from apps.rt.views import RequestViewSet


class RecordingQuerySet:
    def __init__(self, calls=None):
        self.calls = calls if calls is not None else []

    def filter(self, *args, **kwargs):
        self.calls.append(("filter", args, kwargs))
        return self

    def order_by(self, *fields):
        self.calls.append(("order_by", fields))
        return self

    def select_related(self, *fields):
        self.calls.append(("select_related", fields))
        return self


def list_queryset(monkeypatch, params, tenant_id=None, user_id=None):
    tenant_id = tenant_id or uuid.uuid4()
    user_id = user_id or uuid.uuid4()
    queryset = RecordingQuerySet()
    monkeypatch.setattr(
        "apps.rt.views.BaseTenantViewSet.get_queryset", lambda _: queryset
    )
    monkeypatch.setattr(
        "apps.rt.views.resolve_tenant_user",
        lambda auth_user, tenant: (
            SimpleNamespace(userid=user_id),
            SimpleNamespace(),
        ),
    )
    view = RequestViewSet()
    view.action = "list"
    view.request = SimpleNamespace(
        query_params=params, tenant_id=tenant_id, user=SimpleNamespace()
    )
    return view, queryset, user_id


def test_list_serializer_adds_compact_labels_and_keeps_existing_fields():
    tenant = Tenant(tenantid=uuid.uuid4())
    flow = Flow(flowid=uuid.uuid4(), tenantid=tenant, name="Support")
    status = Status(
        statusid=uuid.uuid4(),
        tenantid=tenant,
        flowid=flow,
        name="Open",
        category="open",
        isterminal=False,
    )
    requester = User(userid=uuid.uuid4(), displayname="Owner", email="o@example.test")
    assignee = User(userid=uuid.uuid4(), displayname="Agent", email="a@example.test")
    now = timezone.now()
    request = Request(
        requestid=uuid.uuid4(),
        tenantid=tenant,
        humanid="RT-1",
        title="VPN",
        description="Help",
        priority="high",
        flowid=flow,
        statusid=status,
        requesterid=requester,
        assigneeid=assignee,
        dueat=None,
        createdat=now,
        updatedat=now,
    )
    data = RequestListSerializer(request).data

    assert data["request_id"] == str(request.requestid)
    assert data["status_id"] == str(status.statusid)
    assert data["status"]["name"] == "Open"
    assert data["status"]["category"] == "open"
    assert data["requester"]["display_name"] == "Owner"
    assert data["assignee"]["display_name"] == "Agent"
    assert data["flow"] == {"flow_id": str(flow.flowid), "name": "Support"}
    assert data["due_at"] is None
    assert {"description", "custom_fields", "created_at", "updated_at"} <= data.keys()
    assert not {"comments", "attachments", "activity", "tags"} & data.keys()

    request.assigneeid = None
    assert RequestListSerializer(request).data["assignee"] is None


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({"mine": "true"}, "assigneeid_id"),
        ({"mine": "false"}, "assigneeid__isnull"),
        ({"requested_by_me": "true"}, "requesterid_id"),
        ({"closed": "true"}, "statusid__category__iexact"),
        ({"closed": "false"}, "statusid__isterminal"),
        ({"priority": "high"}, "priority"),
        ({"assignee": "unassigned"}, "assigneeid__isnull"),
    ],
)
def test_dashboard_filters_apply_before_stable_ordering(monkeypatch, params, expected):
    view, queryset, _ = list_queryset(monkeypatch, params)
    assert view.get_queryset() is queryset
    assert expected in str(queryset.calls)
    assert queryset.calls[-1] == ("order_by", ("-updatedat", "requestid"))


def test_combined_filters_and_ascending_order(monkeypatch):
    view, queryset, user_id = list_queryset(
        monkeypatch,
        {"mine": "true", "closed": "false", "priority": "high", "sort": "updated_at"},
    )
    view.get_queryset()
    assert ("filter", (), {"assigneeid_id": user_id}) in queryset.calls
    assert ("filter", (), {"priority": "high"}) in queryset.calls
    assert queryset.calls[-1] == ("order_by", ("updatedat", "requestid"))


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"mine": "true"},
        {"mine": "false"},
        {"requested_by_me": "true"},
        {"closed": "false"},
        {"priority": "high"},
        {"assignee": "unassigned"},
        {"mine": "true", "closed": "false", "priority": "high"},
    ],
)
def test_list_preserves_tenant_filter_before_queue_filters(monkeypatch, params):
    tenant_id = uuid.uuid4()
    user_id = uuid.uuid4()
    queryset = RecordingQuerySet()
    monkeypatch.setattr(
        "rest_framework.viewsets.ModelViewSet.get_queryset", lambda _: queryset
    )
    monkeypatch.setattr(
        "apps.rt.views.resolve_tenant_user",
        lambda *_: (SimpleNamespace(userid=user_id), SimpleNamespace()),
    )
    view = RequestViewSet()
    view.action = "list"
    view.request = SimpleNamespace(
        tenant_id=tenant_id,
        user=SimpleNamespace(),
        query_params=params,
    )

    view.get_queryset()

    assert queryset.calls[0] == ("filter", (), {"tenantid": tenant_id})
    assert queryset.calls[1][0] == "select_related"
    assert queryset.calls[-1][0] == "order_by"


def test_self_filter_uses_authenticated_tenant_identity(monkeypatch):
    tenant_id = uuid.uuid4()
    user_id = uuid.uuid4()
    view, queryset, _ = list_queryset(
        monkeypatch,
        {"mine": "true", "requested_by_me": "true", "user_id": str(uuid.uuid4())},
        tenant_id=tenant_id,
        user_id=user_id,
    )
    auth_user = view.request.user
    calls = []

    def resolve(user, tenant):
        calls.append((user, tenant))
        return SimpleNamespace(userid=user_id), SimpleNamespace()

    monkeypatch.setattr("apps.rt.views.resolve_tenant_user", resolve)
    view.get_queryset()

    assert calls == [(auth_user, tenant_id)]
    assert ("filter", (), {"assigneeid_id": user_id}) in queryset.calls
    assert ("filter", (), {"requesterid_id": user_id}) in queryset.calls


def test_pagination_envelope_and_page_size_with_equal_timestamps():
    paginator = StandardPageNumberPagination()
    request = DRFRequest(APIRequestFactory().get("/api/requests/?page=2&page_size=2"))
    rows = list(range(5))

    page = paginator.paginate_queryset(rows, request)
    response = paginator.get_paginated_response(page)

    assert response.data["count"] == 5
    assert response.data["results"] == [2, 3]
    assert "page=3" in response.data["next"]
    assert "page_size=2" in response.data["previous"]
    assert "page=2" not in response.data["previous"]


def test_request_list_action_returns_paginated_additive_rows(monkeypatch):
    tenant = Tenant(tenantid=uuid.uuid4())
    flow = Flow(flowid=uuid.uuid4(), tenantid=tenant, name="Support")
    status = Status(
        statusid=uuid.uuid4(),
        tenantid=tenant,
        flowid=flow,
        name="Open",
        category="open",
        isterminal=False,
    )
    user = User(userid=uuid.uuid4(), displayname="Owner", email="o@example.test")
    now = timezone.now()
    rows = [
        Request(
            requestid=uuid.uuid4(),
            tenantid=tenant,
            humanid=f"RT-{index}",
            title=f"VPN {index}",
            priority="normal",
            flowid=flow,
            statusid=status,
            requesterid=user,
            assigneeid=None,
            createdat=now,
            updatedat=now,
        )
        for index in range(3)
    ]
    monkeypatch.setattr(RequestViewSet, "get_queryset", lambda _: rows)
    request = APIRequestFactory().get("/api/requests/?page=2&page_size=2")
    force_authenticate(request, user=SimpleNamespace(is_authenticated=True))

    response = RequestViewSet.as_view({"get": "list"})(request)

    assert response.status_code == 200
    assert response.data["count"] == 3
    assert response.data["next"] is None
    assert response.data["previous"] is not None
    assert len(response.data["results"]) == 1
    assert response.data["results"][0]["status"]["name"] == "Open"
    assert response.data["results"][0]["assignee"] is None


@pytest.mark.parametrize("row_count", [0, 1, 10])
def test_preloaded_list_summaries_do_not_query_per_row(row_count):
    tenant = Tenant(tenantid=uuid.uuid4())
    flow = Flow(flowid=uuid.uuid4(), tenantid=tenant, name="Support")
    status = Status(
        statusid=uuid.uuid4(),
        tenantid=tenant,
        flowid=flow,
        name="Open",
        category="open",
        isterminal=False,
    )
    requester = User(userid=uuid.uuid4(), displayname="Owner", email="o@example.test")
    assignee = User(userid=uuid.uuid4(), displayname="Agent", email="a@example.test")
    now = timezone.now()
    rows = [
        Request(
            requestid=uuid.uuid4(),
            tenantid=tenant,
            humanid=f"RT-{index}",
            title="VPN",
            priority="high",
            flowid=flow,
            statusid=status,
            requesterid=requester,
            assigneeid=assignee if index % 2 else None,
            createdat=now,
            updatedat=now,
        )
        for index in range(row_count)
    ]

    with patch.object(
        connection, "cursor", side_effect=AssertionError("DB query")
    ) as cursor:
        data = RequestListSerializer(rows, many=True).data

    assert len(data) == row_count
    cursor.assert_not_called()


def test_openapi_documents_list_summaries_and_filters():
    response = Client().get("/api/schema")
    assert response.status_code == 200
    schema = yaml.safe_load(response.content)
    operation = schema["paths"]["/api/requests/"]["get"]
    names = {parameter["name"] for parameter in operation["parameters"]}
    assert {
        "mine",
        "requested_by_me",
        "closed",
        "priority",
        "assignee",
        "sort",
        "page",
        "page_size",
    } <= names
    fields = schema["components"]["schemas"]["RequestList"]["properties"]
    assert {"status", "requester", "assignee", "flow"} <= fields.keys()
    assert fields["assignee"]["nullable"] is True
    parameters = {item["name"]: item for item in operation["parameters"]}
    assert set(parameters["priority"]["schema"]["enum"]) == {
        "low",
        "normal",
        "high",
        "urgent",
    }
    assert set(parameters["sort"]["schema"]["enum"]) == {"updated_at", "-updated_at"}


def test_only_list_uses_additive_read_serializer():
    view = RequestViewSet()
    view.action = "list"
    assert view.get_serializer_class() is RequestListSerializer
    view.action = "create"
    assert view.get_serializer_class() is not RequestListSerializer


def test_list_requires_authentication_and_tenant_header():
    response = RequestViewSet.as_view({"get": "list"})(
        APIRequestFactory().get("/api/requests/")
    )
    assert response.status_code == 401

    response = Client().get("/api/requests/")
    assert response.status_code == 400
    assert response.json()["code"] == "tenant_required"


@pytest.mark.parametrize(
    "params",
    [
        {"mine": "perhaps"},
        {"requested_by_me": "maybe"},
        {"closed": "unknown"},
        {"priority": "critical"},
        {"assignee": "someone"},
        {"sort": "title"},
    ],
)
def test_invalid_list_filters_raise_validation_error(monkeypatch, params):
    view, _, _ = list_queryset(monkeypatch, params)
    with pytest.raises(ValidationError):
        view.get_queryset()


def test_invalid_filter_returns_http_400(monkeypatch):
    monkeypatch.setattr(
        "apps.rt.views.BaseTenantViewSet.get_queryset", lambda _: RecordingQuerySet()
    )
    request = APIRequestFactory().get("/api/requests/?priority=critical")
    request.tenant_id = uuid.uuid4()
    force_authenticate(request, user=SimpleNamespace(is_authenticated=True))

    response = RequestViewSet.as_view({"get": "list"})(request)

    assert response.status_code == 400
    assert response.data["code"] == "validation_error"


def test_my_filter_fails_closed_without_tenant_user(monkeypatch):
    view, _, _ = list_queryset(monkeypatch, {"mine": "false"})
    monkeypatch.setattr(
        "apps.rt.views.resolve_tenant_user",
        lambda *_: (_ for _ in ()).throw(
            AdminPermissionError("permission_denied", "No membership")
        ),
    )
    with pytest.raises(PermissionDenied):
        view.get_queryset()
