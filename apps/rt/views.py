import json
import uuid
from datetime import datetime

import boto3
from botocore.client import Config
from django.conf import settings
from django.db import connection, transaction
from django.utils import timezone
from rest_framework import mixins, permissions, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Activity, Attachment, Comment, Request
from .serializers import (
    ActivitySerializer,
    AttachmentFinalizeRequestSerializer,
    AttachmentInitRequestSerializer,
    AttachmentInitResponseSerializer,
    AttachmentSerializer,
    CommentSerializer,
    RequestSerializer,
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
        serializer.save(**save_kwargs)

    @action(detail=True, methods=["get"])
    def activity(self, request, pk=None):
        tenant_id = request.tenant_id
        items = Activity.objects.filter(tenantid=tenant_id, requestid=pk).order_by(
            "-createdat"
        )
        return Response(ActivitySerializer(items, many=True).data)


class CommentViewSet(
    mixins.ListModelMixin, mixins.CreateModelMixin, viewsets.GenericViewSet
):
    permission_classes = [TenantPermission]
    serializer_class = CommentSerializer

    def get_queryset(self):
        tenant_id = self.request.tenant_id
        request_id = self.kwargs.get("request_pk")
        return Comment.objects.filter(
            tenantid=tenant_id, requestid=request_id
        ).order_by("-createdat")

    def perform_create(self, serializer):
        tenant_id = self.request.tenant_id
        request_id = self.kwargs.get("request_pk")
        if isinstance(tenant_id, str):
            tenant_id = uuid.UUID(tenant_id)
        if isinstance(request_id, str):
            request_id = uuid.UUID(request_id)
        serializer.save(
            tenantid_id=tenant_id,
            requestid_id=request_id,
            authorid=str(self.request.user.id),
            createdat=timezone.now(),
        )


class AttachmentViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    permission_classes = [TenantPermission]
    serializer_class = AttachmentSerializer

    def get_queryset(self):
        tenant_id = self.request.tenant_id
        request_id = self.kwargs.get("request_pk")
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
