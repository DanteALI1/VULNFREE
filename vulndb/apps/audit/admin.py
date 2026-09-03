from django.contrib import admin

from .models import AuditEntry


@admin.register(AuditEntry)
class AuditEntryAdmin(admin.ModelAdmin):
    list_display = ("action", "user", "target_repr", "created_at")
    list_filter = ("action",)
    search_fields = ("action", "target_repr")
