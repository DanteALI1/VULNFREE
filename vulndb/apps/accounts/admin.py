from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    fieldsets = BaseUserAdmin.fieldsets + (
        ("VULNDB", {"fields": ("full_name", "role", "is_verifier", "telegram_chat_id")}),
    )
    list_display = ("username", "email", "full_name", "role", "is_staff", "is_active")
    list_filter = ("role", "is_staff", "is_active", "is_verifier")
