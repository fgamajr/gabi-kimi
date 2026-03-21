"""TCU BTCU processor — chunk → ES/Mongo document for gabi_tcu_btcu_v1.

Transforms scraped BTCU metadata + PDF chunks into searchable documents,
extracting derived fields (acórdãos citados, normative refs, monetary values).
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import datetime, timezone
from typing import Any

from src.backend.ingest.field_extractors import extract_normative_references
from src.backend.ingest.tcu_processor import extract_acordaos_citados, extract_valores_monetarios

_SPACE_RE = re.compile(r"\s+")
_CHAR_LIMIT = 65_536
_BODY_LIMIT = 500_000


def _normalize(value: str | None) -> str:
    if not value:
        return ""
    text = unicodedata.normalize("NFC", value)
    return _SPACE_RE.sub(" ", text).strip()


def _sha256(*parts: str) -> str:
    payload = "|".join(p.lower() for p in parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _parse_date_br(date_str: str) -> str | None:
    """DD/MM/YYYY → YYYY-MM-DD."""
    if not date_str:
        return None
    try:
        parts = date_str.strip().split("/")
        return f"{parts[2]}-{parts[1]}-{parts[0]}"
    except (IndexError, ValueError):
        return None


def btcu_chunk_to_es_doc(
    entry: Any,  # BtcuEntry
    chunk: Any,  # BtcuChunk
    num_pages: int,
) -> dict[str, Any]:
    """Convert a BTCU entry + chunk into an ES/Mongo document."""
    now = datetime.now(timezone.utc)

    doc_id_base = f"BTCU-{entry.doc_id}"
    doc_id = f"{doc_id_base}-{chunk.chunk_sequence}" if chunk.chunk_sequence > 0 else doc_id_base

    texto = _normalize(chunk.text)[:_BODY_LIMIT]
    assunto = _normalize(entry.assunto)
    section_title = _normalize(chunk.section_title)

    # Build search_all: section title + assunto + text (capped)
    search_parts = [p for p in [section_title, assunto, texto[:_CHAR_LIMIT]] if p]
    search_all = _normalize(" ".join(search_parts))[:_CHAR_LIMIT]

    # Derived fields from text
    norm_refs = extract_normative_references(texto[:50_000])
    normative_references = [f"{r.reference_type} {r.reference_number}" for r in norm_refs]
    acordaos_citados = extract_acordaos_citados(texto[:50_000])
    valores_monetarios, valor_maximo = extract_valores_monetarios(texto[:50_000])

    # Page range
    page_range = None
    if chunk.page_start and chunk.page_end:
        page_range = f"{chunk.page_start}-{chunk.page_end}" if chunk.page_start != chunk.page_end else str(chunk.page_start)

    return {
        "doc_id": doc_id,
        "parent_btcu_id": doc_id_base,
        "chunk_sequence": chunk.chunk_sequence,
        "source_type": "tcu_btcu",
        "caderno": entry.caderno,
        "caderno_tipo": entry.caderno_tipo,
        "edicao_numero": entry.edicao_numero,
        "edicao_ano": entry.edicao_ano,
        "data_publicacao": _parse_date_br(entry.data_publicacao),
        "assunto": assunto or None,
        "section_type": chunk.section_type,
        "section_title": section_title or None,
        "texto_completo": texto or None,
        "search_all": search_all or None,
        "pdf_url": entry.pdf_url,
        "num_pages": num_pages,
        "page_range": page_range,
        "acordaos_citados": acordaos_citados or None,
        "normative_references": normative_references or None,
        "valores_monetarios": valores_monetarios or None,
        "valor_maximo": valor_maximo,
        "deterministic_hash": _sha256(doc_id, section_title or "", texto[:500]),
        "indexed_at": now.isoformat(timespec="seconds"),
        "embedding_status": "pending",
    }
