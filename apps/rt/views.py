import uuid  # <-- Asegúrate de que uuid esté importado

from django.db import connection, transaction
from django.utils import timezone
from rest_framework import mixins, permissions, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import Activity, Attachment, Comment, Request
from .serializers import (
    ActivitySerializer,
    AttachmentSerializer,
    CommentSerializer,
    RequestSerializer,
)


class TenantPermission(permissions.IsAuthenticated):
    # DRF Perm + middleware ya validan token & tenant membership
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
        """
        Asegura que todos los UUIDs sean válidos y solo pasa a .save() los campos correctos.
        """
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

        humanid = generate_human_id(str(tenant_id))
        now = timezone.now()

        save_kwargs = dict(
            tenantid_id=tenant_id,
            humanid=humanid,
            createdat=now,
            updatedat=now,
            flowid_id=flow_id,
            statusid_id=status_id,
            requesterid_id=requester_id,
        )
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
        import uuid

        tenant_id = self.request.tenant_id
        request_id = self.kwargs.get("request_pk")
        # Asegura que tenant_id y request_id sean UUID
        if isinstance(tenant_id, str):
            tenant_id = uuid.UUID(tenant_id)
        if isinstance(request_id, str):
            request_id = uuid.UUID(request_id)
        user = self.request.user
        now = timezone.now()
        serializer.save(
            tenantid_id=tenant_id,
            requestid_id=request_id,
            authorid=str(user.id),
            createdat=now,
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


# --- HumanId Generator (RT-YYYY-000001 por tenant+year) ---


def generate_human_id(tenant_id) -> str:
    # Requiere tabla dbo.IdSequence (TenantId, Year, LastValue)
    from datetime import datetime

    year = datetime.utcnow().year
    with transaction.atomic():
        with connection.cursor() as cur:
            # SERIALIZABLE garantiza exclusión
            cur.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE;")
            cur.execute(
                "SELECT LastValue FROM dbo.IdSequence WITH (UPDLOCK, HOLDLOCK) WHERE TenantId=%s AND Year=%s;",
                [tenant_id, year],
            )
            row = cur.fetchone()
            if row:
                last = row[0] + 1
                cur.execute(
                    "UPDATE dbo.IdSequence SET LastValue=%s WHERE TenantId=%s AND Year=%s;",
                    [last, tenant_id, year],
                )
            else:
                last = 1
                cur.execute(
                    "INSERT INTO dbo.IdSequence (TenantId, Year, LastValue) VALUES (%s,%s,%s);",
                    [tenant_id, year, last],
                )
    return f"RT-{year}-{last:06d}"


# --- End HumanId Generator ---
