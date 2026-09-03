"""bootstrap_install management command used by scripts/install.sh."""

import pytest
from django.core.management import call_command

from vulndb.apps.accounts.models import Role, User
from vulndb.apps.core.models import SystemSettings


@pytest.mark.django_db
def test_bootstrap_install_creates_roles(monkeypatch):
    monkeypatch.setenv("DJANGO_BOOTSTRAP_ORG", "ACME Org")
    monkeypatch.setenv("DJANGO_BOOTSTRAP_PREFIX", "ACME")
    monkeypatch.setenv("DJANGO_BOOTSTRAP_ADMIN_USER", "admin")
    monkeypatch.setenv("DJANGO_BOOTSTRAP_ADMIN_PASS", "Adm1n-Install-Pass!")
    monkeypatch.setenv("DJANGO_BOOTSTRAP_ANALYST_USER", "analyst")
    monkeypatch.setenv("DJANGO_BOOTSTRAP_ANALYST_PASS", "An4lyst-Install-Pass!")
    monkeypatch.setenv("DJANGO_BOOTSTRAP_ASSIGNEE_USER", "assignee")
    monkeypatch.setenv("DJANGO_BOOTSTRAP_ASSIGNEE_PASS", "As5ignee-Install-Pass!")
    monkeypatch.setenv("DJANGO_BOOTSTRAP_VERIFIER_USER", "verifier")
    monkeypatch.setenv("DJANGO_BOOTSTRAP_VERIFIER_PASS", "Ver1fier-Install-Pass!")

    call_command("bootstrap_install")

    s = SystemSettings.load()
    assert s.setup_completed is True
    assert s.organization_name == "ACME Org"
    assert s.local_id_prefix == "ACME"

    admin = User.objects.get(username="admin")
    assert admin.role == Role.PLATFORM_ADMIN
    assert admin.is_superuser
    assert admin.check_password("Adm1n-Install-Pass!")

    analyst = User.objects.get(username="analyst")
    assert analyst.role == Role.ANALYST
    assert analyst.check_password("An4lyst-Install-Pass!")

    assignee = User.objects.get(username="assignee")
    assert assignee.role == Role.TICKET_ASSIGNEE

    verifier = User.objects.get(username="verifier")
    assert verifier.role == Role.VERIFIER
    assert verifier.is_verifier
