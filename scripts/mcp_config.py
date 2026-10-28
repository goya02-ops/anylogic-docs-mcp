#!/usr/bin/env python3
"""Genera la configuración MCP de anylogic-docs-mcp para cada cliente.

El servidor habla stdio, así que todos los clientes hacen lo mismo: lanzar
`<repo>/.venv/bin/python <repo>/server/main.py`. Lo único que cambia es el
formato del fichero (JSON, TOML) y dónde vive.

Uso:
    python scripts/mcp_config.py --list
    python scripts/mcp_config.py opencode
    python scripts/mcp_config.py claude cursor vscode codex antigravity
    python scripts/mcp_config.py --apply            # detecta y registra
    python scripts/mcp_config.py --apply cursor     # solo ese
    python scripts/mcp_config.py --wsl codex        # agente en Windows, repo en WSL
    python scripts/mcp_config.py --dry-run --apply  # enseña, no toca nada
    python scripts/mcp_config.py --check            # valida lo que generaría

No requiere red ni dependencias fuera de la biblioteca estándar.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAME = "anylogic-docs"
PY = ROOT / ".venv" / "bin" / "python"
SERVER = ROOT / "server" / "main.py"

CLIENTS = ("opencode", "claude", "codex", "cursor", "vscode", "antigravity", "generic")

TITLES = {
    "opencode": "opencode",
    "claude": "Claude Code",
    "codex": "Codex CLI",
    "cursor": "Cursor",
    "vscode": "VS Code (Copilot Chat)",
    "antigravity": "Google Antigravity (IDE y CLI)",
    "generic": "cualquier cliente con JSON (mcpServers)",
}


# --------------------------------------------------------------------------- rutas
def vscode_user_dir() -> Path:
    """Carpeta de usuario de VS Code según el sistema."""
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/Code/User"
    if os.name == "nt":
        base = os.environ.get("APPDATA", str(Path.home() / "AppData/Roaming"))
        return Path(base) / "Code/User"
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "Code/User"


def config_path(client: str) -> Path | None:
    """Fichero que edita cada cliente (None si se registra por CLI)."""
    home = Path.home()
    if client == "cursor":
        return home / ".cursor" / "mcp.json"
    if client == "vscode":
        return vscode_user_dir() / "mcp.json"
    if client == "antigravity":
        return home / ".gemini" / "config" / "mcp_config.json"
    if client == "codex":
        return Path(os.environ.get("CODEX_HOME", home / ".codex")) / "config.toml"
    return None


def detect() -> list[str]:
    """Clientes que parecen instalados en esta máquina."""
    home = Path.home()
    found = []
    if shutil.which("opencode") or (home / ".config/opencode").is_dir():
        found.append("opencode")
    if shutil.which("claude") or (home / ".claude.json").exists():
        found.append("claude")
    if shutil.which("codex") or Path(os.environ.get("CODEX_HOME", home / ".codex")).is_dir():
        found.append("codex")
    if (home / ".cursor").is_dir():
        found.append("cursor")
    if vscode_user_dir().is_dir():
        found.append("vscode")
    if (home / ".gemini").is_dir():
        found.append("antigravity")
    return found


def command(wsl: bool, distro: str) -> tuple[str, list[str]]:
    """Comando + argumentos que lanzan el servidor."""
    if wsl:
        # El agente corre en Windows y el repo dentro de WSL.
        return "wsl.exe", ["-d", distro, "--", str(PY), str(SERVER)]
    return str(PY), [str(SERVER)]


def entry(wsl: bool, distro: str) -> dict:
    cmd, args = command(wsl, distro)
    return {"command": cmd, "args": args}


# --------------------------------------------------------------------------- render
def render_opencode(wsl: bool, distro: str) -> str:
    cmd, args = command(wsl, distro)
    joined = " ".join([cmd, *args])
    payload = {"mcp": {"servers": {NAME: {"type": "local", "command": [cmd, *args]}}}}
    return f"""# 1) por CLI (escribe en la config global)
opencode mcp add {NAME} --global -- {joined}

# 2) o a mano en ~/.config/opencode/opencode.json
{json.dumps(payload, indent=2, ensure_ascii=False)}

# comprobar (desde la carpeta del repo)
opencode mcp list"""


def render_claude(wsl: bool, distro: str) -> str:
    cmd, args = command(wsl, distro)
    joined = " ".join([cmd, *args])
    payload = {"mcpServers": {NAME: {"type": "stdio", "command": cmd, "args": args}}}
    return f"""# por CLI, ámbito de usuario (disponible en todos los proyectos)
claude mcp add {NAME} -s user -- {joined}

# o a mano en ~/.claude.json
{json.dumps(payload, indent=2, ensure_ascii=False)}

# comprobar
claude mcp list"""


def render_codex(wsl: bool, distro: str) -> str:
    cmd, args = command(wsl, distro)
    joined = " ".join([cmd, *args])
    args_toml = ", ".join(json.dumps(a) for a in args)
    return f"""# por CLI
codex mcp add {NAME} -- {joined}

# o a mano en ~/.codex/config.toml
[mcp_servers.{NAME}]
command = {json.dumps(cmd)}
args = [{args_toml}]

# comprobar
codex mcp list"""


def render_cursor(wsl: bool, distro: str) -> str:
    payload = json_payload("cursor", wsl, distro)
    return f"""# en {config_path('cursor')}
{json.dumps(payload, indent=2, ensure_ascii=False)}

# luego: Cursor > Settings > MCP y activa "{NAME}\""""


def render_vscode(wsl: bool, distro: str) -> str:
    payload = json_payload("vscode", wsl, distro)
    return f"""# en {config_path('vscode')}
{json.dumps(payload, indent=2, ensure_ascii=False)}

# luego: Ctrl+Shift+P > "MCP: List Servers" y arráncalo
# (o añádelo al .vscode/mcp.json del proyecto)"""


def render_antigravity(wsl: bool, distro: str) -> str:
    payload = json_payload("antigravity", wsl, distro)
    return f"""# en {config_path('antigravity')}  (global, vale para IDE y CLI)
{json.dumps(payload, indent=2, ensure_ascii=False)}

# o por workspace en <proyecto>/.agents/mcp_config.json
# ojo: no añadas "type" en este fichero"""


def render_generic(wsl: bool, distro: str) -> str:
    payload = json_payload("generic", wsl, distro)
    return json.dumps(payload, indent=2, ensure_ascii=False)


def json_payload(client: str, wsl: bool, distro: str) -> dict:
    """Estructura exacta que espera cada cliente con fichero JSON."""
    e = entry(wsl, distro)
    if client == "vscode":
        return {"servers": {NAME: {"type": "stdio", **e}}}
    return {"mcpServers": {NAME: e}}


RENDERERS = {
    "opencode": render_opencode,
    "claude": render_claude,
    "codex": render_codex,
    "cursor": render_cursor,
    "vscode": render_vscode,
    "antigravity": render_antigravity,
    "generic": render_generic,
}


# --------------------------------------------------------------------------- apply
def warn(msg: str) -> None:
    print(f"aviso: {msg}", file=sys.stderr)


def run(cmd: list[str], dry: bool) -> bool:
    printable = " ".join(cmd)
    if dry:
        print(f"  $ {printable}")
        return True
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except FileNotFoundError:
        return False
    if res.returncode != 0:
        warn(f"falló: {printable}\n{res.stderr.strip()[:400]}")
        return False
    print(f"  ok: {printable}")
    return True


def merge_json(path: Path, top_key: str, node: dict, dry: bool) -> bool:
    """Añade/actualiza el servidor sin tocar el resto del fichero."""
    if dry:
        print(f"  escribiría {path}: {json.dumps({top_key: {NAME: node}}, ensure_ascii=False)}")
        return True

    data: dict = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8") or "{}")
        except json.JSONDecodeError as exc:
            warn(f"{path} no es JSON válido ({exc}); no lo toco")
            return False
        if not isinstance(data, dict):
            warn(f"{path} no contiene un objeto JSON; no lo toco")
            return False
        backup = path.with_suffix(path.suffix + ".bak")
        shutil.copy2(path, backup)
        print(f"  copia de seguridad: {backup}")

    servers = data.setdefault(top_key, {})
    if not isinstance(servers, dict):
        warn(f"'{top_key}' en {path} no es un objeto; no lo toco")
        return False
    servers[NAME] = node

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"  escrito: {path}")
    return True


def merge_toml(path: Path, cmd: str, args: list[str], dry: bool) -> bool:
    """Añade la sección [mcp_servers.anylogic-docs] si no está ya."""
    section = f"[mcp_servers.{NAME}]"
    args_toml = ", ".join(json.dumps(a) for a in args)
    block = f"\n{section}\ncommand = {json.dumps(cmd)}\nargs = [{args_toml}]\n"
    if dry:
        print(f"  añadiría a {path}:{block}")
        return True

    text = path.read_text(encoding="utf-8") if path.exists() else ""
    if section in text:
        print(f"  ya existe {section} en {path}; no lo toco")
        return True
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        backup = path.with_suffix(path.suffix + ".bak")
        shutil.copy2(path, backup)
        print(f"  copia de seguridad: {backup}")
    path.write_text(text.rstrip() + "\n" + block, encoding="utf-8")
    print(f"  escrito: {path}")
    return True


def apply(client: str, wsl: bool, distro: str, dry: bool) -> bool:
    cmd, args = command(wsl, distro)
    print(f"\n[{TITLES[client]}]")
    if client == "opencode":
        if not shutil.which("opencode"):
            warn("no encontré el binario 'opencode'")
            return False
        return run(["opencode", "mcp", "add", NAME, "--global", "--", cmd, *args], dry)
    if client == "claude":
        if not shutil.which("claude"):
            warn("no encontré el binario 'claude'")
            return False
        return run(["claude", "mcp", "add", NAME, "-s", "user", "--", cmd, *args], dry)
    if client == "codex":
        if shutil.which("codex"):
            return run(["codex", "mcp", "add", NAME, "--", cmd, *args], dry)
        warn("no encontré el binario 'codex'; escribo el TOML a mano")
        return merge_toml(config_path("codex"), cmd, args, dry)
    if client in ("cursor", "antigravity", "vscode"):
        payload = json_payload(client, wsl, distro)
        top_key = "servers" if client == "vscode" else "mcpServers"
        return merge_json(config_path(client), top_key, payload[top_key][NAME], dry)
    warn(f"'{client}' no se puede registrar automáticamente; copia el JSON a mano")
    return False


# --------------------------------------------------------------------------- main
def check(wsl: bool, distro: str) -> int:
    """Valida que todo lo generado es coherente (sin tocar configuración)."""
    failures = 0
    if not PY.exists():
        print(f"aviso: no existe {PY} (¿falta ./install.sh?)")
    if not SERVER.exists():
        print(f"error: no existe {SERVER}")
        failures += 1

    for client in CLIENTS:
        text = RENDERERS[client](wsl, distro)
        if client in ("opencode", "claude", "codex"):
            if "wsl.exe" in text or str(PY) in text:
                print(f"ok    config: {client}")
            else:
                print(f"FALLO config: {client}")
                failures += 1
            continue
        payload = json_payload(client, wsl, distro)
        server = payload.get("servers", payload.get("mcpServers", {})).get(NAME)
        if not server or not server.get("command") or not server.get("args"):
            print(f"FALLO config: {client}: entrada incompleta")
            failures += 1
            continue
        try:
            json.dumps(payload)
            print(f"ok    config: {client}")
        except (TypeError, ValueError) as exc:
            print(f"FALLO config: {client}: {exc}")
            failures += 1
    return failures


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Configura anylogic-docs-mcp en tu cliente MCP",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("clients", nargs="*", choices=CLIENTS, metavar="cliente")
    ap.add_argument("--list", action="store_true", help="lista los clientes soportados")
    ap.add_argument("--apply", action="store_true", help="registra el servidor (no solo imprimir)")
    ap.add_argument("--dry-run", action="store_true", help="con --apply: enseña qué haría")
    ap.add_argument("--wsl", action="store_true", help="agente en Windows, repo dentro de WSL")
    ap.add_argument(
        "--distro",
        default=os.environ.get("WSL_DISTRO_NAME", "Ubuntu"),
        help="distribución de WSL (por defecto Ubuntu)",
    )
    ap.add_argument("--check", action="store_true", help="valida la configuración generada")
    args = ap.parse_args()

    if args.check:
        return 1 if check(args.wsl, args.distro) else 0

    if args.list:
        print("Clientes soportados:\n")
        for c in CLIENTS:
            where = config_path(c)
            dest = f" → {where}" if where else " → por CLI"
            print(f"  {c:<12} {TITLES[c]}{dest}")
        print("\nUso: python scripts/mcp_config.py <cliente> [--wsl]")
        return 0

    if args.apply:
        targets = args.clients or detect()
        if not targets:
            warn(
                "no detecté ningún cliente MCP instalado.\n"
                "  Indica uno a mano:  python scripts/mcp_config.py --apply cursor\n"
                "  o copia el JSON de: python scripts/mcp_config.py cursor"
            )
            return 1
        print("clientes detectados: " + ", ".join(targets))
        ok = 0
        for c in targets:
            if c == "generic":
                continue
            if apply(c, args.wsl, args.distro, args.dry_run):
                ok += 1
        if ok == 0:
            warn("no se registró nada; usa --print para copiar el JSON a mano")
            return 1
        print("\nReinicia el cliente y pide a la IA que use anylogic_version().")
        return 0

    if not PY.exists():
        warn(f"no existe {PY}; ejecuta ./install.sh antes de registrar el servidor")

    targets = args.clients or ["generic"]
    for c in targets:
        if len(targets) > 1:
            print(f"\n=== {TITLES[c]} " + "=" * max(0, 60 - len(TITLES[c])))
        print(RENDERERS[c](args.wsl, args.distro))
    return 0


if __name__ == "__main__":
    sys.exit(main())
