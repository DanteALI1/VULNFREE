"""
Ticket workflow services and permission matrix.

Матрица переходов (status → allowed actions → new status):
  new         → triage, reject
  triage      → assign (→ in_progress), reject
  in_progress → wait, resolve, force_close
  waiting     → resume (→ in_progress)
  resolved    → confirm_close (→ closed), reopen (→ in_progress)
  closed      → reopen (→ in_progress)
  rejected    → reopen (→ triage)

Матрица прав:
  platform_admin: настройки, force_close (+ все роли через has_role)
  analyst: создать локальную уязвимость, создать заявку, triage/assign/reject
  ticket_assignee: start/wait/resume/resolve
  verifier: confirm_close/reopen
  закрыть заявку (confirm_close): создатель ИЛИ verifier ИЛИ admin
  assignee НЕ может закрыть сам себе (покрыто тестом)
"""

from __future__ import annotations

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from vulndb.apps.accounts.models import Role
from vulndb.apps.audit.services import log_action
from vulndb.apps.notify.tasks import notify_ticket_event
from vulndb.apps.tickets.models import PRIORITY_SLA_HOURS, Ticket, TicketEvent

TRANSITIONS: dict[str, dict[str, str]] = {
    Ticket.Status.NEW: {
        "triage": Ticket.Status.TRIAGE,
        "reject": Ticket.Status.REJECTED,
    },
    Ticket.Status.TRIAGE: {
        "assign": Ticket.Status.IN_PROGRESS,
        "start": Ticket.Status.IN_PROGRESS,
        "reject": Ticket.Status.REJECTED,
    },
    Ticket.Status.IN_PROGRESS: {
        "wait": Ticket.Status.WAITING,
        "resolve": Ticket.Status.RESOLVED,
        "force_close": Ticket.Status.CLOSED,
    },
    Ticket.Status.WAITING: {
        "resume": Ticket.Status.IN_PROGRESS,
    },
    Ticket.Status.RESOLVED: {
        "confirm_close": Ticket.Status.CLOSED,
        "reopen": Ticket.Status.IN_PROGRESS,
    },
    Ticket.Status.CLOSED: {
        "reopen": Ticket.Status.IN_PROGRESS,
    },
    Ticket.Status.REJECTED: {
        "reopen": Ticket.Status.TRIAGE,
    },
}

ACTION_ROLES: dict[str, list[str]] = {
    "triage": [Role.ANALYST],
    "assign": [Role.ANALYST],
    "reject": [Role.ANALYST],
    "start": [Role.TICKET_ASSIGNEE],
    "wait": [Role.TICKET_ASSIGNEE],
    "resume": [Role.TICKET_ASSIGNEE],
    "resolve": [Role.TICKET_ASSIGNEE],
    "force_close": [Role.PLATFORM_ADMIN],
    "confirm_close": [Role.VERIFIER],
    "reopen": [Role.VERIFIER],
}


def _is_admin(user) -> bool:
    return bool(user and (user.is_superuser or user.role == Role.PLATFORM_ADMIN))


def user_can_perform(user, action: str, ticket: Ticket | None = None) -> bool:
    if not user or not user.is_authenticated:
        return False
    if _is_admin(user):
        return True

    if action == "confirm_close" and ticket is not None:
        # assignee сам себе закрыть не может (кроме admin / creator / verifier)
        if (
            ticket.assignee_id == user.id
            and ticket.created_by_id != user.id
            and not user.has_role(Role.VERIFIER)
        ):
            return False
        if ticket.created_by_id == user.id:
            return True
        return user.has_role(Role.VERIFIER)

    roles = ACTION_ROLES.get(action, [])
    return any(user.has_role(r) for r in roles)


def create_ticket(
    *, vulnerability, created_by, priority=Ticket.Priority.P3, reason="", assignee=None
) -> Ticket:
    if not created_by.has_role(Role.ANALYST):
        raise PermissionDenied("Только аналитик может создавать заявки.")
    sla_hours = PRIORITY_SLA_HOURS.get(priority, 72)
    ticket = Ticket.objects.create(
        vulnerability=vulnerability,
        created_by=created_by,
        assignee=assignee,
        priority=priority,
        reason=reason,
        sla_due_at=timezone.now() + timezone.timedelta(hours=sla_hours),
    )
    TicketEvent.objects.create(
        ticket=ticket,
        actor=created_by,
        action="create",
        new_status=ticket.status,
        comment=reason,
    )
    log_action(created_by, "ticket.create", ticket, meta={"number": ticket.number})
    try:
        notify_ticket_event.delay(ticket.id, "create")
    except Exception:  # noqa: BLE001
        pass
    return ticket


@transaction.atomic
def apply_action(ticket: Ticket, user, action: str, *, comment: str = "", assignee=None) -> Ticket:
    action = action.strip().lower()
    allowed = TRANSITIONS.get(ticket.status, {})
    if action not in allowed:
        raise ValidationError(f"Действие «{action}» недоступно из статуса «{ticket.status}».")
    if not user_can_perform(user, action, ticket):
        raise PermissionDenied(f"Недостаточно прав для действия «{action}».")

    if action == "confirm_close":
        if (
            ticket.assignee_id == user.id
            and not _is_admin(user)
            and ticket.created_by_id != user.id
        ):
            raise PermissionDenied("Исполнитель не может закрыть заявку сам себе.")
        if (
            ticket.assignee_id == user.id
            and ticket.created_by_id == user.id
            and not (_is_admin(user) or user.has_role(Role.VERIFIER))
        ):
            # creator who is also assignee may close as creator — allowed by matrix
            pass

    old_status = ticket.status
    new_status = allowed[action]
    ticket.status = new_status
    if action == "assign" and assignee is not None:
        ticket.assignee = assignee
    if action == "reject":
        ticket.rejection_reason = comment
    if comment:
        ticket.comment = comment
    ticket.save()

    TicketEvent.objects.create(
        ticket=ticket,
        actor=user,
        action=action,
        old_status=old_status,
        new_status=new_status,
        comment=comment,
    )
    log_action(user, f"ticket.{action}", ticket, meta={"from": old_status, "to": new_status})
    try:
        notify_ticket_event.delay(ticket.id, action)
    except Exception:  # noqa: BLE001
        pass
    return ticket


def available_actions(ticket: Ticket, user) -> list[str]:
    return [a for a in TRANSITIONS.get(ticket.status, {}) if user_can_perform(user, a, ticket)]
