"""TCU BTCU scraper — listing pages + PDF download + text extraction + chunking.

Scrapes https://portal.tcu.gov.br/btcu for metadata,
downloads PDFs from btcu.apps.tcu.gov.br, extracts text with PyMuPDF,
and splits multi-decision documents into semantic chunks.
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_PORTAL_URL = "https://portal.tcu.gov.br/btcu"
_PDF_BASE = "http://btcu.apps.tcu.gov.br/api/obterDocumentoPdf"
_USER_AGENT = "GABI-DOU/1.0 (legal search; +https://gabidou.top)"
_DELAY_BETWEEN_REQUESTS = 0.5  # polite rate limit (seconds)

_CADERNO_MAP = {
    "Deliberações": 4,
    "Administrativo": 1,
    "Controle Externo": 3,
    "Especial": 2,
}

# Regex for extracting metadata from Next.js SSR __next_f chunks
_PDF_LINK_RE = re.compile(
    r'"href":"http://btcu\.apps\.tcu\.gov\.br/api/obterDocumentoPdf/(\d+)"'
    r'.*?"children":\["(\d+/\d{4})"',
    re.DOTALL,
)
_CADERNO_RE = re.compile(r"(Deliberações|Administrativo|Controle Externo|Especial)")
_DATE_RE = re.compile(r"(\d{2}/\d{2}/\d{4})")
_ASSUNTO_RE = re.compile(r'"children":"([^"]{10,500})"')

# Chunking: decision boundaries in PDF text
_DECISION_BOUNDARY_RE = re.compile(
    r"(?:^|\n)"
    r"(?:"
    r"ACÓRDÃO\s+(?:N[ºo°]?\s*)?\d+/\d{4}"
    r"|DECISÃO\s+NORMATIVA[- ]+TCU\s+(?:N[ºo°]?\s*)?\d+"
    r"|ATA\s+(?:N[ºo°]?\s*)?\d+\s*,?\s*(?:DE\s+)?\d+"
    r"|RESOLUÇÃO[- ]+TCU\s+(?:N[ºo°]?\s*)?\d+"
    r"|PORTARIA[- ]+TCU\s+(?:N[ºo°]?\s*)?\d+"
    r"|INSTRUÇÃO\s+NORMATIVA[- ]+TCU\s+(?:N[ºo°]?\s*)?\d+"
    r")",
    re.IGNORECASE | re.MULTILINE,
)

# Section type detection
_SECTION_TYPE_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("acordao", re.compile(r"ACÓRDÃO\s+(?:N[ºo°]?\s*)?\d+/\d{4}", re.IGNORECASE)),
    ("decisao_normativa", re.compile(r"DECISÃO\s+NORMATIVA", re.IGNORECASE)),
    ("resolucao", re.compile(r"RESOLUÇÃO[- ]+TCU", re.IGNORECASE)),
    ("portaria", re.compile(r"PORTARIA[- ]+TCU", re.IGNORECASE)),
    ("instrucao_normativa", re.compile(r"INSTRUÇÃO\s+NORMATIVA", re.IGNORECASE)),
    ("ata", re.compile(r"ATA\s+(?:N[ºo°]?\s*)?\d+", re.IGNORECASE)),
    ("despacho", re.compile(r"DESPACHO", re.IGNORECASE)),
    ("pauta", re.compile(r"PAUTA", re.IGNORECASE)),
]


def _log(msg: str) -> None:
    print(f"[btcu-scraper] {msg}", flush=True)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class BtcuEntry:
    """Metadata for a single BTCU PDF from the listing page."""
    doc_id: str
    caderno: str
    caderno_tipo: int
    edicao: str  # "48/2026"
    edicao_numero: int
    edicao_ano: int
    data_publicacao: str  # DD/MM/YYYY
    assunto: str
    pdf_url: str


@dataclass
class BtcuChunk:
    """A semantic chunk from a BTCU PDF."""
    chunk_sequence: int
    section_type: str | None
    section_title: str  # first line / heading
    text: str
    page_start: int | None = None  # estimated
    page_end: int | None = None


# ---------------------------------------------------------------------------
# Listing scraper
# ---------------------------------------------------------------------------

def _parse_listing_html(html_text: str) -> list[BtcuEntry]:
    """Extract BTCU entries from Next.js SSR HTML."""
    # Concatenate __next_f data chunks
    chunks = re.findall(r'self\.__next_f\.push\(\[1,"(.*?)"\]', html_text, re.DOTALL)
    full = ""
    for c in chunks:
        full += c.replace("\\n", "\n").replace('\\"', '"').replace("\\\\", "\\")

    entries: list[BtcuEntry] = []
    for m in _PDF_LINK_RE.finditer(full):
        doc_id = m.group(1)
        edicao = m.group(2)

        # Parse edition
        parts = edicao.split("/")
        edicao_numero = int(parts[0]) if parts[0].isdigit() else 0
        edicao_ano = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0

        # Context after the match for caderno, date, assunto
        ctx = full[m.end():m.end() + 2000]

        caderno_match = _CADERNO_RE.search(ctx)
        caderno = caderno_match.group(1) if caderno_match else "Desconhecido"

        date_match = _DATE_RE.search(ctx)
        data = date_match.group(1) if date_match else ""

        assunto_match = _ASSUNTO_RE.search(ctx)
        assunto = assunto_match.group(1) if assunto_match else ""
        # Unescape remaining backslashes
        assunto = assunto.replace("\\", "")

        entries.append(BtcuEntry(
            doc_id=doc_id,
            caderno=caderno,
            caderno_tipo=_CADERNO_MAP.get(caderno, 0),
            edicao=edicao,
            edicao_numero=edicao_numero,
            edicao_ano=edicao_ano,
            data_publicacao=data,
            assunto=assunto,
            pdf_url=f"{_PDF_BASE}/{doc_id}",
        ))

    return entries


def scrape_listing_page(page: int, client: httpx.Client) -> list[BtcuEntry]:
    """Scrape a single listing page."""
    url = f"{_PORTAL_URL}?page={page}" if page > 1 else _PORTAL_URL
    resp = client.get(url)
    resp.raise_for_status()
    return _parse_listing_html(resp.text)


def scrape_all_listings(
    since_date: str | None = None,
    max_pages: int = 200,
) -> list[BtcuEntry]:
    """Scrape all listing pages. Stop when all entries on a page are older than since_date."""
    all_entries: list[BtcuEntry] = []
    seen_ids: set[str] = set()

    with httpx.Client(timeout=30, follow_redirects=True, headers={"User-Agent": _USER_AGENT}) as client:
        for page in range(1, max_pages + 1):
            _log(f"scraping page {page}...")
            try:
                entries = scrape_listing_page(page, client)
            except httpx.HTTPStatusError as e:
                _log(f"page {page} returned {e.response.status_code}, stopping")
                break

            if not entries:
                _log(f"page {page} empty, stopping")
                break

            new_count = 0
            for entry in entries:
                if entry.doc_id not in seen_ids:
                    seen_ids.add(entry.doc_id)
                    all_entries.append(entry)
                    new_count += 1

            _log(f"  page {page}: {len(entries)} entries, {new_count} new")

            # Check if all entries on this page are older than cursor
            if since_date and entries:
                all_older = all(_is_older(e.data_publicacao, since_date) for e in entries)
                if all_older:
                    _log(f"  all entries older than {since_date}, stopping")
                    break

            time.sleep(_DELAY_BETWEEN_REQUESTS)

    _log(f"scraped {len(all_entries)} total entries")
    return all_entries


def _is_older(date_ddmmyyyy: str, reference_ddmmyyyy: str) -> bool:
    """Check if date is older than reference. Both in DD/MM/YYYY format."""
    try:
        d = _parse_date_sortable(date_ddmmyyyy)
        r = _parse_date_sortable(reference_ddmmyyyy)
        return d < r
    except (ValueError, IndexError):
        return False


def _parse_date_sortable(date_str: str) -> str:
    """DD/MM/YYYY → YYYY-MM-DD for comparison."""
    parts = date_str.strip().split("/")
    return f"{parts[2]}-{parts[1]}-{parts[0]}"


# ---------------------------------------------------------------------------
# PDF download + text extraction
# ---------------------------------------------------------------------------

def download_pdf(doc_id: str, cache_dir: str, client: httpx.Client) -> str:
    """Download PDF to cache_dir. Returns filepath. Skips if already cached."""
    filepath = os.path.join(cache_dir, f"{doc_id}.pdf")
    if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
        return filepath

    resp = client.get(f"{_PDF_BASE}/{doc_id}")
    resp.raise_for_status()
    with open(filepath, "wb") as f:
        f.write(resp.content)
    return filepath


def extract_pdf_text(filepath: str) -> tuple[str, int]:
    """Extract text from PDF. Returns (full_text, page_count)."""
    import fitz  # pymupdf

    doc = fitz.open(filepath)
    page_count = doc.page_count
    pages_text: list[str] = []
    for page in doc:
        pages_text.append(page.get_text())
    doc.close()
    return "\n".join(pages_text), page_count


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------

def _detect_section_type(text: str) -> str | None:
    """Detect section type from first ~200 chars of chunk."""
    header = text[:200]
    for name, pattern in _SECTION_TYPE_PATTERNS:
        if pattern.search(header):
            return name
    return None


def _extract_section_title(text: str) -> str:
    """Extract first meaningful line as section title."""
    for line in text.split("\n"):
        line = line.strip()
        if len(line) > 5:
            return line[:256]
    return ""


def chunk_pdf_text(full_text: str, page_count: int) -> list[BtcuChunk]:
    """Split PDF text into semantic chunks at decision boundaries.

    If fewer than 2 decision boundaries found, returns the whole text as one chunk.
    """
    boundaries = list(_DECISION_BOUNDARY_RE.finditer(full_text))

    # Not enough boundaries — single chunk
    if len(boundaries) < 2:
        return [BtcuChunk(
            chunk_sequence=0,
            section_type=_detect_section_type(full_text),
            section_title=_extract_section_title(full_text),
            text=full_text,
            page_start=1,
            page_end=page_count,
        )]

    chunks: list[BtcuChunk] = []

    # Text before first boundary (preamble: table of contents, etc.)
    preamble = full_text[:boundaries[0].start()].strip()
    if len(preamble) > 100:
        chunks.append(BtcuChunk(
            chunk_sequence=0,
            section_type="preamble",
            section_title=_extract_section_title(preamble),
            text=preamble,
        ))

    # Each boundary starts a chunk that ends at the next boundary
    for i, match in enumerate(boundaries):
        start = match.start()
        end = boundaries[i + 1].start() if i + 1 < len(boundaries) else len(full_text)
        text = full_text[start:end].strip()

        if len(text) < 50:
            continue

        seq = len(chunks)
        chunks.append(BtcuChunk(
            chunk_sequence=seq,
            section_type=_detect_section_type(text),
            section_title=_extract_section_title(text),
            text=text,
        ))

    # Estimate page ranges
    total_chars = len(full_text)
    if total_chars > 0 and page_count > 0:
        chars_per_page = total_chars / page_count
        running_chars = 0
        for chunk in chunks:
            page_start = int(running_chars / chars_per_page) + 1
            running_chars += len(chunk.text)
            page_end = int(running_chars / chars_per_page) + 1
            chunk.page_start = min(page_start, page_count)
            chunk.page_end = min(page_end, page_count)

    return chunks
