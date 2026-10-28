#!/usr/bin/env python3
"""Comprobación rápida del índice y de la calidad de la búsqueda.

Cada caso declara la ruta (o el título) que debería salir en el primer
resultado. Si algo se rompe al reindexar, este script lo dice.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))

import main as m  # noqa: E402

# (consulta, trozo esperado en el primer resultado)
SEARCH_CASES = [
    ("Seize", "Seize"),
    ("resource pool", "ResourcePool"),
    ("conveyor", "Conveyor"),
    ("seize capacity", "Seize"),
    ("seize priority", "priority"),
    ("statechart transition", "Transition"),
    ("queue timeout", "Queue"),
    ("event recurring", "Event"),
    ("source arrival rate", "Source"),
    ("transporter fleet", "TransporterFleet"),
]

API_CASES = [
    ("Seize", "class Seize"),
    ("ResourcePool.capacity", "capacity"),
    ("Agent.getEngine", "getEngine"),
    ("Seize.priority", "priority"),
]

TOOL_CASES = [
    ("anylogic_toc", lambda: m.anylogic_toc(scope="api")),
    ("anylogic_version", lambda: m.anylogic_version()),
    (
        "anylogic_read sección",
        lambda: m.anylogic_read(
            "guide/library-reference-guides/process-modeling-library/seize.md",
            heading="Number of units",
            max_chars=600,
        ),
    ),
    (
        "anylogic_examples",
        lambda: m.anylogic_examples("resource pool", limit=3),
    ),
]


def check(name: str, out: str, expect: str | None = None) -> bool:
    bad = (
        not out
        or out.startswith("No encontré")
        or out.startswith("No existe")
        or "Sin resultados" in out
        or "no encontrada" in out
    )
    if not bad and expect:
        first = next(
            (ln for ln in out.splitlines() if ln.strip().startswith("1.")), out
        )
        bad = expect.lower() not in first.lower()
    print(f"{'FAIL' if bad else 'ok  '}  {name}")
    if bad:
        print("      " + out[:220].replace("\n", " "))
    return not bad


def scopes_in_db() -> set[str]:
    """Qué partes del corpus están indexadas (para no fallar por lo que falta)."""
    import sqlite3

    with m.connect() as con:
        return {r[0] for r in con.execute("SELECT DISTINCT scope FROM chunks")}


def main() -> int:
    scopes = scopes_in_db()
    has_guide = "guide" in scopes
    has_api = "api" in scopes
    if not has_api:
        print("aviso: el índice no tiene API; se omiten esas comprobaciones")
    if not has_guide:
        print("aviso: el índice no tiene guía; se omiten esas comprobaciones")

    failures = 0
    for query, expect in (SEARCH_CASES if has_guide else []):
        failures += not check(f"search: {query}", m.anylogic_search(query, limit=3), expect)
    for symbol, expect in (API_CASES if has_api else []):
        failures += not check(f"api: {symbol}", m.anylogic_api(symbol, max_chars=4000), expect)
    tool_cases = [c for c in TOOL_CASES if has_guide or c[0] != "anylogic_read sección"]
    tool_cases = [c for c in tool_cases if has_guide or c[0] != "anylogic_examples"]
    for name, fn in tool_cases:
        try:
            failures += not check(name, fn())
        except Exception as e:  # noqa: BLE001
            print(f"FAIL  {name}: {e}")
            failures += 1

    total = (
        (len(SEARCH_CASES) if has_guide else 0)
        + (len(API_CASES) if has_api else 0)
        + len(tool_cases)
    )
    print(f"\n{total - failures}/{total} correctos")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
