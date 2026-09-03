"""Ticket workflow and permission matrix tests."""

import pytest
from django.core.exceptions import PermissionDenied

from vulndb.apps.accounts.models import Role
from vulndb.apps.tickets.models import Ticket
from vulndb.apps.tickets.services import apply_action, create_ticket
from vulndb.apps.vulns.models import Vulnerability


@pytest.fixture
def vuln(db):
    return Vulnerability.objects.create(
        vuln_id="CVE-2024-TEST",
        record_type=Vulnerability.RecordType.CVE,
        title="Test vuln",
        severity=Vulnerability.Severity.HIGH,
        cvss_score=8.0,
    )


@pytest.mark.django_db
def test_ticket_workflow_happy_path(user_factory, vuln):
    analyst = user_factory("analyst1", Role.ANALYST)
    assignee = user_factory("assignee1", Role.TICKET_ASSIGNEE)
    verifier = user_factory("verifier1", Role.VERIFIER, is_verifier=True)

    ticket = create_ticket(vulnerability=vuln, created_by=analyst, assignee=assignee)
    assert ticket.number > 1000
    assert ticket.display_number.startswith("T-")
    assert ticket.status == Ticket.Status.NEW

    ticket = apply_action(ticket, analyst, "triage")
    assert ticket.status == Ticket.Status.TRIAGE

    ticket = apply_action(ticket, assignee, "start")
    assert ticket.status == Ticket.Status.IN_PROGRESS

    ticket = apply_action(ticket, assignee, "resolve")
    assert ticket.status == Ticket.Status.RESOLVED

    ticket = apply_action(ticket, verifier, "confirm_close")
    assert ticket.status == Ticket.Status.CLOSED


@pytest.mark.django_db
def test_assignee_cannot_close_own_ticket(user_factory, vuln):
    analyst = user_factory("analyst2", Role.ANALYST)
    assignee = user_factory("assignee2", Role.TICKET_ASSIGNEE)

    ticket = create_ticket(vulnerability=vuln, created_by=analyst, assignee=assignee)
    ticket = apply_action(ticket, analyst, "triage")
    ticket = apply_action(ticket, assignee, "start")
    ticket = apply_action(ticket, assignee, "resolve")

    with pytest.raises(PermissionDenied):
        apply_action(ticket, assignee, "confirm_close")

    assert Ticket.objects.get(pk=ticket.pk).status == Ticket.Status.RESOLVED


@pytest.mark.django_db
def test_creator_can_close(user_factory, vuln):
    analyst = user_factory("analyst3", Role.ANALYST)
    assignee = user_factory("assignee3", Role.TICKET_ASSIGNEE)
    ticket = create_ticket(vulnerability=vuln, created_by=analyst, assignee=assignee)
    ticket = apply_action(ticket, analyst, "triage")
    ticket = apply_action(ticket, assignee, "start")
    ticket = apply_action(ticket, assignee, "resolve")
    ticket = apply_action(ticket, analyst, "confirm_close")
    assert ticket.status == Ticket.Status.CLOSED


@pytest.mark.django_db
def test_analyst_cannot_resolve(user_factory, vuln):
    analyst = user_factory("analyst4", Role.ANALYST)
    ticket = create_ticket(vulnerability=vuln, created_by=analyst)
    ticket = apply_action(ticket, analyst, "triage")
    ticket.status = Ticket.Status.IN_PROGRESS
    ticket.save()
    with pytest.raises(PermissionDenied):
        apply_action(ticket, analyst, "resolve")
