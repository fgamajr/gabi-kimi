"""INLabs DOU XML Parser.

Parses XML files extracted from DOU ZIP bundles into structured dataclasses.
Handles encoding (UTF-8 BOM), CDATA sections, and edge cases.

Sanitization:
    A small fraction (~4%) of INLabs XMLs contain a production bug where the
    ``name`` and ``artType`` article attributes include an unescaped closing
    tag, e.g. ``name="RETIFICAÇÃO</Identifica>"``.  The sanitizer strips
    these before ET.fromstring() is called, recovering the records that would
    otherwise be lost to parse errors.

Promoted from scripts/inlabs_parser.py during repository consolidation (2026-03-03).
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class DOUArticle:
    """Parsed DOU article from INLabs XML.

    Attributes correspond 1:1 with ``<article>`` element attributes
    and ``<body>`` child elements in the INLabs XML schema.
    """

    # Core identifiers
    id: str
    id_materia: str
    id_oficio: str
    name: str

    # Publication info
    pub_name: str        # DO1, DO1E, DO2, DO3, etc.
    pub_date: str        # DD/MM/YYYY
    edition_number: str
    number_page: str
    pdf_page: str

    # Content classification
    art_type: str        # Portaria, Resolução, etc.
    art_category: str    # Full organizational path (slash-delimited)
    art_class: str       # 12-level hierarchy code (colon-delimited)
    art_size: str        # Font size
    art_notes: str       # Extra edition markers

    # Highlight flags
    highlight_type: str
    highlight_priority: str
    highlight: str
    highlight_image: str
    highlight_image_name: str

    # Body content
    identifica: str      # Title/identification
    data: str            # Date field (often empty)
    ementa: str          # Summary/abstract
    titulo: str          # Title
    sub_titulo: str      # Subtitle
    texto: str           # Full HTML content

    # --- derived properties ---

    @property
    def is_extra_edition(self) -> bool:
        return bool(self.art_notes and self.art_notes.upper() == "EXTRA")

    @property
    def organization_path(self) -> list[str]:
        return self.art_category.split("/") if self.art_category else []

    @property
    def art_class_hierarchy(self) -> list[str]:
        if not self.art_class:
            return []
        return [p for p in self.art_class.split(":") if p != "00000"]


# ---------------------------------------------------------------------------
# Valid pubName values
# ---------------------------------------------------------------------------

VALID_PUB_NAMES: frozenset[str] = frozenset({
    "DO1", "DO1E", "DO2", "DO2E", "DO3", "DO3E",
})


class XMLParseError(ValueError):
    """Raised when an XML file cannot be parsed or is structurally invalid."""


# ---------------------------------------------------------------------------
# XML sanitizer — fix known INLabs production bugs
# ---------------------------------------------------------------------------

# Pattern: leaked closing tags inside attribute values on the <article> line.
# Example: name="RETIFICAÇÃO</Identifica>" → name="RETIFICAÇÃO"
#          artType="DESPACHOS</Identifica>" → artType="DESPACHOS"
# The INLabs system accidentally includes the closing tag from <Identifica>
# content inside the name= and artType= attribute values.  This is the *only*
# malformation pattern observed across 3.96M XMLs (200-ZIP sample, ~4% affected).
_ATTR_LEAKED_TAG_RE = re.compile(r'</\w+>(?=")')


def _sanitize_xml(content: str) -> tuple[str, bool]:
    """Fix known INLabs XML malformations.

    Returns (sanitized_content, was_modified).
    """
    # Fast path: only 4% of XMLs have this bug — skip the rest instantly
    if "</Identifica>" not in content[:600]:
        return content, False

    # Replace leaked closing tags right before a closing quote in attribute values.
    # This handles: name="RETIFICAÇÃO</Identifica>" → name="RETIFICAÇÃO"
    sanitized = _ATTR_LEAKED_TAG_RE.sub("", content)
    return sanitized, sanitized != content


class INLabsXMLParser:
    """Parser for INLabs DOU XML files."""

    def __init__(self, encoding: str = "utf-8-sig") -> None:
        self.encoding = encoding

    # -- public API --

    def parse_file(self, filepath: Path | str) -> DOUArticle:
        """Parse a single XML file into a ``DOUArticle``."""
        filepath = Path(filepath)
        if not filepath.exists():
            raise FileNotFoundError(f"XML file not found: {filepath}")
        content = filepath.read_text(encoding=self.encoding)
        return self.parse_string(content)

    def parse_string(self, xml_content: str) -> DOUArticle:
        """Parse raw XML string into a ``DOUArticle``.

        Applies sanitization to recover XMLs with known INLabs bugs
        (e.g. leaked ``</Identifica>`` inside attribute values).
        """
        # Sanitize before parsing
        content, was_sanitized = _sanitize_xml(xml_content)

        try:
            root = ET.fromstring(content)
        except ET.ParseError as e:
            raise XMLParseError(f"Invalid XML: {e}") from e

        article = root.find(".//article")
        if article is None and root.tag == "article":
            article = root
        if article is None:
            raise XMLParseError("No <article> element found in XML")

        body = article.find("body")
        if body is None:
            raise XMLParseError("No <body> element found in article")

        body_content = self._extract_body_content(body)

        return DOUArticle(
            id=article.get("id", ""),
            id_materia=article.get("idMateria", ""),
            id_oficio=article.get("idOficio", ""),
            name=article.get("name", ""),
            pub_name=article.get("pubName", ""),
            pub_date=article.get("pubDate", ""),
            edition_number=article.get("editionNumber", ""),
            number_page=article.get("numberPage", ""),
            pdf_page=article.get("pdfPage", ""),
            art_type=article.get("artType", ""),
            art_category=article.get("artCategory", ""),
            art_class=article.get("artClass", ""),
            art_size=article.get("artSize", ""),
            art_notes=article.get("artNotes", ""),
            highlight_type=article.get("highlightType", ""),
            highlight_priority=article.get("highlightPriority", ""),
            highlight=article.get("highlight", ""),
            highlight_image=article.get("highlightimage", ""),
            highlight_image_name=article.get("highlightimagename", ""),
            **body_content,
        )

    def validate(self, article: DOUArticle) -> list[str]:
        """Return a list of validation errors (empty → valid)."""
        errors: list[str] = []

        for field in ("id", "id_materia", "art_type", "pub_date", "art_category"):
            if not getattr(article, field):
                errors.append(f"Missing required field: {field}")

        if article.id_materia:
            if not (len(article.id_materia) == 8 and article.id_materia.isdigit()):
                errors.append(f"Invalid idMateria format: {article.id_materia}")

        if article.pub_name and article.pub_name not in VALID_PUB_NAMES:
            errors.append(f"Unknown pubName: {article.pub_name}")

        return errors

    # -- internals --

    @staticmethod
    def _extract_body_content(body: ET.Element) -> dict[str, str]:
        def _text(tag: str) -> str:
            elem = body.find(tag)
            return (elem.text or "") if elem is not None else ""

        return {
            "identifica": _text("Identifica"),
            "data": _text("Data"),
            "ementa": _text("Ementa"),
            "titulo": _text("Titulo"),
            "sub_titulo": _text("SubTitulo"),
            "texto": _text("Texto"),
        }


# ---------------------------------------------------------------------------
# Convenience helpers
# ---------------------------------------------------------------------------

def parse_directory(directory: Path | str) -> list[DOUArticle]:
    """Parse all ``*.xml`` files in *directory*, skipping failures."""
    directory = Path(directory)
    parser = INLabsXMLParser()
    articles: list[DOUArticle] = []
    for xml_file in sorted(directory.glob("*.xml")):
        try:
            articles.append(parser.parse_file(xml_file))
        except Exception as exc:
            print(f"[WARN] skipping {xml_file.name}: {exc}")
    return articles


def article_to_dict(article: DOUArticle) -> dict[str, Any]:
    """Serialize a ``DOUArticle`` to a plain dict (JSON-safe)."""
    return {
        "id": article.id,
        "id_materia": article.id_materia,
        "id_oficio": article.id_oficio,
        "name": article.name,
        "pub_name": article.pub_name,
        "pub_date": article.pub_date,
        "edition_number": article.edition_number,
        "number_page": article.number_page,
        "pdf_page": article.pdf_page,
        "art_type": article.art_type,
        "art_category": article.art_category,
        "art_class": article.art_class,
        "art_size": article.art_size,
        "art_notes": article.art_notes,
        "is_extra_edition": article.is_extra_edition,
        "organization_path": article.organization_path,
        "art_class_hierarchy": article.art_class_hierarchy,
        "body": {
            "identifica": article.identifica,
            "data": article.data,
            "ementa": article.ementa,
            "titulo": article.titulo,
            "sub_titulo": article.sub_titulo,
            "texto": article.texto,
        },
    }
