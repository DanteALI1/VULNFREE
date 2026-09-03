#!/usr/bin/env bash
# Совместимость: полный установщик теперь scripts/install.sh
set -euo pipefail
exec "$(cd "$(dirname "$0")" && pwd)/install.sh" "$@"
