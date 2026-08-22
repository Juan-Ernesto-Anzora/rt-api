from django.contrib import admin
from django.urls import path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework.routers import SimpleRouter
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
    TokenVerifyView,
)

from apps.common import views as common_views
from apps.rt.views import (
    AdminAuditView,
    AdminFeatureFlagDetailView,
    AdminFeatureFlagListView,
    AdminMembershipDetailView,
    AdminMembershipListCreateView,
    AdminMembershipRoleAssignView,
    AdminMembershipRoleDetailView,
    AdminNotificationTemplateDetailView,
    AdminNotificationTemplateListView,
    AdminPermissionListView,
    AdminPermissionsView,
    AdminRoleDetailView,
    AdminRoleListCreateView,
    AdminRolePermissionAssignView,
    AdminRolePermissionDetailView,
    AdminSlaPolicyDetailView,
    AdminSlaPolicyListCreateView,
    AdminTenantSettingsView,
    AdminUserDetailView,
    AdminUserListCreateView,
    AdminWorkflowDetailView,
    AdminWorkflowListCreateView,
    AdminWorkflowStatusCreateView,
    AdminWorkflowStatusDetailView,
    AdminWorkflowTransitionCreateView,
    AdminWorkflowTransitionDetailView,
    AttachmentFinalizeView,
    AttachmentInitView,
    AttachmentViewSet,
    CommentViewSet,
    DashboardSummaryView,
    FlowViewSet,
    ReportRequestExportView,
    ReportSummaryView,
    RequestViewSet,
    SearchView,
    UserLookupViewSet,
)

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/health", common_views.HealthView.as_view(), name="health"),
    path("api/auth/jwt/create", TokenObtainPairView.as_view(), name="jwt-create"),
    path("api/auth/jwt/refresh", TokenRefreshView.as_view(), name="jwt-refresh"),
    path("api/auth/jwt/verify", TokenVerifyView.as_view(), name="jwt-verify"),
    path(
        "api/storage/presign",
        common_views.PresignUploadView.as_view(),
        name="storage-presign",
    ),
    path(
        "api/attachments/init",
        AttachmentInitView.as_view(),
        name="attachments-init",
    ),
    path(
        "api/attachments/finalize",
        AttachmentFinalizeView.as_view(),
        name="attachments-finalize",
    ),
    path("api/search", SearchView.as_view(), name="search"),
    path("api/search/requests", SearchView.as_view(), name="search-requests"),
    path(
        "api/dashboard/summary",
        DashboardSummaryView.as_view(),
        name="dashboard-summary",
    ),
    path(
        "api/dashboard/summary/",
        DashboardSummaryView.as_view(),
        name="dashboard-summary-slash",
    ),
    path(
        "api/admin/me/permissions/",
        AdminPermissionsView.as_view(),
        name="admin-me-permissions",
    ),
    path(
        "api/admin/audit/",
        AdminAuditView.as_view(),
        name="admin-audit",
    ),
    path(
        "api/admin/users/",
        AdminUserListCreateView.as_view(),
        name="admin-users",
    ),
    path(
        "api/admin/users/<uuid:user_id>/",
        AdminUserDetailView.as_view(),
        name="admin-user-detail",
    ),
    path(
        "api/admin/memberships/",
        AdminMembershipListCreateView.as_view(),
        name="admin-memberships",
    ),
    path(
        "api/admin/memberships/<uuid:membership_id>/",
        AdminMembershipDetailView.as_view(),
        name="admin-membership-detail",
    ),
    path(
        "api/admin/memberships/<uuid:membership_id>/roles/",
        AdminMembershipRoleAssignView.as_view(),
        name="admin-membership-roles",
    ),
    path(
        "api/admin/memberships/<uuid:membership_id>/roles/<uuid:role_id>/",
        AdminMembershipRoleDetailView.as_view(),
        name="admin-membership-role-detail",
    ),
    path(
        "api/admin/roles/",
        AdminRoleListCreateView.as_view(),
        name="admin-roles",
    ),
    path(
        "api/admin/roles/<uuid:role_id>/",
        AdminRoleDetailView.as_view(),
        name="admin-role-detail",
    ),
    path(
        "api/admin/permissions/",
        AdminPermissionListView.as_view(),
        name="admin-permissions",
    ),
    path(
        "api/admin/roles/<uuid:role_id>/permissions/",
        AdminRolePermissionAssignView.as_view(),
        name="admin-role-permissions",
    ),
    path(
        "api/admin/roles/<uuid:role_id>/permissions/<str:permission_code>/",
        AdminRolePermissionDetailView.as_view(),
        name="admin-role-permission-detail",
    ),
    path(
        "api/admin/sla-policies/",
        AdminSlaPolicyListCreateView.as_view(),
        name="admin-sla-policies",
    ),
    path(
        "api/admin/sla-policies/<uuid:sla_policy_id>/",
        AdminSlaPolicyDetailView.as_view(),
        name="admin-sla-policy-detail",
    ),
    path(
        "api/admin/settings/",
        AdminTenantSettingsView.as_view(),
        name="admin-settings",
    ),
    path(
        "api/admin/feature-flags/",
        AdminFeatureFlagListView.as_view(),
        name="admin-feature-flags",
    ),
    path(
        "api/admin/feature-flags/<str:key>/",
        AdminFeatureFlagDetailView.as_view(),
        name="admin-feature-flag-detail",
    ),
    path(
        "api/admin/notification-templates/",
        AdminNotificationTemplateListView.as_view(),
        name="admin-notification-templates",
    ),
    path(
        "api/admin/notification-templates/<uuid:template_id>/",
        AdminNotificationTemplateDetailView.as_view(),
        name="admin-notification-template-detail",
    ),
    path(
        "api/admin/workflows/",
        AdminWorkflowListCreateView.as_view(),
        name="admin-workflows",
    ),
    path(
        "api/admin/workflows/<uuid:flow_id>/",
        AdminWorkflowDetailView.as_view(),
        name="admin-workflow-detail",
    ),
    path(
        "api/admin/workflows/<uuid:flow_id>/statuses/",
        AdminWorkflowStatusCreateView.as_view(),
        name="admin-workflow-statuses",
    ),
    path(
        "api/admin/workflows/<uuid:flow_id>/statuses/<uuid:status_id>/",
        AdminWorkflowStatusDetailView.as_view(),
        name="admin-workflow-status-detail",
    ),
    path(
        "api/admin/workflows/<uuid:flow_id>/transitions/",
        AdminWorkflowTransitionCreateView.as_view(),
        name="admin-workflow-transitions",
    ),
    path(
        "api/admin/workflows/<uuid:flow_id>/transitions/<uuid:transition_id>/",
        AdminWorkflowTransitionDetailView.as_view(),
        name="admin-workflow-transition-detail",
    ),
    path(
        "api/reports/summary/",
        ReportSummaryView.as_view(),
        name="report-summary",
    ),
    path(
        "api/reports/requests/export/",
        ReportRequestExportView.as_view(),
        name="report-request-export",
    ),
    path("api/schema", SpectacularAPIView.as_view(), name="schema"),
    path(
        "api/docs", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"
    ),
]

router = SimpleRouter()
router.register(r"api/requests", RequestViewSet, basename="requests")
router.register(r"api/flows", FlowViewSet, basename="flows")
router.register(r"api/users", UserLookupViewSet, basename="users")

urlpatterns += router.urls

# nested: /api/requests/<id>/comments y /attachments
request_comments = CommentViewSet.as_view({"get": "list", "post": "create"})
request_attachments = AttachmentViewSet.as_view({"get": "list"})

urlpatterns += [
    path(
        "api/requests/<str:request_pk>/comments",
        request_comments,
        name="request-comments",
    ),
    path(
        "api/requests/<str:request_pk>/comments/",
        request_comments,
        name="request-comments-slash",
    ),
    path(
        "api/requests/<str:request_pk>/attachments",
        request_attachments,
        name="request-attachments",
    ),
    path(
        "api/requests/<str:request_pk>/attachments/",
        request_attachments,
        name="request-attachments-slash",
    ),
]
