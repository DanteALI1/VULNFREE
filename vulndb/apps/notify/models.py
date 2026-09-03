"""Notification log model."""

from __future__ import annotations

from django.db import models


class NotificationLog(models.Model):
    class Channel(models.TextChoices):
        EMAIL = "email", "Email"
        TELEGRAM = "telegram", "Telegram"

    class Status(models.TextChoices):
        PENDING = "pending", "Ожидание"
        SENT = "sent", "Отправлено"
        FAILED = "failed", "Ошибка"

    channel = models.CharField(max_length=16, choices=Channel.choices)
    recipient = models.CharField(max_length=255)
    subject = models.CharField(max_length=255, blank=True, default="")
    body = models.TextField(blank=True, default="")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    error = models.TextField(blank=True, default="")
    ticket_id = models.PositiveIntegerField(null=True, blank=True)
    event = models.CharField(max_length=64, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Лог уведомления"
        verbose_name_plural = "Логи уведомлений"

    def __str__(self) -> str:
        return f"{self.channel} → {self.recipient}: {self.status}"
