#!/usr/bin/env bash
# Установка VULNDB в systemd + nginx (прод, без Docker)
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/vulndb}"
APP_USER="${APP_USER:-vulndb}"
DOMAIN="${DOMAIN:-vulndb.local}"

echo "Установка в ${APP_DIR} для пользователя ${APP_USER}"

sudo useradd -r -m -d "$APP_DIR" -s /bin/bash "$APP_USER" 2>/dev/null || true
sudo mkdir -p "$APP_DIR" /var/log/vulndb
sudo rsync -a --exclude '.git' --exclude '.venv' ./ "$APP_DIR/"
sudo chown -R "$APP_USER:$APP_USER" "$APP_DIR" /var/log/vulndb

sudo -u "$APP_USER" bash <<EOF
cd "$APP_DIR"
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
if [[ ! -f .env ]]; then cp .env.example .env; fi
python manage.py migrate --noinput
python manage.py collectstatic --noinput
EOF

sudo tee /etc/systemd/system/vulndb.service >/dev/null <<EOF
[Unit]
Description=VULNDB gunicorn
After=network.target postgresql.service redis.service

[Service]
User=${APP_USER}
Group=${APP_USER}
WorkingDirectory=${APP_DIR}
EnvironmentFile=${APP_DIR}/.env
ExecStart=${APP_DIR}/.venv/bin/gunicorn vulndb.wsgi:application --bind 127.0.0.1:8000 --workers 3
Restart=always

[Install]
WantedBy=multi-user.target
EOF

sudo tee /etc/systemd/system/vulndb-worker.service >/dev/null <<EOF
[Unit]
Description=VULNDB Celery worker
After=network.target redis.service

[Service]
User=${APP_USER}
Group=${APP_USER}
WorkingDirectory=${APP_DIR}
EnvironmentFile=${APP_DIR}/.env
ExecStart=${APP_DIR}/.venv/bin/celery -A vulndb worker -l info
Restart=always

[Install]
WantedBy=multi-user.target
EOF

sudo tee /etc/systemd/system/vulndb-beat.service >/dev/null <<EOF
[Unit]
Description=VULNDB Celery beat
After=network.target redis.service

[Service]
User=${APP_USER}
Group=${APP_USER}
WorkingDirectory=${APP_DIR}
EnvironmentFile=${APP_DIR}/.env
ExecStart=${APP_DIR}/.venv/bin/celery -A vulndb beat -l info
Restart=always

[Install]
WantedBy=multi-user.target
EOF

sudo tee /etc/nginx/sites-available/vulndb >/dev/null <<EOF
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
    }
}
EOF

sudo ln -sf /etc/nginx/sites-available/vulndb /etc/nginx/sites-enabled/vulndb
sudo systemctl daemon-reload
sudo systemctl enable --now vulndb vulndb-worker vulndb-beat
sudo nginx -t && sudo systemctl reload nginx
echo "Готово. Откройте http://${DOMAIN}/setup/"
