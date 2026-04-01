from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from typing import Any


def _normalize(text: str) -> str:
    nfd = unicodedata.normalize("NFD", text.lower().strip())
    return re.sub(r"[^a-z0-9\s]", "", nfd)


def _jaccard(a: str, b: str) -> float:
    set_a = set(_normalize(a).split())
    set_b = set(_normalize(b).split())
    if not set_a or not set_b:
        return 0.0
    return len(set_a & set_b) / len(set_a | set_b)


def deduplicate_docs(
    docs: list[dict[str, Any]],
    threshold: float = 0.9,
) -> list[dict[str, Any]]:
    kept: list[dict[str, Any]] = []
    for doc in docs:
        source = doc.get("_source", doc)
        title = str(source.get("title") or source.get("ementa") or "")
        is_dup = False
        for k in kept:
            k_source = k.get("_source", k)
            k_title = str(k_source.get("title") or k_source.get("ementa") or "")
            if _jaccard(title, k_title) >= threshold:
                is_dup = True
                break
        if not is_dup:
            kept.append(doc)
    return kept


def group_by_organ(
    docs: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for doc in docs:
        source = doc.get("_source", doc)
        organ = (
            source.get("issuing_organ")
            or source.get("organ")
            or source.get("relator")
            or "Desconhecido"
        )
        groups[organ].append(doc)
    return dict(groups)


_SECTION_ORDER = ["do1", "tcu", "do2", "btcu", "normas", "publicacoes", "do3", "do_e"]


def group_by_section(
    docs: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for doc in docs:
        source = doc.get("_source", doc)
        section = source.get("section") or "desconhecida"
        groups[section].append(doc)
    ordered: dict[str, list[dict[str, Any]]] = {}
    for key in _SECTION_ORDER:
        if key in groups:
            ordered[key] = groups.pop(key)
    for key in sorted(groups):
        ordered[key] = groups[key]
    return ordered


def build_aggregation_summary(
    docs: list[dict[str, Any]],
    query: str,
) -> dict[str, Any]:
    deduped = deduplicate_docs(docs)
    by_organ = group_by_organ(deduped)
    by_section = group_by_section(deduped)
    by_type: dict[str, int] = defaultdict(int)
    for doc in deduped:
        source = doc.get("_source", doc)
        art_type = source.get("art_type") or source.get("tipo_processo") or "Outros"
        by_type[art_type] += 1

    return {
        "total_retrieved": len(docs),
        "total_after_dedup": len(deduped),
        "by_organ": {organ: len(items) for organ, items in by_organ.items()},
        "by_section": {section: len(items) for section, items in by_section.items()},
        "by_type": dict(by_type),
        "note": "Contagem reflete apenas os documentos recuperados nesta busca.",
    }
