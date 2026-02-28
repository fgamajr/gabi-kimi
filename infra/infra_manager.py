"""CLI entrypoint for Postgres appliance lifecycle control."""

from __future__ import annotations

import argparse
import json
import sys

from db_control import InfraError, PostgresAppliance


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Programmatic Postgres appliance controller")
    p.add_argument("command", choices=["up", "down", "destroy", "reset_db", "recreate", "status"])
    return p


def main() -> int:
    args = build_parser().parse_args()
    appliance = PostgresAppliance()

    try:
        if args.command == "up":
            out = appliance.up()
        elif args.command == "down":
            out = appliance.down()
        elif args.command == "destroy":
            out = appliance.destroy()
        elif args.command == "reset_db":
            out = appliance.reset_db()
        elif args.command == "recreate":
            out = appliance.recreate()
        else:
            out = appliance.status()
    except InfraError as ex:
        print(json.dumps({"ok": False, "error": str(ex)}))
        return 1

    print(json.dumps({"ok": True, "result": out}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
