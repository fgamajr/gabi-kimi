#!/usr/bin/env python3
"""Install repo-local MCP client entries for machine-local AI clients.

Targets:
- Claude Desktop
- Codex CLI / app
- VS Code
- Cursor
- Gemini CLI
- Kimi CLI
- Qwen Code
- Zed
- Kiro / Kilo

Usage:
  docker compose run --rm -T -v "$HOME:/host-home" backend \
    python ops/bin/install_repo_mcp_clients.py --home /host-home --repo-root "$PWD"
"""

from __future__ import annotations

import argparse
import json
import re
import tomllib
from pathlib import Path
from typing import Any


def _map_symlink_target_into_home(target: Path, mounted_home: Path) -> Path:
    if not target.is_absolute():
        return target
    if target.exists():
        return target
    parts = target.parts
    if len(parts) >= 3 and parts[1] in {"Users", "home"}:
        return mounted_home / Path(*parts[3:])
    return target


def _materialize_path(path: Path, mounted_home: Path) -> Path:
    if not path.is_symlink():
        return path
    target = path.readlink()
    if not target.is_absolute():
        return path.parent / target
    return _map_symlink_target_into_home(target, mounted_home)


def _strip_json_comments(text: str) -> str:
    out: list[str] = []
    in_string = False
    string_char = ""
    escaped = False
    i = 0

    while i < len(text):
        ch = text[i]
        nxt = text[i + 1] if i + 1 < len(text) else ""
        if in_string:
            out.append(ch)
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == string_char:
                in_string = False
            i += 1
            continue

        if ch in {'"', "'"}:
            in_string = True
            string_char = ch
            out.append(ch)
            i += 1
            continue

        if ch == "/" and nxt == "/":
            i += 2
            while i < len(text) and text[i] not in "\r\n":
                i += 1
            continue

        if ch == "/" and nxt == "*":
            i += 2
            while i + 1 < len(text) and not (text[i] == "*" and text[i + 1] == "/"):
                i += 1
            i += 2 if i + 1 < len(text) else 0
            continue

        out.append(ch)
        i += 1

    return "".join(out)


def _strip_trailing_json_commas(text: str) -> str:
    out: list[str] = []
    in_string = False
    string_char = ""
    escaped = False
    i = 0

    while i < len(text):
        ch = text[i]
        if in_string:
            out.append(ch)
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == string_char:
                in_string = False
            i += 1
            continue

        if ch in {'"', "'"}:
            in_string = True
            string_char = ch
            out.append(ch)
            i += 1
            continue

        if ch == ",":
            j = i + 1
            while j < len(text) and text[j] in " \t\r\n":
                j += 1
            if j < len(text) and text[j] in "]}":
                i += 1
                continue

        out.append(ch)
        i += 1

    return "".join(out)


def _load_json(path: Path, *, allow_jsonc: bool = False) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        raw = path.read_text(encoding="utf-8")
        if allow_jsonc:
            raw = _strip_trailing_json_commas(_strip_json_comments(raw))
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"Expected JSON object in {path}")
    return data


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


def _gabi_es_entry(repo_root: Path) -> dict[str, Any]:
    compose_file = repo_root / "docker-compose.yml"
    return {
        "command": "docker",
        "args": [
            "compose",
            "-f",
            str(compose_file),
            "run",
            "--rm",
            "-T",
            "backend",
            "python",
            "ops/bin/mcp_es_server.py",
        ],
    }


def _set_json_server(path: Path, top_level_key: str, server_key: str, entry: dict[str, Any], *, allow_jsonc: bool = False) -> None:
    data = _load_json(path, allow_jsonc=allow_jsonc)
    servers = data.setdefault(top_level_key, {})
    if not isinstance(servers, dict):
        raise RuntimeError(f"Expected {top_level_key} object in {path}")
    servers[server_key] = entry
    _write_json(path, data)


def install_kiro_like(path: Path, entry: dict[str, Any]) -> None:
    _set_json_server(path, "mcpServers", "gabi-es", entry)


def install_claude_desktop(path: Path, entry: dict[str, Any]) -> None:
    _set_json_server(path, "mcpServers", "gabi-es", entry)


def install_cursor(path: Path, entry: dict[str, Any]) -> None:
    _set_json_server(path, "mcpServers", "gabi-es", entry)


def install_gemini(path: Path, entry: dict[str, Any]) -> None:
    _set_json_server(path, "mcpServers", "gabi-es", entry)


def install_kimi(path: Path, entry: dict[str, Any]) -> None:
    _set_json_server(path, "mcpServers", "gabi-es", entry)


def install_qwen(path: Path, entry: dict[str, Any]) -> None:
    _set_json_server(path, "mcpServers", "gabi-es", entry)


def install_vscode(path: Path, entry: dict[str, Any]) -> None:
    vscode_entry = {
        "type": "stdio",
        "command": entry["command"],
        "args": entry["args"],
    }
    _set_json_server(path, "servers", "gabi-es", vscode_entry)


def install_zed(path: Path, entry: dict[str, Any]) -> None:
    data = _load_json(path, allow_jsonc=True)
    servers = data.setdefault("context_servers", {})
    if not isinstance(servers, dict):
        raise RuntimeError(f"Expected context_servers object in {path}")
    servers["gabi-es"] = {
        "command": entry["command"],
        "args": entry["args"],
    }
    _write_json(path, data)


def _toml_string(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def install_codex(path: Path, entry: dict[str, Any]) -> None:
    if path.exists():
        raw = path.read_text(encoding="utf-8")
        tomllib.loads(raw)
    else:
        raw = ""

    block_lines = [
        "[mcp_servers.gabi-es]",
        f"command = {_toml_string(entry['command'])}",
        "args = [" + ", ".join(_toml_string(arg) for arg in entry["args"]) + "]",
    ]
    block = "\n".join(block_lines) + "\n"

    pattern = re.compile(r"(?ms)^\[mcp_servers(?:\.gabi-es|\.\"gabi-es\")\]\n.*?(?=^\[|\Z)")
    if pattern.search(raw):
        updated = pattern.sub(block, raw).rstrip() + "\n"
    else:
        updated = raw.rstrip()
        if updated:
            updated += "\n\n"
        updated += block

    tomllib.loads(updated)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(updated, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Install machine-local MCP entries for supported AI clients.")
    parser.add_argument("--home", type=Path, default=Path.home(), help="Target home directory")
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2], help="Repo root")
    parser.add_argument(
        "--create-missing",
        action="store_true",
        help="Create client config files even when their parent directories do not exist yet",
    )
    args = parser.parse_args()

    home = args.home.expanduser().resolve()
    repo_root = args.repo_root.resolve()
    entry = _gabi_es_entry(repo_root)

    touched: list[Path] = []

    zed_paths = [
        home / ".config/zed/settings.json",
        home / "Library/Application Support/Zed/settings.json",
    ]
    for zed_settings in zed_paths:
        zed_settings = _materialize_path(zed_settings, home)
        if args.create_missing or zed_settings.parent.exists():
            install_zed(zed_settings, entry)
            touched.append(zed_settings)

    kiro_settings = _materialize_path(home / ".kiro/settings/mcp.json", home)
    if args.create_missing or kiro_settings.parent.exists():
        install_kiro_like(kiro_settings, entry)
        touched.append(kiro_settings)

    kilo_settings = _materialize_path(home / ".kilo/settings/mcp.json", home)
    if args.create_missing or kilo_settings.parent.exists():
        install_kiro_like(kilo_settings, entry)
        touched.append(kilo_settings)

    claude_desktop = _materialize_path(home / "Library/Application Support/Claude/claude_desktop_config.json", home)
    if args.create_missing or claude_desktop.parent.exists():
        install_claude_desktop(claude_desktop, entry)
        touched.append(claude_desktop)

    codex_config = _materialize_path(home / ".codex/config.toml", home)
    if args.create_missing or codex_config.parent.exists():
        install_codex(codex_config, entry)
        touched.append(codex_config)

    vscode_config = _materialize_path(home / "Library/Application Support/Code/User/mcp.json", home)
    if args.create_missing or vscode_config.parent.exists():
        install_vscode(vscode_config, entry)
        touched.append(vscode_config)

    cursor_config = _materialize_path(home / ".cursor/mcp.json", home)
    if args.create_missing or cursor_config.parent.exists():
        install_cursor(cursor_config, entry)
        touched.append(cursor_config)

    gemini_config = _materialize_path(home / ".gemini/settings.json", home)
    if args.create_missing or gemini_config.parent.exists():
        install_gemini(gemini_config, entry)
        touched.append(gemini_config)

    kimi_config = _materialize_path(home / ".kimi/mcp.json", home)
    if args.create_missing or kimi_config.parent.exists():
        install_kimi(kimi_config, entry)
        touched.append(kimi_config)

    qwen_config = _materialize_path(home / ".qwen/settings.json", home)
    if args.create_missing or qwen_config.parent.exists():
        install_qwen(qwen_config, entry)
        touched.append(qwen_config)

    for path in touched:
        print(path)


if __name__ == "__main__":
    main()
