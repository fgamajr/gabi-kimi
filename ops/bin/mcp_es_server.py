"""GABI Elasticsearch MCP Server — enterprise-grade BM25 search tooling.

Professional search server for Diário Oficial da União (DOU).
16M+ legal documents (2002-2026). Full-text BM25 with:
  - Smart query parsing (quoted phrases, legal references, proximity)
  - Two-stage search (precision-first, automatic recall fallback)
  - Function scoring (recency decay, authority signals)
  - R11 synonym expansion for Portuguese legal vocabulary
  - Filter inference from natural language
  - 13 specialized tools for search, discovery, and analysis

Usage:
  python ops/bin/mcp_es_server.py
  python ops/bin/mcp_es_server.py --transport sse --port 8766
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

import httpx
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

try:
    from mcp.server.fastmcp import FastMCP
except ModuleNotFoundError:
    FastMCP = None  # type: ignore[assignment]


load_dotenv()


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


SYNONYM_EXPANSION = _env_bool("SYNONYM_EXPANSION", True)
MIN_RESULTS_BEFORE_FALLBACK = int(os.getenv("MIN_RESULTS_BEFORE_FALLBACK", "3"))
RERANK_POOL = int(os.getenv("RERANK_POOL", "60"))

# Re-ranker signal weights (must sum to 1.0)
_W_BM25 = 0.40       # ES BM25 score (normalized)
_W_COVERAGE = 0.12    # Query term coverage across all fields
_W_TITLE = 0.20       # Query term match in identifica (title)
_W_EMENTA = 0.10      # Query term match in ementa (summary)
_W_PROXIMITY = 0.18   # How close query terms appear to each other


# ---------------------------------------------------------------------------
# Filter inference (inlined from legacy adapters.py)
# ---------------------------------------------------------------------------

_SECTION_PATTERN = re.compile(r"\bdo([123](?:e)?)\b", re.IGNORECASE)

_ART_TYPE_PATTERNS = [
    (re.compile(r"\baviso(?:s)?\s+de\s+licitac[aã]o\b", re.IGNORECASE), "aviso"),
    (re.compile(r"\bpreg[aã]o(?:es)?\s+eletr[oô]nico(?:s)?\b", re.IGNORECASE), "pregão"),
    (re.compile(r"\bpreg[aã]o(?:es)?\b", re.IGNORECASE), "pregão"),
    (re.compile(r"\bportaria(?:s)?\b", re.IGNORECASE), "portaria"),
    (re.compile(r"\bdecreto(?:s)?\b", re.IGNORECASE), "decreto"),
    (re.compile(r"\bedital(?:is)?\b", re.IGNORECASE), "edital"),
    (re.compile(r"\bextrato(?:s)?\b", re.IGNORECASE), "extrato"),
    (re.compile(r"\bresolu[cç][aã]o(?:es)?\b", re.IGNORECASE), "resolução"),
    (re.compile(r"\bdespacho(?:s)?\b", re.IGNORECASE), "despacho"),
]

_ORGAN_PATTERNS = [
    (re.compile(r"\bminist[eé]rio\s+da\s+sa[uú]de\b", re.IGNORECASE), "Ministério da Saúde"),
    (re.compile(r"\bminist[eé]rio\s+da\s+justi[cç]a\b", re.IGNORECASE), "Ministério da Justiça"),
    (re.compile(r"\bminist[eé]rio\s+da\s+fazenda\b", re.IGNORECASE), "Ministério da Fazenda"),
    (re.compile(r"\bminist[eé]rio\s+da\s+educa[cç][aã]o\b", re.IGNORECASE), "Ministério da Educação"),
    (re.compile(r"\bminist[eé]rio\s+da\s+defesa\b", re.IGNORECASE), "Ministério da Defesa"),
    (
        re.compile(r"\bminist[eé]rio\s+da\s+agricultura(?:,\s*pecu[aá]ria\s+e\s+abastecimento)?\b", re.IGNORECASE),
        "Ministério da Agricultura, Pecuária e Abastecimento",
    ),
    (re.compile(r"\bminist[eé]rio\s+das\s+comunica[cç][oõ]es\b", re.IGNORECASE), "Ministério das Comunicações"),
    (re.compile(r"\bminist[eé]rio\s+de\s+minas\s+e\s+energia\b", re.IGNORECASE), "Ministério de Minas e Energia"),
    (re.compile(r"\bpresid[eê]ncia\s+da\s+rep[uú]blica\b", re.IGNORECASE), "Presidência da República"),
    (re.compile(r"\bpoder\s+judici[aá]rio\b", re.IGNORECASE), "Poder Judiciário"),
]


# ---------------------------------------------------------------------------
# R11: Portuguese legal synonym expansion (query-time)
# ---------------------------------------------------------------------------

_LEGAL_SYNONYMS: dict[str, list[str]] = {
    # Taxation & fiscal
    "tarifa": ["reajuste tarifário", "revisão tarifária"],
    "imposto": ["tributo", "tributação", "contribuição"],
    "imposto seletivo": ["tributação produtos nocivos", "imposto sobre consumo"],
    "tributo": ["imposto", "contribuição", "taxa"],
    "arcabouço fiscal": ["regra fiscal", "marco fiscal", "teto de gastos"],
    # Contracts & procurement
    "termo aditivo": ["aditamento contratual", "prorrogação contrato"],
    "licitação": ["pregão", "concorrência", "tomada de preços"],
    "pregão eletrônico": ["licitação eletrônica", "pregão"],
    "contratação direta": ["inexigibilidade", "dispensa de licitação"],
    # Social programs
    "bolsa família": ["programa bolsa família", "auxílio brasil", "transferência de renda"],
    "auxílio emergencial": ["benefício emergencial", "auxílio covid"],
    # Legislation
    "medida provisória": ["MP", "medida provisória conversão"],
    "decreto": ["decreto regulamentar", "decreto executivo"],
    "regulamentação": ["regulação", "normatização", "normatizar"],
    # Entities
    "LGPD": ["lei geral de proteção de dados", "lei 13709"],
    "ECA": ["estatuto da criança e do adolescente", "lei 8069"],
    "FUNDEB": ["fundo de manutenção educação básica"],
    # Administrative
    "nomeação": ["designação", "investidura"],
    "exoneração": ["dispensa", "vacância"],
    "cessão": ["requisição", "movimentação de pessoal"],
    # Policy domains
    "segurança alimentar": ["combate à fome", "programa alimentar", "soberania alimentar"],
    "meio ambiente": ["ambiental", "licenciamento ambiental", "proteção ambiental"],
    "energia": ["setor elétrico", "energia elétrica"],
}

_SYNONYM_LOOKUP: dict[str, list[str]] = {}
for _key, _syns in _LEGAL_SYNONYMS.items():
    _SYNONYM_LOOKUP[_key.lower()] = _syns
    for _syn in _syns:
        if _syn.lower() not in _SYNONYM_LOOKUP:
            _SYNONYM_LOOKUP[_syn.lower()] = [_key]


def _expand_synonyms(query: str) -> list[str]:
    """Return synonym expansions for a query (empty list if no matches)."""
    q_lower = query.lower().strip()
    expansions: list[str] = []
    if q_lower in _SYNONYM_LOOKUP:
        expansions.extend(_SYNONYM_LOOKUP[q_lower])
    else:
        words = q_lower.split()
        for i in range(len(words) - 1):
            bigram = f"{words[i]} {words[i + 1]}"
            if bigram in _SYNONYM_LOOKUP:
                expansions.extend(_SYNONYM_LOOKUP[bigram])
        for word in words:
            if word in _SYNONYM_LOOKUP and len(word) > 4:
                for syn in _SYNONYM_LOOKUP[word]:
                    if syn not in expansions:
                        expansions.append(syn)
    return expansions[:5]


# ---------------------------------------------------------------------------
# Smart query parsing — compensates for lack of semantic understanding
# ---------------------------------------------------------------------------

# Legal reference patterns: "Lei 13709", "Decreto nº 1.234", "IN 45/2020", "Lei 8.069/90"
_LEGAL_REF_PATTERN = re.compile(
    r"\b(lei(?:\s+complementar)?|decreto(?:\s*-?\s*lei)?|portaria|"
    r"resolu[cç][aã]o|instru[cç][aã]o\s+normativa|medida\s+provis[oó]ria|"
    r"emenda\s+constitucional|s[uú]mula|IN|MP|RDC|RE|ADI|ADPF)"
    r"\s*(?:n[°º.]?\s*)?(\d[\d.]*(?:/\d{2,4})?)\b",
    re.IGNORECASE,
)

# Article/paragraph references: "art. 5º", "§ 1º", "inciso III"
_ART_PARAGRAPH_PATTERN = re.compile(
    r"\b(art(?:igo)?\.?\s*\d+[°º]?(?:-[A-Z])?"
    r"|§\s*\d+[°º]?"
    r"|par[aá]grafo\s+[uú]nico"
    r"|inciso\s+[IVXLCDM]+"
    r"|al[ií]nea\s+[a-z])\b",
    re.IGNORECASE,
)

# Quoted phrase extraction
_QUOTED_PHRASE_PATTERN = re.compile(r'"([^"]+)"')


# ---------------------------------------------------------------------------
# Person name detection and normalization
# ---------------------------------------------------------------------------

# Common Brazilian suffixes (case-insensitive matching via _normalize_text)
_NAME_SUFFIXES = {"junior", "júnior", "jr", "filho", "filha", "neto", "neta", "sobrinho", "sobrinha", "segundo", "terceiro"}

# Particles that can appear between name parts (kept but optional in matching)
_NAME_PARTICLES = {"de", "da", "do", "dos", "das", "e"}

# Common first names (top ~60 Brazilian) for heuristic detection
_COMMON_FIRST_NAMES = {
    "fernando", "carlos", "jose", "joão", "joao", "antonio", "antônio", "francisco", "pedro",
    "paulo", "lucas", "marcos", "marcelo", "rafael", "rodrigo", "andre", "andré", "felipe",
    "gabriel", "daniel", "eduardo", "bruno", "gustavo", "ricardo", "roberto", "alexandre",
    "luiz", "luis", "henrique", "diego", "thiago", "tiago", "leandro", "fabio", "fábio",
    "sergio", "sérgio", "jorge", "renato", "claudio", "cláudio", "márcio", "marcio",
    "maria", "ana", "patricia", "patrícia", "fernanda", "juliana", "adriana", "luciana",
    "sandra", "marcia", "márcia", "cristina", "aline", "camila", "bruna", "carla",
    "vanessa", "leticia", "letícia", "priscila", "amanda", "larissa", "raquel", "simone",
    "denise", "claudia", "cláudia", "eliane", "rosana", "sonia", "sônia", "regina",
}

# Words that disqualify person name detection (legal/institutional terms)
_NON_NAME_WORDS = {
    "lei", "decreto", "portaria", "edital", "resolução", "resolucao", "despacho",
    "instrução", "instrucao", "normativa", "ministerio", "ministério", "secretaria",
    "tribunal", "conselho", "comissão", "comissao", "fundação", "fundacao", "instituto",
    "universidade", "empresa", "sociedade", "ltda", "eireli", "cnpj", "cpf",
    "contrato", "licitação", "licitacao", "pregão", "pregao", "aviso", "extrato",
    "reforma", "tributária", "tributaria", "fiscal", "saúde", "saude", "educação",
    "educacao", "defesa", "agricultura", "artigo", "parágrafo", "paragrafo",
}


def _normalize_text_simple(text: str) -> str:
    """Lowercase and strip accents for matching."""
    import unicodedata
    nfkd = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _is_likely_person_name(query: str) -> bool:
    """Conservative heuristic: does this query look like a person's name?

    Criteria (ALL must hold):
    - 2-6 words (after removing particles)
    - No legal/institutional disqualifiers
    - First word matches a common Brazilian first name, OR all words are capitalized
    - No digits, no special operators
    """
    q = query.strip()
    if not q or '"' in q:
        return False  # quoted phrases handled separately

    # No digits or special chars (legal refs like "Lei 13709")
    if re.search(r"\d", q):
        return False

    words = q.split()
    if len(words) < 2 or len(words) > 6:
        return False

    normalized_words = [_normalize_text_simple(w) for w in words]

    # Disqualify if any word is a legal/institutional term
    if any(w in _NON_NAME_WORDS for w in normalized_words):
        return False

    # Meaningful words (exclude particles)
    meaningful = [w for w in normalized_words if w not in _NAME_PARTICLES]
    if len(meaningful) < 2:
        return False

    # Check: first word is a common first name
    first_is_name = meaningful[0] in _COMMON_FIRST_NAMES

    # Check: all original words start with uppercase (Title Case pattern)
    # Allow particles to be lowercase
    all_capitalized = all(
        w[0].isupper() or _normalize_text_simple(w) in _NAME_PARTICLES
        for w in words if w
    )

    # Must have at least one signal
    if not first_is_name and not all_capitalized:
        return False

    return True


def _normalize_person_query(query: str) -> str:
    """Normalize person name for matching: standardize suffixes and remove particles.

    "Fernando Lima Gama Júnior" → "fernando lima gama junior"
    "Fernando de Lima Gama Jr" → "fernando lima gama junior"
    "Fernando L. Gama Jr." → "fernando l gama junior"
    """
    q = _normalize_text_simple(query)
    # Remove dots after initials (L. → L)
    q = re.sub(r"\.(?:\s|$)", " ", q)
    # Standardize suffixes
    q = re.sub(r"\b(jr|júnior)\b", "junior", q)
    q = re.sub(r"\b(sr)\b", "senior", q)
    # Remove particles for the canonical form
    words = q.split()
    canonical = [w for w in words if w not in _NAME_PARTICLES]
    return " ".join(canonical)


# Brazilian name orthographic substitutions — each tuple is (from, to).
# Only applied in the specified direction to avoid nonsense variants.
_ORTHO_SUBS: list[tuple[str, str]] = [
    # Y↔I (bidirectional, both common in Brazilian names)
    ("y", "i"),
    ("i", "y"),
    # PH→F and F→PH (Phelipe↔Felipe, Raphael↔Rafael)
    ("ph", "f"),
    ("f", "ph"),
    # TH→T (Thiago→Tiago, but not T→TH which creates noise)
    ("th", "t"),
    # W→V and V→W (Wladimir↔Vladimir, Waldemar↔Valdemar)
    ("w", "v"),
    ("v", "w"),
]


def _word_ortho_variants(word: str) -> list[str]:
    """Generate orthographic variants of a single name word.

    Returns list including the original. Conservative: only applies
    known Brazilian name spelling substitutions, one at a time.
    """
    variants = {word}
    for src, dst in _ORTHO_SUBS:
        if src in word:
            variants.add(word.replace(src, dst, 1))
    return list(variants)


def _name_spelling_variants(normalized_name: str) -> list[str]:
    """Generate full-name spelling variants from orthographic substitutions.

    "sylvio xavier junior" → ["sylvio xavier junior", "silvio xavier junior"]

    Only varies one word at a time to avoid combinatorial explosion.
    Returns the original + up to N variants (one per word that has alternatives).
    """
    words = normalized_name.split()
    results = {normalized_name}
    for i, word in enumerate(words):
        for variant in _word_ortho_variants(word):
            if variant != word:
                new_name = words[:i] + [variant] + words[i + 1:]
                results.add(" ".join(new_name))
    return list(results)


def _person_name_variants(query: str) -> list[str]:
    """Generate controlled name variants for progressive relaxation.

    Returns list from most specific to least specific:
    1. Full name (normalized) — with orthographic variants handled in query clause
    2. Full name without suffix (Junior, Filho, etc.)
    3. First + last name only
    Each level also generates orthographic variants internally.
    """
    canonical = _normalize_person_query(query)
    words = canonical.split()
    if len(words) < 2:
        return [canonical]

    variants = [canonical]

    # Without suffix
    if words[-1] in {_normalize_text_simple(s) for s in _NAME_SUFFIXES}:
        no_suffix = " ".join(words[:-1])
        if no_suffix != canonical:
            variants.append(no_suffix)

    # First + last name only (skip middle names)
    if len(words) >= 3:
        # Last meaningful word (not suffix)
        last_idx = -1
        if words[-1] in {_normalize_text_simple(s) for s in _NAME_SUFFIXES}:
            last_idx = -2
        if abs(last_idx) <= len(words):
            first_last = f"{words[0]} {words[last_idx]}"
            if first_last not in variants:
                variants.append(first_last)

    return variants


def _person_query_clause(query: str) -> dict[str, Any]:
    """Build a person-name-specific query clause.

    Strategy:
    - match_phrase in filter (hard gate) with slop=1 for near-exact
    - Orthographic variants (Y↔I, PH↔F, TH↔T, W↔V) searched as OR alternatives
    - slop=0 boost for exact matches
    - No synonym expansion, no fuzzy
    - Searches all text fields
    """
    normalized = _normalize_person_query(query)
    fields = ["identifica", "ementa", "body_plain"]
    spelling_variants = _name_spelling_variants(normalized)

    # Hard gate: must match ANY spelling variant as phrase with slop=1
    if len(spelling_variants) == 1:
        must_clause = {
            "multi_match": {
                "query": normalized,
                "type": "phrase",
                "fields": fields,
                "slop": 1,
            },
        }
    else:
        # OR across all spelling variants — any one matching is enough
        variant_clauses = []
        for variant in spelling_variants:
            variant_clauses.append({
                "multi_match": {
                    "query": variant,
                    "type": "phrase",
                    "fields": fields,
                    "slop": 1,
                },
            })
        must_clause = {
            "bool": {
                "should": variant_clauses,
                "minimum_should_match": 1,
            },
        }

    # Boost exact matches (slop=0) above near-exact (slop=1)
    should_clauses = [
        {"match_phrase": {"identifica": {"query": normalized, "slop": 0, "boost": 50}}},
        {"match_phrase": {"ementa": {"query": normalized, "slop": 0, "boost": 40}}},
        {"match_phrase": {"body_plain": {"query": normalized, "slop": 0, "boost": 20}}},
    ]

    # Also try the original (un-normalized) query for accent-sensitive exact hits
    original_clean = re.sub(r"\.(?:\s|$)", " ", query.strip().lower())
    original_words = [w for w in original_clean.split() if w not in _NAME_PARTICLES]
    original_form = " ".join(original_words)
    if original_form != normalized:
        should_clauses.append(
            {"match_phrase": {"identifica": {"query": original_form, "slop": 0, "boost": 60}}},
        )

    return {
        "bool": {
            "must": [must_clause],
            "should": should_clauses,
        },
    }


def _parse_query(raw: str) -> dict[str, Any]:
    """Parse a raw query into structured components for intelligent BM25 construction.

    Returns:
      phrases: list of exact phrases extracted from quotes
      legal_refs: list of {"type": "lei", "number": "13709"} dicts
      clean_text: remaining query text with quotes/refs removed
      original: the raw input
    """
    q = raw.replace("\u201c", '"').replace("\u201d", '"').replace("\u2018", "'").replace("\u2019", "'").strip()

    # Guard: cap query length to prevent abuse (preserves semantic integrity)
    if len(q) > 1000:
        q = q[:1000]

    # Extract quoted phrases
    phrases = _QUOTED_PHRASE_PATTERN.findall(q)
    remainder = _QUOTED_PHRASE_PATTERN.sub(" ", q)

    # Extract legal references
    legal_refs = []
    for match in _LEGAL_REF_PATTERN.finditer(remainder):
        ref_type = match.group(1).strip().lower()
        ref_number = match.group(2).strip()
        legal_refs.append({"type": ref_type, "number": ref_number})

    # Extract article/paragraph references for phrase boosting
    art_refs = _ART_PARAGRAPH_PATTERN.findall(remainder)
    # Don't remove refs from text — they're useful for BM25 too

    clean_text = re.sub(r"\s+", " ", remainder).strip()

    return {
        "phrases": phrases,
        "legal_refs": legal_refs,
        "art_refs": art_refs,
        "clean_text": clean_text,
        "original": raw,
    }


def _query_text(query: str) -> str:
    return query.replace("\u201c", '"').replace("\u201d", '"').replace("\u2018", "'").replace("\u2019", "'").strip()


def _infer_request_filters(
    query: str,
    *,
    section: str | None,
    art_type: str | None,
    issuing_organ: str | None,
) -> tuple[str, str | None, str | None, str | None]:
    q = _query_text(query)
    inferred_section = section
    inferred_art_type = art_type
    inferred_organ = issuing_organ

    if not inferred_section:
        match = _SECTION_PATTERN.search(q)
        if match:
            inferred_section = f"do{match.group(1).lower()}"
            q = _SECTION_PATTERN.sub(" ", q)

    if not inferred_art_type:
        for pattern, value in _ART_TYPE_PATTERNS:
            if pattern.search(q):
                inferred_art_type = value
                break

    if not inferred_organ:
        for pattern, value in _ORGAN_PATTERNS:
            if pattern.search(q):
                inferred_organ = value
                break

    q = re.sub(r"\s+", " ", q).strip()
    return q, inferred_section, inferred_art_type, inferred_organ


def _search_context_payload(
    *,
    original_query: str,
    interpreted_query: str,
    requested_section: str | None,
    requested_art_type: str | None,
    requested_issuing_organ: str | None,
    applied_section: str | None,
    applied_art_type: str | None,
    applied_issuing_organ: str | None,
) -> dict[str, Any]:
    inferred: dict[str, str] = {}
    if not requested_section and applied_section:
        inferred["section"] = applied_section
    if not requested_art_type and applied_art_type:
        inferred["art_type"] = applied_art_type
    if not requested_issuing_organ and applied_issuing_organ:
        inferred["issuing_organ"] = applied_issuing_organ
    return {
        "interpreted_query": interpreted_query,
        "query_normalized": interpreted_query != _query_text(original_query),
        "applied_filters": {
            "section": applied_section,
            "art_type": applied_art_type,
            "issuing_organ": applied_issuing_organ,
        },
        "inferred_filters": inferred,
    }


# ---------------------------------------------------------------------------
# Elasticsearch client
# ---------------------------------------------------------------------------

class ElasticClient:
    def __init__(self) -> None:
        self.url = os.getenv("ES_URL", "http://localhost:9200").rstrip("/")
        self.index = os.getenv("ES_INDEX", "gabi_documents")
        username = (os.getenv("ES_USERNAME") or "").strip() or None
        password = (os.getenv("ES_PASSWORD") or "").strip() or None
        verify_tls = _env_bool("ES_VERIFY_TLS", True)
        timeout_sec = int(os.getenv("ES_TIMEOUT_SEC", "20"))
        auth = (username, password or "") if username else None
        self._client = httpx.Client(timeout=timeout_sec, verify=verify_tls, auth=auth)

    def request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        resp = self._client.request(method=method, url=f"{self.url}{path}", json=payload)
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, dict):
            raise RuntimeError("Invalid Elasticsearch response")
        return data

    def msearch(self, searches: list[tuple[dict[str, Any], dict[str, Any]]]) -> list[dict[str, Any]]:
        """Execute multiple searches in a single roundtrip via _msearch API."""
        import json
        ndjson = "\n".join(json.dumps(line) for pair in searches for line in pair) + "\n"
        resp = self._client.request(
            method="POST",
            url=f"{self.url}/{self.index}/_msearch",
            content=ndjson,
            headers={"Content-Type": "application/x-ndjson"},
        )
        resp.raise_for_status()
        return resp.json().get("responses", [])

    def close(self) -> None:
        self._client.close()


ES = ElasticClient()


# ---------------------------------------------------------------------------
# Query construction — the core BM25 intelligence
# ---------------------------------------------------------------------------

def _build_filters(
    *,
    date_from: str | None,
    date_to: str | None,
    section: str | None,
    art_type: str | None,
    issuing_organ: str | None,
) -> list[dict[str, Any]]:
    filters: list[dict[str, Any]] = []
    if date_from or date_to:
        rng: dict[str, Any] = {}
        if date_from:
            rng["gte"] = date_from
        if date_to:
            rng["lte"] = date_to
        filters.append({"range": {"pub_date": rng}})
    if section:
        filters.append({"term": {"edition_section": section}})
    if art_type:
        filters.append({"match": {"art_type": art_type}})
    if issuing_organ:
        filters.append({"term": {"issuing_organ.keyword": issuing_organ}})
    return filters


def _query_clause(query: str, *, strict: bool = True) -> dict[str, Any]:
    """Build an intelligent BM25 query with multi-signal boosting.

    Architecture:
    - Quoted phrases ("...") become must requirements (match_phrase with slop=1)
      so only docs containing that exact phrase (or near-exact) are returned.
    - Unquoted text uses simple_query_string for flexible BM25 matching.
    - Legal references, synonyms, and proximity provide scoring signals.

    When strict=False, uses OR operator for recall fallback on unquoted text.
    """
    parsed = _parse_query(query)
    q = parsed["clean_text"]
    phrases = parsed["phrases"]

    # No query at all
    if (q == "*" or not q) and not phrases:
        return {"match_all": {}}

    default_op = "and" if strict else "or"
    must_clauses: list[dict[str, Any]] = []
    should_clauses: list[dict[str, Any]] = []

    # --- Quoted phrases: MUST match (with slop=1 for prepositions like "de", "da") ---
    # "Fernando Lima Gama Júnior" → only docs with that phrase (or "Fernando de Lima Gama Junior")
    # pt_folded analyzer handles accent folding (Júnior = Junior)
    for phrase in phrases:
        must_clauses.append({
            "multi_match": {
                "query": phrase,
                "type": "phrase",
                "fields": ["identifica", "ementa", "body_plain"],
                "slop": 1,
            },
        })
        # Boost exact (slop=0) matches above slop=1 matches
        should_clauses.extend([
            {"match_phrase": {"identifica": {"query": phrase, "boost": 50}}},
            {"match_phrase": {"ementa": {"query": phrase, "boost": 40}}},
        ])

    # --- Unquoted text: flexible BM25 ---
    if q and q != "*":
        must_clauses.append({
            "simple_query_string": {
                "query": q,
                "fields": [
                    "identifica^5",
                    "ementa^4",
                    "issuing_organ^2",
                    "art_type^2",
                    "art_category",
                    "body_plain",
                ],
                "default_operator": default_op,
                "fuzzy_max_expansions": 20,
            },
        })

        # Exact phrase boost for unquoted text (soft signal)
        should_clauses.extend([
            {"match_phrase": {"identifica": {"query": q, "boost": 20}}},
            {"match_phrase": {"ementa": {"query": q, "boost": 15}}},
            {"match_phrase": {"body_plain": {"query": q, "boost": 5}}},
        ])

        # Proximity boost for multi-word unquoted queries (3+ words)
        # Without this, "Fernando Lima Gama Junior" (unquoted) gives equal
        # score to docs with all 4 names scattered vs. together as one person.
        word_count = len(q.split())
        if word_count >= 3:
            should_clauses.extend([
                {"match_phrase": {"identifica": {"query": q, "slop": 2, "boost": 40}}},
                {"match_phrase": {"ementa": {"query": q, "slop": 2, "boost": 30}}},
                {"match_phrase": {"body_plain": {"query": q, "slop": 3, "boost": 15}}},
            ])

        # Legal reference pinning — "Lei 13709" boosts identifica exact match
        for ref in parsed["legal_refs"]:
            ref_text = f"{ref['type']} {ref['number']}"
            should_clauses.extend([
                {"match_phrase": {"identifica": {"query": ref_text, "boost": 100}}},
                {"match_phrase": {"ementa": {"query": ref_text, "boost": 60}}},
            ])

        # Article/paragraph reference boosting — "art. 5º" in body
        for art_ref in parsed.get("art_refs", []):
            should_clauses.append(
                {"match_phrase": {"body_plain": {"query": art_ref, "boost": 30}}},
            )

        # R11 synonym expansion
        if SYNONYM_EXPANSION:
            for syn in _expand_synonyms(q):
                should_clauses.append({
                    "simple_query_string": {
                        "query": syn,
                        "fields": ["identifica^2", "ementa^2", "body_plain"],
                        "default_operator": "and",
                        "boost": 1.5,
                    },
                })

    if not must_clauses:
        return {"match_all": {}}

    return {
        "bool": {
            "must": must_clauses,
            "should": should_clauses,
        },
    }


def _sort_clause(sort: str) -> list[dict[str, Any]]:
    if sort == "date_desc":
        return [{"pub_date": {"order": "desc"}}, {"_score": {"order": "desc"}}]
    if sort == "date_asc":
        return [{"pub_date": {"order": "asc"}}, {"_score": {"order": "desc"}}]
    return [{"_score": {"order": "desc"}}, {"pub_date": {"order": "desc"}}]


# ---------------------------------------------------------------------------
# Result formatting
# ---------------------------------------------------------------------------

_SOURCE_FIELDS = [
    "doc_id", "identifica", "ementa", "art_type", "art_category",
    "pub_date", "edition_section", "issuing_organ", "body_plain",
]

_HIGHLIGHT_SPEC: dict[str, Any] = {
    "pre_tags": [">>>"],
    "post_tags": ["<<<"],
    "max_analyzed_offset": 500000,
    "fields": {
        "identifica": {"number_of_fragments": 0},
        "ementa": {"number_of_fragments": 1, "fragment_size": 280},
        "body_plain": {"number_of_fragments": 2, "fragment_size": 200},
    },
}


def _format_hits(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert raw ES hits to rich result dicts with merged highlights."""
    results: list[dict[str, Any]] = []
    for hit in hits:
        src = hit.get("_source", {})
        hl = hit.get("highlight", {})

        # Build best snippet from highlights, preferring ementa > identifica > body
        snippet_parts: list[str] = []
        for k in ("ementa", "identifica", "body_plain"):
            frags = hl.get(k)
            if frags:
                snippet_parts.extend(frags)
                if len(snippet_parts) >= 2:
                    break
        snippet = " … ".join(snippet_parts) if snippet_parts else (src.get("ementa") or src.get("body_plain") or "")[:280]

        results.append({
            "doc_id": src.get("doc_id") or hit.get("_id"),
            "score": round(float(hit.get("_score") or 0.0), 4),
            "identifica": src.get("identifica"),
            "ementa": src.get("ementa"),
            "art_type": src.get("art_type"),
            "pub_date": src.get("pub_date"),
            "edition_section": src.get("edition_section"),
            "issuing_organ": src.get("issuing_organ"),
            "snippet": snippet,
        })
    return results


def _extract_agg_buckets(aggs: dict[str, Any], name: str) -> list[dict[str, Any]]:
    return [{"key": x.get("key"), "count": x.get("doc_count", 0)} for x in aggs.get(name, {}).get("buckets", [])]


# ---------------------------------------------------------------------------
# Lightweight re-ranker — multi-signal scoring without GPU
# ---------------------------------------------------------------------------
# Compensates for lack of cross-encoder / kNN by re-scoring BM25 candidates
# with 5 signals computed in Python on the already-fetched _source fields.
# Works on raw ES hits (before formatting) so it has access to body_plain.
#
# Signals:
#   1. BM25 baseline (normalized to 0-1)        — 40%
#   2. Term coverage (% of query terms found)    — 12%
#   3. Title match (overlap with identifica)     — 20%
#   4. Ementa match (overlap with ementa)        — 10%
#   5. Proximity (min span containing 2+ terms)  — 18%
# ---------------------------------------------------------------------------

def _normalize_text(text: str) -> str:
    """Lowercase and strip accents for matching (mirrors pt_folded analyzer)."""
    import unicodedata
    nfkd = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _tokenize_query(query: str) -> list[str]:
    """Split query into searchable terms, filtering stopwords and short tokens."""
    _PT_STOPWORDS = {
        "a", "o", "e", "de", "do", "da", "dos", "das", "em", "no", "na", "nos",
        "nas", "um", "uma", "uns", "umas", "por", "para", "com", "sem", "sob",
        "que", "se", "ao", "aos", "ou", "os", "as", "es", "lo", "la",
    }
    words = _normalize_text(query).split()
    return [w for w in words if len(w) > 1 and w not in _PT_STOPWORDS]


def _compute_coverage(terms: list[str], text: str) -> float:
    """What fraction of query terms appear in text (0.0 - 1.0)."""
    if not terms:
        return 0.0
    found = sum(1 for t in terms if t in text)
    return found / len(terms)


def _compute_proximity(terms: list[str], text: str) -> float:
    """Score how close query terms appear to each other in text.

    Finds the minimum character span containing at least 2 distinct query
    terms. Shorter span = higher score (terms are contextually related).

    Returns 0.0-1.0: 1.0 = adjacent, 0.0 = not found or > 600 chars apart.
    """
    if len(terms) < 2:
        return 1.0  # single-term queries get full proximity score

    # Find all positions of each term
    positions: list[tuple[int, int]] = []  # (char_position, term_index)
    for i, term in enumerate(terms):
        start = 0
        while True:
            idx = text.find(term, start)
            if idx == -1:
                break
            positions.append((idx, i))
            start = idx + len(term)

    distinct_found = len(set(ti for _, ti in positions))
    if distinct_found < 2:
        return 0.0

    positions.sort()

    # Sliding window: find minimum span with 2+ distinct terms
    min_span = len(text)
    for i in range(len(positions)):
        seen = {positions[i][1]}
        for j in range(i + 1, len(positions)):
            seen.add(positions[j][1])
            if len(seen) >= 2:
                span = positions[j][0] - positions[i][0]
                min_span = min(min_span, span)
                break

    # Normalize: 0 chars = 1.0, 600+ chars = 0.0
    return max(0.0, 1.0 - min_span / 600.0)


def _rerank_hits(query: str, hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Re-rank raw ES hits using multi-signal scoring.

    Takes raw ES hits (with _source and highlight), computes 5 scoring
    signals, and returns hits re-sorted by the combined score. Each hit
    gets annotated with score breakdown for transparency.
    """
    if not hits:
        return hits

    terms = _tokenize_query(query)
    if not terms:
        return hits

    # Normalize BM25 scores to [0, 1]
    raw_scores = [float(h.get("_score") or 0.0) for h in hits]
    max_s = max(raw_scores) if raw_scores else 1.0
    min_s = min(raw_scores) if raw_scores else 0.0
    score_range = max_s - min_s or 1.0

    scored: list[tuple[float, dict[str, Any]]] = []
    for hit, raw_score in zip(hits, raw_scores):
        src = hit.get("_source", {})

        title_norm = _normalize_text(src.get("identifica") or "")
        ementa_norm = _normalize_text(src.get("ementa") or "")
        body_norm = _normalize_text(src.get("body_plain") or "")
        all_text = f"{title_norm} {ementa_norm} {body_norm}"

        bm25_norm = (raw_score - min_s) / score_range
        coverage = _compute_coverage(terms, all_text)
        title_match = _compute_coverage(terms, title_norm)
        ementa_match = _compute_coverage(terms, ementa_norm)
        proximity = _compute_proximity(terms, body_norm[:5000])  # cap for perf

        combined = (
            _W_BM25 * bm25_norm
            + _W_COVERAGE * coverage
            + _W_TITLE * title_match
            + _W_EMENTA * ementa_match
            + _W_PROXIMITY * proximity
        )

        # Store breakdown on the hit for transparency
        hit["_rerank_score"] = round(combined, 6)
        hit["_rerank_signals"] = {
            "bm25": round(bm25_norm, 4),
            "coverage": round(coverage, 4),
            "title": round(title_match, 4),
            "ementa": round(ementa_match, 4),
            "proximity": round(proximity, 4),
        }
        scored.append((combined, hit))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [hit for _, hit in scored]


def _format_reranked_hits(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert re-ranked ES hits to result dicts, including rerank signals."""
    results: list[dict[str, Any]] = []
    for hit in hits:
        src = hit.get("_source", {})
        hl = hit.get("highlight", {})

        snippet_parts: list[str] = []
        for k in ("ementa", "identifica", "body_plain"):
            frags = hl.get(k)
            if frags:
                snippet_parts.extend(frags)
                if len(snippet_parts) >= 2:
                    break
        snippet = " … ".join(snippet_parts) if snippet_parts else (src.get("ementa") or src.get("body_plain") or "")[:280]

        entry: dict[str, Any] = {
            "doc_id": src.get("doc_id") or hit.get("_id"),
            "score": hit.get("_rerank_score", round(float(hit.get("_score") or 0.0), 4)),
            "score_bm25": round(float(hit.get("_score") or 0.0), 4),
            "identifica": src.get("identifica"),
            "ementa": src.get("ementa"),
            "art_type": src.get("art_type"),
            "pub_date": src.get("pub_date"),
            "edition_section": src.get("edition_section"),
            "issuing_organ": src.get("issuing_organ"),
            "snippet": snippet,
        }
        signals = hit.get("_rerank_signals")
        if signals:
            entry["rerank_signals"] = signals
        results.append(entry)
    return results


# ---------------------------------------------------------------------------
# TOOL 1: es_search — The primary search tool (two-stage, re-ranked)
# ---------------------------------------------------------------------------

def es_search(
    query: str,
    mode: str = "bm25",
    page: int = 1,
    page_size: int = 20,
    sort: str = "relevance",
    date_from: str | None = None,
    date_to: str | None = None,
    section: str | None = None,
    art_type: str | None = None,
    issuing_organ: str | None = None,
    boost_recent: bool = False,
    include_facets: bool = False,
    rerank: bool = True,
    search_type: str = "auto",
) -> dict[str, Any]:
    """Search DOU documents with intelligent BM25 full-text search + re-ranking.

    Features:
    - Smart query parsing: auto-detects quoted phrases ("reforma tributária"),
      legal references (Lei 13709, Decreto 1234), and structured filters
    - Two-stage search: strict AND first, automatic OR fallback if < 3 results
    - Multi-signal re-ranking: refines BM25 top-N using term coverage,
      title match, ementa match, and proximity scoring (no GPU needed)
    - Function scoring: optional recency decay for time-sensitive queries
    - Synonym expansion: Portuguese legal vocabulary (R11)
    - Filter inference: extracts section/type/organ from natural language

    Args:
      query: search query in Portuguese, or '*' for browse mode.
             Use quotes for exact phrases: "reforma tributária"
             Legal references auto-boost: Lei 13709, Decreto nº 1.234
      mode: ignored (kept for backward compat) — always uses BM25
      page: 1-based page number
      page_size: results per page (1-100)
      sort: relevance | date_desc | date_asc
      date_from: YYYY-MM-DD lower bound
      date_to: YYYY-MM-DD upper bound
      section: do1 | do2 | do3
      art_type: exact act type (e.g. decreto, portaria)
      issuing_organ: exact issuing organ name
      boost_recent: apply recency decay — recent docs score higher (gauss, scale=365d)
      include_facets: include section/type/organ aggregations in response
      rerank: re-rank results using multi-signal scoring (default: true, auto-disabled for date sorts and browse)
      search_type: auto | person | general.
                   'person' forces person-name search mode (phrase match, no OR fallback).
                   'auto' (default) detects person names heuristically.
                   'general' forces standard BM25 search.
    """
    page = max(1, min(page, 500))  # cap deep pagination (500 * 100 = 50K max offset)
    page_size = max(1, min(page_size, 100))
    if sort not in {"relevance", "date_desc", "date_asc"}:
        sort = "relevance"
    if search_type not in {"auto", "person", "general"}:
        search_type = "auto"

    requested_section = section
    requested_art_type = art_type
    requested_issuing_organ = issuing_organ
    interpreted_query, section, art_type, issuing_organ = _infer_request_filters(
        query, section=section, art_type=art_type, issuing_organ=issuing_organ,
    )

    filters = _build_filters(
        date_from=date_from, date_to=date_to,
        section=section, art_type=art_type, issuing_organ=issuing_organ,
    )

    is_text_query = interpreted_query.strip() not in ("*", "")

    # Resolve person mode
    is_person = False
    if is_text_query:
        if search_type == "person":
            is_person = True
        elif search_type == "auto":
            is_person = _is_likely_person_name(interpreted_query)

    # Re-ranking only makes sense for relevance-sorted text queries
    do_rerank = rerank and is_text_query and sort == "relevance"

    # When re-ranking, overfetch candidates from ES then paginate in Python
    if do_rerank:
        fetch_size = max(RERANK_POOL, page * page_size)
        es_from = 0
    else:
        fetch_size = page_size
        es_from = (page - 1) * page_size

    # --- Stage 1: Build query (person mode vs general) ---
    if is_person:
        query_clause = _person_query_clause(interpreted_query)
        search_strategy = "person"
    else:
        query_clause = _query_clause(interpreted_query, strict=True)
        search_strategy = "strict"

    base_query: dict[str, Any] = {
        "bool": {"must": [query_clause], "filter": filters},
    }

    if boost_recent and is_text_query:
        base_query = {
            "function_score": {
                "query": base_query,
                "functions": [{
                    "gauss": {
                        "pub_date": {
                            "origin": "now",
                            "scale": "365d",
                            "offset": "30d",
                            "decay": 0.5,
                        },
                    },
                }],
                "boost_mode": "multiply",
            },
        }

    payload: dict[str, Any] = {
        "from": es_from,
        "size": fetch_size,
        "track_total_hits": True,
        "query": base_query,
        "sort": _sort_clause(sort),
        "_source": _SOURCE_FIELDS,
        "highlight": _HIGHLIGHT_SPEC,
    }

    if include_facets:
        payload["aggs"] = {
            "sections": {"terms": {"field": "edition_section", "size": 10}},
            "types": {"terms": {"field": "art_type.keyword", "size": 10}},
            "organs": {"terms": {"field": "issuing_organ.keyword", "size": 10}},
        }

    data = ES.request("POST", f"/{ES.index}/_search", payload)
    total = int(data.get("hits", {}).get("total", {}).get("value", 0))
    hits = data.get("hits", {}).get("hits", [])

    # --- Stage 2: Fallback ---
    if is_person:
        # Person mode: progressive relaxation (no OR fallback)
        # Try name variants from most specific to least specific
        if total == 0 and page == 1:
            variants = _person_name_variants(interpreted_query)
            for variant in variants[1:]:  # skip first (already tried)
                # Generate orthographic variants for this relaxed form too
                spelling_vars = _name_spelling_variants(variant)
                if len(spelling_vars) == 1:
                    relaxed_clause: dict[str, Any] = {
                        "multi_match": {
                            "query": variant,
                            "type": "phrase",
                            "fields": ["identifica", "ementa", "body_plain"],
                            "slop": 1,
                        },
                    }
                else:
                    relaxed_clause = {
                        "bool": {
                            "should": [
                                {"multi_match": {"query": sv, "type": "phrase", "fields": ["identifica", "ementa", "body_plain"], "slop": 1}}
                                for sv in spelling_vars
                            ],
                            "minimum_should_match": 1,
                        },
                    }
                relaxed_query: dict[str, Any] = {
                    "bool": {"must": [relaxed_clause], "filter": filters},
                }
                if boost_recent:
                    relaxed_query = {
                        "function_score": {
                            "query": relaxed_query,
                            "functions": [{"gauss": {"pub_date": {"origin": "now", "scale": "365d", "offset": "30d", "decay": 0.5}}}],
                            "boost_mode": "multiply",
                        },
                    }
                payload["query"] = relaxed_query
                data = ES.request("POST", f"/{ES.index}/_search", payload)
                relaxed_total = int(data.get("hits", {}).get("total", {}).get("value", 0))
                if relaxed_total > 0:
                    total = relaxed_total
                    hits = data.get("hits", {}).get("hits", [])
                    search_strategy = f"person+relaxed({variant})"
                    break
    else:
        # General mode: OR fallback if strict returned too few results
        if total < MIN_RESULTS_BEFORE_FALLBACK and is_text_query and page == 1:
            fallback_query: dict[str, Any] = {
                "bool": {"must": [_query_clause(interpreted_query, strict=False)], "filter": filters},
            }
            if boost_recent:
                fallback_query = {
                    "function_score": {
                        "query": fallback_query,
                        "functions": [{"gauss": {"pub_date": {"origin": "now", "scale": "365d", "offset": "30d", "decay": 0.5}}}],
                        "boost_mode": "multiply",
                    },
                }
            payload["query"] = fallback_query
            data = ES.request("POST", f"/{ES.index}/_search", payload)
            fallback_total = int(data.get("hits", {}).get("total", {}).get("value", 0))
            if fallback_total > total:
                total = fallback_total
                hits = data.get("hits", {}).get("hits", [])
                search_strategy = "relaxed"

    # --- Stage 3: Re-rank and paginate ---
    if do_rerank and hits:
        hits = _rerank_hits(interpreted_query, hits)
        # Paginate the re-ranked results
        start = (page - 1) * page_size
        end = start + page_size
        page_hits = hits[start:end]
        results = _format_reranked_hits(page_hits)
        search_strategy += "+reranked"
    else:
        results = _format_hits(hits)

    response: dict[str, Any] = {
        "query": query,
        "mode": "bm25",
        "search_type": "person" if is_person else "general",
        "search_strategy": search_strategy,
        "page": page,
        "page_size": page_size,
        "total": total,
        "has_more": (page * page_size) < total,
        "sort": sort,
        **_search_context_payload(
            original_query=query,
            interpreted_query=interpreted_query,
            requested_section=requested_section,
            requested_art_type=requested_art_type,
            requested_issuing_organ=requested_issuing_organ,
            applied_section=section,
            applied_art_type=art_type,
            applied_issuing_organ=issuing_organ,
        ),
        "filters": {
            "date_from": date_from, "date_to": date_to,
            "section": section, "art_type": art_type, "issuing_organ": issuing_organ,
        },
        "results": results,
    }

    if include_facets:
        aggs = data.get("aggregations", {})
        response["facets"] = {
            "sections": _extract_agg_buckets(aggs, "sections"),
            "types": _extract_agg_buckets(aggs, "types"),
            "organs": _extract_agg_buckets(aggs, "organs"),
        }

    return response


# ---------------------------------------------------------------------------
# TOOL 2: es_suggest — Autocomplete
# ---------------------------------------------------------------------------

def es_suggest(prefix: str, limit: int = 10) -> dict[str, Any]:
    """Autocomplete suggestions from title, organ and type fields.

    Args:
      prefix: partial text to autocomplete
      limit: max suggestions (1-20)
    """
    p = prefix.strip()
    if not p:
        return {"prefix": prefix, "suggestions": []}
    limit = max(1, min(limit, 20))
    payload = {
        "size": max(limit * 4, 40),
        "_source": ["identifica", "issuing_organ", "art_type"],
        "query": {
            "bool": {
                "should": [
                    {"match_phrase_prefix": {"identifica": {"query": p}}},
                    {"match_phrase_prefix": {"issuing_organ": {"query": p}}},
                    {"match_phrase_prefix": {"art_type": {"query": p}}},
                ],
                "minimum_should_match": 1,
            }
        },
    }
    data = ES.request("POST", f"/{ES.index}/_search", payload)
    hits = data.get("hits", {}).get("hits", [])
    bucket: dict[tuple[str, str], int] = {}
    needle = p.lower()
    for hit in hits:
        src = hit.get("_source", {})
        candidates = [
            ("titulo", (src.get("identifica") or "").strip()),
            ("orgao", (src.get("issuing_organ") or "").strip()),
            ("tipo", (src.get("art_type") or "").strip()),
        ]
        for cat, term in candidates:
            if not term or needle not in term.lower():
                continue
            key = (cat, term)
            bucket[key] = bucket.get(key, 0) + 1

    ranked = sorted(bucket.items(), key=lambda x: x[1], reverse=True)[:limit]
    return {
        "prefix": prefix,
        "suggestions": [{"cat": cat, "term": term, "doc_freq": cnt} for (cat, term), cnt in ranked],
    }


# ---------------------------------------------------------------------------
# TOOL 3: es_facets — Aggregation analytics
# ---------------------------------------------------------------------------

def es_facets(
    query: str = "*",
    date_from: str | None = None,
    date_to: str | None = None,
    section: str | None = None,
    art_type: str | None = None,
    issuing_organ: str | None = None,
    size: int = 10,
) -> dict[str, Any]:
    """Facet aggregations for sections, types, organs, and date histogram.

    Args:
      query: search query to scope facets, '*' for all
      date_from: YYYY-MM-DD lower bound
      date_to: YYYY-MM-DD upper bound
      section: do1 | do2 | do3
      art_type: exact act type filter
      issuing_organ: exact issuing organ name filter
      size: number of buckets per facet (1-30)
    """
    size = max(1, min(size, 30))
    filters = _build_filters(
        date_from=date_from, date_to=date_to,
        section=section, art_type=art_type, issuing_organ=issuing_organ,
    )
    payload = {
        "size": 0,
        "track_total_hits": True,
        "query": {"bool": {"must": [_query_clause(query)], "filter": filters}},
        "aggs": {
            "sections": {"terms": {"field": "edition_section", "size": 10}},
            "types": {"terms": {"field": "art_type.keyword", "size": size}},
            "organs": {"terms": {"field": "issuing_organ.keyword", "size": size}},
            "by_month": {"date_histogram": {"field": "pub_date", "calendar_interval": "month"}},
        },
    }
    data = ES.request("POST", f"/{ES.index}/_search", payload)
    aggs = data.get("aggregations", {})
    total = int(data.get("hits", {}).get("total", {}).get("value", 0))
    return {
        "query": query,
        "total": total,
        "facets": {
            "sections": _extract_agg_buckets(aggs, "sections"),
            "types": _extract_agg_buckets(aggs, "types"),
            "organs": _extract_agg_buckets(aggs, "organs"),
            "by_month": _extract_agg_buckets(aggs, "by_month"),
        },
    }


# ---------------------------------------------------------------------------
# TOOL 4: es_document — Single document fetch
# ---------------------------------------------------------------------------

def es_document(doc_id: str) -> dict[str, Any]:
    """Fetch a single indexed document by its doc_id.

    Args:
      doc_id: the Elasticsearch document ID
    """
    try:
        data = ES.request("GET", f"/{ES.index}/_doc/{doc_id}")
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            return {"found": False, "doc_id": doc_id}
        raise
    if not data.get("found"):
        return {"found": False, "doc_id": doc_id}
    src = data.get("_source", {})
    return {"found": True, "doc_id": doc_id, "document": src}


# ---------------------------------------------------------------------------
# TOOL 5: es_health — Cluster diagnostics
# ---------------------------------------------------------------------------

def es_health() -> dict[str, Any]:
    """Cluster and index health summary with storage and performance stats."""
    health = ES.request("GET", "/_cluster/health")
    count = ES.request("GET", f"/{ES.index}/_count")
    stats: dict[str, Any] = {}
    try:
        idx_stats = ES.request("GET", f"/{ES.index}/_stats/store,docs,search")
        primaries = idx_stats.get("_all", {}).get("primaries", {})
        stats = {
            "store_size_bytes": primaries.get("store", {}).get("size_in_bytes", 0),
            "store_size_human": _human_bytes(primaries.get("store", {}).get("size_in_bytes", 0)),
            "search_query_total": primaries.get("search", {}).get("query_total", 0),
            "search_query_time_ms": primaries.get("search", {}).get("query_time_in_millis", 0),
        }
    except Exception:
        pass
    return {
        "search_backend": "bm25",
        "tools_available": 13,
        "cluster_name": health.get("cluster_name"),
        "cluster_status": health.get("status"),
        "number_of_nodes": health.get("number_of_nodes"),
        "active_shards": health.get("active_shards"),
        "index": ES.index,
        "index_count": int(count.get("count", 0)),
        **stats,
    }


def _human_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024:
            return f"{n:.1f} {unit}"
        n //= 1024
    return f"{n} PB"


# ---------------------------------------------------------------------------
# TOOL 6: es_more_like_this — Semantic similarity without vectors
# ---------------------------------------------------------------------------

def es_more_like_this(
    doc_id: str,
    max_results: int = 10,
    date_from: str | None = None,
    date_to: str | None = None,
    section: str | None = None,
) -> dict[str, Any]:
    """Find documents similar to a given document using term-based similarity.

    This is the primary tool for "semantic-like" discovery without vectors.
    Uses ES More Like This on title, summary, and body to find documents
    sharing significant terms — effectively a TF-IDF similarity search.

    Args:
      doc_id: the document ID to find similar documents for
      max_results: maximum number of results (1-50)
      date_from: YYYY-MM-DD lower bound
      date_to: YYYY-MM-DD upper bound
      section: do1 | do2 | do3
    """
    max_results = max(1, min(max_results, 50))
    filters = _build_filters(
        date_from=date_from, date_to=date_to,
        section=section, art_type=None, issuing_organ=None,
    )
    filters.append({"bool": {"must_not": [{"term": {"_id": doc_id}}]}})

    payload = {
        "size": max_results,
        "_source": _SOURCE_FIELDS,
        "highlight": _HIGHLIGHT_SPEC,
        "query": {
            "bool": {
                "must": [{
                    "more_like_this": {
                        "fields": ["identifica", "ementa", "body_plain"],
                        "like": [{"_index": ES.index, "_id": doc_id}],
                        "min_term_freq": 1,
                        "min_doc_freq": 2,
                        "max_query_terms": 25,
                        "minimum_should_match": "30%",
                    },
                }],
                "filter": filters,
            },
        },
    }
    data = ES.request("POST", f"/{ES.index}/_search", payload)
    hits = data.get("hits", {}).get("hits", [])
    total = int(data.get("hits", {}).get("total", {}).get("value", 0))
    return {
        "seed_doc_id": doc_id,
        "total": total,
        "results": _format_hits(hits),
    }


# ---------------------------------------------------------------------------
# TOOL 7: es_significant_terms — Theme & concept discovery
# ---------------------------------------------------------------------------

def es_significant_terms(
    query: str,
    field: str = "body_plain",
    date_from: str | None = None,
    date_to: str | None = None,
    section: str | None = None,
    art_type: str | None = None,
    issuing_organ: str | None = None,
    size: int = 20,
) -> dict[str, Any]:
    """Find statistically significant terms that distinguish matching documents.

    Returns terms that appear disproportionately often in the matching
    documents compared to the full index. This is the key tool for:
    - Discovering themes and related concepts (replaces vector clustering)
    - Finding distinguishing vocabulary for a topic
    - Understanding what makes a result set unique

    Args:
      query: search query (must not be '*' unless filters are provided)
      field: body_plain | identifica | ementa | art_type | issuing_organ | edition_section
      date_from: YYYY-MM-DD lower bound
      date_to: YYYY-MM-DD upper bound
      section: do1 | do2 | do3
      art_type: exact act type filter
      issuing_organ: exact issuing organ name filter
      size: number of terms (1-50)
    """
    size = max(1, min(size, 50))
    has_filters = any([date_from, date_to, section, art_type, issuing_organ])
    q = query.strip()

    if (q == "*" or not q) and not has_filters:
        return {"error": "Provide a non-wildcard query or at least one filter."}

    filters = _build_filters(
        date_from=date_from, date_to=date_to,
        section=section, art_type=art_type, issuing_organ=issuing_organ,
    )

    keyword_fields = {"edition_section", "art_type.keyword", "issuing_organ.keyword"}
    text_fields = {"body_plain", "identifica", "ementa", "art_type", "issuing_organ"}

    if field in keyword_fields or field.endswith(".keyword"):
        agg_field = field if field.endswith(".keyword") else f"{field}.keyword"
        inner_agg: dict[str, Any] = {"significant_terms": {"field": agg_field, "size": size}}
    elif field in text_fields:
        inner_agg = {"significant_text": {"field": field, "size": size, "filter_duplicate_text": True}}
    else:
        return {"error": f"Unsupported field: {field}. Use: {', '.join(sorted(text_fields | keyword_fields))}"}

    # Wrap in sampler to avoid scanning millions of docs for text aggregations
    payload = {
        "size": 0,
        "query": {"bool": {"must": [_query_clause(q)], "filter": filters}},
        "aggs": {"sampled": {"sampler": {"shard_size": 5000}, "aggs": {"sig": inner_agg}}},
    }
    data = ES.request("POST", f"/{ES.index}/_search", payload)
    buckets = data.get("aggregations", {}).get("sampled", {}).get("sig", {}).get("buckets", [])
    return {
        "query": query,
        "field": field,
        "terms": [
            {
                "term": b.get("key"),
                "doc_count": b.get("doc_count", 0),
                "score": round(float(b.get("score", 0.0)), 4),
                "bg_count": b.get("bg_count", 0),
            }
            for b in buckets
        ],
    }


# ---------------------------------------------------------------------------
# TOOL 8: es_timeline — Temporal distribution analysis
# ---------------------------------------------------------------------------

def es_timeline(
    query: str = "*",
    interval: str = "month",
    date_from: str | None = None,
    date_to: str | None = None,
    section: str | None = None,
    art_type: str | None = None,
    issuing_organ: str | None = None,
) -> dict[str, Any]:
    """Temporal distribution of publications matching a query.

    Shows how publication volume changes over time — essential for
    understanding legislative trends, policy activity spikes, and
    seasonal patterns. Use to answer "when was this topic most active?"

    Args:
      query: search query or '*' for all documents
      interval: year | quarter | month | week | day
      date_from: YYYY-MM-DD lower bound
      date_to: YYYY-MM-DD upper bound
      section: do1 | do2 | do3
      art_type: exact act type filter
      issuing_organ: exact issuing organ name filter
    """
    valid_intervals = {"year", "quarter", "month", "week", "day"}
    if interval not in valid_intervals:
        interval = "month"

    filters = _build_filters(
        date_from=date_from, date_to=date_to,
        section=section, art_type=art_type, issuing_organ=issuing_organ,
    )
    payload = {
        "size": 0,
        "track_total_hits": True,
        "query": {"bool": {"must": [_query_clause(query)], "filter": filters}},
        "aggs": {
            "timeline": {
                "date_histogram": {"field": "pub_date", "calendar_interval": interval, "min_doc_count": 1},
            },
            "date_range": {
                "stats": {"field": "pub_date"},
            },
        },
    }
    data = ES.request("POST", f"/{ES.index}/_search", payload)
    aggs = data.get("aggregations", {})
    total = int(data.get("hits", {}).get("total", {}).get("value", 0))
    buckets = aggs.get("timeline", {}).get("buckets", [])
    date_stats = aggs.get("date_range", {})

    # Find peak period
    peak = max(buckets, key=lambda b: b.get("doc_count", 0)) if buckets else None

    return {
        "query": query,
        "interval": interval,
        "total": total,
        "periods": len(buckets),
        "first_date": date_stats.get("min_as_string"),
        "last_date": date_stats.get("max_as_string"),
        "peak_period": {"date": peak.get("key_as_string"), "count": peak.get("doc_count")} if peak else None,
        "timeline": [
            {"date": b.get("key_as_string"), "count": b.get("doc_count", 0)}
            for b in buckets
        ],
    }


# ---------------------------------------------------------------------------
# TOOL 9: es_trending — Recent publication activity
# ---------------------------------------------------------------------------

def es_trending(
    days: int = 7,
    section: str | None = None,
    size: int = 10,
) -> dict[str, Any]:
    """Discover trending topics and active organs in recent publications.

    Analyzes the last N days of publications to surface:
    - Most active issuing organs
    - Most common act types
    - Significant terms (what's distinctive about recent publications)
    - Daily publication volume

    Args:
      days: lookback window (1-90, default 7)
      section: do1 | do2 | do3 to scope
      size: number of items per facet (1-30)
    """
    days = max(1, min(days, 90))
    size = max(1, min(size, 30))
    filters = _build_filters(
        date_from=f"now-{days}d/d", date_to=None,
        section=section, art_type=None, issuing_organ=None,
    )
    payload = {
        "size": 0,
        "track_total_hits": True,
        "query": {"bool": {"filter": filters}},
        "aggs": {
            "top_organs": {"terms": {"field": "issuing_organ.keyword", "size": size}},
            "top_types": {"terms": {"field": "art_type.keyword", "size": size}},
            "top_sections": {"terms": {"field": "edition_section", "size": 5}},
            "daily_volume": {"date_histogram": {"field": "pub_date", "calendar_interval": "day", "min_doc_count": 1}},
            "hot_terms_sampled": {"sampler": {"shard_size": 5000}, "aggs": {"hot_terms": {"significant_text": {"field": "identifica", "size": size, "filter_duplicate_text": True}}}},
        },
    }
    data = ES.request("POST", f"/{ES.index}/_search", payload)
    aggs = data.get("aggregations", {})
    total = int(data.get("hits", {}).get("total", {}).get("value", 0))
    return {
        "days": days,
        "total_publications": total,
        "avg_daily": round(total / max(days, 1), 1),
        "top_organs": _extract_agg_buckets(aggs, "top_organs"),
        "top_types": _extract_agg_buckets(aggs, "top_types"),
        "sections": _extract_agg_buckets(aggs, "top_sections"),
        "daily_volume": [
            {"date": b.get("key_as_string"), "count": b.get("doc_count", 0)}
            for b in aggs.get("daily_volume", {}).get("buckets", [])
        ],
        "trending_terms": [
            {"term": b.get("key"), "doc_count": b.get("doc_count", 0), "score": round(float(b.get("score", 0.0)), 4)}
            for b in aggs.get("hot_terms_sampled", {}).get("hot_terms", {}).get("buckets", [])
        ],
    }


# ---------------------------------------------------------------------------
# TOOL 10: es_cross_reference — Legal citation network
# ---------------------------------------------------------------------------

def es_cross_reference(
    reference: str,
    max_results: int = 20,
    date_from: str | None = None,
    date_to: str | None = None,
    section: str | None = None,
) -> dict[str, Any]:
    """Find all documents that cite or reference a specific law, decree, or act.

    Searches across body text for mentions of a legal reference
    (e.g., "Lei 13709", "Decreto 9.203"). This builds a citation
    network without needing graph databases — essential for understanding
    regulatory impact and legislative reach.

    Args:
      reference: the legal reference to search for (e.g., "Lei 13709", "Decreto 9.203/2017")
      max_results: number of citing documents (1-100)
      date_from: YYYY-MM-DD lower bound
      date_to: YYYY-MM-DD upper bound
      section: do1 | do2 | do3
    """
    max_results = max(1, min(max_results, 100))
    ref = reference.strip()
    if not ref:
        return {"error": "Provide a legal reference to search for."}

    filters = _build_filters(
        date_from=date_from, date_to=date_to,
        section=section, art_type=None, issuing_organ=None,
    )

    payload = {
        "from": 0,
        "size": max_results,
        "track_total_hits": True,
        "query": {
            "bool": {
                "must": [{"match_phrase": {"body_plain": {"query": ref}}}],
                "filter": filters,
            },
        },
        "sort": [{"pub_date": {"order": "desc"}}, {"_score": {"order": "desc"}}],
        "_source": _SOURCE_FIELDS,
        "highlight": {
            "pre_tags": [">>>"], "post_tags": ["<<<"],
            "fields": {"body_plain": {"number_of_fragments": 1, "fragment_size": 300}},
        },
        "aggs": {
            "citing_organs": {"terms": {"field": "issuing_organ.keyword", "size": 10}},
            "citing_types": {"terms": {"field": "art_type.keyword", "size": 10}},
            "citations_over_time": {"date_histogram": {"field": "pub_date", "calendar_interval": "year", "min_doc_count": 1}},
        },
    }
    data = ES.request("POST", f"/{ES.index}/_search", payload)
    hits = data.get("hits", {}).get("hits", [])
    total = int(data.get("hits", {}).get("total", {}).get("value", 0))
    aggs = data.get("aggregations", {})

    return {
        "reference": reference,
        "total_citations": total,
        "citing_organs": _extract_agg_buckets(aggs, "citing_organs"),
        "citing_types": _extract_agg_buckets(aggs, "citing_types"),
        "citations_over_time": [
            {"year": b.get("key_as_string"), "count": b.get("doc_count", 0)}
            for b in aggs.get("citations_over_time", {}).get("buckets", [])
        ],
        "results": _format_hits(hits),
    }


# ---------------------------------------------------------------------------
# TOOL 11: es_organ_profile — Publishing profile analysis
# ---------------------------------------------------------------------------

def es_organ_profile(
    organ: str,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict[str, Any]:
    """Comprehensive publishing profile for a government organ.

    Shows what an organ publishes, how much, what types of acts,
    trending topics, and publication patterns. Essential for understanding
    institutional activity and regulatory output.

    Args:
      organ: exact organ name (use es_suggest or es_facets to find valid names)
      date_from: YYYY-MM-DD lower bound
      date_to: YYYY-MM-DD upper bound
    """
    organ = organ.strip()
    if not organ:
        return {"error": "Provide an organ name."}

    filters = _build_filters(
        date_from=date_from, date_to=date_to,
        section=None, art_type=None, issuing_organ=organ,
    )

    payload = {
        "size": 0,
        "track_total_hits": True,
        "query": {"bool": {"filter": filters}},
        "aggs": {
            "act_types": {"terms": {"field": "art_type.keyword", "size": 20}},
            "sections": {"terms": {"field": "edition_section", "size": 5}},
            "monthly_volume": {"date_histogram": {"field": "pub_date", "calendar_interval": "month", "min_doc_count": 1}},
            "yearly_volume": {"date_histogram": {"field": "pub_date", "calendar_interval": "year", "min_doc_count": 1}},
            "key_topics_sampled": {"sampler": {"shard_size": 5000}, "aggs": {"key_topics": {"significant_text": {"field": "identifica", "size": 15, "filter_duplicate_text": True}}}},
            "date_range": {"stats": {"field": "pub_date"}},
        },
    }
    data = ES.request("POST", f"/{ES.index}/_search", payload)
    aggs = data.get("aggregations", {})
    total = int(data.get("hits", {}).get("total", {}).get("value", 0))
    date_stats = aggs.get("date_range", {})

    yearly = aggs.get("yearly_volume", {}).get("buckets", [])
    peak_year = max(yearly, key=lambda b: b.get("doc_count", 0)) if yearly else None

    return {
        "organ": organ,
        "total_publications": total,
        "first_publication": date_stats.get("min_as_string"),
        "latest_publication": date_stats.get("max_as_string"),
        "peak_year": {"year": peak_year.get("key_as_string"), "count": peak_year.get("doc_count")} if peak_year else None,
        "act_types": _extract_agg_buckets(aggs, "act_types"),
        "sections": _extract_agg_buckets(aggs, "sections"),
        "key_topics": [
            {"term": b.get("key"), "doc_count": b.get("doc_count", 0), "score": round(float(b.get("score", 0.0)), 4)}
            for b in aggs.get("key_topics_sampled", {}).get("key_topics", {}).get("buckets", [])
        ],
        "yearly_volume": [
            {"year": b.get("key_as_string"), "count": b.get("doc_count", 0)}
            for b in yearly
        ],
    }


# ---------------------------------------------------------------------------
# TOOL 12: es_compare_periods — Temporal comparative analysis
# ---------------------------------------------------------------------------

def es_compare_periods(
    query: str = "*",
    period_a_from: str = "",
    period_a_to: str = "",
    period_b_from: str = "",
    period_b_to: str = "",
    section: str | None = None,
) -> dict[str, Any]:
    """Compare search results between two time periods.

    Analyzes differences in volume, act types, organs, and significant
    terms between period A and period B. Essential for detecting policy
    shifts, regulatory changes, and institutional reorganizations.

    Args:
      query: search query or '*' for all
      period_a_from: YYYY-MM-DD start of period A
      period_a_to: YYYY-MM-DD end of period A
      period_b_from: YYYY-MM-DD start of period B
      period_b_to: YYYY-MM-DD end of period B
      section: do1 | do2 | do3
    """
    if not all([period_a_from, period_a_to, period_b_from, period_b_to]):
        return {"error": "All four period dates are required (period_a_from/to, period_b_from/to)."}

    def _period_payload(d_from: str, d_to: str) -> dict[str, Any]:
        filters = _build_filters(
            date_from=d_from, date_to=d_to,
            section=section, art_type=None, issuing_organ=None,
        )
        return {
            "size": 0,
            "track_total_hits": True,
            "query": {"bool": {"must": [_query_clause(query)], "filter": filters}},
            "aggs": {
                "types": {"terms": {"field": "art_type.keyword", "size": 15}},
                "organs": {"terms": {"field": "issuing_organ.keyword", "size": 15}},
                "sig_sampled": {"sampler": {"shard_size": 5000}, "aggs": {"sig_terms": {"significant_text": {"field": "identifica", "size": 10, "filter_duplicate_text": True}}}},
            },
        }

    responses = ES.msearch([
        ({}, _period_payload(period_a_from, period_a_to)),
        ({}, _period_payload(period_b_from, period_b_to)),
    ])

    def _extract_period(resp: dict[str, Any], label: str, d_from: str, d_to: str) -> dict[str, Any]:
        aggs = resp.get("aggregations", {})
        total = int(resp.get("hits", {}).get("total", {}).get("value", 0))
        return {
            "label": label,
            "date_from": d_from,
            "date_to": d_to,
            "total": total,
            "types": _extract_agg_buckets(aggs, "types"),
            "organs": _extract_agg_buckets(aggs, "organs"),
            "distinctive_terms": [
                {"term": b.get("key"), "doc_count": b.get("doc_count", 0), "score": round(float(b.get("score", 0.0)), 4)}
                for b in aggs.get("sig_sampled", {}).get("sig_terms", {}).get("buckets", [])
            ],
        }

    period_a_data = _extract_period(responses[0] if responses else {}, "period_a", period_a_from, period_a_to)
    period_b_data = _extract_period(responses[1] if len(responses) > 1 else {}, "period_b", period_b_from, period_b_to)

    # Compute delta
    total_a = period_a_data["total"]
    total_b = period_b_data["total"]
    change_pct = round((total_b - total_a) / max(total_a, 1) * 100, 1)

    return {
        "query": query,
        "period_a": period_a_data,
        "period_b": period_b_data,
        "volume_change_pct": change_pct,
        "volume_direction": "increase" if change_pct > 0 else "decrease" if change_pct < 0 else "stable",
    }


# ---------------------------------------------------------------------------
# TOOL 13: es_explain — Search quality debugging
# ---------------------------------------------------------------------------

def es_explain(
    query: str,
    doc_id: str,
) -> dict[str, Any]:
    """Explain why a document scored the way it did for a given query.

    Returns the ES explain output showing BM25 scoring breakdown —
    useful for debugging search quality and understanding ranking.

    Args:
      query: the search query
      doc_id: the document ID to explain
    """
    q = _query_text(query)
    interpreted_query, section, art_type, issuing_organ = _infer_request_filters(
        q, section=None, art_type=None, issuing_organ=None,
    )
    payload = {"query": _query_clause(interpreted_query)}

    data = ES.request("POST", f"/{ES.index}/_explain/{doc_id}", payload)
    explanation = data.get("explanation", {})

    def _simplify_explanation(exp: dict[str, Any], depth: int = 0) -> dict[str, Any]:
        result: dict[str, Any] = {
            "score": round(float(exp.get("value", 0.0)), 4),
            "description": exp.get("description", ""),
        }
        details = exp.get("details", [])
        if details and depth < 3:
            result["details"] = [_simplify_explanation(d, depth + 1) for d in details[:8]]
        return result

    return {
        "query": query,
        "doc_id": doc_id,
        "matched": data.get("matched", False),
        "score": round(float(explanation.get("value", 0.0)), 4),
        "explanation": _simplify_explanation(explanation),
    }


# ---------------------------------------------------------------------------
# MCP registration
# ---------------------------------------------------------------------------

if FastMCP is not None:
    mcp = FastMCP(
        "GABI Elasticsearch MCP",
        instructions=(
            "Professional BM25 search server for Brazil's Diário Oficial da União (DOU). "
            "13 tools over ~16M legal documents (2002-2026). Capabilities:\n"
            "- SEARCH: es_search (smart BM25 with two-stage fallback, phrase detection, "
            "legal ref boosting, synonym expansion, recency decay)\n"
            "- DISCOVER: es_more_like_this (find similar docs), es_significant_terms "
            "(theme discovery), es_cross_reference (citation network)\n"
            "- ANALYZE: es_timeline (temporal trends), es_trending (recent activity), "
            "es_organ_profile (institutional analysis), es_compare_periods (before/after)\n"
            "- UTILITY: es_suggest (autocomplete), es_facets (aggregations), "
            "es_document (fetch), es_health (status), es_explain (debug ranking)\n\n"
            "Tips: Use Portuguese terms. Use quotes for exact phrases. "
            "Legal references (Lei 13709) auto-boost. Combine tools for deep analysis."
        ),
    )
    mcp.tool()(es_search)
    mcp.tool()(es_suggest)
    mcp.tool()(es_facets)
    mcp.tool()(es_document)
    mcp.tool()(es_health)
    mcp.tool()(es_more_like_this)
    mcp.tool()(es_significant_terms)
    mcp.tool()(es_timeline)
    mcp.tool()(es_trending)
    mcp.tool()(es_cross_reference)
    mcp.tool()(es_organ_profile)
    mcp.tool()(es_compare_periods)
    mcp.tool()(es_explain)
else:
    mcp = None


def main() -> int:
    import argparse

    p = argparse.ArgumentParser(description="GABI Elasticsearch MCP Server")
    p.add_argument("--transport", choices=["stdio", "sse"], default="stdio")
    p.add_argument("--port", type=int, default=8766)
    args = p.parse_args()

    if mcp is None:
        raise SystemExit("mcp package is not installed.")

    if args.transport == "sse":
        mcp.settings.port = args.port
        mcp.run(transport="sse")
    else:
        mcp.run(transport="stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
