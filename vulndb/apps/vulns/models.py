"""Vulnerability catalog models."""

from __future__ import annotations

from django.db import models
from django.utils import timezone


class Vulnerability(models.Model):
    class RecordType(models.TextChoices):
        CVE = "cve", "CVE"
        BDU = "bdu", "БДУ"
        LOCAL = "local", "Локальная"

    class Severity(models.TextChoices):
        CRITICAL = "CRITICAL", "Critical"
        HIGH = "HIGH", "High"
        MEDIUM = "MEDIUM", "Medium"
        LOW = "LOW", "Low"
        NONE = "NONE", "None"
        UNKNOWN = "UNKNOWN", "Unknown"

    vuln_id = models.CharField(max_length=64, unique=True, db_index=True)
    record_type = models.CharField(
        max_length=16, choices=RecordType.choices, default=RecordType.CVE
    )

    title = models.TextField(blank=True, default="")
    description_nvd = models.TextField(blank=True, default="")
    description_bdu = models.TextField(blank=True, default="")

    severity = models.CharField(
        max_length=16, choices=Severity.choices, default=Severity.UNKNOWN, db_index=True
    )
    cvss_score = models.FloatField(null=True, blank=True)
    cvss_v31 = models.JSONField(default=dict, blank=True)
    cvss_v30 = models.JSONField(default=dict, blank=True)
    cvss_v2 = models.JSONField(default=dict, blank=True)
    cvss_v40 = models.JSONField(default=dict, blank=True)

    cwe = models.JSONField(default=list, blank=True)
    cpe = models.JSONField(default=list, blank=True)
    references = models.JSONField(default=list, blank=True)

    in_kev = models.BooleanField(default=False, db_index=True)
    kev_data = models.JSONField(default=dict, blank=True)

    bdu_id = models.CharField(max_length=64, blank=True, default="", db_index=True)
    has_bdu = models.BooleanField(default=False)
    bdu_raw = models.JSONField(default=dict, blank=True)

    # CRITICAL: TextField — БДУ strings can exceed 255 chars
    vendor = models.TextField(blank=True, default="")
    product_name = models.TextField(blank=True, default="")
    product_version = models.TextField(blank=True, default="")
    remediation = models.TextField(blank=True, default="")

    vuln_status = models.CharField(max_length=64, blank=True, default="")
    exploit_present = models.BooleanField(default=False)

    published_at = models.DateTimeField(null=True, blank=True)
    modified_at = models.DateTimeField(null=True, blank=True)
    raw_nvd = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Уязвимость"
        verbose_name_plural = "Уязвимости"
        ordering = ["-modified_at", "-created_at"]
        indexes = [
            models.Index(fields=["record_type", "severity"]),
            models.Index(fields=["in_kev"]),
        ]

    def __str__(self) -> str:
        return self.vuln_id

    @property
    def badges(self) -> list[str]:
        result: list[str] = []
        if self.in_kev:
            result.append("KEV")
        if self.has_bdu or self.record_type == self.RecordType.BDU:
            result.append("BDU")
        if self.record_type == self.RecordType.LOCAL:
            result.append("LOCAL")
        return result


class LocalIdSequence(models.Model):
    prefix = models.CharField(max_length=16)
    year = models.PositiveIntegerField()
    last_number = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = ("prefix", "year")
        verbose_name = "Последовательность локальных ID"
        verbose_name_plural = "Последовательности локальных ID"

    def __str__(self) -> str:
        return f"{self.prefix}-{self.year}-{self.last_number:04d}"

    @classmethod
    def next_id(cls, prefix: str | None = None) -> str:
        """Атомарно выдаёт следующий локальный ID вида PREFIX-YEAR-NNNN."""
        import time

        from django.db import IntegrityError, OperationalError, transaction

        from vulndb.apps.core.models import SystemSettings

        if prefix is None:
            prefix = SystemSettings.load().local_id_prefix
        prefix = SystemSettings.validate_prefix(prefix)
        year = timezone.localtime().year
        last_exc: Exception | None = None
        for attempt in range(25):
            try:
                with transaction.atomic():
                    seq = (
                        cls.objects.select_for_update()
                        .filter(prefix=prefix, year=year)
                        .first()
                    )
                    if seq is None:
                        try:
                            seq = cls.objects.create(
                                prefix=prefix, year=year, last_number=0
                            )
                        except IntegrityError:
                            seq = cls.objects.select_for_update().get(
                                prefix=prefix, year=year
                            )
                    seq.last_number += 1
                    seq.save(update_fields=["last_number"])
                    return f"{prefix}-{year}-{seq.last_number:04d}"
            except (OperationalError, IntegrityError) as exc:
                last_exc = exc
                time.sleep(0.02 * (attempt + 1))
        raise last_exc  # type: ignore[misc]

    @classmethod
    def validate_prefix(cls, prefix: str) -> str:
        from vulndb.apps.core.models import SystemSettings

        return SystemSettings.validate_prefix(prefix)


class SyncState(models.Model):
    class Source(models.TextChoices):
        NVD = "nvd", "NVD"
        KEV = "kev", "CISA KEV"
        BDU = "bdu", "БДУ ФСТЭК"

    class Status(models.TextChoices):
        IDLE = "idle", "Ожидание"
        RUNNING = "running", "Выполняется"
        SUCCESS = "success", "Успех"
        ERROR = "error", "Ошибка"

    source = models.CharField(max_length=16, choices=Source.choices, unique=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.IDLE)
    checkpoint = models.JSONField(default=dict, blank=True)
    last_success_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True, default="")
    items_total = models.PositiveIntegerField(default=0)
    items_synced = models.PositiveIntegerField(default=0)
    meta = models.JSONField(default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Состояние синхронизации"
        verbose_name_plural = "Состояния синхронизации"

    def __str__(self) -> str:
        return f"{self.source}: {self.status}"

    @classmethod
    def get_or_create_source(cls, source: str) -> SyncState:
        obj, _ = cls.objects.get_or_create(source=source)
        return obj

    def mark_running(self, total: int = 0) -> None:
        self.status = self.Status.RUNNING
        self.last_error = ""
        self.items_total = total
        self.items_synced = 0
        self.save(
            update_fields=["status", "last_error", "items_total", "items_synced", "updated_at"]
        )

    def mark_progress(self, synced: int, total: int | None = None) -> None:
        self.items_synced = synced
        fields = ["items_synced", "updated_at"]
        if total is not None:
            self.items_total = total
            fields.append("items_total")
        self.save(update_fields=fields)

    def mark_success(self, checkpoint: dict | None = None) -> None:
        self.status = self.Status.SUCCESS
        self.last_success_at = timezone.now()
        self.last_error = ""
        if checkpoint is not None:
            self.checkpoint = checkpoint
        self.save(
            update_fields=["status", "last_success_at", "last_error", "checkpoint", "updated_at"]
        )

    def mark_error(self, error: str) -> None:
        self.status = self.Status.ERROR
        self.last_error = (error or "")[:4000]
        self.save(update_fields=["status", "last_error", "updated_at"])
