from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from validation.html_tools import HtmlTag, parse_html_tags

# ---------------------------------------------------------------------------
# Semantic versioning — bump SEMANTIC_VERSION on any rule change that
# affects field values or hash inputs.
# ---------------------------------------------------------------------------
SEMANTIC_VERSION = "v1"

_RESOLVER_SOURCE = Path(__file__)


def _ruleset_hash() -> str:
    src = _RESOLVER_SOURCE.read_bytes()
    return hashlib.sha256(src).hexdigest()


# ---------------------------------------------------------------------------
# Per-field coverage thresholds (fraction, not percent)
# ---------------------------------------------------------------------------
COVERAGE_THRESHOLDS: dict[str, float] = {
    "document_type": 0.95,
    "body_text_semantic": 0.95,
    "publication_date": 0.99,
    "issuing_organ_normalized": 0.80,
    "title_normalized": 0.80,
    "edition_number": 0.80,
    "edition_section": 0.80,
}

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class FieldCoverage:
    field_name: str
    total: int = 0
    resolved: int = 0

    @property
    def pct(self) -> float:
        return (self.resolved / self.total * 100.0) if self.total else 0.0


@dataclass(slots=True)
class EnrichmentSummary:
    files_processed: int = 0
    documents_processed: int = 0
    html_missing: int = 0
    coverage: dict[str, FieldCoverage] = field(default_factory=dict)
    failures: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Document type detection
# ---------------------------------------------------------------------------

_DOC_TYPE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("EMENDA CONSTITUCIONAL", re.compile(r"(?i)\bemenda\s+constitucional\b")),
    ("LEI COMPLEMENTAR", re.compile(r"(?i)\blei\s+complementar\b")),
    ("MEDIDA PROVISORIA", re.compile(r"(?i)\bmedida\s+provis[oó]ria\b")),
    ("INSTRUCAO NORMATIVA", re.compile(r"(?i)\binstru[cç][aã]o\s+normativa\b")),
    ("INSTRUCAO OPERACIONAL", re.compile(r"(?i)\binstru[cç][aã]o\s+operacional\b")),
    ("ATO DECLARATORIO EXECUTIVO", re.compile(r"(?i)\bato\s+declarat[oó]rio\s+executivo\b")),
    ("ATO DECLARATORIO", re.compile(r"(?i)\bato\s+declarat[oó]rio\b")),
    ("RESULTADO DE JULGAMENTO", re.compile(r"(?i)\bresultado\s+de\s+julgamento\b")),
    ("RESULTADO DE HABILITACAO", re.compile(r"(?i)\bresultado\s+de\s+habilita[cç][aã]o\b")),
    ("PAUTA DE JULGAMENTO", re.compile(r"(?i)\bpauta\s+de\s+julgamento\b")),
    ("LEI", re.compile(r"(?i)\blei\b(?!\s+complementar)")),
    ("DECRETO", re.compile(r"(?i)\bdecretos?\b")),
    ("PORTARIA", re.compile(r"(?i)\bportarias?\b")),
    ("RESOLUCAO", re.compile(r"(?i)\bresolu[cç][aã]o\b")),
    ("DELIBERACAO", re.compile(r"(?i)\bdelibera[cç][aã]o\b")),
    ("DECISAO", re.compile(r"(?i)\bdecis[aã]o\b")),
    ("DESPACHO", re.compile(r"(?i)\bdespacho\b")),
    ("ALVARA", re.compile(r"(?i)\balvar[aá]\b")),
    ("AVISO", re.compile(r"(?i)\bavisos?\b")),
    ("EDITAL", re.compile(r"(?i)\beditais\b|(?:(?:\b|^)edital)")),
    ("PREGAO", re.compile(r"(?i)(?:\b|^)preg[aã]o\b")),
    ("CONCORRENCIA", re.compile(r"(?i)\bconcorr[eê]ncia\b")),
    ("RETIFICACAO", re.compile(r"(?i)\bretifica[cç][aã]o\b")),
    ("ERRATA", re.compile(r"(?i)\berrata\b")),
    ("EXTRATO", re.compile(r"(?i)\bextratos?\b")),
    ("ATO", re.compile(r"(?i)\bato\b")),
]


def _detect_document_type(heading: str | None, p_tags: list[str]) -> str | None:
    candidates = []
    if heading:
        candidates.append(heading)
    candidates.extend(p_tags[:3])
    for text in candidates:
        for label, pat in _DOC_TYPE_PATTERNS:
            if pat.search(text):
                return label
    return None


# ---------------------------------------------------------------------------
# Publication issue extraction
# ---------------------------------------------------------------------------

_PUB_DATE_RE = re.compile(r"(?i)publicado\s+em:?\s*(\d{2}/\d{2}/\d{4})")
_EDITION_RE = re.compile(r"(?i)edi[cç][aã]o:?\s*(\d+)")
_SECTION_RE = re.compile(r"(?i)se[cç][aã]o:?\s*(\d+)")
_PAGE_RE = re.compile(r"(?i)p[aá]gina:?\s*(\d+)")


def _extract_publication_issue(p_texts: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    blob = " ".join(p_texts[:5])
    m = _PUB_DATE_RE.search(blob)
    if m:
        parts = m.group(1).split("/")
        if len(parts) == 3:
            out["publication_date"] = f"{parts[2]}-{parts[1]}-{parts[0]}"
    m = _EDITION_RE.search(blob)
    if m:
        out["edition_number"] = m.group(1)
    m = _SECTION_RE.search(blob)
    if m:
        out["edition_section"] = m.group(1)
    m = _PAGE_RE.search(blob)
    if m:
        out["page_number"] = m.group(1)
    return out


# ---------------------------------------------------------------------------
# Organ extraction and normalization
# ---------------------------------------------------------------------------

_ORGAN_RE = re.compile(r"(?i)[oó]rg[aã]o:?\s*(.+)")
_PT_LOWERCASE = {"da", "de", "do", "das", "dos", "e", "em", "para", "a", "o", "as", "os", "no", "na", "nos", "nas"}


def _extract_organ(p_texts: list[str]) -> tuple[str | None, str | None]:
    for text in p_texts[:5]:
        m = _ORGAN_RE.search(text)
        if m:
            raw = m.group(1).strip()
            top_level = raw.split("/")[0].strip()
            normalized = _pt_title_case(top_level)
            return raw, normalized
    return None, None


def _pt_title_case(text: str) -> str:
    words = text.split()
    out = []
    for i, w in enumerate(words):
        low = w.lower()
        if i == 0 or low not in _PT_LOWERCASE:
            out.append(w.capitalize())
        else:
            out.append(low)
    return " ".join(out)


# ---------------------------------------------------------------------------
# Title normalization
# ---------------------------------------------------------------------------

_DATE_SUFFIX_RE = re.compile(
    r",?\s+DE\s+\d{1,2}\s+DE\s+\w+\s+DE\s+\d{4}\s*$",
    re.IGNORECASE,
)


def _normalize_title(heading: str | None) -> str | None:
    if not heading or not heading.strip():
        return None
    title = _DATE_SUFFIX_RE.sub("", heading).strip()
    return title if title else None


# ---------------------------------------------------------------------------
# Body text extraction
# ---------------------------------------------------------------------------

_BOILERPLATE_RE = [
    re.compile(r"(?i)este\s+conte[uú]do\s+n[aã]o\s+substitui"),
    re.compile(r"(?i)audi[eê]ncia\s+do\s+portal"),
    re.compile(r"(?i)^imprensa\s+nacional$"),
    re.compile(r"(?i)^redes\s+sociais$"),
]

_METADATA_RE = [
    re.compile(r"(?i)publicado\s+em:"),
    re.compile(r"(?i)[oó]rg[aã]o:"),
]

_SIGNATURE_RE = re.compile(r"^[A-ZÁÀÂÃÉÊÍÓÔÕÚÜÇ][A-ZÁÀÂÃÉÊÍÓÔÕÚÜÇ\s\.\-]{4,}$")


def _extract_body_text(p_texts: list[str], heading: str | None) -> str | None:
    body_lines: list[str] = []
    heading_norm = (heading or "").strip().lower()

    for text in p_texts:
        stripped = text.strip()
        if not stripped:
            continue

        if any(bp.search(stripped) for bp in _BOILERPLATE_RE):
            break

        if any(mp.search(stripped) for mp in _METADATA_RE):
            continue

        if heading_norm and stripped.lower() == heading_norm:
            continue

        body_lines.append(stripped)

    while body_lines and _SIGNATURE_RE.match(body_lines[-1]):
        body_lines.pop()

    result = "\n".join(body_lines).strip()
    return result if result else None


# ---------------------------------------------------------------------------
# Heading finder
# ---------------------------------------------------------------------------


_NAV_HEADINGS_RE = re.compile(
    r"(?i)^(caminho\s+de\s+navega|publicador\s+de\s+conte|"
    r"di[aá]rio\s+oficial\s+da\s+uni|reportar\s+erro|"
    r"imprensa\s+nacional|portalvisitorscounter)",
)


def _find_heading(tags: list[HtmlTag]) -> str | None:
    # First pass: find heading that contains a document type keyword
    for t in tags:
        if t.name in {"h1", "h2", "h3", "h4", "h5"} and t.text.strip():
            text = t.text.strip()
            if _NAV_HEADINGS_RE.search(text):
                continue
            for _, pat in _DOC_TYPE_PATTERNS:
                if pat.search(text):
                    return text
    # Second pass: find first non-navigation heading
    for t in tags:
        if t.name in {"h2", "h3"} and t.text.strip():
            text = t.text.strip()
            if _NAV_HEADINGS_RE.search(text):
                continue
            return text
    # Third pass: first <p> that looks like a document heading
    for t in tags:
        if t.name == "p" and t.text.strip():
            text = t.text.strip()
            for _, pat in _DOC_TYPE_PATTERNS:
                if pat.search(text):
                    return text
    return None


# ---------------------------------------------------------------------------
# Per-file enrichment
# ---------------------------------------------------------------------------


def _enrich_file(parsed: dict[str, Any], sem_meta: dict[str, str]) -> dict[str, Any]:
    raw_html = parsed.get("raw_html")
    if raw_html:
        html = raw_html
    else:
        html_path = Path(parsed.get("file", ""))
        if not html_path.exists():
            return parsed
        html = html_path.read_text(encoding="utf-8", errors="ignore")

    tags = parse_html_tags(html)
    p_texts = [t.text for t in tags if t.name == "p" and t.text.strip()]

    heading = _find_heading(tags)
    pub_extracted = _extract_publication_issue(p_texts)
    organ_raw, organ_norm = _extract_organ(p_texts)
    doc_type = _detect_document_type(heading, p_texts)
    title_norm = _normalize_title(heading)
    body_text = _extract_body_text(p_texts, heading)

    pub = dict(parsed.get("publication_issue") or {})
    for k, v in pub_extracted.items():
        if not pub.get(k):
            pub[k] = v

    enriched_docs = []
    for doc_entry in parsed.get("documents", []):
        entry = dict(doc_entry)
        doc = dict(entry.get("document") or {})

        if not doc.get("document_type"):
            doc["document_type"] = doc_type
        if not doc.get("title_normalized"):
            doc["title_normalized"] = title_norm
        if not doc.get("issuing_organ_normalized"):
            doc["issuing_organ_normalized"] = organ_norm
        if not doc.get("issuing_organ"):
            doc["issuing_organ"] = organ_raw
        if not doc.get("body_text_semantic"):
            doc["body_text_semantic"] = body_text
        if not doc.get("body_text"):
            doc["body_text"] = body_text

        entry["document"] = doc
        entry["_semantic"] = dict(sem_meta)
        enriched_docs.append(entry)

    result = dict(parsed)
    result["publication_issue"] = pub
    result["documents"] = enriched_docs
    return result


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def resolve_semantics(parsed_dir: Path, out_dir: Path) -> EnrichmentSummary:
    out_dir.mkdir(parents=True, exist_ok=True)
    enriched_dir = out_dir / "enriched"
    enriched_dir.mkdir(parents=True, exist_ok=True)

    sem_meta = {
        "version": SEMANTIC_VERSION,
        "ruleset_hash": _ruleset_hash(),
        "resolver": "deterministic",
    }

    summary = EnrichmentSummary()
    coverage_fields = list(COVERAGE_THRESHOLDS.keys())
    for f in coverage_fields:
        summary.coverage[f] = FieldCoverage(field_name=f)

    for fp in sorted(parsed_dir.glob("*.json")):
        parsed = json.loads(fp.read_text(encoding="utf-8"))

        raw_html = parsed.get("raw_html")
        html_path = Path(parsed.get("file", ""))
        if not raw_html and not html_path.exists():
            summary.html_missing += 1

        enriched = _enrich_file(parsed, sem_meta)
        summary.files_processed += 1

        pub = enriched.get("publication_issue") or {}
        for doc_entry in enriched.get("documents", []):
            summary.documents_processed += 1
            doc = doc_entry.get("document") or {}
            for field_name in coverage_fields:
                cov = summary.coverage[field_name]
                cov.total += 1
                val = doc.get(field_name) or pub.get(field_name)
                if val is not None and str(val).strip():
                    cov.resolved += 1

        (enriched_dir / fp.name).write_text(
            json.dumps(enriched, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    _write_semantic_report(summary, out_dir / "semantic_report.md")

    for field_name, threshold in COVERAGE_THRESHOLDS.items():
        cov = summary.coverage.get(field_name)
        if cov and cov.total > 0:
            actual = cov.resolved / cov.total
            if actual < threshold:
                summary.failures.append(
                    f"FAIL: {field_name} coverage {cov.pct:.1f}% < {threshold * 100:.0f}%"
                )

    return summary


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------


def _write_semantic_report(summary: EnrichmentSummary, path: Path) -> None:
    lines = [
        "# Semantic Enrichment Report",
        "",
        f"- semantic_version: {SEMANTIC_VERSION}",
        f"- files_processed: {summary.files_processed}",
        f"- documents_processed: {summary.documents_processed}",
        f"- html_missing: {summary.html_missing}",
        "",
        "## Field Coverage",
        "",
        "| field | total | resolved | coverage_pct | threshold | status |",
        "|---|---:|---:|---:|---:|---|",
    ]

    for field_name, cov in sorted(summary.coverage.items(), key=lambda x: x[0]):
        threshold = COVERAGE_THRESHOLDS.get(field_name, 0.80)
        actual = (cov.resolved / cov.total) if cov.total else 0.0
        status = "PASS" if actual >= threshold else "FAIL"
        lines.append(
            f"| {field_name} | {cov.total} | {cov.resolved} | {cov.pct:.1f}% "
            f"| {threshold * 100:.0f}% | {status} |"
        )

    if summary.failures:
        lines += ["", "## Failures", ""]
        for f in summary.failures:
            lines.append(f"- {f}")

    lines.append("")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
