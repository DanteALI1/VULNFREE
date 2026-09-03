"""Стили должны существовать и подключаться в базовом шаблоне."""

from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from vulndb.apps.accounts.models import Role
from vulndb.apps.core.models import SystemSettings

CSS = Path(__file__).resolve().parents[1] / "vulndb" / "static" / "css" / "app.css"


def test_app_css_exists_in_source():
    assert CSS.is_file()
    text = CSS.read_text(encoding="utf-8")
    assert ".sidebar" in text
    assert ".layout" in text


@pytest.mark.django_db
def test_login_page_links_stylesheet():
    SystemSettings.objects.get_or_create(pk=1, defaults={"setup_completed": True})
    s = SystemSettings.load()
    s.setup_completed = True
    s.save()
    client = Client()
    resp = client.get("/accounts/login/")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert 'rel="stylesheet"' in body
    assert "/static/css/app" in body
    assert "/static/vendor/htmx" in body


@pytest.mark.django_db
def test_dashboard_uses_layout_after_login():
    SystemSettings.objects.get_or_create(pk=1, defaults={"setup_completed": True})
    s = SystemSettings.load()
    s.setup_completed = True
    s.save()
    user = get_user_model().objects.create_user(
        username="admin_css", password="Passw0rd!", role=Role.PLATFORM_ADMIN
    )
    client = Client()
    client.force_login(user)
    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "/static/css/app" in body
    assert "Дашборд" in body
