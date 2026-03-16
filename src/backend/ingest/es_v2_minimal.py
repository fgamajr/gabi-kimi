"""Minimal Elasticsearch v2 document mapper for the clean reindex path.

This schema is intentionally lean. It captures only the fields approved for
the first reindex canary while keeping the live v1 search surface untouched.
"""

from __future__ import annotations

from datetime import datetime
import hashlib
import re
import unicodedata
from typing import Any


_BODY_TEXT_LIMIT = 32_768
_SPACE_RE = re.compile(r"\s+")


def _normalize_text(value: Any) -> str:
    if value is None:
        return ""
    text = unicodedata.normalize("NFC", str(value))
    return _SPACE_RE.sub(" ", text).strip()


def _canonicalize_hash_parts(parts: list[str]) -> str:
    normalized = [_normalize_text(part).lower() for part in parts]
    return "|".join(normalized)


def _sha256_hex(parts: list[str]) -> str:
    payload = _canonicalize_hash_parts(parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _truncate_body_text(value: Any) -> str:
    text = _normalize_text(value)
    if len(text) <= _BODY_TEXT_LIMIT:
        return text
    return text[:_BODY_TEXT_LIMIT].rstrip()


def _pub_date_str(pub_date: Any) -> str | None:
    if isinstance(pub_date, datetime):
        return pub_date.strftime("%Y-%m-%d")
    if pub_date:
        return str(pub_date)[:10]
    return None


def _quality_score(doc: dict[str, Any]) -> float:
    checks = [
        bool(doc.get("identifica")),
        bool(doc.get("texto")),
        bool(doc.get("pub_date")),
        bool(doc.get("section")),
        bool(doc.get("art_type")),
        bool((doc.get("structured") or {}).get("signer")),
    ]
    return round(sum(1 for ok in checks if ok) / len(checks), 4)


def mongo_to_es_v2_minimal(doc: dict[str, Any]) -> dict[str, Any]:
    """Map a MongoDB document into the approved 16-field v2 minimum shape.

    Notes:
    - `logical_doc_id` currently falls back to the Mongo `_id` if a rebuilt
      multipart identifier is not yet present on the source document.
    - `deterministic_hash` is a canonical SHA-256 over the minimum identity
      inputs so the reindex pipeline can validate stability before cutover.
    """

    structured = doc.get("structured") or {}
    pub_date_str = _pub_date_str(doc.get("pub_date"))
    section = _normalize_text(doc.get("section_normalized") or doc.get("section")) or None
    doc_type = _normalize_text(doc.get("art_type_normalized") or doc.get("art_type")) or None
    title = _normalize_text(doc.get("identifica") or doc.get("titulo")) or None
    body_text = _truncate_body_text(doc.get("texto")) or None
    organ = _normalize_text(doc.get("issuing_organ") or doc.get("orgao")) or None
    edition = _normalize_text(doc.get("edition")) or None
    page = doc.get("page")
    primary_signer = _normalize_text(doc.get("primary_signer") or structured.get("signer")) or None

    logical_doc_id = (
        _normalize_text(doc.get("logical_doc_id"))
        or _normalize_text(doc.get("_id"))
        or _sha256_hex(
            [
                pub_date_str or "",
                section or "",
                doc_type or "",
                title or "",
                str(doc.get("source_zip") or ""),
                str(page or ""),
            ]
        )[:32]
    )

    deterministic_hash = _sha256_hex(
        [
            logical_doc_id,
            pub_date_str or "",
            section or "",
            doc_type or "",
            title or "",
            body_text or "",
        ]
    )

    return {
        "logical_doc_id": logical_doc_id,
        "deterministic_hash": deterministic_hash,
        "pub_date": pub_date_str,
        "organ": organ,
        "section": section,
        "doc_type": doc_type,
        "edition_id": (
            _normalize_text(doc.get("edition_id"))
            or _sha256_hex([pub_date_str or "", section or "", edition or ""])[:32]
        ),
        "edition_date": pub_date_str,
        "title": title,
        "body_text": body_text,
        "is_multipart": bool(doc.get("is_multipart", False)),
        "multipart_seq": int(doc.get("multipart_seq") or 0),
        "is_tombstone": bool(doc.get("is_tombstone", False)),
        "parse_quality_score": float(doc.get("parse_quality_score") or _quality_score(doc)),
        "primary_signer": primary_signer,
        "source_url": _normalize_text(doc.get("source_url")) or None,
    }
