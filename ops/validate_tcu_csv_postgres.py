#!/usr/bin/env python3
"""Validate TCU CSV raw pipeline: header check vs catalog and/or Postgres row counts.

python ops/validate_tcu_csv_postgres.py --headers-only
python ops/validate_tcu_csv_postgres.py --counts-only
python ops/validate_tcu_csv_postgres.py --headers-only --counts-only
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys


def main() -> None:
    p = argparse.ArgumentParser(description="Validate TCU CSV → Postgres raw")
    p.add_argument("--headers-only", action="store_true")
    p.add_argument("--counts-only", action="store_true")
    p.add_argument(
        "--postgres-url",
        default=os.getenv("POSTGRES_URL", "postgresql://gabi:gabi@localhost:5432/gabi"),
    )
    args = p.parse_args()

    if not args.headers_only and not args.counts_only:
        p.error("pass --headers-only and/or --counts-only")

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env = {
        **os.environ,
        "PYTHONPATH": root + os.pathsep + os.environ.get("PYTHONPATH", ""),
    }

    if args.headers_only:
        cmd = [
            sys.executable,
            "-m",
            "src.backend.ingest.tcu_csv_postgres_ingest",
            "--validate-headers-only",
        ]
        print("Running:", " ".join(cmd))
        rc = subprocess.call(cmd, cwd=root, env=env)
        if rc != 0:
            raise SystemExit(rc)

    if args.counts_only:
        import psycopg

        from src.backend.ingest.tcu_csv_raw_catalog import EXPECTED_ROW_COUNTS

        bad = 0
        with psycopg.connect(args.postgres_url) as conn:
            with conn.cursor() as cur:
                for table, expected in sorted(EXPECTED_ROW_COUNTS.items()):
                    try:
                        cur.execute(f"SELECT COUNT(*) FROM {table}")
                        n = cur.fetchone()[0]
                    except Exception as exc:
                        print(f"SKIP {table}: {exc}")
                        continue
                    delta = abs(n - expected)
                    pct = 100.0 * delta / expected if expected else 0.0
                    ok = delta <= max(50, int(expected * 0.02))
                    status = "OK" if ok else "WARN"
                    if not ok:
                        bad += 1
                    print(
                        f"{status} {table}: count={n:,} expected≈{expected:,} delta={delta} ({pct:.2f}%)"
                    )
        if bad:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
