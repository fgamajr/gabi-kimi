"""Multi-part document merger for DOU XML files.

Some INLabs XML files are split across multiple parts:
  ``600_20260227_23639293-1.xml``, ``600_20260227_23639293-2.xml``

These represent a single logical document whose ``<Texto>`` content is
split across consecutive files.  This module detects, groups, and merges
them into unified ``MergedArticle`` instances.

Approximately 2.5% of DOU XMLs are multi-part.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from ingest.xml_parser import DOUArticle


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class MergedArticle:
    """A (possibly merged) DOU article with provenance info.

    For single-part articles, ``parts`` has one element and
    ``is_multipart`` is False.
    """
    article: DOUArticle
    xml_paths: list[Path]
    is_multipart: bool
    part_count: int
    base_id_materia: str     # idMateria without the -N suffix


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_MULTIPART_RE = re.compile(r'^(.*?)-(\d+)$')


def _parse_id_from_filename(filename: str) -> tuple[str, int]:
    """Extract base ID and part index from an XML filename.

    Filenames follow the pattern: ``{section}_{YYYYMMDD}_{idMateria}[-N].xml``

    Returns:
        (base_idMateria, part_index) where part_index=0 for single files.

    Examples:
        "600_20260227_23639293-1.xml" → ("23639293", 1)
        "600_20260227_23639293-2.xml" → ("23639293", 2)
        "515_20260227_23615168.xml"   → ("23615168", 0)
    """
    stem = Path(filename).stem  # e.g. "600_20260227_23639293-1"
    parts = stem.split("_")
    if len(parts) < 3:
        return stem, 0

    last_part = parts[-1]  # e.g. "23639293-1" or "23615168"
    m = _MULTIPART_RE.match(last_part)
    if m:
        return m.group(1), int(m.group(2))
    return last_part, 0


def _merge_body_html(articles: list[DOUArticle]) -> str:
    """Concatenate ``texto`` fields from multiple parts.

    Inserts an ``<hr class="multipart-break">`` separator between parts.
    """
    parts = []
    for a in articles:
        if a.texto and a.texto.strip():
            parts.append(a.texto.strip())
    return '\n<hr class="multipart-break" />\n'.join(parts)


def _merge_articles(base_id: str, parts: list[tuple[int, DOUArticle, Path]]) -> MergedArticle:
    """Merge multiple parts into a single MergedArticle.

    Uses the first part's metadata (identifica, ementa, etc.) as the
    primary source, and concatenates all body HTML.
    """
    # Sort by part index
    parts.sort(key=lambda t: t[0])
    articles = [a for _, a, _ in parts]
    paths = [p for _, _, p in parts]

    primary = articles[0]
    merged_html = _merge_body_html(articles)

    # Build a new DOUArticle with merged texto
    merged = DOUArticle(
        id=primary.id,
        id_materia=base_id,
        id_oficio=primary.id_oficio,
        name=primary.name,
        pub_name=primary.pub_name,
        pub_date=primary.pub_date,
        edition_number=primary.edition_number,
        number_page=primary.number_page,
        pdf_page=primary.pdf_page,
        art_type=primary.art_type,
        art_category=primary.art_category,
        art_class=primary.art_class,
        art_size=primary.art_size,
        art_notes=primary.art_notes,
        highlight_type=primary.highlight_type,
        highlight_priority=primary.highlight_priority,
        highlight=primary.highlight,
        highlight_image=primary.highlight_image,
        highlight_image_name=primary.highlight_image_name,
        identifica=primary.identifica,
        data=primary.data,
        ementa=primary.ementa,
        titulo=primary.titulo,
        sub_titulo=primary.sub_titulo,
        texto=merged_html,
    )

    return MergedArticle(
        article=merged,
        xml_paths=paths,
        is_multipart=True,
        part_count=len(parts),
        base_id_materia=base_id,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def group_and_merge(
    articles: list[tuple[DOUArticle, Path]],
) -> list[MergedArticle]:
    """Group multi-part articles and merge them into unified documents.

    Single-part articles pass through as-is.  Multi-part articles
    (detected by ``-N`` suffix in the XML filename) are grouped by
    their base ``idMateria`` and merged.

    Args:
        articles: List of (article, xml_path) tuples from the parser.

    Returns:
        List of MergedArticle, each representing one logical document.
    """
    # Group by base ID
    groups: dict[str, list[tuple[int, DOUArticle, Path]]] = {}

    for article, path in articles:
        base_id, part_idx = _parse_id_from_filename(path.name)
        key = base_id
        if key not in groups:
            groups[key] = []
        groups[key].append((part_idx, article, path))

    # Build output
    result: list[MergedArticle] = []

    for base_id, parts in groups.items():
        if len(parts) == 1:
            # Single document (no merge needed)
            _, article, path = parts[0]
            result.append(MergedArticle(
                article=article,
                xml_paths=[path],
                is_multipart=False,
                part_count=1,
                base_id_materia=base_id,
            ))
        else:
            # Multi-part → merge
            result.append(_merge_articles(base_id, parts))

    return result
