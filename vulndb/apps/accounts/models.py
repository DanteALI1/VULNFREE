"""Custom user model and roles for VULNDB."""

from __future__ import annotations

from django.contrib.auth.models import AbstractUser
from django.db import models


class Role(models.TextChoices):
    PLATFORM_ADMIN = "platform_admin", "Администратор платформы"
    ANALYST = "analyst", "Аналитик"
    TICKET_ASSIGNEE = "ticket_assignee", "Исполнитель заявок"
    VERIFIER = "verifier", "Верификатор"


class User(AbstractUser):
    full_name = models.CharField("ФИО", max_length=255, blank=True)
    role = models.CharField(
        "Роль",
        max_length=32,
        choices=Role.choices,
        default=Role.ANALYST,
    )
    is_verifier = models.BooleanField("Верификатор", default=False)
    telegram_chat_id = models.CharField("Telegram chat ID", max_length=64, blank=True)

    class Meta:
        verbose_name = "Пользователь"
        verbose_name_plural = "Пользователи"

    def __str__(self) -> str:
        return self.full_name or self.username

    def has_role(self, role: str) -> bool:
        """superuser и platform_admin проходят проверку для любой роли."""
        if self.is_superuser or self.role == Role.PLATFORM_ADMIN:
            return True
        if role == Role.VERIFIER and self.is_verifier:
            return True
        return self.role == role
