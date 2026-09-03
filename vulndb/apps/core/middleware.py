"""Redirect to setup wizard until setup_completed=True."""

from __future__ import annotations

from django.shortcuts import redirect
from django.utils.deprecation import MiddlewareMixin

SKIP_PREFIXES = ("/setup/", "/healthz", "/readyz", "/static/", "/media/", "/accounts/login/")


class SetupRequiredMiddleware(MiddlewareMixin):
    def process_request(self, request):
        path = request.path
        if any(path.startswith(p) for p in SKIP_PREFIXES):
            return None
        try:
            from vulndb.apps.core.models import SystemSettings

            settings_obj = SystemSettings.load()
        except Exception:
            # БД ещё не готова / миграций нет
            if path.startswith("/setup/"):
                return None
            return redirect("/setup/")
        if not settings_obj.setup_completed:
            return redirect("/setup/")
        return None
