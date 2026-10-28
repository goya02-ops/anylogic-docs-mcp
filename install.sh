#!/usr/bin/env bash
#
# Instala anylogic-docs-mcp: entorno Python, corpus de documentación e índice.
#
# Solo Unix (Linux y macOS). En Windows hace falta WSL con entorno gráfico.
#
# Uso:
#   ./install.sh                # completo: API + descarga de la guía + índice
#   ./install.sh --api-only     # solo API (offline, sin descargar la guía)
#   ./install.sh --skip-crawl   # reutiliza lo ya descargado en raw/html
#   ./install.sh --no-images    # descarga la guía sin imágenes (más rápido)
#   ./install.sh --skip-api     # solo guía (si no tienes AnyLogic instalado)
#
set -euo pipefail
cd "$(dirname "$0")"

usage() {
  cat <<'TXT'
Instala anylogic-docs-mcp: entorno Python, corpus de documentación e índice.

Solo Unix (Linux y macOS). En Windows hace falta WSL con entorno gráfico.

Uso:
  ./install.sh                # completo: API + descarga de la guía + índice
  ./install.sh --api-only     # solo API (offline, sin descargar la guía)
  ./install.sh --skip-crawl   # reutiliza lo ya descargado en raw/html
  ./install.sh --no-images    # descarga la guía sin imágenes (más rápido)
  ./install.sh --skip-api     # solo guía (si no tienes AnyLogic instalado)

Requisitos: Python 3.12+, Node 20+ y Chrome/Chromium (para el crawler),
AnyLogic instalado (para la API) y ~1 GB de disco libre.
TXT
}

PYTHON_MIN="3.12"
NODE_MIN=20

DO_API=1
DO_CRAWL=1
DO_IMAGES=1

for arg in "$@"; do
  case "$arg" in
    --api-only)   DO_CRAWL=0 ;;
    --skip-crawl) DO_CRAWL=0 ;;
    --no-images)  DO_IMAGES=0 ;;
    --skip-api)   DO_API=0 ;;
    -h|--help) usage; exit 0 ;;
    *)
      echo "Opción desconocida: $arg (usa --help)" >&2
      exit 2 ;;
  esac
done

info()  { printf '\n\033[1m== %s\033[0m\n' "$*"; }
fail()  { printf '\n\033[1;31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }
warn()  { printf '\033[1;33mAviso:\033[0m %s\n' "$*"; }

# ---------------------------------------------------------------- comprobaciones
case "$(uname -s)" in
  Linux|Darwin) ;;
  *) fail "Este instalador es para Linux y macOS. En Windows usa WSL2 con entorno
  gráfico (wsl --install) y ejecútalo dentro de la distribución de Linux." ;;
esac

command -v python3 >/dev/null 2>&1 || fail "No encontré python3. Instálalo (3.12 o superior)."
if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3,12) else 1)'; then
  fail "Python $(python3 -V | cut -d' ' -f2) es demasiado antiguo. Hace falta 3.12 o superior."
fi

if [ "$DO_CRAWL" = 1 ]; then
  command -v node >/dev/null 2>&1 || fail "No encontré Node.js. Hace falta Node 20 o superior para descargar la guía.
  Alternativa sin Node: ./install.sh --api-only (solo API, offline)."
  NODE_V=$(node -p 'process.versions.node.split(".")[0]')
  [ "$NODE_V" -ge "$NODE_MIN" ] || fail "Node $(node -v) es demasiado antiguo. Hace falta Node $NODE_MIN o superior."
fi

# ---------------------------------------------------------------- resumen previo
echo
echo "anylogic-docs-mcp — instalación"
echo "-----------------------------------------------"
echo "  Sistema:   $(uname -s) $(uname -m)"
echo "  Python:    $(python3 -V | cut -d' ' -f2)"
[ "$DO_CRAWL" = 1 ] && echo "  Node:      $(node -v)"
echo
if [ "$DO_API" = 1 ]; then
  echo "  1. API Java:   se lee del javadoc de tu instalación de AnyLogic (sin red, ~1 min)"
else
  echo "  1. API Java:   OMITIDA (--skip-api)"
fi
if [ "$DO_CRAWL" = 1 ]; then
  echo "  2. Guía:       se DESCARGA de anylogic.help (~964 páginas, ~300 MB, ~10 min)"
  echo "                 Abre una ventana de Chromium: si Cloudflare pide verificación,"
  echo "                 complétala a mano y el proceso continúa solo."
else
  echo "  2. Guía:       OMITIDA (se reutiliza lo que ya haya en raw/html)"
fi
echo "  3. Índice:     se construye en index.db (~1 min)"
echo
echo "  Espacio necesario: ~1 GB libre. Tiempo total: 10–15 min."
echo

# ---------------------------------------------------------------- entorno Python
info "Entorno Python"
if [ ! -x .venv/bin/python ]; then
  if command -v uv >/dev/null 2>&1; then
    uv venv --python "$PYTHON_MIN" .venv
  else
    warn "No encontré 'uv'; uso python3 -m venv (más lento, funciona igual)."
    python3 -m venv .venv
  fi
fi
if command -v uv >/dev/null 2>&1; then
  uv pip install --python .venv/bin/python -r requirements.txt
else
  .venv/bin/python -m pip install --quiet --upgrade pip
  .venv/bin/python -m pip install --quiet -r requirements.txt
fi
PY=.venv/bin/python
echo "intérprete del entorno: $($PY -V 2>&1)"

# ---------------------------------------------------------------- API (offline)
if [ "$DO_API" = 1 ]; then
  info "API Java (javadoc local de AnyLogic)"
  if ! $PY - <<'EOF'
import sys
sys.path.insert(0, "scripts")
from convert_api import autodetect_anylogic
sys.exit(0 if autodetect_anylogic() else 1)
EOF
  then
    fail "No encontré una instalación de AnyLogic con javadoc.
  Buscado en: ~/Applications, /opt, /usr/local, /Applications
  Opciones:
    - indica la ruta:  $PY scripts/convert_api.py --anylogic /ruta/a/AnyLogic-8.9.9
    - o define ANYLOGIC_HOME
    - o instala solo la guía:  ./install.sh --skip-api"
  fi
  $PY scripts/convert_api.py
fi

# ---------------------------------------------------------------- guía (red)
if [ "$DO_CRAWL" = 1 ]; then
  info "Guía de anylogic.help (descarga)"
  if ! node scripts/crawl.mjs --check; then
    fail "No hay un navegador Chromium disponible. Instala Chrome/Chromium o define
  ANYLOGIC_CHROME con la ruta al binario."
  fi
  if [ "$DO_IMAGES" = 1 ]; then
    node scripts/crawl.mjs --images
  else
    node scripts/crawl.mjs
  fi
fi

# ---------------------------------------------------------------- corpus + índice
if [ -d raw/html ] && [ -n "$(ls -A raw/html 2>/dev/null)" ]; then
  info "Conversión de la guía a Markdown"
  $PY scripts/convert_guide.py
else
  warn "No hay páginas en raw/html: el índice tendrá solo la API.
  Para añadir la guía, ejecuta ./install.sh (sin --api-only ni --skip-crawl)."
fi

info "Construcción del índice de búsqueda"
$PY scripts/build_index.py

# ---------------------------------------------------------------- verificación
info "Verificación"
$PY scripts/selftest.py

cat <<EOF

Listo. Ahora registra el servidor en tu agente:

  opencode mcp add anylogic-docs --global -- "$PWD/.venv/bin/python" "$PWD/server/main.py"

  claude mcp add anylogic-docs -- "$PWD/.venv/bin/python" "$PWD/server/main.py"

  (o el JSON equivalente para Cursor / VS Code; ver README)

Reinicia la sesión del agente y pídele algo de AnyLogic: debería consultar
la documentación antes de responder.
EOF
