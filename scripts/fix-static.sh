#!/usr/bin/env bash
# =============================================================================
# VULNDB — починить стили на уже установленной системе
#
# Симптом: дашборд как «голый» HTML (чёрный serif, синие ссылки), без сайдбара.
# Причина: nginx читает /opt/vulndb/staticfiles, но каталог — home vulndb (700)
# и/или SELinux. CSS есть (collectstatic отработал), браузер его не получает.
#
#   sudo bash scripts/fix-static.sh
#   sudo APP_DIR=/opt/vulndb bash /opt/vulndb/scripts/fix-static.sh
# =============================================================================
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Запустите от root: sudo bash $0" >&2
  exit 1
fi

APP_DIR="${APP_DIR:-/opt/vulndb}"
APP_USER="${APP_USER:-vulndb}"
APP_GROUP="${APP_GROUP:-${APP_USER}}"

if [[ ! -d "${APP_DIR}" ]]; then
  echo "Нет каталога ${APP_DIR}" >&2
  exit 1
fi

echo "Права на ${APP_DIR} (чтобы nginx мог пройти к staticfiles)..."
chmod 755 "${APP_DIR}"
mkdir -p "${APP_DIR}/staticfiles" "${APP_DIR}/media"
if [[ -d "${APP_DIR}/staticfiles" ]]; then
  find "${APP_DIR}/staticfiles" -type d -exec chmod 755 {} +
  find "${APP_DIR}/staticfiles" -type f -exec chmod 644 {} +
fi
if [[ -d "${APP_DIR}/media" ]]; then
  find "${APP_DIR}/media" -type d -exec chmod 755 {} +
  find "${APP_DIR}/media" -type f -exec chmod 644 {} +
fi
if [[ -f "${APP_DIR}/.env" ]]; then
  chmod 640 "${APP_DIR}/.env"
  chgrp "${APP_GROUP}" "${APP_DIR}/.env" || true
fi

if [[ ! -f "${APP_DIR}/staticfiles/css/app.css" ]]; then
  echo "Нет ${APP_DIR}/staticfiles/css/app.css — запускаю collectstatic..."
  if [[ -x "${APP_DIR}/.venv/bin/python" ]]; then
    sudo -u "${APP_USER}" bash -c "
      set -euo pipefail
      cd '${APP_DIR}'
      set -a
      . '${APP_DIR}/.env'
      set +a
      . .venv/bin/activate
      python manage.py collectstatic --noinput
    "
    find "${APP_DIR}/staticfiles" -type d -exec chmod 755 {} +
    find "${APP_DIR}/staticfiles" -type f -exec chmod 644 {} +
  else
    echo "Нет venv, collectstatic пропущен." >&2
  fi
fi

write_nginx_proxy() {
  local conf="$1"
  local domain
  domain="$(hostname -f 2>/dev/null || hostname || echo vulndb.local)"
  cat > "${conf}" <<EOF
server {
    listen 80;
    server_name ${domain};

    client_max_body_size 5m;

    # Статику отдаёт gunicorn (WhiteNoise), не файлы с диска.
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 120s;
    }
}
EOF
}

if [[ -f /etc/nginx/conf.d/vulndb.conf ]]; then
  echo "nginx: /etc/nginx/conf.d/vulndb.conf → proxy на gunicorn (без alias static)"
  write_nginx_proxy /etc/nginx/conf.d/vulndb.conf
elif [[ -f /etc/nginx/sites-available/vulndb ]]; then
  echo "nginx: /etc/nginx/sites-available/vulndb → proxy на gunicorn"
  write_nginx_proxy /etc/nginx/sites-available/vulndb
  ln -sfn /etc/nginx/sites-available/vulndb /etc/nginx/sites-enabled/vulndb
fi

if command -v getenforce >/dev/null 2>&1 && [[ "$(getenforce)" != "Disabled" ]]; then
  echo "SELinux: контекст httpd для staticfiles/media..."
  setsebool -P httpd_can_network_connect 1 2>/dev/null || true
  if command -v semanage >/dev/null 2>&1; then
    semanage fcontext -a -t httpd_sys_content_t "${APP_DIR}/staticfiles(/.*)?" 2>/dev/null || true
    semanage fcontext -a -t httpd_sys_rw_content_t "${APP_DIR}/media(/.*)?" 2>/dev/null || true
  fi
  restorecon -Rv "${APP_DIR}/staticfiles" "${APP_DIR}/media" >/dev/null 2>&1 || true
fi

if command -v nginx >/dev/null 2>&1; then
  nginx -t
  systemctl reload nginx || systemctl restart nginx
fi
systemctl reload vulndb 2>/dev/null || systemctl restart vulndb || true

echo
echo "Проверка CSS:"
for url in \
  "http://127.0.0.1:8000/static/css/app.css" \
  "http://127.0.0.1/static/css/app.css"; do
  code="$(curl -s -o /dev/null -w '%{http_code}' "${url}" || true)"
  echo "  ${url}  →  HTTP ${code}  (нужно 200)"
done

if [[ -f "${APP_DIR}/staticfiles/css/app.css" ]]; then
  echo "  файл на диске: ${APP_DIR}/staticfiles/css/app.css  ($(stat -c%s "${APP_DIR}/staticfiles/css/app.css") байт)"
fi

echo
echo "Обновите страницу в браузере с очисткой кэша (Ctrl+F5)."
