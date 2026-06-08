import uuid
from types import SimpleNamespace

from django.utils import timezone

from apps.rt.models import Comment, Flow, Request, Status, Tenant, Transition, User
from apps.rt.serializers import RequestSerializer
from apps.rt.services import notification_service
from apps.rt.views import RequestViewSet, apply_transition


def build_request(assignee=None):
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
        userid=uuid.uuid4(),
        email="requester@example.com",
        displayname="Requester",
    )
    now = timezone.now()
    return Request(
        requestid=uuid.uuid4(),
        tenantid=tenant,
        humanid="RT-2026-000111",
        title="Notification test",
        description="Notification baseline.",
        flowid=flow,
        statusid=status,
        requesterid=requester,
        assigneeid=assignee,
        priority="normal",
        createdat=now,
        updatedat=now,
    )


def test_notification_service_sends_mailhog_visible_email(monkeypatch, settings):
    assignee = User(
        userid=uuid.uuid4(),
        email="assignee@example.com",
        displayname="Assignee",
    )
    rt_request = build_request(assignee=assignee)
    sent = []
    settings.DEFAULT_FROM_EMAIL = "rt-api@example.com"
    settings.WEB_BASE_URL = "http://127.0.0.1:5173"

    monkeypatch.setattr(
        "apps.rt.services.notification_service.send_mail",
        lambda **kwargs: sent.append(kwargs),
    )

    notification_service.notify_request_created(rt_request)

    assert sent[0]["subject"] == "Request created: RT-2026-000111"
    assert sent[0]["from_email"] == "rt-api@example.com"
    assert sent[0]["recipient_list"] == [
        "requester@example.com",
        "assignee@example.com",
    ]
    assert sent[0]["fail_silently"] is True
    assert "Human ID: RT-2026-000111" in sent[0]["message"]
    assert "Title: Notification test" in sent[0]["message"]
    assert f"Request ID: {rt_request.requestid}" in sent[0]["message"]
    assert (
        f"Link: http://127.0.0.1:5173/requests/{rt_request.requestid}"
        in sent[0]["message"]
    )


def test_notification_service_dedupes_recipients(monkeypatch):
    assignee = User(
        userid=uuid.uuid4(),
        email="REQUESTER@example.com",
        displayname="Same user",
    )
    rt_request = build_request(assignee=assignee)
    sent = []

    monkeypatch.setattr(
        "apps.rt.services.notification_service.send_mail",
        lambda **kwargs: sent.append(kwargs),
    )

    notification_service.notify_request_created(rt_request)

    assert sent[0]["recipient_list"] == ["requester@example.com"]


def test_notification_failure_does_not_break_main_action(monkeypatch):
    rt_request = build_request()

    def failing_send_mail(**kwargs):
        raise RuntimeError("mail server unavailable")

    monkeypatch.setattr(
        "apps.rt.services.notification_service.send_mail", failing_send_mail
    )

    notification_service.notify_request_created(rt_request)


def test_request_create_triggers_created_and_assigned_notifications(monkeypatch):
    tenant_id = uuid.uuid4()
    assignee_id = uuid.uuid4()
    assignee = User(userid=assignee_id, email="assignee@example.com")
    rt_request = build_request(assignee=assignee)
    rt_request.assigneeid_id = assignee_id
    created = []
    assigned = []

    class FakeSerializer:
        validated_data = {
            "flowid_id": rt_request.flowid_id,
            "statusid_id": rt_request.statusid_id,
            "requesterid_id": rt_request.requesterid_id,
            "assigneeid_id": assignee_id,
        }

        def save(self, **kwargs):
            return rt_request

    monkeypatch.setattr(
        "apps.rt.views.generate_human_id", lambda tenant: rt_request.humanid
    )
    monkeypatch.setattr("apps.rt.views.Activity.objects.create", lambda **kwargs: None)
    monkeypatch.setattr(
        "apps.rt.views.notify_request_created",
        lambda request: created.append(request),
    )
    monkeypatch.setattr(
        "apps.rt.views.notify_request_assigned",
        lambda request: assigned.append(request),
    )

    view = RequestViewSet()
    view.request = SimpleNamespace(tenant_id=tenant_id)
    perform_create = RequestViewSet.perform_create.__wrapped__

    perform_create(view, FakeSerializer())

    assert created == [rt_request]
    assert assigned == [rt_request]


def test_request_update_changed_assignee_triggers_assignment_notification(monkeypatch):
    old_assignee = User(userid=uuid.uuid4(), email="old-assignee@example.com")
    new_assignee_id = uuid.uuid4()
    rt_request = build_request(assignee=old_assignee)
    rt_request.assigneeid_id = old_assignee.userid
    assigned = []

    class FakeSerializer:
        instance = rt_request

        def save(self, **kwargs):
            rt_request.assigneeid = User(
                userid=new_assignee_id,
                email="new-assignee@example.com",
            )
            rt_request.assigneeid_id = new_assignee_id
            rt_request.updatedat = kwargs["updatedat"]
            return rt_request

    monkeypatch.setattr(
        "apps.rt.views.notify_request_assigned",
        lambda request: assigned.append(request),
    )
    monkeypatch.setattr(
        "apps.rt.views.notify_request_closed",
        lambda request: None,
    )

    RequestViewSet.perform_update.__wrapped__(RequestViewSet(), FakeSerializer())

    assert assigned == [rt_request]


def test_partial_assignment_update_validates_with_existing_request_fields(monkeypatch):
    tenant = Tenant(tenantid=uuid.uuid4())
    new_assignee_id = uuid.uuid4()
    rt_request = build_request()
    rt_request.tenantid = tenant
    rt_request.tenantid_id = tenant.tenantid

    class FakeExistsQuerySet:
        def exists(self):
            return True

    monkeypatch.setattr(
        "apps.rt.serializers.Flow.objects.get",
        lambda **kwargs: rt_request.flowid,
    )
    monkeypatch.setattr(
        "apps.rt.serializers.Status.objects.get",
        lambda **kwargs: rt_request.statusid,
    )
    monkeypatch.setattr(
        "apps.rt.serializers.Membership.objects.filter",
        lambda **kwargs: FakeExistsQuerySet(),
    )

    serializer = RequestSerializer(
        rt_request,
        data={"assignee_id": str(new_assignee_id)},
        context={"tenant_id": tenant.tenantid},
        partial=True,
    )

    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data["assigneeid_id"] == new_assignee_id


def test_comment_notification_uses_request_stakeholders(monkeypatch):
    rt_request = build_request()
    comment = Comment(
        commentid=uuid.uuid4(),
        tenantid=rt_request.tenantid,
        requestid=rt_request,
        authorid=rt_request.requesterid,
        messagemd="A useful update.",
        visibility="public",
        createdat=timezone.now(),
    )
    sent = []
    monkeypatch.setattr(
        "apps.rt.services.notification_service.send_mail",
        lambda **kwargs: sent.append(kwargs),
    )

    notification_service.notify_comment_added(comment)

    assert sent[0]["subject"] == "Comment added: RT-2026-000111"
    assert sent[0]["recipient_list"] == ["requester@example.com"]


def test_transition_to_closed_category_triggers_closed_notification(monkeypatch):
    rt_request = build_request()
    closed_status = Status(
        statusid=uuid.uuid4(),
        tenantid=rt_request.tenantid,
        flowid=rt_request.flowid,
        name="Closed",
        category="closed",
        isterminal=True,
    )
    transition = Transition(
        transitionid=uuid.uuid4(),
        flowid=rt_request.flowid,
        fromstatusid=rt_request.statusid,
        tostatusid=closed_status,
    )
    notified = []

    monkeypatch.setattr(rt_request, "save", lambda **kwargs: None)
    monkeypatch.setattr("apps.rt.views.Activity.objects.create", lambda **kwargs: None)
    monkeypatch.setattr(
        "apps.rt.views.notify_request_closed",
        lambda request: notified.append(request),
    )
    apply_transition_without_transaction = apply_transition.__wrapped__

    apply_transition_without_transaction(
        rt_request,
        transition,
        action_type="request.transitioned",
    )

    assert notified == [rt_request]


def test_send_mail_exception_does_not_break_request_create(monkeypatch):
    tenant_id = uuid.uuid4()
    rt_request = build_request()

    class FakeSerializer:
        validated_data = {
            "flowid_id": rt_request.flowid_id,
            "statusid_id": rt_request.statusid_id,
            "requesterid_id": rt_request.requesterid_id,
        }

        def save(self, **kwargs):
            return rt_request

    def failing_send_mail(**kwargs):
        raise RuntimeError("mail server unavailable")

    monkeypatch.setattr(
        "apps.rt.views.generate_human_id", lambda tenant: rt_request.humanid
    )
    monkeypatch.setattr("apps.rt.views.Activity.objects.create", lambda **kwargs: None)
    monkeypatch.setattr(
        "apps.rt.services.notification_service.send_mail", failing_send_mail
    )

    view = RequestViewSet()
    view.request = SimpleNamespace(tenant_id=tenant_id)
    perform_create = RequestViewSet.perform_create.__wrapped__

    perform_create(view, FakeSerializer())
