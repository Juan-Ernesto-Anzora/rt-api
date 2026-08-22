import uuid
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest
from django.contrib.auth.models import AnonymousUser
from django.test import Client
from django.urls import resolve
from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.rt.models import Featureflag, Notificationtemplate, Tenantsetting
from apps.rt.serializers import (
    FeatureFlagSerializer,
    FeatureFlagUpdateSerializer,
    NotificationTemplateSerializer,
    NotificationTemplateUpdateSerializer,
    TenantSettingSerializer,
    TenantSettingsUpdateSerializer,
)
from apps.rt.services import admin_configuration
from apps.rt.services.admin_directory import AdminDirectoryError
from apps.rt.services.admin_permissions import (
    ADMIN_ACCESS_PERMISSION,
    ADMIN_SETTINGS_PERMISSION,
    FEATURE_FLAGS_MANAGE_PERMISSION,
    NOTIFICATIONS_MANAGE_PERMISSION,
    TENANT_SETTINGS_MANAGE_PERMISSION,
)
from apps.rt.views import (
    AdminFeatureFlagDetailView,
    AdminFeatureFlagListView,
    AdminNotificationTemplateDetailView,
    AdminNotificationTemplateListView,
    AdminTenantSettingsView,
)


def admin_context(*permissions):
    return SimpleNamespace(
        user=SimpleNamespace(user_id=str(uuid.uuid4())),
        permissions=list(permissions),
    )


def authenticated_request(method, path, tenant_id, data=None):
    request = getattr(APIRequestFactory(), method)(path, data or {}, format="json")
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


def make_setting(sensitive=False):
    return Tenantsetting(
        tenantsettingid=uuid.uuid4(),
        tenantid_id=uuid.uuid4(),
        key="smtp_password" if sensitive else "web_base_url",
        value="top-secret" if sensitive else "http://127.0.0.1:5173",
        valuetype="string" if sensitive else "url",
        issensitive=sensitive,
        updatedat=timezone.now(),
        updatedbyid_id=None,
    )


def make_flag(tenant_id=None):
    return Featureflag(
        featureflagid=uuid.uuid4(),
        tenantid_id=tenant_id or uuid.uuid4(),
        key="notificationTemplates",
        enabled=True,
        description="Enable templates",
        updatedat=timezone.now(),
        updatedbyid_id=None,
    )


def make_template(tenant_id=None):
    return Notificationtemplate(
        notificationtemplateid=uuid.uuid4(),
        tenantid_id=tenant_id or uuid.uuid4(),
        eventtype="request.created",
        subjecttemplate="Request created: {human_id}",
        bodytemplate="Open {request_url}",
        isactive=True,
        updatedat=timezone.now(),
        updatedbyid_id=None,
    )


def test_day8_routes_resolve():
    template_id = uuid.uuid4()
    assert resolve("/api/admin/settings/").url_name == "admin-settings"
    assert resolve("/api/admin/feature-flags/").url_name == "admin-feature-flags"
    assert (
        resolve("/api/admin/feature-flags/adminConsole/").url_name
        == "admin-feature-flag-detail"
    )
    assert (
        resolve("/api/admin/notification-templates/").url_name
        == "admin-notification-templates"
    )
    assert (
        resolve(f"/api/admin/notification-templates/{template_id}/").url_name
        == "admin-notification-template-detail"
    )


def test_day8_endpoint_without_jwt_returns_401():
    request = APIRequestFactory().get("/api/admin/settings/")
    request.user = AnonymousUser()

    response = AdminTenantSettingsView.as_view()(request)

    assert response.status_code == 401


def test_day8_endpoint_without_tenant_returns_clean_400():
    request = APIRequestFactory().get("/api/admin/settings/")
    force_authenticate(
        request,
        user=SimpleNamespace(
            is_authenticated=True,
            email="admin@example.com",
            username="admin@example.com",
        ),
    )

    response = AdminTenantSettingsView.as_view()(request)

    assert response.status_code == 400
    assert response.data["code"] == "tenant_required"


def test_configuration_models_are_unmanaged_and_tenant_unique():
    assert Tenantsetting._meta.managed is False
    assert Featureflag._meta.managed is False
    assert Notificationtemplate._meta.managed is False
    assert ("tenantid", "key") in Tenantsetting._meta.unique_together
    assert ("tenantid", "key") in Featureflag._meta.unique_together
    assert ("tenantid", "eventtype") in Notificationtemplate._meta.unique_together


def test_sensitive_setting_is_masked_but_reports_presence():
    data = TenantSettingSerializer(make_setting(sensitive=True)).data

    assert data["value"] is None
    assert data["has_value"] is True
    assert data["is_sensitive"] is True
    assert "top-secret" not in str(data)


@pytest.mark.parametrize(
    ("payload", "error_field"),
    [
        (
            {
                "settings": [
                    {
                        "key": "web_base_url",
                        "value": "javascript:alert(1)",
                        "value_type": "url",
                    }
                ]
            },
            "settings",
        ),
        (
            {
                "settings": [
                    {
                        "key": "default_timezone",
                        "value": "Mars/Olympus",
                        "value_type": "timezone",
                    }
                ]
            },
            "settings",
        ),
    ],
)
def test_setting_validation_rejects_invalid_typed_values(payload, error_field):
    serializer = TenantSettingsUpdateSerializer(data=payload)

    assert not serializer.is_valid()
    assert error_field in serializer.errors


def test_template_validation_rejects_unknown_or_executable_placeholders():
    unknown = NotificationTemplateUpdateSerializer(
        data={"body_template": "Hello {unknown}"}
    )
    executable = NotificationTemplateUpdateSerializer(
        data={"body_template": "Hello {requester_name.__class__}"}
    )

    assert not unknown.is_valid()
    assert not executable.is_valid()
    assert "body_template" in unknown.errors
    assert "body_template" in executable.errors


def test_feature_flag_key_and_template_event_type_cannot_be_renamed():
    flag = FeatureFlagUpdateSerializer(data={"key": "renamed", "enabled": True})
    template = NotificationTemplateUpdateSerializer(
        data={"event_type": "renamed", "is_active": True}
    )

    assert not flag.is_valid()
    assert flag.errors["key"][0] == "Unknown field."
    assert not template.is_valid()
    assert template.errors["event_type"][0] == "Unknown field."


@pytest.mark.parametrize(
    ("view", "path", "permission"),
    [
        (AdminTenantSettingsView, "/api/admin/settings/", ADMIN_SETTINGS_PERMISSION),
        (
            AdminFeatureFlagListView,
            "/api/admin/feature-flags/",
            FEATURE_FLAGS_MANAGE_PERMISSION,
        ),
        (
            AdminNotificationTemplateListView,
            "/api/admin/notification-templates/",
            NOTIFICATIONS_MANAGE_PERMISSION,
        ),
    ],
)
def test_configuration_endpoints_require_exact_permission(
    monkeypatch, view, path, permission
):
    monkeypatch.setattr(
        "apps.rt.views.get_admin_context",
        lambda request, required_permission: admin_context(ADMIN_ACCESS_PERMISSION),
    )

    response = view.as_view()(authenticated_request("get", path, uuid.uuid4()))

    assert response.status_code == 403
    assert response.data["code"] == "permission_denied"
    assert permission not in admin_context(ADMIN_ACCESS_PERMISSION).permissions


def test_settings_patch_requires_write_permission(monkeypatch):
    monkeypatch.setattr(
        "apps.rt.views.get_admin_context",
        lambda request, required_permission: admin_context(
            ADMIN_ACCESS_PERMISSION, ADMIN_SETTINGS_PERMISSION
        ),
    )

    response = AdminTenantSettingsView.as_view()(
        authenticated_request(
            "patch",
            "/api/admin/settings/",
            uuid.uuid4(),
            {
                "settings": [
                    {
                        "key": "web_base_url",
                        "value": "http://127.0.0.1:5173",
                        "value_type": "url",
                    }
                ]
            },
        )
    )

    assert response.status_code == 403


def test_settings_patch_uses_current_tenant_and_write_permission(monkeypatch):
    tenant_id = uuid.uuid4()
    context = admin_context(
        ADMIN_ACCESS_PERMISSION,
        ADMIN_SETTINGS_PERMISSION,
        TENANT_SETTINGS_MANAGE_PERMISSION,
    )
    captured = {}
    monkeypatch.setattr(
        "apps.rt.views.get_admin_context",
        lambda request, required_permission: context,
    )

    def fake_update(scoped_tenant, actor_id, items):
        captured.update(
            tenant_id=scoped_tenant,
            actor_id=actor_id,
            items=items,
        )
        setting = make_setting()
        setting.tenantid_id = tenant_id
        return [setting]

    monkeypatch.setattr("apps.rt.views.update_tenant_settings", fake_update)

    response = AdminTenantSettingsView.as_view()(
        authenticated_request(
            "patch",
            "/api/admin/settings/",
            tenant_id,
            {
                "settings": [
                    {
                        "key": "web_base_url",
                        "value": "https://rt.acme.test/",
                        "value_type": "url",
                    }
                ]
            },
        )
    )

    assert response.status_code == 200
    assert captured["tenant_id"] == tenant_id
    assert captured["items"][0]["value"] == "https://rt.acme.test"
    assert response.data["settings"][0]["key"] == "web_base_url"


def test_feature_flag_update_is_tenant_scoped_and_audited(monkeypatch):
    tenant_id = uuid.uuid4()
    actor_id = uuid.uuid4()
    flag = make_flag(tenant_id)
    saved = []
    audits = []
    monkeypatch.setattr(
        admin_configuration.transaction, "atomic", lambda: nullcontext()
    )
    monkeypatch.setattr(
        admin_configuration,
        "tenant_feature_flag",
        lambda scoped_tenant, key, lock: (
            flag if scoped_tenant == tenant_id and key == flag.key and lock else None
        ),
    )
    monkeypatch.setattr(flag, "save", lambda **kwargs: saved.append(kwargs))
    monkeypatch.setattr(
        admin_configuration, "write_admin_audit", lambda *args: audits.append(args)
    )

    updated, changed = admin_configuration.update_feature_flag(
        tenant_id, actor_id, flag.key, {"enabled": False}
    )

    assert updated.enabled is False
    assert changed is True
    assert len(saved) == 1
    assert audits[0][0:3] == (
        tenant_id,
        actor_id,
        "admin.feature_flag.updated",
    )


def test_tenant_settings_update_is_atomic_and_audited_without_secret_values(
    monkeypatch,
):
    tenant_id = uuid.uuid4()
    actor_id = uuid.uuid4()
    setting = make_setting(sensitive=True)
    setting.tenantid_id = tenant_id
    audits = []

    class FakeQuery:
        def __init__(self, items):
            self.items = items

        def filter(self, **kwargs):
            return self

        def order_by(self, *args):
            return self

        def __iter__(self):
            return iter(self.items)

    class FakeManager:
        def select_for_update(self):
            return FakeQuery([setting])

        def filter(self, **kwargs):
            return FakeQuery([setting])

    monkeypatch.setattr(
        admin_configuration.transaction, "atomic", lambda: nullcontext()
    )
    monkeypatch.setattr(admin_configuration.Tenantsetting, "objects", FakeManager())
    monkeypatch.setattr(setting, "save", lambda **kwargs: None)
    monkeypatch.setattr(
        admin_configuration, "write_admin_audit", lambda *args: audits.append(args)
    )

    result = admin_configuration.update_tenant_settings(
        tenant_id,
        actor_id,
        [{"key": "smtp_password", "value": "new-secret", "value_type": "string"}],
    )

    assert result == [setting]
    assert setting.value == "new-secret"
    assert audits[0][2] == "admin.tenant_settings.updated"
    assert "new-secret" not in str(audits[0][3])


def test_template_update_is_tenant_scoped_and_audited(monkeypatch):
    tenant_id = uuid.uuid4()
    actor_id = uuid.uuid4()
    template = make_template(tenant_id)
    audits = []
    monkeypatch.setattr(
        admin_configuration.transaction, "atomic", lambda: nullcontext()
    )
    monkeypatch.setattr(
        admin_configuration,
        "tenant_notification_template",
        lambda scoped_tenant, template_id, lock: (
            template
            if scoped_tenant == tenant_id
            and template_id == template.notificationtemplateid
            and lock
            else None
        ),
    )
    monkeypatch.setattr(template, "save", lambda **kwargs: None)
    monkeypatch.setattr(
        admin_configuration, "write_admin_audit", lambda *args: audits.append(args)
    )

    updated, changed = admin_configuration.update_notification_template(
        tenant_id,
        actor_id,
        template.notificationtemplateid,
        {"is_active": False},
    )

    assert updated.isactive is False
    assert changed is True
    assert audits[0][2] == "admin.notification_template.updated"


def test_cross_tenant_feature_and_template_ids_return_404(monkeypatch):
    tenant_id = uuid.uuid4()
    context = admin_context(
        ADMIN_ACCESS_PERMISSION,
        FEATURE_FLAGS_MANAGE_PERMISSION,
        NOTIFICATIONS_MANAGE_PERMISSION,
    )
    monkeypatch.setattr(
        "apps.rt.views.get_admin_context",
        lambda request, required_permission: context,
    )
    not_found = AdminDirectoryError("not_found", "Not found.", 404)
    monkeypatch.setattr(
        "apps.rt.views.update_feature_flag",
        lambda *args: (_ for _ in ()).throw(not_found),
    )
    monkeypatch.setattr(
        "apps.rt.views.tenant_notification_template",
        lambda *args: (_ for _ in ()).throw(not_found),
    )

    flag_response = AdminFeatureFlagDetailView.as_view()(
        authenticated_request(
            "patch",
            "/api/admin/feature-flags/foreign/",
            tenant_id,
            {"enabled": False},
        ),
        key="foreign",
    )
    template_response = AdminNotificationTemplateDetailView.as_view()(
        authenticated_request("get", "/api/admin/notification-templates/x/", tenant_id),
        template_id=uuid.uuid4(),
    )

    assert flag_response.status_code == 404
    assert template_response.status_code == 404


def test_configuration_serializers_use_clean_public_fields():
    flag_data = FeatureFlagSerializer(make_flag()).data
    template_data = NotificationTemplateSerializer(make_template()).data

    assert "feature_flag_id" in flag_data
    assert "featureflagid" not in flag_data
    assert "notification_template_id" in template_data
    assert "event_type" in template_data
    assert "eventtype" not in template_data


def test_schema_upgrade_is_additive_and_insert_only():
    upgrade = Path("db/upgrade-sprint3-admin-settings.sql").read_text(encoding="utf-8")
    create = Path("db/create-rt-database.sql").read_text(encoding="utf-8")

    for table in ("TenantSetting", "FeatureFlag", "NotificationTemplate"):
        assert f"CREATE TABLE dbo.{table}" in upgrade
        assert f"CREATE TABLE dbo.{table}" in create
    assert upgrade.count("WHEN NOT MATCHED THEN") == 3
    assert "WHEN MATCHED" not in upgrade
    assert "UPDATE SET" not in upgrade
    assert "admin.access" not in upgrade


def test_openapi_includes_day8_routes_and_clean_fields():
    response = Client().get("/api/schema")
    content = response.content.decode()

    assert response.status_code == 200
    assert "/api/admin/settings/" in content
    assert "/api/admin/feature-flags/{key}/" in content
    assert "/api/admin/notification-templates/{template_id}/" in content
    assert "subject_template" in content
    assert "is_sensitive" in content
    assert "notificationtemplateid" not in content
