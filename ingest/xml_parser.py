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
# Page-fragment detection (Bug 3: page-break continuations)
# ---------------------------------------------------------------------------

_SEPARATOR_RE = re.compile(r'^[_\-]{2,}')
_STARTS_LOWERCASE_RE = re.compile(r'^[a-záàâãéêíóôõúüç]')
_WORD_BREAK_HYPHEN_RE = re.compile(r'\w-$')

# Art types that are always section headers, never real acts.
# These appear in TCU session publications where cases are grouped by ministry.
_SECTION_HEADER_TYPES: frozenset[str] = frozenset({
    "MINISTÉRIO",
})
_TCU_CATEGORY_RE = re.compile(r"Tribunal\s+de\s+Contas\s+da\s+Uni[aã]o", re.IGNORECASE)
_FRAGMENT_ART_TYPES: frozenset[str] = frozenset({
    "AV",  # broken "AVISO"
    "VO",  # broken "EXECUTIVO"
})

# Known valid act types (from frequency analysis of 2002 data).
# Documents whose art_type is in this set are NEVER treated as fragments.
_KNOWN_ACT_TYPES: frozenset[str] = frozenset({
    "PORTARIA", "DECRETO", "RESOLUÇÃO", "EXTRATO", "AVISO", "ATO", "EDITAL",
    "RETIFICAÇÃO", "DESPACHO", "DESPACHOS", "PORTARIAS", "EXTRATOS", "AVISOS",
    "RESULTADO", "RESULTADOS", "PREGÃO", "TOMADA", "CONCORRÊNCIA", "CONVITE",
    "ATA", "ATOS", "EDITAIS", "COMUNICADO", "CIRCULAR", "LEI", "DECRETOS",
    "ANEXO", "INSTRUÇÃO", "INSTRUÇÃO NORMATIVA", "DELIBERAÇÃO", "DECISÃO",
    "DECISÕES", "ACÓRDÃO", "ACÓRDÃOS", "SÚMULA", "PARECER", "PARECERES",
    "MEDIDA", "RESOLUÇÃO-RE", "RESOLUÇÃO-RDC", "RESOLUÇÕES", "RESOLUÇÕES-RDC",
    "RETIFICAÇÕES", "CONCORRÊNCIAS", "CONCORRENCIA", "CARTA-CONVITE",
    "CARTA-CIRCULAR", "LEILÃO", "DISPENSA", "INEXIGIBILIDADE", "SOLUÇÃO",
    "SOLUÇÕES", "PAUTA", "PAUTAS", "RELATÓRIO", "AUTORIZAÇÃO", "ADITAMENTO",
    "PROPOSTA", "CONVÊNIO", "PROTOCOLO", "CONTRATO", "DECLARAÇÃO",
    "APOSENTADORIA", "PENSÃO", "DEMONSTRATIVO", "DEMONSTRAÇÃO",
    "DEMONSTRAÇÕES", "BALANÇO", "BALANCETE", "CONSULTA", "EMENTÁRIO",
    "EMENTÁRIOS", "PROCESSO", "TOMADAS", "JUSTIFICATIVA", "PRESTAÇÃO",
    "NOTA", "NOTAS", "RESUMO", "JULGAMENTO", "SESSÃO", "ALTERAÇÃO",
    "ORDEM", "QUADRO", "ARTIGO", "SEÇÃO", "CAPÍTULO", "CONJUNTO",
    "EDITAL-RF-ADJ", "PROVIMENTO", "REGULAMENTO", "REGIMENTO",
    "RELAÇÃO", "PROGRAMA", "TERMO",
})


def is_page_fragment(article: DOUArticle) -> bool:
    """Detect page-fragment documents (page-break continuations).

    INLabs' PDF-to-XML converter sometimes creates a new ``<article>``
    at a page break even though the content is a continuation of the
    previous article.  These fragments have garbage ``artType`` values
    (e.g. "TADO" from "ESTADO", "VO" from "EXECUTIVO") and their
    ``identifica`` starts mid-sentence.
    """
    ident = (article.identifica or "").strip()
    art = (article.art_type or "").strip()

    # identifica starts with lowercase → clear continuation
    if ident and _STARTS_LOWERCASE_RE.match(ident):
        return True

    # art_type is a separator line (underscores, dashes)
    if _SEPARATOR_RE.match(art):
        return True

    # art_type is a single character (A, V, O, -, *, etc.)
    if len(art) <= 1:
        return True

    # art_type starts with ( or digit or * → continuation content
    if art and art[0] in '(*':
        return True
    if art and art[0].isdigit():
        return True

    # identifica ends with word-break hyphen (e.g. "DESENVOLVIMEN-")
    # AND art_type is not a recognized type → page-break fragment
    if _WORD_BREAK_HYPHEN_RE.search(ident) and art.upper() not in _KNOWN_ACT_TYPES:
        return True

    # art_type is a known section header (e.g. "MINISTÉRIO" in TCU listings)
    if art.upper() in _SECTION_HEADER_TYPES:
        return True

    # Known broken fragment tokens observed in 2002 OCR/XML conversion
    if art.upper() in _FRAGMENT_ART_TYPES:
        return True

    # Standalone annex marker with effectively empty body is usually a page split.
    body_len = len((article.texto or "").strip())
    if art.upper() in {"ANEXO", "ANEXOS"} and body_len <= 40:
        return True

    # TCU page-continuations often leak random heading fragments as artType
    # (e.g. "Penitenciário", "VO", "-Relator,"). Keep known act types intact.
    cat = (article.art_category or "").strip()
    if cat and _TCU_CATEGORY_RE.search(cat) and art.upper() not in _KNOWN_ACT_TYPES:
        return True

    return False


# ---------------------------------------------------------------------------
# Index document detection (Bug 1: 2002 TOC/index pages)
# ---------------------------------------------------------------------------

# Dot-leader pattern: ".PORTARIA 16, GM, 24-01-2002 . . . . . . . . .91"
_INDEX_DOT_LEADER_RE = re.compile(r'\.{3,}\s*\d+\s*$', re.MULTILINE)


def is_index_document(article: DOUArticle) -> bool:
    """Detect index/table-of-contents documents.

    These are pages listing act titles with page numbers (dot-leaders),
    not actual legal acts. Common in 2002-era DOU XMLs.
    """
    cat = article.art_category or ""
    if "Índice de Normas" in cat or "Indice de Normas" in cat:
        return True
    if article.art_type.strip().upper() in ("MINISTÉRIO", "ÍNDICE DE NORMAS"):
        if _INDEX_DOT_LEADER_RE.search(article.texto or ""):
            return True
    return False


# ---------------------------------------------------------------------------
# Blob document splitting (Bug 2: multiple acts in one XML)
# ---------------------------------------------------------------------------

# Full act header pattern: "PORTARIA Nº 1.460, DE 31 DE OUTUBRO DE 2002"
# Must include date to avoid matching references like "nos termos da Portaria Nº 123"
_ACT_HEADER_FULL_RE = re.compile(
    r"(?:PORTARIA|RESOLUÇÃO|INSTRUÇÃO NORMATIVA|DESPACHO|DECRETO|"
    r"EDITAL|ATO|CIRCULAR|MEDIDA PROVISÓRIA)"
    r"\s+N[ºo°]\s*[\d\.]+"
    r",?\s+DE\s+\d{1,2}\s+DE\s+\w+\s+DE\s+\d{4}",
    re.IGNORECASE,
)

# Shorter pattern for identifica-class tags (these are more trustworthy)
_ACT_HEADER_RE = re.compile(
    r"(?:PORTARIA|RESOLUÇÃO|INSTRUÇÃO NORMATIVA|DESPACHO|DECRETO|"
    r"EDITAL|ATO|CIRCULAR|MEDIDA PROVISÓRIA)"
    r"\s+N[ºo°]\s*[\d\.]+",
    re.IGNORECASE,
)

# Any <p> tag opening
_P_TAG_RE = re.compile(r"<p\s[^>]*>", re.IGNORECASE)

_BLOB_MIN_LENGTH = 15000  # body_html must be at least this long to attempt splitting
_BLOB_MIN_ACTS = 2        # need at least 2 act headers to justify splitting


def _find_act_boundaries(html: str) -> list[tuple[int, str]]:
    """Find act header positions in HTML, checking both identifica and corpo tags.

    Returns list of (position, identifica_text) tuples.
    """
    split_positions: list[tuple[int, str]] = []

    for m in _P_TAG_RE.finditer(html):
        tag_start = m.start()
        close = html.find("</p>", m.end())
        if close == -1:
            continue
        tag_content = html[m.end():close]
        # Strip inner HTML tags to get text
        text = re.sub(r"<[^>]+>", "", tag_content).strip()
        if not text:
            continue

        tag_str = m.group(0)
        is_identifica = "identifica" in tag_str.lower()

        # For identifica-class tags, the shorter pattern is sufficient
        if is_identifica and _ACT_HEADER_RE.match(text):
            split_positions.append((tag_start, text))
        # For corpo/other tags, require the full pattern (with date) to avoid
        # matching references to other acts within body text
        elif not is_identifica and _ACT_HEADER_FULL_RE.match(text):
            split_positions.append((tag_start, text))

    return split_positions


def split_blob_acts(article: DOUArticle, base_id_materia: str = "") -> list[DOUArticle]:
    """Split a blob document containing multiple concatenated acts.

    Returns a list of DOUArticle instances — one per act found.
    If the document is not a blob (single act or too short), returns [article].

    Args:
        article: The DOUArticle to potentially split.
        base_id_materia: Override for id_materia prefix (used when the XML
            lacks an idMateria attribute, as in 2002-era files).

    Each segment inherits envelope metadata (pub_date, pub_name, art_category,
    edition_number, number_page, pdf_page) from the parent.
    """
    base_id = base_id_materia or article.id_materia
    html = article.texto or ""
    if len(html) < _BLOB_MIN_LENGTH:
        return [article]

    split_positions = _find_act_boundaries(html)

    if len(split_positions) < _BLOB_MIN_ACTS:
        return [article]

    # Split HTML into segments
    segments: list[tuple[str, str]] = []  # (identifica, html_segment)
    for i, (pos, identifica) in enumerate(split_positions):
        if i + 1 < len(split_positions):
            end = split_positions[i + 1][0]
        else:
            end = len(html)
        segment_html = html[pos:end].strip()
        if segment_html:
            segments.append((identifica, segment_html))

    if len(segments) < _BLOB_MIN_ACTS:
        return [article]

    # Extract art_type from each segment's identifica
    def _extract_art_type(identifica: str) -> str:
        m = re.match(
            r"(PORTARIA|RESOLUÇÃO|INSTRUÇÃO NORMATIVA|DESPACHO|DECRETO|"
            r"EDITAL|ATO|CIRCULAR|MEDIDA PROVISÓRIA)",
            identifica, re.IGNORECASE,
        )
        return m.group(1) if m else article.art_type

    results: list[DOUArticle] = []
    for i, (identifica, seg_html) in enumerate(segments, 1):
        seg_art_type = _extract_art_type(identifica)
        seg = DOUArticle(
            id=article.id,
            id_materia=f"{base_id}_seg{i}",
            id_oficio=article.id_oficio,
            name=article.name,
            pub_name=article.pub_name,
            pub_date=article.pub_date,
            edition_number=article.edition_number,
            number_page=article.number_page,
            pdf_page=article.pdf_page,
            art_type=seg_art_type,
            art_category=article.art_category,
            art_class=article.art_class,
            art_size=article.art_size,
            art_notes=article.art_notes,
            highlight_type=article.highlight_type,
            highlight_priority=article.highlight_priority,
            highlight=article.highlight,
            highlight_image=article.highlight_image,
            highlight_image_name=article.highlight_image_name,
            identifica=identifica,
            data=article.data,
            ementa="",
            titulo=article.titulo,
            sub_titulo=article.sub_titulo,
            texto=seg_html,
        )
        results.append(seg)

    return results


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
