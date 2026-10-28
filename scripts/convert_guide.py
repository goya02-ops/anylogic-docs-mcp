#!/usr/bin/env python3
"""Convierte el HTML descargado de anylogic.help a Markdown limpio.

Entrada:  raw/html/**.html   (salida de scripts/crawl.mjs)
Salida:   corpus/guide/**.md
Imágenes: se referencian como assets/<ruta>; corpus/assets es un symlink a raw/img
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup, NavigableString, Tag

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "raw"
BASE = "https://anylogic.help"
VERSION = "8.9.9"

SKIP_CLASSES = {
    "content-nav",
    "in-page",
    "back-to-top",
    "breadcrumb",
    "youtubediv",
    "copy-code",
    "toc",
    "table-of-contents",
}
BLOCK_TAGS = {
    "p",
    "div",
    "section",
    "article",
    "ul",
    "ol",
    "table",
    "pre",
    "blockquote",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "dl",
    "figure",
}


def norm(s: str) -> str:
    return re.sub(r"[ \t]+", " ", s.replace("\xa0", " ")).strip()


def classes(el: Tag) -> set[str]:
    return set(el.get("class") or [])


def inline(el, page_url: str) -> str:
    """Markdown en línea (código, negritas, enlaces, imágenes)."""
    if isinstance(el, NavigableString):
        return str(el).replace("\xa0", " ")
    if not isinstance(el, Tag):
        return ""
    if el.name in ("script", "style", "noscript"):
        return ""
    if el.name == "code" or "codeblank" in classes(el):
        t = norm(el.get_text(" "))
        return f"`{t}`" if t else ""
    if el.name in ("b", "strong"):
        return f"**{inline_children(el, page_url)}**"
    if el.name in ("i", "em"):
        return f"*{inline_children(el, page_url)}*"
    if el.name == "br":
        return "\n"
    if el.name == "img":
        return image_md(el, page_url)
    if el.name == "a":
        label = inline_children(el, page_url) or norm(el.get_text(" "))
        href = el.get("href", "")
        if not href or href.startswith("#"):
            return label
        return f"[{label}]({urljoin(page_url, href)})"
    if el.name in BLOCK_TAGS:
        return block(el, page_url)
    return inline_children(el, page_url)


def inline_children(el, page_url: str) -> str:
    return norm("".join(inline(c, page_url) for c in el.children))


def image_md(el: Tag, page_url: str) -> str:
    src = el.get("src", "")
    if not src or src.startswith("data:"):
        return ""
    abs_url = urljoin(page_url, src)
    if not abs_url.startswith(BASE):
        return f"![{el.get('alt', '')}]({abs_url})"
    path = abs_url[len(BASE) :].lstrip("/")
    alt = norm(el.get("alt", "")) or Path(path).stem
    return f"![{alt}](assets/{path})"


def render_list(el: Tag, page_url: str, depth: int = 0) -> str:
    ordered = el.name == "ol"
    lines = []
    for i, li in enumerate(el.find_all("li", recursive=False), 1):
        bullet = f"{i}." if ordered else "-"
        # separa el contenido propio del li de sus listas anidadas
        own = []
        nested = []
        for child in li.children:
            if isinstance(child, Tag) and child.name in ("ul", "ol"):
                nested.append(child)
            else:
                own.append(inline(child, page_url))
        text = norm(" ".join(own))
        text = re.sub(r"\n+", " ", text)
        lines.append(f"{'  ' * depth}{bullet} {text}".rstrip())
        for sub in nested:
            lines.append(render_list(sub, page_url, depth + 1))
    return "\n".join(lines)


def render_table(el: Tag, page_url: str) -> str:
    rows = []
    for tr in el.find_all("tr"):
        cells = []
        for cell in tr.find_all(["th", "td"], recursive=False):
            txt = norm(" ".join(inline(c, page_url) for c in cell.children))
            txt = re.sub(r"\n+", " ", txt).replace("|", "\\|")
            cells.append(txt)
        if cells:
            rows.append(cells)
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    out = ["| " + " | ".join(rows[0]) + " |"]
    out.append("|" + "|".join([" --- "] * width) + "|")
    for r in rows[1:]:
        out.append("| " + " | ".join(r) + " |")
    return "\n".join(out)


def block(el: Tag, page_url: str) -> str:
    if not isinstance(el, Tag):
        return inline(el, page_url)
    name = el.name
    cls = classes(el)
    if name in ("script", "style", "noscript"):
        return ""
    if cls & SKIP_CLASSES:
        return ""
    if name in ("h1", "h2", "h3", "h4", "h5", "h6"):
        level = int(name[1])
        txt = inline_children(el, page_url)
        return f"\n\n{'#' * level} {txt}\n\n" if txt else ""
    if name == "p":
        txt = inline_children(el, page_url)
        # los saltos dentro de un párrafo (Name / Type / Local variable) son
        # líneas reales en la documentación original: forzar salto en Markdown
        txt = txt.replace("\n", "  \n")
        return f"\n\n{txt}\n\n" if txt else ""
    if name in ("ul", "ol"):
        return "\n\n" + render_list(el, page_url) + "\n\n"
    if name == "dl":
        # listas de definición: cada propiedad (dt) con su descripción (dd)
        out = []
        for child in el.children:
            if not isinstance(child, Tag):
                continue
            if child.name == "dt":
                label = norm(child.get_text(" ")).strip("# ").strip()
                if label:
                    out.append(f"\n\n#### {label}\n\n")
            elif child.name == "dd":
                out.append(render_children(child, page_url))
        return "".join(out)
    if name == "table":
        return "\n\n" + render_table(el, page_url) + "\n\n"
    if name == "pre":
        code = el.get_text("")
        lang = ""
        for c in classes(el):
            if c.startswith("language-"):
                lang = c.split("-", 1)[1]
        code_el = el.find("code")
        if code_el:
            for c in classes(code_el):
                if c.startswith("language-"):
                    lang = c.split("-", 1)[1]
        return f"\n\n```{lang}\n{code.rstrip()}\n```\n\n"
    if name == "blockquote":
        inner = render_children(el, page_url)
        quoted = "\n".join("> " + ln for ln in inner.splitlines() if ln.strip())
        return f"\n\n{quoted}\n\n"
    if name == "div" and "note" in cls:
        inner = render_children(el, page_url)
        quoted = "\n".join("> " + ln for ln in inner.splitlines() if ln.strip())
        return f"\n\n> **Nota**\n>\n{quoted}\n\n"
    if name == "div" and "scenario" in cls:
        inner = render_children(el, page_url)
        quoted = "\n".join("> " + ln for ln in inner.splitlines() if ln.strip())
        return f"\n\n> **Escenario**\n>\n{quoted}\n\n"
    if name == "img":
        return image_md(el, page_url)
    if name in ("br", "hr"):
        return "\n\n---\n\n" if name == "hr" else "\n"
    return render_children(el, page_url)


def render_children(el: Tag, page_url: str) -> str:
    parts = []
    for c in el.children:
        piece = block(c, page_url)
        if not piece:
            continue
        # separa bloques consecutivos para que no se peguen las frases
        if isinstance(c, Tag) and c.name in BLOCK_TAGS and not piece.startswith("\n"):
            piece = "\n" + piece
        parts.append(piece)
    return "".join(parts)


def clean(md: str) -> str:
    md = re.sub(r"[ \t]+\n", "\n", md)
    md = re.sub(r"\n{3,}", "\n\n", md)
    md = re.sub(r"^\s+", "", md)
    return md.strip() + "\n"


def convert(page: Path, html_root: Path) -> tuple[Path, str] | None:
    raw = page.read_text(encoding="utf-8", errors="replace")
    if "Just a moment" in raw[:3000]:
        return None
    soup = BeautifulSoup(raw, "lxml")

    # fuera el formulario de feedback del final de cada página (es el único
    # dl.params con data-success; los demás dl.params son las propiedades)
    for el in soup.select("dl.params[data-success], form#feedback, #image-modal, a.back-to-top"):
        el.decompose()

    content = soup.select_one("div.content") or soup.select_one("div.page-content")
    if content is None:
        return None

    rel = page.relative_to(html_root).with_suffix(".md")
    url = f"{BASE}/{page.relative_to(html_root).as_posix()}"

    h1 = content.find("h1")
    title = norm(h1.get_text(" ")) if h1 else page.stem.replace("-", " ").title()

    crumbs_el = soup.select_one("div.breadcrumb")
    crumbs = []
    if crumbs_el:
        for a in crumbs_el.find_all(["a", "span"]):
            t = norm(a.get_text(" "))
            if t and t.lower() not in ("home", "anylogic help"):
                crumbs.append(t)
    section = rel.parts[0] if rel.parts else ""

    body = clean(render_children(content, url))

    front = [
        "---",
        "scope: guide",
        f"section: {section}",
        f"title: {title}",
        f"url: {url}",
        f"breadcrumbs: {' > '.join(crumbs)}",
        f"version: {VERSION}",
        "---",
        "",
    ]
    return rel, "\n".join(front) + body


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", type=Path, default=RAW / "html")
    ap.add_argument("--out", type=Path, default=ROOT / "corpus" / "guide")
    args = ap.parse_args()

    if not args.raw.is_dir():
        sys.exit(f"No existe {args.raw}. Ejecuta antes scripts/crawl.mjs")

    (ROOT / "raw" / "img").mkdir(parents=True, exist_ok=True)
    assets = ROOT / "corpus" / "assets"
    if not assets.exists() and not assets.is_symlink():
        assets.symlink_to(ROOT / "raw" / "img")

    pages = sorted(args.raw.rglob("*.html"))
    print(f"[guide] {len(pages)} páginas HTML")
    ok = skipped = 0
    for page in pages:
        try:
            res = convert(page, args.raw)
        except Exception as e:  # noqa: BLE001
            print(f"  ! {page.relative_to(args.raw)}: {e}")
            skipped += 1
            continue
        if res is None:
            skipped += 1
            continue
        rel, md = res
        dest = args.out / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(md, encoding="utf-8")
        ok += 1
        if ok % 200 == 0:
            print(f"[guide] {ok} convertidas")

    print(f"[guide] listo: {ok} convertidas, {skipped} omitidas")


if __name__ == "__main__":
    main()
