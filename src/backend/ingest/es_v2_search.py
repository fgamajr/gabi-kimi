"""Expanded Elasticsearch v2 mapper for the BM25-first search canary."""

from __future__ import annotations

from typing import Any

from src.backend.ingest.es_v2_minimal import _normalize_text, mongo_to_es_v2_minimal


def _keyword_list(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    return [item for item in (_normalize_text(value) for value in values) if item]


def mongo_to_es_v2_search(doc: dict[str, Any]) -> dict[str, Any]:
    base = mongo_to_es_v2_minimal(doc)
    structured = doc.get("structured") or {}

    base.update(
        {
            "normalized_title": _normalize_text(doc.get("normalized_title")) or None,
            "text_language": _normalize_text(doc.get("text_language")) or None,
            "search_all": _normalize_text(doc.get("search_all")) or None,
            "references_flat": _keyword_list(doc.get("references_flat")),
            "reference_types": _keyword_list(doc.get("reference_types")),
            "reference_count": int(doc.get("reference_count") or 0),
            "signers_all_flat": _keyword_list(doc.get("signers_all_flat")),
            "has_multiple_signers": bool(doc.get("has_multiple_signers", False)),
            "signature_count": int(doc.get("signature_count") or 0),
            "organization_path": _keyword_list(doc.get("organization_path")),
            "art_class_hierarchy": _keyword_list(doc.get("art_class_hierarchy")),
            "document_number": _normalize_text(structured.get("act_number")) or None,
            "document_year": int(structured.get("act_year")) if structured.get("act_year") is not None else None,
            "affected_entities_normalized": _keyword_list(doc.get("affected_entities_normalized")),
        }
    )
    return base
