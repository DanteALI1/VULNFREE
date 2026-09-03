#!/usr/bin/env bash
# Быстрый старт VULNDB через docker compose
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ ! -f .env ]]; then
  cp .env.example .env
  # сгенерировать SECRET_KEY
  SECRET=$(python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(48))
PY
)
  sed -i "s|^SECRET_KEY=.*|SECRET_KEY=${SECRET}|" .env
  echo "DEBUG=False" >> .env || true
fi

docker compose up -d --build
echo "VULNDB поднят: http://localhost:8000/setup/"
echo "Проверка: curl -s http://localhost:8000/healthz"
