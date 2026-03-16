#!/usr/bin/env python3
"""Install repo-local MCP client entries for desktop editors.

Targets:
- Zed user settings on macOS
- Kiro/Kilo MCP settings on Linux/macOS

Usage:
  python3 ops/bin/install_repo_mcp_clients.py
  python3 ops/bin/install_repo_mcp_clients.py --home /tmp/fake-home
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"Expected JSON object in {path}")
    return data


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


def _gabi_es_entry(repo_root: Path) -> dict[str, Any]:
    return {
        "command": "bash",
        "args": [str(repo_root / "ops/bin/run_mcp_gabi_es.sh")],
    }


def install_kiro_like(path: Path, entry: dict[str, Any]) -> None:
    data = _load_json(path)
    servers = data.setdefault("mcpServers", {})
    if not isinstance(servers, dict):
        raise RuntimeError(f"Expected mcpServers object in {path}")
    servers["gabi-es"] = entry
    _write_json(path, data)


def install_zed(path: Path, entry: dict[str, Any]) -> None:
    data = _load_json(path)
    servers = data.setdefault("context_servers", {})
    if not isinstance(servers, dict):
        raise RuntimeError(f"Expected context_servers object in {path}")
    servers["gabi-es"] = {
        "command": entry["command"],
        "args": entry["args"],
    }
    _write_json(path, data)


def main() -> None:
    parser = argparse.ArgumentParser(description="Install repo-local MCP entries for Zed and Kiro/Kilo.")
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

    zed_settings = home / "Library/Application Support/Zed/settings.json"
    if args.create_missing or zed_settings.parent.exists():
        install_zed(zed_settings, entry)
        touched.append(zed_settings)

    kiro_settings = home / ".kiro/settings/mcp.json"
    if args.create_missing or kiro_settings.parent.exists():
        install_kiro_like(kiro_settings, entry)
        touched.append(kiro_settings)

    kilo_settings = home / ".kilo/settings/mcp.json"
    if args.create_missing or kilo_settings.parent.exists():
        install_kiro_like(kilo_settings, entry)
        touched.append(kilo_settings)

    for path in touched:
        print(path)


if __name__ == "__main__":
    main()
