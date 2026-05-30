import json
import uuid
from types import SimpleNamespace

from django.core.exceptions import FieldError
from django.utils import timezone

from apps.rt.models import Flow, Membership, Request, Status, Tenant, User
from apps.rt.serializers import RequestSerializer
from apps.rt.views import RequestViewSet


def create_payload(flow_id, status_id, requester_id, assignee_id=None):
    payload = {
        "title": "Sprint 2 create request",
        "description": "Created by API test.",
        "flow_id": str(flow_id),
        "status_id": str(status_id),
        "requester_id": str(requester_id),
        "priority": "NORMAL",
        "due_at": "2026-05-29T17:00:00Z",
        "custom_fields": '{"source":"pytest"}',
    }
    if assignee_id is not None:
        payload["assignee_id"] = str(assignee_id)
    return payload


class FakeExistsQuerySet:
    def __init__(self, exists):
        self._exists = exists

    def exists(self):
        return self._exists


def patch_create_lookups(
    monkeypatch,
    tenant,
    flow_id,
    requester_id=None,
    assignee_id=None,
    status_flow_id=None,
    requester_in_tenant=True,
    assignee_in_tenant=True,
):
    status_flow_id = status_flow_id or flow_id
    requester_id = requester_id or uuid.uuid4()
    assignee_id = assignee_id or uuid.uuid4()

    def flow_get(**kwargs):
        assert kwargs == {"flowid": flow_id, "tenantid": tenant.tenantid}
        return Flow(flowid=flow_id, tenantid=tenant, name="IT Support")

    def status_get(**kwargs):
        return Status(
            statusid=kwargs["statusid"],
            tenantid=tenant,
            flowid=Flow(flowid=status_flow_id, tenantid=tenant, name="IT Support"),
            name="Open",
            category="open",
            isterminal=False,
        )

    def membership_filter(**kwargs):
        assert kwargs["tenantid_id"] == tenant.tenantid
        user_id = kwargs["userid_id"]
        if user_id == requester_id:
            return FakeExistsQuerySet(requester_in_tenant)
        if user_id == assignee_id:
            return FakeExistsQuerySet(assignee_in_tenant)
        return FakeExistsQuerySet(True)

    monkeypatch.setattr(Flow.objects, "get", flow_get)
    monkeypatch.setattr(Status.objects, "get", status_get)
    monkeypatch.setattr(Membership.objects, "filter", membership_filter)


def test_request_serializer_accepts_public_create_fields(monkeypatch):
    tenant = Tenant(tenantid=uuid.uuid4())
    flow_id = uuid.uuid4()
    status_id = uuid.uuid4()
    requester_id = uuid.uuid4()
    assignee_id = uuid.uuid4()
    patch_create_lookups(
        monkeypatch,
        tenant,
        flow_id,
        requester_id=requester_id,
        assignee_id=assignee_id,
    )

    serializer = RequestSerializer(
        data=create_payload(flow_id, status_id, requester_id, assignee_id),
        context={"tenant_id": tenant.tenantid},
    )

    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data["flowid_id"] == flow_id
    assert serializer.validated_data["statusid_id"] == status_id
    assert serializer.validated_data["requesterid_id"] == requester_id
    assert serializer.validated_data["assigneeid_id"] == assignee_id
    assert serializer.validated_data["priority"] == "normal"
    assert serializer.validated_data["customfields"] == '{"source":"pytest"}'


def test_request_serializer_rejects_requester_not_in_tenant(monkeypatch):
    tenant = Tenant(tenantid=uuid.uuid4())
    flow_id = uuid.uuid4()
    requester_id = uuid.uuid4()
    patch_create_lookups(
        monkeypatch,
        tenant,
        flow_id,
        requester_id=requester_id,
        requester_in_tenant=False,
    )

    serializer = RequestSerializer(
        data=create_payload(flow_id, uuid.uuid4(), requester_id),
        context={"tenant_id": tenant.tenantid},
    )

    assert not serializer.is_valid()
    assert (
        serializer.errors["requester_id"][0] == "User is not a member of this tenant."
    )


def test_request_serializer_rejects_assignee_not_in_tenant(monkeypatch):
    tenant = Tenant(tenantid=uuid.uuid4())
    flow_id = uuid.uuid4()
    requester_id = uuid.uuid4()
    assignee_id = uuid.uuid4()
    patch_create_lookups(
        monkeypatch,
        tenant,
        flow_id,
        requester_id=requester_id,
        assignee_id=assignee_id,
        assignee_in_tenant=False,
    )

    serializer = RequestSerializer(
        data=create_payload(flow_id, uuid.uuid4(), requester_id, assignee_id),
        context={"tenant_id": tenant.tenantid},
    )

    assert not serializer.is_valid()
    assert serializer.errors["assignee_id"][0] == "User is not a member of this tenant."


def test_request_serializer_uses_public_response_fields():
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
    requester = User(userid=uuid.uuid4(), email="requester@example.com")
    assignee = User(userid=uuid.uuid4(), email="assignee@example.com")
    now = timezone.now()
    rt_request = Request(
        requestid=uuid.uuid4(),
        tenantid=tenant,
        humanid="RT-2026-000123",
        title="Public response",
        description="Clean public fields.",
        flowid=flow,
        statusid=status,
        requesterid=requester,
        assigneeid=assignee,
        priority="normal",
        customfields='{"source":"pytest"}',
        dueat=now,
        createdat=now,
        updatedat=now,
    )

    data = RequestSerializer(rt_request).data

    assert data["request_id"] == str(rt_request.requestid)
    assert data["human_id"] == "RT-2026-000123"
    assert data["flow_id"] == str(flow.flowid)
    assert data["status_id"] == str(status.statusid)
    assert data["requester_id"] == str(requester.userid)
    assert data["assignee_id"] == str(assignee.userid)
    assert data["custom_fields"] == '{"source":"pytest"}'
    assert data["due_at"]
    assert "flowid_id" not in data
    assert "statusid_id" not in data
    assert "requesterid_id" not in data
    assert "assigneeid_id" not in data


def test_request_serializer_rejects_internal_create_fields(monkeypatch):
    tenant = Tenant(tenantid=uuid.uuid4())
    flow_id = uuid.uuid4()
    status_id = uuid.uuid4()
    requester_id = uuid.uuid4()
    patch_create_lookups(monkeypatch, tenant, flow_id, requester_id=requester_id)

    serializer = RequestSerializer(
        data={
            "title": "Legacy payload",
            "description": "Should not be accepted.",
            "flowid_id": str(flow_id),
            "statusid_id": str(status_id),
            "requesterid_id": str(requester_id),
            "priority": "normal",
        },
        context={"tenant_id": tenant.tenantid},
    )

    assert not serializer.is_valid()
    assert "flow_id" in serializer.errors
    assert "status_id" in serializer.errors
    assert "requester_id" in serializer.errors


def test_request_serializer_rejects_status_from_another_flow(monkeypatch):
    tenant = Tenant(tenantid=uuid.uuid4())
    flow_id = uuid.uuid4()
    other_flow_id = uuid.uuid4()
    patch_create_lookups(monkeypatch, tenant, flow_id, status_flow_id=other_flow_id)

    serializer = RequestSerializer(
        data=create_payload(flow_id, uuid.uuid4(), uuid.uuid4()),
        context={"tenant_id": tenant.tenantid},
    )

    assert not serializer.is_valid()
    assert (
        serializer.errors["status_id"][0] == "Status must belong to the selected flow."
    )


def test_request_serializer_rejects_cross_tenant_lookup(monkeypatch):
    tenant = Tenant(tenantid=uuid.uuid4())

    def flow_get(**kwargs):
        raise Flow.DoesNotExist

    monkeypatch.setattr(Flow.objects, "get", flow_get)

    serializer = RequestSerializer(
        data=create_payload(uuid.uuid4(), uuid.uuid4(), uuid.uuid4()),
        context={"tenant_id": tenant.tenantid},
    )

    assert not serializer.is_valid()
    assert serializer.errors["flow_id"][0] == "Not found for this tenant."


def test_request_create_returns_json_validation_shape_for_bad_uuid():
    tenant_id = uuid.uuid4()
    request = SimpleNamespace(
        data={
            "title": "Bad UUID",
            "description": "Should fail cleanly.",
            "flow_id": "not-a-guid",
            "status_id": str(uuid.uuid4()),
            "requester_id": str(uuid.uuid4()),
            "priority": "normal",
        },
        tenant_id=tenant_id,
    )
    view = RequestViewSet()
    view.request = request
    view.action = "create"
    view.format_kwarg = None

    response = view.create(request)

    assert response.status_code == 400
    assert response.data["code"] == "validation_error"
    assert response.data["message"] == "Invalid request payload."
    assert response.data["details"][0]["field"] == "flow_id"


def test_request_create_post_does_not_raise_field_error_for_user_tenant_validation(
    monkeypatch,
):
    tenant = Tenant(tenantid=uuid.uuid4())
    flow_id = uuid.uuid4()
    status_id = uuid.uuid4()
    requester_id = uuid.uuid4()
    assignee_id = uuid.uuid4()
    patch_create_lookups(
        monkeypatch,
        tenant,
        flow_id,
        requester_id=requester_id,
        assignee_id=assignee_id,
    )
    monkeypatch.setattr(
        User.objects,
        "get",
        lambda **kwargs: (_ for _ in ()).throw(
            FieldError("Cannot resolve keyword 'tenantid' into field.")
        ),
    )
    now = timezone.now()
    rt_request = Request(
        requestid=uuid.uuid4(),
        tenantid=tenant,
        humanid="RT-2026-000555",
        title="No FieldError",
        description="Membership validation only.",
        flowid=Flow(flowid=flow_id, tenantid=tenant, name="IT Support"),
        statusid=Status(
            statusid=status_id,
            tenantid=tenant,
            flowid=Flow(flowid=flow_id, tenantid=tenant),
            name="Open",
            category="open",
            isterminal=False,
        ),
        requesterid=User(userid=requester_id, email="requester@example.com"),
        assigneeid=User(userid=assignee_id, email="assignee@example.com"),
        priority="normal",
        createdat=now,
        updatedat=now,
    )
    request = SimpleNamespace(
        data=create_payload(flow_id, status_id, requester_id, assignee_id),
        tenant_id=tenant.tenantid,
    )
    view = RequestViewSet()
    view.request = request
    view.action = "create"
    view.format_kwarg = None
    view.perform_create = lambda serializer: rt_request

    response = view.create(request)

    assert response.status_code == 201
    assert response.data["request_id"] == str(rt_request.requestid)


def test_request_create_missing_tenant_returns_json_error():
    request = SimpleNamespace(data={}, tenant_id=None)
    view = RequestViewSet()
    view.request = request
    view.action = "create"
    view.format_kwarg = None

    response = view.create(request)

    assert response.status_code == 400
    assert response.data == {
        "code": "tenant_required",
        "message": "Tenant context missing.",
        "details": [],
    }


def test_request_perform_create_generates_human_id_and_activity(monkeypatch):
    tenant_id = uuid.uuid4()
    flow_id = uuid.uuid4()
    status_id = uuid.uuid4()
    requester_id = uuid.uuid4()
    assignee_id = uuid.uuid4()
    tenant = Tenant(tenantid=tenant_id)
    requester = User(userid=requester_id, email="requester@example.com")
    assignee = User(userid=assignee_id, email="assignee@example.com")
    saved_kwargs = {}
    created_activities = []

    class FakeSerializer:
        validated_data = {
            "title": "Created request",
            "description": "Created by perform_create.",
            "flowid_id": flow_id,
            "statusid_id": status_id,
            "requesterid_id": requester_id,
            "assigneeid_id": assignee_id,
            "priority": "normal",
        }

        def save(self, **kwargs):
            saved_kwargs.update(kwargs)
            return Request(
                requestid=uuid.uuid4(),
                tenantid=tenant,
                humanid=kwargs["humanid"],
                title=self.validated_data["title"],
                description=self.validated_data["description"],
                flowid=Flow(flowid=flow_id, tenantid=tenant, name="IT Support"),
                statusid=Status(
                    statusid=status_id,
                    tenantid=tenant,
                    flowid=Flow(flowid=flow_id, tenantid=tenant),
                    name="Open",
                    category="open",
                    isterminal=False,
                ),
                requesterid=requester,
                assigneeid=assignee,
                priority=self.validated_data["priority"],
                createdat=kwargs["createdat"],
                updatedat=kwargs["updatedat"],
            )

    monkeypatch.setattr(
        "apps.rt.views.generate_human_id", lambda tenant: "RT-2026-000777"
    )
    monkeypatch.setattr(
        "apps.rt.views.Activity.objects.create",
        lambda **kwargs: created_activities.append(kwargs),
    )

    view = RequestViewSet()
    view.request = SimpleNamespace(tenant_id=tenant_id)
    perform_create = RequestViewSet.perform_create.__wrapped__

    rt_request = perform_create(view, FakeSerializer())

    assert rt_request.humanid == "RT-2026-000777"
    assert saved_kwargs["tenantid_id"] == tenant_id
    assert saved_kwargs["flowid_id"] == flow_id
    assert saved_kwargs["statusid_id"] == status_id
    assert saved_kwargs["requesterid_id"] == requester_id
    assert saved_kwargs["assigneeid_id"] == assignee_id
    assert saved_kwargs["createdat"] == saved_kwargs["updatedat"]
    assert len(created_activities) == 1
    activity = created_activities[0]
    assert activity["type"] == "request.created"
    assert activity["tenantid"] == tenant
    assert activity["requestid"] == rt_request
    assert activity["actorid"] == requester
    assert json.loads(activity["payload"]) == {
        "human_id": "RT-2026-000777",
        "title": "Created request",
        "flow_id": str(flow_id),
        "status_id": str(status_id),
        "requester_id": str(requester_id),
        "assignee_id": str(assignee_id),
    }
