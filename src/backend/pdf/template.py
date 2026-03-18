"""HTML template for DOU-style PDF generation.

Renders a document as an A4 page mimicking the printed Diário Oficial da União,
with coat of arms, serif typography, filigree borders, and structured layout.
"""

from __future__ import annotations

import html
import re
from datetime import datetime
from typing import Any

# ---------------------------------------------------------------------------
# Section names
# ---------------------------------------------------------------------------
_SECTION_LABELS = {
    "1": "Seção 1", "2": "Seção 2", "3": "Seção 3",
    "e": "Edição Extra", "DO1": "Seção 1", "DO2": "Seção 2",
    "DO3": "Seção 3", "DOE": "Edição Extra",
}

# ---------------------------------------------------------------------------
# Coat of arms SVG (adapted from doc-viewer.jsx)
# ---------------------------------------------------------------------------
_COAT_OF_ARMS_SVG = """
<svg viewBox="0 0 100 100" width="64" height="64" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <linearGradient id="shield" x1="0%" y1="0%" x2="0%" y2="100%">
      <stop offset="0%" stop-color="#1B5E20"/>
      <stop offset="100%" stop-color="#2E7D32"/>
    </linearGradient>
    <linearGradient id="gold" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#C8A415"/>
      <stop offset="100%" stop-color="#D4AF37"/>
    </linearGradient>
  </defs>
  <ellipse cx="50" cy="48" rx="38" ry="40" fill="url(#shield)"/>
  <ellipse cx="50" cy="48" rx="34" ry="36" fill="url(#gold)"/>
  <ellipse cx="50" cy="48" rx="30" ry="32" fill="#1565C0"/>
  <circle cx="50" cy="32" r="1.6" fill="white" opacity="0.9"/>
  <circle cx="42" cy="38" r="1.6" fill="white" opacity="0.9"/>
  <circle cx="58" cy="38" r="1.6" fill="white" opacity="0.9"/>
  <circle cx="38" cy="48" r="1.6" fill="white" opacity="0.9"/>
  <circle cx="62" cy="48" r="1.6" fill="white" opacity="0.9"/>
  <circle cx="44" cy="56" r="1.6" fill="white" opacity="0.9"/>
  <circle cx="56" cy="56" r="1.6" fill="white" opacity="0.9"/>
  <circle cx="50" cy="62" r="1.6" fill="white" opacity="0.9"/>
  <circle cx="35" cy="55" r="1.6" fill="white" opacity="0.9"/>
  <circle cx="65" cy="55" r="1.6" fill="white" opacity="0.9"/>
  <circle cx="50" cy="46" r="1.6" fill="white" opacity="0.9"/>
  <path d="M15 82 Q50 72 85 82 Q50 90 15 82Z" fill="url(#gold)" stroke="#8B6914" stroke-width="0.5"/>
  <path d="M12 30 Q8 50 15 75" fill="none" stroke="#2E7D32" stroke-width="3" stroke-linecap="round"/>
  <path d="M88 30 Q92 50 85 75" fill="none" stroke="#2E7D32" stroke-width="3" stroke-linecap="round"/>
  <ellipse cx="12" cy="30" rx="6" ry="3" fill="#388E3C" transform="rotate(-20 12 30)"/>
  <ellipse cx="11.5" cy="39" rx="6" ry="3" fill="#388E3C" transform="rotate(-15 11.5 39)"/>
  <ellipse cx="11" cy="48" rx="6" ry="3" fill="#388E3C" transform="rotate(-10 11 48)"/>
  <ellipse cx="10.5" cy="57" rx="6" ry="3" fill="#388E3C" transform="rotate(-5 10.5 57)"/>
  <ellipse cx="10" cy="66" rx="6" ry="3" fill="#388E3C" transform="rotate(0 10 66)"/>
  <ellipse cx="88" cy="30" rx="6" ry="3" fill="#388E3C" transform="rotate(20 88 30)"/>
  <ellipse cx="88.5" cy="39" rx="6" ry="3" fill="#388E3C" transform="rotate(15 88.5 39)"/>
  <ellipse cx="89" cy="48" rx="6" ry="3" fill="#388E3C" transform="rotate(10 89 48)"/>
  <ellipse cx="89.5" cy="57" rx="6" ry="3" fill="#388E3C" transform="rotate(5 89.5 57)"/>
  <ellipse cx="90" cy="66" rx="6" ry="3" fill="#388E3C" transform="rotate(0 90 66)"/>
  <polygon points="50,8 52,14 58,14 53,18 55,24 50,20 45,24 47,18 42,14 48,14"
           fill="url(#gold)" stroke="#8B6914" stroke-width="0.3"/>
</svg>
"""


# ---------------------------------------------------------------------------
# Body text structure detection
# ---------------------------------------------------------------------------

_RE_CONSIDERANDO = re.compile(
    r"^(CONSIDERANDO)\b", re.MULTILINE,
)
_RE_ARTIGO = re.compile(
    r"^(Art\.\s*\d+[°º]?\.?)", re.MULTILINE,
)
_RE_INCISO = re.compile(
    r"^(\s*[IVXLCDM]+\s*[-–—])", re.MULTILINE,
)
_RE_PARAGRAFO = re.compile(
    r"^((?:Parágrafo único|§\s*\d+[°º]?)\.?)", re.MULTILINE,
)
_RE_RESOLVE = re.compile(
    r"^(RESOLVE:|DECRETA:|DETERMINA:)\s*$", re.MULTILINE,
)


def _format_body(text: str) -> str:
    """Convert plain text body to structured HTML with DOU formatting."""
    if not text:
        return ""

    escaped = html.escape(text)
    lines = escaped.split("\n")
    result: list[str] = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        # CONSIDERANDO
        if _RE_CONSIDERANDO.match(stripped):
            stripped = _RE_CONSIDERANDO.sub(
                r'<span class="considerando">\1</span>', stripped
            )
            result.append(f'<p class="considerando-p">{stripped}</p>')
        # RESOLVE / DECRETA
        elif _RE_RESOLVE.match(stripped):
            result.append(f'<p class="resolve">{stripped}</p>')
        # Art. N°
        elif _RE_ARTIGO.match(stripped):
            stripped = _RE_ARTIGO.sub(r'<span class="art-num">\1</span>', stripped)
            result.append(f'<p class="artigo">{stripped}</p>')
        # § / Parágrafo único
        elif _RE_PARAGRAFO.match(stripped):
            stripped = _RE_PARAGRAFO.sub(r'<span class="art-num">\1</span>', stripped)
            result.append(f'<p class="paragrafo">{stripped}</p>')
        # I —, II —
        elif _RE_INCISO.match(stripped):
            stripped = _RE_INCISO.sub(r'<span class="inciso-num">\1</span>', stripped)
            result.append(f'<p class="inciso">{stripped}</p>')
        else:
            result.append(f"<p>{stripped}</p>")

    return "\n".join(result)


def _format_date(pub_date: str) -> str:
    """Format date to Brazilian locale style."""
    try:
        dt = datetime.fromisoformat(pub_date.replace("Z", "+00:00"))
        months = [
            "", "janeiro", "fevereiro", "março", "abril", "maio", "junho",
            "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
        ]
        return f"{dt.day} de {months[dt.month]} de {dt.year}"
    except Exception:
        return pub_date or ""


# ---------------------------------------------------------------------------
# Main template
# ---------------------------------------------------------------------------

def render_pdf_html(doc: dict[str, Any]) -> str:
    """Render a DOU document as a complete HTML page ready for weasyprint."""

    title = html.escape(doc.get("identifica") or doc.get("title") or "")
    ementa = html.escape(doc.get("ementa") or doc.get("subtitle") or "")
    organ = html.escape(doc.get("issuing_organ") or "")
    art_type = html.escape(doc.get("art_type") or "")
    body = _format_body(doc.get("body_plain") or "")
    pub_date = _format_date(doc.get("pub_date") or "")
    section = doc.get("section") or doc.get("edition_section") or ""
    section_label = _SECTION_LABELS.get(section, section)
    page = doc.get("page") or doc.get("page_number") or ""
    edition = doc.get("edition") or doc.get("edition_number") or ""
    signer = html.escape(doc.get("primary_signer") or "")
    signers_all = doc.get("signers_all_flat") or []

    # Build signer block
    signer_html = ""
    if signers_all:
        parts = [f"<p>{html.escape(s)}</p>" for s in signers_all]
        signer_html = "\n".join(parts)
    elif signer:
        signer_html = f"<p>{signer}</p>"

    # Build meta line
    meta_parts = []
    if pub_date:
        meta_parts.append(f"Publicado em: {pub_date}")
    if section_label:
        meta_parts.append(section_label)
    if edition:
        meta_parts.append(f"Edição: {edition}")
    if page:
        meta_parts.append(f"Página: {page}")
    meta_line = " &nbsp;|&nbsp; ".join(meta_parts)

    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8"/>
<title>{title}</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,400;0,600;0,700;1,400;1,600&family=DM+Sans:wght@400;500;600&display=swap');

@page {{
    size: A4;
    margin: 2cm 1.8cm 2.5cm 1.8cm;
    @top-center {{
        content: "";
    }}
    @bottom-center {{
        content: "Documento gerado por GABI DOU — gabidou.top";
        font-family: 'DM Sans', sans-serif;
        font-size: 7pt;
        color: #999;
    }}
}}

* {{ margin: 0; padding: 0; box-sizing: border-box; }}

body {{
    font-family: 'Cormorant Garamond', 'Liberation Serif', Georgia, serif;
    font-size: 11pt;
    line-height: 1.5;
    color: #1A1612;
    background: white;
}}

/* ── Filigree borders ── */
.filigree-top {{
    height: 5px;
    background: linear-gradient(90deg, #8B6914, #C8A415, #8B6914);
    margin-bottom: 20pt;
}}

.filigree-bottom {{
    height: 3px;
    background: linear-gradient(90deg, #8B6914, #C8A415, #8B6914);
    margin-top: 24pt;
}}

/* ── Header ── */
.header {{
    text-align: center;
    margin-bottom: 20pt;
    padding-bottom: 16pt;
    border-bottom: 1px solid #C4B89A;
}}

.coat-of-arms {{
    display: block;
    margin: 0 auto 8pt;
}}

.republic-line {{
    font-family: 'Cormorant Garamond', serif;
    font-size: 9pt;
    font-weight: 600;
    letter-spacing: 3pt;
    color: #3D3529;
    text-transform: uppercase;
    margin-bottom: 2pt;
}}

.dou-title {{
    font-family: 'Cormorant Garamond', serif;
    font-size: 16pt;
    font-weight: 700;
    letter-spacing: 4pt;
    color: #1A1612;
    text-transform: uppercase;
    margin-bottom: 8pt;
}}

.pub-meta {{
    font-family: 'DM Sans', sans-serif;
    font-size: 8pt;
    color: #3D3529;
    letter-spacing: 0.5pt;
}}

/* ── Organ / Act type ── */
.orgao {{
    font-family: 'Cormorant Garamond', serif;
    font-size: 12pt;
    font-weight: 700;
    text-align: center;
    color: #1A1612;
    text-transform: uppercase;
    letter-spacing: 2pt;
    margin-bottom: 4pt;
    margin-top: 16pt;
}}

.art-type {{
    font-family: 'DM Sans', sans-serif;
    font-size: 9pt;
    text-align: center;
    color: #3D3529;
    letter-spacing: 1pt;
    text-transform: uppercase;
    margin-bottom: 16pt;
}}

/* ── Title / Identifica ── */
.identifica {{
    font-family: 'Cormorant Garamond', serif;
    font-size: 14pt;
    font-weight: 700;
    text-align: center;
    color: #8B1A1A;
    letter-spacing: 0.5pt;
    line-height: 1.4;
    margin-bottom: 14pt;
}}

/* ── Ementa ── */
.ementa {{
    font-family: 'Cormorant Garamond', serif;
    font-size: 10pt;
    font-style: italic;
    color: #3D3529;
    line-height: 1.5;
    padding: 10pt 16pt;
    border-left: 3px solid #8B6914;
    margin-bottom: 20pt;
    background: #FDFAF2;
}}

/* ── Body (two columns) ── */
.body-content {{
    column-count: 2;
    column-gap: 24pt;
    column-rule: 1px solid #E0D8C8;
    text-align: justify;
    hyphens: auto;
    -webkit-hyphens: auto;
}}

.body-content p {{
    margin-bottom: 6pt;
    text-indent: 24pt;
    orphans: 3;
    widows: 3;
}}

/* CONSIDERANDO */
.body-content .considerando {{
    font-weight: 700;
    color: #8B1A1A;
    font-variant: small-caps;
}}

.body-content .considerando-p {{
    text-indent: 24pt;
    margin-bottom: 4pt;
}}

/* RESOLVE / DECRETA */
.body-content .resolve {{
    text-align: center;
    font-weight: 700;
    font-size: 12pt;
    letter-spacing: 2pt;
    margin: 12pt 0;
    text-indent: 0;
    column-span: all;
}}

/* Art. N° */
.body-content .artigo {{
    text-indent: 0;
    margin-top: 8pt;
    margin-bottom: 4pt;
}}

.body-content .art-num {{
    font-weight: 700;
    color: #1A1612;
}}

/* Parágrafo / § */
.body-content .paragrafo {{
    text-indent: 24pt;
    margin-bottom: 4pt;
}}

/* Incisos (I —, II —) */
.body-content .inciso {{
    text-indent: 0;
    padding-left: 36pt;
    margin-bottom: 3pt;
}}

.body-content .inciso-num {{
    font-weight: 600;
    color: #3D3529;
}}

/* ── Signature block ── */
.signature {{
    margin-top: 24pt;
    padding-top: 16pt;
    border-top: 1px solid #C4B89A;
    text-align: center;
    column-span: all;
}}

.signature p {{
    font-family: 'Cormorant Garamond', serif;
    font-size: 11pt;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 1pt;
    margin-bottom: 2pt;
}}
</style>
</head>
<body>

<div class="filigree-top"></div>

<div class="header">
    {_COAT_OF_ARMS_SVG}
    <div class="republic-line">República Federativa do Brasil</div>
    <div class="dou-title">Diário Oficial da União</div>
    <div class="pub-meta">{meta_line}</div>
</div>

{"<div class='orgao'>" + organ + "</div>" if organ else ""}
{"<div class='art-type'>" + art_type + "</div>" if art_type else ""}
<div class="identifica">{title}</div>
{"<div class='ementa'>" + ementa + "</div>" if ementa else ""}

<div class="body-content">
{body}
</div>

{"<div class='signature'>" + signer_html + "</div>" if signer_html else ""}

<div class="filigree-bottom"></div>

</body>
</html>"""
