from django.contrib import admin

from .models import LocalIdSequence, SyncState, Vulnerability


@admin.register(Vulnerability)
class VulnerabilityAdmin(admin.ModelAdmin):
    list_display = ("vuln_id", "record_type", "severity", "in_kev", "has_bdu", "vendor")
    list_filter = ("record_type", "severity", "in_kev", "has_bdu")
    search_fields = ("vuln_id", "title", "vendor", "product_name")


@admin.register(LocalIdSequence)
class LocalIdSequenceAdmin(admin.ModelAdmin):
    list_display = ("prefix", "year", "last_number")


@admin.register(SyncState)
class SyncStateAdmin(admin.ModelAdmin):
    list_display = ("source", "status", "items_synced", "items_total", "last_success_at")
