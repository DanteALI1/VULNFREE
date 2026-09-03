"""Ticket views."""

from __future__ import annotations

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from vulndb.apps.core.forms import TicketCreateForm
from vulndb.apps.tickets.models import Ticket
from vulndb.apps.tickets.services import apply_action, available_actions, create_ticket


def ticket_list(request: HttpRequest) -> HttpResponse:
    qs = Ticket.objects.select_related("vulnerability", "assignee", "created_by")
    status = request.GET.get("status", "")
    if status:
        qs = qs.filter(status=status)
    page = Paginator(qs, 25).get_page(request.GET.get("page"))
    ctx = {"page": page, "statuses": Ticket.Status.choices, "status": status}
    if request.headers.get("HX-Request"):
        return render(request, "tickets/partials/list_table.html", ctx)
    return render(request, "tickets/list.html", ctx)


def ticket_detail(request: HttpRequest, number: int) -> HttpResponse:
    ticket = get_object_or_404(
        Ticket.objects.select_related("vulnerability", "assignee", "created_by"),
        number=number,
    )
    events = ticket.events.select_related("actor").all()
    actions = available_actions(ticket, request.user)
    from django.contrib.auth import get_user_model

    assignees = get_user_model().objects.filter(is_active=True).order_by("username")
    return render(
        request,
        "tickets/detail.html",
        {"ticket": ticket, "events": events, "actions": actions, "assignees": assignees},
    )


@require_http_methods(["GET", "POST"])
def ticket_create(request: HttpRequest) -> HttpResponse:
    initial = {}
    vuln_id = request.GET.get("vuln")
    if vuln_id:
        from vulndb.apps.vulns.models import Vulnerability

        vuln = Vulnerability.objects.filter(vuln_id=vuln_id).first()
        if vuln:
            initial["vulnerability"] = vuln
    form = TicketCreateForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        try:
            ticket = create_ticket(
                vulnerability=form.cleaned_data["vulnerability"],
                created_by=request.user,
                priority=form.cleaned_data["priority"],
                reason=form.cleaned_data.get("reason") or "",
                assignee=form.cleaned_data.get("assignee"),
            )
            messages.success(request, f"Создана заявка {ticket.display_number}")
            return redirect("ticket_detail", number=ticket.number)
        except PermissionDenied as exc:
            messages.error(request, str(exc))
    return render(request, "tickets/form.html", {"form": form})


@require_POST
def ticket_action(request: HttpRequest, number: int) -> HttpResponse:
    from django.contrib.auth import get_user_model

    ticket = get_object_or_404(Ticket, number=number)
    action = request.POST.get("action", "")
    comment = request.POST.get("comment", "")
    assignee = None
    assignee_id = request.POST.get("assignee_id")
    if assignee_id:
        assignee = get_user_model().objects.filter(pk=assignee_id, is_active=True).first()
    try:
        ticket = apply_action(ticket, request.user, action, comment=comment, assignee=assignee)
        messages.success(request, f"Действие «{action}» выполнено.")
    except (PermissionDenied, ValidationError) as exc:
        messages.error(request, str(exc))
    events = ticket.events.select_related("actor").all()
    actions = available_actions(ticket, request.user)
    assignees = get_user_model().objects.filter(is_active=True).order_by("username")
    if request.headers.get("HX-Request"):
        return render(
            request,
            "tickets/partials/detail_body.html",
            {
                "ticket": ticket,
                "events": events,
                "actions": actions,
                "assignees": assignees,
            },
        )
    return redirect("ticket_detail", number=ticket.number)
