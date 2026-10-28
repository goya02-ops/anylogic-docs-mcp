#!/usr/bin/env python3
"""Construye index.db (SQLite FTS5) a partir de corpus/api y corpus/guide.

- API: un chunk por clase y otro por método/constructor/campo.
- Guía: un chunk por sección (## / ###), partiendo las muy largas.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "corpus"
DB = ROOT / "index.db"

SCHEMA = """
PRAGMA journal_mode=DELETE;
DROP TABLE IF EXISTS chunks_fts;
DROP TABLE IF EXISTS chunks;
CREATE TABLE chunks(
  id INTEGER PRIMARY KEY,
  scope TEXT NOT NULL,
  kind TEXT,
  symbol TEXT,
  owner TEXT,
  path TEXT NOT NULL,
  url TEXT,
  title TEXT,
  heading TEXT,
  body TEXT
);
CREATE VIRTUAL TABLE chunks_fts USING fts5(
  title, heading, body,
  content='chunks', content_rowid='id',
  tokenize='unicode61 remove_diacritics 2'
);
"""

MAX_CHARS = int(__import__("os").environ.get("CHUNK_CHARS", "1200"))
OVERLAP = 300
TITLE_IN_BODY = __import__("os").environ.get("TITLE_IN_BODY", "0") == "1"


def split_long(text: str) -> list[str]:
    if len(text) <= MAX_CHARS:
        return [text]
    parts = []
    start = 0
    while start < len(text):
        end = min(start + MAX_CHARS, len(text))
        if end < len(text):
            cut = text.rfind("\n", start + MAX_CHARS // 2, end)
            if cut > 0:
                end = cut
        parts.append(text[start:end])
        if end >= len(text):
            break
        start = max(end - OVERLAP, start + 1)
    return parts


def parse_front(md: str) -> tuple[dict, str]:
    if not md.startswith("---\n"):
        return {}, md
    end = md.find("\n---\n", 4)
    if end == -1:
        return {}, md
    meta = {}
    for line in md[4:end].splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip()
    return meta, md[end + 5 :]


def chunks_from_guide(path: Path) -> list[dict]:
    md = path.read_text(encoding="utf-8", errors="replace")
    meta, body = parse_front(md)
    rel = path.relative_to(CORPUS).as_posix()
    title = meta.get("title") or path.stem

    # separa por encabezados de nivel 2 y 3
    blocks: list[tuple[str, str]] = []
    cur_head = ""
    cur: list[str] = []
    for line in body.splitlines():
        m = re.match(r"^(#{2,4})\s+(.*)$", line)
        if m:
            blocks.append((cur_head, "\n".join(cur).strip()))
            cur_head = m.group(2).strip()
            cur = []
        else:
            cur.append(line)
    blocks.append((cur_head, "\n".join(cur).strip()))

    out = []
    for head, text in blocks:
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        if not text and not head:
            continue
        for i, part in enumerate(split_long(text)):
            body = f"{title}. {head}.\n{part}" if TITLE_IN_BODY else part
            out.append(
                {
                    "scope": "guide",
                    "kind": "page",
                    "symbol": None,
                    "owner": None,
                    "path": rel,
                    "url": meta.get("url", ""),
                    "title": title,
                    "heading": head if i == 0 else f"{head} (cont.)",
                    "body": body,
                }
            )
    return out


def chunks_from_api(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        desc = r.get("description") or ""
        body = r["signature"] + ("\n\n" + desc if desc else "")
        rows.append(
            {
                "scope": "api",
                "kind": r["kind"],
                "symbol": r["symbol"],
                "owner": r.get("owner"),
                "path": r["path"],
                "url": r.get("url", ""),
                "title": r.get("owner", ""),
                "heading": r["signature"],
                "body": body[:4000],
            }
        )
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DB)
    args = ap.parse_args()

    rows: list[dict] = []
    symbols = CORPUS / "api_symbols.jsonl"
    if symbols.exists():
        rows += chunks_from_api(symbols)
        print(f"[index] {len(rows)} chunks de API")
    else:
        print("[index] aviso: no hay api_symbols.jsonl")

    guide_dir = CORPUS / "guide"
    n_guide = 0
    if guide_dir.is_dir():
        for md in sorted(guide_dir.rglob("*.md")):
            rows += chunks_from_guide(md)
            n_guide += 1
        print(f"[index] {len(rows)} chunks totales ({n_guide} páginas de guía)")

    if not rows:
        sys.exit("Nada que indexar. Ejecuta convert_api.py / convert_guide.py")

    tmp = args.db.with_suffix(".db.tmp")
    for f in (tmp, Path(str(tmp) + "-wal"), Path(str(tmp) + "-shm")):
        f.unlink(missing_ok=True)
    con = sqlite3.connect(tmp)
    con.executescript(SCHEMA)
    con.executemany(
        """INSERT INTO chunks(scope,kind,symbol,owner,path,url,title,heading,body)
           VALUES(:scope,:kind,:symbol,:owner,:path,:url,:title,:heading,:body)""",
        rows,
    )
    con.execute("INSERT INTO chunks_fts(rowid,title,heading,body) SELECT id,title,heading,body FROM chunks")
    con.execute(
        """CREATE TABLE pages AS
           SELECT path, scope, title, url, MIN(id) AS first_chunk
           FROM chunks GROUP BY path"""
    )
    con.execute("CREATE INDEX idx_pages_title ON pages(lower(title))")
    con.execute("CREATE INDEX idx_chunks_scope ON chunks(scope)")
    con.execute("CREATE INDEX idx_chunks_path ON chunks(path)")
    con.execute("CREATE INDEX idx_chunks_symbol ON chunks(symbol)")
    con.commit()
    con.execute("INSERT INTO chunks_fts(chunks_fts) VALUES('optimize')")
    con.commit()
    con.close()

    # reemplazo atómico: los lectores abren el fichero nuevo en la siguiente consulta
    for suffix in ("", "-wal", "-shm"):
        Path(str(args.db) + suffix).unlink(missing_ok=True)
    tmp.replace(args.db)
    print(f"[index] listo: {args.db} ({args.db.stat().st_size/1e6:.1f} MB)")


if __name__ == "__main__":
    main()
