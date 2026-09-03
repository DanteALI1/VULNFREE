"""Ticket models and SLA mapping constants."""

from __future__ import annotations

from django.conf import settings
from django.db import models

# priority → sla_hours mapping for future auto-calculation
PRIORITY_SLA_HOURS = {
    "p1": 4,
    "p2": 24,
    "p3": 72,
    "p4": 168,
}


class Ticket(models.Model):
    class Status(models.TextChoices):
        NEW = "new", "Новая"
        TRIAGE = "triage", "Триаж"
        IN_PROGRESS = "in_progress", "В работе"
        WAITING = "waiting", "Ожидание"
        RESOLVED = "resolved", "Решена"
        CLOSED = "closed", "Закрыта"
        REJECTED = "rejected", "Отклонена"

    class Priority(models.TextChoices):
        P1 = "p1", "P1 — Критический"
        P2 = "p2", "P2 — Высокий"
        P3 = "p3", "P3 — Средний"
        P4 = "p4", "P4 — Низкий"

    number = models.PositiveIntegerField(unique=True, editable=False)
    status = models.CharField(
        max_length=32, choices=Status.choices, default=Status.NEW, db_index=True
    )
    priority = models.CharField(max_length=8, choices=Priority.choices, default=Priority.P3)
    vulnerability = models.ForeignKey(
        "vulns.Vulnerability",
        on_delete=models.CASCADE,
        related_name="tickets",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_tickets",
    )
    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_tickets",
    )
    title = models.CharField(max_length=255, blank=True, default="")
    reason = models.TextField(blank=True, default="")
    comment = models.TextField(blank=True, default="")
    rejection_reason = models.TextField(blank=True, default="")
    sla_due_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Заявка"
        verbose_name_plural = "Заявки"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.display_number

    @property
    def display_number(self) -> str:
        return f"T-{self.number}"

    def save(self, *args, **kwargs):
        if not self.number:
            last = Ticket.objects.order_by("-number").values_list("number", flat=True).first()
            self.number = max((last or 1000) + 1, 1001)
        if not self.title and self.vulnerability_id:
            self.title = f"Устранение {self.vulnerability.vuln_id}"
        super().save(*args, **kwargs)


class TicketEvent(models.Model):
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="events")
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    action = models.CharField(max_length=64)
    old_status = models.CharField(max_length=32, blank=True, default="")
    new_status = models.CharField(max_length=32, blank=True, default="")
    comment = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        verbose_name = "Событие заявки"
        verbose_name_plural = "События заявок"

    def __str__(self) -> str:
        return f"{self.ticket.display_number}: {self.action}"
