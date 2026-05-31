import uuid
from types import SimpleNamespace

import pytest
from django.test import Client
from django.urls import resolve
from rest_framework.exceptions import NotFound

from apps.rt.models import Flow, Status, Tenant, User
from apps.rt.serializers import (
    FlowLookupSerializer,
    StatusLookupSerializer,
    UserLookupSerializer,
)
from apps.rt.views import FlowViewSet, UserLookupViewSet


class FakeQuerySet:
    def __init__(self, items=None):
        self.items = items or []
        self.calls = []

    def order_by(self, *fields):
        self.calls.append(("order_by", fields))
        return self

    def filter(self, *args, **kwargs):
        self.calls.append(("filter", args, kwargs))
        return self

    def __iter__(self):
        return iter(self.items)


def test_lookup_routes_resolve():
    assert resolve("/api/flows/").url_name == "flows-list"
    assert resolve(f"/api/flows/{uuid.uuid4()}/statuses/").url_name == "flows-statuses"
    assert resolve("/api/users/").url_name == "users-list"


def test_lookup_serializers_return_public_fields():
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
    user = User(
        userid=uuid.uuid4(),
        email="agent@example.com",
        displayname="Agent One",
    )

    assert FlowLookupSerializer(flow).data == {
        "flow_id": str(flow.flowid),
        "name": "IT Support",
    }
    assert StatusLookupSerializer(status).data == {
        "status_id": str(status.statusid),
        "flow_id": str(flow.flowid),
        "name": "Open",
        "category": "open",
        "is_terminal": False,
    }
    assert UserLookupSerializer(user).data == {
        "user_id": str(user.userid),
        "display_name": "Agent One",
        "email": "agent@example.com",
    }


def test_flows_queryset_is_tenant_scoped(monkeypatch):
    tenant_id = uuid.uuid4()
    fake_qs = FakeQuerySet()
    captured = {}

    def fake_filter(**kwargs):
        captured.update(kwargs)
        return fake_qs

    monkeypatch.setattr(Flow.objects, "filter", fake_filter)
    view = FlowViewSet()
    view.request = SimpleNamespace(tenant_id=tenant_id)

    queryset = view.get_queryset()

    assert queryset is fake_qs
    assert captured == {"tenantid": tenant_id}
    assert fake_qs.calls == [("order_by", ("name",))]


def test_flow_statuses_are_tenant_and_flow_scoped(monkeypatch):
    tenant_id = uuid.uuid4()
    flow_id = uuid.uuid4()
    flow = Flow(flowid=flow_id, tenantid=Tenant(tenantid=tenant_id), name="IT Support")
    statuses = [
        Status(
            statusid=uuid.uuid4(),
            tenantid=flow.tenantid,
            flowid=flow,
            name="Open",
            category="open",
            isterminal=False,
        )
    ]
    captured_get = {}
    captured_filter = {}

    def fake_get(**kwargs):
        captured_get.update(kwargs)
        return flow

    def fake_filter(**kwargs):
        captured_filter.update(kwargs)
        return FakeQuerySet(statuses)

    monkeypatch.setattr(Flow.objects, "get", fake_get)
    monkeypatch.setattr(Status.objects, "filter", fake_filter)
    view = FlowViewSet()
    view.request = SimpleNamespace(tenant_id=tenant_id)
    view.kwargs = {"flow_id": str(flow_id)}

    response = view.statuses(view.request, flow_id=str(flow_id))

    assert response.status_code == 200
    assert response.data[0]["category"] == "open"
    assert captured_get == {"flowid": str(flow_id), "tenantid": tenant_id}
    assert captured_filter == {"tenantid": tenant_id, "flowid": flow_id}


def test_flow_statuses_cross_tenant_flow_returns_not_found(monkeypatch):
    def fake_get(**kwargs):
        raise Flow.DoesNotExist

    monkeypatch.setattr(Flow.objects, "get", fake_get)
    view = FlowViewSet()
    view.request = SimpleNamespace(tenant_id=uuid.uuid4())
    view.kwargs = {"flow_id": str(uuid.uuid4())}

    with pytest.raises(NotFound) as exc:
        view.statuses(view.request, flow_id=view.kwargs["flow_id"])

    assert exc.value.detail["code"] == "not_found"


def test_user_lookup_queryset_uses_membership_and_search(monkeypatch):
    tenant_id = uuid.uuid4()
    member_ids = [uuid.uuid4()]
    fake_qs = FakeQuerySet()
    captured_membership = {}
    captured_users = {}

    class FakeMembershipQuery:
        def values_list(self, *fields, **kwargs):
            assert fields == ("userid_id",)
            assert kwargs == {"flat": True}
            return member_ids

    def fake_membership_filter(**kwargs):
        captured_membership.update(kwargs)
        return FakeMembershipQuery()

    def fake_user_filter(**kwargs):
        captured_users.update(kwargs)
        return fake_qs

    monkeypatch.setattr(
        "apps.rt.views.Membership.objects.filter", fake_membership_filter
    )
    monkeypatch.setattr(User.objects, "filter", fake_user_filter)
    view = UserLookupViewSet()
    view.request = SimpleNamespace(
        tenant_id=tenant_id,
        query_params={"search": "ana"},
    )

    queryset = view.get_queryset()

    assert queryset is fake_qs
    assert captured_membership == {"tenantid": tenant_id}
    assert captured_users == {"userid__in": member_ids}
    assert fake_qs.calls[0] == ("order_by", ("displayname", "email"))
    assert fake_qs.calls[1][0] == "filter"


def test_openapi_schema_includes_lookup_paths():
    response = Client().get("/api/schema")

    assert response.status_code == 200
    assert b"/api/flows/" in response.content
    assert b"/api/flows/{flow_id}/statuses/" in response.content
    assert b"/api/users/" in response.content
