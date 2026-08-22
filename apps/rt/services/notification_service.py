import logging

from django.conf import settings
from django.core.mail import send_mail

from apps.rt.models import Featureflag, Notificationtemplate, Tenantsetting, User
from apps.rt.services.admin_configuration import (
    normalize_setting_value,
    render_safe_template,
)

logger = logging.getLogger(__name__)

BUILT_IN_TEMPLATES = {
    "request.created": ("Request created: {human_id}", "A request was created."),
    "request.assigned": ("Request assigned: {human_id}", "A request was assigned."),
    "comment.added": ("Comment added: {human_id}", "A comment was added."),
    "request.closed": ("Request closed: {human_id}", "A request was closed."),
}


def notify_request_created(rt_request):
    _notify_event(
        "request.created", rt_request, recipients=_request_recipients(rt_request)
    )


def notify_request_assigned(rt_request):
    assignee = _request_assignee(rt_request)
    _notify_event("request.assigned", rt_request, recipients=_unique_emails(assignee))


def notify_comment_added(comment):
    rt_request = getattr(comment, "requestid", None)
    if rt_request is None:
        return
    _notify_event(
        "comment.added",
        rt_request,
        recipients=_request_recipients(rt_request),
        comment=comment,
    )


def notify_request_closed(rt_request):
    _notify_event(
        "request.closed", rt_request, recipients=_request_recipients(rt_request)
    )


def _notify_event(event_type, rt_request, recipients, comment=None):
    context, from_email = _notification_context(rt_request, comment)
    subject_template, headline = BUILT_IN_TEMPLATES[event_type]
    subject = render_safe_template(subject_template, context)
    message = _request_message(rt_request, headline, context["request_url"])

    try:
        tenant_id = _tenant_id(rt_request)
        if tenant_id and _tenant_templates_enabled(tenant_id):
            template = Notificationtemplate.objects.filter(
                tenantid_id=tenant_id,
                eventtype=event_type,
                isactive=True,
            ).first()
            if template is not None:
                subject = render_safe_template(template.subjecttemplate, context)
                message = render_safe_template(template.bodytemplate, context)
    except Exception:
        logger.exception(
            "Failed to load or render tenant notification template; using fallback."
        )

    _send_notification(subject, message, recipients, from_email=from_email)


def _notification_context(rt_request, comment=None):
    tenant_id = _tenant_id(rt_request)
    web_base_url = settings.WEB_BASE_URL
    from_email = settings.DEFAULT_FROM_EMAIL
    if tenant_id:
        try:
            configured = {
                item.key: item
                for item in Tenantsetting.objects.filter(
                    tenantid_id=tenant_id,
                    key__in=["web_base_url", "email_from"],
                )
            }
            web_setting = configured.get("web_base_url")
            if web_setting and web_setting.value:
                web_base_url = normalize_setting_value(
                    "web_base_url", "url", web_setting.value
                )
            email_setting = configured.get("email_from")
            if email_setting and email_setting.value:
                from_email = normalize_setting_value(
                    "email_from", "email", email_setting.value
                )
        except Exception:
            logger.exception(
                "Failed to load tenant notification settings; using defaults."
            )

    request_url = f"{web_base_url.rstrip('/')}/requests/{rt_request.requestid}"
    requester = _related_object(rt_request, "requesterid")
    assignee = _request_assignee(rt_request)
    author = _related_object(comment, "authorid") if comment else None
    status_obj = _related_object(rt_request, "statusid")
    context = {
        "human_id": str(getattr(rt_request, "humanid", "") or ""),
        "title": str(getattr(rt_request, "title", "") or ""),
        "request_id": str(getattr(rt_request, "requestid", "") or ""),
        "request_url": request_url,
        "requester_name": _display_name(requester),
        "assignee_name": _display_name(assignee),
        "comment_author": _display_name(author),
        "status_name": str(getattr(status_obj, "name", "") or ""),
    }
    return context, from_email


def _tenant_templates_enabled(tenant_id):
    enabled = (
        Featureflag.objects.filter(tenantid_id=tenant_id, key="notificationTemplates")
        .values_list("enabled", flat=True)
        .first()
    )
    return enabled is not False


def _tenant_id(rt_request):
    tenant_id = getattr(rt_request, "tenantid_id", None)
    if tenant_id:
        return tenant_id
    tenant = _related_object(rt_request, "tenantid")
    return getattr(tenant, "tenantid", None)


def _request_recipients(rt_request):
    return _unique_emails(
        _related_object(rt_request, "requesterid"),
        _request_assignee(rt_request),
    )


def _request_assignee(rt_request):
    assignee = _related_object(rt_request, "assigneeid")
    if assignee:
        return assignee

    assignee_id = getattr(rt_request, "assigneeid_id", None)
    if not assignee_id:
        return None
    try:
        return User.objects.get(userid=assignee_id)
    except Exception:
        logger.exception("Failed to resolve request assignee for notification.")
        return None


def _related_object(instance, field):
    if instance is None:
        return None
    try:
        return getattr(instance, field, None)
    except Exception:
        return None


def _display_name(user):
    if user is None:
        return ""
    return str(getattr(user, "displayname", None) or getattr(user, "email", None) or "")


def _unique_emails(*users):
    emails = []
    seen = set()
    for user in users:
        email = (getattr(user, "email", "") or "").strip()
        normalized = email.lower()
        if email and normalized not in seen:
            emails.append(email)
            seen.add(normalized)
    return emails


def _request_message(rt_request, headline, request_url=None):
    request_url = request_url or (
        f"{settings.WEB_BASE_URL.rstrip('/')}/requests/{rt_request.requestid}"
    )
    return "\n".join(
        [
            headline,
            f"Human ID: {rt_request.humanid}",
            f"Title: {rt_request.title}",
            f"Request ID: {rt_request.requestid}",
            f"Link: {request_url}",
        ]
    )


def _send_notification(subject, message, recipients, from_email=None):
    if not recipients:
        return
    try:
        send_mail(
            subject=subject,
            message=message,
            from_email=from_email or settings.DEFAULT_FROM_EMAIL,
            recipient_list=recipients,
            fail_silently=True,
        )
    except Exception:
        logger.exception("Failed to send notification email.")
