from django.contrib import admin
from django.urls import path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
    TokenVerifyView,
)

from apps.common import views as common_views

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
    path("api/schema", SpectacularAPIView.as_view(), name="schema"),
    path(
        "api/docs", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"
    ),
]
