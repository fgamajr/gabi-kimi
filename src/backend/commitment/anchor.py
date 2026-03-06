"""Commitment anchor — query registry → CRSS-1 serialize → Merkle tree → envelope.

Invariants enforced:
  OP-1    All queries in a single REPEATABLE READ transaction.
  OP-2    ORDER BY uses COLLATE "C" for portable bytewise ordering.
  MECH-2  NULL → empty string and trim at SQL level.
  INV-2   Joins ingestion_log for event_type; excludes duplicate_skipped.
  INV-4   Snapshot bounded by log_high_water_mark.
  INV-5   Interpretation contract hashes from rule file bytes.
  INV-6   observation_stats with duplicate_skipped_count.
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psycopg
from psycopg import IsolationLevel

from src.backend.commitment.crss1 import (
    CRSS_VERSION,
    FIELD_ORDER,
    SORT_KEY_FIELDS,
    canonical_bytes,
    leaf_hash,
)
from src.backend.commitment.tree import build_tree, MerkleTree


# ---------------------------------------------------------------------------
# SQL — the canonical projection query
# ---------------------------------------------------------------------------

# MECH-2: All trim/COALESCE at SQL level.
# OP-2:   COLLATE "C" on all ORDER BY columns.
# INV-2:  Joins ingestion_log for event_type, excludes duplicate_skipped.
# INV-4:  Bounded by l.id <= high_water_mark.
_PROJECTION_QUERY = """\
SELECT
    l.action                                    AS event_type,
    trim(c.natural_key_hash)                    AS natural_key_hash,
    COALESCE(trim(c.strategy), '')              AS strategy,
    trim(v.content_hash)                        AS content_hash,
    trim(o.occurrence_hash)                     AS occurrence_hash,
    COALESCE(trim(o.page_number), '')           AS page_number,
    COALESCE(trim(o.source_url), '')            AS source_url,
    COALESCE(e.publication_date::text, '')       AS publication_date,
    COALESCE(trim(e.edition_number), '')        AS edition_number,
    COALESCE(trim(e.edition_section), '')       AS edition_section,
    COALESCE(trim(e.listing_sha256), '')        AS listing_sha256
FROM registry.ingestion_log l
JOIN registry.occurrences o ON trim(o.occurrence_hash) = trim(l.occurrence_hash)
JOIN registry.versions v ON v.id = o.version_id
JOIN registry.concepts c ON trim(c.natural_key_hash) = trim(v.natural_key_hash)
JOIN registry.editions e ON trim(e.edition_id) = trim(o.edition_id)
WHERE l.action != 'duplicate_skipped'
  AND l.id <= %(log_high_water_mark)s
ORDER BY
    COALESCE(e.publication_date::text, '') COLLATE "C",
    COALESCE(trim(e.edition_number), '')  COLLATE "C",
    COALESCE(trim(o.page_number), '')     COLLATE "C",
    trim(o.occurrence_hash)               COLLATE "C";
"""

_HIGH_WATER_QUERY = "SELECT COALESCE(max(id), 0) FROM registry.ingestion_log;"

_OBSERVATION_STATS_QUERY = """\
SELECT
    count(*)                                          AS total_log_entries,
    count(*) FILTER (WHERE action = 'duplicate_skipped') AS duplicate_skipped_count,
    count(*) FILTER (WHERE action != 'duplicate_skipped') AS state_transitions
FROM registry.ingestion_log
WHERE id <= %(log_high_water_mark)s;
"""

_SCOPE_QUERY = """\
SELECT
    (SELECT count(*) FROM registry.editions)    AS editions_count,
    (SELECT count(*) FROM registry.concepts)    AS concepts_count,
    (SELECT count(*) FROM registry.versions)    AS versions_count,
    (SELECT COALESCE(min(publication_date)::text, '') FROM registry.editions) AS earliest_date,
    (SELECT COALESCE(max(publication_date)::text, '') FROM registry.editions) AS latest_date;
"""

# Column names matching FIELD_ORDER for row → dict mapping
_ROW_KEYS = (
    "event_type",
    "natural_key_hash",
    "strategy",
    "content_hash",
    "occurrence_hash",
    "page_number",
    "source_url",
    "publication_date",
    "edition_number",
    "edition_section",
    "listing_sha256",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _row_to_record(row: tuple) -> dict[str, Any]:
    """Map a DB row to a record dict. Values are already clean (MECH-2)."""
    return dict(zip(_ROW_KEYS, row))


def _file_sha256(path: Path) -> str:
    """SHA256 of raw file bytes (INV-5: no normalization — file IS the contract)."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(8192)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

def compute_commitment(
    dsn: str,
    *,
    log_high_water: int | None = None,
    sources_yaml: Path | None = None,
    identity_yaml: Path | None = None,
    dump_records_path: Path | None = None,
    prev_commitment_root: str | None = None,
) -> tuple[dict[str, Any], bytes]:
    """Compute the full CRSS-1 commitment from the registry.

    OP-1: Entire computation runs in a single REPEATABLE READ transaction.

    Args:
        dsn: PostgreSQL connection string.
        log_high_water: Snapshot boundary. If None, reads max(id) from ingestion_log.
        sources_yaml: Path to sources YAML for interpretation contract hash (INV-5).
        identity_yaml: Path to identity YAML for interpretation contract hash (INV-5).
        dump_records_path: If set, write canonical record lines to this file (debug mode).

    Returns:
        Tuple of (commitment envelope dict, canonical records bytes).
    """
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute("SET search_path = registry, public")

        # OP-1: Single REPEATABLE READ transaction for entire computation.
        # Set isolation level via SQL before BEGIN, then use explicit transaction.
        conn.execute("SET default_transaction_isolation TO 'repeatable read'")
        with conn.transaction():
            # Snapshot boundary (INV-4)
            if log_high_water is None:
                row = conn.execute(_HIGH_WATER_QUERY).fetchone()
                log_high_water = row[0] if row else 0

            params = {"log_high_water_mark": log_high_water}

            # Observation stats (INV-6)
            obs_row = conn.execute(_OBSERVATION_STATS_QUERY, params).fetchone()
            total_log_entries = obs_row[0]
            duplicate_skipped_count = obs_row[1]
            state_transitions = obs_row[2]

            # Validate INV-6 invariant
            if total_log_entries != state_transitions + duplicate_skipped_count:
                raise ValueError(
                    f"INV-6 violation: total_log_entries={total_log_entries} != "
                    f"state_transitions={state_transitions} + "
                    f"duplicate_skipped_count={duplicate_skipped_count}"
                )

            # Scope metadata
            scope_row = conn.execute(_SCOPE_QUERY).fetchone()

            # Stream projection — server-side cursor for large registries
            leaves: list[str] = []
            records_bytes_parts: list[bytes] = []
            dump_file = None
            if dump_records_path is not None:
                dump_file = open(dump_records_path, "wb")

            try:
                with conn.cursor(name="crss1_projection") as cur:
                    cur.execute(_PROJECTION_QUERY, params)
                    for row in cur:
                        record = _row_to_record(row)
                        cb = canonical_bytes(record)
                        leaves.append(hashlib.sha256(cb).hexdigest())
                        records_bytes_parts.append(cb)
                        if dump_file is not None:
                            dump_file.write(cb)
                            dump_file.write(b"\n")
            finally:
                if dump_file is not None:
                    dump_file.close()

    # Store raw records for chaining (newline-separated)
    records_bytes = b"\n".join(records_bytes_parts)
    if records_bytes_parts:
        records_bytes += b"\n"

    # Verify record count matches observation stats
    if len(leaves) != state_transitions:
        raise ValueError(
            f"Record count mismatch: projection returned {len(leaves)} rows "
            f"but observation_stats.state_transitions={state_transitions}"
        )

    # Build Merkle tree
    tree = build_tree(leaves)

    # Interpretation contract (INV-5)
    interpretation_contract: dict[str, str] = {}
    if sources_yaml is not None and sources_yaml.exists():
        interpretation_contract["sources_yaml_sha256"] = _file_sha256(sources_yaml)
    if identity_yaml is not None and identity_yaml.exists():
        interpretation_contract["identity_yaml_sha256"] = _file_sha256(identity_yaml)

    now_utc = datetime.now(timezone.utc).isoformat()

    # Assemble envelope
    envelope: dict[str, Any] = {
        "crss_version": CRSS_VERSION,
        "commitment_root": tree.root,
        "record_count": tree.leaf_count,
        "prev_commitment_root": prev_commitment_root,
        "hash_algorithm": "sha256",
        "tree_structure": "binary_merkle_duplicate_last",
        "field_order": list(FIELD_ORDER),
        "null_encoding": "empty_string",
        "text_normalization": "nfc",
        "canonicalization": {
            "version": 1,
            "steps": [
                "remove_signature_blocks",
                "normalize_whitespace",
                "normalize_quotes",
                "remove_page_headers",
            ],
        },
        "ordering": {
            "clause": list(SORT_KEY_FIELDS),
            "collation": "C",
            "null_sort": "empty_string_first",
        },
        "snapshot": {
            "log_high_water_mark": log_high_water,
            "computed_at_utc": now_utc,
        },
        "interpretation_contract": interpretation_contract,
        "observation_stats": {
            "total_log_entries": total_log_entries,
            "duplicate_skipped_count": duplicate_skipped_count,
            "state_transitions": state_transitions,
        },
        "scope": {
            "editions_count": scope_row[0],
            "concepts_count": scope_row[1],
            "versions_count": scope_row[2],
            "earliest_publication_date": scope_row[3],
            "latest_publication_date": scope_row[4],
        },
    }
    return envelope, records_bytes


# ---------------------------------------------------------------------------
# File + DB persistence
# ---------------------------------------------------------------------------

def anchor_to_file(
    dsn: str,
    out_path: Path,
    *,
    sources_yaml: Path | None = None,
    identity_yaml: Path | None = None,
    dump_records_path: Path | None = None,
    persist_to_db: bool = True,
) -> dict[str, Any]:
    """Compute commitment, write envelope to JSON file, optionally persist to DB.

    Args:
        dsn: PostgreSQL connection string.
        out_path: Path for the output JSON envelope.
        sources_yaml: Path to sources YAML for interpretation contract hash.
        identity_yaml: Path to identity YAML for interpretation contract hash.
        dump_records_path: If set, write canonical record lines (debug mode).
        persist_to_db: If True, INSERT into registry.commitments.

    Returns:
        The commitment envelope dict.
    """
    envelope, _records_bytes = compute_commitment(
        dsn,
        sources_yaml=sources_yaml,
        identity_yaml=identity_yaml,
        dump_records_path=dump_records_path,
    )

    json_envelope = envelope
    out_path.write_text(
        json.dumps(json_envelope, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    _log(
        f"commitment root={envelope['commitment_root'][:16]}... "
        f"records={envelope['record_count']} "
        f"high_water={envelope['snapshot']['log_high_water_mark']} "
        f"written={out_path}"
    )

    # Persist to DB
    if persist_to_db:
        _persist_commitment(dsn, envelope)

    return envelope


def _persist_commitment(dsn: str, envelope: dict[str, Any]) -> None:
    """INSERT commitment into registry.commitments (append-only)."""
    with psycopg.connect(dsn) as conn:
        conn.execute("SET search_path = registry, public")
        conn.execute(
            """INSERT INTO registry.commitments
               (crss_version, commitment_root, record_count, log_high_water, envelope)
               VALUES (%(crss_version)s, %(commitment_root)s, %(record_count)s,
                       %(log_high_water)s, %(envelope)s)""",
            {
                "crss_version": envelope["crss_version"],
                "commitment_root": envelope["commitment_root"],
                "record_count": envelope["record_count"],
                "log_high_water": envelope["snapshot"]["log_high_water_mark"],
                "envelope": json.dumps(envelope),
            },
        )
        conn.commit()
    _log("commitment persisted to registry.commitments")
