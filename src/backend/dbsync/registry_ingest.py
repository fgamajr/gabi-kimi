"""Registry ingestion engine — SERIALIZABLE CTE state machine.

Every document is ingested via ONE prepared SQL statement.
Classification is derived entirely from INSERT...ON CONFLICT...RETURNING.
No pre-reads. No fallback SELECTs. The database is the authority; Python is transport.

LIFECYCLE CONTRACT:
  A batch is COMPLETE iff a commitment exists whose:
    commitment.log_high_water_mark == max(registry.ingestion_log.id)

  Ingestion without commitment is failure.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import psycopg
from psycopg import IsolationLevel

from src.backend.commitment.anchor import compute_commitment
from src.backend.commitment.chain import chain_anchor
from src.backend.ingest.identity_analyzer import (
    IdentityConfig,
    load_identity_config,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_SERIALIZATION_RETRIES = 10

# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class IngestResult:
    total: int = 0
    inserted: int = 0
    duplicate_skipped: int = 0
    new_version: int = 0
    new_publication: int = 0
    errors: list[dict] = field(default_factory=list)
    log_high_water: int = 0
    commitment_root: str | None = None
    commitment_sealed: bool = False


# ---------------------------------------------------------------------------
# Hash helpers — reused from identity_analyzer patterns
# ---------------------------------------------------------------------------


def _sha(s: str) -> str:
    return hashlib.sha256((s or "").encode("utf-8")).hexdigest()


def _norm(v: Any) -> str:
    if v is None:
        return ""
    s = str(v).strip().lower()
    s = re.sub(r"\s+", " ", s)
    return s


def _field_value(field_name: str, doc: dict[str, str], pub: dict[str, str], source: dict[str, Any]) -> str:
    if field_name == "issuing_organ_normalized":
        return doc.get("issuing_organ") or doc.get("issuing_authority") or ""
    if field_name == "title_normalized":
        return doc.get("title") or ""
    if field_name == "body_text_first_200_chars_normalized":
        return (doc.get("body_text") or "")[:200]
    if field_name == "body_text_semantic":
        return doc.get("body_text") or ""
    if field_name == "source_url_canonical":
        u = str(source.get("page_url") or "")
        return re.sub(r"[?#].*$", "", u)
    if field_name in {
        "publication_date",
        "edition_number",
        "edition_section",
        "page_number",
    }:
        return pub.get(field_name) or ""
    if field_name in doc:
        return doc.get(field_name) or ""
    return ""


def _canonicalize_content(text: str, steps: list[str]) -> str:
    out = text or ""
    for s in steps:
        if s == "remove_signature_blocks":
            out = re.sub(r"(?is)assinado por:.*$", "", out).strip()
        elif s == "normalize_whitespace":
            out = re.sub(r"\s+", " ", out).strip()
        elif s == "normalize_quotes":
            out = out.replace("\u201c", '"').replace("\u201d", '"').replace("\u2018", "'").replace("`", "'")
        elif s == "remove_page_headers":
            out = re.sub(r"(?im)^\s*di[aá]rio oficial da uni[aã]o.*$", "", out)
    return out


def _hash_record(
    doc: dict[str, str],
    pub: dict[str, str],
    source: dict[str, Any],
    cfg: IdentityConfig,
) -> dict[str, Any]:
    """Compute natural_key_hash, content_hash, strategy, body_text_semantic."""
    strategy_name = "none"
    strategy_values: list[str] = []
    for s in cfg.strategies:
        name = str(s.get("name") or "unnamed")
        fields = list(s.get("inputs") or [])
        vals = [_field_value(f, doc, pub, source) for f in fields]
        if all(v for v in vals):
            strategy_name = name
            strategy_values = vals
            break
    natural_key_hash = _sha(strategy_name + "|" + "|".join(strategy_values))

    body_text = _field_value("body_text_semantic", doc, pub, source)
    body_text = _canonicalize_content(body_text, cfg.content_canonicalize)
    content_hash = _sha(body_text)

    return {
        "natural_key_hash": natural_key_hash,
        "content_hash": content_hash,
        "strategy": strategy_name,
        "body_text_semantic": body_text,
    }


# ---------------------------------------------------------------------------
# Evidence-anchored hashes (computed here, NOT from identity_analyzer)
# ---------------------------------------------------------------------------


def _evidence_edition_id(pub_date: str, edition_number: str, section: str, listing_sha256: str) -> str:
    """edition_id = sha256(publication_date | edition_number | section | listing_sha256)"""
    return _sha(f"{pub_date}|{edition_number}|{section}|{listing_sha256 or ''}")


def _evidence_occurrence_hash(edition_id: str, page_number: str, source_url: str) -> str:
    """occurrence_hash = sha256(edition_id | page_number | source_url_canonical)"""
    return _sha(f"{edition_id}|{page_number}|{source_url}")


def _safe_iso_date(raw: Any) -> str | None:
    """Ensure publication_date is ISO YYYY-MM-DD. Never trust upstream text."""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    # Already ISO?
    try:
        d = date.fromisoformat(s)
        return d.isoformat()
    except ValueError:
        pass
    # Brazilian DD/MM/YYYY?
    parts = s.split("/")
    if len(parts) == 3:
        try:
            d = date(int(parts[2]), int(parts[1]), int(parts[0]))
            return d.isoformat()
        except (ValueError, IndexError):
            pass
    return None


# ---------------------------------------------------------------------------
# Listing SHA-256 lookup
# ---------------------------------------------------------------------------


def load_listing_index(samples_dir: Path) -> dict[tuple[str, str], str]:
    """Load listing_sha256 map from samples/index.json.

    Returns: {(publication_date, section): listing_sha256}
    """
    index_path = samples_dir / "index.json"
    if not index_path.exists():
        return {}
    index = json.loads(index_path.read_text(encoding="utf-8"))
    result: dict[tuple[str, str], str] = {}
    for ls in index.get("listings", []):
        d = ls.get("date", "")
        section = ls.get("section", "")
        sha = ls.get("sha256", "")
        if d and sha:
            result[(d, section)] = sha
    return result


def _lookup_listing_sha256(
    listing_index: dict[tuple[str, str], str] | None,
    pub_date: str,
    section: str,
) -> str:
    if not listing_index:
        return ""
    return listing_index.get((pub_date, section), "")


# ---------------------------------------------------------------------------
# Record loading
# ---------------------------------------------------------------------------


def _load_ingest_records(
    enriched_dir: Path,
    cfg: IdentityConfig,
    listing_index: dict[tuple[str, str], str] | None = None,
) -> list[dict[str, Any]]:
    """Load enriched JSON files and compute all hashes for ingestion."""
    out: list[dict[str, Any]] = []
    for fp in sorted(enriched_dir.glob("*.json")):
        data = json.loads(fp.read_text(encoding="utf-8"))
        page_url = str(data.get("page_url") or "")
        pub = data.get("publication_issue") or {}
        pub_norm = {k: _norm(pub.get(k)) for k in pub.keys()}
        docs = data.get("documents") or []

        for i, row in enumerate(docs, start=1):
            doc = row.get("document") or {}
            doc_norm = {k: _norm(v) for k, v in doc.items()}
            source = {
                "file": data.get("file"),
                "page_url": page_url,
                "doc_index": i,
            }

            # Natural key + content hash from identity contract
            rec = _hash_record(doc_norm, pub_norm, source, cfg)

            # Publication metadata
            pub_date_raw = pub.get("publication_date")
            pub_date = _safe_iso_date(pub_date_raw)
            edition_number = pub.get("edition_number") or ""
            edition_section = pub.get("edition_section") or ""
            page_number = pub.get("page_number") or ""
            source_url = _field_value("source_url_canonical", doc_norm, pub_norm, source)

            # Evidence-anchored hashes (computed HERE, not from identity_analyzer)
            listing_sha = _lookup_listing_sha256(listing_index, pub_date or "", edition_section)
            edition_id = _evidence_edition_id(pub_date or "", edition_number, edition_section, listing_sha)
            occurrence_hash = _evidence_occurrence_hash(edition_id, page_number, source_url)

            out.append(
                {
                    "occurrence_hash": occurrence_hash,
                    "edition_id": edition_id,
                    "publication_date": pub_date,
                    "edition_number": edition_number or None,
                    "edition_section": edition_section or None,
                    "listing_sha256": listing_sha or None,
                    "natural_key_hash": rec["natural_key_hash"],
                    "strategy": rec["strategy"],
                    "content_hash": rec["content_hash"],
                    "body_text_semantic": rec["body_text_semantic"] or None,
                    "page_number": page_number or None,
                    "source_url": source_url or None,
                    "source_file": str(fp),
                }
            )
    return out


# ---------------------------------------------------------------------------
# The CTE — single atomic statement
# ---------------------------------------------------------------------------

_INGEST_CTE = """\
WITH
-- Step 1: Upsert edition. xmax=0 means inserted.
upsert_edition AS (
    INSERT INTO registry.editions
        (edition_id, publication_date, edition_number, edition_section, listing_sha256)
    VALUES (%(edition_id)s, %(publication_date)s::date, %(edition_number)s,
            %(edition_section)s, %(listing_sha256)s)
    ON CONFLICT (edition_id)
        DO UPDATE SET listing_sha256 = registry.editions.listing_sha256
    RETURNING edition_id, (xmax = 0) AS inserted
),

-- Step 2: Upsert concept. xmax=0 means new concept.
upsert_concept AS (
    INSERT INTO registry.concepts (natural_key_hash, strategy)
    VALUES (%(natural_key_hash)s, %(strategy)s)
    ON CONFLICT (natural_key_hash)
        DO UPDATE SET strategy = registry.concepts.strategy
    RETURNING natural_key_hash, (xmax = 0) AS inserted
),

-- Step 3: Upsert version. xmax=0 means new content for this concept.
upsert_version AS (
    INSERT INTO registry.versions (natural_key_hash, content_hash, body_text_semantic)
    VALUES (%(natural_key_hash)s, %(content_hash)s, %(body_text_semantic)s)
    ON CONFLICT (natural_key_hash, content_hash)
        DO UPDATE SET content_hash = registry.versions.content_hash
    RETURNING id, (xmax = 0) AS inserted
),

-- Step 4: Insert occurrence. DO NOTHING = duplicate. RETURNING rows = new.
ins_occurrence AS (
    INSERT INTO registry.occurrences
        (occurrence_hash, edition_id, version_id, page_number, source_url, source_file)
    SELECT %(occurrence_hash)s, ue.edition_id, uv.id,
           %(page_number)s, %(source_url)s, %(source_file)s
    FROM upsert_edition ue, upsert_version uv
    ON CONFLICT (occurrence_hash) DO NOTHING
    RETURNING occurrence_hash
),

-- Step 5: Classify from SQL results only.
classification AS (
    SELECT
        CASE
            WHEN NOT EXISTS (SELECT 1 FROM ins_occurrence)                        THEN 'duplicate_skipped'
            WHEN COALESCE((SELECT inserted FROM upsert_concept LIMIT 1), false)   THEN 'inserted'
            WHEN COALESCE((SELECT inserted FROM upsert_version LIMIT 1), false)   THEN 'new_version'
            ELSE 'new_publication'
        END AS action,
        jsonb_build_object(
            'edition_inserted',    COALESCE((SELECT inserted FROM upsert_edition LIMIT 1), false),
            'concept_inserted',    COALESCE((SELECT inserted FROM upsert_concept LIMIT 1), false),
            'version_inserted',    COALESCE((SELECT inserted FROM upsert_version LIMIT 1), false),
            'occurrence_inserted', EXISTS (SELECT 1 FROM ins_occurrence),
            'version_id',          (SELECT id FROM upsert_version LIMIT 1)
        ) AS decision_basis
),

-- Step 6: Atomic log — same statement, same transaction.
ins_log AS (
    INSERT INTO registry.ingestion_log
        (occurrence_hash, action, natural_key_hash, content_hash, edition_id,
         source_file, decision_basis)
    SELECT %(occurrence_hash)s, c.action, %(natural_key_hash)s, %(content_hash)s,
           %(edition_id)s, %(source_file)s, c.decision_basis
    FROM classification c
    RETURNING action, decision_basis
)

SELECT action, decision_basis::text FROM ins_log;
"""

_PERSIST_COMMITMENT_SQL = """\
INSERT INTO registry.commitments
    (crss_version, commitment_root, record_count, log_high_water, envelope)
VALUES (%(crss_version)s, %(commitment_root)s, %(record_count)s,
        %(log_high_water)s, %(envelope)s);
"""

_HIGH_WATER_SQL = "SELECT COALESCE(max(id), 0) FROM registry.ingestion_log;"


# ---------------------------------------------------------------------------
# Ingestion
# ---------------------------------------------------------------------------


def _bump_result(result: IngestResult, action: str) -> None:
    if action == "inserted":
        result.inserted += 1
    elif action == "duplicate_skipped":
        result.duplicate_skipped += 1
    elif action == "new_version":
        result.new_version += 1
    elif action == "new_publication":
        result.new_publication += 1


def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _seal_commitment(
    dsn: str,
    sources_yaml: Path | None = None,
    identity_yaml: Path | None = None,
) -> dict[str, Any]:
    """Compute and persist commitment. Raises on failure.

    This is the seal step. Without it, the batch never happened.
    prev_commitment_root is NOT set here — it is injected by chain_anchor()
    under an exclusive lock to avoid TOCTOU races.
    """
    envelope, records_bytes = compute_commitment(
        dsn,
        sources_yaml=sources_yaml,
        identity_yaml=identity_yaml,
    )

    with psycopg.connect(dsn) as conn:
        conn.execute("SET search_path = registry, public")
        conn.execute(
            _PERSIST_COMMITMENT_SQL,
            {
                "crss_version": envelope["crss_version"],
                "commitment_root": envelope["commitment_root"],
                "record_count": envelope["record_count"],
                "log_high_water": envelope["snapshot"]["log_high_water_mark"],
                "envelope": json.dumps(envelope),
            },
        )
        conn.commit()

    _log(
        f"commitment sealed: root={envelope['commitment_root'][:16]}... "
        f"records={envelope['record_count']} "
        f"high_water={envelope['snapshot']['log_high_water_mark']}"
    )
    return envelope, records_bytes


class IngestionUnsealedError(RuntimeError):
    """Raised when ingestion completes but commitment seal fails."""

    pass


def ingest_batch(
    dsn: str,
    enriched_dir: Path,
    cfg: IdentityConfig,
    listing_index: dict[tuple[str, str], str] | None = None,
) -> IngestResult:
    """Ingest enriched documents from JSON files into the registry.

    Loads records from enriched JSON, computes hashes, and delegates
    to ``ingest_records()`` for the actual DB ingestion.

    NOTE: This function does NOT seal the batch with a commitment.
    Use ingest_batch_sealed() for complete archival ingestion.
    """
    records = _load_ingest_records(enriched_dir, cfg, listing_index)
    return ingest_records(dsn, records)


def ingest_records(
    dsn: str,
    records: list[dict[str, Any]],
) -> IngestResult:
    """Ingest pre-computed records into the registry.

    Each record must contain the fields expected by the _INGEST_CTE:
      occurrence_hash, edition_id, publication_date, edition_number,
      edition_section, listing_sha256, natural_key_hash, strategy,
      content_hash, body_text_semantic, page_number, source_url, source_file

    Each document is ingested in its own SERIALIZABLE transaction.
    Classification is derived entirely from INSERT...ON CONFLICT...RETURNING.

    NOTE: This function does NOT seal the batch with a commitment.
    Use ingest_and_seal() for complete archival ingestion.
    """
    result = IngestResult(total=len(records))
    _log(f"ingest: loading {len(records)} records")

    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute("SET search_path = registry, public")

        for idx, rec in enumerate(records, start=1):
            for attempt in range(1, MAX_SERIALIZATION_RETRIES + 1):
                try:
                    # Retry wraps ENTIRE transaction: BEGIN → CTE → classify → log → COMMIT
                    conn.isolation_level = IsolationLevel.SERIALIZABLE
                    with conn.transaction():
                        row = conn.execute(_INGEST_CTE, rec).fetchone()
                        action = row[0]
                    # Transaction committed — classification is ground truth
                    _bump_result(result, action)
                    break
                except psycopg.errors.SerializationFailure:
                    # Transaction aborted — log was NOT written (atomic).
                    # Retry with exponential backoff to reduce contention.
                    time.sleep(0.01 * (2 ** (attempt - 1)))
                    if attempt == MAX_SERIALIZATION_RETRIES:
                        _log(f"  WARN: serialization exhausted for {rec.get('source_file')}")
                        result.errors.append(
                            {
                                "file": rec.get("source_file"),
                                "error": "serialization_exhausted",
                            }
                        )
                except Exception as ex:
                    _log(f"  ERROR: {rec.get('source_file')}: {ex}")
                    result.errors.append(
                        {
                            "file": rec.get("source_file"),
                            "error": str(ex),
                        }
                    )
                    break

            if idx % 50 == 0:
                _log(
                    f"ingest progress: {idx}/{result.total} "
                    f"inserted={result.inserted} dup={result.duplicate_skipped} "
                    f"new_ver={result.new_version} new_pub={result.new_publication}"
                )

        row = conn.execute(_HIGH_WATER_SQL).fetchone()
        result.log_high_water = row[0] if row else 0

    _log(
        f"ingest done: total={result.total} inserted={result.inserted} "
        f"duplicate_skipped={result.duplicate_skipped} new_version={result.new_version} "
        f"new_publication={result.new_publication} errors={len(result.errors)} "
        f"high_water={result.log_high_water}"
    )
    return result


def ingest_batch_sealed(
    dsn: str,
    enriched_dir: Path,
    cfg: IdentityConfig,
    listing_index: dict[tuple[str, str], str] | None = None,
    sources_yaml: Path | None = None,
    identity_yaml: Path | None = None,
) -> IngestResult:
    """Ingest enriched JSON documents and seal with CRSS-1 commitment.

    Legacy entry point for the enriched-JSON pipeline.
    Delegates to ``ingest_and_seal()`` after loading records.
    """
    records = _load_ingest_records(enriched_dir, cfg, listing_index)
    return ingest_and_seal(dsn, records, sources_yaml, identity_yaml)


def ingest_and_seal(
    dsn: str,
    records: list[dict[str, Any]],
    sources_yaml: Path | None = None,
    identity_yaml: Path | None = None,
) -> IngestResult:
    """Ingest pre-computed records and seal with CRSS-1 commitment.

    COMPLETE ARCHIVAL INGESTION:
      1. Ingest all records into registry.* tables
      2. Compute CRSS-1 commitment over ingested state
      3. Persist commitment to registry.commitments
      4. Return result with commitment_root set

    FAILURE SEMANTICS:
      - If any record fails to ingest, returns with errors populated
      - If ingestion succeeds but commitment fails, raises IngestionUnsealedError
      - Success requires: errors empty AND commitment_sealed True

    This is the canonical entry point for archival ingestion.
    """
    result = ingest_records(dsn, records)

    if result.errors:
        _log(f"ingest: {len(result.errors)} errors, skipping commitment seal")
        return result

    try:
        envelope, records_bytes = _seal_commitment(dsn, sources_yaml, identity_yaml)
        result.commitment_root = envelope["commitment_root"]

        if result.log_high_water != envelope["snapshot"]["log_high_water_mark"]:
            raise IngestionUnsealedError(
                f"commitment high_water={envelope['snapshot']['log_high_water_mark']} "
                f"!= ingestion high_water={result.log_high_water}"
            )

        # CHAIN-6: Every ingestion MUST produce an anchor.
        anchor_path = chain_anchor(envelope, records_bytes)
        _log(f"anchor written: {anchor_path}")

        # Only mark sealed AFTER anchor succeeds (CHAIN-5/CHAIN-6).
        result.commitment_sealed = True

    except IngestionUnsealedError:
        raise
    except Exception as ex:
        _log(f"FATAL: commitment seal or anchor chain failed: {ex}")
        raise IngestionUnsealedError(f"ingestion completed but src/backend/commitment/anchor failed: {ex}") from ex

    _log(f"BATCH SEALED + ANCHORED: high_water={result.log_high_water} commitment={result.commitment_root[:16]}...")
    return result


# ---------------------------------------------------------------------------
# Schema creation
# ---------------------------------------------------------------------------


def create_schema(dsn: str) -> None:
    """Execute DDL from registry_schema.sql."""
    sql_path = Path(__file__).parent / "registry_schema.sql"
    sql = sql_path.read_text(encoding="utf-8")
    with psycopg.connect(dsn) as conn:
        conn.execute("SET search_path = registry, public")
        conn.execute(sql)
        conn.commit()
    _log("registry schema created")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> int:
    import argparse
    import os

    p = argparse.ArgumentParser(description="Registry ingestion engine — sealed archival ingestion")
    p.add_argument(
        "--dsn",
        default=os.environ.get("GABI_DSN", "host=localhost port=5433 dbname=gabi user=gabi password=gabi"),
    )
    p.add_argument("--enriched-dir", required=True, type=Path)
    p.add_argument("--identity", required=True, type=Path)
    p.add_argument("--sources", type=Path, default=None)
    p.add_argument("--listing-index", type=Path, default=None)
    p.add_argument(
        "--unsealed",
        action="store_true",
        help="Skip commitment seal (NOT recommended for archival use)",
    )

    args = p.parse_args()
    cfg = load_identity_config(args.identity)

    listing_index = None
    if args.listing_index and args.listing_index.exists():
        listing_index = load_listing_index(args.listing_index)

    if args.unsealed:
        result = ingest_batch(args.dsn, args.enriched_dir, cfg, listing_index)
    else:
        result = ingest_batch_sealed(
            args.dsn,
            args.enriched_dir,
            cfg,
            listing_index=listing_index,
            sources_yaml=args.sources,
            identity_yaml=args.identity,
        )

    if result.errors:
        _log(f"ERRORS: {len(result.errors)}")
        for e in result.errors:
            _log(f"  {e}")
        return 1

    if not args.unsealed and not result.commitment_sealed:
        _log("FATAL: ingestion completed but commitment was not sealed")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
