"""TCU Publicações Institucionais processor — PublicacaoEntry + PDF text → ES document."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import datetime, timezone
from typing import Any

from src.backend.ingest.tcu_publicacoes_scraper import PublicacaoEntry

_SPACE_RE = re.compile(r"\s+")
_BODY_LIMIT = 500_000  # max chars stored in body_plain
_SEARCH_LIMIT = 65_536  # max chars in search_all


def _normalize(value: str | None) -> str:
    if not value:
        return ""
    text = unicodedata.normalize("NFC", value)
    return _SPACE_RE.sub(" ", text).strip()


def _sha256(*parts: str) -> str:
    payload = "|".join(p.lower() for p in parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _parse_date_br(date_str: str | None) -> str | None:
    """DD/MM/YYYY → YYYY-MM-DD. Returns None if unparseable."""
    if not date_str:
        return None
    date_str = date_str.strip()
    parts = date_str.split("/")
    if len(parts) == 3:
        try:
            day, month, year = int(parts[0]), int(parts[1]), int(parts[2])
            return f"{year:04d}-{month:02d}-{day:02d}"
        except ValueError:
            pass
    return None


def pub_to_es_doc(
    entry: PublicacaoEntry,
    body_plain: str,
    pdf_url: str,
    page_count: int,
    pdf_index: int = 0,
) -> dict[str, Any]:
    """Convert a PublicacaoEntry + extracted PDF text into an ES document.

    Args:
        entry:      Scraped publication metadata.
        body_plain: Raw text extracted from the PDF (may be empty string).
        pdf_url:    The specific PDF URL this doc corresponds to.
        page_count: Number of pages in the PDF (0 if no PDF).
        pdf_index:  0-based index when a publication has multiple PDFs.
                    Appended as suffix to doc_id when > 0.

    Returns:
        dict ready for ES bulk indexing.
    """
    now = datetime.now(timezone.utc)

    title = _normalize(entry.title)
    description = _normalize(entry.description)
    body = _normalize(body_plain)[:_BODY_LIMIT]

    # Unique, stable ID based on slug; suffix for multi-PDF publications
    slug_hash = _sha256(entry.slug)
    doc_id = (
        f"tcu-pub-{slug_hash}" if pdf_index == 0 else f"tcu-pub-{slug_hash}-{pdf_index}"
    )

    # Combined search field: title + description + body excerpt
    search_all = _normalize(f"{title} {description} {body}")[:_SEARCH_LIMIT]

    pub_date_iso = _parse_date_br(entry.pub_date)

    return {
        "doc_id": doc_id,
        "slug": entry.slug,
        "source_type": "tcu_publicacoes",
        "title": title,
        "pub_type": entry.pub_type,
        "pub_date": pub_date_iso,
        "description": description,
        "body_plain": body,
        "search_all": search_all,
        "pdf_urls": entry.pdf_urls,
        "source_url": entry.url,
        "page_count": page_count,
        "indexed_at": now.isoformat(timespec="seconds"),
        "embedding_status": "pending",
        "deterministic_hash": _sha256(
            entry.slug,
            entry.pub_date or "",
            body[:500],
        ),
    }
