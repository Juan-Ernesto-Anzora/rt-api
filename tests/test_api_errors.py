import json
from types import SimpleNamespace

from django.core.exceptions import FieldError
from django.db import IntegrityError
from django.http import HttpResponseNotFound
from rest_framework.permissions import AllowAny
from rest_framework.test import APIRequestFactory
from rest_framework.views import APIView

from apps.core.middleware import ApiErrorEnvelopeMiddleware, TenantMiddleware


class RaisingView(APIView):
    permission_classes = [AllowAny]
    exception = None

    def get(self, request):
        raise self.exception


def dispatch_exception(exc):
    view = RaisingView.as_view(exception=exc)
    return view(APIRequestFactory().get("/api/test-errors/"))


def test_missing_tenant_uses_canonical_error_envelope():
    request = SimpleNamespace(
        path="/api/requests/", headers={}, user=SimpleNamespace(is_authenticated=False)
    )

    response = TenantMiddleware(lambda request: None).process_request(request)

    assert response.status_code == 400
    assert json.loads(response.content) == {
        "code": "tenant_required",
        "message": "X-Tenant header required.",
        "details": [],
    }


def test_unexpected_integrity_field_and_key_errors_are_not_uncaught():
    integrity = dispatch_exception(IntegrityError("constraint details"))
    field = dispatch_exception(FieldError("bad field"))
    key = dispatch_exception(KeyError("missing"))

    assert integrity.status_code == 409
    assert integrity.data["code"] == "conflict"
    assert "constraint" not in integrity.data["message"]
    for response in (field, key):
        assert response.status_code == 500
        assert response.data == {
            "code": "server_error",
            "message": "The request could not be completed.",
            "details": [],
        }


def test_router_level_api_404_is_normalized_without_touching_non_api():
    middleware = ApiErrorEnvelopeMiddleware(lambda request: None)
    api_request = SimpleNamespace(path="/api/admin/users/not-a-uuid/")
    web_request = SimpleNamespace(path="/admin/missing/")

    api_response = middleware.process_response(
        api_request, HttpResponseNotFound("not found")
    )
    web_response = middleware.process_response(
        web_request, HttpResponseNotFound("not found")
    )

    api_data = json.loads(api_response.content)
    assert api_data["code"] == "not_found"
    assert set(api_data) == {"code", "message", "details"}
    assert web_response.content == b"not found"
