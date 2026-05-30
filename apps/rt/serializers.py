from rest_framework import serializers

from .models import (
    Activity,
    Attachment,
    Comment,
    Flow,
    Membership,
    Request,
    Status,
    User,
)


class RequestSerializer(serializers.ModelSerializer):
    VALID_PRIORITIES = {"low", "normal", "high", "urgent"}

    request_id = serializers.UUIDField(source="requestid", read_only=True)
    human_id = serializers.CharField(source="humanid", read_only=True)
    flow_id = serializers.UUIDField(source="flowid_id")
    status_id = serializers.UUIDField(source="statusid_id")
    requester_id = serializers.UUIDField(source="requesterid_id")
    assignee_id = serializers.UUIDField(
        source="assigneeid_id", required=False, allow_null=True
    )
    custom_fields = serializers.CharField(
        source="customfields", required=False, allow_blank=True, allow_null=True
    )
    due_at = serializers.DateTimeField(source="dueat", required=False, allow_null=True)
    created_at = serializers.DateTimeField(source="createdat", read_only=True)
    updated_at = serializers.DateTimeField(source="updatedat", read_only=True)

    class Meta:
        model = Request
        fields = [
            "request_id",
            "human_id",
            "title",
            "description",
            "priority",
            "flow_id",
            "status_id",
            "requester_id",
            "assignee_id",
            "custom_fields",
            "due_at",
            "created_at",
            "updated_at",
        ]

    def validate_title(self, value):
        if not value.strip():
            raise serializers.ValidationError("Title is required.")
        return value

    def validate_priority(self, value):
        normalized = value.strip().lower()
        if normalized not in self.VALID_PRIORITIES:
            allowed = ", ".join(sorted(self.VALID_PRIORITIES))
            raise serializers.ValidationError(f"Priority must be one of: {allowed}.")
        return normalized

    def validate(self, attrs):
        tenant_id = self.context.get("tenant_id")
        if not tenant_id:
            raise serializers.ValidationError({"tenant": ["Tenant context missing."]})

        flow_id = attrs.get("flowid_id")
        status_id = attrs.get("statusid_id")
        requester_id = attrs.get("requesterid_id")
        assignee_id = attrs.get("assigneeid_id")

        self._get_tenant_object(Flow, "flow_id", flowid=flow_id, tenantid=tenant_id)
        status = self._get_tenant_object(
            Status, "status_id", statusid=status_id, tenantid=tenant_id
        )
        if status.flowid_id != flow_id:
            raise serializers.ValidationError(
                {"status_id": ["Status must belong to the selected flow."]}
            )

        self._validate_user_membership("requester_id", requester_id, tenant_id)
        if assignee_id:
            self._validate_user_membership("assignee_id", assignee_id, tenant_id)
        return attrs

    def _get_tenant_object(self, model, public_field, **lookup):
        try:
            return model.objects.get(**lookup)
        except model.DoesNotExist as exc:
            raise serializers.ValidationError(
                {public_field: ["Not found for this tenant."]}
            ) from exc

    def _validate_user_membership(self, public_field, user_id, tenant_id):
        if not Membership.objects.filter(
            userid_id=user_id, tenantid_id=tenant_id
        ).exists():
            raise serializers.ValidationError(
                {public_field: ["User is not a member of this tenant."]}
            )


class UserSummarySerializer(serializers.ModelSerializer):
    user_id = serializers.UUIDField(source="userid", read_only=True)
    display_name = serializers.CharField(source="displayname", read_only=True)
    employee_code = serializers.CharField(source="employeecode", read_only=True)
    avatar_url = serializers.CharField(source="avatarurl", read_only=True)

    class Meta:
        model = User
        fields = ["user_id", "email", "display_name", "employee_code", "avatar_url"]


class FlowSummarySerializer(serializers.ModelSerializer):
    flow_id = serializers.UUIDField(source="flowid", read_only=True)

    class Meta:
        model = Flow
        fields = ["flow_id", "name", "description"]


class StatusSummarySerializer(serializers.ModelSerializer):
    status_id = serializers.UUIDField(source="statusid", read_only=True)
    is_terminal = serializers.BooleanField(source="isterminal", read_only=True)

    class Meta:
        model = Status
        fields = ["status_id", "name", "category", "is_terminal"]


class RequestDetailSerializer(serializers.ModelSerializer):
    request_id = serializers.UUIDField(source="requestid", read_only=True)
    human_id = serializers.CharField(source="humanid", read_only=True)
    flow = FlowSummarySerializer(source="flowid", read_only=True)
    status = StatusSummarySerializer(source="statusid", read_only=True)
    requester = UserSummarySerializer(source="requesterid", read_only=True)
    assignee = UserSummarySerializer(source="assigneeid", read_only=True)
    flow_id = serializers.UUIDField(source="flowid_id", read_only=True)
    status_id = serializers.UUIDField(source="statusid_id", read_only=True)
    requester_id = serializers.UUIDField(source="requesterid_id", read_only=True)
    assignee_id = serializers.UUIDField(source="assigneeid_id", read_only=True)
    custom_fields = serializers.CharField(source="customfields", read_only=True)
    due_at = serializers.DateTimeField(source="dueat", read_only=True)
    created_at = serializers.DateTimeField(source="createdat", read_only=True)
    updated_at = serializers.DateTimeField(source="updatedat", read_only=True)
    tags = serializers.SerializerMethodField()

    class Meta:
        model = Request
        fields = [
            "request_id",
            "human_id",
            "title",
            "description",
            "priority",
            "flow_id",
            "flow",
            "status_id",
            "status",
            "requester_id",
            "requester",
            "assignee_id",
            "assignee",
            "custom_fields",
            "tags",
            "due_at",
            "created_at",
            "updated_at",
        ]

    def get_tags(self, obj):
        return []


class CommentSerializer(serializers.ModelSerializer):
    body = serializers.CharField(required=False, allow_blank=True, write_only=True)
    message = serializers.CharField(source="messagemd", read_only=True)
    visibility = serializers.CharField(required=False, allow_blank=True)
    messagemd = serializers.CharField(required=False, allow_blank=True)

    class Meta:
        model = Comment
        fields = [
            "commentid",
            "requestid",
            "authorid",
            "messagemd",
            "message",
            "body",
            "visibility",
            "createdat",
        ]
        read_only_fields = ["commentid", "requestid", "authorid", "createdat"]

    def validate(self, attrs):
        body = attrs.pop("body", None)
        if body is not None and "messagemd" not in attrs:
            attrs["messagemd"] = body
        attrs.setdefault("messagemd", "")
        attrs.setdefault("visibility", "public")
        return attrs


class AttachmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Attachment
        fields = [
            "attachmentid",
            "requestid",
            "commentid",
            "groupid",
            "filename",
            "contenttype",
            "sizebytes",
            "storageurl",
            "checksum",
            "scanstatus",
            "createdat",
        ]
        read_only_fields = ["attachmentid", "createdat"]


class AttachmentInitFileSerializer(serializers.Serializer):
    filename = serializers.CharField(max_length=255)
    content_type = serializers.CharField(max_length=100)
    size_bytes = serializers.IntegerField(required=False, min_value=0)
    checksum = serializers.CharField(required=False, allow_blank=True)


class AttachmentInitRequestSerializer(serializers.Serializer):
    request_id = serializers.UUIDField()
    files = AttachmentInitFileSerializer(many=True, allow_empty=False)


class PresignedUploadSerializer(serializers.Serializer):
    filename = serializers.CharField()
    content_type = serializers.CharField()
    size_bytes = serializers.IntegerField(required=False)
    checksum = serializers.CharField(required=False, allow_blank=True)
    object_key = serializers.CharField()
    url = serializers.CharField()
    method = serializers.CharField()
    headers = serializers.DictField()


class AttachmentInitResponseSerializer(serializers.Serializer):
    request_id = serializers.UUIDField()
    group_id = serializers.UUIDField()
    uploads = PresignedUploadSerializer(many=True)


class AttachmentFinalizeFileSerializer(serializers.Serializer):
    object_key = serializers.CharField(max_length=500)
    filename = serializers.CharField(max_length=255)
    content_type = serializers.CharField(
        max_length=100, required=False, allow_blank=True
    )
    size_bytes = serializers.IntegerField(required=False, min_value=0)
    checksum = serializers.CharField(required=False, allow_blank=True)


class AttachmentFinalizeRequestSerializer(serializers.Serializer):
    request_id = serializers.UUIDField()
    group_id = serializers.UUIDField()
    message = serializers.CharField(allow_blank=True, required=False)
    comment_markdown = serializers.CharField(
        allow_blank=True, required=False, write_only=True
    )
    files = AttachmentFinalizeFileSerializer(
        many=True, allow_empty=False, required=False
    )
    objects = AttachmentFinalizeFileSerializer(
        many=True, allow_empty=False, required=False, write_only=True
    )
    idempotency_key = serializers.CharField(
        max_length=120, required=False, allow_blank=True
    )

    def validate(self, attrs):
        objects = attrs.pop("objects", None)
        comment_markdown = attrs.pop("comment_markdown", None)
        if "files" not in attrs and objects is not None:
            attrs["files"] = objects
        if "message" not in attrs and comment_markdown is not None:
            attrs["message"] = comment_markdown
        if "files" not in attrs:
            raise serializers.ValidationError({"files": ["This field is required."]})
        attrs.setdefault("message", "")
        return attrs


class ActivitySerializer(serializers.ModelSerializer):
    class Meta:
        model = Activity
        fields = ["activityid", "requestid", "actorid", "type", "payload", "createdat"]


class SearchQuerySerializer(serializers.Serializer):
    q = serializers.CharField(max_length=200, trim_whitespace=True)
    page = serializers.IntegerField(required=False, min_value=1, default=1)
    page_size = serializers.IntegerField(
        required=False, min_value=1, max_value=100, default=25
    )
    types = serializers.CharField(required=False, allow_blank=True)
    status_id = serializers.UUIDField(required=False)
    assignee_id = serializers.UUIDField(required=False)
    flow_id = serializers.UUIDField(required=False)
    created_from = serializers.DateTimeField(required=False)
    created_to = serializers.DateTimeField(required=False)
    updated_from = serializers.DateTimeField(required=False)
    updated_to = serializers.DateTimeField(required=False)
