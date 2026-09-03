"""Создаёт роли Django и помечает setup завершённым (для scripts/install.sh)."""

from __future__ import annotations

import os

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand

from vulndb.apps.accounts.models import Role, User
from vulndb.apps.core.models import SystemSettings


def _upsert_user(
    *,
    username: str,
    password: str,
    role: str,
    full_name: str,
    is_superuser: bool = False,
    is_verifier: bool = False,
) -> bool:
    user, created = User.objects.get_or_create(
        username=username,
        defaults={
            "email": f"{username}@localhost",
            "full_name": full_name,
            "role": role,
            "is_staff": is_superuser,
            "is_superuser": is_superuser,
            "is_verifier": is_verifier,
        },
    )
    user.full_name = full_name
    user.role = role
    user.is_staff = is_superuser
    user.is_superuser = is_superuser
    user.is_verifier = is_verifier
    user.set_password(password)
    user.save()
    return created


class Command(BaseCommand):
    help = "Bootstrap SystemSettings + default role accounts from environment."

    def handle(self, *args, **options):
        org = os.environ.get("DJANGO_BOOTSTRAP_ORG", "VULNDB")
        prefix = os.environ.get("DJANGO_BOOTSTRAP_PREFIX", "ACME")
        try:
            prefix = SystemSettings.validate_prefix(prefix)
        except ValidationError:
            prefix = "ACME"

        settings = SystemSettings.load()
        settings.organization_name = org
        settings.local_id_prefix = prefix
        settings.product_name = settings.product_name or "VULNDB"
        settings.setup_completed = True
        settings.setup_step = 7
        settings.save()

        accounts = [
            (
                os.environ.get("DJANGO_BOOTSTRAP_ADMIN_USER", "admin"),
                os.environ.get("DJANGO_BOOTSTRAP_ADMIN_PASS", ""),
                Role.PLATFORM_ADMIN,
                "Администратор платформы",
                True,
                False,
            ),
            (
                os.environ.get("DJANGO_BOOTSTRAP_ANALYST_USER", "analyst"),
                os.environ.get("DJANGO_BOOTSTRAP_ANALYST_PASS", ""),
                Role.ANALYST,
                "Аналитик",
                False,
                False,
            ),
            (
                os.environ.get("DJANGO_BOOTSTRAP_ASSIGNEE_USER", "assignee"),
                os.environ.get("DJANGO_BOOTSTRAP_ASSIGNEE_PASS", ""),
                Role.TICKET_ASSIGNEE,
                "Исполнитель заявок",
                False,
                False,
            ),
            (
                os.environ.get("DJANGO_BOOTSTRAP_VERIFIER_USER", "verifier"),
                os.environ.get("DJANGO_BOOTSTRAP_VERIFIER_PASS", ""),
                Role.VERIFIER,
                "Верификатор",
                False,
                True,
            ),
        ]
        for username, password, role, full_name, is_super, is_ver in accounts:
            if not password:
                self.stderr.write(self.style.WARNING(f"Пропуск {username}: пароль пуст"))
                continue
            created = _upsert_user(
                username=username,
                password=password,
                role=role,
                full_name=full_name,
                is_superuser=is_super,
                is_verifier=is_ver,
            )
            state = "создан" if created else "обновлён"
            self.stdout.write(f"Пользователь {username} ({role}) {state}")

        self.stdout.write(self.style.SUCCESS("bootstrap_install: setup_completed=True"))
