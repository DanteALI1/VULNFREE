"""Require authentication for all pages except public endpoints."""

from __future__ import annotations

from django.conf import settings
from django.shortcuts import redirect
from django.utils.deprecation import MiddlewareMixin

PUBLIC_PREFIXES = (
    "/accounts/login/",
    "/accounts/logout/",
    "/accounts/sso/",
    "/accounts/ldap/",
    "/accounts/google/",
    "/setup/",
    "/healthz",
    "/readyz",
    "/static/",
    "/media/",
    "/admin/login/",
)


class LoginRequiredMiddleware(MiddlewareMixin):
    def process_request(self, request):
        path = request.path
        if any(path.startswith(p) for p in PUBLIC_PREFIXES):
            return None
        if request.user.is_authenticated:
            return None
        return redirect(f"{settings.LOGIN_URL}?next={path}")
