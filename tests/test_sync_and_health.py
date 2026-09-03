"""Health endpoints and NVD→KEV coupling unit smoke."""

import pytest
from django.test import Client

from vulndb.apps.core.models import SystemSettings
from vulndb.apps.vulns.models import Vulnerability
from vulndb.apps.vulns.tasks import seed_demo_cves, sync_nvd


@pytest.mark.django_db
def test_healthz_no_db_dependency():
    c = Client()
    # bypass middlewares needing setup by hitting healthz which is public
    SystemSettings.objects.get_or_create(pk=1, defaults={"setup_completed": True})
    resp = c.get("/healthz")
    assert resp.status_code == 200
    assert resp.content == b"ok"


@pytest.mark.django_db
def test_sync_nvd_calls_kev_when_enabled(monkeypatch):
    SystemSettings.load()
    s = SystemSettings.load()
    s.kev_enabled = True
    s.nvd_enabled = True
    s.setup_completed = True
    s.save()

    called = {"kev": False}

    def fake_kev():
        called["kev"] = True
        return {"ok": True, "synced": 0}

    monkeypatch.setattr("vulndb.apps.vulns.tasks.sync_kev", fake_kev)
    monkeypatch.setattr(
        "vulndb.apps.vulns.tasks.request_with_retries",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("nvd down")),
    )

    result = sync_nvd()
    assert called["kev"] is True
    assert "kev" in result or result.get("ok") is False
    # demo seed when empty
    assert Vulnerability.objects.exists()


@pytest.mark.django_db
def test_seed_demo():
    assert seed_demo_cves() >= 2
    assert Vulnerability.objects.filter(vuln_id__startswith="CVE-").exists()
