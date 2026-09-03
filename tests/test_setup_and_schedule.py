"""Setup wizard, scheduling rules, readyz."""

import pytest
from django.test import Client

from vulndb.apps.accounts.models import Role
from vulndb.apps.core.models import SystemSettings
from vulndb.apps.vulns.models import SyncState
from vulndb.apps.vulns.tasks import tick_sync_schedules


@pytest.mark.django_db
def test_setup_wizard_blocks_reentry_after_finish(user_factory):
    s = SystemSettings.load()
    s.setup_completed = True
    s.setup_step = 7
    s.save()
    client = Client()
    resp = client.get("/setup/")
    assert resp.status_code in (302, 301)
    assert resp.url == "/"


@pytest.mark.django_db
def test_setup_organization_step_accessible_when_incomplete():
    s = SystemSettings.load()
    s.setup_completed = False
    s.setup_step = 1
    s.save()
    client = Client()
    resp = client.get("/setup/organization/")
    assert resp.status_code == 200
    assert (
        "Организация".encode() in resp.content
        or b"organization" in resp.content.lower()
        or b"local_id" in resp.content
    )


@pytest.mark.django_db
def test_readyz_checks_db(settings):
    SystemSettings.load()
    settings.REDIS_URL = "redis://127.0.0.1:6399/15"  # unlikely up
    client = Client()
    # Bypass setup by marking completed
    s = SystemSettings.load()
    s.setup_completed = True
    s.save()
    resp = client.get("/readyz")
    # DB ok, redis likely fail → 503
    assert resp.status_code in (200, 503)
    if resp.status_code == 503:
        assert b"redis" in resp.content.lower() or b"db" in resp.content.lower()


@pytest.mark.django_db
def test_tick_sync_schedules_skips_kev_when_nvd_enabled(monkeypatch):
    s = SystemSettings.load()
    s.nvd_enabled = True
    s.kev_enabled = True
    s.bdu_enabled = False
    s.nvd_sync_interval_minutes = 1
    s.save()
    SyncState.objects.filter(source=SyncState.Source.NVD).delete()
    SyncState.objects.filter(source=SyncState.Source.KEV).delete()

    launched = []

    class FakeDelay:
        def __init__(self, name):
            self.name = name

        def delay(self):
            launched.append(self.name)

    monkeypatch.setattr("vulndb.apps.vulns.tasks.sync_nvd", FakeDelay("nvd"))
    monkeypatch.setattr("vulndb.apps.vulns.tasks.sync_kev", FakeDelay("kev"))
    monkeypatch.setattr("vulndb.apps.vulns.tasks.sync_bdu", FakeDelay("bdu"))

    result = tick_sync_schedules()
    assert "nvd" in result["launched"]
    assert "kev" not in result["launched"]


@pytest.mark.django_db
def test_tick_sync_schedules_kev_when_nvd_disabled(monkeypatch):
    s = SystemSettings.load()
    s.nvd_enabled = False
    s.kev_enabled = True
    s.bdu_enabled = False
    s.kev_sync_interval_minutes = 1
    s.save()
    SyncState.objects.all().delete()

    launched = []

    class FakeDelay:
        def __init__(self, name):
            self.name = name

        def delay(self):
            launched.append(self.name)

    monkeypatch.setattr("vulndb.apps.vulns.tasks.sync_nvd", FakeDelay("nvd"))
    monkeypatch.setattr("vulndb.apps.vulns.tasks.sync_kev", FakeDelay("kev"))
    monkeypatch.setattr("vulndb.apps.vulns.tasks.sync_bdu", FakeDelay("bdu"))

    result = tick_sync_schedules()
    assert "kev" in result["launched"]
    assert "nvd" not in result["launched"]


@pytest.mark.django_db
def test_assign_sets_assignee(user_factory):
    from vulndb.apps.tickets.services import apply_action, create_ticket
    from vulndb.apps.vulns.models import Vulnerability

    vuln = Vulnerability.objects.create(
        vuln_id="CVE-2024-ASSIGN",
        title="t",
        severity="HIGH",
    )
    analyst = user_factory("an_a", Role.ANALYST)
    assignee = user_factory("as_a", Role.TICKET_ASSIGNEE)
    ticket = create_ticket(vulnerability=vuln, created_by=analyst)
    ticket = apply_action(ticket, analyst, "triage")
    ticket = apply_action(ticket, analyst, "assign", assignee=assignee)
    assert ticket.assignee_id == assignee.id
    assert ticket.status == "in_progress"
