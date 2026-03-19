"""SEO: dynamic meta tags, JSON-LD, and XML sitemaps for GABI DOU."""

import html
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.backend.core.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SPA template handling
# ---------------------------------------------------------------------------

_template_prefix: str = ""
_template_suffix: str = ""
_template_loaded: bool = False


def load_spa_template() -> None:
    """Read dist/index.html once. Strip generic meta tags, split at </head>."""
    global _template_prefix, _template_suffix, _template_loaded

    index_path = Path(settings.SPA_DIST_DIR) / "index.html"
    if not index_path.exists():
        logger.warning("SPA template not found at %s — SEO HTML disabled", index_path)
        return

    raw = index_path.read_text(encoding="utf-8")

    # Strip existing generic tags we'll replace dynamically
    raw = re.sub(r"<title>[^<]*</title>\s*", "", raw)
    raw = re.sub(r'<meta\s+name="description"[^>]*>\s*', "", raw)
    raw = re.sub(r'<meta\s+property="og:[^"]*"[^>]*>\s*', "", raw)

    parts = raw.split("</head>", 1)
    if len(parts) != 2:
        logger.error("SPA template has no </head> — cannot inject meta tags")
        return

    _template_prefix = parts[0]
    _template_suffix = "</head>" + parts[1]
    _template_loaded = True
    logger.info("SPA template loaded from %s", index_path)


def is_template_loaded() -> bool:
    return _template_loaded


# ---------------------------------------------------------------------------
# Meta tag builders
# ---------------------------------------------------------------------------

def _truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rsplit(" ", 1)[0] + "\u2026"


def _esc(text: str) -> str:
    return html.escape(text, quote=True)


def _build_meta_block(
    title: str,
    description: str,
    canonical: str,
    og_type: str = "article",
) -> str:
    lines = [
        f"<title>{_esc(title)}</title>",
        f'<meta name="description" content="{_esc(description)}">',
        f'<link rel="canonical" href="{_esc(canonical)}">',
        f'<meta property="og:title" content="{_esc(title)}">',
        f'<meta property="og:description" content="{_esc(description)}">',
        f'<meta property="og:url" content="{_esc(canonical)}">',
        f'<meta property="og:type" content="{og_type}">',
        f'<meta property="og:locale" content="pt_BR">',
        f'<meta property="og:image" content="{settings.SITE_URL}/gabi-icon-512.png">',
    ]
    return "\n".join(lines)


def _inject(meta_block: str) -> str:
    return _template_prefix + "\n" + meta_block + "\n" + _template_suffix


# ---------------------------------------------------------------------------
# JSON-LD
# ---------------------------------------------------------------------------

def build_jsonld_document(doc: dict[str, Any], doc_id: str) -> str:
    ld = {
        "@context": "https://schema.org",
        "@type": "LegislationObject",
        "name": doc.get("identifica") or "",
        "description": doc.get("ementa") or "",
        "datePublished": doc.get("pub_date") or "",
        "inLanguage": "pt-BR",
        "publisher": {
            "@type": "GovernmentOrganization",
            "name": "Imprensa Nacional",
        },
        "url": f"{settings.SITE_URL}/document/{doc_id}",
    }
    organ = doc.get("issuing_organ")
    if organ:
        ld["creator"] = {"@type": "GovernmentOrganization", "name": organ}
    return '<script type="application/ld+json">' + json.dumps(ld, ensure_ascii=False) + "</script>"


def _build_jsonld_website() -> str:
    ld = {
        "@context": "https://schema.org",
        "@type": "WebSite",
        "name": "GABI DOU",
        "url": settings.SITE_URL,
        "potentialAction": {
            "@type": "SearchAction",
            "target": {
                "@type": "EntryPoint",
                "urlTemplate": f"{settings.SITE_URL}/search?q={{search_term_string}}",
            },
            "query-input": "required name=search_term_string",
        },
    }
    return '<script type="application/ld+json">' + json.dumps(ld, ensure_ascii=False) + "</script>"


# ---------------------------------------------------------------------------
# Page renderers
# ---------------------------------------------------------------------------

def render_document_html(doc: dict[str, Any], doc_id: str) -> str:
    identifica = doc.get("identifica") or "Documento"
    ementa = doc.get("ementa") or ""

    title = _truncate(f"{identifica} \u2014 GABI DOU", 70)
    description = _truncate(ementa, 160) if ementa else _truncate(identifica, 160)
    canonical = f"{settings.SITE_URL}/document/{doc_id}"

    meta = _build_meta_block(title, description, canonical, og_type="article")
    jsonld = build_jsonld_document(doc, doc_id)
    return _inject(meta + "\n" + jsonld)


def render_home_html() -> str:
    title = "GABI DOU \u2014 Busca no Di\u00e1rio Oficial da Uni\u00e3o"
    description = "Pesquise e consulte mais de 15 milh\u00f5es de publica\u00e7\u00f5es do Di\u00e1rio Oficial da Uni\u00e3o desde 2002."
    canonical = settings.SITE_URL

    meta = _build_meta_block(title, description, canonical, og_type="website")
    jsonld = _build_jsonld_website()
    return _inject(meta + "\n" + jsonld)


def render_search_html(query: str) -> str:
    safe_q = _truncate(query.strip(), 50)
    title = f'"{safe_q}" \u2014 Pesquisa no Di\u00e1rio Oficial'
    description = f'Resultados da busca por "{safe_q}" no Di\u00e1rio Oficial da Uni\u00e3o.'
    canonical = f"{settings.SITE_URL}/search?q={html.escape(query.strip(), quote=True)}"

    meta = _build_meta_block(title, description, canonical, og_type="website")
    return _inject(meta)


def render_fallback_html() -> str:
    title = "GABI DOU \u2014 Di\u00e1rio Oficial da Uni\u00e3o"
    description = "Pesquise e consulte publica\u00e7\u00f5es do Di\u00e1rio Oficial da Uni\u00e3o."
    canonical = settings.SITE_URL

    meta = _build_meta_block(title, description, canonical, og_type="website")
    return _inject(meta)


# ---------------------------------------------------------------------------
# Sitemap generation
# ---------------------------------------------------------------------------

_SITEMAP_XML_HEADER = '<?xml version="1.0" encoding="UTF-8"?>\n'


def build_sitemap_index(min_date: str, max_date: str) -> str:
    """Generate a sitemap index with one entry per year-month."""
    lines = [
        _SITEMAP_XML_HEADER,
        '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]

    try:
        start = datetime.fromisoformat(min_date[:10])
        end = datetime.fromisoformat(max_date[:10])
    except (ValueError, TypeError):
        start = datetime(2002, 1, 1)
        end = datetime.now(timezone.utc)

    year, month = start.year, start.month
    end_year, end_month = end.year, end.month

    while (year, month) <= (end_year, end_month):
        loc = f"{settings.SITE_URL}/sitemap-{year}-{month:02d}.xml"
        lines.append(f"  <sitemap><loc>{loc}</loc></sitemap>")
        month += 1
        if month > 12:
            month = 1
            year += 1

    lines.append("</sitemapindex>")
    return "\n".join(lines)


def build_sitemap_urls(doc_ids_dates: list[tuple[str, str]]) -> str:
    """Generate a sitemap from a list of (doc_id, pub_date) tuples."""
    lines = [
        _SITEMAP_XML_HEADER,
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for doc_id, pub_date in doc_ids_dates:
        loc = f"{settings.SITE_URL}/document/{doc_id}"
        lastmod = pub_date[:10] if pub_date else ""
        entry = f"  <url><loc>{loc}</loc>"
        if lastmod:
            entry += f"<lastmod>{lastmod}</lastmod>"
        entry += "</url>"
        lines.append(entry)
    lines.append("</urlset>")
    return "\n".join(lines)
