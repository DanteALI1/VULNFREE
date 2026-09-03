# VULNDB — локальная база данных уязвимостей

Каталог уязвимостей (NVD + CISA KEV + БДУ ФСТЭК + локальные ID), заявки на устранение, мастер первичной настройки и уведомления.

**Стек:** Python 3.12, Django 5.1, PostgreSQL 16, Redis 7, Celery, Gunicorn, WhiteNoise, HTMX, Alpine.js (локально в `static/vendor/`).

Лицензионный gate **не используется** (вариант A) — после `/setup/` система полностью рабочая.

## Быстрый старт (Docker)

```bash
cp .env.example .env
# отредактируйте SECRET_KEY
./scripts/install-docker-dev.sh
# или:
docker compose up -d --build
```

Откройте http://localhost:8000/setup/ и пройдите 7 шагов мастера.

Проверка:

```bash
curl -s http://localhost:8000/healthz   # ok
curl -s http://localhost:8000/readyz    # ok (БД + Redis)
```

## Локальная разработка (SQLite)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# DATABASE_URL оставьте пустым → SQLite
python manage.py migrate
python manage.py runserver
```

Для Celery нужен Redis:

```bash
celery -A vulndb worker -l info
celery -A vulndb beat -l info
```

## Миграции

```bash
python manage.py migrate
python manage.py migrate --check
```

## Первый запуск

1. Пройдите `/setup/` (организация → брендинг → БД → источники → admin → почта → finish).
2. Войдите под созданным `platform_admin`.
3. **Настройки → sources → «Синхронизировать NVD»** — KEV подтянется автоматически в конце `sync_nvd`.
4. **«Скачать и разобрать БДУ»** — разбор XLSX ФСТЭК.

## Демо-аккаунты

Мастер создаёт первого суперпользователя с ролью `platform_admin` (логин/пароль задаёте сами на шаге admin).

Дополнительно можно создать пользователей в Django Admin (`/admin/`):

| Роль | Назначение |
|------|------------|
| `platform_admin` | настройки, force_close |
| `analyst` | локальные CVE, заявки, triage/assign/reject |
| `ticket_assignee` | start/wait/resume/resolve |
| `verifier` | confirm_close/reopen |

Пример:

```bash
python manage.py shell -c "
from vulndb.apps.accounts.models import User, Role
# Пароль: используйте сложный (не словарный), например Str0ng-Passw0rd!
User.objects.create_user('analyst', password='Str0ng-Passw0rd!', role=Role.ANALYST, full_name='Аналитик')
User.objects.create_user('assignee', password='Str0ng-Passw0rd!', role=Role.TICKET_ASSIGNEE)
User.objects.create_user('verifier', password='Str0ng-Passw0rd!', role=Role.VERIFIER, is_verifier=True)
"
```

## Восстановление platform_admin

```bash
python manage.py createsuperuser
python manage.py shell -c "
from vulndb.apps.accounts.models import User, Role
u = User.objects.get(username='ВАШ_ЛОГИН')
u.role = Role.PLATFORM_ADMIN
u.is_staff = True
u.is_superuser = True
u.save()
"
```

## Синхронизация

- `sync_nvd` всегда в конце вызывает `sync_kev()` если `kev_enabled=True`.
- `tick_sync_schedules` (каждую минуту) не планирует отдельный KEV, пока включён NVD.
- При ошибке NVD и пустом каталоге засеваются demo CVE.

## Тесты и линт

```bash
ruff check .
ruff format .
pytest
```

## Прод без Docker

См. `scripts/install-prod.sh` (systemd units + nginx, лимит upload 5m для логотипа).

## Структура

```
vulndb/apps/{core,vulns,tickets,accounts,notify,audit}
templates/, static/vendor/{htmx,alpine,fonts}
docker-compose.yml  # web, db, redis, worker, beat
```
