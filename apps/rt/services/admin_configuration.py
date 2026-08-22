import re
import string
from urllib.parse import urlsplit, urlunsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.utils import timezone

from apps.rt.models import Featureflag, Notificationtemplate, Tenantsetting
from apps.rt.services.admin_audit import write_admin_audit
from apps.rt.services.admin_directory import AdminDirectoryError

SUPPORTED_VALUE_TYPES = {
    "string",
    "integer",
    "boolean",
    "url",
    "timezone",
    "email",
}
SUPPORTED_TEMPLATE_PLACEHOLDERS = {
    "human_id",
    "title",
    "request_id",
    "request_url",
    "requester_name",
    "assignee_name",
    "comment_author",
    "status_name",
}
INTEGER_PATTERN = re.compile(r"^[+-]?\d+$")
CONTROL_PATTERN = re.compile(r"[\x00-\x1f\x7f]")
FORMATTER = string.Formatter()


def normalize_setting_value(key, value_type, value):
    if value_type not in SUPPORTED_VALUE_TYPES:
        raise ValueError("Unsupported value type.")
    if value is None:
        return None

    if value_type == "boolean":
        if isinstance(value, bool):
            return "true" if value else "false"
        normalized = str(value).strip().lower()
        if normalized not in {"true", "false"}:
            raise ValueError("Boolean values must be true or false.")
        return normalized

    text = str(value).strip()
    if "\x00" in text:
        raise ValueError("Values cannot contain null characters.")

    if value_type == "integer":
        if not INTEGER_PATTERN.fullmatch(text):
            raise ValueError("Integer values must use base-10 digits.")
        number = int(text)
        if key == "default_page_size" and not 1 <= number <= 100:
            raise ValueError("Default page size must be between 1 and 100.")
        return str(number)

    if value_type == "url":
        if CONTROL_PATTERN.search(text):
            raise ValueError("URLs cannot contain control characters.")
        try:
            parsed = urlsplit(text)
            _ = parsed.port
        except ValueError as exc:
            raise ValueError("Enter a valid URL.") from exc
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.fragment
        ):
            raise ValueError("Enter an absolute HTTP or HTTPS URL without credentials.")
        path = parsed.path.rstrip("/") if key == "web_base_url" else parsed.path
        return urlunsplit((parsed.scheme, parsed.netloc, path, parsed.query, ""))

    if value_type == "timezone":
        try:
            ZoneInfo(text)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("Enter a valid IANA timezone.") from exc
        return text

    if value_type == "email":
        try:
            validate_email(text)
        except DjangoValidationError as exc:
            raise ValueError("Enter a valid email address.") from exc
        return text

    if len(text) > 4000:
        raise ValueError("String values cannot exceed 4000 characters.")
    return text


def validate_template_text(template):
    try:
        parsed = list(FORMATTER.parse(template))
    except ValueError as exc:
        raise ValueError("Template braces are malformed.") from exc

    for _literal, field_name, format_spec, conversion in parsed:
        if field_name is None:
            continue
        if field_name not in SUPPORTED_TEMPLATE_PLACEHOLDERS:
            raise ValueError(f"Unsupported placeholder: {{{field_name}}}.")
        if format_spec or conversion:
            raise ValueError(
                "Template conversions and format specifiers are not allowed."
            )
    return template


def render_safe_template(template, context):
    validate_template_text(template)
    return FORMATTER.vformat(template, (), context)


def update_tenant_settings(tenant_id, actor_id, items):
    keys = [item["key"] for item in items]
    with transaction.atomic():
        settings_by_key = {
            item.key: item
            for item in Tenantsetting.objects.select_for_update().filter(
                tenantid_id=tenant_id, key__in=keys
            )
        }
        missing = [key for key in keys if key not in settings_by_key]
        if missing:
            raise AdminDirectoryError(
                "validation_error",
                "One or more tenant settings are unknown.",
                400,
                [{"field": "key", "message": key} for key in missing],
            )

        changed = []
        now = timezone.now()
        for item in items:
            setting = settings_by_key[item["key"]]
            if setting.valuetype != item["value_type"]:
                raise AdminDirectoryError(
                    "validation_error",
                    "Setting value type does not match its configured type.",
                    400,
                    [{"field": "value_type", "message": setting.key}],
                )
            try:
                normalized = normalize_setting_value(
                    setting.key, setting.valuetype, item["value"]
                )
            except ValueError as exc:
                raise AdminDirectoryError(
                    "validation_error",
                    "Setting value is invalid.",
                    400,
                    [{"field": setting.key, "message": str(exc)}],
                ) from exc
            if setting.value == normalized:
                continue
            setting.value = normalized
            setting.updatedat = now
            setting.updatedbyid_id = actor_id
            setting.save(update_fields=["value", "updatedat", "updatedbyid"])
            changed.append(setting)

        if changed:
            write_admin_audit(
                tenant_id,
                actor_id,
                "admin.tenant_settings.updated",
                {
                    "settings": [
                        {"key": setting.key, "value_type": setting.valuetype}
                        for setting in changed
                    ]
                },
            )
        return list(Tenantsetting.objects.filter(tenantid_id=tenant_id).order_by("key"))


def tenant_feature_flag(tenant_id, key, lock=False):
    queryset = Featureflag.objects
    if lock:
        queryset = queryset.select_for_update()
    try:
        flag = queryset.get(tenantid_id=tenant_id, key=key)
    except Featureflag.DoesNotExist as exc:
        raise AdminDirectoryError(
            "not_found", "Feature flag not found for this tenant.", 404
        ) from exc
    if flag.key != key:
        raise AdminDirectoryError(
            "not_found", "Feature flag not found for this tenant.", 404
        )
    return flag


def update_feature_flag(tenant_id, actor_id, key, data):
    with transaction.atomic():
        flag = tenant_feature_flag(tenant_id, key, lock=True)
        changed_fields = []
        old_enabled = flag.enabled
        for public_field, model_field in (
            ("enabled", "enabled"),
            ("description", "description"),
        ):
            if (
                public_field in data
                and getattr(flag, model_field) != data[public_field]
            ):
                setattr(flag, model_field, data[public_field])
                changed_fields.append(model_field)
        if not changed_fields:
            return flag, False

        flag.updatedat = timezone.now()
        flag.updatedbyid_id = actor_id
        flag.save(update_fields=[*changed_fields, "updatedat", "updatedbyid"])
        write_admin_audit(
            tenant_id,
            actor_id,
            "admin.feature_flag.updated",
            {
                "key": flag.key,
                "changed_fields": changed_fields,
                "old_enabled": old_enabled,
                "enabled": flag.enabled,
            },
        )
        return flag, True


def tenant_notification_template(tenant_id, template_id, lock=False):
    queryset = Notificationtemplate.objects
    if lock:
        queryset = queryset.select_for_update()
    try:
        return queryset.get(tenantid_id=tenant_id, notificationtemplateid=template_id)
    except Notificationtemplate.DoesNotExist as exc:
        raise AdminDirectoryError(
            "not_found", "Notification template not found for this tenant.", 404
        ) from exc


def update_notification_template(tenant_id, actor_id, template_id, data):
    with transaction.atomic():
        template = tenant_notification_template(tenant_id, template_id, lock=True)
        changed_fields = []
        was_active = template.isactive
        for public_field, model_field in (
            ("subject_template", "subjecttemplate"),
            ("body_template", "bodytemplate"),
            ("is_active", "isactive"),
        ):
            if (
                public_field in data
                and getattr(template, model_field) != data[public_field]
            ):
                setattr(template, model_field, data[public_field])
                changed_fields.append(model_field)
        if not changed_fields:
            return template, False

        template.updatedat = timezone.now()
        template.updatedbyid_id = actor_id
        template.save(update_fields=[*changed_fields, "updatedat", "updatedbyid"])
        write_admin_audit(
            tenant_id,
            actor_id,
            "admin.notification_template.updated",
            {
                "notification_template_id": template.notificationtemplateid,
                "event_type": template.eventtype,
                "changed_fields": changed_fields,
                "was_active": was_active,
                "is_active": template.isactive,
            },
        )
        return template, True
