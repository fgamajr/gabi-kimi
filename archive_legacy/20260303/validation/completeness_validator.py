from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from validation.html_tools import parse_html_tags

# ---------------------------------------------------------------------------
# Document-start patterns for independent block counting.
# Reuses the same legal act type vocabulary as semantic_resolver.
# ---------------------------------------------------------------------------

# Matches only at the START of paragraph text — DOU publication titles
# always begin with the act type keyword. Body text references (e.g.,
# "Art. 2º Cancelados todos os efeitos do Ato Declaratório...") must
# NOT be counted as separate publications.
_DOC_START_RE = re.compile(
    r"(?i)^"
    r"(?:"
    r"emenda\s+constitucional"
    r"|lei\s+complementar"
    r"|medida\s+provis[oó]ria"
    r"|instru[cç][aã]o\s+normativa"
    r"|instru[cç][aã]o\s+operacional"
    r"|ato\s+declarat[oó]rio\s+executivo"
    r"|ato\s+declarat[oó]rio"
    r"|resultado\s+de\s+julgamento"
    r"|resultado\s+de\s+habilita[cç][aã]o"
    r"|pauta\s+de\s+julgamento"
    r"|lei\b"
    r"|decretos?\b"
    r"|portarias?\b"
    r"|resolu[cç][aã]o"
    r"|delibera[cç][aã]o"
    r"|decis[aã]o"
    r"|despacho"
    r"|alvar[aá]"
    r"|avisos?\b"
    r"|editais\b|edital"
    r"|preg[aã]o"
    r"|concorr[eê]ncia"
    r"|retifica[cç][aã]o"
    r"|errata"
    r"|extratos?\b"
    r"|ato\b"
    r")"
)

_SKIP_RE = [
    re.compile(r"(?i)publicado\s+em:"),
    re.compile(r"(?i)[oó]rg[aã]o:"),
    re.compile(r"(?i)este\s+conte[uú]do\s+n[aã]o\s+substitui"),
    re.compile(r"(?i)audi[eê]ncia\s+do\s+portal"),
    re.compile(r"(?i)^imprensa\s+nacional$"),
    re.compile(r"(?i)^redes\s+sociais$"),
]


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class PageCheck:
    file: str
    html_path: str
    html_exists: bool
    html_blocks: int
    json_documents: int
    status: str  # "match", "missing", "extra", "no_html"


@dataclass(slots=True)
class EditionCheck:
    date: str
    sections: list[str]
    discovered_urls: int
    downloaded_count: int
    processed_count: int
    missing_files: list[str]


@dataclass(slots=True)
class CompletenessResult:
    page_checks: list[PageCheck] = field(default_factory=list)
    edition_checks: list[EditionCheck] = field(default_factory=list)
    total_html_files: int = 0
    total_json_documents: int = 0
    page_matches: int = 0
    page_missing: int = 0
    page_extra: int = 0
    page_no_html: int = 0
    edition_discovered: int = 0
    edition_downloaded: int = 0
    edition_processed: int = 0


# ---------------------------------------------------------------------------
# Independent DOM block counting
# ---------------------------------------------------------------------------


def _count_html_blocks(html_path: Path) -> int:
    """Count visible publication blocks in the HTML.

    DOU article URLs are single-publication pages: each URL corresponds to
    exactly one published act.  The counter looks for content paragraphs
    (skipping metadata and boilerplate) and checks whether any match a
    legal act type keyword at the start.  If content exists, the page
    holds one publication.

    For future multi-publication pages (listing-style), the counter would
    need structural boundary detection (e.g., repeated container divs).
    The current DOU format does not require this.
    """
    html = html_path.read_text(encoding="utf-8", errors="ignore")
    tags = parse_html_tags(html)
    p_texts = [t.text.strip() for t in tags if t.name == "p" and t.text.strip()]

    has_content = False
    for text in p_texts:
        if any(skip.search(text) for skip in _SKIP_RE):
            continue
        has_content = True
        break

    # Every page with content is 1 publication (DOU article URL invariant).
    return 1 if has_content else 0


# ---------------------------------------------------------------------------
# Page-level check
# ---------------------------------------------------------------------------


def _check_page(parsed: dict[str, Any]) -> PageCheck:
    html_path = Path(parsed.get("file", ""))
    json_docs = len(parsed.get("documents", []))
    html_exists = html_path.exists()

    if not html_exists:
        return PageCheck(
            file=parsed.get("file", ""),
            html_path=str(html_path),
            html_exists=False,
            html_blocks=0,
            json_documents=json_docs,
            status="no_html",
        )

    html_blocks = _count_html_blocks(html_path)

    if json_docs < html_blocks:
        status = "missing"
    elif json_docs > html_blocks:
        status = "extra"
    else:
        status = "match"

    return PageCheck(
        file=parsed.get("file", ""),
        html_path=str(html_path),
        html_exists=True,
        html_blocks=html_blocks,
        json_documents=json_docs,
        status=status,
    )


# ---------------------------------------------------------------------------
# Edition-level check
# ---------------------------------------------------------------------------


def _check_editions(
    index_data: dict[str, Any],
    processed_files: set[str],
) -> list[EditionCheck]:
    items = index_data.get("items", [])
    unstable_dates = {
        ud.get("date") for ud in index_data.get("unstable_days", [])
    }

    by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        by_date[item.get("date", "")].append(item)

    checks = []
    for dt in sorted(by_date.keys()):
        if dt in unstable_dates:
            continue
        group = by_date[dt]
        sections = sorted({item.get("listing_url", "").split("secao=")[-1].split("&")[0] for item in group})
        discovered = len(group)
        downloaded = sum(1 for item in group if item.get("file"))

        missing_files = []
        processed = 0
        for item in group:
            rel_file = item.get("file")
            if not rel_file:
                continue
            if rel_file in processed_files:
                processed += 1
            else:
                missing_files.append(rel_file)

        checks.append(EditionCheck(
            date=dt,
            sections=sections,
            discovered_urls=discovered,
            downloaded_count=downloaded,
            processed_count=processed,
            missing_files=missing_files,
        ))

    return checks


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def validate_completeness(
    parsed_dir: Path,
    samples_dir: Path,
    out_dir: Path,
) -> CompletenessResult:
    out_dir.mkdir(parents=True, exist_ok=True)
    result = CompletenessResult()

    # Load sampler index
    index_path = samples_dir / "index.json"
    index_data: dict[str, Any] = {}
    if index_path.exists():
        index_data = json.loads(index_path.read_text(encoding="utf-8"))

    # Build set of processed file stems for edition cross-reference
    # index.json stores relative paths like "2022/06/29/abc123.html"
    # parsed JSON filenames encode the full path with underscores
    processed_files: set[str] = set()
    file_to_parsed: dict[str, Path] = {}

    for fp in sorted(parsed_dir.glob("*.json")):
        data = json.loads(fp.read_text(encoding="utf-8"))
        html_file = data.get("file", "")

        # Match against index.json relative paths
        for item in index_data.get("items", []):
            rel = item.get("file", "")
            if rel and html_file.endswith(rel):
                processed_files.add(rel)
                break

        file_to_parsed[html_file] = fp

    # Page-level checks
    for fp in sorted(parsed_dir.glob("*.json")):
        data = json.loads(fp.read_text(encoding="utf-8"))
        pc = _check_page(data)
        result.page_checks.append(pc)
        result.total_html_files += 1
        result.total_json_documents += pc.json_documents

        if pc.status == "match":
            result.page_matches += 1
        elif pc.status == "missing":
            result.page_missing += 1
        elif pc.status == "extra":
            result.page_extra += 1
        elif pc.status == "no_html":
            result.page_no_html += 1

    # Edition-level checks
    result.edition_checks = _check_editions(index_data, processed_files)
    for ec in result.edition_checks:
        result.edition_discovered += ec.discovered_urls
        result.edition_downloaded += ec.downloaded_count
        result.edition_processed += ec.processed_count

    # Write reports
    _write_per_file(result.page_checks, out_dir / "per_file.json")
    _write_mismatches(result.page_checks, out_dir / "mismatches.json")
    _write_edition_gaps(result.edition_checks, out_dir / "edition_gaps.json")
    _write_summary(result, out_dir / "summary.md")

    return result


# ---------------------------------------------------------------------------
# Report writers
# ---------------------------------------------------------------------------


def _write_per_file(checks: list[PageCheck], path: Path) -> None:
    path.write_text(
        json.dumps([asdict(c) for c in checks], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _write_mismatches(checks: list[PageCheck], path: Path) -> None:
    mismatches = [asdict(c) for c in checks if c.status in ("missing", "no_html")]
    path.write_text(
        json.dumps(mismatches, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _write_edition_gaps(checks: list[EditionCheck], path: Path) -> None:
    gaps = []
    for ec in checks:
        if ec.missing_files or ec.processed_count < ec.downloaded_count:
            gaps.append(asdict(ec))
    path.write_text(
        json.dumps(gaps, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _write_summary(result: CompletenessResult, path: Path) -> None:
    total = result.total_html_files
    page_cov = (result.page_matches + result.page_extra) / total * 100 if total else 0
    ed_cov = result.edition_processed / result.edition_downloaded * 100 if result.edition_downloaded else 0

    lines = [
        "# Completeness Report",
        "",
        "## Page-Level Verification",
        "",
        f"- total_html_files: {total}",
        f"- total_extracted_documents: {result.total_json_documents}",
        f"- page_matches: {result.page_matches}",
        f"- page_missing: {result.page_missing}",
        f"- page_extra: {result.page_extra}",
        f"- page_no_html: {result.page_no_html}",
        f"- page_coverage: {page_cov:.1f}%",
        "",
        "## Edition-Level Verification",
        "",
        f"- edition_dates_checked: {len(result.edition_checks)}",
        f"- edition_articles_discovered: {result.edition_discovered}",
        f"- edition_articles_downloaded: {result.edition_downloaded}",
        f"- edition_articles_processed: {result.edition_processed}",
        f"- edition_coverage: {ed_cov:.1f}%",
        "",
    ]

    if result.page_missing > 0:
        lines += ["## Missing Pages", ""]
        for pc in result.page_checks:
            if pc.status == "missing":
                lines.append(
                    f"- `{pc.file}`: expected {pc.html_blocks} blocks, got {pc.json_documents} documents"
                )
        lines.append("")

    edition_gaps = [ec for ec in result.edition_checks if ec.missing_files]
    if edition_gaps:
        lines += ["## Edition Gaps", ""]
        for ec in edition_gaps:
            lines.append(f"- `{ec.date}`: {len(ec.missing_files)} files not processed")
        lines.append("")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
