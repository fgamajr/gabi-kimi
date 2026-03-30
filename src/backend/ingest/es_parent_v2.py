"""Parent Elasticsearch v2 mapper for the DOU reindex-v3 rollout.

This mapper freezes the parent document contract for the new alias-backed
rollout while keeping compatibility with the current parent-oriented DOU
indexing flow.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
import hashlib
import re
import unicodedata
from typing import Any


_BODY_TEXT_LIMIT = 32_768
_SPACE_RE = re.compile(r"\s+")
_DEFAULT_PIPELINE_FINGERPRINT = "parent-v2.2026-03-28"
_DEFAULT_SCHEMA_VERSION = "parent_v2"
_DEFAULT_SIGNAL_VERSION = "parent_v2_s0"
_DEFAULT_FRESHNESS_VERSION = "freshness_v1"
_DEFAULT_ENTITY_DICTIONARY_VERSION = "entity_dict_v1"
_DEFAULT_ENTITY_RESOLUTION_VERSION = "entity_resolution_v1"
_DEFAULT_CHUNK_INDEX_VERSION = "chunk_v1"
_DEFAULT_EMBEDDING_VERSION = "qwen3_384_v1"
_DEFAULT_LEGAL_UPDATE_VERSION = "legal_update_v1"
_DEFAULT_PRUNING_AUDIT_VERSION = "chunk_prune_v1"
_FRESHNESS_BUCKETS = (
    (30, "d0_30", 2 * 24 * 60 * 60),
    (180, "d31_180", 8 * 24 * 60 * 60),
    (730, "d181_730", 35 * 24 * 60 * 60),
)


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
    if isinstance(pub_date, date):
        return pub_date.strftime("%Y-%m-%d")
    if pub_date:
        return str(pub_date)[:10]
    return None


def _timestamp_str(value: Any, *, default: datetime | None = None) -> str | None:
    if isinstance(value, datetime):
        timestamp = value if value.tzinfo else value.replace(tzinfo=UTC)
        return timestamp.astimezone(UTC).isoformat(timespec="seconds")
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).isoformat(timespec="seconds")
    if value:
        return _normalize_text(value) or None
    if default is None:
        return None
    return default.astimezone(UTC).isoformat(timespec="seconds")


def _clamp_score(value: float) -> float:
    return round(max(0.0, min(1.0, value)), 4)


def _count_nonempty_lists(doc: dict[str, Any], *keys: str) -> int:
    return sum(1 for key in keys if _keyword_list(doc.get(key)))


def _authority_score(doc: dict[str, Any], art_type_normalized: str, section: str | None) -> float:
    score = 0.15
    if section == "do1":
        score += 0.3
    elif section == "do2":
        score += 0.12
    elif section == "do3":
        score += 0.08

    if art_type_normalized in {"lei", "lei complementar"}:
        score += 0.4
    elif art_type_normalized in {"decreto", "decreto-lei", "medida provisoria", "medida provisória"}:
        score += 0.3
    elif art_type_normalized in {"resolucao", "resolução", "instrucao normativa", "instrução normativa"}:
        score += 0.2
    elif art_type_normalized in {"portaria", "edital"}:
        score += 0.1

    if _normalize_text(doc.get("issuing_organ") or doc.get("orgao")):
        score += 0.1
    if int(doc.get("reference_count") or 0) > 0:
        score += 0.05
    return _clamp_score(score)


def _entity_density(doc: dict[str, Any]) -> float:
    entity_hits = len(_keyword_list(doc.get("affected_entities_normalized")))
    signer_hits = len(_keyword_list(doc.get("signers_all_flat")))
    organization_hits = len(_keyword_list(doc.get("organization_path")))
    return _clamp_score((entity_hits + signer_hits + organization_hits) / 10.0)


def _legal_reference_density(doc: dict[str, Any]) -> float:
    return _clamp_score(int(doc.get("reference_count") or 0) / 8.0)


def _legal_action_score(doc: dict[str, Any]) -> float:
    base = 0.0
    if bool(doc.get("is_revocation")):
        base += 0.7
    if bool(doc.get("is_retification")):
        base += 0.4
    if int(doc.get("reference_count") or 0) > 0:
        base += 0.1
    return _clamp_score(base)


def _reconstruction_trust_score(doc: dict[str, Any]) -> float:
    parse_quality = float(doc.get("parse_quality_score") or 0.0)
    reconstruction_confidence = float(doc.get("reconstruction_confidence") or 1.0)
    return _clamp_score(parse_quality * reconstruction_confidence)


def _freshness_fields(pub_date: Any, now: datetime) -> dict[str, Any]:
    if not isinstance(pub_date, datetime):
        return {
            "days_since_pub": None,
            "freshness_bucket": None,
            "freshness_score": None,
            "time_decay_precomputed": None,
            "freshness_last_updated_at": now.isoformat(timespec="seconds"),
            "freshness_ttl_sec": 35 * 24 * 60 * 60,
            "freshness_is_stale": False,
        }

    pub_ts = pub_date if pub_date.tzinfo else pub_date.replace(tzinfo=UTC)
    days_since_pub = max(0, (now - pub_ts.astimezone(UTC)).days)
    bucket = "d730_plus"
    ttl_sec = 35 * 24 * 60 * 60
    for max_days, bucket_name, bucket_ttl_sec in _FRESHNESS_BUCKETS:
        if days_since_pub <= max_days:
            bucket = bucket_name
            ttl_sec = bucket_ttl_sec
            break

    freshness_score = _clamp_score(1.0 - min(days_since_pub, 3650) / 3650.0)
    time_decay_precomputed = _clamp_score(2.718281828 ** (-days_since_pub / 365.0))
    return {
        "days_since_pub": days_since_pub,
        "freshness_bucket": bucket,
        "freshness_score": freshness_score,
        "time_decay_precomputed": time_decay_precomputed,
        "freshness_last_updated_at": now.isoformat(timespec="seconds"),
        "freshness_ttl_sec": ttl_sec,
        "freshness_is_stale": False,
    }


def _rerank_text(
    identifica: str | None,
    ementa: str | None,
    body_plain: str | None,
    references_flat: list[str],
    signers: list[str],
    issuing_organ: str | None,
) -> str | None:
    parts = [
        identifica,
        ementa,
        issuing_organ,
        " ".join(references_flat[:5]),
        " ".join(signers[:3]),
        body_plain[:1200] if body_plain else None,
    ]
    text = _normalize_text(" ".join(part for part in parts if part))
    return text or None


def _extract_article_anchors(body_plain: str | None) -> list[str]:
    if not body_plain:
        return []
    matches = re.findall(r"\bart\.?\s*\d+[º°]?(?:-[a-z])?\b", body_plain, flags=re.IGNORECASE)
    normalized = []
    seen: set[str] = set()
    for match in matches:
        item = _normalize_text(match).lower()
        if item and item not in seen:
            normalized.append(item)
            seen.add(item)
        if len(normalized) >= 20:
            break
    return normalized


def mongo_to_es_parent_v2(doc: dict[str, Any]) -> dict[str, Any]:
    structured = doc.get("structured") or {}
    now = datetime.now(UTC)

    pub_date_raw = doc.get("pub_date")
    pub_date = _pub_date_str(pub_date_raw)
    edition_date = _pub_date_str(doc.get("edition_date"))
    section = _normalize_text(doc.get("section_normalized") or doc.get("section")).lower() or None
    doc_id = str(doc["_id"])
    logical_doc_id = _normalize_text(doc.get("logical_doc_id")) or doc_id

    identifica = _normalize_text(doc.get("identifica")) or None
    ementa = _normalize_text(doc.get("ementa")) or None
    body_plain = _truncate_body_text(doc.get("texto")) or None
    search_all = _normalize_text(doc.get("search_all")) or None

    issuing_organ = _normalize_text(doc.get("issuing_organ") or doc.get("orgao")) or None
    art_type = _normalize_text(doc.get("art_type")) or None
    art_type_normalized = _normalize_text(doc.get("art_type_normalized")) or None
    art_category = _normalize_text(doc.get("art_category")) or None

    primary_signer = _normalize_text(doc.get("primary_signer") or structured.get("signer")) or None
    primary_signer_normalized = _normalize_text(doc.get("primary_signer_normalized")) or None

    edition = doc.get("edition")
    edition_normalized = _normalize_text(edition)
    page = doc.get("page")
    edition_id = _normalize_text(doc.get("edition_id")) or _sha256_hex([pub_date or "", section or "", edition_normalized])[:32]

    deterministic_hash = _sha256_hex(
        [
            logical_doc_id,
            pub_date or "",
            section or "",
            art_type_normalized or "",
            identifica or "",
            body_plain or "",
        ]
    )

    references_flat = _keyword_list(doc.get("references_flat"))
    signers_all_flat = _keyword_list(doc.get("signers_all_flat"))
    topics = _keyword_list(doc.get("topics"))

    authority_score = _authority_score(doc, art_type_normalized, section)
    entity_density = _entity_density(doc)
    legal_reference_density = _legal_reference_density(doc)
    legal_action_score = _legal_action_score(doc)
    reconstruction_trust_score = _reconstruction_trust_score(doc)
    freshness = _freshness_fields(pub_date_raw, now)

    return {
        "doc_id": doc_id,
        "logical_doc_id": logical_doc_id,
        "deterministic_hash": deterministic_hash,
        "schema_version": _DEFAULT_SCHEMA_VERSION,
        "pipeline_fingerprint": _normalize_text(doc.get("pipeline_fingerprint")) or _DEFAULT_PIPELINE_FINGERPRINT,
        "signal_version": _DEFAULT_SIGNAL_VERSION,
        "entity_dictionary_version": _normalize_text(doc.get("entity_dictionary_version"))
        or _DEFAULT_ENTITY_DICTIONARY_VERSION,
        "entity_resolution_version": _normalize_text(doc.get("entity_resolution_version"))
        or _DEFAULT_ENTITY_RESOLUTION_VERSION,
        "chunk_index_version": _normalize_text(doc.get("chunk_index_version")) or _DEFAULT_CHUNK_INDEX_VERSION,
        "chunk_enabled_flag": bool(doc.get("chunk_enabled_flag", False)),
        "freshness_version": _normalize_text(doc.get("freshness_version")) or _DEFAULT_FRESHNESS_VERSION,
        "embedding_version": _normalize_text(doc.get("embedding_version")) or _DEFAULT_EMBEDDING_VERSION,
        "legal_update_version": _normalize_text(doc.get("legal_update_version")) or _DEFAULT_LEGAL_UPDATE_VERSION,
        "indexed_at": _timestamp_str(doc.get("indexed_at"), default=now),
        "updated_at": _timestamp_str(doc.get("updated_at"), default=now),
        "identifica": identifica,
        "normalized_title": _normalize_text(doc.get("normalized_title")) or None,
        "ementa": ementa,
        "body_plain": body_plain,
        "search_all": search_all,
        "art_type": art_type,
        "art_type_normalized": art_type_normalized,
        "art_category": art_category,
        "art_class_hierarchy": _keyword_list(doc.get("art_class_hierarchy")),
        "issuing_organ": issuing_organ,
        "organization_path": _keyword_list(doc.get("organization_path")),
        "affected_entities_normalized": _keyword_list_normalized(doc.get("affected_entities_normalized")),
        "section": section,
        "edition_number": str(edition) if edition is not None else None,
        "edition_id": edition_id,
        "edition_date": edition_date,
        "edition_type": _normalize_text(doc.get("edition_type")) or None,
        "is_extra_edition": bool(doc.get("is_extra_edition", False)),
        "page_number": str(page) if page is not None else None,
        "pub_date": pub_date,
        "document_number": _normalize_text(structured.get("act_number")) or None,
        "document_year": int(structured["act_year"]) if structured.get("act_year") is not None else None,
        "primary_signer": primary_signer,
        "primary_signer_normalized": primary_signer_normalized,
        "signers_all_flat": signers_all_flat,
        "has_multiple_signers": bool(doc.get("has_multiple_signers", False)),
        "signature_count": int(doc.get("signature_count") or 0),
        "signer_roles_flat": [
            item for item in (_normalize_text(signature.get("role_title")) for signature in doc.get("signatures") or []) if item
        ],
        "references_flat": references_flat,
        "reference_types": _keyword_list(doc.get("reference_types")),
        "reference_count": int(doc.get("reference_count") or 0),
        "procedure_refs_flat": [
            item
            for item in (
                _normalize_text(
                    f"{ref.get('procedure_type') or ''} {ref.get('procedure_identifier') or ''}".strip()
                )
                for ref in doc.get("procedure_references") or []
            )
            if item
        ],
        "relation_action_types": sorted(
            {
                action
                for action, enabled in (
                    ("revoga", bool(doc.get("is_revocation"))),
                    ("retifica", bool(doc.get("is_retification"))),
                )
                if enabled
            }
        ),
        "relation_target_keys": references_flat[:20] or None,
        "is_tombstone": bool(doc.get("is_tombstone", False)),
        "is_retification": bool(doc.get("is_retification", False)),
        "is_revocation": bool(doc.get("is_revocation", False)),
        "is_multipart": bool(doc.get("is_multipart", False)),
        "multipart_seq": int(doc.get("multipart_seq") or 0),
        "part_count": int(doc.get("part_count") or 0),
        "split_segment_index": int(doc.get("split_segment_index") or 0),
        "was_blob_split": bool(doc.get("was_blob_split", False)),
        "was_page_fragment_merged": bool(doc.get("was_page_fragment_merged", False)),
        "reconstruction_status": _normalize_text(doc.get("reconstruction_status")) or None,
        "reconstruction_confidence": float(doc.get("reconstruction_confidence") or 0.0),
        "parse_quality_score": float(doc.get("parse_quality_score") or 0.0),
        "reconstruction_trust_score": reconstruction_trust_score,
        "authority_score": authority_score,
        "entity_density": entity_density,
        "legal_reference_density": legal_reference_density,
        "legal_action_score": legal_action_score,
        "text_language": _normalize_text(doc.get("text_language")) or None,
        "source_url": _normalize_text(doc.get("source_url")) or None,
        "source_zip": _normalize_text(doc.get("source_zip")) or None,
        "topics": topics or None,
        "topic_primary": topics[0] if topics else None,
        "embedding_status": _normalize_text(doc.get("embedding_status")) or None,
        "embedding_model": _normalize_text(doc.get("embedding_model")) or None,
        "embedding": doc.get("embedding"),
        "raw_chunk_candidate_count": int(doc.get("raw_chunk_candidate_count") or 0),
        "retained_chunk_count": int(doc.get("retained_chunk_count") or 0),
        "pruned_chunk_count": int(doc.get("pruned_chunk_count") or 0),
        "pruning_reason": _normalize_text(doc.get("pruning_reason")) or None,
        "pruning_audit_version": _normalize_text(doc.get("pruning_audit_version")) or _DEFAULT_PRUNING_AUDIT_VERSION,
        "freshness_score": freshness["freshness_score"],
        "time_decay_precomputed": freshness["time_decay_precomputed"],
        "days_since_pub": freshness["days_since_pub"],
        "freshness_bucket": freshness["freshness_bucket"],
        "freshness_last_updated_at": freshness["freshness_last_updated_at"],
        "freshness_ttl_sec": freshness["freshness_ttl_sec"],
        "freshness_is_stale": freshness["freshness_is_stale"],
        "rerank_text": _rerank_text(
            identifica,
            ementa,
            body_plain,
            references_flat,
            signers_all_flat,
            issuing_organ,
        ),
        "lead_passage": body_plain[:1000] if body_plain else None,
        "citation_anchors": references_flat[:20] or None,
        "article_anchors": _extract_article_anchors(body_plain) or None,
        "rerank_feature_version": _DEFAULT_SIGNAL_VERSION,
    }
