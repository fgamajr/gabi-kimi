"""Normative document model — minimal structural representation.

Frozen dataclasses representing juridical units extracted from DOU pages.
No behavior, no I/O, no mutation.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Article:
    """A single article within a normative act."""
    number: str
    text: str


@dataclass(frozen=True, slots=True)
class NormativeAct:
    """A normative act (Decreto, Lei, Portaria, etc.) with its articles."""
    kind: str       # DECRETO, LEI, PORTARIA, etc.
    number: str     # "1.234", "12", etc.
    date: str       # raw date string as it appears in the header
    ementa: str     # summary text between header and first article
    articles: tuple[Article, ...]
