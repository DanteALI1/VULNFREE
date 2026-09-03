"""Core models: SystemSettings singleton."""

from __future__ import annotations

import re

from django.core.exceptions import ValidationError
from django.db import models


def validate_logo_file(value) -> None:
    if value.size > 2 * 1024 * 1024:
        raise ValidationError("Логотип не должен превышать 2 МБ.")
    name = (value.name or "").lower()
    # ImageField/Pillow: raster only (без SVG)
    if not name.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif")):
        raise ValidationError("Допустимы только PNG, JPG, WEBP, GIF.")


class SystemSettings(models.Model):
    """Singleton настроек системы (pk=1)."""

    RESERVED_PREFIXES = {"CVE", "BDU"}

    setup_completed = models.BooleanField(default=False)
    setup_step = models.PositiveSmallIntegerField(default=1)

    organization_name = models.CharField(max_length=255, blank=True, default="")
    local_id_prefix = models.CharField(max_length=16, default="ACME")
    product_name = models.CharField(max_length=64, default="VULNDB")

    login_title = models.CharField(max_length=255, blank=True, default="Вход в VULNDB")
    login_text = models.TextField(blank=True, default="Локальная база данных уязвимостей")
    logo = models.ImageField(
        upload_to="branding/", blank=True, null=True, validators=[validate_logo_file]
    )
    accent_color = models.CharField(max_length=16, default="#0a7ab8")
    sidebar_color = models.CharField(max_length=16, default="#1b2430")

    # NVD
    nvd_api_key = models.CharField(max_length=128, blank=True, default="")
    nvd_enabled = models.BooleanField(default=True)
    nvd_sync_interval_minutes = models.PositiveIntegerField(default=60)

    # KEV
    kev_enabled = models.BooleanField(default=True)
    kev_sync_interval_minutes = models.PositiveIntegerField(default=360)

    # БДУ
    bdu_enabled = models.BooleanField(default=True)
    bdu_xlsx_url = models.URLField(
        default="https://bdu.fstec.ru/files/documents/vullist.xlsx",
        max_length=512,
    )
    bdu_sync_interval_minutes = models.PositiveIntegerField(default=1440)
    bdu_verify_ssl = models.BooleanField(default=False)

    # Mail provider fields
    mail_provider = models.CharField(
        max_length=32,
        choices=[
            ("smtp", "SMTP"),
            ("exchange", "Exchange"),
            ("office365", "Office 365"),
            ("gmail", "Gmail"),
        ],
        default="smtp",
        blank=True,
    )
    mail_smtp_host = models.CharField(max_length=255, blank=True, default="")
    mail_smtp_port = models.PositiveIntegerField(default=587)
    mail_smtp_user = models.CharField(max_length=255, blank=True, default="")
    mail_smtp_password = models.CharField(max_length=255, blank=True, default="")
    mail_use_tls = models.BooleanField(default=True)
    mail_from_address = models.EmailField(blank=True, default="")
    mail_exchange_server = models.CharField(max_length=255, blank=True, default="")
    mail_office365_tenant = models.CharField(max_length=255, blank=True, default="")
    mail_gmail_app_password = models.CharField(max_length=255, blank=True, default="")
    mail_enabled = models.BooleanField(default=False)

    # Telegram
    telegram_bot_token = models.CharField(max_length=255, blank=True, default="")
    telegram_enabled = models.BooleanField(default=False)
    telegram_default_chat_id = models.CharField(max_length=64, blank=True, default="")

    # Auth flags (SSO stubs)
    auth_local_enabled = models.BooleanField(default=True)
    auth_google_enabled = models.BooleanField(default=False)
    auth_sso_enabled = models.BooleanField(default=False)
    auth_ldap_enabled = models.BooleanField(default=False)

    # DB connection metadata (password NEVER stored here — only in .env)
    db_host = models.CharField(max_length=255, blank=True, default="")
    db_port = models.PositiveIntegerField(default=5432)
    db_name = models.CharField(max_length=128, blank=True, default="")
    db_user = models.CharField(max_length=128, blank=True, default="")
    db_sslmode = models.CharField(max_length=32, blank=True, default="prefer")
    db_configured = models.BooleanField(default=False)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Системные настройки"
        verbose_name_plural = "Системные настройки"

    def __str__(self) -> str:
        return f"SystemSettings(setup_completed={self.setup_completed})"

    def save(self, *args, **kwargs):
        self.pk = 1
        self.local_id_prefix = self.validate_prefix(self.local_id_prefix)
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        pass  # singleton — не удаляем

    @classmethod
    def load(cls) -> SystemSettings:
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    @classmethod
    def validate_prefix(cls, prefix: str) -> str:
        value = (prefix or "").strip().upper()
        if not re.fullmatch(r"[A-Z0-9]{2,16}", value):
            raise ValidationError("Префикс: 2–16 символов [A-Z0-9].")
        if value in cls.RESERVED_PREFIXES:
            raise ValidationError(f"Префикс «{value}» зарезервирован.")
        return value
