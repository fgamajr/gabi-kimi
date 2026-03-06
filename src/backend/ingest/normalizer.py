"""Field normalizer for DOU XML articles.

Transforms raw INLabs XML fields into the normalized schema expected
by ``dbsync.registry_ingest``.

Two output modes:
  1. ``normalize_article()`` → flat dict for the legal_publication.* schema
  2. ``article_to_ingest_record()`` → dict compatible with the
     registry.* CTE state machine (natural_key_hash, content_hash, etc.)
"""
from __future__ import annotations

import hashlib
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

from src.backend.ingest.xml_parser import DOUArticle


# ---------------------------------------------------------------------------
# Primitive normalizers
# ---------------------------------------------------------------------------

def normalize_pub_date(raw: str) -> date | None:
    """Convert DD/MM/YYYY to ``datetime.date``, or None on failure."""
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%d/%m/%Y").date()
    except ValueError:
        return None


def normalize_section(pub_name: str) -> str:
    """Map pubName (DO1, DO1E, etc.) to lowercase section code."""
    mapping = {
        "DO1": "do1",
        "DO1E": "do1e",
        "DO2": "do2",
        "DO2E": "do2e",
        "DO3": "do3",
        "DO3E": "do3e",
    }
    return mapping.get(pub_name, pub_name.lower())


def strip_html(html: str) -> str:
    """Remove HTML tags, keeping only text content."""
    if not html:
        return ""
    return re.sub(r"<[^>]+>", "", html).strip()


def _norm(v: Any) -> str:
    """Normalize a value to lowercase stripped string."""
    if v is None:
        return ""
    s = str(v).strip().lower()
    s = re.sub(r"\s+", " ", s)
    return s


def _sha(s: str) -> str:
    """SHA-256 hex digest of a string."""
    return hashlib.sha256((s or "").encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Content canonicalization (matches registry_ingest._canonicalize_content)
# ---------------------------------------------------------------------------

def _canonicalize_content(text: str, steps: list[str] | None = None) -> str:
    """Apply canonicalization steps to body text."""
    if steps is None:
        steps = [
            "remove_signature_blocks",
            "normalize_whitespace",
            "normalize_quotes",
            "remove_page_headers",
        ]
    out = text or ""
    for s in steps:
        if s == "remove_signature_blocks":
            out = re.sub(r"(?is)assinado por:.*$", "", out).strip()
        elif s == "normalize_whitespace":
            out = re.sub(r"\s+", " ", out).strip()
        elif s == "normalize_quotes":
            out = (
                out.replace("\u201c", '"').replace("\u201d", '"')
                .replace("\u2018", "'").replace("`", "'")
            )
        elif s == "remove_page_headers":
            out = re.sub(r"(?im)^\s*di[aá]rio oficial da uni[aã]o.*$", "", out)
    return out


# ---------------------------------------------------------------------------
# Mode 1: normalize_article → flat dict for legal_publication.* schema
# ---------------------------------------------------------------------------

def normalize_article(article: DOUArticle) -> dict:
    """Transform a ``DOUArticle`` into a flat dict matching the PG schema.

    This is a minimal normalization stub — expand as schema evolves.
    """
    return {
        "id_materia": article.id_materia,
        "id_oficio": article.id_oficio,
        "section": normalize_section(article.pub_name),
        "pub_date": normalize_pub_date(article.pub_date),
        "edition_number": article.edition_number,
        "page_number": article.number_page,
        "art_type": article.art_type,
        "art_category": article.art_category,
        "identifica": article.identifica,
        "ementa": article.ementa,
        "texto_plain": strip_html(article.texto),
        "texto_html": article.texto,
        "is_extra": article.is_extra_edition,
        "organization_path": article.organization_path,
    }


# ---------------------------------------------------------------------------
# Mode 2: article_to_ingest_record → dict for registry.* CTE
# ---------------------------------------------------------------------------

def _extract_doc_number(identifica: str, art_type: str) -> str:
    """Try to extract a document number from Identifica field.

    Patterns like: 'PORTARIA Nº 123, DE 15 DE FEVEREIRO DE 2026'
    """
    if not identifica:
        return ""
    # Match common patterns: Nº 123, N° 456, nº 789/2026
    match = re.search(r"[Nn][º°]\s*(\d[\d./\-]*)", identifica)
    if match:
        return match.group(1).strip().rstrip(".,")
    return ""


def _extract_doc_year(pub_date_str: str, identifica: str) -> str:
    """Extract year from pub_date or Identifica field."""
    d = normalize_pub_date(pub_date_str)
    if d:
        return str(d.year)
    # Fallback: look for 4-digit year in identifica
    match = re.search(r"\b(20\d{2})\b", identifica or "")
    return match.group(1) if match else ""


def _extract_issuing_organ(art_category: str) -> str:
    """Extract the issuing organ (last element of slash-delimited category path)."""
    if not art_category:
        return ""
    parts = [p.strip() for p in art_category.split("/") if p.strip()]
    return parts[-1] if parts else ""


def _compute_natural_key_hash(article: DOUArticle) -> tuple[str, str]:
    """Compute natural_key_hash using the identity strategy cascade.

    Tries strategies in order: strict → medium → weak → fallback.
    Returns (hash, strategy_name).
    """
    art_type = _norm(article.art_type)
    doc_number = _norm(_extract_doc_number(article.identifica, article.art_type))
    doc_year = _extract_doc_year(article.pub_date, article.identifica)
    issuing_organ = _norm(_extract_issuing_organ(article.art_category))
    title = _norm(article.identifica)
    body_200 = _norm(strip_html(article.texto))[:200]

    # Strict: type + number + year + organ
    if all([art_type, doc_number, doc_year, issuing_organ]):
        vals = [art_type, doc_number, doc_year, issuing_organ]
        return _sha("strict|" + "|".join(vals)), "strict"

    # Medium: type + number + organ
    if all([art_type, doc_number, issuing_organ]):
        vals = [art_type, doc_number, issuing_organ]
        return _sha("medium|" + "|".join(vals)), "medium"

    # Weak: title only
    if title:
        return _sha("weak|" + title), "weak"

    # Fallback: first 200 chars of body
    if body_200:
        return _sha("fallback|" + body_200), "fallback"

    # Last resort
    return _sha("none|" + article.id), "none"


def article_to_ingest_record(
    article: DOUArticle,
    zip_sha256: str = "",
    source_file: str = "",
) -> dict[str, Any]:
    """Transform a ``DOUArticle`` into a dict ready for ``registry_ingest.ingest_records()``.

    Computes all identity hashes (natural_key, content, edition_id, occurrence)
    matching the format expected by the registry.* CTE state machine.

    Args:
        article: Parsed DOU article
        zip_sha256: SHA-256 of the source ZIP file (used as listing_sha256)
        source_file: Path to the source file (ZIP or XML)

    Returns:
        Dict with all fields expected by the _INGEST_CTE SQL.
    """
    # Publication metadata
    pub_date = normalize_pub_date(article.pub_date)
    pub_date_iso = pub_date.isoformat() if pub_date else None
    section = normalize_section(article.pub_name)
    edition_number = article.edition_number or None
    page_number = article.number_page or None
    source_url = re.sub(r"[?#].*$", "", article.pdf_page) if article.pdf_page else None

    # Natural key hash (identity strategy cascade)
    natural_key_hash, strategy = _compute_natural_key_hash(article)

    # Content hash (canonicalized body text)
    body_plain = strip_html(article.texto)
    body_canonical = _canonicalize_content(body_plain)
    content_hash = _sha(body_canonical)

    # Edition ID = sha256(pub_date | edition_number | section | listing_sha256)
    edition_id = _sha(
        f"{pub_date_iso or ''}|{edition_number or ''}|{section}|{zip_sha256}"
    )

    # Occurrence hash = sha256(edition_id | page_number | source_url_canonical)
    occurrence_hash = _sha(
        f"{edition_id}|{page_number or ''}|{source_url or ''}"
    )

    return {
        "occurrence_hash": occurrence_hash,
        "edition_id": edition_id,
        "publication_date": pub_date_iso,
        "edition_number": edition_number,
        "edition_section": section,
        "listing_sha256": zip_sha256 or None,
        "natural_key_hash": natural_key_hash,
        "strategy": strategy,
        "content_hash": content_hash,
        "body_text_semantic": body_canonical or None,
        "page_number": page_number,
        "source_url": source_url,
        "source_file": source_file,
    }
