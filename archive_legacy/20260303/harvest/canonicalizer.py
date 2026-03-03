"""Canonicalization layer — deterministic HTML normalization for DOU pages.

Pure function: canonicalize(raw_bytes) -> bytes.
Deterministic, idempotent, no I/O, no side effects, no global state.

Strips server-side non-determinism (cache-busters, session tokens, dynamic IDs)
so that semantically identical pages produce identical output bytes.

This is Layer 1. Layer 0 (freezer) stores raw evidence unchanged.
"""
from __future__ import annotations

import re

# --- Compiled regex patterns ---
# Each pattern targets a specific source of Liferay server non-determinism.

# 1. Cache-buster timestamps appended to resource URLs.
#    Matches: ?t=<digits>, &t=<digits>, &amp;t=<digits>
_CACHE_BUSTER_RE = re.compile(rb"([?&](?:amp;)?t=)\d+")
_CACHE_BUSTER_REPLACEMENT = rb"\g<1>0"

# 2. Liferay per-session auth token injected into inline JS.
#    Matches: Liferay.authToken = 'abcdef1234' or Liferay.authToken = "abcdef1234"
_AUTH_TOKEN_RE = re.compile(rb"Liferay\.authToken\s*=\s*([\"']).*?\1")
_AUTH_TOKEN_REPLACEMENT = rb"Liferay.authToken='REDACTED'"

# 3. Hidden "today" input field with server-rendered current date.
#    Matches: <input ... name="today" ... value="..."> in any attribute order.
_TODAY_VALUE_RE = re.compile(
    rb'(<input\b(?=[^>]*\bname="today")[^>]*\bvalue=")[^"]*(")'
)
_TODAY_VALUE_REPLACEMENT = rb"\g<1>REDACTED\2"

# 4. "today" date embedded in listing navigation hrefs.
#    Matches: href="/leiturajornal?data=01-03-2026&secao=do1"
_TODAY_HREF_RE = re.compile(
    rb'(href="/leiturajornal\?data=)\d{2}-\d{2}-\d{4}(&(?:amp;)?secao=do[123]")'
)
_TODAY_HREF_REPLACEMENT = rb"\g<1>REDACTED\2"

# 5. Dynamic combo servlet IDs (hex fingerprints on aggregated resource URLs).
#    Matches: /combo?...stuff..." id="a1b2c3d4e5"
_COMBO_ID_RE = re.compile(rb'(/combo\?[^"]*")\s+id="[0-9a-fA-F]+"')
_COMBO_ID_REPLACEMENT = rb'\1 id="REDACTED"'

# Ordered pipeline of (pattern, replacement).
_PIPELINE: tuple[tuple[re.Pattern[bytes], bytes], ...] = (
    (_CACHE_BUSTER_RE, _CACHE_BUSTER_REPLACEMENT),
    (_AUTH_TOKEN_RE, _AUTH_TOKEN_REPLACEMENT),
    (_TODAY_VALUE_RE, _TODAY_VALUE_REPLACEMENT),
    (_TODAY_HREF_RE, _TODAY_HREF_REPLACEMENT),
    (_COMBO_ID_RE, _COMBO_ID_REPLACEMENT),
)


def canonicalize(raw: bytes) -> bytes:
    """Canonicalize raw HTML bytes by removing server non-determinism.

    Pure function. No I/O, no side effects.
    Deterministic: same input always produces same output.
    Idempotent: canonicalize(canonicalize(x)) == canonicalize(x).

    Args:
        raw: Unmodified HTML bytes from the freezer layer.

    Returns:
        Canonicalized bytes with non-deterministic tokens replaced
        by fixed constants.
    """
    result = raw
    for pattern, replacement in _PIPELINE:
        result = pattern.sub(replacement, result)
    return result
