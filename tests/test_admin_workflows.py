import uuid
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

from django.test import Client
from django.urls import resolve
from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.rt.models import Activity, Comment, Flow, Status, Transition
from apps.rt.services.admin_permissions import (
    ADMIN_ACCESS_PERMISSION,
    AdminPermissionError,
)
from apps.rt.views import (
    AdminWorkflowDetailView,
    AdminWorkflowListCreateView,
    AdminWorkflowStatusCreateView,
    AdminWorkflowStatusDetailView,
    AdminWorkflowTransitionCreateView,
    AdminWorkflowTransitionDetailView,
)


class FakeQuerySet(list):
    def __init__(self, items=None):
        super().__init__(items or [])
        self.calls = []

    def order_by(self, *fields):
        self.calls.append(("order_by", fields))
        return self


def authenticated_request(method, path, tenant_id, data=None):
    factory = APIRequestFactory()
    request = getattr(factory, method)(path, data or {}, format="json")
    request.tenant_id = tenant_id
    force_authenticate(
        request,
        user=SimpleNamespace(
            is_authenticated=True,
            email="admin@example.com",
            username="admin@example.com",
        ),
    )
    return request


def admin_context():
    return SimpleNamespace(
        user=SimpleNamespace(
            user_id=uuid.uuid4(),
            email="admin@example.com",
            display_name="Admin User",
        ),
        permissions=[ADMIN_ACCESS_PERMISSION],
    )


def make_flow(tenant_id=None, name="IT Support"):
    return Flow(
        flowid=uuid.uuid4(),
        tenantid_id=tenant_id or uuid.uuid4(),
        name=name,
        description="Support workflow",
        createdat=timezone.now(),
    )


def make_status(flow, name="Open", category="open"):
    return Status(
        statusid=uuid.uuid4(),
        tenantid_id=flow.tenantid_id,
        flowid=flow,
        flowid_id=flow.flowid,
        name=name,
        category=category,
        isterminal=False,
        createdat=timezone.now(),
    )


def make_transition(flow, from_status, to_status):
    return Transition(
        transitionid=uuid.uuid4(),
        flowid=flow,
        flowid_id=flow.flowid,
        fromstatusid=from_status,
        fromstatusid_id=from_status.statusid,
        tostatusid=to_status,
        tostatusid_id=to_status.statusid,
        guardrolesjson="[]",
        guardpermsjson="[]",
        autorules="{}",
        createdat=timezone.now(),
    )


def patch_admin_context(monkeypatch):
    captured = []

    def fake_get_admin_context(request, required_permission):
        captured.append(required_permission)
        return admin_context()

    monkeypatch.setattr("apps.rt.views.get_admin_context", fake_get_admin_context)
    return captured


def patch_no_transaction(monkeypatch):
    monkeypatch.setattr("apps.rt.views.transaction.atomic", lambda: nullcontext())


def test_admin_workflow_routes_resolve():
    flow_id = uuid.uuid4()
    status_id = uuid.uuid4()
    transition_id = uuid.uuid4()

    assert resolve("/api/admin/workflows/").url_name == "admin-workflows"
    assert (
        resolve(f"/api/admin/workflows/{flow_id}/").url_name == "admin-workflow-detail"
    )
    assert (
        resolve(f"/api/admin/workflows/{flow_id}/statuses/").url_name
        == "admin-workflow-statuses"
    )
    assert (
        resolve(f"/api/admin/workflows/{flow_id}/statuses/{status_id}/").url_name
        == "admin-workflow-status-detail"
    )
    assert (
        resolve(f"/api/admin/workflows/{flow_id}/transitions/").url_name
        == "admin-workflow-transitions"
    )
    assert (
        resolve(f"/api/admin/workflows/{flow_id}/transitions/{transition_id}/").url_name
        == "admin-workflow-transition-detail"
    )


def test_admin_audit_model_matches_tenant_level_activity_schema():
    assert Activity._meta.get_field("requestid").null is True
    assert Comment._meta.get_field("requestid").null is False


def test_existing_database_upgrade_supports_admin_audit_events():
    upgrade_sql = Path("db/upgrade-sprint3-admin-workflows.sql").read_text(
        encoding="utf-8"
    )
    create_sql = Path("db/create-rt-database.sql").read_text(encoding="utf-8")

    assert (
        "ALTER TABLE dbo.Activity ALTER COLUMN RequestId UNIQUEIDENTIFIER NULL"
        in upgrade_sql
    )
    for permission_code in ("admin.read", "admin.audit.read", "admin.workflows"):
        assert permission_code in upgrade_sql
        assert permission_code in create_sql


def test_admin_workflow_list_is_tenant_scoped(monkeypatch):
    tenant_id = uuid.uuid4()
    flow = make_flow(tenant_id)
    captured = {}
    permissions = patch_admin_context(monkeypatch)

    def fake_filter(**kwargs):
        captured.update(kwargs)
        return FakeQuerySet([flow])

    monkeypatch.setattr("apps.rt.views.Flow.objects.filter", fake_filter)

    response = AdminWorkflowListCreateView.as_view()(
        authenticated_request("get", "/api/admin/workflows/", tenant_id)
    )

    assert response.status_code == 200
    assert permissions == [ADMIN_ACCESS_PERMISSION]
    assert captured == {"tenantid": tenant_id}
    assert response.data[0]["flow_id"] == str(flow.flowid)


def test_admin_workflow_create_writes_tenant_flow_and_audit(monkeypatch):
    tenant_id = uuid.uuid4()
    created = {}
    audits = []
    patch_no_transaction(monkeypatch)
    patch_admin_context(monkeypatch)

    def fake_create_flow(**kwargs):
        created.update(kwargs)
        return Flow(
            flowid=kwargs["flowid"],
            tenantid_id=kwargs["tenantid_id"],
            name=kwargs["name"],
            description=kwargs["description"],
            createdat=kwargs["createdat"],
        )

    monkeypatch.setattr("apps.rt.views.Flow.objects.create", fake_create_flow)
    monkeypatch.setattr(
        "apps.rt.views.Activity.objects.create", lambda **kwargs: audits.append(kwargs)
    )

    response = AdminWorkflowListCreateView.as_view()(
        authenticated_request(
            "post",
            "/api/admin/workflows/",
            tenant_id,
            {"name": "Facilities", "description": "Facilities requests"},
        )
    )

    assert response.status_code == 201
    assert created["tenantid_id"] == tenant_id
    assert created["name"] == "Facilities"
    assert audits[0]["requestid_id"] is None
    assert audits[0]["type"] == "admin.workflow.created"


def test_admin_workflow_detail_returns_404_for_cross_tenant(monkeypatch):
    patch_admin_context(monkeypatch)

    def fake_get(**kwargs):
        raise Flow.DoesNotExist

    monkeypatch.setattr("apps.rt.views.Flow.objects.get", fake_get)

    response = AdminWorkflowDetailView.as_view()(
        authenticated_request(
            "get", f"/api/admin/workflows/{uuid.uuid4()}/", uuid.uuid4()
        ),
        flow_id=uuid.uuid4(),
    )

    assert response.status_code == 404
    assert response.data["code"] == "not_found"


def test_admin_workflow_detail_returns_nested_configuration(monkeypatch):
    tenant_id = uuid.uuid4()
    flow = make_flow(tenant_id)
    open_status = make_status(flow)
    closed_status = make_status(flow, "Closed", "closed")
    transition = make_transition(flow, open_status, closed_status)
    patch_admin_context(monkeypatch)
    monkeypatch.setattr("apps.rt.views.Flow.objects.get", lambda **kwargs: flow)
    monkeypatch.setattr(
        "apps.rt.views.Status.objects.filter",
        lambda **kwargs: FakeQuerySet([open_status, closed_status]),
    )
    monkeypatch.setattr(
        "apps.rt.views.Transition.objects.filter",
        lambda **kwargs: FakeQuerySet([transition]),
    )

    response = AdminWorkflowDetailView.as_view()(
        authenticated_request("get", f"/api/admin/workflows/{flow.flowid}/", tenant_id),
        flow_id=flow.flowid,
    )

    assert response.status_code == 200
    assert response.data["flow_id"] == str(flow.flowid)
    assert {item["status_id"] for item in response.data["statuses"]} == {
        str(open_status.statusid),
        str(closed_status.statusid),
    }
    assert response.data["transitions"][0]["transition_id"] == str(
        transition.transitionid
    )


def test_admin_workflow_update_audits_write(monkeypatch):
    tenant_id = uuid.uuid4()
    flow = make_flow(tenant_id)
    saved = {}
    audits = []
    patch_no_transaction(monkeypatch)
    patch_admin_context(monkeypatch)
    monkeypatch.setattr("apps.rt.views.Flow.objects.get", lambda **kwargs: flow)
    monkeypatch.setattr(
        "apps.rt.views.Activity.objects.create", lambda **kwargs: audits.append(kwargs)
    )
    flow.save = lambda update_fields=None: saved.update(
        {"update_fields": update_fields}
    )

    response = AdminWorkflowDetailView.as_view()(
        authenticated_request(
            "patch",
            f"/api/admin/workflows/{flow.flowid}/",
            tenant_id,
            {"name": "Updated"},
        ),
        flow_id=flow.flowid,
    )

    assert response.status_code == 200
    assert flow.name == "Updated"
    assert saved == {"update_fields": ["name"]}
    assert audits[0]["type"] == "admin.workflow.updated"


def test_admin_status_create_is_tenant_and_flow_scoped(monkeypatch):
    tenant_id = uuid.uuid4()
    flow = make_flow(tenant_id)
    created = {}
    audits = []
    patch_no_transaction(monkeypatch)
    patch_admin_context(monkeypatch)
    monkeypatch.setattr("apps.rt.views.Flow.objects.get", lambda **kwargs: flow)

    def fake_create_status(**kwargs):
        created.update(kwargs)
        return Status(
            statusid=kwargs["statusid"],
            tenantid_id=kwargs["tenantid_id"],
            flowid=kwargs["flowid"],
            flowid_id=kwargs["flowid"].flowid,
            name=kwargs["name"],
            category=kwargs["category"],
            isterminal=kwargs["isterminal"],
            createdat=kwargs["createdat"],
        )

    monkeypatch.setattr("apps.rt.views.Status.objects.create", fake_create_status)
    monkeypatch.setattr(
        "apps.rt.views.Activity.objects.create", lambda **kwargs: audits.append(kwargs)
    )

    response = AdminWorkflowStatusCreateView.as_view()(
        authenticated_request(
            "post",
            f"/api/admin/workflows/{flow.flowid}/statuses/",
            tenant_id,
            {"name": "Closed", "category": "closed", "is_terminal": True},
        ),
        flow_id=flow.flowid,
    )

    assert response.status_code == 201
    assert created["tenantid_id"] == tenant_id
    assert created["flowid"] is flow
    assert response.data["is_terminal"] is True
    assert audits[0]["type"] == "admin.status.created"


def test_admin_status_update_returns_404_for_cross_tenant_status(monkeypatch):
    tenant_id = uuid.uuid4()
    flow = make_flow(tenant_id)
    patch_admin_context(monkeypatch)
    monkeypatch.setattr("apps.rt.views.Flow.objects.get", lambda **kwargs: flow)

    def fake_status_get(**kwargs):
        raise Status.DoesNotExist

    monkeypatch.setattr("apps.rt.views.Status.objects.get", fake_status_get)

    response = AdminWorkflowStatusDetailView.as_view()(
        authenticated_request(
            "patch",
            f"/api/admin/workflows/{flow.flowid}/statuses/{uuid.uuid4()}/",
            tenant_id,
            {"name": "Hidden"},
        ),
        flow_id=flow.flowid,
        status_id=uuid.uuid4(),
    )

    assert response.status_code == 404
    assert response.data["code"] == "not_found"


def test_admin_status_update_saves_and_audits(monkeypatch):
    tenant_id = uuid.uuid4()
    flow = make_flow(tenant_id)
    status_obj = make_status(flow)
    saved = {}
    audits = []
    patch_no_transaction(monkeypatch)
    patch_admin_context(monkeypatch)
    monkeypatch.setattr("apps.rt.views.Flow.objects.get", lambda **kwargs: flow)
    monkeypatch.setattr("apps.rt.views.Status.objects.get", lambda **kwargs: status_obj)
    monkeypatch.setattr(
        "apps.rt.views.Activity.objects.create", lambda **kwargs: audits.append(kwargs)
    )
    status_obj.save = lambda update_fields=None: saved.update(
        {"update_fields": update_fields}
    )

    response = AdminWorkflowStatusDetailView.as_view()(
        authenticated_request(
            "patch",
            f"/api/admin/workflows/{flow.flowid}/statuses/{status_obj.statusid}/",
            tenant_id,
            {"name": "In progress", "category": "in_progress"},
        ),
        flow_id=flow.flowid,
        status_id=status_obj.statusid,
    )

    assert response.status_code == 200
    assert response.data["name"] == "In progress"
    assert response.data["category"] == "in_progress"
    assert saved["update_fields"] == ["name", "category"]
    assert audits[0]["type"] == "admin.status.updated"


def test_admin_transition_create_validates_statuses_in_workflow(monkeypatch):
    tenant_id = uuid.uuid4()
    flow = make_flow(tenant_id)
    from_status = make_status(flow, "Open", "open")
    to_status = make_status(flow, "Closed", "closed")
    audits = []
    patch_no_transaction(monkeypatch)
    patch_admin_context(monkeypatch)
    monkeypatch.setattr("apps.rt.views.Flow.objects.get", lambda **kwargs: flow)

    def fake_status_get(**kwargs):
        if kwargs["statusid"] == from_status.statusid:
            return from_status
        if kwargs["statusid"] == to_status.statusid:
            return to_status
        raise Status.DoesNotExist

    def fake_transition_create(**kwargs):
        return make_transition(flow, kwargs["fromstatusid"], kwargs["tostatusid"])

    monkeypatch.setattr("apps.rt.views.Status.objects.get", fake_status_get)
    monkeypatch.setattr(
        "apps.rt.views.Transition.objects.create", fake_transition_create
    )
    monkeypatch.setattr(
        "apps.rt.views.Activity.objects.create", lambda **kwargs: audits.append(kwargs)
    )

    response = AdminWorkflowTransitionCreateView.as_view()(
        authenticated_request(
            "post",
            f"/api/admin/workflows/{flow.flowid}/transitions/",
            tenant_id,
            {
                "from_status_id": str(from_status.statusid),
                "to_status_id": str(to_status.statusid),
                "guard_roles_json": "[]",
            },
        ),
        flow_id=flow.flowid,
    )

    assert response.status_code == 201
    assert response.data["from_status_id"] == str(from_status.statusid)
    assert response.data["to_status_id"] == str(to_status.statusid)
    assert audits[0]["type"] == "admin.transition.created"


def test_admin_transition_update_returns_404_for_cross_tenant_transition(monkeypatch):
    tenant_id = uuid.uuid4()
    flow = make_flow(tenant_id)
    patch_admin_context(monkeypatch)
    monkeypatch.setattr("apps.rt.views.Flow.objects.get", lambda **kwargs: flow)

    def fake_transition_get(**kwargs):
        raise Transition.DoesNotExist

    monkeypatch.setattr("apps.rt.views.Transition.objects.get", fake_transition_get)

    response = AdminWorkflowTransitionDetailView.as_view()(
        authenticated_request(
            "patch",
            f"/api/admin/workflows/{flow.flowid}/transitions/{uuid.uuid4()}/",
            tenant_id,
            {"auto_rules": "{}"},
        ),
        flow_id=flow.flowid,
        transition_id=uuid.uuid4(),
    )

    assert response.status_code == 404
    assert response.data["code"] == "not_found"


def test_admin_transition_update_saves_and_audits(monkeypatch):
    tenant_id = uuid.uuid4()
    flow = make_flow(tenant_id)
    from_status = make_status(flow)
    to_status = make_status(flow, "Closed", "closed")
    transition = make_transition(flow, from_status, to_status)
    saved = {}
    audits = []
    patch_no_transaction(monkeypatch)
    patch_admin_context(monkeypatch)
    monkeypatch.setattr("apps.rt.views.Flow.objects.get", lambda **kwargs: flow)
    monkeypatch.setattr(
        "apps.rt.views.Transition.objects.get", lambda **kwargs: transition
    )
    monkeypatch.setattr(
        "apps.rt.views.Activity.objects.create", lambda **kwargs: audits.append(kwargs)
    )
    transition.save = lambda update_fields=None: saved.update(
        {"update_fields": update_fields}
    )

    response = AdminWorkflowTransitionDetailView.as_view()(
        authenticated_request(
            "patch",
            f"/api/admin/workflows/{flow.flowid}/transitions/{transition.transitionid}/",
            tenant_id,
            {"auto_rules": '{"notify": true}'},
        ),
        flow_id=flow.flowid,
        transition_id=transition.transitionid,
    )

    assert response.status_code == 200
    assert response.data["auto_rules"] == '{"notify": true}'
    assert saved["update_fields"] == ["autorules"]
    assert audits[0]["type"] == "admin.transition.updated"


def test_admin_workflow_permission_denied_returns_403(monkeypatch):
    def fake_get_admin_context(request, required_permission):
        raise AdminPermissionError(
            code="permission_denied",
            message="You do not have permission to access this admin resource.",
            status_code=403,
        )

    monkeypatch.setattr("apps.rt.views.get_admin_context", fake_get_admin_context)

    response = AdminWorkflowListCreateView.as_view()(
        authenticated_request("get", "/api/admin/workflows/", uuid.uuid4())
    )

    assert response.status_code == 403
    assert response.data["code"] == "permission_denied"


def test_openapi_schema_includes_admin_workflow_paths():
    response = Client().get("/api/schema")

    assert response.status_code == 200
    assert b"/api/admin/workflows/" in response.content
    assert b"/api/admin/workflows/{flow_id}/" in response.content
    assert b"/api/admin/workflows/{flow_id}/statuses/" in response.content
    assert b"/api/admin/workflows/{flow_id}/statuses/{status_id}/" in response.content
    assert b"/api/admin/workflows/{flow_id}/transitions/" in response.content
    assert (
        b"/api/admin/workflows/{flow_id}/transitions/{transition_id}/"
        in response.content
    )
