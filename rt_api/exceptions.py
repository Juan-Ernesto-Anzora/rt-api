import logging
from http import HTTPStatus

from django.core.exceptions import FieldError, ValidationError as DjangoValidationError
from django.db import IntegrityError
from rest_framework import status
from rest_framework.exceptions import ErrorDetail
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

logger = logging.getLogger(__name__)


def error_envelope(code, message, details=None):
    return {"code": code, "message": str(message), "details": details or []}


def format_error_details(errors):
    details = []

    def walk(value, field=""):
        if isinstance(value, dict):
            for key, child in value.items():
                child_field = f"{field}.{key}" if field else str(key)
                walk(child, child_field)
            return
        if isinstance(value, (list, tuple)):
            for child in value:
                walk(child, field)
            return
        details.append({"field": field, "message": str(value)})

    walk(errors)
    return details


def api_exception_handler(exc, context):
    response = drf_exception_handler(exc, context)
    if response is None:
        response = _unexpected_exception_response(exc)
    if response is None:
        return None

    data = response.data
    if isinstance(data, dict) and {"code", "message", "details"}.issubset(data):
        response.data = error_envelope(data["code"], data["message"], data["details"])
        return response

    message = _message_from_data(data, response.status_code)
    code = _code_for_status(response.status_code, exc)
    details = [] if _is_detail_only(data) else format_error_details(data)
    response.data = error_envelope(code, message, details)
    return response


def _unexpected_exception_response(exc):
    if isinstance(exc, IntegrityError):
        logger.exception("Unhandled database integrity error in API request.")
        return Response(
            error_envelope("conflict", "The operation conflicts with existing data."),
            status=status.HTTP_409_CONFLICT,
        )
    if isinstance(exc, (DjangoValidationError, ValueError)):
        return Response(
            error_envelope(
                "validation_error",
                "Invalid request value.",
                format_error_details(getattr(exc, "message_dict", str(exc))),
            ),
            status=status.HTTP_400_BAD_REQUEST,
        )
    if isinstance(exc, (FieldError, KeyError)):
        logger.exception("Unhandled API programming error.")
        return Response(
            error_envelope("server_error", "The request could not be completed."),
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
    return None


def _message_from_data(data, status_code):
    if isinstance(data, dict) and "detail" in data:
        return str(data["detail"])
    if isinstance(data, ErrorDetail):
        return str(data)
    try:
        return HTTPStatus(status_code).phrase
    except ValueError:
        return "Request failed."


def _is_detail_only(data):
    return isinstance(data, dict) and set(data) == {"detail"}


def _code_for_status(status_code, exc):
    default_code = getattr(exc, "default_code", None)
    if status_code == 400:
        return "validation_error"
    if status_code == 401:
        return "authentication_required"
    if status_code == 403:
        return "permission_denied"
    if status_code == 404:
        return "not_found"
    if status_code == 409:
        return "conflict"
    if status_code == 429:
        return "throttled"
    return str(default_code or "request_failed")
