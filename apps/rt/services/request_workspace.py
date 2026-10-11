from rest_framework.exceptions import APIException, PermissionDenied, ValidationError

from .admin_permissions import (
    ATTACHMENTS_WRITE_PERMISSION,
    COMMENTS_WRITE_PERMISSION,
    REQUESTS_READ_PERMISSION,
    REQUESTS_TRANSITION_PERMISSION,
    REQUESTS_WRITE_PERMISSION,
    AdminPermissionError,
    get_admin_context,
)

OPERATIONS = {
    "can_comment": COMMENTS_WRITE_PERMISSION,
    "can_upload": ATTACHMENTS_WRITE_PERMISSION,
    "can_assign": REQUESTS_WRITE_PERMISSION,
    "can_transition": REQUESTS_TRANSITION_PERMISSION,
    "can_download_attachments": REQUESTS_READ_PERMISSION,
}


class WorkspaceConflict(APIException):
    status_code = 409
    default_code = "conflict"
    default_detail = "The operation conflicts with existing data."


def workspace_context(request):
    context = getattr(request, "rt_workspace_context", None)
    if context is None:
        try:
            context = get_admin_context(request, required_permission=None)
        except AdminPermissionError as exc:
            if exc.status_code == 400:
                raise ValidationError(
                    {"code": exc.code, "message": exc.message, "details": []}
                ) from exc
            raise PermissionDenied(
                "Tenant membership and request permission required."
            ) from exc
        request.rt_workspace_context = context
    if context.actor is None:
        raise PermissionDenied("Authenticated RT user required.")
    if context.actor.isactive is False:
        raise PermissionDenied("RT user is inactive.")
    return context


def require_workspace(request, permission=REQUESTS_READ_PERMISSION):
    context = workspace_context(request)
    if not {REQUESTS_READ_PERMISSION, permission}.issubset(context.permissions):
        raise PermissionDenied(f"Required permission: {permission}.")
    return context


def require_comment_text(request, text):
    # Upload containers need no text grant; authored notes are ordinary comments.
    if text:
        require_workspace(request, COMMENTS_WRITE_PERMISSION)


def capabilities(context):
    permissions = set(context.permissions)
    return {
        name: REQUESTS_READ_PERMISSION in permissions and permission in permissions
        for name, permission in OPERATIONS.items()
    }


def validate_request_relations(item):
    expected = str(item.tenantid_id).lower()
    if any(
        str(obj.tenantid_id).lower() != expected for obj in (item.flowid, item.statusid)
    ):
        raise PermissionDenied("Request metadata is unavailable for this tenant.")
    if item.statusid.flowid_id != item.flowid_id:
        raise PermissionDenied("Request metadata is inconsistent.")
