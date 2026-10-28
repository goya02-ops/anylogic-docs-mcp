#!/usr/bin/env python3
"""Convierte el javadoc local de AnyLogic a Markdown + un JSONL de símbolos.

Fuente: los javadoc que trae el instalador de AnyLogic en
`~/Applications/AnyLogic-*/plugins/*/{javadoc,lib/doc}`.
No requiere red.

Salida:
    corpus/api/<paquete>/<Clase>.md      legible por humanos y por la IA
    corpus/api_symbols.jsonl             un registro por clase/método/campo
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "corpus"
API_URL = "https://anylogic.help/api"

# Dónde suele quedar AnyLogic en cada sistema (solo Unix: en Windows hace falta
# WSL y la ruta es la de Linux).
CANDIDATE_ROOTS = (
    "~/Applications",
    "/opt",
    "/usr/local",
    "/Applications",  # macOS
    "~/anylogic",
)

INTERNAL_MARKERS = ("@AnyLogicInternalCodegenAPI", "@AnyLogicInternalAPI")


def norm(text: str | None) -> str:
    if not text:
        return ""
    text = text.replace("\xa0", " ")
    return re.sub(r"[ \t]+", " ", text).strip()


def norm1(text: str | None) -> str:
    """Como norm() pero para contextos de una sola línea (firmas, títulos)."""
    return norm((text or "").replace("\n", " "))


def text_of(el) -> str:
    """Texto plano de un nodo, respetando saltos de bloque."""
    if el is None:
        return ""
    parts = []
    for child in el.descendants:
        if getattr(child, "name", None) in ("p", "li", "div", "dt", "dd", "br"):
            parts.append("\n")
        elif isinstance(child, str):
            parts.append(child)
    raw = "".join(parts)
    lines = [norm(x) for x in raw.split("\n")]
    return "\n".join(x for x in lines if x)


def md_inline(el) -> str:
    """Convierte un nodo a Markdown conservando `code`, **bold**, *em* y links."""
    if el is None:
        return ""
    out = []
    for child in el.children:
        if isinstance(child, str):
            out.append(child.replace("\xa0", " "))
            continue
        name = child.name
        if name == "code" or (child.get("class") and "codeblank" in child.get("class")):
            inner = norm(child.get_text(" "))
            out.append(f"`{inner}`" if inner else "")
        elif name in ("b", "strong"):
            out.append(f"**{md_inline(child)}**")
        elif name in ("i", "em"):
            out.append(f"*{md_inline(child)}*")
        elif name == "a":
            label = md_inline(child) or norm(child.get_text(" "))
            href = child.get("href", "")
            out.append(f"[{label}]({href})" if href.startswith("http") else label)
        elif name == "br":
            out.append("\n")
        else:
            out.append(md_inline(child))
    return re.sub(r"[ \t]+", " ", "".join(out)).strip()


def find_doc_roots(install: Path) -> list[Path]:
    roots = []
    for pattern in ("*/javadoc", "*/lib/doc"):
        roots.extend(sorted(install.joinpath("plugins").glob(pattern)))
    return [r for r in roots if r.is_dir()]


def is_anylogic_install(path: Path) -> bool:
    """¿Es una instalación de AnyLogic con javadoc utilizable?"""
    return path.is_dir() and bool(find_doc_roots(path))


def autodetect_anylogic() -> Path | None:
    """Busca una instalación de AnyLogic en las rutas habituales de Unix."""
    env = os.environ.get("ANYLOGIC_HOME")
    if env:
        p = Path(env).expanduser()
        if is_anylogic_install(p):
            return p

    found: list[Path] = []
    for base in CANDIDATE_ROOTS:
        base_path = Path(base).expanduser()
        if not base_path.is_dir():
            continue
        for entry in sorted(base_path.glob("AnyLogic*")):
            if is_anylogic_install(entry):
                found.append(entry)
    if not found:
        return None
    # si hay varias versiones, la más nueva por nombre (8.9.9 > 8.8)
    return sorted(found, key=lambda p: p.name)[-1]


def class_pages(roots: list[Path]) -> list[tuple[Path, Path]]:
    out = []
    for root in roots:
        for p in root.rglob("*.html"):
            if p.name in (
                "package-summary.html",
                "index.html",
                "overview-tree.html",
                "allclasses-index.html",
                "allpackages-index.html",
                "index-all.html",
                "help-doc.html",
                "serialized-form.html",
                "constant-values.html",
                "deprecated-list.html",
                "package-tree.html",
                "package-use.html",
                "overview-summary.html",
            ):
                continue
            if "class-use" in p.parts or "doc-files" in p.parts:
                continue
            out.append((root, p))
    return out


def parse_class(root: Path, path: Path) -> dict | None:
    html = path.read_text(encoding="iso-8859-1", errors="replace")
    if 'class="type-signature"' not in html and 'class="type-signature"' not in html.replace(
        "'", '"'
    ):
        return None
    soup = BeautifulSoup(html, "lxml")

    sig_el = soup.select_one("div.type-signature")
    if sig_el is None:
        return None

    meta = soup.find("meta", attrs={"name": "description"})
    fqn = package = None
    if meta and meta.get("content"):
        m = re.search(r"package: ([\w.]+), (?:class|interface|enum|record|annotation interface): ([\w.]+)", meta["content"])
        if m:
            package, name = m.group(1), m.group(2)
            fqn = f"{package}.{name}"
    if not fqn:
        sub = soup.select_one("div.sub-title")
        if not sub:
            return None
        package = norm(sub.get_text(" ")).replace("Package ", "").strip()
        name = path.stem
        fqn = f"{package}.{name}"

    kind = "class"
    body_classes = " ".join(soup.body.get("class", [])) if soup.body else ""
    for k in ("interface", "enum", "annotation", "record", "exception"):
        if f"{k}-declaration-page" in body_classes:
            kind = k
            break

    title = name
    signature = norm1(sig_el.get_text(" "))

    desc = ""
    cd = soup.select_one("#class-description")
    if cd:
        block = cd.find("div", class_="block")
        if block:
            desc = text_of(block)

    notes = []
    if cd:
        dl = cd.find("dl", class_="notes")
        if dl:
            for dt in dl.find_all("dt"):
                dd = dt.find_next_sibling("dd")
                notes.append((norm(dt.get_text(" ")).rstrip(":"), text_of(dd)))

    members = []
    for sec in soup.select("section.detail"):
        sig = sec.select_one("div.member-signature")
        if sig is None:
            continue
        sig_text = norm1(sig.get_text(" "))
        if any(m in sig_text for m in INTERNAL_MARKERS):
            continue
        h3 = sec.select_one("h3")
        mname = norm1(h3.get_text(" ")) if h3 else ""
        if not mname:
            continue
        block = sec.find("div", class_="block")
        mdesc = text_of(block)
        if "shouldn't be accessed by user" in mdesc:
            continue

        group = "methods"
        parent = sec.find_parent("section")
        if parent and parent.get("class"):
            pc = " ".join(parent.get("class"))
            if "constructor" in pc:
                group = "constructors"
            elif "field" in pc:
                group = "fields"
            elif "method" in pc:
                group = "methods"
            elif "enum" in pc:
                group = "enum constants"

        params, returns, throws = [], "", ""
        dl = sec.find("dl", class_="notes")
        if dl:
            for dt in dl.find_all("dt"):
                dd = dt.find_next_sibling("dd")
                label = norm(dt.get_text(" ")).rstrip(":").lower()
                if label.startswith("parameters"):
                    for li in dd.select("li"):
                        ptxt = norm(li.get_text(" "))
                        pname, _, pdesc = ptxt.partition(" - ")
                        params.append({"name": pname.strip(), "desc": pdesc.strip()})
                elif label.startswith("returns"):
                    returns = text_of(dd)
                elif label.startswith("throws"):
                    throws = text_of(dd)

        members.append(
            {
                "group": group,
                "name": mname,
                "signature": sig_text,
                "description": mdesc,
                "params": params,
                "returns": returns,
                "throws": throws,
            }
        )

    return {
        "kind": kind,
        "fqn": fqn,
        "package": package,
        "name": name,
        "title": title,
        "signature": signature,
        "description": desc,
        "notes": notes,
        "members": members,
        "url": f"{API_URL}/{fqn.replace('.', '/')}.html",
    }


def render_md(c: dict) -> str:
    lines = [
        "---",
        "scope: api",
        f"kind: {c['kind']}",
        f"fqn: {c['fqn']}",
        f"package: {c['package']}",
        f"title: {c['title']}",
        f"url: {c['url']}",
        "version: 8.9.9",
        "---",
        "",
        f"# {c['name']}",
        "",
        f"`{c['signature']}`",
        "",
        f"**Package:** `{c['package']}`",
        "",
    ]
    if c["description"]:
        lines += [c["description"], ""]
    for label, value in c["notes"]:
        if value:
            lines += [f"**{label}:** {value}", ""]

    order = ["constructors", "fields", "enum constants", "methods"]
    for group in order:
        items = [m for m in c["members"] if m["group"] == group]
        if not items:
            continue
        lines += [f"## {group.capitalize()}", ""]
        for m in items:
            lines += [f"### `{m['signature']}`", ""]
            if m["description"]:
                lines += [m["description"], ""]
            if m["params"]:
                lines += ["**Parameters:**", ""]
                for p in m["params"]:
                    lines.append(f"- `{p['name']}` — {p['desc']}" if p["desc"] else f"- `{p['name']}`")
                lines.append("")
            if m["returns"]:
                lines += [f"**Returns:** {m['returns']}", ""]
            if m["throws"]:
                lines += [f"**Throws:** {m['throws']}", ""]
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--anylogic",
        type=Path,
        default=None,
        help="ruta de la instalación de AnyLogic (por defecto se autodetecta)",
    )
    ap.add_argument("--out", type=Path, default=CORPUS)
    args = ap.parse_args()

    install = args.anylogic or autodetect_anylogic()
    if install is None:
        sys.exit(
            "No encontré una instalación de AnyLogic con javadoc.\n"
            "  Buscado en: " + ", ".join(CANDIDATE_ROOTS) + "\n"
            "  Solución: indica la ruta a mano, por ejemplo\n"
            "    python scripts/convert_api.py --anylogic ~/Applications/AnyLogic-8.9.9\n"
            "  o define la variable de entorno ANYLOGIC_HOME."
        )
    print(f"[api] instalación de AnyLogic: {install}")
    roots = find_doc_roots(install)
    if not roots:
        sys.exit(f"No encontré javadoc dentro de {install}/plugins")
    print(f"[api] raíces: {len(roots)}")

    api_dir = args.out / "api"
    api_dir.mkdir(parents=True, exist_ok=True)
    symbols_path = args.out / "api_symbols.jsonl"

    seen: dict[str, dict] = {}
    total = 0
    for root, page in class_pages(roots):
        total += 1
        try:
            cls = parse_class(root, page)
        except Exception as e:  # noqa: BLE001
            print(f"  ! {page}: {e}")
            continue
        if not cls:
            continue
        if "_xjal" in cls["name"]:
            continue
        prev = seen.get(cls["fqn"])
        if prev is None or len(cls["members"]) > len(prev["members"]):
            seen[cls["fqn"]] = cls
        if total % 200 == 0:
            print(f"[api] {total} páginas revisadas, {len(seen)} clases")

    print(f"[api] {len(seen)} clases únicas de {total} páginas")

    with symbols_path.open("w", encoding="utf-8") as fh:
        for fqn, c in sorted(seen.items()):
            rel = Path("api") / (fqn.replace(".", "/") + ".md")
            dest = args.out / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(render_md(c), encoding="utf-8")

            fh.write(
                json.dumps(
                    {
                        "kind": "class",
                        "symbol": fqn,
                        "name": c["name"],
                        "owner": c["fqn"],
                        "signature": c["signature"],
                        "description": c["description"][:4000],
                        "url": c["url"],
                        "path": str(rel),
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
            for m in c["members"]:
                desc = m["description"]
                if m["returns"]:
                    desc = f"{desc}\nReturns: {m['returns']}".strip()
                fh.write(
                    json.dumps(
                        {
                            "kind": m["group"].rstrip("s"),
                            "symbol": f"{c['fqn']}.{m['name']}",
                            "name": m["name"],
                            "owner": c["fqn"],
                            "signature": m["signature"],
                            "description": desc[:4000],
                            "url": c["url"],
                            "path": str(rel),
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )

    print(f"[api] escrito {symbols_path}")


if __name__ == "__main__":
    main()
