"""Vulnerability list/detail/create views."""

from __future__ import annotations

from datetime import timedelta

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from vulndb.apps.accounts.models import Role
from vulndb.apps.audit.services import log_action
from vulndb.apps.core.forms import LocalVulnerabilityForm
from vulndb.apps.vulns.models import LocalIdSequence, Vulnerability


def vuln_list(request: HttpRequest) -> HttpResponse:
    qs = Vulnerability.objects.all()
    q = request.GET.get("q", "").strip()
    record_type = request.GET.get("type", "").strip()
    severity = request.GET.get("severity", "").strip()
    kev = request.GET.get("kev", "").strip()
    days = request.GET.get("days", "").strip()
    cvss_min = request.GET.get("cvss_min", "").strip()
    cvss_max = request.GET.get("cvss_max", "").strip()

    if q:
        qs = qs.filter(
            Q(title__icontains=q)
            | Q(vuln_id__icontains=q)
            | Q(vendor__icontains=q)
            | Q(product_name__icontains=q)
        )
    if record_type:
        qs = qs.filter(record_type=record_type)
    if severity:
        qs = qs.filter(severity=severity)
    if kev == "1":
        qs = qs.filter(in_kev=True)
    elif kev == "0":
        qs = qs.filter(in_kev=False)
    if days.isdigit():
        since = timezone.now() - timedelta(days=int(days))
        qs = qs.filter(modified_at__gte=since)
    if cvss_min:
        try:
            qs = qs.filter(cvss_score__gte=float(cvss_min))
        except ValueError:
            pass
    if cvss_max:
        try:
            qs = qs.filter(cvss_score__lte=float(cvss_max))
        except ValueError:
            pass

    paginator = Paginator(qs, 25)
    page = paginator.get_page(request.GET.get("page"))
    ctx = {
        "page": page,
        "filters": {
            "q": q,
            "type": record_type,
            "severity": severity,
            "kev": kev,
            "days": days,
            "cvss_min": cvss_min,
            "cvss_max": cvss_max,
        },
        "severities": Vulnerability.Severity.choices,
        "types": Vulnerability.RecordType.choices,
    }
    if request.headers.get("HX-Request"):
        return render(request, "vulns/partials/list_table.html", ctx)
    return render(request, "vulns/list.html", ctx)


def vuln_detail(request: HttpRequest, vuln_id: str) -> HttpResponse:
    vuln = get_object_or_404(Vulnerability, vuln_id=vuln_id)
    tickets = vuln.tickets.select_related("assignee", "created_by").all()
    return render(
        request,
        "vulns/detail.html",
        {"vuln": vuln, "tickets": tickets, "tab": request.GET.get("tab", "nvd")},
    )


@require_http_methods(["GET", "POST"])
def vuln_local_create(request: HttpRequest) -> HttpResponse:
    if not request.user.has_role(Role.ANALYST):
        raise PermissionDenied("Только аналитик может создавать локальные записи.")
    form = LocalVulnerabilityForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        obj.vuln_id = LocalIdSequence.next_id()
        obj.record_type = Vulnerability.RecordType.LOCAL
        obj.modified_at = timezone.now()
        obj.save()
        log_action(request.user, "vuln.create_local", obj)
        messages.success(request, f"Создана локальная запись {obj.vuln_id}")
        return redirect("vuln_detail", vuln_id=obj.vuln_id)
    return render(request, "vulns/local_form.html", {"form": form})
