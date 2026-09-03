"""Async notification delivery via Celery."""

from __future__ import annotations

import logging

import requests
from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail

from vulndb.apps.notify.models import NotificationLog

logger = logging.getLogger(__name__)


def _send_email(recipient: str, subject: str, body: str, ticket_id=None, event: str = "") -> None:
    log = NotificationLog.objects.create(
        channel=NotificationLog.Channel.EMAIL,
        recipient=recipient,
        subject=subject,
        body=body,
        ticket_id=ticket_id,
        event=event,
    )
    try:
        from vulndb.apps.core.models import SystemSettings

        s = SystemSettings.load()
        if not s.mail_enabled and not settings.EMAIL_HOST:
            log.status = NotificationLog.Status.FAILED
            log.error = "Почта не настроена"
            log.save(update_fields=["status", "error"])
            return
        send_mail(
            subject,
            body,
            s.mail_from_address or settings.DEFAULT_FROM_EMAIL,
            [recipient],
            fail_silently=False,
        )
        log.status = NotificationLog.Status.SENT
        log.save(update_fields=["status"])
    except Exception as exc:  # noqa: BLE001
        log.status = NotificationLog.Status.FAILED
        log.error = str(exc)[:2000]
        log.save(update_fields=["status", "error"])
        logger.exception("Email notification failed")


def _send_telegram(chat_id: str, body: str, ticket_id=None, event: str = "") -> None:
    log = NotificationLog.objects.create(
        channel=NotificationLog.Channel.TELEGRAM,
        recipient=chat_id,
        subject="",
        body=body,
        ticket_id=ticket_id,
        event=event,
    )
    try:
        from vulndb.apps.core.models import SystemSettings

        s = SystemSettings.load()
        token = s.telegram_bot_token or getattr(settings, "TELEGRAM_BOT_TOKEN", "")
        if not s.telegram_enabled or not token:
            log.status = NotificationLog.Status.FAILED
            log.error = "Telegram не настроен"
            log.save(update_fields=["status", "error"])
            return
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        resp = requests.post(url, json={"chat_id": chat_id, "text": body}, timeout=30)
        if resp.status_code >= 400:
            raise RuntimeError(f"Telegram API {resp.status_code}: {resp.text[:500]}")
        log.status = NotificationLog.Status.SENT
        log.save(update_fields=["status"])
    except Exception as exc:  # noqa: BLE001
        log.status = NotificationLog.Status.FAILED
        log.error = str(exc)[:2000]
        log.save(update_fields=["status", "error"])
        logger.exception("Telegram notification failed")


@shared_task(name="vulndb.apps.notify.tasks.notify_ticket_event")
def notify_ticket_event(ticket_id: int, event: str) -> None:
    try:
        from vulndb.apps.tickets.models import Ticket

        ticket = Ticket.objects.select_related("assignee", "created_by", "vulnerability").get(
            pk=ticket_id
        )
    except Exception:  # noqa: BLE001
        logger.exception("notify_ticket_event: ticket %s not found", ticket_id)
        return

    subject = f"Заявка {ticket.display_number}: {event}"
    body = (
        f"Заявка {ticket.display_number}\n"
        f"Уязвимость: {ticket.vulnerability.vuln_id}\n"
        f"Статус: {ticket.get_status_display()}\n"
        f"Событие: {event}\n"
    )
    recipients: set[str] = set()
    if ticket.created_by and ticket.created_by.email:
        recipients.add(ticket.created_by.email)
    if ticket.assignee and ticket.assignee.email:
        recipients.add(ticket.assignee.email)
    for email in recipients:
        try:
            _send_email(email, subject, body, ticket_id=ticket.id, event=event)
        except Exception:  # noqa: BLE001
            logger.exception("email send failed")

    chat_ids: set[str] = set()
    if ticket.assignee and ticket.assignee.telegram_chat_id:
        chat_ids.add(ticket.assignee.telegram_chat_id)
    if ticket.created_by and ticket.created_by.telegram_chat_id:
        chat_ids.add(ticket.created_by.telegram_chat_id)
    try:
        from vulndb.apps.core.models import SystemSettings

        s = SystemSettings.load()
        if s.telegram_default_chat_id:
            chat_ids.add(s.telegram_default_chat_id)
    except Exception:  # noqa: BLE001
        pass
    for chat_id in chat_ids:
        try:
            _send_telegram(chat_id, body, ticket_id=ticket.id, event=event)
        except Exception:  # noqa: BLE001
            logger.exception("telegram send failed")
