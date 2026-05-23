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
    AttachmentFinalizeView,
    AttachmentInitView,
    AttachmentViewSet,
    CommentViewSet,
    RequestViewSet,
    SearchView,
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
    path("api/schema", SpectacularAPIView.as_view(), name="schema"),
    path(
        "api/docs", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"
    ),
]

router = SimpleRouter()
router.register(r"api/requests", RequestViewSet, basename="requests")

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
