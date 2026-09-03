"""Branding context for all templates."""

from __future__ import annotations


def branding(request):
    try:
        from vulndb.apps.core.models import SystemSettings

        s = SystemSettings.load()
        return {
            "branding": {
                "product_name": s.product_name or "VULNDB",
                "organization_name": s.organization_name,
                "logo": s.logo,
                "accent_color": s.accent_color or "#0a7ab8",
                "sidebar_color": s.sidebar_color or "#1b2430",
                "login_title": s.login_title,
                "login_text": s.login_text,
            },
            "system_settings": s,
        }
    except Exception:
        return {
            "branding": {
                "product_name": "VULNDB",
                "organization_name": "",
                "logo": None,
                "accent_color": "#0a7ab8",
                "sidebar_color": "#1b2430",
                "login_title": "Вход в VULNDB",
                "login_text": "Локальная база данных уязвимостей",
            },
            "system_settings": None,
        }
