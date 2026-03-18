"""Full Elasticsearch v3 document mapper — all search-relevant fields.

Maps ~40 fields from MongoDB to ES covering:
- Full-text: identifica, ementa, body_plain, search_all
- Filters: art_type, issuing_organ, section, pub_date, signers, references, entities
- Ranking: parse_quality_score, is_tombstone, is_retification
- Embedding: dense_vector placeholder for embed_indexer
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


def _truncate_body_text(value: Any) -> str:
    text = _normalize_text(value)
    if len(text) <= _BODY_TEXT_LIMIT:
        return text
    return text[:_BODY_TEXT_LIMIT].rstrip()


def _sha256_hex(parts: list[str]) -> str:
    """SHA-256 of pipe-joined lowercased parts. Expects pre-normalized strings."""
    payload = "|".join(p.lower() for p in parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _keyword_list(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    return [str(v) for v in values if v]


def _keyword_list_normalized(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    return [item for item in (_normalize_text(v) for v in values) if item]


def _pub_date_str(pub_date: Any) -> str | None:
    if isinstance(pub_date, datetime):
        return pub_date.strftime("%Y-%m-%d")
    if pub_date:
        return str(pub_date)[:10]
    return None


def mongo_to_es_v3_full(doc: dict[str, Any]) -> dict[str, Any]:
    """Map a MongoDB document to the full v3 ES schema (~40 fields)."""
    structured = doc.get("structured") or {}

    pub_date = _pub_date_str(doc.get("pub_date"))
    edition_date = _pub_date_str(doc.get("edition_date"))
    section = _normalize_text(doc.get("section_normalized") or doc.get("section")) or None
    doc_id = str(doc["_id"])
    logical_doc_id = _normalize_text(doc.get("logical_doc_id")) or doc_id

    # Text fields
    identifica = _normalize_text(doc.get("identifica")) or None
    ementa = _normalize_text(doc.get("ementa")) or None
    body_plain = _truncate_body_text(doc.get("texto")) or None
    search_all = _normalize_text(doc.get("search_all")) or None

    # Organ / classification
    issuing_organ = _normalize_text(doc.get("issuing_organ") or doc.get("orgao")) or None
    art_type = _normalize_text(doc.get("art_type")) or None
    art_type_normalized = _normalize_text(doc.get("art_type_normalized")) or None
    art_category = _normalize_text(doc.get("art_category")) or None

    # Signer
    primary_signer = _normalize_text(doc.get("primary_signer") or structured.get("signer")) or None
    primary_signer_normalized = _normalize_text(doc.get("primary_signer_normalized")) or None

    # Edition
    edition = doc.get("edition")
    edition_normalized = _normalize_text(edition)
    page = doc.get("page")
    edition_id = (
        _normalize_text(doc.get("edition_id"))
        or _sha256_hex([pub_date or "", section or "", edition_normalized])[:32]
    )

    # Deterministic hash for validation
    deterministic_hash = _sha256_hex([
        logical_doc_id,
        pub_date or "",
        section or "",
        art_type_normalized or "",
        identifica or "",
        body_plain or "",
    ])

    return {
        # Identity
        "doc_id": doc_id,
        "logical_doc_id": logical_doc_id,
        "deterministic_hash": deterministic_hash,

        # Full-text search
        "identifica": identifica,
        "normalized_title": _normalize_text(doc.get("normalized_title")) or None,
        "ementa": ementa,
        "body_plain": body_plain,
        "search_all": search_all,

        # Document type / classification
        "art_type": art_type,
        "art_type_normalized": art_type_normalized,
        "art_category": art_category,
        "art_class_hierarchy": _keyword_list(doc.get("art_class_hierarchy")),

        # Issuing body
        "issuing_organ": issuing_organ,
        "organization_path": _keyword_list(doc.get("organization_path")),
        "affected_entities_normalized": _keyword_list_normalized(doc.get("affected_entities_normalized")),

        # Publication metadata
        "section": section,
        "edition_number": str(edition) if edition is not None else None,
        "edition_id": edition_id,
        "edition_date": edition_date,
        "page_number": str(page) if page is not None else None,
        "pub_date": pub_date,

        # Structured act identifiers
        "document_number": _normalize_text(structured.get("act_number")) or None,
        "document_year": int(structured["act_year"]) if structured.get("act_year") is not None else None,

        # Signers
        "primary_signer": primary_signer,
        "primary_signer_normalized": primary_signer_normalized,
        "signers_all_flat": _keyword_list(doc.get("signers_all_flat")),
        "has_multiple_signers": bool(doc.get("has_multiple_signers", False)),
        "signature_count": int(doc.get("signature_count") or 0),

        # Legal references
        "references_flat": _keyword_list(doc.get("references_flat")),
        "reference_types": _keyword_list(doc.get("reference_types")),
        "reference_count": int(doc.get("reference_count") or 0),

        # Status flags (ranking signals)
        "is_tombstone": bool(doc.get("is_tombstone", False)),
        "is_retification": bool(doc.get("is_retification", False)),
        "is_revocation": bool(doc.get("is_revocation", False)),
        "is_multipart": bool(doc.get("is_multipart", False)),
        "multipart_seq": int(doc.get("multipart_seq") or 0),

        # Quality / metadata
        "parse_quality_score": float(doc.get("parse_quality_score") or 0),
        "text_language": _normalize_text(doc.get("text_language")) or None,

        # Source
        "source_url": _normalize_text(doc.get("source_url")) or None,
        "source_zip": _normalize_text(doc.get("source_zip")) or None,

        # Topic classification
        "topics": _keyword_list(doc.get("topics")) or None,
        "topic_primary": (doc.get("topics") or [None])[0],
    }
