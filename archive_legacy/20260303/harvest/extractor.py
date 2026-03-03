"""Structural extraction layer — deterministic normative act parser.

Pure function: extract(canonical_bytes) -> NormativeAct.
Deterministic, no I/O, no side effects, no global state.
Operates only on canonicalized HTML bytes from Phase 2.

This is Layer 2. Layer 0 = freezer, Layer 1 = canonicalizer.
"""
from __future__ import annotations

import re
from html import unescape

from harvest.model import Article, NormativeAct


class ExtractionError(Exception):
    """Raised when extraction fails deterministically."""


# --- HTML stripping ---

_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_BLOCK_TAG_RE = re.compile(r"</?(?:p|div|br|hr|tr|li|h[1-6]|blockquote)\b[^>]*>", re.IGNORECASE)
_ANY_TAG_RE = re.compile(r"</?[A-Za-z][A-Za-z0-9:-]*\b[^>]*>")
_MULTI_SPACE_RE = re.compile(r"[ \t\xa0]+")


def _strip_html(html: str) -> str:
    """Remove HTML tags. Block tags become newlines; inline tags become spaces."""
    text = _COMMENT_RE.sub("", html)
    text = _BLOCK_TAG_RE.sub("\n", text)
    text = _ANY_TAG_RE.sub(" ", text)
    text = unescape(text)
    text = _MULTI_SPACE_RE.sub(" ", text)
    lines = [line.strip() for line in text.splitlines()]
    text = "\n".join(line for line in lines if line)
    return text.strip()


# --- Act header identification ---
# Matches: DECRETO Nº 1.234, DE 1º DE JANEIRO DE 2020
# Matches: LEI Nº 14.133, DE 1º DE ABRIL DE 2021
# Matches: PORTARIA Nº 12, DE 03 DE MARÇO DE 2021
# Matches: RESOLUÇÃO Nº 100, DE 20 DE DEZEMBRO DE 2024
# Case-sensitive, line-anchored — excludes in-text references.

_ACT_KINDS = (
    "DECRETO",
    "LEI",
    "PORTARIA",
    "RESOLUÇÃO",
)

_ACT_KINDS_PATTERN = "|".join(re.escape(k) for k in _ACT_KINDS)

_ACT_HEADER_RE = re.compile(
    rf"^({_ACT_KINDS_PATTERN})"
    r"\s+N\.?[º°]\s*"
    r"(\d+(?:\.\d+)*)"
    r"\s*,\s*DE\s+"
    r"(.+?)(?=\n|$)",
    re.MULTILINE,
)

# --- Article identification ---

_ARTICLE_RE = re.compile(
    r"^(Art\.\s*([1-9]\d*)[º°]?(?:-[A-Z])?\.?)(?=\s|$)",
    re.MULTILINE,
)


def _split_articles(text: str, matches: list[re.Match]) -> list[Article]:
    """Split text into articles at each Art. boundary."""
    if not matches:
        return []

    articles: list[Article] = []
    for i, m in enumerate(matches):
        number = m.group(2)
        start = m.end()
        if i + 1 < len(matches):
            end = matches[i + 1].start()
        else:
            end = len(text)

        body = text[start:end].strip()
        articles.append(Article(number=number, text=body))

    return articles


def _extract_ementa(text: str, header_end: int, first_article_start: int) -> str:
    """Extract ementa (summary) between act header and first article."""
    ementa = text[header_end:first_article_start].strip()
    return ementa


def extract(canonical: bytes) -> NormativeAct:
    """Extract a single normative act from canonicalized HTML bytes.

    Pure function. No I/O, no side effects.
    Deterministic: same input always produces same output.

    Args:
        canonical: Canonicalized HTML bytes from the canonicalizer layer.

    Returns:
        A single NormativeAct instance.

    Raises:
        ExtractionError: If no header found, more than one header found,
                         or no articles found.
    """
    try:
        decoded = canonical.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ExtractionError(f"invalid utf-8 canonical input: {exc}") from exc
    text = _strip_html(decoded)

    headers = list(_ACT_HEADER_RE.finditer(text))
    if not headers:
        raise ExtractionError("no normative act header found")
    if len(headers) > 1:
        raise ExtractionError(
            f"multiple headers found ({len(headers)}), expected exactly one"
        )

    header = headers[0]
    kind = header.group(1).upper()
    number = header.group(2)
    date_str = header.group(3).strip().rstrip(".,;:")

    act_text = text[header.end():]
    article_matches = list(_ARTICLE_RE.finditer(act_text))

    if not article_matches:
        raise ExtractionError(f"no articles found in {kind} Nº {number}")

    articles = _split_articles(act_text, article_matches)

    # Extract ementa
    first_art_start = article_matches[0].start()
    ementa = _extract_ementa(act_text, 0, first_art_start)

    return NormativeAct(
        kind=kind,
        number=number,
        date=date_str,
        ementa=ementa,
        articles=tuple(articles),
    )
