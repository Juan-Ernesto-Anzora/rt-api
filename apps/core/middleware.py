# apps/core/middleware.py
from django.http import JsonResponse
from django.utils.deprecation import MiddlewareMixin
from django.db import connection

PUBLIC_PATH_PREFIXES = (
    "/api/health",
    "/api/schema",
    "/api/docs",
    "/api/auth/jwt",   # create/refresh/verify
    "/admin",          # opcional si usas el admin
    "/static", "/media",  # si sirves estáticos
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
            return JsonResponse({"detail": f"{TENANT_HEADER} header required."}, status=400)

        # Resolver TenantId
        with connection.cursor() as cur:
            cur.execute("SELECT TenantId FROM dbo.Tenant WHERE Code = %s", [tenant_code])
            row = cur.fetchone()
        if not row:
            return JsonResponse({"detail": "Tenant not found."}, status=404)

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
                    return JsonResponse({"detail": "Forbidden: user not in tenant."}, status=403)

        return None
