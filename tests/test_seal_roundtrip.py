#!/usr/bin/env python3
"""Integration test: ingest_batch_sealed() → hostile_verify.py round-trip.

Requires: running PostgreSQL on port 5433 with registry schema applied.

Steps:
  1. Reset registry tables (truncate via SERIALIZABLE to bypass immutability triggers)
  2. Create synthetic enriched JSON files
  3. Call ingest_batch_sealed() → must return commitment_sealed=True
  4. Dump canonical records via commitment CLI
  5. Run hostile_verify.py against the envelope + records
  6. Verify everything matches

Usage:
    .venv/bin/python3 test_seal_roundtrip.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

# Ensure project root is on sys.path when running as standalone script
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import psycopg

DSN = os.environ.get("GABI_DSN", "host=localhost port=5433 dbname=gabi user=gabi password=gabi")
SOURCES_YAML = Path("sources_v3.yaml")
IDENTITY_YAML = Path("sources_v3.identity-test.yaml")
VENV_PYTHON = Path(".venv/bin/python3")


def _log(msg: str) -> None:
    print(f"  {msg}", file=sys.stderr, flush=True)


def reset_registry(dsn: str) -> None:
    """Truncate all registry tables. Must disable triggers temporarily."""
    with psycopg.connect(dsn) as conn:
        conn.execute("SET search_path = registry, public")
        # Disable triggers to allow truncate on immutable tables
        conn.execute("ALTER TABLE registry.commitments DISABLE TRIGGER ALL")
        conn.execute("ALTER TABLE registry.ingestion_log DISABLE TRIGGER ALL")
        conn.execute("ALTER TABLE registry.occurrences DISABLE TRIGGER ALL")
        conn.execute("ALTER TABLE registry.versions DISABLE TRIGGER ALL")
        conn.execute("ALTER TABLE registry.concepts DISABLE TRIGGER ALL")
        conn.execute("ALTER TABLE registry.editions DISABLE TRIGGER ALL")
        conn.execute("TRUNCATE registry.commitments, registry.ingestion_log, registry.occurrences, registry.versions, registry.concepts, registry.editions CASCADE")
        conn.execute("ALTER TABLE registry.editions ENABLE TRIGGER ALL")
        conn.execute("ALTER TABLE registry.concepts ENABLE TRIGGER ALL")
        conn.execute("ALTER TABLE registry.versions ENABLE TRIGGER ALL")
        conn.execute("ALTER TABLE registry.occurrences ENABLE TRIGGER ALL")
        conn.execute("ALTER TABLE registry.ingestion_log ENABLE TRIGGER ALL")
        conn.execute("ALTER TABLE registry.commitments ENABLE TRIGGER ALL")
        conn.commit()


def create_synthetic_enriched(out_dir: Path) -> None:
    """Create enriched JSON files matching the format expected by _load_ingest_records."""
    docs = [
        {
            "file": "page1.html",
            "page_url": "https://www.in.gov.br/leiturajornal?data=2024-03-10&secao=do1",
            "publication_issue": {
                "publication_date": "2024-03-10",
                "edition_number": "48",
                "edition_section": "S1",
                "page_number": "12",
            },
            "documents": [
                {
                    "document": {
                        "document_type": "Portaria",
                        "document_number": "123",
                        "document_year": "2024",
                        "issuing_organ": "Ministério da Fazenda",
                        "title": "Portaria nº 123, de 9 de março de 2024",
                        "body_text": "O MINISTRO DE ESTADO DA FAZENDA resolve: Art. 1º Fica aprovado o regulamento. Art. 2º Esta portaria entra em vigor na data de sua publicação.",
                    }
                }
            ],
        },
        {
            "file": "page2.html",
            "page_url": "https://www.in.gov.br/leiturajornal?data=2024-03-10&secao=do1",
            "publication_issue": {
                "publication_date": "2024-03-10",
                "edition_number": "48",
                "edition_section": "S1",
                "page_number": "15",
            },
            "documents": [
                {
                    "document": {
                        "document_type": "Decreto",
                        "document_number": "11999",
                        "document_year": "2024",
                        "issuing_organ": "Presidência da República",
                        "title": "Decreto nº 11.999, de 9 de março de 2024",
                        "body_text": "A PRESIDENTA DA REPÚBLICA, no uso das atribuições que lhe confere o art. 84, inciso IV, da Constituição, decreta: Art. 1º Fica instituído o Programa Nacional de Transparência.",
                    }
                }
            ],
        },
        {
            "file": "page3.html",
            "page_url": "https://www.in.gov.br/leiturajornal?data=2024-03-11&secao=do1",
            "publication_issue": {
                "publication_date": "2024-03-11",
                "edition_number": "49",
                "edition_section": "S1",
                "page_number": "3",
            },
            "documents": [
                {
                    "document": {
                        "document_type": "Portaria",
                        "document_number": "123",
                        "document_year": "2024",
                        "issuing_organ": "Ministério da Fazenda",
                        "title": "Portaria nº 123, de 9 de março de 2024 (Republicação)",
                        "body_text": "O MINISTRO DE ESTADO DA FAZENDA resolve: Art. 1º Fica aprovado o regulamento revisado. Art. 2º Esta portaria entra em vigor na data de sua publicação.",
                    }
                }
            ],
        },
        # Duplicate of first doc — should be duplicate_skipped
        {
            "file": "page1_dup.html",
            "page_url": "https://www.in.gov.br/leiturajornal?data=2024-03-10&secao=do1",
            "publication_issue": {
                "publication_date": "2024-03-10",
                "edition_number": "48",
                "edition_section": "S1",
                "page_number": "12",
            },
            "documents": [
                {
                    "document": {
                        "document_type": "Portaria",
                        "document_number": "123",
                        "document_year": "2024",
                        "issuing_organ": "Ministério da Fazenda",
                        "title": "Portaria nº 123, de 9 de março de 2024",
                        "body_text": "O MINISTRO DE ESTADO DA FAZENDA resolve: Art. 1º Fica aprovado o regulamento. Art. 2º Esta portaria entra em vigor na data de sua publicação.",
                    }
                }
            ],
        },
    ]

    out_dir.mkdir(parents=True, exist_ok=True)
    for i, doc in enumerate(docs):
        fp = out_dir / f"enriched_{i:03d}.json"
        fp.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")


def main() -> None:
    passed = 0
    failed = 0

    def check(label: str, condition: bool, detail: str = "") -> None:
        nonlocal passed, failed
        if condition:
            print(f"  PASS  {label}")
            passed += 1
        else:
            print(f"  FAIL  {label}  {detail}")
            failed += 1

    print("=" * 60)
    print("Integration Test: ingest_batch_sealed → hostile_verify")
    print("=" * 60)

    # Step 1: Reset registry
    print("\n[1] Reset registry tables")
    reset_registry(DSN)
    _log("registry truncated")

    with psycopg.connect(DSN) as conn:
        conn.execute("SET search_path = registry, public")
        r = conn.execute("SELECT count(*) FROM registry.ingestion_log").fetchone()
        check("registry empty after reset", r[0] == 0, f"got {r[0]}")

    # Step 2: Create synthetic enriched data
    print("\n[2] Create synthetic enriched data")
    with tempfile.TemporaryDirectory() as tmpdir:
        enriched_dir = Path(tmpdir) / "enriched"
        create_synthetic_enriched(enriched_dir)
        files = list(enriched_dir.glob("*.json"))
        check(f"created {len(files)} enriched files", len(files) == 4)

        # Step 3: Run ingest_batch_sealed
        print("\n[3] Run ingest_batch_sealed()")
        from ingest.identity_analyzer import load_identity_config
        from dbsync.registry_ingest import ingest_batch_sealed, IngestionUnsealedError

        cfg = load_identity_config(IDENTITY_YAML)
        result = ingest_batch_sealed(
            DSN,
            enriched_dir,
            cfg,
            sources_yaml=SOURCES_YAML,
            identity_yaml=IDENTITY_YAML,
        )

        check("no errors", len(result.errors) == 0, f"errors={result.errors}")
        check("commitment_sealed is True", result.commitment_sealed)
        check("commitment_root is set", result.commitment_root is not None and len(result.commitment_root) == 64,
              f"got {result.commitment_root}")
        check("log_high_water > 0", result.log_high_water > 0, f"got {result.log_high_water}")
        check(f"total={result.total}", result.total == 4)
        check(f"inserted > 0", result.inserted > 0, f"inserted={result.inserted}")
        check(f"duplicate_skipped > 0", result.duplicate_skipped > 0,
              f"dup={result.duplicate_skipped}")

        _log(f"result: inserted={result.inserted} dup={result.duplicate_skipped} "
             f"new_ver={result.new_version} new_pub={result.new_publication}")

        # Step 4: Verify commitment persisted to DB
        print("\n[4] Verify commitment in registry.commitments")
        with psycopg.connect(DSN) as conn:
            conn.execute("SET search_path = registry, public")
            r = conn.execute("SELECT count(*) FROM registry.commitments").fetchone()
            check("commitments row count = 1", r[0] == 1, f"got {r[0]}")

            r = conn.execute(
                "SELECT commitment_root, record_count, log_high_water FROM registry.commitments ORDER BY id DESC LIMIT 1"
            ).fetchone()
            check("DB root matches result", r[0].strip() == result.commitment_root,
                  f"db={r[0].strip()} result={result.commitment_root}")
            check("DB log_high_water matches", r[2] == result.log_high_water,
                  f"db={r[2]} result={result.log_high_water}")

        # Step 5: Dump canonical records + envelope via commitment_cli
        print("\n[5] Dump canonical records for hostile verification")
        envelope_path = Path(tmpdir) / "envelope.json"
        records_path = Path(tmpdir) / "canonical_records.txt"

        from commitment.anchor import anchor_to_file
        envelope = anchor_to_file(
            DSN,
            envelope_path,
            sources_yaml=SOURCES_YAML,
            identity_yaml=IDENTITY_YAML,
            dump_records_path=records_path,
            persist_to_db=False,  # already persisted in step 3
        )
        check("envelope written", envelope_path.exists())
        check("canonical records written", records_path.exists())
        check("envelope root matches sealed root",
              envelope["commitment_root"] == result.commitment_root,
              f"envelope={envelope['commitment_root'][:16]} sealed={result.commitment_root[:16]}")

        # Step 6: Run hostile_verify.py
        print("\n[6] Hostile verification (independent verifier)")
        python = str(VENV_PYTHON) if VENV_PYTHON.exists() else sys.executable
        proc = subprocess.run(
            [python, "hostile_verify.py", str(records_path), str(envelope_path)],
            capture_output=True,
            text=True,
        )
        # Print hostile verifier output
        for line in proc.stdout.strip().split("\n"):
            _log(line)

        check("hostile_verify.py exit code = 0 (PASS)", proc.returncode == 0,
              f"exit={proc.returncode}\nstderr={proc.stderr}")

    # Summary
    print(f"\n{'=' * 60}")
    print(f"  Results: {passed}/{passed + failed} passed, {failed} failed")
    print(f"{'=' * 60}")
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
