#!/usr/bin/env python3
"""Servidor MCP de documentación de AnyLogic (stdio).

Expone 7 herramientas de sólo lectura sobre un índice SQLite FTS5 construido a
partir del javadoc local de AnyLogic y de la guía descargada de anylogic.help.

No usa red: sólo abre index.db y los Markdown de corpus/.
"""
from __future__ import annotations

import os
import re
import sqlite3
from pathlib import Path

from mcp.server.mcpserver import MCPServer

# ANYLOGIC_DOCS_HOME permite apuntar a otra copia del corpus/índice sin mover
# el servidor (útil para probar dos versiones de la documentación a la vez).
ROOT = Path(os.environ.get("ANYLOGIC_DOCS_HOME") or Path(__file__).resolve().parent.parent)
DB = ROOT / "index.db"
CORPUS = ROOT / "corpus"
ASSETS = CORPUS / "assets"

mcp = MCPServer(
    "anylogic-docs",
    instructions=(
        "Documentación de AnyLogic 8.9 (guía de usuario + API de Java). "
        "Usa anylogic_search para empezar, anylogic_read para leer una sección "
        "completa y anylogic_api para firmas exactas. Cita siempre la URL."
    ),
)

TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_.]*|\d+")


def connect() -> sqlite3.Connection:
    if not DB.exists():
        raise RuntimeError(
            f"No existe el índice en {DB}.\n"
            "  Genera el corpus y el índice con:  ./install.sh\n"
            "  (o define ANYLOGIC_DOCS_HOME si lo tienes en otra carpeta)"
        )
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


_SUFFIXES = (
    "ingly",
    "ingly",
    "ing",
    "edly",
    "ed",
    "ence",
    "ance",
    "ions",
    "ion",
    "ment",
    "ity",
    "ies",
    "es",
    "s",
)


def _en_stem(t: str) -> str:
    """Stemmer inglés mínimo: quita sufijos frecuentes y dobles consonantes.

    No pretende ser Porter; sólo evitar que "recurring" no encuentre
    "recurrence" (FTS5 no tiene stemming).
    """
    if len(t) <= 4:
        return t
    stem = t
    for suf in _SUFFIXES:
        if stem.endswith(suf) and len(stem) - len(suf) >= 3:
            stem = stem[: -len(suf)]
            break
    if stem.endswith("y") and len(stem) > 3:
        stem = stem[:-1] + "i"
    # "recurr" -> "recur": la misma raíz que produce "recurrence"
    if len(stem) > 4 and stem[-1] == stem[-2] and stem[-1] not in "aeiou":
        stem = stem[:-1]
    return stem


def _stems(query: str) -> list[str]:
    """Raíces de los términos de la consulta, para medir cobertura."""
    out = []
    for t in TOKEN_RE.findall(query):
        t = t.lower()
        if len(t) <= 2:
            continue
        out.append(_en_stem(t))
    return list(dict.fromkeys(out))


def _coverage(row: sqlite3.Row, stems: list[str]) -> int:
    """Cuántos términos distintos de la consulta aparecen en el fragmento."""
    body = row["_body"] if "_body" in row.keys() else row["snippet"]
    hay = f"{row['title'] or ''} {row['heading'] or ''} {body or ''}".lower()
    return sum(1 for s in stems if s in hay)


def _title_matches(row: sqlite3.Row, stems: list[str]) -> int:
    """Cuántos términos de la consulta están en el título de la página."""
    title = (row["title"] or "").lower()
    return sum(1 for s in stems if s in title)


def fts_query(q: str, op: str = " OR ") -> str:
    """Convierte texto libre en una consulta FTS5 razonable."""
    q = q.strip()
    if not q:
        return ""
    phrases = re.findall(r'"([^"]+)"', q)
    rest = re.sub(r'"[^"]+"', " ", q)
    terms = TOKEN_RE.findall(rest)

    parts = []
    for p in phrases:
        p = p.replace('"', "")
        if p:
            parts.append(f'"{p}"')
    for t in terms:
        t = t.replace('"', "")
        if not t:
            continue
        if "." in t:
            # identificador cualificado: frase exacta + términos sueltos
            parts.append(f'"{t}"')
            parts.extend(f"{x}*" for x in t.split(".") if len(x) > 2)
        elif len(t) > 2:
            parts.append(f"{t}*")
            # morfología inglesa sin stemmer: "recurring" debe encontrar
            # "recurrence", "capacities" -> "capacity". El BM25 se encarga de
            # que la variante corta no arrastre ruido.
            stem = _en_stem(t.lower())
            if len(stem) >= 4 and stem != t.lower():
                parts.append(f"{stem}*")
        else:
            parts.append(t)
    # sin duplicados, preservando orden
    seen = set()
    uniq = []
    for p in parts:
        if p not in seen:
            seen.add(p)
            uniq.append(p)
    return op.join(uniq)


def title_hits(con, query: str, scope: str | None, section: str | None) -> list[sqlite3.Row]:
    """Páginas cuyo título contiene TODOS los términos de la consulta.

    Resuelve el caso "el bloque se llama X": con la consulta "resource pool"
    aparece ResourcePool aunque su texto no repita ambas palabras.
    """
    terms = [t.lower() for t in TOKEN_RE.findall(query) if len(t) > 2]
    if not terms:
        return []
    longest = max(terms, key=len)
    where = ["lower(p.title) LIKE ?"]
    params: list = [f"%{longest}%"]
    if scope in ("guide", "api"):
        where.append("p.scope = ?")
        params.append(scope)
    if section:
        where.append("p.path LIKE ?")
        params.append(section.rstrip("/") + "%")
    sql = f"""
        SELECT c.scope, c.kind, c.symbol, c.path, c.url, c.title, c.heading,
               substr(c.body, 1, 300) AS snippet, 0.0 AS score
        FROM pages p JOIN chunks c ON c.id = p.first_chunk
        WHERE {' AND '.join(where)}
        LIMIT 300
    """
    rows = con.execute(sql, params).fetchall()
    hits = [r for r in rows if all(t in (r["title"] or "").lower() for t in terms)]
    hits.sort(key=lambda r: len(r["title"] or ""))
    return hits[:5]


def fmt_rows(rows: list[sqlite3.Row], header: str) -> str:
    if not rows:
        return (
            f"{header}\n\nSin resultados. Prueba con menos palabras o en inglés "
            "(la documentación está en inglés)."
        )
    out = [header, ""]
    for i, r in enumerate(rows, 1):
        title = r["title"] or ""
        head = r["heading"] or ""
        if r["scope"] == "api" and head:
            label = head
        elif head and head != title:
            label = f"{title} › {head}"
        else:
            label = title or head
        meta = [r["scope"]]
        if r["symbol"]:
            meta.append(r["symbol"])
        snip = (r["snippet"] or "").strip()
        snip = re.sub(r"\s+", " ", snip)
        out.append(f"{i}. **{label}**")
        out.append(f"   {' · '.join(meta)}")
        if snip:
            out.append(f"   {snip}")
        out.append(f"   {r['url']}")
        out.append("")
    return "\n".join(out).rstrip()


def _ranked_rows(
    query: str,
    scope: str | None = None,
    section: str | None = None,
    limit: int = 8,
    prefixes: tuple[str, ...] | None = None,
) -> list[sqlite3.Row]:
    """Pipeline de búsqueda: título exacto, cobertura de términos y BM25."""
    where = []
    base_params: list = []
    if scope in ("guide", "api"):
        where.append("c.scope = ?")
        base_params.append(scope)
    if section:
        where.append("c.path LIKE ?")
        base_params.append(section.rstrip("/") + "%")
    if prefixes:
        where.append("(" + " OR ".join("c.path LIKE ?" for _ in prefixes) + ")")
        base_params.extend(p.rstrip("/") + "%" for p in prefixes)

    sql = f"""
        SELECT c.scope, c.kind, c.symbol, c.path, c.url, c.title, c.heading,
               snippet(chunks_fts, 2, '**', '**', ' … ', 20) AS snippet,
               bm25(chunks_fts, 8.0, 4.0, 1.0)
                 * (CASE c.scope WHEN 'guide' THEN 1.25 ELSE 1.0 END) AS score,
               c.body AS _body
        FROM chunks_fts JOIN chunks c ON c.id = chunks_fts.rowid
        WHERE chunks_fts MATCH ?{''.join(' AND ' + w for w in where)}
        ORDER BY score
        LIMIT ?
    """
    n = max(1, min(int(limit), 25))
    stems = _stems(query)
    cands: list[tuple[int, int, int, float, sqlite3.Row]] = []
    with connect() as con:
        for r in title_hits(con, query, scope, section):
            cands.append((0, _coverage(r, stems), 1, 0.0, r))
        for op in (" AND ", " OR "):
            match = fts_query(query, op)
            if not match:
                continue
            for r in con.execute(sql, [match, *base_params, n * 4]).fetchall():
                cands.append(
                    (1, _coverage(r, stems), _title_matches(r, stems), r["score"], r)
                )

    # une las dos pasadas: primero las páginas que se llaman como lo buscado,
    # luego las que cubren más términos, luego el BM25
    cands.sort(key=lambda t: (t[0], -t[1], -t[2], t[3]))

    rows: list[sqlite3.Row] = []
    seen: set[str] = set()
    per_path: dict[str, int] = {}
    for _, _, _, _, r in cands:
        key = r["path"] + "|" + (r["heading"] or "")
        if key in seen:
            continue
        if per_path.get(r["path"], 0) >= 2:
            continue
        seen.add(key)
        per_path[r["path"]] = per_path.get(r["path"], 0) + 1
        rows.append(r)
        if len(rows) >= n:
            break
    return rows


@mcp.tool()
def anylogic_search(
    query: str,
    scope: str | None = None,
    section: str | None = None,
    limit: int = 8,
) -> str:
    """Busca en la documentación de AnyLogic (guía y API).

    Args:
        query: términos de búsqueda; los identificadores exactos funcionan mejor
            (p.ej. "Seize", "take()", "ResourcePool", "agent.enter").
        scope: "guide" (guía de usuario) o "api" (referencia Java). Vacío = todo.
        section: prefijo de ruta para acotar, p.ej. "guide/anylogic/process-modeling-library".
        limit: número máximo de resultados (1-25).
    """
    n = max(1, min(int(limit), 25))
    rows = _ranked_rows(query, scope, section, n)
    return fmt_rows(rows, f"Resultados para **{query}**:")


@mcp.tool()
def anylogic_read(path: str, heading: str | None = None, max_chars: int = 12000) -> str:
    """Lee una página o una sección concreta del corpus.

    Args:
        path: ruta relativa devuelta por anylogic_search, p.ej.
            "guide/anylogic/3d/3d-object.md" o "api/com/anylogic/engine/Agent.md".
        heading: si se indica, devuelve sólo esa sección (coincidencia parcial).
        max_chars: recorte máximo del resultado.
    """
    clean = path.strip().replace("\\", "/").lstrip("/")
    if ".." in clean:
        return "Ruta no permitida."

    # Acepta también la URL original de anylogic.help
    if clean.startswith("http"):
        from urllib.parse import urlparse

        p = urlparse(clean).path.lstrip("/")
        clean = ("api/" + p[4:]) if p.startswith("api/") else ("guide/" + p)

    candidates = [clean]
    if not clean.startswith(("api/", "guide/")):
        candidates += [f"guide/{clean}", f"api/{clean}"]
    for c in list(candidates):
        if c.endswith(".html"):
            candidates.append(c[:-5] + ".md")
        elif not c.endswith(".md"):
            candidates.append(c + ".md")

    f = next((CORPUS / c for c in candidates if (CORPUS / c).is_file()), None)
    if f is None:
        return f"No existe `{path}`. Usa anylogic_search para localizar la página."

    text = f.read_text(encoding="utf-8", errors="replace")
    source = ""
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end != -1:
            meta = {}
            for line in text[4:end].splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    meta[k.strip()] = v.strip()
            source = meta.get("url", "")
            text = text[end + 5 :]
    if heading:
        lines = text.splitlines()
        start = None
        for i, line in enumerate(lines):
            m = re.match(r"^(#{2,6})\s+(.*)$", line)
            if m and heading.lower() in m.group(2).lower():
                start = i
                level = len(m.group(1))
                break
        if start is not None:
            end = len(lines)
            for j in range(start + 1, len(lines)):
                m = re.match(r"^(#{2,6})\s+", lines[j])
                if m and len(m.group(1)) <= level:
                    end = j
                    break
            text = "\n".join(lines[start:end])
        else:
            text = f"(Sección '{heading}' no encontrada; devuelvo la página completa.)\n\n" + text

    text = text.replace("](assets/", f"]({ASSETS}/")
    if source:
        text = f"> Fuente: {source}\n\n" + text
    if len(text) > max_chars:
        text = text[:max_chars] + f"\n\n… (recortado; pide una sección con `heading`)"
    return text


@mcp.tool()
def anylogic_api(symbol: str, max_chars: int = 8000) -> str:
    """Devuelve la ficha exacta de una clase, método o campo de la API Java.

    Args:
        symbol: nombre simple ("Seize"), cualificado
            ("com.anylogic.libraries.processmodeling.Seize") o miembro
            ("Seize.take", "Agent.getEngine").
    """
    s = symbol.strip()
    with connect() as con:
        row = con.execute(
            """SELECT * FROM chunks WHERE scope='api' AND symbol = ? COLLATE NOCASE
               ORDER BY CASE kind WHEN 'class' THEN 0 ELSE 1 END LIMIT 1""",
            (s,),
        ).fetchone()
        if row is None and "." in s:
            owner, _, member = s.rpartition(".")
            row = con.execute(
                """SELECT * FROM chunks WHERE scope='api'
                   AND symbol LIKE ? AND owner LIKE ?
                   ORDER BY length(symbol) LIMIT 1""",
                (f"%.{member}", f"%{owner}"),
            ).fetchone()
        if row is None:
            # nombre simple: la clase cuyo nombre corto es exactamente ese
            # ("Seize" -> com.anylogic.libraries.processmodeling.Seize, no onSeize)
            row = con.execute(
                """SELECT * FROM chunks WHERE scope='api'
                   AND (symbol LIKE ? OR symbol LIKE ?)
                   ORDER BY CASE kind WHEN 'class' THEN 0 ELSE 1 END,
                            length(symbol) LIMIT 1""",
                (f"%.{s}", f"%.{s}.%"),
            ).fetchone()
        if row is None:
            row = con.execute(
                """SELECT * FROM chunks WHERE scope='api' AND symbol LIKE ?
                   ORDER BY length(symbol) LIMIT 1""",
                (f"%{s}%",),
            ).fetchone()
        if row is None:
            return (
                f"No encontré `{symbol}` en la API. Prueba anylogic_api_search "
                "o anylogic_search con el nombre de la clase."
            )
        cls = con.execute(
            "SELECT * FROM chunks WHERE scope='api' AND kind='class' AND owner=? LIMIT 1",
            (row["owner"],),
        ).fetchone()

    if row["kind"] == "class" or cls is None:
        return anylogic_read(row["path"], max_chars=max_chars)

    body = row["body"].split("\n\n", 1)
    desc = body[1] if len(body) > 1 else ""
    head = (
        f"**`{row['symbol']}`**\n\n"
        f"```java\n{row['heading']}\n```\n\n{desc}\n\n"
        f"Declarado en `{row['owner']}`. Fuente: {row['url']}\n\n"
    )
    ctx = anylogic_read(cls["path"], max_chars=1500)
    return head + "---\n\n### Contexto de la clase\n\n" + ctx


@mcp.tool()
def anylogic_api_search(query: str, limit: int = 10) -> str:
    """Busca clases y métodos en la API Java (firmas, parámetros, tipos).

    Args:
        query: nombre o concepto, p.ej. "seize capacity", "getEngine", "queue".
        limit: número máximo de resultados.
    """
    return anylogic_search(query, scope="api", limit=limit)


@mcp.tool()
def anylogic_examples(query: str, limit: int = 6) -> str:
    """Busca ejemplos y fragmentos de código en tutoriales y modelado avanzado.

    Args:
        query: concepto o API, p.ej. "resource pool animation", "statechart transition".
        limit: número máximo de resultados.
    """
    n = max(1, min(int(limit), 20))
    rows = _ranked_rows(
        query,
        scope="guide",
        limit=n,
        prefixes=("guide/tutorials/", "guide/advanced/"),
    )
    return fmt_rows(rows, f"Ejemplos para **{query}**:")


@mcp.tool()
def anylogic_toc(scope: str | None = None, section: str | None = None) -> str:
    """Mapa de la documentación: secciones, paquetes y páginas disponibles.

    Args:
        scope: "guide" o "api". Vacío = resumen de ambos.
        section: para la guía, prefijo de sección a detallar
            (p.ej. "anylogic/process-modeling-library"). Para la API, un paquete.
    """
    lines: list[str] = []
    with connect() as con:
        if scope in (None, "guide"):
            if section:
                rows = con.execute(
                    """SELECT DISTINCT path, title FROM chunks
                       WHERE scope='guide' AND path LIKE ?
                       ORDER BY path""",
                    (f"guide/{section.strip('/')}%",),
                ).fetchall()
                lines.append(f"## Guía › {section} ({len(rows)} páginas)\n")
                for r in rows:
                    lines.append(f"- {r['path'].removeprefix('guide/')} — {r['title']}")
            else:
                rows = con.execute(
                    """SELECT substr(path, 7, instr(substr(path,7),'/')-1) AS sec,
                              COUNT(DISTINCT path) AS n
                       FROM chunks WHERE scope='guide' GROUP BY sec ORDER BY n DESC"""
                ).fetchall()
                lines.append("## Guía (secciones)\n")
                for r in rows:
                    lines.append(f"- {r['sec']}: {r['n']} páginas")
                lines.append(
                    "\nUsa `anylogic_toc(scope='guide', section='anylogic')` para "
                    "ver las páginas de una sección."
                )

        if scope in (None, "api"):
            if section:
                rows = con.execute(
                    """SELECT symbol FROM chunks
                       WHERE scope='api' AND kind='class' AND symbol LIKE ?
                       ORDER BY symbol""",
                    (f"{section.strip('.')}%",),
                ).fetchall()
                lines.append(f"\n## API › {section} ({len(rows)} clases)\n")
                for r in rows:
                    lines.append(f"- `{r['symbol']}`")
            else:
                rows = con.execute(
                    "SELECT symbol FROM chunks WHERE scope='api' AND kind='class'"
                ).fetchall()
                by_pkg: dict[str, int] = {}
                for r in rows:
                    pkg = r["symbol"].rsplit(".", 1)[0]
                    by_pkg[pkg] = by_pkg.get(pkg, 0) + 1
                lines.append(f"\n## API ({len(rows)} clases en {len(by_pkg)} paquetes)\n")
                for pkg, n in sorted(by_pkg.items(), key=lambda x: -x[1]):
                    lines.append(f"- {pkg}: {n}")
                lines.append(
                    "\nUsa `anylogic_toc(scope='api', section='com.anylogic.engine')` "
                    "para listar las clases de un paquete."
                )
    return "\n".join(lines)


@mcp.tool()
def anylogic_version() -> str:
    """Versión del corpus, número de documentos y fecha de construcción."""
    with connect() as con:
        rows = con.execute(
            "SELECT scope, COUNT(*) AS n, COUNT(DISTINCT path) AS pages FROM chunks GROUP BY scope"
        ).fetchall()
        syms = con.execute("SELECT COUNT(*) FROM chunks WHERE scope='api'").fetchone()[0]
    out = ["# Corpus de documentación AnyLogic", ""]
    out.append("- Versión documentada: **8.9.9**")
    out.append(f"- Índice: `{DB}`")
    for r in rows:
        out.append(f"- {r['scope']}: {r['n']} fragmentos en {r['pages']} páginas")
    out.append(f"- Símbolos de API: {syms}")
    out.append("")
    out.append(
        "Fuentes: javadoc incluido en el instalador de AnyLogic + anylogic.help "
        "(copia local, uso personal)."
    )
    return "\n".join(out)


if __name__ == "__main__":
    mcp.run()
