#!/usr/bin/env bash
# Reconstruye el corpus y el índice tras actualizar AnyLogic.
# Es un alias de install.sh, que ya es idempotente: no vuelve a descargar lo que
# ya está en raw/ y regenera corpus e índice desde cero.
#
# Uso: ./update.sh [--api-only | --skip-crawl | --no-images | --skip-api]
set -euo pipefail
cd "$(dirname "$0")"
exec ./install.sh "$@"
