#!/usr/bin/env bash
# =============================================================================
# VULNDB — полный установщик для РЕД ОС 8 / РЕД ОС 7.3+
# (семейство RHEL: dnf/yum, systemd, nginx, firewalld, SELinux)
#
# Что делает:
#   • ставит пакеты (Python 3.10+, PostgreSQL, Redis, nginx, gcc, libpq)
#   • создаёт системного пользователя и каталоги
#   • инициализирует PostgreSQL, создаёт роль и БД
#   • настраивает pg_hba (пароль с localhost), SELinux, firewalld
#   • раскладывает приложение, пишет .env, миграции, static
#   • поднимает systemd (web / worker / beat) + nginx
#   • создаёт учётные записи Django и печатает все креды
#
# Запуск (от root):
#   sudo bash scripts/install-redos.sh
#
# Переменные: APP_DIR APP_USER DOMAIN ORG_NAME SKIP_PACKAGES SKIP_NGINX SKIP_FIREWALL
# =============================================================================
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Запустите от root: sudo bash $0" >&2
  exit 1
fi

if [[ ! -f /etc/redos-release ]] && ! grep -qiE 'redos|red os|red-soft' /etc/os-release 2>/dev/null; then
  echo "Внимание: /etc/os-release не похож на РЕД ОС. Продолжаю как RHEL-семейство." >&2
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
SKIP_FIREWALL="${SKIP_FIREWALL:-0}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

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
  echo "  sudo bash scripts/install-redos.sh" >&2
  exit 1
}
echo "Исходники: ${REPO_ROOT}"

umask 077

if command -v dnf >/dev/null 2>&1; then
  PKG="dnf"
  PKG_INSTALL=(dnf install -y)
  PKG_UPDATE=(dnf makecache)
else
  PKG="yum"
  PKG_INSTALL=(yum install -y)
  PKG_UPDATE=(yum makecache)
fi

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
echo " VULNDB — установка на РЕД ОС"
echo " Каталог:  ${APP_DIR}"
echo " Пользователь ОС: ${APP_USER}"
echo " Домен:    ${DOMAIN}"
echo " Пакетный менеджер: ${PKG}"
echo "=============================================="

# --- пакеты -----------------------------------------------------------------
if [[ "${SKIP_PACKAGES}" != "1" ]]; then
  "${PKG_UPDATE[@]}" -q || true
  "${PKG_INSTALL[@]}" \
    python3 python3-pip python3-devel \
    gcc gcc-c++ make \
    libffi-devel openssl-devel zlib-devel libjpeg-turbo-devel \
    rsync curl sudo tar \
    nginx redis \
    postgresql postgresql-server postgresql-contrib \
    policycoreutils-python-utils || true

  # libpq / заголовки для psycopg (имя пакета зависит от релиза)
  "${PKG_INSTALL[@]}" libpq-devel 2>/dev/null \
    || "${PKG_INSTALL[@]}" postgresql-devel 2>/dev/null \
    || "${PKG_INSTALL[@]}" libpqxx-devel 2>/dev/null \
    || true

  # Python 3.11/3.12, если есть в репозитории (Django 5.1 требует ≥ 3.10)
  "${PKG_INSTALL[@]}" python3.12 python3.12-devel python3.12-pip 2>/dev/null || true
  "${PKG_INSTALL[@]}" python3.11 python3.11-devel python3.11-pip 2>/dev/null || true
fi

PYTHON_BIN="$(command -v python3.12 || command -v python3.11 || command -v python3.10 || command -v python3)"
PY_VER="$("${PYTHON_BIN}" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
PY_MAJ="${PY_VER%%.*}"
PY_MIN="${PY_VER#*.}"
if [[ "${PY_MAJ}" -lt 3 || "${PY_MIN}" -lt 10 ]]; then
  echo "Нужен Python ≥ 3.10 (Django 5.1). Найден ${PYTHON_BIN} (${PY_VER})." >&2
  echo "Установите python3.11 или python3.12 из репозитория РЕД ОС 8 и повторите." >&2
  exit 1
fi
echo "Интерпретатор: ${PYTHON_BIN} (${PY_VER})"

# --- Redis ------------------------------------------------------------------
systemctl enable --now redis 2>/dev/null || systemctl enable --now redis-server 2>/dev/null || true
REDIS_UNIT="redis"
systemctl is-active --quiet redis && REDIS_UNIT="redis" || true
systemctl is-active --quiet redis-server && REDIS_UNIT="redis-server" || true

# --- PostgreSQL initdb + сервис ---------------------------------------------
PG_UNIT="postgresql"
if systemctl list-unit-files | grep -q '^postgresql-16.service'; then
  PG_UNIT="postgresql-16"
  if [[ ! -d /var/lib/pgsql/16/data/base ]]; then
    /usr/pgsql-16/bin/postgresql-16-setup initdb || true
  fi
elif [[ ! -f /var/lib/pgsql/data/PG_VERSION ]]; then
  if command -v postgresql-setup >/dev/null 2>&1; then
    postgresql-setup --initdb 2>/dev/null || postgresql-setup initdb 2>/dev/null || true
  fi
fi
systemctl enable --now "${PG_UNIT}"

PG_HBA=""
for cand in \
  /var/lib/pgsql/data/pg_hba.conf \
  /var/lib/pgsql/16/data/pg_hba.conf \
  /var/lib/pgsql/15/data/pg_hba.conf; do
  if [[ -f "${cand}" ]]; then
    PG_HBA="${cand}"
    break
  fi
done
if [[ -n "${PG_HBA}" ]]; then
  if grep -qE '127\.0\.0\.1/32[[:space:]]+(ident|peer|trust)' "${PG_HBA}"; then
    sed -i -E 's/(127\.0\.0\.1\/32[[:space:]]+)(ident|peer|trust)/\1scram-sha-256/' "${PG_HBA}" || true
    sed -i -E 's/(::1\/128[[:space:]]+)(ident|peer|trust)/\1scram-sha-256/' "${PG_HBA}" || true
    # если scram не поддерживается старым PG — md5
    systemctl reload "${PG_UNIT}" 2>/dev/null || systemctl restart "${PG_UNIT}"
  fi
fi

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
# Сгенерировано scripts/install-redos.sh — не коммитить
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
  sudo -u "${APP_USER}" "${PYTHON_BIN}" -m venv "${APP_DIR}/.venv" \
    || sudo -u "${APP_USER}" virtualenv -p "${PYTHON_BIN}" "${APP_DIR}/.venv"
fi
chown -R "${APP_USER}:${APP_GROUP}" "${APP_DIR}" "${LOG_DIR}"
chmod 640 "${APP_DIR}/.env"
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

# Файл в APP_DIR: /tmp на РЕД ОС недоступен пользователю vulndb (600 root + sticky)
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
After=network.target ${PG_UNIT}.service ${REDIS_UNIT}.service
Wants=${PG_UNIT}.service ${REDIS_UNIT}.service

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
After=network.target ${REDIS_UNIT}.service ${PG_UNIT}.service

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
After=network.target ${REDIS_UNIT}.service ${PG_UNIT}.service

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

# --- nginx (РЕД ОС: /etc/nginx/conf.d, без sites-available) -----------------
if [[ "${SKIP_NGINX}" != "1" ]]; then
  mkdir -p /etc/nginx/conf.d
  cat > /etc/nginx/conf.d/vulndb.conf <<EOF
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
  nginx -t
  systemctl enable --now nginx
  systemctl reload nginx
fi

# --- SELinux ----------------------------------------------------------------
if command -v getenforce >/dev/null 2>&1 && [[ "$(getenforce)" != "Disabled" ]]; then
  setsebool -P httpd_can_network_connect 1 2>/dev/null || true
  if command -v semanage >/dev/null 2>&1; then
    semanage fcontext -a -t httpd_sys_content_t "${APP_DIR}/staticfiles(/.*)?" 2>/dev/null || true
    semanage fcontext -a -t httpd_sys_rw_content_t "${APP_DIR}/media(/.*)?" 2>/dev/null || true
  fi
  restorecon -Rv "${APP_DIR}/staticfiles" "${APP_DIR}/media" >/dev/null 2>&1 || true
fi

# --- firewalld --------------------------------------------------------------
if [[ "${SKIP_FIREWALL}" != "1" ]] && command -v firewall-cmd >/dev/null 2>&1; then
  if systemctl is-active --quiet firewalld; then
    firewall-cmd --permanent --add-service=http || true
    firewall-cmd --reload || true
  fi
fi

# --- креды ------------------------------------------------------------------
mkdir -p "$(dirname "${CRED_FILE}")"
cat > "${CRED_FILE}" <<EOF
# VULNDB credentials (РЕД ОС) — $(date -Is)
# Права 600. Храните в секрете.

URL=http://${DOMAIN}/
ADMIN_URL=http://${DOMAIN}/admin/

OS_USER=${APP_USER}
APP_DIR=${APP_DIR}
LOG_DIR=${LOG_DIR}

DB_HOST=127.0.0.1
DB_PORT=5432
DB_NAME=${DB_NAME}
DB_USER=${DB_USER}
POSTGRES_PASSWORD=${DB_PASS}
DATABASE_URL=postgres://${DB_USER}:${DB_PASS}@127.0.0.1:5432/${DB_NAME}

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
install -m 600 -o root -g root "${CRED_FILE}" "${APP_DIR}/CREDENTIALS.txt"
install -m 600 -o root -g root "${CRED_FILE}" /etc/vulndb/credentials.txt

sleep 1
HEALTH="$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/healthz || true)"
READY="$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/readyz || true)"

cat <<EOF

================================================================
 VULNDB установлен на РЕД ОС
================================================================

 URL:              http://${DOMAIN}/
 Вход:             http://${DOMAIN}/accounts/login/
 Django Admin:     http://${DOMAIN}/admin/
 healthz / readyz: HTTP ${HEALTH} / ${READY}  (ожидается 200 / 200)

 Креды:
   ${CRED_FILE}
   /etc/vulndb/credentials.txt
   ${APP_DIR}/CREDENTIALS.txt

----------------------------------------------------------------
 СИСТЕМА
----------------------------------------------------------------
 Пользователь ОС:  ${APP_USER}
 Каталог:          ${APP_DIR}
 Логи:             ${LOG_DIR}
 PostgreSQL unit:  ${PG_UNIT}
 Redis unit:       ${REDIS_UNIT}

----------------------------------------------------------------
 БАЗА ДАННЫХ PostgreSQL
----------------------------------------------------------------
 Хост:             127.0.0.1:5432
 БД:               ${DB_NAME}
 Пользователь:     ${DB_USER}
 Пароль:           ${DB_PASS}

----------------------------------------------------------------
 DJANGO
----------------------------------------------------------------
 ${ADMIN_USER}     /  ${ADMIN_PASS}     роль platform_admin
 ${ANALYST_USER}   /  ${ANALYST_PASS}   роль analyst
 ${ASSIGNEE_USER}  /  ${ASSIGNEE_PASS}  роль ticket_assignee
 ${VERIFIER_USER}  /  ${VERIFIER_PASS}  роль verifier

----------------------------------------------------------------
 ДАЛЬНЕЙШИЕ ДЕЙСТВИЯ
----------------------------------------------------------------
 1. Откройте http://${DOMAIN}/accounts/login/ и войдите как ${ADMIN_USER}.
    Мастер /setup/ уже завершён.

 2. Настройки → sources:
      «Синхронизировать NVD»  (KEV подтянется автоматически)
      «Скачать и разобрать БДУ»

 3. Настройки → org / branding / mail / telegram.

 4. HTTPS: firewall-cmd --permanent --add-service=https && firewall-cmd --reload
    В ${APP_DIR}/.env: CSRF_COOKIE_SECURE=True и SESSION_COOKIE_SECURE=True
    systemctl restart vulndb vulndb-worker vulndb-beat

 5. Если nginx отдаёт 403 на static/media — SELinux:
      restorecon -Rv ${APP_DIR}/staticfiles ${APP_DIR}/media
      setsebool -P httpd_can_network_connect 1

 6. Смените пароли и удалите файлы кредов:
      shred -u ${CRED_FILE} /etc/vulndb/credentials.txt ${APP_DIR}/CREDENTIALS.txt

 7. Команды:
      systemctl status vulndb vulndb-worker vulndb-beat ${PG_UNIT} ${REDIS_UNIT} nginx
      journalctl -u vulndb -f

================================================================
EOF
