from __future__ import annotations

from django.contrib.auth.views import LoginView, LogoutView
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.urls import path

from vulndb.apps.audit.services import log_action


class VulnLoginView(LoginView):
    template_name = "accounts/login.html"
    redirect_authenticated_user = True

    def form_valid(self, form):
        response = super().form_valid(form)
        log_action(
            self.request.user,
            "login",
            self.request.user,
            meta={"ip": self.request.META.get("REMOTE_ADDR")},
        )
        return response


class VulnLogoutView(LogoutView):
    next_page = "/accounts/login/"


def sso_stub(request: HttpRequest) -> HttpResponse:
    return render(
        request,
        "accounts/stub_501.html",
        {
            "title": "SSO / Google / LDAP",
            "message": "Интеграция SSO/LDAP не реализована в этой версии (501 Not Implemented).",
        },
        status=501,
    )


urlpatterns = [
    path("login/", VulnLoginView.as_view(), name="login"),
    path("logout/", VulnLogoutView.as_view(), name="logout"),
    path("sso/", sso_stub, name="sso"),
    path("ldap/", sso_stub, name="ldap"),
    path("google/", sso_stub, name="google"),
]
