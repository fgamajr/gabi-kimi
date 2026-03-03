"""Field normalizer for DOU XML articles.

Transforms raw INLabs XML fields into the normalized schema expected
by ``dbsync.registry_ingest``.

TODO:
    - Map artType → canonical document types (Portaria, Decreto, etc.)
    - Normalize pub_date from DD/MM/YYYY → ISO 8601
    - Extract organization hierarchy from artCategory
    - Clean HTML from Texto field
    - Map pub_name → section enum (do1, do2, do3, do1e, etc.)
"""
from __future__ import annotations

import re
from datetime import date, datetime

from ingest.xml_parser import DOUArticle


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
