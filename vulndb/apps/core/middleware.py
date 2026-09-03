"""Redirect to setup wizard until setup_completed=True."""

from __future__ import annotations

from django.shortcuts import redirect
from django.utils.deprecation import MiddlewareMixin

SKIP_PREFIXES = (
    "/healthz",
    "/readyz",
    "/static/",
    "/media/",
    "/accounts/login/",
)


class SetupRequiredMiddleware(MiddlewareMixin):
    def process_request(self, request):
        path = request.path
        try:
            from vulndb.apps.core.models import SystemSettings

            settings_obj = SystemSettings.load()
        except Exception:
            # БД ещё не готова / миграций нет — пускаем только setup и служебные
            if path.startswith("/setup/") or any(path.startswith(p) for p in SKIP_PREFIXES):
                return None
            return redirect("/setup/")

        if settings_obj.setup_completed:
            # После finish повторный заход в wizard запрещён
            if path.startswith("/setup/"):
                return redirect("/")
            return None

        if path.startswith("/setup/") or any(path.startswith(p) for p in SKIP_PREFIXES):
            return None
        return redirect("/setup/")
