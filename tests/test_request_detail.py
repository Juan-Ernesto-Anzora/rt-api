import uuid

from django.urls import resolve
from django.utils import timezone

from apps.rt.models import Flow, Request, Status, Tenant, User
from apps.rt.serializers import RequestDetailSerializer

UPPER_REQUEST_ID = "9DC80633-F354-44D3-A4CE-B3B78A027D33"


def build_request():
    tenant = Tenant(tenantid=uuid.uuid4())
    flow = Flow(
        flowid=uuid.uuid4(),
        tenantid=tenant,
        name="IT Support",
        description="Internal service desk",
    )
    status = Status(
        statusid=uuid.uuid4(),
        tenantid=tenant,
        flowid=flow,
        name="In Progress",
        category="in_progress",
        isterminal=False,
    )
    requester = User(
        userid=uuid.uuid4(),
        email="requester@example.com",
        displayname="Request Owner",
        employeecode="E-100",
        avatarurl="https://example.com/avatar.png",
    )
    assignee = User(
        userid=uuid.uuid4(),
        email="assignee@example.com",
        displayname="Assigned Agent",
        employeecode="E-200",
    )
    now = timezone.now()
    return Request(
        requestid=uuid.UUID(UPPER_REQUEST_ID),
        tenantid=tenant,
        humanid="RT-2026-000001",
        title="VPN access",
        description="Need VPN access for travel.",
        flowid=flow,
        statusid=status,
        priority="normal",
        requesterid=requester,
        assigneeid=assignee,
        customfields='{"country": "SV"}',
        dueat=now,
        createdat=now,
        updatedat=now,
    )


def test_request_detail_routes_resolve():
    assert (
        resolve(f"/api/requests/{UPPER_REQUEST_ID}/detail/").url_name
        == "requests-detail-bundle"
    )
    assert (
        resolve(f"/api/requests/{UPPER_REQUEST_ID}/activities/").url_name
        == "requests-activities"
    )


def test_nested_comments_and_attachments_accept_trailing_slash():
    comments = resolve(f"/api/requests/{UPPER_REQUEST_ID}/comments/")
    attachments = resolve(f"/api/requests/{UPPER_REQUEST_ID}/attachments/")

    assert comments.url_name == "request-comments-slash"
    assert comments.kwargs["request_pk"] == UPPER_REQUEST_ID
    assert attachments.url_name == "request-attachments-slash"
    assert attachments.kwargs["request_pk"] == UPPER_REQUEST_ID


def test_request_detail_serializer_returns_header_and_related_summaries():
    data = RequestDetailSerializer(build_request()).data

    assert data["request_id"] == UPPER_REQUEST_ID.lower()
    assert data["human_id"] == "RT-2026-000001"
    assert data["title"] == "VPN access"
    assert data["flow"]["name"] == "IT Support"
    assert data["status"]["category"] == "in_progress"
    assert data["requester"]["display_name"] == "Request Owner"
    assert data["assignee"]["email"] == "assignee@example.com"
    assert data["custom_fields"] == '{"country": "SV"}'
    assert data["tags"] == []
    assert data["created_at"]
    assert data["updated_at"]
