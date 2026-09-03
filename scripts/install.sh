#!/usr/bin/env bash
# =============================================================================
# VULNDB — полный установщик (Ubuntu/Debian)
#
# Что делает:
#   • ставит пакеты (Python 3.12, PostgreSQL 16, Redis, nginx, build-deps)
#   • создаёт системного пользователя и каталоги
#   • создаёт роль и БД PostgreSQL
#   • раскладывает приложение, пишет .env, миграции, static
#   • поднимает systemd (web / worker / beat) + nginx
#   • создаёт учётные записи Django (admin / analyst / assignee / verifier)
#   • печатает все креды и следующие шаги
#
# Запуск (от root, из корня репозитория или по пути к этому файлу):
#   sudo bash scripts/install.sh
#
# Переменные окружения (необязательно):
#   APP_DIR=/opt/vulndb   APP_USER=vulndb   DOMAIN=vulndb.local
#   SKIP_PACKAGES=1       SKIP_NGINX=1      ORG_NAME="Моя организация"
# =============================================================================
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Запустите от root: sudo bash $0" >&2
  exit 1
fi

APP_DIR="${APP_DIR:-/opt/vulndb}"
APP_USER="${APP_USER:-vulndb}"
APP_GROUP="${APP_GROUP:-${APP_USER}}"
DOMAIN="${DOMAIN:-$(hostname -f 2>/dev/null || hostname || echo vulndb.local)}"
ORG_NAME="${ORG_NAME:-VULNDB}"
LOCAL_PREFIX="${LOCAL_PREFIX:-ACME}"
LOG_DIR="${LOG_DIR:-/var/log/vulndb}"
CRED_FILE="${CRED_FILE:-/root/vulndb-credentials.txt}"
SKIP_PACKAGES="${SKIP_PACKAGES:-0}"
SKIP_NGINX="${SKIP_NGINX:-0}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# РЕД ОС / RHEL-семейство — отдельный установщик
if [[ -f /etc/redos-release ]] || grep -qiE 'redos|red os|red-soft' /etc/os-release 2>/dev/null; then
  exec "${SCRIPT_DIR}/install-redos.sh" "$@"
fi

find_repo_root() {
  local cand
  for cand in \
    "${SCRIPT_DIR}/.." \
    "${PWD}" \
    "${SCRIPT_DIR}" \
    /opt/vulndb \
    "${APP_DIR}"; do
    if [[ -f "${cand}/requirements.txt" && -f "${cand}/manage.py" ]]; then
      (cd "${cand}" && pwd)
      return 0
    fi
  done
  return 1
}

REPO_ROOT="$(find_repo_root)" || {
  echo "Не найден исходный код VULNDB (нет requirements.txt и manage.py)." >&2
  echo "Скрипт нельзя запускать отдельно. Сначала клонируйте репозиторий:" >&2
  echo "  git clone https://github.com/DanteALI1/VULNFREE.git" >&2
  echo "  cd VULNFREE" >&2
  echo "  sudo bash scripts/install.sh" >&2
  exit 1
}
echo "Исходники: ${REPO_ROOT}"

umask 077

rand_alnum() {
  local n="${1:-24}"
  python3 - <<PY
import secrets, string
print("".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(${n})))
PY
}

rand_secret() {
  python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(48))
PY
}

rand_password() {
  # Сложный пароль, проходит Django validators (длина, не словарный)
  python3 - <<'PY'
import secrets, string
alphabet = string.ascii_letters + string.digits + "!@#%^*_+-="
while True:
    pwd = "".join(secrets.choice(alphabet) for _ in range(20))
    if (any(c.islower() for c in pwd) and any(c.isupper() for c in pwd)
            and any(c.isdigit() for c in pwd) and any(c in "!@#%^*_+-=" for c in pwd)):
        print(pwd)
        break
PY
}

echo "=============================================="
echo " VULNDB — полная установка"
echo " Каталог:  ${APP_DIR}"
echo " Пользователь ОС: ${APP_USER}"
echo " Домен:    ${DOMAIN}"
echo "=============================================="

# --- пакеты -----------------------------------------------------------------
if [[ "${SKIP_PACKAGES}" != "1" ]]; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  apt-get install -y -qq \
    python3 python3-venv python3-pip python3-dev \
    build-essential libpq-dev libffi-dev libssl-dev \
    postgresql postgresql-contrib \
    redis-server \
    nginx \
    rsync curl sudo
  # python3.12-venv на Ubuntu 24.04, если доступен
  apt-get install -y -qq python3.12-venv 2>/dev/null || true
fi

systemctl enable --now postgresql redis-server 2>/dev/null || true
systemctl start postgresql redis-server 2>/dev/null || true

# --- системный пользователь и каталоги --------------------------------------
if ! id -u "${APP_USER}" >/dev/null 2>&1; then
  useradd --system --create-home --home-dir "${APP_DIR}" --shell /bin/bash "${APP_USER}"
  echo "Создан пользователь ОС: ${APP_USER}"
else
  echo "Пользователь ОС уже есть: ${APP_USER}"
fi

mkdir -p \
  "${APP_DIR}" \
  "${APP_DIR}/media/branding" \
  "${APP_DIR}/staticfiles" \
  "${LOG_DIR}" \
  /etc/vulndb

# --- раскладка кода ---------------------------------------------------------
rsync -a --delete \
  --exclude '.git' \
  --exclude '.venv' \
  --exclude 'db.sqlite3' \
  --exclude '__pycache__' \
  --exclude '.pytest_cache' \
  --exclude '.ruff_cache' \
  --exclude 'staticfiles' \
  --exclude 'media' \
  "${REPO_ROOT}/" "${APP_DIR}/"

if [[ ! -f "${APP_DIR}/requirements.txt" || ! -f "${APP_DIR}/manage.py" ]]; then
  echo "Копирование в ${APP_DIR} не удалось: нет requirements.txt / manage.py" >&2
  echo "Источник был: ${REPO_ROOT}" >&2
  ls -la "${REPO_ROOT}" >&2 || true
  exit 1
fi

# --- PostgreSQL: роль + БД --------------------------------------------------
DB_NAME="vulndb"
DB_USER="vulndb"
if [[ -f "${APP_DIR}/.env" ]] && grep -q '^POSTGRES_PASSWORD=.\+' "${APP_DIR}/.env"; then
  DB_PASS="$(grep '^POSTGRES_PASSWORD=' "${APP_DIR}/.env" | head -1 | cut -d= -f2-)"
else
  DB_PASS="$(rand_alnum 28)"
fi
DB_PASS_SQL="${DB_PASS//\'/\'\'}"

sudo -u postgres psql -v ON_ERROR_STOP=1 <<SQL
DO \$\$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '${DB_USER}') THEN
    CREATE ROLE ${DB_USER} LOGIN PASSWORD '${DB_PASS_SQL}';
  ELSE
    ALTER ROLE ${DB_USER} WITH LOGIN PASSWORD '${DB_PASS_SQL}';
  END IF;
END
\$\$;
SELECT 'CREATE DATABASE ${DB_NAME} OWNER ${DB_USER}'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '${DB_NAME}')
\\gexec
GRANT ALL PRIVILEGES ON DATABASE ${DB_NAME} TO ${DB_USER};
SQL

sudo -u postgres psql -d "${DB_NAME}" -v ON_ERROR_STOP=1 <<SQL
GRANT ALL ON SCHEMA public TO ${DB_USER};
ALTER SCHEMA public OWNER TO ${DB_USER};
SQL

# --- .env -------------------------------------------------------------------
if [[ -f "${APP_DIR}/.env" ]] && grep -q '^SECRET_KEY=.\+' "${APP_DIR}/.env"; then
  SECRET_KEY="$(grep '^SECRET_KEY=' "${APP_DIR}/.env" | head -1 | cut -d= -f2-)"
else
  SECRET_KEY="$(rand_secret)"
fi

LAN_HOSTS="$(hostname -I 2>/dev/null | xargs | tr ' ' ',' || true)"
ALLOWED_HOSTS_VALUE="${DOMAIN},localhost,127.0.0.1"
if [[ -n "${LAN_HOSTS}" ]]; then
  ALLOWED_HOSTS_VALUE="${ALLOWED_HOSTS_VALUE},${LAN_HOSTS}"
fi

cat > "${APP_DIR}/.env" <<EOF
# Сгенерировано scripts/install.sh — не коммитить
SECRET_KEY=${SECRET_KEY}
DEBUG=False
ALLOWED_HOSTS=${ALLOWED_HOSTS_VALUE}
ALLOW_LAN_HOSTS=True
DATABASE_URL=postgres://${DB_USER}:${DB_PASS}@127.0.0.1:5432/${DB_NAME}
REDIS_URL=redis://127.0.0.1:6379/0
POSTGRES_PASSWORD=${DB_PASS}
CSRF_COOKIE_SECURE=False
SESSION_COOKIE_SECURE=False
NVD_API_KEY=
EMAIL_HOST=
EMAIL_PORT=587
EMAIL_HOST_USER=
EMAIL_HOST_PASSWORD=
EMAIL_USE_TLS=True
DEFAULT_FROM_EMAIL=vulndb@${DOMAIN}
TELEGRAM_BOT_TOKEN=
EOF
chmod 640 "${APP_DIR}/.env"

# --- venv + приложение ------------------------------------------------------
if [[ ! -d "${APP_DIR}/.venv" ]]; then
  sudo -u "${APP_USER}" python3 -m venv "${APP_DIR}/.venv"
fi
chown -R "${APP_USER}:${APP_GROUP}" "${APP_DIR}" "${LOG_DIR}"
chmod 640 "${APP_DIR}/.env"
# root должен читать EnvironmentFile
chgrp "${APP_GROUP}" "${APP_DIR}/.env"

sudo -u "${APP_USER}" bash -c "
  set -euo pipefail
  cd '${APP_DIR}'
  . .venv/bin/activate
  pip install -q -U pip
  pip install -q -r '${APP_DIR}/requirements.txt'
  python manage.py migrate --noinput
  python manage.py collectstatic --noinput
"

# --- Django-пользователи и завершение setup --------------------------------
ADMIN_USER="admin"
ANALYST_USER="analyst"
ASSIGNEE_USER="assignee"
VERIFIER_USER="verifier"

if [[ -f "${CRED_FILE}" ]] && grep -q "^ADMIN_PASSWORD=" "${CRED_FILE}"; then
  ADMIN_PASS="$(grep '^ADMIN_PASSWORD=' "${CRED_FILE}" | head -1 | cut -d= -f2-)"
  ANALYST_PASS="$(grep '^ANALYST_PASSWORD=' "${CRED_FILE}" | head -1 | cut -d= -f2-)"
  ASSIGNEE_PASS="$(grep '^ASSIGNEE_PASSWORD=' "${CRED_FILE}" | head -1 | cut -d= -f2-)"
  VERIFIER_PASS="$(grep '^VERIFIER_PASSWORD=' "${CRED_FILE}" | head -1 | cut -d= -f2-)"
else
  ADMIN_PASS="$(rand_password)"
  ANALYST_PASS="$(rand_password)"
  VERIFIER_PASS="$(rand_password)"
  ASSIGNEE_PASS="$(rand_password)"
fi

export DJANGO_BOOTSTRAP_ADMIN_USER="${ADMIN_USER}"
export DJANGO_BOOTSTRAP_ADMIN_PASS="${ADMIN_PASS}"
export DJANGO_BOOTSTRAP_ANALYST_PASS="${ANALYST_PASS}"
export DJANGO_BOOTSTRAP_ASSIGNEE_PASS="${ASSIGNEE_PASS}"
export DJANGO_BOOTSTRAP_VERIFIER_PASS="${VERIFIER_PASS}"
export DJANGO_BOOTSTRAP_ORG="${ORG_NAME}"
export DJANGO_BOOTSTRAP_PREFIX="${LOCAL_PREFIX}"

# передаём секреты только через env файла, не в argv
# Файл в APP_DIR: /tmp недоступен пользователю приложения (600 root)
BOOT_ENV="${APP_DIR}/.bootstrap.env"
cat > "${BOOT_ENV}" <<EOF
DJANGO_BOOTSTRAP_ADMIN_USER=${ADMIN_USER}
DJANGO_BOOTSTRAP_ADMIN_PASS=${ADMIN_PASS}
DJANGO_BOOTSTRAP_ANALYST_USER=${ANALYST_USER}
DJANGO_BOOTSTRAP_ANALYST_PASS=${ANALYST_PASS}
DJANGO_BOOTSTRAP_ASSIGNEE_USER=${ASSIGNEE_USER}
DJANGO_BOOTSTRAP_ASSIGNEE_PASS=${ASSIGNEE_PASS}
DJANGO_BOOTSTRAP_VERIFIER_USER=${VERIFIER_USER}
DJANGO_BOOTSTRAP_VERIFIER_PASS=${VERIFIER_PASS}
DJANGO_BOOTSTRAP_ORG=${ORG_NAME}
DJANGO_BOOTSTRAP_PREFIX=${LOCAL_PREFIX}
EOF
chown "${APP_USER}:${APP_GROUP}" "${BOOT_ENV}"
chmod 600 "${BOOT_ENV}"

sudo -u "${APP_USER}" bash -c "
  set -euo pipefail
  cd '${APP_DIR}'
  set -a
  . '${APP_DIR}/.env'
  . '${BOOT_ENV}'
  set +a
  . .venv/bin/activate
  python manage.py bootstrap_install
"
rm -f "${BOOT_ENV}"

# --- systemd ----------------------------------------------------------------
cat > /etc/systemd/system/vulndb.service <<EOF
[Unit]
Description=VULNDB gunicorn
After=network.target postgresql.service redis-server.service
Wants=postgresql.service redis-server.service

[Service]
User=${APP_USER}
Group=${APP_GROUP}
WorkingDirectory=${APP_DIR}
EnvironmentFile=${APP_DIR}/.env
ExecStart=${APP_DIR}/.venv/bin/gunicorn vulndb.wsgi:application --bind 127.0.0.1:8000 --workers 3 --access-logfile ${LOG_DIR}/gunicorn-access.log --error-logfile ${LOG_DIR}/gunicorn-error.log
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

cat > /etc/systemd/system/vulndb-worker.service <<EOF
[Unit]
Description=VULNDB Celery worker
After=network.target redis-server.service postgresql.service

[Service]
User=${APP_USER}
Group=${APP_GROUP}
WorkingDirectory=${APP_DIR}
EnvironmentFile=${APP_DIR}/.env
ExecStart=${APP_DIR}/.venv/bin/celery -A vulndb worker -l info
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

cat > /etc/systemd/system/vulndb-beat.service <<EOF
[Unit]
Description=VULNDB Celery beat
After=network.target redis-server.service postgresql.service

[Service]
User=${APP_USER}
Group=${APP_GROUP}
WorkingDirectory=${APP_DIR}
EnvironmentFile=${APP_DIR}/.env
ExecStart=${APP_DIR}/.venv/bin/celery -A vulndb beat -l info
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now vulndb vulndb-worker vulndb-beat

# --- nginx ------------------------------------------------------------------
if [[ "${SKIP_NGINX}" != "1" ]]; then
  cat > /etc/nginx/sites-available/vulndb <<EOF
server {
    listen 80;
    server_name ${DOMAIN};

    client_max_body_size 5m;

    location /static/ {
        alias ${APP_DIR}/staticfiles/;
    }
    location /media/ {
        alias ${APP_DIR}/media/;
    }
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 120s;
    }
}
EOF
  ln -sfn /etc/nginx/sites-available/vulndb /etc/nginx/sites-enabled/vulndb
  rm -f /etc/nginx/sites-enabled/default
  nginx -t
  systemctl enable --now nginx
  systemctl reload nginx
fi

# --- файл кредов ------------------------------------------------------------
mkdir -p "$(dirname "${CRED_FILE}")"
cat > "${CRED_FILE}" <<EOF
# VULNDB credentials — $(date -Is)
# Права 600. Храните в секрете. После смены паролей удалите этот файл.

URL=http://${DOMAIN}/
ADMIN_URL=http://${DOMAIN}/admin/

# --- ОС ---
OS_USER=${APP_USER}
APP_DIR=${APP_DIR}
LOG_DIR=${LOG_DIR}

# --- PostgreSQL ---
DB_HOST=127.0.0.1
DB_PORT=5432
DB_NAME=${DB_NAME}
DB_USER=${DB_USER}
POSTGRES_PASSWORD=${DB_PASS}
DATABASE_URL=postgres://${DB_USER}:${DB_PASS}@127.0.0.1:5432/${DB_NAME}

# --- Django ---
SECRET_KEY=${SECRET_KEY}

ADMIN_USER=${ADMIN_USER}
ADMIN_PASSWORD=${ADMIN_PASS}
ADMIN_ROLE=platform_admin

ANALYST_USER=${ANALYST_USER}
ANALYST_PASSWORD=${ANALYST_PASS}
ANALYST_ROLE=analyst

ASSIGNEE_USER=${ASSIGNEE_USER}
ASSIGNEE_PASSWORD=${ASSIGNEE_PASS}
ASSIGNEE_ROLE=ticket_assignee

VERIFIER_USER=${VERIFIER_USER}
VERIFIER_PASSWORD=${VERIFIER_PASS}
VERIFIER_ROLE=verifier
EOF
chmod 600 "${CRED_FILE}"
cp -a "${CRED_FILE}" "${APP_DIR}/CREDENTIALS.txt"
chown root:root "${APP_DIR}/CREDENTIALS.txt"
chmod 600 "${APP_DIR}/CREDENTIALS.txt"

# копия для пользователя приложения (чтобы прочитать sudo -u vulndb)
install -m 600 -o root -g root "${CRED_FILE}" /etc/vulndb/credentials.txt

sleep 1
HEALTH="$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/healthz || true)"
READY="$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/readyz || true)"

cat <<EOF

================================================================
 VULNDB установлен
================================================================

 URL:              http://${DOMAIN}/
 Вход:             http://${DOMAIN}/accounts/login/
 Django Admin:     http://${DOMAIN}/admin/
 healthz / readyz: HTTP ${HEALTH} / ${READY}  (ожидается 200 / 200)

 Креды сохранены в:
   ${CRED_FILE}
   /etc/vulndb/credentials.txt
   ${APP_DIR}/CREDENTIALS.txt   (права 600, только root)

----------------------------------------------------------------
 СИСТЕМА
----------------------------------------------------------------
 Пользователь ОС:  ${APP_USER}
 Каталог:          ${APP_DIR}
 Логи:             ${LOG_DIR}

----------------------------------------------------------------
 БАЗА ДАННЫХ PostgreSQL
----------------------------------------------------------------
 Хост:             127.0.0.1:5432
 БД:               ${DB_NAME}
 Пользователь:     ${DB_USER}
 Пароль:           ${DB_PASS}

----------------------------------------------------------------
 DJANGO (вход в веб)
----------------------------------------------------------------
 ${ADMIN_USER}     /  ${ADMIN_PASS}     роль platform_admin
 ${ANALYST_USER}   /  ${ANALYST_PASS}   роль analyst
 ${ASSIGNEE_USER}  /  ${ASSIGNEE_PASS}  роль ticket_assignee
 ${VERIFIER_USER}  /  ${VERIFIER_PASS}  роль verifier

 SECRET_KEY записан в ${APP_DIR}/.env

----------------------------------------------------------------
 ДАЛЬНЕЙШИЕ ДЕЙСТВИЯ
----------------------------------------------------------------
 1. Откройте http://${DOMAIN}/accounts/login/ и войдите как ${ADMIN_USER}.
    Мастер /setup/ уже завершён установщиком.

 2. Настройки → sources:
      «Синхронизировать NVD»  (KEV подтянется автоматически)
      «Скачать и разобрать БДУ»

 3. Настройки → org / branding / mail / telegram — укажите организацию,
    логотип, SMTP и токен Telegram (по желанию).

 4. Для HTTPS поставьте сертификат (certbot) и в ${APP_DIR}/.env выставьте:
      CSRF_COOKIE_SECURE=True
      SESSION_COOKIE_SECURE=True
    затем:  systemctl restart vulndb vulndb-worker vulndb-beat

 5. Смените пароли из этого отчёта и удалите файлы кредов:
      shred -u ${CRED_FILE} /etc/vulndb/credentials.txt ${APP_DIR}/CREDENTIALS.txt

 6. Полезные команды:
      systemctl status vulndb vulndb-worker vulndb-beat
      journalctl -u vulndb -f
      sudo -u ${APP_USER} ${APP_DIR}/.venv/bin/python ${APP_DIR}/manage.py createsuperuser

================================================================
EOF
