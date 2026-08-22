from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from .models import (
    Activity,
    Attachment,
    Comment,
    Featureflag,
    Flow,
    Membership,
    Notificationtemplate,
    Permission,
    Request,
    Role,
    Slapolicy,
    Status,
    Tenantsetting,
    Transition,
    User,
)
from .services.admin_configuration import (
    SUPPORTED_VALUE_TYPES,
    normalize_setting_value,
    validate_template_text,
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

        instance = getattr(self, "instance", None)
        missing = object()
        flow_id = attrs.get("flowid_id", getattr(instance, "flowid_id", None))
        status_id = attrs.get("statusid_id", getattr(instance, "statusid_id", None))
        requester_id = attrs.get(
            "requesterid_id", getattr(instance, "requesterid_id", None)
        )
        assignee_id = attrs.get("assigneeid_id", missing)
        if assignee_id is missing:
            assignee_id = getattr(instance, "assigneeid_id", None)

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


class FlowLookupSerializer(serializers.ModelSerializer):
    flow_id = serializers.UUIDField(source="flowid", read_only=True)

    class Meta:
        model = Flow
        fields = ["flow_id", "name"]


class StatusSummarySerializer(serializers.ModelSerializer):
    status_id = serializers.UUIDField(source="statusid", read_only=True)
    is_terminal = serializers.BooleanField(source="isterminal", read_only=True)

    class Meta:
        model = Status
        fields = ["status_id", "name", "category", "is_terminal"]


class StatusLookupSerializer(serializers.ModelSerializer):
    status_id = serializers.UUIDField(source="statusid", read_only=True)
    flow_id = serializers.UUIDField(source="flowid_id", read_only=True)
    is_terminal = serializers.BooleanField(source="isterminal", read_only=True)

    class Meta:
        model = Status
        fields = ["status_id", "flow_id", "name", "category", "is_terminal"]


class UserLookupSerializer(serializers.ModelSerializer):
    user_id = serializers.UUIDField(source="userid", read_only=True)
    display_name = serializers.CharField(source="displayname", read_only=True)

    class Meta:
        model = User
        fields = ["user_id", "display_name", "email"]


class TransitionLookupSerializer(serializers.ModelSerializer):
    transition_id = serializers.UUIDField(source="transitionid", read_only=True)
    from_status_id = serializers.UUIDField(source="fromstatusid_id", read_only=True)
    to_status_id = serializers.UUIDField(source="tostatusid_id", read_only=True)
    to_status = StatusLookupSerializer(source="tostatusid", read_only=True)

    class Meta:
        model = Transition
        fields = ["transition_id", "from_status_id", "to_status_id", "to_status"]


class RequestTransitionSerializer(serializers.Serializer):
    transition_id = serializers.UUIDField()
    comment = serializers.CharField(required=False, allow_blank=True)


class RequestCloseReopenSerializer(serializers.Serializer):
    comment = serializers.CharField(required=False, allow_blank=True)


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

    @extend_schema_field(serializers.ListField(child=serializers.CharField()))
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


class AdminUserContextSerializer(serializers.Serializer):
    user_id = serializers.UUIDField()
    display_name = serializers.CharField()
    email = serializers.EmailField()


class AdminPermissionsSerializer(serializers.Serializer):
    tenant_id = serializers.UUIDField()
    user = AdminUserContextSerializer()
    roles = serializers.ListField(child=serializers.CharField())
    permissions = serializers.ListField(child=serializers.CharField())
    is_admin = serializers.BooleanField()
    can_read_audit = serializers.BooleanField()


class AdminAuditSerializer(serializers.ModelSerializer):
    activity_id = serializers.UUIDField(source="activityid", read_only=True)
    request_id = serializers.UUIDField(source="requestid_id", read_only=True)
    actor_id = serializers.UUIDField(source="actorid_id", read_only=True)
    created_at = serializers.DateTimeField(source="createdat", read_only=True)
    payload_json = serializers.SerializerMethodField()
    entity_id = serializers.SerializerMethodField()
    entity_type = serializers.SerializerMethodField()

    class Meta:
        model = Activity
        fields = [
            "activity_id",
            "request_id",
            "actor_id",
            "type",
            "payload",
            "payload_json",
            "entity_id",
            "entity_type",
            "created_at",
        ]

    @extend_schema_field(serializers.JSONField(allow_null=True))
    def get_payload_json(self, obj):
        import json

        try:
            value = json.loads(obj.payload) if obj.payload else None
        except (TypeError, ValueError):
            return None
        return value if isinstance(value, (dict, list)) else None

    @extend_schema_field(serializers.UUIDField(allow_null=True))
    def get_entity_id(self, obj):
        payload = self.get_payload_json(obj)
        value = payload.get("entity_id") if isinstance(payload, dict) else None
        return value or obj.requestid_id

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_entity_type(self, obj):
        payload = self.get_payload_json(obj)
        if isinstance(payload, dict) and payload.get("entity_type"):
            return payload["entity_type"]
        return "request" if obj.requestid_id else None


class AdminAuditFilterSerializer(serializers.Serializer):
    type = serializers.CharField(required=False, max_length=50)
    actor_id = serializers.UUIDField(required=False)
    request_id = serializers.UUIDField(required=False)
    entity_id = serializers.UUIDField(required=False)
    created_from = serializers.DateTimeField(required=False)
    created_to = serializers.DateTimeField(required=False)
    page = serializers.IntegerField(required=False, min_value=1, default=1)
    page_size = serializers.IntegerField(
        required=False, min_value=1, max_value=100, default=25
    )

    def validate(self, attrs):
        if (
            attrs.get("created_from")
            and attrs.get("created_to")
            and attrs["created_to"] < attrs["created_from"]
        ):
            raise serializers.ValidationError(
                {"created_to": ["Must be on or after created_from."]}
            )
        return attrs


class PaginatedAdminAuditResponseSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    next = serializers.URLField(allow_null=True)
    previous = serializers.URLField(allow_null=True)
    results = AdminAuditSerializer(many=True)


class AdminDirectoryUserSerializer(serializers.ModelSerializer):
    user_id = serializers.UUIDField(source="userid", read_only=True)
    display_name = serializers.CharField(source="displayname", read_only=True)
    employee_code = serializers.CharField(
        source="employeecode", read_only=True, allow_null=True
    )
    avatar_url = serializers.CharField(
        source="avatarurl", read_only=True, allow_null=True
    )
    is_active = serializers.BooleanField(source="isactive", read_only=True)
    created_at = serializers.DateTimeField(source="createdat", read_only=True)
    updated_at = serializers.DateTimeField(
        source="updatedat", read_only=True, allow_null=True
    )

    class Meta:
        model = User
        fields = [
            "user_id",
            "email",
            "display_name",
            "employee_code",
            "avatar_url",
            "is_active",
            "created_at",
            "updated_at",
        ]


class AdminUserCreateSerializer(serializers.Serializer):
    email = serializers.EmailField(max_length=320)
    display_name = serializers.CharField(max_length=200, trim_whitespace=True)
    employee_code = serializers.CharField(
        max_length=50, required=False, allow_blank=True, allow_null=True
    )
    avatar_url = serializers.CharField(
        max_length=400, required=False, allow_blank=True, allow_null=True
    )
    is_default_tenant = serializers.BooleanField(required=False, default=False)

    def validate_display_name(self, value):
        if not value.strip():
            raise serializers.ValidationError("Display name is required.")
        return value.strip()

    def validate_email(self, value):
        return value.strip().lower()


class AdminUserUpdateSerializer(serializers.Serializer):
    email = serializers.EmailField(max_length=320, required=False)
    display_name = serializers.CharField(
        max_length=200, trim_whitespace=True, required=False
    )
    employee_code = serializers.CharField(
        max_length=50, required=False, allow_blank=True, allow_null=True
    )
    avatar_url = serializers.CharField(
        max_length=400, required=False, allow_blank=True, allow_null=True
    )
    is_active = serializers.BooleanField(required=False)

    def validate_display_name(self, value):
        if not value.strip():
            raise serializers.ValidationError("Display name is required.")
        return value.strip()

    def validate_email(self, value):
        return value.strip().lower()


class AdminPermissionCatalogueSerializer(serializers.ModelSerializer):
    class Meta:
        model = Permission
        fields = ["code", "description"]


class AdminRoleSummarySerializer(serializers.ModelSerializer):
    role_id = serializers.UUIDField(source="roleid", read_only=True)

    class Meta:
        model = Role
        fields = ["role_id", "name"]


class AdminMembershipSerializer(serializers.ModelSerializer):
    membership_id = serializers.UUIDField(source="membershipid", read_only=True)
    tenant_id = serializers.UUIDField(source="tenantid_id", read_only=True)
    user = AdminDirectoryUserSerializer(source="userid", read_only=True)
    is_default_tenant = serializers.BooleanField(
        source="isdefaulttenant", read_only=True
    )
    roles = serializers.SerializerMethodField()
    created_at = serializers.DateTimeField(source="createdat", read_only=True)

    class Meta:
        model = Membership
        fields = [
            "membership_id",
            "tenant_id",
            "user",
            "is_default_tenant",
            "roles",
            "created_at",
        ]

    @extend_schema_field(AdminRoleSummarySerializer(many=True))
    def get_roles(self, instance):
        from apps.rt.services.admin_directory import membership_roles

        links = getattr(instance, "_admin_role_links", None)
        roles = [link.roleid for link in links] if links is not None else None
        return AdminRoleSummarySerializer(
            roles if roles is not None else membership_roles(instance.membershipid),
            many=True,
        ).data


class AdminMembershipCreateSerializer(serializers.Serializer):
    user_id = serializers.UUIDField()
    is_default_tenant = serializers.BooleanField(required=False, default=False)


class AdminMembershipUpdateSerializer(serializers.Serializer):
    is_default_tenant = serializers.BooleanField()


class AdminRoleSerializer(serializers.ModelSerializer):
    role_id = serializers.UUIDField(source="roleid", read_only=True)
    tenant_id = serializers.UUIDField(source="tenantid_id", read_only=True)
    permissions = serializers.SerializerMethodField()
    created_at = serializers.DateTimeField(source="createdat", read_only=True)

    class Meta:
        model = Role
        fields = [
            "role_id",
            "tenant_id",
            "name",
            "description",
            "permissions",
            "created_at",
        ]

    @extend_schema_field(AdminPermissionCatalogueSerializer(many=True))
    def get_permissions(self, instance):
        from apps.rt.services.admin_directory import role_permissions

        links = getattr(instance, "_admin_permission_links", None)
        permissions = (
            [link.permissioncode for link in links] if links is not None else None
        )
        return AdminPermissionCatalogueSerializer(
            (
                permissions
                if permissions is not None
                else role_permissions(instance.roleid)
            ),
            many=True,
        ).data


class AdminRoleWriteSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=100, trim_whitespace=True)
    description = serializers.CharField(
        max_length=400, required=False, allow_blank=True, allow_null=True
    )

    def validate_name(self, value):
        if not value.strip():
            raise serializers.ValidationError("Name is required.")
        return value.strip()


class AdminRoleAssignmentSerializer(serializers.Serializer):
    role_id = serializers.UUIDField()


class AdminPermissionAssignmentSerializer(serializers.Serializer):
    permission_code = serializers.CharField(max_length=100, trim_whitespace=True)


class AdminUserCreateResponseSerializer(serializers.Serializer):
    user = AdminDirectoryUserSerializer()
    membership = AdminMembershipSerializer()


class AdminSlaPolicySerializer(serializers.ModelSerializer):
    sla_policy_id = serializers.UUIDField(source="policyid", read_only=True)
    response_minutes = serializers.IntegerField(
        source="responseminutes", read_only=True
    )
    resolution_minutes = serializers.IntegerField(
        source="resolutionminutes", read_only=True
    )
    is_active = serializers.BooleanField(source="isactive", read_only=True)
    created_at = serializers.DateTimeField(source="createdat", read_only=True)
    updated_at = serializers.DateTimeField(
        source="updatedat", read_only=True, allow_null=True
    )

    class Meta:
        model = Slapolicy
        fields = [
            "sla_policy_id",
            "name",
            "priority",
            "response_minutes",
            "resolution_minutes",
            "is_active",
            "created_at",
            "updated_at",
        ]


class AdminSlaPolicyWriteSerializer(serializers.Serializer):
    VALID_PRIORITIES = {"low", "normal", "high", "urgent"}

    name = serializers.CharField(max_length=100, trim_whitespace=True)
    priority = serializers.CharField(max_length=20, trim_whitespace=True)
    response_minutes = serializers.IntegerField(min_value=1)
    resolution_minutes = serializers.IntegerField(min_value=1)
    is_active = serializers.BooleanField(required=False, default=True)

    def validate_name(self, value):
        if not value.strip():
            raise serializers.ValidationError("Name is required.")
        return value.strip()

    def validate_priority(self, value):
        normalized = value.strip().lower()
        if normalized not in self.VALID_PRIORITIES:
            allowed = ", ".join(sorted(self.VALID_PRIORITIES))
            raise serializers.ValidationError(f"Priority must be one of: {allowed}.")
        return normalized

    def validate(self, attrs):
        instance = self.instance
        response_minutes = attrs.get(
            "response_minutes", getattr(instance, "responseminutes", None)
        )
        resolution_minutes = attrs.get(
            "resolution_minutes", getattr(instance, "resolutionminutes", None)
        )
        if (
            response_minutes is not None
            and resolution_minutes is not None
            and response_minutes > resolution_minutes
        ):
            raise serializers.ValidationError(
                {
                    "response_minutes": [
                        "Response minutes cannot exceed resolution minutes."
                    ]
                }
            )
        return attrs


class StrictFieldsMixin:
    def to_internal_value(self, data):
        if isinstance(data, dict):
            unknown = sorted(set(data) - set(self.fields))
            if unknown:
                raise serializers.ValidationError(
                    {field: ["Unknown field."] for field in unknown}
                )
        return super().to_internal_value(data)


class TenantSettingSerializer(serializers.ModelSerializer):
    setting_id = serializers.UUIDField(source="tenantsettingid", read_only=True)
    value = serializers.SerializerMethodField()
    value_type = serializers.CharField(source="valuetype", read_only=True)
    is_sensitive = serializers.BooleanField(source="issensitive", read_only=True)
    has_value = serializers.SerializerMethodField()
    updated_at = serializers.DateTimeField(source="updatedat", read_only=True)
    updated_by_id = serializers.UUIDField(
        source="updatedbyid_id", read_only=True, allow_null=True
    )

    class Meta:
        model = Tenantsetting
        fields = [
            "setting_id",
            "key",
            "value",
            "value_type",
            "is_sensitive",
            "has_value",
            "updated_at",
            "updated_by_id",
        ]

    @extend_schema_field(OpenApiTypes.STR)
    def get_value(self, obj):
        return None if obj.issensitive else obj.value

    @extend_schema_field(OpenApiTypes.BOOL)
    def get_has_value(self, obj):
        return obj.value not in (None, "")


class TenantSettingsResponseSerializer(serializers.Serializer):
    settings = TenantSettingSerializer(many=True)


class TenantSettingUpdateItemSerializer(StrictFieldsMixin, serializers.Serializer):
    key = serializers.CharField(max_length=100, trim_whitespace=True)
    value = serializers.JSONField(allow_null=True)
    value_type = serializers.ChoiceField(choices=sorted(SUPPORTED_VALUE_TYPES))

    def validate(self, attrs):
        try:
            attrs["value"] = normalize_setting_value(
                attrs["key"], attrs["value_type"], attrs["value"]
            )
        except ValueError as exc:
            raise serializers.ValidationError({"value": [str(exc)]}) from exc
        return attrs


class TenantSettingsUpdateSerializer(StrictFieldsMixin, serializers.Serializer):
    settings = TenantSettingUpdateItemSerializer(many=True, allow_empty=False)

    def validate_settings(self, value):
        keys = [item["key"] for item in value]
        duplicates = sorted({key for key in keys if keys.count(key) > 1})
        if duplicates:
            raise serializers.ValidationError(
                [f"Duplicate setting key: {key}." for key in duplicates]
            )
        return value


class FeatureFlagSerializer(serializers.ModelSerializer):
    feature_flag_id = serializers.UUIDField(source="featureflagid", read_only=True)
    updated_at = serializers.DateTimeField(source="updatedat", read_only=True)
    updated_by_id = serializers.UUIDField(
        source="updatedbyid_id", read_only=True, allow_null=True
    )

    class Meta:
        model = Featureflag
        fields = [
            "feature_flag_id",
            "key",
            "enabled",
            "description",
            "updated_at",
            "updated_by_id",
        ]


class FeatureFlagUpdateSerializer(StrictFieldsMixin, serializers.Serializer):
    enabled = serializers.BooleanField(required=False)
    description = serializers.CharField(
        required=False, allow_blank=True, allow_null=True, max_length=500
    )

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError("At least one field is required.")
        return attrs


class NotificationTemplateSerializer(serializers.ModelSerializer):
    notification_template_id = serializers.UUIDField(
        source="notificationtemplateid", read_only=True
    )
    event_type = serializers.CharField(source="eventtype", read_only=True)
    subject_template = serializers.CharField(source="subjecttemplate", read_only=True)
    body_template = serializers.CharField(source="bodytemplate", read_only=True)
    is_active = serializers.BooleanField(source="isactive", read_only=True)
    updated_at = serializers.DateTimeField(source="updatedat", read_only=True)
    updated_by_id = serializers.UUIDField(
        source="updatedbyid_id", read_only=True, allow_null=True
    )

    class Meta:
        model = Notificationtemplate
        fields = [
            "notification_template_id",
            "event_type",
            "subject_template",
            "body_template",
            "is_active",
            "updated_at",
            "updated_by_id",
        ]


class NotificationTemplateUpdateSerializer(StrictFieldsMixin, serializers.Serializer):
    subject_template = serializers.CharField(
        required=False, max_length=500, trim_whitespace=False
    )
    body_template = serializers.CharField(
        required=False, trim_whitespace=False, max_length=20000
    )
    is_active = serializers.BooleanField(required=False)

    def validate_subject_template(self, value):
        if not value.strip():
            raise serializers.ValidationError("Subject template cannot be blank.")
        if "\r" in value or "\n" in value:
            raise serializers.ValidationError("Subject template must be one line.")
        try:
            return validate_template_text(value)
        except ValueError as exc:
            raise serializers.ValidationError(str(exc)) from exc

    def validate_body_template(self, value):
        if not value.strip():
            raise serializers.ValidationError("Body template cannot be blank.")
        try:
            return validate_template_text(value)
        except ValueError as exc:
            raise serializers.ValidationError(str(exc)) from exc

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError("At least one field is required.")
        return attrs


class ReportFilterSerializer(serializers.Serializer):
    VALID_PRIORITIES = AdminSlaPolicyWriteSerializer.VALID_PRIORITIES
    VALID_STATUS_CATEGORIES = {"open", "in_progress", "waiting", "closed"}

    q = serializers.CharField(
        required=False, allow_blank=True, max_length=200, trim_whitespace=True
    )
    status_id = serializers.UUIDField(required=False)
    status_category = serializers.CharField(
        required=False, max_length=20, trim_whitespace=True
    )
    priority = serializers.CharField(
        required=False, max_length=20, trim_whitespace=True
    )
    flow_id = serializers.UUIDField(required=False)
    requester_id = serializers.UUIDField(required=False)
    assignee_id = serializers.UUIDField(required=False)
    created_from = serializers.DateTimeField(required=False)
    created_to = serializers.DateTimeField(required=False)
    updated_from = serializers.DateTimeField(required=False)
    updated_to = serializers.DateTimeField(required=False)
    due_from = serializers.DateTimeField(required=False)
    due_to = serializers.DateTimeField(required=False)

    def validate_priority(self, value):
        normalized = value.strip().lower()
        if normalized not in self.VALID_PRIORITIES:
            raise serializers.ValidationError("Unsupported priority.")
        return normalized

    def validate_status_category(self, value):
        normalized = value.strip().lower()
        if normalized not in self.VALID_STATUS_CATEGORIES:
            raise serializers.ValidationError("Unsupported status category.")
        return normalized

    def validate(self, attrs):
        for prefix in ("created", "updated", "due"):
            lower = attrs.get(f"{prefix}_from")
            upper = attrs.get(f"{prefix}_to")
            if lower and upper and upper < lower:
                raise serializers.ValidationError(
                    {f"{prefix}_to": ["Must be on or after the lower bound."]}
                )
        return attrs


class ReportExportFilterSerializer(ReportFilterSerializer):
    format = serializers.ChoiceField(choices=["csv"])


class ReportDimensionSerializer(serializers.Serializer):
    count = serializers.IntegerField()


class ReportPriorityDimensionSerializer(ReportDimensionSerializer):
    priority = serializers.CharField()


class ReportStatusDimensionSerializer(ReportDimensionSerializer):
    status_id = serializers.UUIDField()
    name = serializers.CharField()
    category = serializers.CharField()


class ReportSummarySerializer(serializers.Serializer):
    total = serializers.IntegerField()
    open = serializers.IntegerField()
    in_progress = serializers.IntegerField()
    waiting = serializers.IntegerField()
    closed = serializers.IntegerField()
    due_today = serializers.IntegerField()
    overdue = serializers.IntegerField()
    unassigned = serializers.IntegerField()
    assigned_to_me = serializers.IntegerField()
    by_priority = ReportPriorityDimensionSerializer(many=True)
    by_status = ReportStatusDimensionSerializer(many=True)


class AdminFlowSerializer(serializers.ModelSerializer):
    flow_id = serializers.UUIDField(source="flowid", read_only=True)
    created_at = serializers.DateTimeField(source="createdat", read_only=True)

    class Meta:
        model = Flow
        fields = ["flow_id", "name", "description", "created_at"]


class AdminFlowWriteSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=100, trim_whitespace=True)
    description = serializers.CharField(
        max_length=400, required=False, allow_blank=True, allow_null=True
    )

    def validate_name(self, value):
        if not value.strip():
            raise serializers.ValidationError("Name is required.")
        return value.strip()


class AdminStatusSerializer(serializers.ModelSerializer):
    status_id = serializers.UUIDField(source="statusid", read_only=True)
    flow_id = serializers.UUIDField(source="flowid_id", read_only=True)
    is_terminal = serializers.BooleanField(source="isterminal", read_only=True)
    created_at = serializers.DateTimeField(source="createdat", read_only=True)

    class Meta:
        model = Status
        fields = [
            "status_id",
            "flow_id",
            "name",
            "category",
            "is_terminal",
            "created_at",
        ]


class AdminStatusWriteSerializer(serializers.Serializer):
    VALID_CATEGORIES = {"open", "in_progress", "waiting", "closed"}
    name = serializers.CharField(max_length=50, trim_whitespace=True)
    category = serializers.CharField(max_length=20, trim_whitespace=True)
    is_terminal = serializers.BooleanField(required=False, default=False)

    def validate_name(self, value):
        if not value.strip():
            raise serializers.ValidationError("Name is required.")
        return value.strip()

    def validate_category(self, value):
        normalized = value.strip().lower()
        if not normalized:
            raise serializers.ValidationError("Category is required.")
        if normalized not in self.VALID_CATEGORIES:
            raise serializers.ValidationError("Unsupported status category.")
        return normalized


class AdminTransitionSerializer(serializers.ModelSerializer):
    transition_id = serializers.UUIDField(source="transitionid", read_only=True)
    flow_id = serializers.UUIDField(source="flowid_id", read_only=True)
    from_status_id = serializers.UUIDField(source="fromstatusid_id", read_only=True)
    to_status_id = serializers.UUIDField(source="tostatusid_id", read_only=True)
    guard_roles_json = serializers.CharField(
        source="guardrolesjson", read_only=True, allow_null=True
    )
    guard_perms_json = serializers.CharField(
        source="guardpermsjson", read_only=True, allow_null=True
    )
    auto_rules = serializers.CharField(
        source="autorules", read_only=True, allow_null=True
    )
    created_at = serializers.DateTimeField(source="createdat", read_only=True)

    class Meta:
        model = Transition
        fields = [
            "transition_id",
            "flow_id",
            "from_status_id",
            "to_status_id",
            "guard_roles_json",
            "guard_perms_json",
            "auto_rules",
            "created_at",
        ]


class AdminTransitionWriteSerializer(serializers.Serializer):
    from_status_id = serializers.UUIDField()
    to_status_id = serializers.UUIDField()
    guard_roles_json = serializers.CharField(
        required=False, allow_blank=True, allow_null=True
    )
    guard_perms_json = serializers.CharField(
        required=False, allow_blank=True, allow_null=True
    )
    auto_rules = serializers.CharField(
        required=False, allow_blank=True, allow_null=True
    )


class DashboardSummarySerializer(serializers.Serializer):
    open = serializers.IntegerField()
    in_progress = serializers.IntegerField()
    waiting = serializers.IntegerField()
    closed = serializers.IntegerField()
    due_today = serializers.IntegerField()
    overdue = serializers.IntegerField()
    assigned_to_me = serializers.IntegerField()
    unassigned = serializers.IntegerField()


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


class SearchResultSerializer(serializers.Serializer):
    request_id = serializers.UUIDField()
    human_id = serializers.CharField()
    title = serializers.CharField()
    priority = serializers.CharField()
    status_id = serializers.UUIDField()
    assignee_id = serializers.UUIDField(allow_null=True)
    flow_id = serializers.UUIDField()
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()
    rank = serializers.IntegerField()
    match_sources = serializers.ListField(child=serializers.CharField())


class SearchResponseSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    page = serializers.IntegerField()
    page_size = serializers.IntegerField()
    results = SearchResultSerializer(many=True)


class AttachmentFinalizeItemResponseSerializer(serializers.Serializer):
    attachment_id = serializers.UUIDField()
    filename = serializers.CharField()
    storage_url = serializers.URLField()


class AttachmentFinalizeResponseSerializer(serializers.Serializer):
    request_id = serializers.UUIDField()
    group_id = serializers.UUIDField()
    comment_id = serializers.UUIDField()
    attachments = AttachmentFinalizeItemResponseSerializer(many=True)
