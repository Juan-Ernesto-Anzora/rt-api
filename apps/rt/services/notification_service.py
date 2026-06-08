import logging

from django.conf import settings
from django.core.mail import send_mail

from apps.rt.models import User

logger = logging.getLogger(__name__)


def notify_request_created(rt_request):
    recipients = _request_recipients(rt_request)
    _send_notification(
        subject=f"Request created: {rt_request.humanid}",
        message=_request_message(rt_request, "A request was created."),
        recipients=recipients,
    )


def notify_request_assigned(rt_request):
    assignee = _request_assignee(rt_request)
    recipients = _unique_emails(assignee)
    _send_notification(
        subject=f"Request assigned: {rt_request.humanid}",
        message=_request_message(rt_request, "A request was assigned."),
        recipients=recipients,
    )


def notify_comment_added(comment):
    rt_request = getattr(comment, "requestid", None)
    if rt_request is None:
        return
    _send_notification(
        subject=f"Comment added: {rt_request.humanid}",
        message=_request_message(rt_request, "A comment was added."),
        recipients=_request_recipients(rt_request),
    )


def notify_request_closed(rt_request):
    _send_notification(
        subject=f"Request closed: {rt_request.humanid}",
        message=_request_message(rt_request, "A request was closed."),
        recipients=_request_recipients(rt_request),
    )


def _request_recipients(rt_request):
    return _unique_emails(
        getattr(rt_request, "requesterid", None),
        _request_assignee(rt_request),
    )


def _request_assignee(rt_request):
    try:
        assignee = getattr(rt_request, "assigneeid", None)
    except Exception:
        assignee = None
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


def _request_message(rt_request, headline):
    request_url = f"{settings.WEB_BASE_URL.rstrip('/')}/requests/{rt_request.requestid}"
    return "\n".join(
        [
            headline,
            f"Human ID: {rt_request.humanid}",
            f"Title: {rt_request.title}",
            f"Request ID: {rt_request.requestid}",
            f"Link: {request_url}",
        ]
    )


def _send_notification(subject, message, recipients):
    if not recipients:
        return
    try:
        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=recipients,
            fail_silently=True,
        )
    except Exception:
        logger.exception("Failed to send notification email.")
