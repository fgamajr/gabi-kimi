"""CRSS-1 canonical serializer — deterministic record → bytes → SHA256.

Specification reference: CRSS-1 (Canonical Registry Serialization Specification v1)

Invariants enforced:
  MECH-1  Byte-level encoding (NFC, no BOM, no trailing newline, trailing pipe for empty final field)
  INV-2   event_type is first data field
  INV-3   sort_key follows frozen ordering contract
"""

from __future__ import annotations

import hashlib
import unicodedata
from typing import Any

CRSS_VERSION = "CRSS1"

# Fixed field order — matches the joined occurrence projection + ingestion classification.
# body_text_semantic is excluded; content_hash commits to it.
# event_type is first data field (INV-2).
FIELD_ORDER: tuple[str, ...] = (
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

# Frozen ordering contract (INV-3).
# Follows physical publication structure with deterministic tie-breaker.
SORT_KEY_FIELDS: tuple[str, ...] = (
    "publication_date",
    "edition_number",
    "page_number",
    "occurrence_hash",
)


def _nfc(value: Any) -> str:
    """NFC-normalize a value. NULL/None → empty string.

    MECH-1 rule 1: each field is individually NFC-normalized.
    MECH-1 rule 2: NULL becomes empty string BEFORE normalization.
    MECH-1 rule 6: version tag is never passed through this function.
    """
    if value is None:
        return ""
    return unicodedata.normalize("NFC", str(value))


def canonical_bytes(record: dict[str, Any]) -> bytes:
    """Serialize a single occurrence record to CRSS-1 canonical bytes.

    MECH-1 rules:
      1. Each field individually NFC-normalized.
      2. NULL → empty string before normalization.
      3. Joined by pipe (0x7C): "|".join([CRSS_VERSION] + field_values)
      4. UTF-8, no BOM, no trailing newline.
      5. Empty final field produces trailing pipe.

    Args:
        record: dict with keys matching FIELD_ORDER.
                Missing keys or None values → empty string.

    Returns:
        UTF-8 bytes of the canonical line.
    """
    parts = [CRSS_VERSION]
    for field in FIELD_ORDER:
        parts.append(_nfc(record.get(field)))
    return "|".join(parts).encode("utf-8")


def leaf_hash(record: dict[str, Any]) -> str:
    """Compute the Merkle leaf hash for a single occurrence record.

    Returns:
        64-character lowercase hex SHA256 digest.
    """
    return hashlib.sha256(canonical_bytes(record)).hexdigest()


def sort_key(record: dict[str, Any]) -> tuple[str, ...]:
    """Compute the sort key for global ordering (INV-3).

    Returns:
        Tuple of (publication_date, edition_number, page_number, occurrence_hash).
        NULLs → empty string (sorts before non-empty in COLLATE "C").
    """
    return tuple(_nfc(record.get(f)) for f in SORT_KEY_FIELDS)
