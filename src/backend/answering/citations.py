from __future__ import annotations

import re
from typing import Any

from src.backend.answering.models import Citation
from src.backend.core.config import settings

_CITATION_RE = re.compile(r"\[([A-Za-z0-9_:\-\.]{5,80})\]")

_DOC_URL_BASE = f"{settings.SITE_URL}/documento"


def _build_url(doc_id: str) -> str:
    return f"{_DOC_URL_BASE}/{doc_id}"


def extract_and_validate_citations(
    llm_text: str,
    evidence_docs: list[dict[str, Any]],
) -> tuple[list[Citation], int]:
    """Return validated citations and count of hallucinated ones removed."""
    evidence_index: dict[str, dict[str, Any]] = {}
    for doc in evidence_docs:
        doc_id = doc.get("_id") or doc.get("id") or doc.get("doc_id") or ""
        if doc_id:
            evidence_index[str(doc_id)] = doc

    raw_ids = _CITATION_RE.findall(llm_text)
    seen: set[str] = set()
    unique_ids: list[str] = []
    for raw_id in raw_ids:
        if raw_id not in seen:
            seen.add(raw_id)
            unique_ids.append(raw_id)

    hallucinated = 0
    citations: list[Citation] = []
    for doc_id in unique_ids:
        doc = evidence_index.get(doc_id)
        if doc is None:
            hallucinated += 1
            continue
        source = doc.get("_source", doc)
        snippet = _extract_snippet(llm_text, doc_id)
        citations.append(
            Citation(
                doc_id=doc_id,
                snippet=snippet,
                url=_build_url(doc_id),
                organ=source.get("issuing_organ") or source.get("organ"),
                pub_date=source.get("pub_date") or source.get("data_sessao"),
                art_type=source.get("art_type") or source.get("tipo_processo"),
            )
        )

    return citations, hallucinated


def _extract_snippet(text: str, doc_id: str) -> str:
    pattern = re.compile(
        r"(.{0,150})\[" + re.escape(doc_id) + r"\](.{0,100})",
        re.DOTALL,
    )
    match = pattern.search(text)
    if not match:
        return ""
    before = match.group(1).strip().replace("\n", " ")[-120:]
    after = match.group(2).strip().replace("\n", " ")[:80]
    return f"{before}[{doc_id}]{after}".strip()
