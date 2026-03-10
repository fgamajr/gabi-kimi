#!/usr/bin/env python3
"""CLI for CRSS-1 commitment operations.

Commands:
    compute   Compute commitment from registry and write envelope
    verify    Verify registry against a published envelope

Usage:
    python3 ops/bin/commitment_cli.py compute --dsn "..." --out envelope.json
    python3 ops/bin/commitment_cli.py verify  --dsn "..." --envelope envelope.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def _resolve_dsn(args: argparse.Namespace) -> str:
    dsn = getattr(args, "dsn", None) or os.environ.get("GABI_DSN", "")
    if not dsn:
        print("ERROR: --dsn or GABI_DSN environment variable required", file=sys.stderr)
        sys.exit(1)
    return dsn


def cmd_compute(args: argparse.Namespace) -> None:
    from src.backend.commitment.anchor import anchor_to_file

    dsn = _resolve_dsn(args)
    out = Path(args.out)
    sources = Path(args.sources) if args.sources else None
    identity = Path(args.identity) if args.identity else None
    dump = Path(args.dump_records) if args.dump_records else None

    envelope = anchor_to_file(
        dsn,
        out,
        sources_yaml=sources,
        identity_yaml=identity,
        dump_records_path=dump,
        persist_to_db=not args.no_persist,
    )
    print(json.dumps(envelope, indent=2))


def cmd_verify(args: argparse.Namespace) -> None:
    from src.backend.commitment.verify import verify_against_envelope

    dsn = _resolve_dsn(args)
    sources = Path(args.sources) if args.sources else None
    identity = Path(args.identity) if args.identity else None

    result = verify_against_envelope(
        dsn,
        Path(args.envelope),
        sources_yaml=sources,
        identity_yaml=identity,
    )

    status = "PASS" if result.matches else "FAIL"
    print(
        f"{status} "
        f"expected={result.expected_root[:16]}... "
        f"computed={result.computed_root[:16]}... "
        f"records_expected={result.expected_count} "
        f"records_computed={result.computed_count}"
    )

    if not result.matches:
        print("\nDiagnostics:", file=sys.stderr)
        for k, v in result.details.items():
            print(f"  {k}: {v}", file=sys.stderr)

    sys.exit(0 if result.matches else 1)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="CRSS-1 commitment operations",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command")

    # compute
    p_compute = sub.add_parser("compute", help="Compute commitment from registry")
    p_compute.add_argument("--dsn", help="PostgreSQL DSN (or set GABI_DSN)")
    p_compute.add_argument("--out", required=True, help="Output envelope JSON path")
    p_compute.add_argument("--sources", help="Path to sources YAML (for interpretation contract)")
    p_compute.add_argument("--identity", help="Path to identity YAML (for interpretation contract)")
    p_compute.add_argument("--dump-records", help="Debug: dump canonical record lines to file")
    p_compute.add_argument(
        "--no-persist", action="store_true", help="Do not persist commitment to registry.commitments"
    )

    # verify
    p_verify = sub.add_parser("verify", help="Verify registry against published envelope")
    p_verify.add_argument("--dsn", help="PostgreSQL DSN (or set GABI_DSN)")
    p_verify.add_argument("--envelope", required=True, help="Published envelope JSON path")
    p_verify.add_argument("--sources", help="Path to sources YAML (for contract check)")
    p_verify.add_argument("--identity", help="Path to identity YAML (for contract check)")

    args = parser.parse_args()
    if args.command == "compute":
        cmd_compute(args)
    elif args.command == "verify":
        cmd_verify(args)
    else:
        parser.print_help()
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
