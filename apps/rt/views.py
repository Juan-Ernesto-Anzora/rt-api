import json
import uuid
from datetime import datetime

import boto3
from botocore.client import Config
from django.conf import settings
from django.db import connection, transaction
from django.db.models import Q
from django.utils import timezone
from drf_spectacular.utils import OpenApiExample, OpenApiParameter, extend_schema
from rest_framework import mixins, permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import (
    Activity,
    Attachment,
    Comment,
    Flow,
    Membership,
    Request,
    Status,
    Transition,
    User,
)
from .search import SearchValidationError, search_requests
from .serializers import (
    ActivitySerializer,
    AdminAuditSerializer,
    AdminFlowSerializer,
    AdminFlowWriteSerializer,
    AdminPermissionsSerializer,
    AdminStatusSerializer,
    AdminStatusWriteSerializer,
    AdminTransitionSerializer,
    AdminTransitionWriteSerializer,
    AttachmentFinalizeRequestSerializer,
    AttachmentInitRequestSerializer,
    AttachmentInitResponseSerializer,
    AttachmentSerializer,
    CommentSerializer,
    DashboardSummarySerializer,
    FlowLookupSerializer,
    RequestCloseReopenSerializer,
    RequestDetailSerializer,
    RequestSerializer,
    RequestTransitionSerializer,
    SearchQuerySerializer,
    StatusLookupSerializer,
    TransitionLookupSerializer,
    UserLookupSerializer,
)
from .services.admin_permissions import (
    ADMIN_ACCESS_PERMISSION,
    ADMIN_AUDIT_READ_PERMISSION,
    AdminPermissionError,
    get_admin_context,
)
from .services.notification_service import (
    notify_comment_added,
    notify_request_assigned,
    notify_request_closed,
    notify_request_created,
)


class TenantPermission(permissions.IsAuthenticated):
    # DRF permissions and tenant middleware validate auth and tenant context.
    pass


class BaseTenantViewSet(viewsets.ModelViewSet):
    permission_classes = [TenantPermission]

    def get_queryset(self):
        qs = super().get_queryset()
        tenant_id = getattr(self.request, "tenant_id", None)
        if tenant_id:
            return qs.filter(tenantid=tenant_id)
        return qs.none()


class RequestViewSet(BaseTenantViewSet):
    queryset = Request.objects.all().order_by("-updatedat")
    serializer_class = RequestSerializer

    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .select_related("flowid", "statusid", "requesterid", "assigneeid")
        )

    def get_serializer_class(self):
        if self.action in {"retrieve", "detail_bundle"}:
            return RequestDetailSerializer
        return super().get_serializer_class()

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["tenant_id"] = getattr(self.request, "tenant_id", None)
        return context

    def create(self, request, *args, **kwargs):
        if not getattr(request, "tenant_id", None):
            return Response(
                {
                    "code": "tenant_required",
                    "message": "Tenant context missing.",
                    "details": [],
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = self.get_serializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {
                    "code": "validation_error",
                    "message": "Invalid request payload.",
                    "details": format_validation_details(serializer.errors),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        rt_request = self.perform_create(serializer)
        response_serializer = self.get_serializer(rt_request)
        headers = self.get_success_headers(response_serializer.data)
        return Response(
            response_serializer.data,
            status=status.HTTP_201_CREATED,
            headers=headers,
        )

    @transaction.atomic
    def perform_create(self, serializer):
        validated_data = serializer.validated_data

        def to_uuid(val):
            if val is None or val == "":
                return None
            if isinstance(val, uuid.UUID):
                return val
            return uuid.UUID(str(val))

        flow_id = to_uuid(validated_data.get("flowid_id"))
        status_id = to_uuid(validated_data.get("statusid_id"))
        requester_id = to_uuid(validated_data.get("requesterid_id"))
        assignee_id = to_uuid(validated_data.get("assigneeid_id"))

        tenant_id = self.request.tenant_id
        if isinstance(tenant_id, str):
            tenant_id = uuid.UUID(tenant_id)

        now = timezone.now()
        save_kwargs = {
            "tenantid_id": tenant_id,
            "humanid": generate_human_id(str(tenant_id)),
            "createdat": now,
            "updatedat": now,
            "flowid_id": flow_id,
            "statusid_id": status_id,
            "requesterid_id": requester_id,
        }
        if assignee_id:
            save_kwargs["assigneeid_id"] = assignee_id
        rt_request = serializer.save(**save_kwargs)
        Activity.objects.create(
            activityid=uuid.uuid4(),
            tenantid=rt_request.tenantid,
            requestid=rt_request,
            actorid=rt_request.requesterid,
            type="request.created",
            payload=json.dumps(
                {
                    "human_id": rt_request.humanid,
                    "title": rt_request.title,
                    "flow_id": str(rt_request.flowid_id),
                    "status_id": str(rt_request.statusid_id),
                    "requester_id": str(rt_request.requesterid_id),
                    "assignee_id": (
                        str(rt_request.assigneeid_id)
                        if rt_request.assigneeid_id
                        else None
                    ),
                }
            ),
            createdat=save_kwargs["createdat"],
        )
        notify_request_created(rt_request)
        if rt_request.assigneeid_id:
            notify_request_assigned(rt_request)
        return rt_request

    @transaction.atomic
    def perform_update(self, serializer):
        instance = serializer.instance
        previous_assignee_id = getattr(instance, "assigneeid_id", None)
        previous_status = getattr(instance, "statusid", None)

        rt_request = serializer.save(updatedat=timezone.now())
        current_assignee_id = getattr(rt_request, "assigneeid_id", None)
        if current_assignee_id and current_assignee_id != previous_assignee_id:
            notify_request_assigned(rt_request)

        if status_changed_to_closed(
            previous_status, getattr(rt_request, "statusid", None)
        ):
            notify_request_closed(rt_request)

    @action(detail=True, methods=["get"])
    def activity(self, request, pk=None):
        return self._activity_response(request, pk)

    @action(detail=True, methods=["get"], url_path="activities")
    def activities(self, request, pk=None):
        return self._activity_response(request, pk)

    @action(detail=True, methods=["get"], url_path="detail")
    def detail_bundle(self, request, pk=None):
        rt_request = self.get_object()
        tenant_id = request.tenant_id
        comments = Comment.objects.filter(
            tenantid=tenant_id, requestid=rt_request.requestid
        ).order_by("-createdat")
        attachments = Attachment.objects.filter(
            tenantid=tenant_id, requestid=rt_request.requestid
        ).order_by("-createdat")
        activity = Activity.objects.filter(
            tenantid=tenant_id, requestid=rt_request.requestid
        ).order_by("-createdat")
        return Response(
            {
                "request": RequestDetailSerializer(rt_request).data,
                "comments": CommentSerializer(comments, many=True).data,
                "attachments": AttachmentSerializer(attachments, many=True).data,
                "activity": ActivitySerializer(activity, many=True).data,
            }
        )

    def _activity_response(self, request, pk=None):
        rt_request = self.get_object()
        tenant_id = request.tenant_id
        items = Activity.objects.filter(
            tenantid=tenant_id, requestid=rt_request.requestid
        ).order_by("-createdat")
        return Response(ActivitySerializer(items, many=True).data)

    @extend_schema(
        responses=TransitionLookupSerializer(many=True),
        description="List workflow transitions available from the request current status.",
    )
    @action(detail=True, methods=["get"], url_path="available-transitions")
    def available_transitions(self, request, pk=None):
        rt_request = self.get_object()
        transitions = get_available_transitions(rt_request)
        return Response(TransitionLookupSerializer(transitions, many=True).data)

    @extend_schema(
        request=RequestTransitionSerializer,
        responses=RequestSerializer,
        description="Apply a workflow transition to a tenant-scoped request.",
    )
    @action(detail=True, methods=["post"], url_path="transition")
    def transition(self, request, pk=None):
        serializer = RequestTransitionSerializer(data=request.data)
        if not serializer.is_valid():
            return validation_error_response(serializer.errors)

        rt_request = self.get_object()
        try:
            transition = get_available_transitions(rt_request).get(
                transitionid=serializer.validated_data["transition_id"]
            )
        except Transition.DoesNotExist:
            return Response(
                {
                    "code": "invalid_transition",
                    "message": "Transition is not available for this request.",
                    "details": [
                        {
                            "field": "transition_id",
                            "message": "Not available from current status.",
                        }
                    ],
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        updated_request = apply_transition(
            rt_request=rt_request,
            transition=transition,
            action_type="request.transitioned",
            comment=serializer.validated_data.get("comment") or "",
        )
        return Response(RequestSerializer(updated_request).data)

    @extend_schema(
        request=RequestCloseReopenSerializer,
        responses=RequestSerializer,
        description="Close a request using an available terminal/closed transition.",
    )
    @action(detail=True, methods=["post"], url_path="close")
    def close(self, request, pk=None):
        serializer = RequestCloseReopenSerializer(data=request.data)
        if not serializer.is_valid():
            return validation_error_response(serializer.errors)

        rt_request = self.get_object()
        transition = find_transition_by_target_category(
            rt_request, categories={"closed"}, terminal=True
        )
        if not transition:
            return transition_not_available_response(
                "No close transition is available."
            )

        updated_request = apply_transition(
            rt_request=rt_request,
            transition=transition,
            action_type="request.closed",
            comment=serializer.validated_data.get("comment") or "",
        )
        return Response(RequestSerializer(updated_request).data)

    @extend_schema(
        request=RequestCloseReopenSerializer,
        responses=RequestSerializer,
        description="Reopen a request using an available open transition.",
    )
    @action(detail=True, methods=["post"], url_path="reopen")
    def reopen(self, request, pk=None):
        serializer = RequestCloseReopenSerializer(data=request.data)
        if not serializer.is_valid():
            return validation_error_response(serializer.errors)

        rt_request = self.get_object()
        transition = find_transition_by_target_category(rt_request, categories={"open"})
        if not transition:
            return transition_not_available_response(
                "No reopen transition is available."
            )

        updated_request = apply_transition(
            rt_request=rt_request,
            transition=transition,
            action_type="request.reopened",
            comment=serializer.validated_data.get("comment") or "",
        )
        return Response(RequestSerializer(updated_request).data)


class FlowViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    permission_classes = [TenantPermission]
    serializer_class = FlowLookupSerializer
    lookup_field = "flowid"
    lookup_url_kwarg = "flow_id"

    @extend_schema(
        responses=FlowLookupSerializer(many=True),
        description="List flows available in the active tenant.",
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    def get_queryset(self):
        tenant_id = getattr(self.request, "tenant_id", None)
        if not tenant_id:
            return Flow.objects.none()
        return Flow.objects.filter(tenantid=tenant_id).order_by("name")

    def get_flow(self):
        tenant_id = getattr(self.request, "tenant_id", None)
        try:
            return Flow.objects.get(
                flowid=self.kwargs.get(self.lookup_url_kwarg), tenantid=tenant_id
            )
        except Flow.DoesNotExist as exc:
            raise NotFound(
                {
                    "code": "not_found",
                    "message": "Flow not found for this tenant.",
                    "details": [],
                }
            ) from exc

    @extend_schema(
        responses=StatusLookupSerializer(many=True),
        description="List statuses for a tenant-scoped flow.",
    )
    @action(detail=True, methods=["get"], url_path="statuses")
    def statuses(self, request, flow_id=None):
        flow = self.get_flow()
        statuses = Status.objects.filter(
            tenantid=request.tenant_id, flowid=flow.flowid
        ).order_by("name")
        return Response(StatusLookupSerializer(statuses, many=True).data)


class UserLookupViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    permission_classes = [TenantPermission]
    serializer_class = UserLookupSerializer

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="search",
                description="Optional case-insensitive search by display name or email.",
                required=False,
                type=str,
            )
        ],
        responses=UserLookupSerializer(many=True),
        description="List users who belong to the active tenant.",
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    def get_queryset(self):
        tenant_id = getattr(self.request, "tenant_id", None)
        if not tenant_id:
            return User.objects.none()

        member_user_ids = Membership.objects.filter(tenantid=tenant_id).values_list(
            "userid_id", flat=True
        )
        queryset = User.objects.filter(userid__in=member_user_ids).order_by(
            "displayname", "email"
        )
        search = self.request.query_params.get("search", "").strip()
        if search:
            queryset = queryset.filter(
                Q(displayname__icontains=search) | Q(email__icontains=search)
            )
        return queryset


class DashboardSummaryView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses=DashboardSummarySerializer,
        description="Return tenant-scoped request dashboard KPI counts.",
    )
    def get(self, request):
        tenant_id = getattr(request, "tenant_id", None)
        if not tenant_id:
            return Response(
                {
                    "code": "tenant_required",
                    "message": "Tenant context missing.",
                    "details": [],
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        summary = build_dashboard_summary(
            queryset=Request.objects.filter(tenantid=tenant_id),
            user_id=getattr(getattr(request, "user", None), "id", None),
        )
        return Response(DashboardSummarySerializer(summary).data)


class AdminPermissionsView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses=AdminPermissionsSerializer,
        description="Return current tenant admin roles and effective permissions.",
    )
    def get(self, request):
        try:
            context = get_admin_context(
                request, required_permission=ADMIN_ACCESS_PERMISSION
            )
        except AdminPermissionError as exc:
            return admin_error_response(exc)
        return Response(AdminPermissionsSerializer(context).data)


class AdminAuditView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses=AdminAuditSerializer(many=True),
        description="Return tenant-scoped admin audit activity.",
    )
    def get(self, request):
        try:
            get_admin_context(request, required_permission=ADMIN_AUDIT_READ_PERMISSION)
        except AdminPermissionError as exc:
            return admin_error_response(exc)

        queryset = Activity.objects.filter(tenantid=request.tenant_id).order_by(
            "-createdat"
        )
        activity_type = request.query_params.get("type")
        request_id = request.query_params.get("request_id")
        actor_id = request.query_params.get("actor_id")
        created_from = request.query_params.get("created_from")
        created_to = request.query_params.get("created_to")
        if activity_type:
            queryset = queryset.filter(type=activity_type)
        if request_id:
            queryset = queryset.filter(requestid_id=request_id)
        if actor_id:
            queryset = queryset.filter(actorid_id=actor_id)
        if created_from:
            queryset = queryset.filter(createdat__gte=created_from)
        if created_to:
            queryset = queryset.filter(createdat__lte=created_to)

        paginator = PageNumberPagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        serializer = AdminAuditSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)


class AdminWorkflowBaseView(APIView):
    permission_classes = [IsAuthenticated]

    def get_admin_context_or_response(self, request):
        try:
            return get_admin_context(
                request, required_permission=ADMIN_ACCESS_PERMISSION
            )
        except AdminPermissionError as exc:
            return admin_error_response(exc)

    def get_flow(self, request, flow_id):
        try:
            return Flow.objects.get(flowid=flow_id, tenantid=request.tenant_id)
        except Flow.DoesNotExist as exc:
            raise NotFound(
                {
                    "code": "not_found",
                    "message": "Workflow not found for this tenant.",
                    "details": [],
                }
            ) from exc

    def get_status(self, request, flow, status_id):
        try:
            return Status.objects.get(
                statusid=status_id, tenantid=request.tenant_id, flowid=flow.flowid
            )
        except Status.DoesNotExist as exc:
            raise NotFound(
                {
                    "code": "not_found",
                    "message": "Status not found for this workflow and tenant.",
                    "details": [],
                }
            ) from exc

    def get_transition(self, flow, transition_id):
        try:
            return Transition.objects.get(
                transitionid=transition_id, flowid=flow.flowid
            )
        except Transition.DoesNotExist as exc:
            raise NotFound(
                {
                    "code": "not_found",
                    "message": "Transition not found for this workflow.",
                    "details": [],
                }
            ) from exc

    def admin_validation_response(self, serializer):
        return Response(
            {
                "code": "validation_error",
                "message": "Invalid admin workflow payload.",
                "details": format_validation_details(serializer.errors),
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    def write_audit(self, request, admin_context, activity_type, payload):
        Activity.objects.create(
            activityid=uuid.uuid4(),
            tenantid_id=request.tenant_id,
            requestid_id=None,
            actorid_id=admin_context.user.user_id,
            type=activity_type,
            payload=json.dumps(payload, default=str),
            createdat=timezone.now(),
        )

    def transition_statuses(self, request, flow, serializer):
        from_status = self.get_status(
            request, flow, serializer.validated_data["from_status_id"]
        )
        to_status = self.get_status(
            request, flow, serializer.validated_data["to_status_id"]
        )
        return from_status, to_status


class AdminWorkflowListCreateView(AdminWorkflowBaseView):
    @extend_schema(
        responses=AdminFlowSerializer(many=True),
        examples=[
            OpenApiExample(
                "Workflow list",
                value=[
                    {
                        "flow_id": "11111111-1111-1111-1111-111111111111",
                        "name": "IT Support",
                        "description": "Default support workflow",
                        "created_at": "2026-06-12T12:00:00Z",
                    }
                ],
                response_only=True,
            )
        ],
        description="List tenant-scoped workflows for admin configuration.",
    )
    def get(self, request):
        admin_context = self.get_admin_context_or_response(request)
        if isinstance(admin_context, Response):
            return admin_context
        flows = Flow.objects.filter(tenantid=request.tenant_id).order_by("name")
        return Response(AdminFlowSerializer(flows, many=True).data)

    @extend_schema(
        request=AdminFlowWriteSerializer,
        responses={201: AdminFlowSerializer},
        examples=[
            OpenApiExample(
                "Create workflow",
                value={"name": "Facilities", "description": "Facilities requests"},
                request_only=True,
            )
        ],
        description="Create a tenant-scoped workflow and audit the admin write.",
    )
    def post(self, request):
        admin_context = self.get_admin_context_or_response(request)
        if isinstance(admin_context, Response):
            return admin_context
        serializer = AdminFlowWriteSerializer(data=request.data)
        if not serializer.is_valid():
            return self.admin_validation_response(serializer)

        now = timezone.now()
        with transaction.atomic():
            flow = Flow.objects.create(
                flowid=uuid.uuid4(),
                tenantid_id=request.tenant_id,
                name=serializer.validated_data["name"],
                description=serializer.validated_data.get("description") or "",
                createdat=now,
            )
            self.write_audit(
                request,
                admin_context,
                "admin.workflow.created",
                {"flow_id": flow.flowid, "name": flow.name},
            )
        return Response(AdminFlowSerializer(flow).data, status=status.HTTP_201_CREATED)


class AdminWorkflowDetailView(AdminWorkflowBaseView):
    @extend_schema(
        responses=AdminFlowSerializer,
        description="Return a tenant-scoped workflow with statuses and transitions.",
    )
    def get(self, request, flow_id):
        admin_context = self.get_admin_context_or_response(request)
        if isinstance(admin_context, Response):
            return admin_context
        flow = self.get_flow(request, flow_id)
        data = AdminFlowSerializer(flow).data
        data["statuses"] = AdminStatusSerializer(
            Status.objects.filter(
                tenantid=request.tenant_id, flowid=flow.flowid
            ).order_by("name"),
            many=True,
        ).data
        data["transitions"] = AdminTransitionSerializer(
            Transition.objects.filter(flowid=flow.flowid).order_by("createdat"),
            many=True,
        ).data
        return Response(data)

    @extend_schema(
        request=AdminFlowWriteSerializer,
        responses=AdminFlowSerializer,
        examples=[
            OpenApiExample(
                "Update workflow",
                value={"name": "IT Support", "description": "Updated description"},
                request_only=True,
            )
        ],
        description="Update a tenant-scoped workflow and audit the admin write.",
    )
    def patch(self, request, flow_id):
        admin_context = self.get_admin_context_or_response(request)
        if isinstance(admin_context, Response):
            return admin_context
        flow = self.get_flow(request, flow_id)
        serializer = AdminFlowWriteSerializer(data=request.data, partial=True)
        if not serializer.is_valid():
            return self.admin_validation_response(serializer)

        changed_fields = []
        for field in ("name", "description"):
            if field in serializer.validated_data:
                setattr(flow, field, serializer.validated_data[field] or "")
                changed_fields.append(field)
        with transaction.atomic():
            if changed_fields:
                flow.save(update_fields=changed_fields)
            self.write_audit(
                request,
                admin_context,
                "admin.workflow.updated",
                {"flow_id": flow.flowid, "changed_fields": changed_fields},
            )
        return Response(AdminFlowSerializer(flow).data)


class AdminWorkflowStatusCreateView(AdminWorkflowBaseView):
    @extend_schema(
        request=AdminStatusWriteSerializer,
        responses={201: AdminStatusSerializer},
        examples=[
            OpenApiExample(
                "Create status",
                value={"name": "Waiting", "category": "waiting", "is_terminal": False},
                request_only=True,
            )
        ],
        description="Create a status in a tenant-scoped workflow.",
    )
    def post(self, request, flow_id):
        admin_context = self.get_admin_context_or_response(request)
        if isinstance(admin_context, Response):
            return admin_context
        flow = self.get_flow(request, flow_id)
        serializer = AdminStatusWriteSerializer(data=request.data)
        if not serializer.is_valid():
            return self.admin_validation_response(serializer)

        with transaction.atomic():
            status_obj = Status.objects.create(
                statusid=uuid.uuid4(),
                tenantid_id=request.tenant_id,
                flowid=flow,
                name=serializer.validated_data["name"],
                category=serializer.validated_data["category"],
                isterminal=serializer.validated_data.get("is_terminal", False),
                createdat=timezone.now(),
            )
            self.write_audit(
                request,
                admin_context,
                "admin.status.created",
                {
                    "flow_id": flow.flowid,
                    "status_id": status_obj.statusid,
                    "name": status_obj.name,
                },
            )
        return Response(
            AdminStatusSerializer(status_obj).data, status=status.HTTP_201_CREATED
        )


class AdminWorkflowStatusDetailView(AdminWorkflowBaseView):
    @extend_schema(
        request=AdminStatusWriteSerializer,
        responses=AdminStatusSerializer,
        description="Update a status in a tenant-scoped workflow.",
    )
    def patch(self, request, flow_id, status_id):
        admin_context = self.get_admin_context_or_response(request)
        if isinstance(admin_context, Response):
            return admin_context
        flow = self.get_flow(request, flow_id)
        status_obj = self.get_status(request, flow, status_id)
        serializer = AdminStatusWriteSerializer(data=request.data, partial=True)
        if not serializer.is_valid():
            return self.admin_validation_response(serializer)

        field_map = {
            "name": "name",
            "category": "category",
            "is_terminal": "isterminal",
        }
        changed_fields = []
        for public_field, model_field in field_map.items():
            if public_field in serializer.validated_data:
                setattr(
                    status_obj, model_field, serializer.validated_data[public_field]
                )
                changed_fields.append(model_field)
        with transaction.atomic():
            if changed_fields:
                status_obj.save(update_fields=changed_fields)
            self.write_audit(
                request,
                admin_context,
                "admin.status.updated",
                {
                    "flow_id": flow.flowid,
                    "status_id": status_obj.statusid,
                    "changed_fields": changed_fields,
                },
            )
        return Response(AdminStatusSerializer(status_obj).data)


class AdminWorkflowTransitionCreateView(AdminWorkflowBaseView):
    @extend_schema(
        request=AdminTransitionWriteSerializer,
        responses={201: AdminTransitionSerializer},
        examples=[
            OpenApiExample(
                "Create transition",
                value={
                    "from_status_id": "22222222-2222-2222-2222-222222222222",
                    "to_status_id": "33333333-3333-3333-3333-333333333333",
                    "guard_roles_json": "[]",
                    "guard_perms_json": "[]",
                    "auto_rules": "{}",
                },
                request_only=True,
            )
        ],
        description="Create a workflow transition scoped through its workflow.",
    )
    def post(self, request, flow_id):
        admin_context = self.get_admin_context_or_response(request)
        if isinstance(admin_context, Response):
            return admin_context
        flow = self.get_flow(request, flow_id)
        serializer = AdminTransitionWriteSerializer(data=request.data)
        if not serializer.is_valid():
            return self.admin_validation_response(serializer)
        from_status, to_status = self.transition_statuses(request, flow, serializer)

        with transaction.atomic():
            transition = Transition.objects.create(
                transitionid=uuid.uuid4(),
                flowid=flow,
                fromstatusid=from_status,
                tostatusid=to_status,
                guardrolesjson=serializer.validated_data.get("guard_roles_json"),
                guardpermsjson=serializer.validated_data.get("guard_perms_json"),
                autorules=serializer.validated_data.get("auto_rules"),
                createdat=timezone.now(),
            )
            self.write_audit(
                request,
                admin_context,
                "admin.transition.created",
                {
                    "flow_id": flow.flowid,
                    "transition_id": transition.transitionid,
                    "from_status_id": from_status.statusid,
                    "to_status_id": to_status.statusid,
                },
            )
        return Response(
            AdminTransitionSerializer(transition).data, status=status.HTTP_201_CREATED
        )


class AdminWorkflowTransitionDetailView(AdminWorkflowBaseView):
    @extend_schema(
        request=AdminTransitionWriteSerializer,
        responses=AdminTransitionSerializer,
        description="Update a workflow transition scoped through its workflow.",
    )
    def patch(self, request, flow_id, transition_id):
        admin_context = self.get_admin_context_or_response(request)
        if isinstance(admin_context, Response):
            return admin_context
        flow = self.get_flow(request, flow_id)
        transition = self.get_transition(flow, transition_id)
        serializer = AdminTransitionWriteSerializer(data=request.data, partial=True)
        if not serializer.is_valid():
            return self.admin_validation_response(serializer)

        changed_fields = []
        if "from_status_id" in serializer.validated_data:
            transition.fromstatusid = self.get_status(
                request, flow, serializer.validated_data["from_status_id"]
            )
            changed_fields.append("fromstatusid")
        if "to_status_id" in serializer.validated_data:
            transition.tostatusid = self.get_status(
                request, flow, serializer.validated_data["to_status_id"]
            )
            changed_fields.append("tostatusid")
        field_map = {
            "guard_roles_json": "guardrolesjson",
            "guard_perms_json": "guardpermsjson",
            "auto_rules": "autorules",
        }
        for public_field, model_field in field_map.items():
            if public_field in serializer.validated_data:
                setattr(
                    transition, model_field, serializer.validated_data[public_field]
                )
                changed_fields.append(model_field)
        with transaction.atomic():
            if changed_fields:
                transition.save(update_fields=changed_fields)
            self.write_audit(
                request,
                admin_context,
                "admin.transition.updated",
                {
                    "flow_id": flow.flowid,
                    "transition_id": transition.transitionid,
                    "changed_fields": changed_fields,
                },
            )
        return Response(AdminTransitionSerializer(transition).data)


class CommentViewSet(
    mixins.ListModelMixin, mixins.CreateModelMixin, viewsets.GenericViewSet
):
    permission_classes = [TenantPermission]
    serializer_class = CommentSerializer

    def get_request_uuid(self):
        request_id = self.kwargs.get("request_pk")
        try:
            return uuid.UUID(str(request_id))
        except (TypeError, ValueError) as exc:
            raise ValidationError(
                {
                    "code": "validation_error",
                    "message": "Invalid request id.",
                    "details": [{"field": "request_id", "message": "Invalid UUID."}],
                }
            ) from exc

    def get_request(self):
        request_id = self.get_request_uuid()
        tenant_id = self.request.tenant_id
        try:
            return Request.objects.get(requestid=request_id, tenantid=tenant_id)
        except Request.DoesNotExist as exc:
            raise NotFound(
                {
                    "code": "not_found",
                    "message": "Request not found for this tenant.",
                    "details": [],
                }
            ) from exc

    def get_queryset(self):
        tenant_id = self.request.tenant_id
        request_id = self.get_request_uuid()
        return Comment.objects.filter(
            tenantid=tenant_id, requestid=request_id
        ).order_by("-createdat")

    def perform_create(self, serializer):
        req = self.get_request()
        comment = serializer.save(
            commentid=uuid.uuid4(),
            tenantid=req.tenantid,
            requestid=req,
            authorid=req.requesterid,
            createdat=timezone.now(),
        )
        if comment:
            notify_comment_added(comment)


class AttachmentViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    permission_classes = [TenantPermission]
    serializer_class = AttachmentSerializer

    def get_request_uuid(self):
        request_id = self.kwargs.get("request_pk")
        try:
            return uuid.UUID(str(request_id))
        except (TypeError, ValueError) as exc:
            raise ValidationError(
                {
                    "code": "validation_error",
                    "message": "Invalid request id.",
                    "details": [{"field": "request_id", "message": "Invalid UUID."}],
                }
            ) from exc

    def get_queryset(self):
        tenant_id = self.request.tenant_id
        request_id = self.get_request_uuid()
        return Attachment.objects.filter(
            tenantid=tenant_id, requestid=request_id
        ).order_by("-createdat")


class AttachmentInitView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = AttachmentInitRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        tenant_id = getattr(request, "tenant_id", None)
        if not tenant_id:
            return Response({"detail": "Tenant context missing."}, status=400)

        try:
            req = Request.objects.get(requestid=data["request_id"], tenantid=tenant_id)
        except Request.DoesNotExist:
            return Response(
                {"detail": "Request not found for this tenant."}, status=404
            )

        group_id = uuid.uuid4()
        s3 = boto3.client(
            "s3",
            endpoint_url=settings.MINIO_ENDPOINT,
            aws_access_key_id=settings.MINIO_ACCESS_KEY,
            aws_secret_access_key=settings.MINIO_SECRET_KEY,
            config=Config(signature_version="s3v4"),
            region_name=settings.MINIO_REGION,
        )

        uploads = []
        for file_data in data["files"]:
            filename = file_data["filename"]
            content_type = file_data["content_type"]
            object_key = f"uploads/{group_id}/{uuid.uuid4()}-{filename}"
            url = s3.generate_presigned_url(
                "put_object",
                Params={
                    "Bucket": settings.MINIO_BUCKET,
                    "Key": object_key,
                    "ContentType": content_type,
                },
                ExpiresIn=3600,
            )

            upload = {
                "filename": filename,
                "content_type": content_type,
                "object_key": object_key,
                "url": url,
                "method": "PUT",
                "headers": {"Content-Type": content_type},
            }
            if file_data.get("size_bytes") is not None:
                upload["size_bytes"] = file_data["size_bytes"]
            if file_data.get("checksum"):
                upload["checksum"] = file_data["checksum"]
            uploads.append(upload)

        response = AttachmentInitResponseSerializer(
            {
                "request_id": req.requestid,
                "group_id": group_id,
                "uploads": uploads,
            }
        )
        return Response(response.data)


class AttachmentFinalizeView(APIView):
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request):
        serializer = AttachmentFinalizeRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        tenant_id = getattr(request, "tenant_id", None)
        if not tenant_id:
            return Response({"detail": "Tenant context missing."}, status=400)

        try:
            req = Request.objects.get(requestid=data["request_id"], tenantid=tenant_id)
        except Request.DoesNotExist:
            return Response(
                {"detail": "Request not found for this tenant."}, status=404
            )

        now = timezone.now()
        group_id = str(data["group_id"])
        message = data.get("message") or ""

        # Use the request owner until auth_user -> dbo.User mapping exists.
        author = req.requesterid
        comment = Comment.objects.create(
            commentid=uuid.uuid4(),
            tenantid=req.tenantid,
            requestid=req,
            authorid=author,
            groupid=group_id,
            messagemd=message,
            visibility="public",
            createdat=now,
        )

        attachments = []
        for file_data in data["files"]:
            object_key = file_data["object_key"]
            storage_url = build_storage_url(object_key)
            attachments.append(
                Attachment(
                    attachmentid=uuid.uuid4(),
                    tenantid=req.tenantid,
                    requestid=req,
                    commentid=comment,
                    groupid=group_id,
                    filename=file_data["filename"],
                    storageurl=storage_url,
                    contenttype=file_data.get("content_type") or "",
                    sizebytes=file_data.get("size_bytes") or 0,
                    checksum=file_data.get("checksum") or "",
                    scanstatus="pending",
                    createdat=now,
                )
            )

        Attachment.objects.bulk_create(attachments)
        Activity.objects.create(
            activityid=uuid.uuid4(),
            tenantid=req.tenantid,
            requestid=req,
            actorid=author,
            type="attachments.finalized",
            payload=json.dumps(
                {
                    "comment_id": str(comment.commentid),
                    "group_id": group_id,
                    "filenames": [file_data["filename"] for file_data in data["files"]],
                }
            ),
            createdat=now,
        )
        notify_comment_added(comment)

        return Response(
            {
                "request_id": str(req.requestid),
                "group_id": group_id,
                "comment_id": str(comment.commentid),
                "attachments": [
                    {
                        "attachment_id": str(attachment.attachmentid),
                        "filename": attachment.filename,
                        "storage_url": attachment.storageurl,
                    }
                    for attachment in attachments
                ],
            },
            status=201,
        )


class SearchView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        serializer = SearchQuerySerializer(data=request.query_params)
        if not serializer.is_valid():
            return Response(
                {
                    "code": "validation_error",
                    "message": "Invalid search query.",
                    "details": serializer.errors,
                },
                status=400,
            )

        tenant_id = getattr(request, "tenant_id", None)
        if not tenant_id:
            return Response(
                {
                    "code": "tenant_required",
                    "message": "Tenant context missing.",
                    "details": [],
                },
                status=400,
            )

        data = serializer.validated_data
        try:
            results = search_requests(
                tenant_id=tenant_id,
                raw_query=data["q"],
                page=data["page"],
                page_size=data["page_size"],
                types=data.get("types"),
                status_id=data.get("status_id"),
                assignee_id=data.get("assignee_id"),
                flow_id=data.get("flow_id"),
                created_from=data.get("created_from"),
                created_to=data.get("created_to"),
                updated_from=data.get("updated_from"),
                updated_to=data.get("updated_to"),
            )
        except SearchValidationError as exc:
            return Response(
                {
                    "code": "validation_error",
                    "message": str(exc),
                    "details": [],
                },
                status=400,
            )
        return Response(results)


def format_validation_details(errors):
    details = []

    def walk(value, field):
        if isinstance(value, dict):
            for key, child in value.items():
                child_field = f"{field}.{key}" if field else str(key)
                walk(child, child_field)
            return
        if isinstance(value, list):
            for child in value:
                walk(child, field)
            return
        details.append({"field": field, "message": str(value)})

    walk(errors, "")
    return details


def validation_error_response(errors):
    return Response(
        {
            "code": "validation_error",
            "message": "Invalid request payload.",
            "details": format_validation_details(errors),
        },
        status=status.HTTP_400_BAD_REQUEST,
    )


def admin_error_response(exc):
    return Response(
        {
            "code": exc.code,
            "message": exc.message,
            "details": [],
        },
        status=exc.status_code,
    )


def build_dashboard_summary(queryset, user_id=None):
    today = timezone.localdate()
    open_requests = queryset.filter(statusid__category__iexact="open")
    in_progress_requests = queryset.filter(statusid__category__iexact="in_progress")
    waiting_requests = queryset.filter(statusid__category__iexact="waiting")
    closed_requests = queryset.filter(statusid__category__iexact="closed")
    active_requests = queryset.exclude(statusid__category__iexact="closed").exclude(
        statusid__isterminal=True
    )

    return {
        "open": open_requests.count(),
        "in_progress": in_progress_requests.count(),
        "waiting": waiting_requests.count(),
        "closed": closed_requests.count(),
        "due_today": active_requests.filter(dueat__date=today).count(),
        "overdue": active_requests.filter(dueat__date__lt=today).count(),
        "assigned_to_me": count_assigned_to_me(queryset, user_id),
        "unassigned": active_requests.filter(assigneeid__isnull=True).count(),
    }


def count_assigned_to_me(queryset, user_id):
    try:
        assignee_id = uuid.UUID(str(user_id))
    except (TypeError, ValueError, AttributeError):
        return 0
    return queryset.filter(assigneeid_id=assignee_id).count()


def transition_not_available_response(message):
    return Response(
        {
            "code": "invalid_transition",
            "message": message,
            "details": [],
        },
        status=status.HTTP_400_BAD_REQUEST,
    )


def get_available_transitions(rt_request):
    return Transition.objects.filter(
        flowid=rt_request.flowid_id,
        fromstatusid=rt_request.statusid_id,
    ).select_related("tostatusid")


def find_transition_by_target_category(rt_request, categories, terminal=False):
    normalized_categories = {category.lower() for category in categories}
    for transition in get_available_transitions(rt_request):
        target = transition.tostatusid
        category = (target.category or "").lower()
        if category in normalized_categories or (terminal and target.isterminal):
            return transition
    return None


def status_category(status_obj):
    return (getattr(status_obj, "category", "") or "").lower()


def status_changed_to_closed(previous_status, current_status):
    return (
        status_category(previous_status) != "closed"
        and status_category(current_status) == "closed"
    )


@transaction.atomic
def apply_transition(rt_request, transition, action_type, comment=""):
    previous_status_id = rt_request.statusid_id
    previous_status = rt_request.statusid
    now = timezone.now()
    rt_request.statusid = transition.tostatusid
    rt_request.updatedat = now
    rt_request.save(update_fields=["statusid", "updatedat"])

    created_comment = None
    if comment:
        created_comment = Comment.objects.create(
            commentid=uuid.uuid4(),
            tenantid=rt_request.tenantid,
            requestid=rt_request,
            authorid=rt_request.requesterid,
            messagemd=comment,
            visibility="public",
            createdat=now,
        )

    Activity.objects.create(
        activityid=uuid.uuid4(),
        tenantid=rt_request.tenantid,
        requestid=rt_request,
        actorid=rt_request.requesterid,
        type=action_type,
        payload=json.dumps(
            {
                "transition_id": str(transition.transitionid),
                "from_status_id": str(previous_status_id),
                "to_status_id": str(transition.tostatusid_id),
                "comment_id": (
                    str(created_comment.commentid) if created_comment else None
                ),
            }
        ),
        createdat=now,
    )
    if status_changed_to_closed(previous_status, transition.tostatusid):
        notify_request_closed(rt_request)
    return rt_request


def build_storage_url(object_key):
    endpoint = getattr(settings, "MINIO_PUBLIC_URL", None) or settings.MINIO_ENDPOINT
    return f"{endpoint.rstrip('/')}/{settings.MINIO_BUCKET}/{object_key}"


def generate_human_id(tenant_id) -> str:
    year = datetime.utcnow().year
    with transaction.atomic():
        with connection.cursor() as cur:
            cur.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE;")
            cur.execute(
                "SELECT LastValue FROM dbo.IdSequence WITH (UPDLOCK, HOLDLOCK) "
                "WHERE TenantId=%s AND Year=%s;",
                [tenant_id, year],
            )
            row = cur.fetchone()
            if row:
                last = row[0] + 1
                cur.execute(
                    "UPDATE dbo.IdSequence SET LastValue=%s "
                    "WHERE TenantId=%s AND Year=%s;",
                    [last, tenant_id, year],
                )
            else:
                last = 1
                cur.execute(
                    "INSERT INTO dbo.IdSequence (TenantId, Year, LastValue) "
                    "VALUES (%s,%s,%s);",
                    [tenant_id, year, last],
                )
    return f"RT-{year}-{last:06d}"
