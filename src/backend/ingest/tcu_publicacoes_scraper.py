"""TCU Publicações Institucionais scraper — listing pages + detail pages + PDF discovery.

Two-phase scraping:
  Phase 1: Paginate https://portal.tcu.gov.br/publicacoes-institucionais/todas
           with delta=100 (3 requests for ~242 publications). Extracts title,
           description, slug, pub_type from SSR HTML (Liferay CMS — no JS needed).
  Phase 2: For each publication not yet fully scraped, visit its detail page to
           extract pub_date (DD/MM/YYYY) and direct PDF download URLs.

Usage:
  from src.backend.ingest.tcu_publicacoes_scraper import scrape_all
  entries = scrape_all(skip_slugs={"sumarios-executivos/royalties-..."})
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from urllib.parse import urlparse

import httpx
from lxml import html

_BASE_URL = "https://portal.tcu.gov.br"
_LISTING_URL = f"{_BASE_URL}/publicacoes-institucionais/todas"
_DELTA = 100  # items per page; portal supports up to 100
_DELAY_SEC = 0.5  # polite rate limit between requests
_USER_AGENT = "GABI-DOU/1.0 (legal search; +https://gabidou.top)"

# Prefix in URL path that marks the publications area
_PUB_PATH_PREFIX = "/publicacoes-institucionais/"
# Known path segments that are category index pages (not individual publications)
_CATEGORY_SLUGS = {
    "todas",
    "relatorio-de-fiscalizacao",
    "cartilha-manual-ou-tutorial",
    "revista-ou-periodico",
    "sumarios-executivos",
    "fichas-sinteses",
    "normativo",
    "livro",
    "relatorio-de-gestao",
    "Caderno Temático",
}


def _log(msg: str) -> None:
    print(f"[tcu-pub-scraper] {msg}", flush=True)


# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------


@dataclass
class PublicacaoEntry:
    slug: str  # e.g. "sumarios-executivos/royalties-da-mineracao-..."
    url: str  # full detail page URL
    title: str
    pub_type: str  # first path segment after /publicacoes-institucionais/
    description: str  # abstract from listing page
    pub_date: str | None = None  # "DD/MM/YYYY" — populated in Phase 2
    pdf_urls: list[str] = field(default_factory=list)  # direct PDF URLs


# ---------------------------------------------------------------------------
# HTML parsing helpers
# ---------------------------------------------------------------------------


def _extract_slug(href: str) -> str | None:
    """Extract slug from an href like /publicacoes-institucionais/tipo/nome."""
    path = urlparse(href).path
    if not path.startswith(_PUB_PATH_PREFIX):
        return None
    rest = path[len(_PUB_PATH_PREFIX) :]
    parts = rest.strip("/").split("/")
    # Must have at least type + name segments
    if len(parts) < 2:
        return None
    # Exclude category index pages
    if parts[-1] in _CATEGORY_SLUGS or parts[0] in _CATEGORY_SLUGS and len(parts) == 1:
        return None
    return "/".join(parts)


def _pub_type_from_slug(slug: str) -> str:
    """Return the type segment from a slug, normalised to lowercase with hyphens."""
    return slug.split("/")[0].lower().strip()


def _parse_listing_page(html_text: str) -> list[PublicacaoEntry]:
    """Parse a listing page HTML and return PublicacaoEntry objects."""
    tree = html.fromstring(html_text)
    entries: list[PublicacaoEntry] = []
    seen_slugs: set[str] = set()

    # Each publication is an <a> wrapping an <article> inside the results section
    for link_el in tree.xpath("//main//a[@href]"):
        href = link_el.get("href", "")
        # Make absolute if relative
        if href.startswith("/"):
            href = _BASE_URL + href

        # Extract slug; skip non-publication links
        slug = _extract_slug(href)
        if not slug or slug in seen_slugs:
            continue
        seen_slugs.add(slug)

        pub_type = _pub_type_from_slug(slug)

        # Title: <h3> inside the link
        title_els = link_el.xpath(".//h3")
        title = title_els[0].text_content().strip() if title_els else ""
        if not title:
            continue

        # Description: <p> inside the link
        desc_els = link_el.xpath(".//p")
        description = " ".join(el.text_content().strip() for el in desc_els).strip()

        entries.append(
            PublicacaoEntry(
                slug=slug,
                url=href,
                title=title,
                pub_type=pub_type,
                description=description,
            )
        )

    return entries


def _parse_detail_page(html_text: str) -> tuple[str | None, list[str]]:
    """Parse a detail page. Returns (pub_date, pdf_urls)."""
    tree = html.fromstring(html_text)

    # Date: <dt> containing "Data:" followed by <dd>
    pub_date: str | None = None
    for dt in tree.xpath("//dt"):
        if "Data" in (dt.text_content() or ""):
            dd = dt.getnext()
            if dd is not None and dd.tag == "dd":
                pub_date = dd.text_content().strip() or None
            break

    # PDF links: any <a href="...pdf"> inside a "Documentos" section
    pdf_urls: list[str] = []
    for a in tree.xpath("//a[@href]"):
        href = a.get("href", "")
        if href.lower().endswith(".pdf"):
            if href.startswith("/"):
                href = _BASE_URL + href
            if href not in pdf_urls:
                pdf_urls.append(href)

    return pub_date, pdf_urls


# ---------------------------------------------------------------------------
# Phase 1: Listing scraper
# ---------------------------------------------------------------------------


def _scrape_listing_pages(client: httpx.Client) -> list[PublicacaoEntry]:
    """Fetch all listing pages and return deduplicated PublicacaoEntry list."""
    all_entries: list[PublicacaoEntry] = []
    seen: set[str] = set()

    page = 1
    while True:
        params = {"pagina": str(page), "delta": str(_DELTA)}
        _log(f"listing page {page} (delta={_DELTA})…")
        try:
            resp = client.get(_LISTING_URL, params=params)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            _log(f"  HTTP {exc.response.status_code} — stopping")
            break

        entries = _parse_listing_page(resp.text)
        if not entries:
            _log("  no entries found — stopping pagination")
            break

        new = 0
        for e in entries:
            if e.slug not in seen:
                seen.add(e.slug)
                all_entries.append(e)
                new += 1

        _log(
            f"  page {page}: {len(entries)} found, {new} new (total {len(all_entries)})"
        )

        if len(entries) < _DELTA:
            _log("  partial page — reached end of listing")
            break

        page += 1
        time.sleep(_DELAY_SEC)

    return all_entries


# ---------------------------------------------------------------------------
# Phase 2: Detail scraper
# ---------------------------------------------------------------------------


def _enrich_with_detail(entries: list[PublicacaoEntry], client: httpx.Client) -> None:
    """Fetch each publication's detail page and fill in pub_date + pdf_urls (in-place)."""
    total = len(entries)
    for i, entry in enumerate(entries, 1):
        _log(f"  detail {i}/{total}: {entry.slug}")
        try:
            resp = client.get(entry.url)
            resp.raise_for_status()
            pub_date, pdf_urls = _parse_detail_page(resp.text)
            entry.pub_date = pub_date
            entry.pdf_urls = pdf_urls
            if not pdf_urls:
                _log(f"    warning: no PDFs found for {entry.slug}")
        except Exception as exc:
            _log(f"    error fetching detail for {entry.slug}: {exc}")
        time.sleep(_DELAY_SEC)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def scrape_all(skip_slugs: set[str] | None = None) -> list[PublicacaoEntry]:
    """Scrape all TCU institutional publications.

    Args:
        skip_slugs: Set of already-processed slugs to skip in Phase 2 detail fetching.
                    Slugs in this set still appear in the returned list (with empty
                    pub_date/pdf_urls) so the caller can decide whether to process them.
                    Pass None to scrape everything.

    Returns:
        List of PublicacaoEntry, where entries NOT in skip_slugs have pub_date and
        pdf_urls populated. Entries in skip_slugs are omitted from the return list.
    """
    with httpx.Client(
        timeout=30,
        follow_redirects=True,
        headers={"User-Agent": _USER_AGENT},
    ) as client:
        # Phase 1: collect all publication slugs and basic metadata
        _log("=== Phase 1: scraping listing pages ===")
        all_entries = _scrape_listing_pages(client)
        _log(f"Phase 1 complete: {len(all_entries)} publications found")

        # Filter out already-processed slugs
        if skip_slugs:
            to_enrich = [e for e in all_entries if e.slug not in skip_slugs]
            _log(
                f"Skipping {len(all_entries) - len(to_enrich)} already-processed slugs"
            )
        else:
            to_enrich = all_entries

        if not to_enrich:
            _log("Nothing new to enrich — all slugs already processed")
            return []

        # Phase 2: visit each detail page for PDF links + date
        _log(f"=== Phase 2: fetching details for {len(to_enrich)} publications ===")
        _enrich_with_detail(to_enrich, client)
        _log("Phase 2 complete")

    return to_enrich
