"""Document chunking helpers for RAG/hybrid retrieval pipelines."""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any


_WS_RE = re.compile(r"[ \t]+")
_NL_RE = re.compile(r"\n{3,}")
_WORD_RE = re.compile(r"\S+")


@dataclass(slots=True)
class DocumentChunk:
    """Chunk payload ready for persistence/indexing."""

    chunk_index: int
    chunk_text: str
    chunk_text_norm: str
    chunk_char_start: int
    chunk_char_end: int
    token_estimate: int
    heading_context: str
    metadata: dict[str, Any]


def normalize_text(text: str) -> str:
    """Normalize whitespace while preserving basic paragraph breaks."""
    if not text:
        return ""
    # Keep newlines as structural hints but collapse repeated spaces.
    s = text.replace("\r\n", "\n").replace("\r", "\n")
    s = _WS_RE.sub(" ", s)
    s = _NL_RE.sub("\n\n", s)
    return s.strip()


def normalize_for_lookup(text: str) -> str:
    """Normalize text for optional fallback matching/indexing."""
    return normalize_text(text).casefold()


def estimate_tokens(text: str) -> int:
    """Cheap token estimate suitable for chunk budgeting."""
    if not text:
        return 0
    # Portuguese prose averages ~0.75 words per token in legal corpora.
    words = len(_WORD_RE.findall(text))
    return max(1, int(math.ceil(words / 0.75)))


def _find_split_point(
    text: str,
    start: int,
    target_size: int,
    min_size: int,
    max_size: int,
) -> int:
    """Find a robust split boundary near target size."""
    n = len(text)
    if start >= n:
        return n

    min_end = min(n, start + max(1, min_size))
    target_end = min(n, start + max(1, target_size))
    max_end = min(n, start + max(1, max_size))
    if target_end >= n:
        return n

    # Prefer sentence/paragraph boundaries after target.
    for i in range(target_end, max_end):
        ch = text[i]
        if ch in ".!?:;\n":
            j = i + 1
            while j < n and text[j] == " ":
                j += 1
            if j >= min_end:
                return j

    # Fallback: nearest boundary before target.
    for i in range(target_end, min_end - 1, -1):
        ch = text[i - 1]
        if ch in ".!?:;\n":
            return i

    # Last resort: hard cut.
    return max_end


def chunk_document(
    body_plain: str,
    *,
    heading_context: str = "",
    metadata: dict[str, Any] | None = None,
    chunk_size: int = 900,
    chunk_overlap: int = 150,
    min_chunk_size: int = 280,
    max_chunk_size: int = 1400,
) -> list[DocumentChunk]:
    """Split a document body into deterministic overlapping chunks.

    Offsets are calculated over normalized body text.
    """
    text = normalize_text(body_plain)
    if not text:
        return []

    metadata = metadata or {}
    out: list[DocumentChunk] = []
    idx = 0
    start = 0
    prev_start = -1
    n = len(text)

    while start < n:
        end = _find_split_point(
            text,
            start,
            target_size=chunk_size,
            min_size=min_chunk_size,
            max_size=max_chunk_size,
        )
        if end <= start:
            end = min(n, start + max(1, chunk_size))

        raw = text[start:end]
        left_trim = len(raw) - len(raw.lstrip())
        right_trim = len(raw) - len(raw.rstrip())
        chunk_text = raw.strip()
        if chunk_text:
            c_start = start + left_trim
            c_end = end - right_trim
            out.append(
                DocumentChunk(
                    chunk_index=idx,
                    chunk_text=chunk_text,
                    chunk_text_norm=normalize_for_lookup(chunk_text),
                    chunk_char_start=c_start,
                    chunk_char_end=c_end,
                    token_estimate=estimate_tokens(chunk_text),
                    heading_context=heading_context.strip(),
                    metadata=dict(metadata),
                )
            )
            idx += 1

        if end >= n:
            break

        next_start = max(0, end - max(0, chunk_overlap))
        if next_start <= prev_start or next_start <= start:
            next_start = end
        prev_start = start
        start = next_start

    return out
