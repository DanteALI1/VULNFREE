"""Core views: health, dashboard, setup wizard, settings, metrics."""

from __future__ import annotations

import logging

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from vulndb.apps.accounts.models import Role
from vulndb.apps.audit.services import log_action
from vulndb.apps.core.forms import (
    AdminSetupForm,
    BrandingForm,
    DatabaseForm,
    MailSetupForm,
    OrganizationForm,
    SourcesForm,
)
from vulndb.apps.core.models import SystemSettings
from vulndb.apps.tickets.models import Ticket
from vulndb.apps.vulns.models import SyncState, Vulnerability

logger = logging.getLogger(__name__)
User = get_user_model()

SETUP_STEPS = [
    ("organization", "Организация"),
    ("branding", "Брендинг"),
    ("database", "База данных"),
    ("sources", "Источники"),
    ("admin", "Администратор"),
    ("mail", "Почта"),
    ("finish", "Завершение"),
]


def _apply_mail_form(s: SystemSettings, data: dict) -> None:
    for field in (
        "mail_enabled",
        "mail_provider",
        "mail_smtp_host",
        "mail_smtp_port",
        "mail_smtp_user",
        "mail_smtp_password",
        "mail_use_tls",
        "mail_from_address",
        "mail_exchange_server",
        "mail_office365_tenant",
        "mail_gmail_app_password",
    ):
        if data.get(field) is not None:
            setattr(s, field, data[field])


def _test_db_connection(data: dict) -> tuple[bool, str]:
    """Проверка подключения к PostgreSQL. Пароль только из DATABASE_URL / POSTGRES_PASSWORD."""
    import os
    from urllib.parse import urlparse

    host = data.get("db_host") or ""
    if not host:
        return False, "Укажите хост БД или нажмите «Пропустить»."
    password = os.environ.get("POSTGRES_PASSWORD", "")
    db_url = os.environ.get("DATABASE_URL", "")
    if db_url:
        parsed = urlparse(db_url)
        password = parsed.password or password
    try:
        import psycopg

        with psycopg.connect(
            host=host,
            port=int(data.get("db_port") or 5432),
            dbname=data.get("db_name") or "vulndb",
            user=data.get("db_user") or "vulndb",
            password=password,
            connect_timeout=5,
        ) as conn:
            conn.execute("SELECT 1")
        return True, "Подключение к PostgreSQL успешно."
    except Exception as exc:  # noqa: BLE001
        return False, f"Ошибка подключения: {exc}"


def _send_test_mail(data: dict) -> tuple[bool, str]:
    from django.conf import settings as dj_settings
    from django.core.mail import get_connection, send_mail

    to = data.get("test_to") or data.get("mail_from_address")
    if not to:
        return False, "Укажите адрес для проверки (test_to или From)."
    host = data.get("mail_smtp_host") or dj_settings.EMAIL_HOST
    if not host:
        return False, "SMTP хост не задан — укажите или пропустите шаг."
    try:
        connection = get_connection(
            host=host,
            port=int(data.get("mail_smtp_port") or 587),
            username=data.get("mail_smtp_user") or "",
            password=data.get("mail_smtp_password") or data.get("mail_gmail_app_password") or "",
            use_tls=bool(data.get("mail_use_tls")),
            timeout=15,
        )
        send_mail(
            "VULNDB — тестовое письмо",
            "Если вы видите это сообщение, SMTP настроен корректно.",
            data.get("mail_from_address") or dj_settings.DEFAULT_FROM_EMAIL,
            [to],
            connection=connection,
            fail_silently=False,
        )
        return True, f"Тестовое письмо отправлено на {to}."
    except Exception as exc:  # noqa: BLE001
        return False, f"Не удалось отправить: {exc}"


@require_GET
def healthz(request: HttpRequest) -> HttpResponse:
    """Liveness — без обращения к БД/Redis."""
    return HttpResponse("ok", content_type="text/plain")


@require_GET
def readyz(request: HttpRequest) -> HttpResponse:
    """Readiness — проверяет БД + Redis."""
    errors = []
    try:
        from django.db import connection

        connection.ensure_connection()
    except Exception as exc:  # noqa: BLE001
        errors.append(f"db: {exc}")
    try:
        import redis
        from django.conf import settings

        r = redis.from_url(settings.REDIS_URL, socket_connect_timeout=2)
        r.ping()
    except Exception as exc:  # noqa: BLE001
        errors.append(f"redis: {exc}")
    if errors:
        return HttpResponse("; ".join(errors), status=503, content_type="text/plain")
    return HttpResponse("ok", content_type="text/plain")


def dashboard(request: HttpRequest) -> HttpResponse:
    qs = Vulnerability.objects.all()
    ctx = {
        "count_critical": qs.filter(severity=Vulnerability.Severity.CRITICAL).count(),
        "count_high": qs.filter(severity=Vulnerability.Severity.HIGH).count(),
        "count_kev": qs.filter(in_kev=True).count(),
        "count_local": qs.filter(record_type=Vulnerability.RecordType.LOCAL).count(),
        "attention": qs.filter(
            severity__in=[Vulnerability.Severity.CRITICAL, Vulnerability.Severity.HIGH]
        ).order_by("-modified_at")[:10],
        "open_tickets": Ticket.objects.exclude(
            status__in=[Ticket.Status.CLOSED, Ticket.Status.REJECTED]
        ).select_related("vulnerability", "assignee")[:10],
        "sync_states": list(SyncState.objects.all()),
    }
    return render(request, "core/dashboard.html", ctx)


def _setup_guard(request: HttpRequest):
    s = SystemSettings.load()
    if s.setup_completed:
        return None, redirect("/")
    return s, None


@require_http_methods(["GET", "POST"])
def setup_wizard(request: HttpRequest, step: str | None = None) -> HttpResponse:
    s, early = _setup_guard(request)
    if early:
        return early

    step_names = [name for name, _ in SETUP_STEPS]
    if not step:
        step = step_names[max(0, min(s.setup_step - 1, len(step_names) - 1))]
    if step not in step_names:
        return redirect(f"/setup/{step_names[0]}/")

    # Нельзя перескакивать шаги вперёд (resume только с текущего/пройденных)
    requested_index = step_names.index(step) + 1
    max_allowed = max(s.setup_step, 1)
    if requested_index > max_allowed:
        return redirect(f"/setup/{step_names[max_allowed - 1]}/")

    step_index = requested_index
    ctx = {
        "steps": SETUP_STEPS,
        "current_step": step,
        "step_index": step_index,
        "settings": s,
    }

    if step == "organization":
        form = OrganizationForm(
            request.POST or None,
            initial={
                "organization_name": s.organization_name,
                "local_id_prefix": s.local_id_prefix,
            },
        )
        if request.method == "POST" and form.is_valid():
            s.organization_name = form.cleaned_data["organization_name"]
            s.local_id_prefix = form.cleaned_data["local_id_prefix"]
            s.setup_step = max(s.setup_step, 2)
            s.save()
            return redirect("/setup/branding/")
        ctx["form"] = form
        return render(request, "setup/organization.html", ctx)

    if step == "branding":
        form = BrandingForm(
            request.POST or None,
            request.FILES or None,
            initial={
                "product_name": s.product_name,
                "login_title": s.login_title,
                "login_text": s.login_text,
            },
        )
        if request.method == "POST" and form.is_valid():
            s.product_name = form.cleaned_data["product_name"]
            s.login_title = form.cleaned_data["login_title"]
            s.login_text = form.cleaned_data["login_text"]
            if form.cleaned_data.get("logo"):
                s.logo = form.cleaned_data["logo"]
            s.setup_step = max(s.setup_step, 3)
            s.save()
            return redirect("/setup/database/")
        ctx["form"] = form
        return render(request, "setup/branding.html", ctx)

    if step == "database":
        form = DatabaseForm(
            request.POST or None,
            initial={
                "db_host": s.db_host,
                "db_port": s.db_port,
                "db_name": s.db_name,
                "db_user": s.db_user,
                "db_sslmode": s.db_sslmode,
            },
        )
        if request.method == "POST" and form.is_valid():
            action = form.cleaned_data.get("action") or "save"
            if form.cleaned_data.get("skip") or action == "skip":
                s.setup_step = max(s.setup_step, 4)
                s.save()
                return redirect("/setup/sources/")
            if action == "test":
                ok, msg = _test_db_connection(form.cleaned_data)
                ctx["form"] = form
                ctx["db_test_message"] = msg
                ctx["db_test_ok"] = ok
                return render(request, "setup/database.html", ctx)
            s.db_host = form.cleaned_data.get("db_host") or ""
            s.db_port = form.cleaned_data.get("db_port") or 5432
            s.db_name = form.cleaned_data.get("db_name") or ""
            s.db_user = form.cleaned_data.get("db_user") or ""
            s.db_sslmode = form.cleaned_data.get("db_sslmode") or "prefer"
            s.db_configured = bool(s.db_host)
            s.setup_step = max(s.setup_step, 4)
            s.save()
            return redirect("/setup/sources/")
        ctx["form"] = form
        return render(request, "setup/database.html", ctx)

    if step == "sources":
        form = SourcesForm(
            request.POST or None,
            initial={
                "nvd_enabled": s.nvd_enabled,
                "nvd_api_key": s.nvd_api_key,
                "nvd_sync_interval_minutes": s.nvd_sync_interval_minutes,
                "kev_enabled": s.kev_enabled,
                "kev_sync_interval_minutes": s.kev_sync_interval_minutes,
                "bdu_enabled": s.bdu_enabled,
                "bdu_xlsx_url": s.bdu_xlsx_url,
                "bdu_sync_interval_minutes": s.bdu_sync_interval_minutes,
                "bdu_verify_ssl": s.bdu_verify_ssl,
            },
        )
        if request.method == "POST" and form.is_valid():
            for field in form.cleaned_data:
                setattr(s, field, form.cleaned_data[field])
            s.setup_step = max(s.setup_step, 5)
            s.save()
            return redirect("/setup/admin/")
        ctx["form"] = form
        return render(request, "setup/sources.html", ctx)

    if step == "admin":
        form = AdminSetupForm(request.POST or None)
        if request.method == "POST" and form.is_valid():
            user = User.objects.create_superuser(
                username=form.cleaned_data["username"],
                email=form.cleaned_data.get("email") or "",
                password=form.cleaned_data["password1"],
            )
            user.full_name = form.cleaned_data.get("full_name") or ""
            user.role = Role.PLATFORM_ADMIN
            user.save()
            s.setup_step = max(s.setup_step, 6)
            s.save()
            return redirect("/setup/mail/")
        ctx["form"] = form
        return render(request, "setup/admin.html", ctx)

    if step == "mail":
        form = MailSetupForm(
            request.POST or None,
            initial={
                "mail_enabled": s.mail_enabled,
                "mail_provider": s.mail_provider,
                "mail_smtp_host": s.mail_smtp_host,
                "mail_smtp_port": s.mail_smtp_port,
                "mail_smtp_user": s.mail_smtp_user,
                "mail_use_tls": s.mail_use_tls,
                "mail_from_address": s.mail_from_address,
                "mail_exchange_server": s.mail_exchange_server,
                "mail_office365_tenant": s.mail_office365_tenant,
            },
        )
        if request.method == "POST" and form.is_valid():
            if request.POST.get("do_test") == "1":
                # Save fields first then send test
                _apply_mail_form(s, form.cleaned_data)
                s.save()
                ok, msg = _send_test_mail(form.cleaned_data)
                ctx["form"] = form
                ctx["mail_test_message"] = msg
                ctx["mail_test_ok"] = ok
                return render(request, "setup/mail.html", ctx)
            if not form.cleaned_data.get("skip"):
                _apply_mail_form(s, form.cleaned_data)
            s.setup_step = max(s.setup_step, 7)
            s.save()
            return redirect("/setup/finish/")
        ctx["form"] = form
        return render(request, "setup/mail.html", ctx)

    if step == "finish":
        if request.method == "POST":
            has_admin = User.objects.filter(role=Role.PLATFORM_ADMIN).exists()
            has_super = User.objects.filter(is_superuser=True).exists()
            if not has_admin and not has_super:
                messages.error(request, "Сначала создайте администратора на шаге Admin.")
                return redirect("/setup/admin/")
            try:
                call_command("migrate", interactive=False, verbosity=0)
            except Exception:  # noqa: BLE001
                logger.exception("migrate on finish")
            s.setup_completed = True
            s.setup_step = 7
            s.save()
            log_action(request.user if request.user.is_authenticated else None, "setup.finish", s)
            # Launch syncs per §4 rule
            from vulndb.apps.vulns.tasks import sync_bdu, sync_kev, sync_nvd

            if s.nvd_enabled:
                sync_nvd.delay()
            elif s.kev_enabled:
                sync_kev.delay()
            if s.bdu_enabled:
                sync_bdu.delay()
            messages.success(request, "Настройка завершена. Войдите в систему.")
            return redirect("/accounts/login/")
        return render(request, "setup/finish.html", ctx)

    return redirect("/setup/organization/")


@require_POST
def setup_validate_prefix(request: HttpRequest) -> HttpResponse:
    prefix = request.POST.get("local_id_prefix", "")
    try:
        value = SystemSettings.validate_prefix(prefix)
        return HttpResponse(
            f'<span class="ok">✓ Префикс «{value}» допустим</span>',
            content_type="text/html",
        )
    except Exception as exc:  # noqa: BLE001
        return HttpResponse(f'<span class="err">✗ {exc}</span>', content_type="text/html")


def settings_view(request: HttpRequest, tab: str = "org") -> HttpResponse:
    if not request.user.has_role(Role.PLATFORM_ADMIN):
        messages.error(request, "Недостаточно прав.")
        return redirect("/")
    s = SystemSettings.load()
    tabs = ["org", "branding", "sources", "database", "auth", "mail", "telegram", "system"]
    if tab not in tabs:
        tab = "org"
    ctx = {"tab": tab, "tabs": tabs, "settings": s, "sync_states": list(SyncState.objects.all())}

    if request.method == "POST":
        action = request.POST.get("action", "save")
        if action == "save":
            if tab == "org":
                form = OrganizationForm(request.POST)
                if form.is_valid():
                    s.organization_name = form.cleaned_data["organization_name"]
                    s.local_id_prefix = form.cleaned_data["local_id_prefix"]
                    s.save()
                    log_action(request.user, "settings.org", s)
                    messages.success(request, "Сохранено.")
            elif tab == "branding":
                form = BrandingForm(request.POST, request.FILES)
                if form.is_valid():
                    s.product_name = form.cleaned_data["product_name"]
                    s.login_title = form.cleaned_data["login_title"]
                    s.login_text = form.cleaned_data["login_text"]
                    if form.cleaned_data.get("logo"):
                        s.logo = form.cleaned_data["logo"]
                    s.save()
                    log_action(request.user, "settings.branding", s)
                    messages.success(request, "Сохранено.")
            elif tab == "sources":
                form = SourcesForm(request.POST)
                if form.is_valid():
                    for field, value in form.cleaned_data.items():
                        setattr(s, field, value)
                    s.save()
                    log_action(request.user, "settings.sources", s)
                    messages.success(request, "Сохранено.")
            elif tab == "mail":
                form = MailSetupForm(request.POST)
                if form.is_valid():
                    for field, value in form.cleaned_data.items():
                        if field != "skip" and hasattr(s, field):
                            setattr(s, field, value)
                    s.save()
                    log_action(request.user, "settings.mail", s)
                    messages.success(request, "Сохранено.")
            elif tab == "telegram":
                s.telegram_enabled = request.POST.get("telegram_enabled") == "on"
                s.telegram_bot_token = request.POST.get("telegram_bot_token", s.telegram_bot_token)
                s.telegram_default_chat_id = request.POST.get(
                    "telegram_default_chat_id", s.telegram_default_chat_id
                )
                s.save()
                log_action(request.user, "settings.telegram", s)
                messages.success(request, "Сохранено.")
            elif tab == "auth":
                s.auth_local_enabled = request.POST.get("auth_local_enabled") == "on"
                s.auth_google_enabled = request.POST.get("auth_google_enabled") == "on"
                s.auth_sso_enabled = request.POST.get("auth_sso_enabled") == "on"
                s.auth_ldap_enabled = request.POST.get("auth_ldap_enabled") == "on"
                s.save()
                log_action(request.user, "settings.auth", s)
                messages.success(request, "Сохранено.")
            elif tab == "database":
                form = DatabaseForm(request.POST)
                if form.is_valid() and not form.cleaned_data.get("skip"):
                    s.db_host = form.cleaned_data.get("db_host") or ""
                    s.db_port = form.cleaned_data.get("db_port") or 5432
                    s.db_name = form.cleaned_data.get("db_name") or ""
                    s.db_user = form.cleaned_data.get("db_user") or ""
                    s.db_sslmode = form.cleaned_data.get("db_sslmode") or "prefer"
                    s.db_configured = bool(s.db_host)
                    s.save()
                    log_action(request.user, "settings.database", s)
                    messages.success(request, "Метаданные БД сохранены (пароль только в .env).")
            return redirect(f"/settings/{tab}/")

    if tab == "org":
        ctx["form"] = OrganizationForm(
            initial={"organization_name": s.organization_name, "local_id_prefix": s.local_id_prefix}
        )
    elif tab == "branding":
        ctx["form"] = BrandingForm(
            initial={
                "product_name": s.product_name,
                "login_title": s.login_title,
                "login_text": s.login_text,
            }
        )
    elif tab == "sources":
        ctx["form"] = SourcesForm(
            initial={
                "nvd_enabled": s.nvd_enabled,
                "nvd_api_key": s.nvd_api_key,
                "nvd_sync_interval_minutes": s.nvd_sync_interval_minutes,
                "kev_enabled": s.kev_enabled,
                "kev_sync_interval_minutes": s.kev_sync_interval_minutes,
                "bdu_enabled": s.bdu_enabled,
                "bdu_xlsx_url": s.bdu_xlsx_url,
                "bdu_sync_interval_minutes": s.bdu_sync_interval_minutes,
                "bdu_verify_ssl": s.bdu_verify_ssl,
            }
        )
    elif tab == "mail":
        ctx["form"] = MailSetupForm(
            initial={
                "mail_enabled": s.mail_enabled,
                "mail_provider": s.mail_provider,
                "mail_smtp_host": s.mail_smtp_host,
                "mail_smtp_port": s.mail_smtp_port,
                "mail_smtp_user": s.mail_smtp_user,
                "mail_use_tls": s.mail_use_tls,
                "mail_from_address": s.mail_from_address,
            }
        )
    elif tab == "database":
        ctx["form"] = DatabaseForm(
            initial={
                "db_host": s.db_host,
                "db_port": s.db_port,
                "db_name": s.db_name,
                "db_user": s.db_user,
                "db_sslmode": s.db_sslmode,
            }
        )
    return render(request, "settings/index.html", ctx)


@require_POST
def trigger_sync(request: HttpRequest, source: str) -> HttpResponse:
    if not request.user.has_role(Role.PLATFORM_ADMIN):
        return HttpResponse("Forbidden", status=403)
    from vulndb.apps.vulns.tasks import sync_bdu, sync_kev, sync_nvd

    mapping = {"nvd": sync_nvd, "kev": sync_kev, "bdu": sync_bdu}
    task = mapping.get(source)
    if not task:
        return HttpResponse("Unknown source", status=400)
    task.delay()
    state = SyncState.get_or_create_source(source)
    return render(
        request,
        "partials/sync_status.html",
        {"state": state, "message": f"Синхронизация {source.upper()} запущена"},
    )


@require_GET
def sync_status_partial(request: HttpRequest) -> HttpResponse:
    states = SyncState.objects.all()
    return render(request, "partials/sync_status_list.html", {"states": states})


@require_GET
def system_metrics(request: HttpRequest) -> HttpResponse:
    import psutil

    disks = []
    for p in psutil.disk_partitions(all=False):
        try:
            u = psutil.disk_usage(p.mountpoint)
            disks.append(
                {
                    "mount": p.mountpoint,
                    "total": u.total,
                    "used": u.used,
                    "percent": u.percent,
                }
            )
        except Exception:  # noqa: BLE001
            continue
    vm = psutil.virtual_memory()
    swap = psutil.swap_memory()
    ctx = {
        "cpu_percent": psutil.cpu_percent(interval=None),
        "ram_percent": vm.percent,
        "ram_used": vm.used,
        "ram_total": vm.total,
        "swap_percent": swap.percent,
        "disks": disks,
    }
    if request.headers.get("HX-Request"):
        return render(request, "partials/metrics.html", ctx)
    return JsonResponse(ctx)
