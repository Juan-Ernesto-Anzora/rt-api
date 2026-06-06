import json
import uuid
from types import SimpleNamespace

from django.test import Client
from django.urls import resolve
from django.utils import timezone

from apps.rt.models import Flow, Request, Status, Tenant, Transition, User
from apps.rt.serializers import (
    RequestCloseReopenSerializer,
    RequestTransitionSerializer,
    TransitionLookupSerializer,
)
from apps.rt.views import (
    RequestViewSet,
    apply_transition,
    find_transition_by_target_category,
    get_available_transitions,
)


class FakeTransitionQuerySet:
    def __init__(self, transitions):
        self.transitions = transitions
        self.select_related_args = None
        self.get_kwargs = None

    def select_related(self, *fields):
        self.select_related_args = fields
        return self

    def get(self, **kwargs):
        self.get_kwargs = kwargs
        for transition in self.transitions:
            if transition.transitionid == kwargs["transitionid"]:
                return transition
        raise Transition.DoesNotExist

    def __iter__(self):
        return iter(self.transitions)


def build_request_and_transition(to_category="in_progress", terminal=False):
    tenant = Tenant(tenantid=uuid.uuid4())
    flow = Flow(flowid=uuid.uuid4(), tenantid=tenant, name="IT Support")
    requester = User(userid=uuid.uuid4(), email="requester@example.com")
    from_status = Status(
        statusid=uuid.uuid4(),
        tenantid=tenant,
        flowid=flow,
        name="Open",
        category="open",
        isterminal=False,
    )
    to_status = Status(
        statusid=uuid.uuid4(),
        tenantid=tenant,
        flowid=flow,
        name="Next",
        category=to_category,
        isterminal=terminal,
    )
    now = timezone.now()
    rt_request = Request(
        requestid=uuid.uuid4(),
        tenantid=tenant,
        humanid="RT-2026-000321",
        title="Transition test",
        description="Workflow transition.",
        flowid=flow,
        statusid=from_status,
        requesterid=requester,
        priority="normal",
        createdat=now,
        updatedat=now,
    )
    transition = Transition(
        transitionid=uuid.uuid4(),
        flowid=flow,
        fromstatusid=from_status,
        tostatusid=to_status,
    )
    return rt_request, transition


def test_transition_routes_resolve():
    request_id = uuid.uuid4()

    assert (
        resolve(f"/api/requests/{request_id}/available-transitions/").url_name
        == "requests-available-transitions"
    )
    assert (
        resolve(f"/api/requests/{request_id}/transition/").url_name
        == "requests-transition"
    )
    assert resolve(f"/api/requests/{request_id}/close/").url_name == "requests-close"
    assert resolve(f"/api/requests/{request_id}/reopen/").url_name == "requests-reopen"


def test_transition_serializers_use_public_fields():
    rt_request, transition = build_request_and_transition()

    assert RequestTransitionSerializer(
        data={"transition_id": str(transition.transitionid), "comment": "Moving"}
    ).is_valid()
    assert RequestCloseReopenSerializer(data={"comment": "Done"}).is_valid()
    data = TransitionLookupSerializer(transition).data

    assert data["transition_id"] == str(transition.transitionid)
    assert data["from_status_id"] == str(rt_request.statusid_id)
    assert data["to_status_id"] == str(transition.tostatusid_id)
    assert data["to_status"]["category"] == "in_progress"


def test_available_transitions_filters_current_flow_and_status(monkeypatch):
    rt_request, transition = build_request_and_transition()
    fake_qs = FakeTransitionQuerySet([transition])
    captured = {}

    def fake_filter(**kwargs):
        captured.update(kwargs)
        return fake_qs

    monkeypatch.setattr("apps.rt.views.Transition.objects.filter", fake_filter)

    transitions = get_available_transitions(rt_request)

    assert transitions is fake_qs
    assert fake_qs.select_related_args == ("tostatusid",)
    assert captured == {
        "flowid": rt_request.flowid_id,
        "fromstatusid": rt_request.statusid_id,
    }


def test_available_transitions_action_returns_lookup_data(monkeypatch):
    rt_request, transition = build_request_and_transition()
    monkeypatch.setattr(
        "apps.rt.views.get_available_transitions",
        lambda request: [transition],
    )
    view = RequestViewSet()
    view.request = SimpleNamespace(tenant_id=rt_request.tenantid_id)
    view.get_object = lambda: rt_request

    response = view.available_transitions(view.request, pk=str(rt_request.requestid))

    assert response.status_code == 200
    assert response.data[0]["transition_id"] == str(transition.transitionid)


def test_transition_action_rejects_unavailable_transition(monkeypatch):
    rt_request, transition = build_request_and_transition()
    fake_qs = FakeTransitionQuerySet([transition])
    requested_transition_id = uuid.uuid4()
    monkeypatch.setattr(
        "apps.rt.views.get_available_transitions",
        lambda request: fake_qs,
    )
    view = RequestViewSet()
    view.request = SimpleNamespace(
        tenant_id=rt_request.tenantid_id,
        data={"transition_id": str(requested_transition_id)},
    )
    view.get_object = lambda: rt_request

    response = view.transition(view.request, pk=str(rt_request.requestid))

    assert response.status_code == 400
    assert response.data["code"] == "invalid_transition"
    assert response.data["details"][0]["field"] == "transition_id"


def test_apply_transition_updates_status_comment_and_activity(monkeypatch):
    rt_request, transition = build_request_and_transition(to_category="closed")
    saved = {}
    created_comments = []
    created_activities = []

    def fake_save(**kwargs):
        saved.update(kwargs)

    monkeypatch.setattr(rt_request, "save", fake_save)
    monkeypatch.setattr(
        "apps.rt.views.Comment.objects.create",
        lambda **kwargs: created_comments.append(SimpleNamespace(**kwargs))
        or created_comments[-1],
    )
    monkeypatch.setattr(
        "apps.rt.views.Activity.objects.create",
        lambda **kwargs: created_activities.append(kwargs),
    )

    apply_transition_without_transaction = apply_transition.__wrapped__
    updated_request = apply_transition_without_transaction(
        rt_request,
        transition,
        action_type="request.closed",
        comment="Closing this out.",
    )

    assert updated_request.statusid == transition.tostatusid
    assert saved == {"update_fields": ["statusid", "updatedat"]}
    assert created_comments[0].messagemd == "Closing this out."
    assert created_activities[0]["type"] == "request.closed"
    assert created_activities[0]["createdat"] == updated_request.updatedat
    assert json.loads(created_activities[0]["payload"]) == {
        "transition_id": str(transition.transitionid),
        "from_status_id": str(transition.fromstatusid_id),
        "to_status_id": str(transition.tostatusid_id),
        "comment_id": str(created_comments[0].commentid),
    }


def test_close_selects_terminal_or_closed_transition(monkeypatch):
    rt_request, transition = build_request_and_transition(to_category="waiting")
    terminal_request, terminal_transition = build_request_and_transition(
        to_category="resolved", terminal=True
    )
    terminal_transition.flowid = rt_request.flowid
    terminal_transition.fromstatusid = rt_request.statusid
    monkeypatch.setattr(
        "apps.rt.views.get_available_transitions",
        lambda request: [transition, terminal_transition],
    )

    selected = find_transition_by_target_category(
        rt_request, categories={"closed"}, terminal=True
    )

    assert selected == terminal_transition
    assert terminal_request is not None


def test_reopen_action_uses_open_transition(monkeypatch):
    rt_request, transition = build_request_and_transition(to_category="open")
    monkeypatch.setattr(
        "apps.rt.views.find_transition_by_target_category",
        lambda request, categories, terminal=False: transition,
    )
    monkeypatch.setattr(
        "apps.rt.views.apply_transition",
        lambda rt_request, transition, action_type, comment="": rt_request,
    )
    view = RequestViewSet()
    view.request = SimpleNamespace(tenant_id=rt_request.tenantid_id, data={})
    view.get_object = lambda: rt_request

    response = view.reopen(view.request, pk=str(rt_request.requestid))

    assert response.status_code == 200
    assert response.data["request_id"] == str(rt_request.requestid)


def test_openapi_schema_includes_transition_paths():
    response = Client().get("/api/schema")

    assert response.status_code == 200
    assert b"/api/requests/{requestid}/available-transitions/" in response.content
    assert b"/api/requests/{requestid}/transition/" in response.content
    assert b"/api/requests/{requestid}/close/" in response.content
    assert b"/api/requests/{requestid}/reopen/" in response.content
