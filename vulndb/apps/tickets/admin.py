from django.contrib import admin

from .models import Ticket, TicketEvent


class TicketEventInline(admin.TabularInline):
    model = TicketEvent
    extra = 0
    readonly_fields = ("actor", "action", "old_status", "new_status", "comment", "created_at")


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = ("number", "status", "priority", "vulnerability", "assignee", "created_at")
    list_filter = ("status", "priority")
    inlines = [TicketEventInline]


@admin.register(TicketEvent)
class TicketEventAdmin(admin.ModelAdmin):
    list_display = ("ticket", "action", "actor", "created_at")
