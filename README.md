# anylogic-docs-mcp

Servidor [MCP](https://modelcontextprotocol.io) que le da a un agente de IA (opencode,
Claude Code, Cursor, Codex…) la documentación real de **AnyLogic 8.9** para que
consulte en vez de inventar: bloques, propiedades, firmas de la API Java, tutoriales
y ejemplos.

Todo se consulta **en local**: el servidor sólo abre un índice SQLite y unos ficheros
Markdown. No hay red en tiempo de consulta.

> **Solo Unix.** Este proyecto está pensado para **Linux y macOS**. En **Windows
> requiere WSL2** con entorno gráfico (el crawler abre una ventana de navegador).
> No está probado de forma nativa en Windows.

---

## El problema que resuelve

Sin documentación a mano, un agente improvisa:

> — "Para cambiar la prioridad de un `Seize`, usa `seize.setPriority(5)`."
> ❌ Ese método no existe.

Con este MCP, busca primero y cita:

> — "`Seize` tiene el campo `priority` de tipo `double`; se define con
> `public double priority(T agent)` y cuanto mayor, antes se atiende la tarea.
> Fuente: https://anylogic.help/api/com/anylogic/libraries/processmodeling/Seize.html"

Eso es todo lo que hace: convierte "creo que la API es así" en "la API es así, aquí
está".

---

## Cómo funciona

```
   anylogic.help  ──crawl──┐
   (964 páginas)           │
                           ├──►  corpus/*.md  ──►  index.db  ──►  servidor MCP  ──►  agente
   javadoc de AnyLogic ────┘     (Markdown)      (SQLite FTS5)      (stdio)
   (1.066 clases)
```

1. **API** — se lee del javadoc que **ya viene instalado con AnyLogic** (sin red).
2. **Guía** — se descarga una vez de `anylogic.help` (necesita red, ver aviso abajo).
3. **Conversión** — todo se normaliza a Markdown limpio: tablas, código, listas de
   propiedades de cada bloque, imágenes.
4. **Índice** — se construye `index.db` con búsqueda de texto (BM25 de SQLite FTS5,
   sin embeddings ni modelos).
5. **Servidor** — `server/main.py` expone 7 herramientas MCP sobre ese índice.

---

## Requisitos previos

Esto no es un paquete que se instala y listo: **genera tu propia copia local de la
documentación**. Antes de empezar, comprueba que tienes todo esto.

| Requisito | Versión | Cómo comprobarlo | Para qué | Si falta |
|---|---|---|---|---|
| **Sistema operativo** | Linux o macOS | `uname -s` | todo el proyecto | en Windows usa **WSL2** con entorno gráfico |
| **Python** | 3.12 o superior | `python3 --version` | servidor MCP y conversores | no arranca nada |
| **uv** | última | `uv --version` | crear el entorno e instalar dependencias | el instalador usa `python3 -m venv` + `pip` (más lento, funciona igual) |
| **Node.js** | 20 o superior | `node --version` | crawler (`fetch` y `WebSocket` nativos) | no se puede descargar la guía (queda solo la API) |
| **Chrome / Chromium** | 120 o superior | `node scripts/crawl.mjs --check` | abrir la web real y superar Cloudflare | el crawl falla |
| **AnyLogic** | 8.9.x instalado | debe existir `~/Applications/AnyLogic-8.9.9` (Linux) o `/Applications/AnyLogic*.app` (macOS) | de ahí salen los javadoc de la API | tendrías guía pero **sin referencia de API** |
| **Conexión a internet** | — | — | descargar `anylogic.help` (~300 MB) | solo funciona la parte de API, que es offline |
| **Espacio en disco** | ~1 GB libre | `df -h .` | venv (60 MB) + HTML (215 MB) + imágenes (76 MB) + índice (40 MB) | el proceso se corta a medias |
| **Entorno gráfico** | X11, Wayland o macOS | — | Chromium necesita ventana visible para el challenge | el crawl no pasa Cloudflare |

**Tiempo total de la primera instalación: 10–15 minutos** (API ~1 min, descarga de la
guía ~10 min, índice ~1 min).

Navegadores válidos: Chrome, Chromium, Brave o Edge (cualquier binario basado en
Chromium). Si no está en el `PATH`, se indica con `ANYLOGIC_CHROME`.

---

## Instalación

```bash
git clone https://github.com/<usuario>/anylogic-docs-mcp.git
cd anylogic-docs-mcp
./install.sh
```

Eso es todo. El script crea el entorno, genera el corpus y el índice, y termina con una
verificación automática.

### Opciones

| Comando | Qué hace | Cuándo usarlo |
|---|---|---|
| `./install.sh` | API + descarga de la guía + índice | instalación normal |
| `./install.sh --api-only` | solo API, sin red | ya tienes la guía, o no quieres descargar nada |
| `./install.sh --skip-crawl` | reutiliza lo ya descargado en `raw/html` | reinstalar sin volver a bajar |
| `./install.sh --no-images` | descarga la guía sin imágenes | ahorra ~4 minutos y 76 MB |
| `./install.sh --skip-api` | solo guía | no tienes AnyLogic instalado |

### Qué hace exactamente

1. Comprueba sistema operativo, Python 3.12+, Node 20+ y el navegador.
2. Crea `.venv` e instala `mcp[cli]`, `beautifulsoup4` y `lxml`.
3. `scripts/convert_api.py` → lee el javadoc de tu AnyLogic y genera `corpus/api/`.
4. `scripts/crawl.mjs --images` → **descarga** la guía de `anylogic.help` en `raw/html/`.
5. `scripts/convert_guide.py` → HTML a Markdown en `corpus/guide/`.
6. `scripts/build_index.py` → construye `index.db` (~37.000 fragmentos).
7. `scripts/selftest.py` → 18 comprobaciones de búsqueda y de API.

Si no encuentra AnyLogic, **aborta** y te dice cómo indicar la ruta, porque sin la API
el MCP pierde la mitad de su valor. Si sólo quieres la guía, usa `--skip-api`.

---

## Aviso: la instalación descarga la documentación

La primera ejecución de `./install.sh` **descarga 964 páginas y unas 3.000 imágenes de
`anylogic.help`** (~300 MB). Es una descarga **única**: después todo se consulta en
local, sin internet.

- **Abre una ventana de Chromium.** No es un error. Cloudflare bloquea la descarga
  automática normal, así que el crawler usa un navegador real. Si aparece un challenge
  ("Just a moment…" / "Un momento…"), **complétalo a mano** en esa ventana: el script
  continúa solo.
- **Es reanudable.** Si se corta, vuelve a ejecutarlo: salta lo que ya está descargado.
- **Respeta `robots.txt`** y va a ~2 páginas por segundo.
- **Solo una vez por versión de AnyLogic.** Cuando actualices AnyLogic, repite
  `./install.sh`.
- **Este repositorio no incluye la documentación.** Es de The AnyLogic Company; cada
  uno genera su copia para uso personal. No la subas ni la redistribuyas.

---

## Registro en el agente

Sustituye `/ruta/a/anylogic-docs-mcp` por la ruta real (la misma donde hiciste `git clone`).

### opencode

```bash
opencode mcp add anylogic-docs --global -- \
  /ruta/a/anylogic-docs-mcp/.venv/bin/python \
  /ruta/a/anylogic-docs-mcp/server/main.py
```

Comprobar: `opencode mcp list` debe decir `connected`.

### Claude Code

```bash
claude mcp add anylogic-docs -- \
  /ruta/a/anylogic-docs-mcp/.venv/bin/python \
  /ruta/a/anylogic-docs-mcp/server/main.py
```

### Cursor / VS Code / otros clientes con JSON

```json
{
  "mcpServers": {
    "anylogic-docs": {
      "command": "/ruta/a/anylogic-docs-mcp/.venv/bin/python",
      "args": ["/ruta/a/anylogic-docs-mcp/server/main.py"]
    }
  }
}
```

En opencode el JSON equivalente es:

```json
{
  "mcp": {
    "servers": {
      "anylogic-docs": {
        "type": "local",
        "command": [
          "/ruta/a/anylogic-docs-mcp/.venv/bin/python",
          "/ruta/a/anylogic-docs-mcp/server/main.py"
        ]
      }
    }
  }
}
```

**Reinicia la sesión del agente** después de registrarlo. Si el servidor arranca pero no
hay índice, la herramienta responde con un error explicando que ejecutes `./install.sh`.

### Opcional: que el agente sepa cuándo consultar

El MCP da las herramientas, pero no obliga a usarlas. Para que el agente consulte
siempre antes de afirmar algo de AnyLogic, añade esto a tu `AGENTS.md` (opencode,
Codex) o `CLAUDE.md`:

```markdown
## AnyLogic

Antes de afirmar cómo funciona un bloque, una propiedad o una firma de la API:

1. `anylogic_search("términos en inglés")` → `anylogic_read(path, heading)`.
2. Para código: `anylogic_api("Clase.miembro")`. Si no existe, no lo inventes.
3. La documentación está en inglés; responde en español y cita la URL.
4. Este entorno es AnyLogic PLE 8.9.9: hay funciones (export a Java, librerías
   propias, tamaño de modelo) que no están disponibles.
```

---

## Herramientas

| Herramienta | Para qué | Cuándo usarla |
|---|---|---|
| `anylogic_search(query, scope?, section?, limit?)` | búsqueda BM25 en guía + API | siempre, es el punto de entrada |
| `anylogic_read(path, heading?, max_chars?)` | lee una página o **una sección** | tras una búsqueda, para no tragarse la página entera |
| `anylogic_api(symbol, max_chars?)` | ficha exacta de clase/método/campo con firma Java | antes de escribir código |
| `anylogic_api_search(query, limit?)` | búsqueda acotada a la API | cuando sólo quieres firmas |
| `anylogic_examples(query, limit?)` | ejemplos en tutoriales y modelado avanzado | para ver código real de un patrón |
| `anylogic_toc(scope?, section?)` | mapa de secciones y paquetes | cuando no sabes dónde vive un tema |
| `anylogic_version()` | versión y tamaño del corpus | para comprobar que el índice está generado |

`scope` acepta `"guide"` (guía de usuario) o `"api"` (referencia Java).

### Ejemplo de uso real

```
anylogic_search("seize priority")
  → Seize › Task priority (guía) + Seize.priority (API)

anylogic_read("guide/library-reference-guides/process-modeling-library/seize.md",
              heading="Number of units")
  → sección concreta: tipo, valor por defecto, variables locales

anylogic_api("Seize.priority")
  → public double priority ( T agent)
    "The priority of the task for the incoming agent (the larger the higher)."
```

---

## Cómo busca

BM25 de SQLite FTS5, sin embeddings. Ajustes que importan en la práctica:

- **Nombre de bloque primero.** Si la consulta coincide con el título de una página
  (`Seize`, `ResourcePool`, `Conveyor`), esa página va arriba aunque su texto no repita
  la palabra.
- **AND y luego OR.** Primero exige todos los términos; si no hay nada, relaja.
- **Cobertura.** Entre los resultados sube el fragmento que contiene más términos
  distintos de la consulta, y más si están en el título.
- **Stemmer mínimo.** `recurring` encuentra `recurrence`, `capacities` encuentra
  `capacity` (FTS5 no trae stemming).
- **Sesgo de guía (×1.25).** La guía explica el bloque; la API da la firma.
- **Máximo 2 fragmentos por página**, para no repetir la misma fuente.

La documentación está en inglés: **busca en inglés** (`seize capacity`, no
`capacidad de seize`).

---

## Mantenimiento

### Actualizar a una versión nueva de AnyLogic

```bash
./install.sh          # re-descarga lo que falte y regenera todo
./update.sh           # equivalente (alias)
```

Si sólo cambió AnyLogic y quieres refrescar la API (offline, rápido):

```bash
.venv/bin/python scripts/convert_api.py
.venv/bin/python scripts/build_index.py
```

### Reconstruir sólo el índice

```bash
.venv/bin/python scripts/build_index.py
```

### Comprobar que todo sigue bien

```bash
.venv/bin/python scripts/selftest.py
```

### Variables de entorno útiles

| Variable | Para qué | Por defecto |
|---|---|---|
| `ANYLOGIC_HOME` | ruta de la instalación de AnyLogic | autodetectada |
| `ANYLOGIC_CHROME` | binario de Chrome/Chromium | autodetectado |
| `ANYLOGIC_CDP_PORT` | puerto de depuración del crawler | `9333` |
| `ANYLOGIC_PROFILE` | perfil del navegador | `.chrome-profile/` |
| `ANYLOGIC_DOCS_HOME` | otra copia del corpus/índice | la del repo |

---

## Problemas típicos

| Síntoma | Causa | Solución |
|---|---|---|
| `No encontré Chrome ni Chromium` | no hay navegador en el `PATH` | instálalo (`sudo dnf install chromium`, `brew install --cask google-chrome`) o `export ANYLOGIC_CHROME=/ruta/al/binario` |
| `Cloudflare no cedió` | challenge no resuelto | complétalo en la ventana abierta; si insiste, `rm -rf .chrome-profile` y reintenta con `--delay 0.5` |
| `Chromium no abrió el puerto de depuración` | perfil bloqueado o puerto ocupado | `rm -rf .chrome-profile` y/o `ANYLOGIC_CDP_PORT=9336 ./install.sh` |
| `No encontré una instalación de AnyLogic` | ruta no estándar | `.venv/bin/python scripts/convert_api.py --anylogic /ruta/AnyLogic-8.9.9` o `export ANYLOGIC_HOME=...` |
| `No existe el índice en ...` | falta generar el corpus | `./install.sh` |
| `disk I/O error` al reconstruir | otra sesión tiene el índice abierto | cierra el agente y reintenta; el índice se reemplaza de forma atómica |
| Búsquedas en español devuelven poco | la documentación está en inglés | busca en inglés (`arrival rate`, no `tasa de llegada`) |
| Faltan imágenes | enlaces roscos en la propia web de AnyLogic | se registran en `logs/image_failures.json`; no afecta al texto |
| El crawl va lento | ~2 páginas/s es lo normal | es una descarga única; se puede reanudar |

---

## Estructura del repositorio

```
anylogic-docs-mcp/
├── server/main.py          # servidor MCP (stdio), 7 herramientas
├── scripts/
│   ├── crawl.mjs           # descarga anylogic.help con Chromium por CDP
│   ├── convert_api.py      # javadoc de AnyLogic → Markdown + símbolos
│   ├── convert_guide.py    # HTML → Markdown
│   ├── build_index.py      # corpus → index.db (FTS5)
│   └── selftest.py         # comprobaciones de búsqueda y API
├── install.sh              # instalación completa (idempotente)
├── NOTICE.md               # aviso: la licencia MIT no cubre la documentación
├── update.sh               # alias de install.sh para actualizar
├── requirements.txt
└── pyproject.toml
```

Generado en local, **no versionado** (ver `.gitignore`):

```
corpus/          # Markdown de la guía y de la API
raw/             # HTML e imágenes descargados (caché reanudable)
index.db         # índice de búsqueda
.venv/           # entorno Python
logs/            # fallos de crawl e imágenes
.chrome-profile/ # perfil del navegador usado por el crawler
```

---

## Aviso legal y licencia

- **Código:** MIT (ver [LICENSE](LICENSE)).
- **Documentación:** la guía, el javadoc y las imágenes son propiedad de
  **The AnyLogic Company** y están sujetos a sus términos de uso. Este repositorio
  **no los distribuye**: los scripts los generan en tu máquina a partir de tu propia
  instalación de AnyLogic y del sitio público `anylogic.help`, para **uso personal**.
  Detalle en [NOTICE.md](NOTICE.md).
- No redistribuyas `corpus/`, `raw/` ni `index.db`.
- El crawler respeta `robots.txt` y va deliberadamente despacio.
