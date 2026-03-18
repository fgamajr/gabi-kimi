"""Query intent classification for dynamic ranking."""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

# Import person name detector from existing code
from src.backend.search.hybrid import _is_person_name, _query_word_count
from src.backend.search.topic_profiles import match_topic_profile


# ---------------------------------------------------------------------------
# Enums & data classes
# ---------------------------------------------------------------------------

class QueryIntent(Enum):
    EXACT_NAME = "exact_name"
    CANONICAL_LOOKUP = "canonical_lookup"
    PERSON_NAME = "person_name"
    TRENDING_BROWSE = "trending_browse"
    SUBJECT_EXPLORE = "subject_explore"


@dataclass
class IntentResult:
    intent: QueryIntent
    confidence: float
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Text normalisation
# ---------------------------------------------------------------------------

def _normalize_for_matching(s: str) -> str:
    """Lowercase + strip accents (NFD decompose, remove combining chars)."""
    s = s.lower().strip()
    nfkd = unicodedata.normalize("NFD", s)
    return "".join(c for c in nfkd if unicodedata.category(c) != "Mn")


# ---------------------------------------------------------------------------
# Canonical laws index (loaded once at import)
# ---------------------------------------------------------------------------

_CANONICAL_LAWS_PATH = Path(__file__).resolve().parent.parent / "data" / "canonical_laws.json"

with open(_CANONICAL_LAWS_PATH, encoding="utf-8") as _f:
    CANONICAL_LAWS: list[dict[str, Any]] = json.load(_f)

# Build alias -> entry index at import time
_ALIAS_INDEX: dict[str, dict[str, Any]] = {}
for _entry in CANONICAL_LAWS:
    for _alias in _entry["aliases"]:
        _ALIAS_INDEX[_normalize_for_matching(_alias)] = _entry

_MATCH_STOPWORDS = frozenset({"da", "de", "do", "das", "dos", "e", "lei", "codigo", "estatuto"})


# ---------------------------------------------------------------------------
# ART_TYPE_ALIASES & ORGAN_ALIASES (precompiled at module scope)
# ---------------------------------------------------------------------------

ART_TYPE_ALIASES: dict[str, str] = {
    "port.": "portaria", "port": "portaria", "portaria": "portaria",
    "dec.": "decreto", "dec": "decreto", "decreto": "decreto",
    "decreto-lei": "decreto-lei", "dl": "decreto-lei",
    "mp": "medida provisoria", "medida provisoria": "medida provisoria",
    "med. prov.": "medida provisoria",
    "in": "instrucao normativa", "instrucao normativa": "instrucao normativa",
    "inst. norm.": "instrucao normativa",
    "res.": "resolucao", "res": "resolucao", "resolucao": "resolucao",
    "lc": "lei complementar", "lei complementar": "lei complementar",
    "lei": "lei",
    "edital": "edital",
    "acordao": "acordao",
}

ORGAN_ALIASES: dict[str, str] = {
    "ministerio da educacao": "MEC", "mec": "MEC",
    "ministerio da saude": "MS", "ms": "MS",
    "receita federal": "RFB", "rfb": "RFB",
    "banco central": "BCB", "bacen": "BCB", "bcb": "BCB",
    "tribunal de contas da uniao": "TCU", "tcu": "TCU",
    "advocacia geral da uniao": "AGU", "agu": "AGU",
    "ministerio do trabalho": "MTE", "mte": "MTE",
    "ministerio da justica": "MJ", "mj": "MJ",
    "ministerio da fazenda": "MF", "mf": "MF",
    "aneel": "ANEEL", "anatel": "ANATEL", "anvisa": "ANVISA",
    "anac": "ANAC", "ana": "ANA", "ibama": "IBAMA",
    "inss": "INSS", "inpi": "INPI",
    "cgu": "CGU", "controladoria geral da uniao": "CGU",
    "anpd": "ANPD",
}

# ---------------------------------------------------------------------------
# DOU recurring categories (trending detection)
# ---------------------------------------------------------------------------

DOU_RECURRING_CATEGORIES: list[str] = [
    "concurso", "concursos", "nomeacao", "nomeacoes", "exoneracao",
    "licitacao", "licitacoes", "edital", "editais", "pregao",
    "aposentadoria", "pensao", "cessao", "designacao",
    "convenio", "convenios", "contrato", "contratos",
    "multa", "multas", "sancao", "sancoes",
    "autorizacao", "homologacao", "ratificacao",
    "portaria", "decreto", "resolucao",
]

_TRENDING_SET: frozenset[str] = frozenset(DOU_RECURRING_CATEGORIES)

# ---------------------------------------------------------------------------
# Precompiled regex for EXACT_NAME detection
# ---------------------------------------------------------------------------

_EXACT_NAME_PATTERN = re.compile(
    r"^(?:port\.?|portaria|dec\.?|decreto(?:\s*-?\s*lei)?|"
    r"lei(?:\s+complementar)?|mp|medida\s+prov[io]s[oo]ria|"
    r"in|instru[cc][aa]o\s+normativa|"
    r"res\.?|resolu[cc][aa]o|edital|ac[oo]rd[aa]o|lc|dl)"
    r"\s+(?:\w+\s+)?(?:n[°º.]?\s*)?(\d[\d.]*(?:/\d{2,4})?)",
    re.IGNORECASE,
)

# More detailed pattern for parsing structured parts
_EXACT_NAME_PARSE = re.compile(
    r"^(?P<art_type>port\.?|portaria|dec\.?|decreto(?:\s*-?\s*lei)?|"
    r"lei(?:\s+complementar)?|mp|medida\s+prov[io]s[oo]ria|"
    r"in|instru[cc][aa]o\s+normativa|inst\.\s*norm\.|"
    r"res\.?|resolu[cc][aa]o|edital|ac[oo]rd[aa]o|lc|dl)"
    r"\s+(?:(?P<organ>[a-zA-Z][a-zA-Z.]+(?:\s+[a-zA-Z.]+)*)\s+)?"
    r"(?:n[°º.]?\s*)?(?P<number>\d[\d.]*)"
    r"(?:/(?P<year>\d{2,4}))?",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# normalize_exact_name
# ---------------------------------------------------------------------------

def normalize_exact_name(query: str) -> dict | None:
    """Parse queries like 'port. MEC 234/26' into structured parts.

    Returns dict with keys: art_type, organ, number, year (all strings)
    or None if the query doesn't match an exact-name pattern.
    """
    q = query.strip()
    m = _EXACT_NAME_PARSE.match(q)
    if not m:
        return None

    raw_art = _normalize_for_matching(m.group("art_type"))
    art_type = ART_TYPE_ALIASES.get(raw_art, raw_art)

    organ_raw = m.group("organ")
    organ: str | None = None
    if organ_raw:
        organ_key = _normalize_for_matching(organ_raw)
        organ = ORGAN_ALIASES.get(organ_key, organ_raw.upper())

    number = m.group("number")

    year_raw = m.group("year")
    year: int | None = None
    if year_raw:
        if len(year_raw) == 2:
            yr = int(year_raw)
            cutoff = (datetime.now(timezone.utc).year % 100) + 10
            year = 2000 + yr if yr <= cutoff else 1900 + yr
        else:
            year = int(year_raw)

    return {
        "art_type": art_type,
        "organ": organ,
        "number": number,
        "year": year,
    }


# ---------------------------------------------------------------------------
# _match_canonical
# ---------------------------------------------------------------------------

def _match_canonical(query: str) -> dict | None:
    """Match query against canonical laws index.

    Returns dict with canonical entry data + optional 'suggestion', or None.
    """
    norm = _normalize_for_matching(query)

    # 1. Exact alias match -> confidence 0.95
    if norm in _ALIAS_INDEX:
        entry = _ALIAS_INDEX[norm]
        return {
            "entry": entry,
            "confidence": 0.95,
            "matched_alias": norm,
        }

    # 2. Substring match — query must be substantial part of an alias
    #    (min 4 chars, and query must cover >=50% of alias length)
    if len(norm) >= 4:
        best_match = None
        best_overlap = 0.0
        for alias, entry in _ALIAS_INDEX.items():
            if norm in alias:
                overlap = len(norm) / len(alias)
                if overlap >= 0.5 and overlap > best_overlap:
                    best_match = (alias, entry)
                    best_overlap = overlap
        if best_match:
            alias, entry = best_match
            return {
                "entry": entry,
                "confidence": 0.80,
                "matched_alias": alias,
                "suggestion": entry["aliases"][0],
            }

    # 3. Token-overlap fuzzy match for partial canonical queries
    query_tokens = {token for token in re.findall(r"[a-z0-9]+", norm) if token not in _MATCH_STOPWORDS}
    if len(query_tokens) >= 2:
        best_match = None
        best_overlap = 0.0
        for alias, entry in _ALIAS_INDEX.items():
            alias_tokens = {token for token in re.findall(r"[a-z0-9]+", alias) if token not in _MATCH_STOPWORDS}
            if not alias_tokens:
                continue
            overlap = len(query_tokens & alias_tokens) / len(query_tokens)
            if overlap >= 0.66 and overlap > best_overlap:
                best_match = (alias, entry)
                best_overlap = overlap
        if best_match:
            alias, entry = best_match
            return {
                "entry": entry,
                "confidence": 0.78,
                "matched_alias": alias,
                "suggestion": entry["aliases"][0],
            }

    return None


# ---------------------------------------------------------------------------
# _is_trending_query
# ---------------------------------------------------------------------------

def _is_trending_query(query: str, *, is_trending: bool = False) -> bool:
    """Check if query matches a recurring DOU category.

    Returns True if is_trending flag is set OR the normalised query
    has 1-2 meaningful words and matches a DOU recurring category.
    """
    if is_trending:
        return True

    word_count = _query_word_count(query)
    if word_count < 1 or word_count > 2:
        return False

    norm = _normalize_for_matching(query)
    # Check if normalised query is a substring of (or contains) any category
    for cat in _TRENDING_SET:
        if cat in norm or norm in cat:
            return True

    return False


# ---------------------------------------------------------------------------
# Main classifier
# ---------------------------------------------------------------------------

def classify_intent(
    query: str,
    *,
    is_trending: bool = False,
) -> IntentResult:
    """Classify query intent with strict priority ordering.

    Priority:
      1. EXACT_NAME   - regex detects art_type + number
      2. CANONICAL_LOOKUP - match in canonical laws index
      3. CURATED_TOPIC - explicit high-value topic profile
      4. PERSON_NAME  - existing _is_person_name() heuristic
      5. TRENDING_BROWSE - is_trending flag or DOU recurring category
      6. SUBJECT_EXPLORE - fallback
    """
    # Truncate long queries
    q = query[:200].strip()

    # 1. EXACT_NAME — structured legal reference (art_type + number)
    exact = normalize_exact_name(q)
    if exact:
        return IntentResult(
            intent=QueryIntent.EXACT_NAME,
            confidence=0.95,
            metadata=exact,
        )

    profile = match_topic_profile(q)

    # 2. CANONICAL_LOOKUP — known law by alias
    canon = _match_canonical(q)
    if canon:
        if profile and canon["confidence"] < 0.9:
            intent = (
                QueryIntent.TRENDING_BROWSE
                if profile.intent == QueryIntent.TRENDING_BROWSE.value
                else QueryIntent.SUBJECT_EXPLORE
            )
            return IntentResult(
                intent=intent,
                confidence=0.84,
                metadata={
                    "topic_profile": profile.to_metadata(),
                    "topic": profile.label,
                },
            )
        return IntentResult(
            intent=QueryIntent.CANONICAL_LOOKUP,
            confidence=canon["confidence"],
            metadata=canon,
        )

    # 3. CURATED_TOPIC — explicit high-value browse/explore profiles
    if profile:
        intent = (
            QueryIntent.TRENDING_BROWSE
            if profile.intent == QueryIntent.TRENDING_BROWSE.value
            else QueryIntent.SUBJECT_EXPLORE
        )
        return IntentResult(
            intent=intent,
            confidence=0.9 if is_trending else 0.84,
            metadata={
                "topic_profile": profile.to_metadata(),
                "topic": profile.label,
            },
        )

    # 4. PERSON_NAME — heuristic name detection
    if _is_person_name(q):
        return IntentResult(
            intent=QueryIntent.PERSON_NAME,
            confidence=0.85,
            metadata={},
        )

    # 5. TRENDING_BROWSE — recurring DOU categories
    if _is_trending_query(q, is_trending=is_trending):
        return IntentResult(
            intent=QueryIntent.TRENDING_BROWSE,
            confidence=0.80,
            metadata={"category": _normalize_for_matching(q)},
        )

    # 6. SUBJECT_EXPLORE — fallback
    return IntentResult(
        intent=QueryIntent.SUBJECT_EXPLORE,
        confidence=0.50,
        metadata={},
    )
