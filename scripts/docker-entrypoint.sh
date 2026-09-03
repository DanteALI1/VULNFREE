#!/usr/bin/env bash
set -euo pipefail

echo "Waiting for database..."
python - <<'PY'
import os, time
url = os.environ.get("DATABASE_URL", "")
if not url:
    raise SystemExit(0)
import psycopg
from urllib.parse import urlparse
p = urlparse(url)
for i in range(60):
    try:
        with psycopg.connect(
            dbname=p.path.lstrip("/"),
            user=p.username,
            password=p.password,
            host=p.hostname,
            port=p.port or 5432,
            connect_timeout=3,
        ) as conn:
            conn.execute("SELECT 1")
        print("DB ready")
        break
    except Exception as e:
        print(f"DB not ready ({e}), retry...")
        time.sleep(2)
else:
    raise SystemExit("Database not available")
PY

python manage.py migrate --noinput
python manage.py collectstatic --noinput
exec "$@"
