"""HTML content extractor for DOU publications.

Extracts structured data from the HTML inside ``<Texto>`` CDATA sections:
  - Signatures (``<p class="assina">``, ``<p class="cargo">``)
  - Image references (``<img name="...">``)
  - Normative references (Lei nº, Decreto nº, Resolução, etc.)
  - Procedure references (Processo nº, PROAD nº, etc.)
  - Document number and year from the ``identifica`` field
  - Issuing organ from ``art_category``
  - Normalized ``art_type``

Uses only stdlib (``html.parser``, ``re``) — no external dependencies.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class Signature:
    """A document signatory extracted from HTML."""
    person_name: str
    role_title: str | None
    sequence: int


@dataclass(slots=True)
class ImageRef:
    """An image reference extracted from ``<img ...>`` tags."""
    name: str           # e.g. "1_MPESCA_27_001" (usually no extension)
    source: str | None  # original src/name payload from HTML tag
    sequence: int


@dataclass(slots=True)
class NormRef:
    """A normative/legislative reference extracted by regex."""
    reference_type: str         # "lei", "decreto", "resolução", etc.
    reference_number: str       # "12.846/2013"
    reference_date: str | None  # "29 de junho de 2009"
    reference_text: str         # full matched snippet
    issuing_body: str | None    # "MPA/MMA", "GECEX"


@dataclass(slots=True)
class ProcRef:
    """A procedure/process reference."""
    procedure_type: str         # "processo_etico", "processo_sei", "proad", etc.
    procedure_identifier: str   # "0096/2023"


# ===========================================================================
# HTML parser for signatures and image refs
# ===========================================================================

class _SignatureImageParser(HTMLParser):
    """Extract ``<p class="assina|cargo">`` blocks and ``<img name="...">`` tags."""

    def __init__(self) -> None:
        super().__init__()
        self._in_assina = False
        self._in_cargo = False
        self._current_text: list[str] = []

        self.raw_assina: list[str] = []
        self.raw_cargo: list[str] = []
        self.images: list[tuple[str, str | None]] = []

    # -- handlers --

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_dict = dict(attrs)

        if tag == "img":
            name = attr_dict.get("name", "")
            src = attr_dict.get("src")
            if name:
                self.images.append((name.strip(), src.strip() if src else None))
                return
            if src:
                src_clean = src.strip()
                inferred = src_clean.rsplit("/", 1)[-1]
                if inferred:
                    self.images.append((inferred, src_clean))
            return

        if tag == "p":
            css = (attr_dict.get("class") or "").strip().lower()
            if css == "assina":
                self._in_assina = True
                self._current_text = []
            elif css == "cargo":
                self._in_cargo = True
                self._current_text = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "p":
            if self._in_assina:
                text = "".join(self._current_text).strip()
                if text:
                    self.raw_assina.append(text)
                self._in_assina = False
            elif self._in_cargo:
                text = "".join(self._current_text).strip()
                if text:
                    self.raw_cargo.append(text)
                self._in_cargo = False
            self._current_text = []

    def handle_data(self, data: str) -> None:
        if self._in_assina or self._in_cargo:
            self._current_text.append(data)


# ===========================================================================
# Public API
# ===========================================================================

def extract_signatures(html: str) -> list[Signature]:
    """Extract signatory blocks from HTML.

    Looks for ``<p class="assina">NAME</p>`` optionally followed by
    ``<p class="cargo">TITLE</p>``.  Returns ordered list of Signature.
    """
    if not html:
        return []

    parser = _SignatureImageParser()
    parser.feed(html)

    signatures: list[Signature] = []
    # Build ordered list from the raw sequences.
    # A "cargo" entry immediately following an "assina" entry is paired.
    # Strategy: walk through the combined event stream by tracking positions
    # in the raw HTML to preserve ordering.

    # Simple pairing: for each assina, check if a cargo follows before next assina.
    cargo_idx = 0
    for i, name in enumerate(parser.raw_assina):
        role: str | None = None
        # If there's a cargo that corresponds to this signatory
        if cargo_idx < len(parser.raw_cargo):
            # Heuristic: cargo count <= assina count; pair sequentially
            # This works because DOU XML always puts cargo right after assina
            role = parser.raw_cargo[cargo_idx]
            cargo_idx += 1
        elif len(parser.raw_cargo) == 0:
            # No cargos at all — common pattern
            role = None
        signatures.append(Signature(
            person_name=name,
            role_title=role,
            sequence=i + 1,
        ))

    return signatures


def _extract_signatures_precise(html: str) -> list[Signature]:
    """More precise signature extraction using regex on raw HTML.

    Handles the pairing of assina/cargo correctly by position.
    """
    if not html:
        return []

    # Find all <p> tags whose class contains "assina" or "cargo".
    # Handles both single/double quotes and extra CSS classes like "assina pdf-RIGHT".
    pattern = re.compile(
        r"""<p\s+class=['"]([^'"]*\b(?:assina|cargo)\b[^'"]*)['"][^>]*>(.*?)</p>""",
        re.IGNORECASE | re.DOTALL,
    )

    events: list[tuple[str, str]] = []
    for m in pattern.finditer(html):
        cls_str = m.group(1).lower()
        # Extract which type matched (assina or cargo) from the full class string
        cls = "assina" if "assina" in cls_str else "cargo"
        raw = m.group(2)
        # Handle <br>-separated name/role in a single assina tag:
        # <p class='assina'>NAME<br>Role</p> → assina=NAME + cargo=Role
        if cls == "assina" and re.search(r'<br\s*/?\s*>', raw, re.IGNORECASE):
            parts = re.split(r'<br\s*/?\s*>', raw, maxsplit=1)
            name = re.sub(r'<[^>]+>', '', parts[0]).strip()
            role = re.sub(r'<[^>]+>', '', parts[1]).strip() if len(parts) > 1 else ""
            if name:
                events.append(("assina", name))
            if role:
                events.append(("cargo", role))
        else:
            text = re.sub(r'<[^>]+>', '', raw).strip()
            if text:
                events.append((cls, text))

    signatures: list[Signature] = []
    seq = 0
    i = 0
    while i < len(events):
        cls, text = events[i]
        if cls == "assina":
            seq += 1
            role: str | None = None
            # Check if next event is a cargo
            if i + 1 < len(events) and events[i + 1][0] == "cargo":
                role = events[i + 1][1]
                i += 2
            else:
                i += 1
            signatures.append(Signature(
                person_name=text,
                role_title=role,
                sequence=seq,
            ))
        else:
            # Orphan cargo — skip
            i += 1

    return signatures


def extract_images(html: str) -> list[ImageRef]:
    """Extract image references from ``<img ...>`` tags."""
    if not html:
        return []

    parser = _SignatureImageParser()
    parser.feed(html)

    return [
        ImageRef(name=name, source=src, sequence=i + 1)
        for i, (name, src) in enumerate(parser.images)
    ]


# ---------------------------------------------------------------------------
# Normative references (regex)
# ---------------------------------------------------------------------------

# The main regex captures patterns like:
#   Lei nº 12.846, de 1º de agosto de 2013
#   Decreto nº 11.129/2022
#   Resolução Gecex nº 780, de 28 de agosto de 2025
#   Instrução Normativa Interministerial MPA/MMA nº 10, de 10 de junho de 2011
#   Portaria nº 409, de 14 de janeiro de 2025
#   Deliberação nº 5, de 20 de março de 2023

_NORM_REF_TYPES = {
    "lei complementar":     "lei_complementar",
    "lei":                  "lei",
    "decreto-lei":          "decreto_lei",
    "decreto":              "decreto",
    "resolução":            "resolução",
    "portaria":             "portaria",
    "instrução normativa":  "instrução_normativa",
    "deliberação":          "deliberação",
    "medida provisória":    "medida_provisória",
    "emenda constitucional": "emenda_constitucional",
    "súmula":               "súmula",
}

_NORM_REF_TYPE_PATTERN = "|".join(
    re.escape(k) for k in sorted(_NORM_REF_TYPES.keys(), key=len, reverse=True)
)

_NORM_REF_RE = re.compile(
    rf"""
    (?P<type>{_NORM_REF_TYPE_PATTERN})     # reference type
    (?:\s+(?P<qualifier>                    # optional qualifier (Interministerial, Conjunta, etc.)
        (?:Interministerial|Conjunta|Complementar|Executivo|Executiva)
        (?:\s+[A-Z][A-Za-z/]+)?            # ... MPA/MMA, GECEX
    ))?
    (?:\s+(?P<body>[A-Z][A-Za-z/]+))?      # optional issuing body (standalone)
    \s+[Nn][º°.]\s*                         # "nº" / "N°" / "n."
    (?P<number>\d[\d./\-]*)                 # number: 12.846/2013 (no comma)
    (?:                                     # optional date clause
        ,?\s+de\s+
        (?P<date>\d{{1,2}}[º°]?\s+de\s+\w+\s+de\s+\d{{4}})
    )?
    """,
    re.IGNORECASE | re.VERBOSE,
)


def extract_normative_references(text: str) -> list[NormRef]:
    """Extract normative/legislative references from plain text."""
    if not text:
        return []

    refs: list[NormRef] = []
    seen: set[str] = set()

    for m in _NORM_REF_RE.finditer(text):
        ref_type_raw = m.group("type").lower().strip()
        ref_type = _NORM_REF_TYPES.get(ref_type_raw, ref_type_raw)
        number = m.group("number").strip().rstrip(",.")
        date_str = (m.group("date") or "").strip() or None
        full_text = m.group(0).strip()

        # Issuing body from qualifier or standalone body
        qualifier = (m.group("qualifier") or "").strip()
        body = (m.group("body") or "").strip()
        issuing = None
        if qualifier:
            # Extract org code from qualifier: "Interministerial MPA/MMA" → "MPA/MMA"
            parts = qualifier.split()
            if len(parts) > 1:
                issuing = parts[-1]
        elif body and re.match(r'^[A-Z]', body):
            issuing = body

        # Dedup by (type, number)
        dedup_key = f"{ref_type}|{number}"
        if dedup_key in seen:
            continue
        seen.add(dedup_key)

        refs.append(NormRef(
            reference_type=ref_type,
            reference_number=number,
            reference_date=date_str,
            reference_text=full_text,
            issuing_body=issuing,
        ))

    return refs


# ---------------------------------------------------------------------------
# Procedure references (regex)
# ---------------------------------------------------------------------------

_PROC_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("processo_etico", re.compile(
        r"Processo\s+[ÉE]tico\s+[Nn][º°]?\s*:?\s*([\d./\-]+)",
        re.IGNORECASE,
    )),
    ("processo_sei", re.compile(
        r"Processo\s+SEI\s+[Nn]?[º°]?\s*:?\s*([\d./\-]+)",
        re.IGNORECASE,
    )),
    ("processo_administrativo", re.compile(
        r"Processo\s+(?:Administrativo\s+)?[Nn][º°]\s*:?\s*([\d./\-]+)",
        re.IGNORECASE,
    )),
    ("proad", re.compile(
        r"PROAD\s+[Nn][º°]\s*([\d./\-]+)",
        re.IGNORECASE,
    )),
    ("processo_generico", re.compile(
        r"[Nn][º°]\s*Processo\s*:\s*([\d./\-]+)",
        re.IGNORECASE,
    )),
]


def extract_procedure_references(text: str) -> list[ProcRef]:
    """Extract process/procedure references from plain text."""
    if not text:
        return []

    refs: list[ProcRef] = []
    seen: set[str] = set()

    for ptype, pattern in _PROC_PATTERNS:
        for m in pattern.finditer(text):
            identifier = m.group(1).strip().rstrip(",.")
            if identifier in seen:
                continue
            seen.add(identifier)
            refs.append(ProcRef(
                procedure_type=ptype,
                procedure_identifier=identifier,
            ))

    return refs


# ---------------------------------------------------------------------------
# Document number / year extraction
# ---------------------------------------------------------------------------

def extract_document_number(identifica: str) -> tuple[str | None, int | None]:
    """Extract document number and year from the ``identifica`` field.

    Examples:
        "PORTARIA Nº 772, DE 23 DE SETEMBRO DE 2020" → ("772", 2020)
        "ACÓRDÃO"                                     → (None, None)
        "LEI Nº 12.846/2013"                          → ("12.846/2013", 2013)
    """
    if not identifica:
        return None, None

    # Match: Nº 772 / N° 123 / nº 12.846/2013
    m = re.search(r"[Nn][º°.]\s*([\d][\d.,/\-]*)", identifica)
    number = m.group(1).strip().rstrip(",.") if m else None

    # Year: look for 4-digit year after "DE" or at end
    ym = re.search(r"\b((?:19|20)\d{2})\b", identifica)
    year = int(ym.group(1)) if ym else None

    return number, year


# ---------------------------------------------------------------------------
# Art type normalization
# ---------------------------------------------------------------------------

# Maps common raw art_type values to a canonical lowercase form.
# Covers patterns found in 200-ZIP analysis (pre-2010 UPPERCASE, post-2010 TitleCase).
_ART_TYPE_CANONICAL: dict[str, str] = {
    # Already-seen top-20 from analysis
    "portaria":             "portaria",
    "ato":                  "ato",
    "despachos":            "despacho",
    "despacho":             "despacho",
    "extrato":              "extrato",
    "portarias":            "portaria",
    "edital":               "edital",
    "retificação":          "retificação",
    "resolução":            "resolução",
    "aviso":                "aviso",
    "pregão":               "pregão",
    "extratos":             "extrato",
    "avisos":               "aviso",
    "resultado":            "resultado",
    "atos":                 "ato",
    "ata":                  "ata",
    "instrução normativa":  "instrução normativa",
    "acórdão":              "acórdão",
    "decreto":              "decreto",
    "decisão":              "decisão",
    "circular":             "circular",
    "pauta":                "pauta",
    "convênio":             "convênio",
    "contrato":             "contrato",
    "apostila":             "apostila",
    "termo aditivo":        "termo aditivo",
    "lei":                  "lei",
    "ato declaratório":     "ato declaratório",
    "ato declaratório executivo": "ato declaratório executivo",
    "portaria interministerial": "portaria interministerial",
    "decreto numerado":     "decreto",
    "medida provisória":    "medida provisória",
}


def normalize_art_type(art_type: str) -> str:
    """Normalize ``art_type`` to a canonical lowercase form.

    Handles pre-2010 UPPERCASE and post-2010 TitleCase patterns,
    plus plural→singular normalization (PORTARIAS → portaria).
    """
    if not art_type:
        return ""
    key = art_type.strip().lower()
    return _ART_TYPE_CANONICAL.get(key, key)


# ---------------------------------------------------------------------------
# Issuing organ extraction
# ---------------------------------------------------------------------------

def extract_issuing_organ(art_category: str) -> str:
    """Extract the top-level issuing organ from ``art_category``.

    ``art_category`` is a slash-delimited organizational path, e.g.:
        "Ministério da Educação/Gabinete do Ministro"
    Returns the first segment: "Ministério da Educação".

    Handles INLabs quirk where a comma precedes the slash, splitting one
    organ name across segments, e.g.:
        "Ministério da Agricultura,/Pecuária e Abastecimento/..."
    → "Ministério da Agricultura, Pecuária e Abastecimento"
    """
    if not art_category:
        return ""
    parts = [p.strip() for p in art_category.split("/") if p.strip()]
    if not parts:
        return ""
    # Rejoin segments that were split by comma-slash
    result = parts[0]
    for i in range(1, len(parts)):
        if result.endswith(","):
            result += " " + parts[i]
        else:
            break
    return result


# ---------------------------------------------------------------------------
# Strip HTML helper
# ---------------------------------------------------------------------------

def strip_html(html: str) -> str:
    """Remove HTML tags, keeping only text content."""
    if not html:
        return ""
    text = re.sub(r"<[^>]+>", "", html)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text
