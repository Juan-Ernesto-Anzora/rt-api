# apps/core/middleware.py
from django.db import connection
from django.http import JsonResponse
from django.utils.deprecation import MiddlewareMixin

from rt_api.exceptions import error_envelope

PUBLIC_PATH_PREFIXES = (
    "/api/health",
    "/api/schema",
    "/api/docs",
    "/api/auth/jwt",  # create/refresh/verify
    "/admin",  # opcional si usas el admin
    "/static",
    "/media",  # si sirves estáticos
)

TENANT_HEADER = "X-Tenant"


class TenantMiddleware(MiddlewareMixin):
    def process_request(self, request):
        # Solo aplica a /api; si no, salir
        if not request.path.startswith("/api"):
            return None

        # Whitelist de rutas públicas (no requieren X-Tenant)
        for prefix in PUBLIC_PATH_PREFIXES:
            if request.path.startswith(prefix):
                return None

        # Requerir header X-Tenant en el resto
        tenant_code = request.headers.get(TENANT_HEADER)
        if not tenant_code:
            return JsonResponse(
                error_envelope("tenant_required", f"{TENANT_HEADER} header required."),
                status=400,
            )

        # Resolver TenantId
        with connection.cursor() as cur:
            cur.execute(
                "SELECT TenantId FROM dbo.Tenant WHERE Code = %s", [tenant_code]
            )
            row = cur.fetchone()
        if not row:
            return JsonResponse(
                error_envelope("tenant_not_found", "Tenant not found."), status=404
            )

        tenant_id = row[0]
        request.tenant_id = tenant_id

        # Si hay usuario autenticado, validar membresía
        user = getattr(request, "user", None)
        if user and user.is_authenticated:
            with connection.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM dbo.Membership WHERE UserId=%s AND TenantId=%s",
                    [str(user.id), str(tenant_id)],
                )
                if cur.fetchone() is None:
                    return JsonResponse(
                        error_envelope(
                            "permission_denied", "User is not a member of this tenant."
                        ),
                        status=403,
                    )

        return None


class ApiErrorEnvelopeMiddleware(MiddlewareMixin):
    def process_response(self, request, response):
        if (
            not request.path.startswith("/api/")
            or response.status_code < 400
            or getattr(response, "streaming", False)
        ):
            return response
        response_data = getattr(response, "data", None)
        if isinstance(response_data, dict) and {
            "code",
            "message",
            "details",
        }.issubset(response_data):
            return response
        content_type = response.get("Content-Type", "")
        if content_type.startswith("application/json"):
            try:
                import json

                data = json.loads(response.content.decode(response.charset))
                if isinstance(data, dict) and {
                    "code",
                    "message",
                    "details",
                }.issubset(data):
                    return response
            except (ValueError, UnicodeDecodeError):
                pass
        code = {
            400: "validation_error",
            401: "authentication_required",
            403: "permission_denied",
            404: "not_found",
            409: "conflict",
        }.get(response.status_code, "server_error")
        try:
            from http import HTTPStatus

            message = HTTPStatus(response.status_code).phrase
        except ValueError:
            message = "Request failed."
        replacement = JsonResponse(
            error_envelope(code, message), status=response.status_code
        )
        for header, value in response.items():
            if header.lower() not in {"content-type", "content-length"}:
                replacement[header] = value
        return replacement
