import json
import uuid
from datetime import datetime

import boto3
from botocore.client import Config
from django.conf import settings
from django.db import connection, transaction
from django.utils import timezone
from rest_framework import mixins, permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Activity, Attachment, Comment, Request
from .search import SearchValidationError, search_requests
from .serializers import (
    ActivitySerializer,
    AttachmentFinalizeRequestSerializer,
    AttachmentInitRequestSerializer,
    AttachmentInitResponseSerializer,
    AttachmentSerializer,
    CommentSerializer,
    RequestDetailSerializer,
    RequestSerializer,
    SearchQuerySerializer,
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

        save_kwargs = {
            "tenantid_id": tenant_id,
            "humanid": generate_human_id(str(tenant_id)),
            "createdat": timezone.now(),
            "updatedat": timezone.now(),
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
        return rt_request

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
        serializer.save(
            commentid=uuid.uuid4(),
            tenantid=req.tenantid,
            requestid=req,
            authorid=req.requesterid,
            createdat=timezone.now(),
        )


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
