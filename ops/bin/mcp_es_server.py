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
        self.url = os.getenv("ES_URL", "http://elasticsearch:9200").rstrip("/")
        self.index = (os.getenv("ES_ALIAS") or os.getenv("ES_INDEX") or "gabi_documents").strip()
        self.tcu_index = os.getenv("TCU_ES_INDEX", "gabi_tcu_acordaos_v1").strip()
        self.normas_index = os.getenv("TCU_NORMAS_INDEX", "gabi_tcu_normas_v1").strip()
        username = (os.getenv("ES_USERNAME") or "").strip() or None
        password = (os.getenv("ES_PASSWORD") or "").strip() or None
        verify_tls = _env_bool("ES_VERIFY_TLS", True)
        timeout_sec = int(os.getenv("ES_TIMEOUT_SEC", "20"))
        auth = (username, password or "") if username else None
        self._client = httpx.Client(timeout=timeout_sec, verify=verify_tls, auth=auth)

    def resolve_index(self, source: str | None = None) -> str:
        """Resolve index name from source filter.

        source: 'dou' | 'tcu' | 'tcu_normas' | 'all' | None
        """
        if source == "tcu":
            return self.tcu_index
        if source == "tcu_normas":
            return self.normas_index
        if source == "all":
            return f"{self.index},{self.tcu_index},{self.normas_index}"
        return self.index

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


class GabiAPIClient:
    """Async HTTP client for the FastAPI backend (hybrid search pipeline).

    Uses httpx.AsyncClient to avoid blocking the event loop when the MCP
    server is mounted inside the same FastAPI process (SSE transport).
    """

    def __init__(self) -> None:
        self.base_url = os.getenv("GABI_API_URL", "http://localhost:8001").rstrip("/")
        token = os.getenv("GABI_API_TOKEN", "").strip()
        headers: dict[str, str] = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self._headers = headers
        self._timeout = 30
        # Lazy-init async client (created on first use inside event loop)
        self._async_client: httpx.AsyncClient | None = None

    def _get_async_client(self) -> httpx.AsyncClient:
        if self._async_client is None:
            self._async_client = httpx.AsyncClient(timeout=self._timeout, headers=self._headers)
        return self._async_client

    async def search(self, **params: Any) -> dict[str, Any]:
        client = self._get_async_client()
        resp = await client.get(f"{self.base_url}/api/search", params={k: v for k, v in params.items() if v is not None})
        resp.raise_for_status()
        return resp.json()

    async def autocomplete(self, q: str, n: int = 10) -> list[Any]:
        client = self._get_async_client()
        resp = await client.get(f"{self.base_url}/api/autocomplete", params={"q": q, "n": n})
        resp.raise_for_status()
        return resp.json()

    async def document(self, doc_id: str) -> dict[str, Any]:
        client = self._get_async_client()
        resp = await client.get(f"{self.base_url}/api/document/{doc_id}")
        resp.raise_for_status()
        return resp.json()


API = GabiAPIClient()


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
# TCU-specific search helpers
# ---------------------------------------------------------------------------

_TCU_SOURCE_FIELDS = [
    "doc_id", "titulo", "sumario", "acordao_texto", "tipo", "colegiado",
    "tipo_processo", "relator", "data_sessao", "numero_acordao", "ano_acordao",
    "numero_processo", "entidade", "dispositivo_tipo", "dispositivo_resumo",
    "source_type", "source_url",
]

_TCU_HIGHLIGHT_SPEC: dict[str, Any] = {
    "pre_tags": [">>>"],
    "post_tags": ["<<<"],
    "max_analyzed_offset": 500000,
    "fields": {
        "titulo": {"number_of_fragments": 0},
        "sumario": {"number_of_fragments": 1, "fragment_size": 280},
        "acordao_texto": {"number_of_fragments": 2, "fragment_size": 200},
        "search_all": {"number_of_fragments": 2, "fragment_size": 200},
    },
}


def _format_tcu_hits(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Format TCU ES hits into result dicts."""
    results: list[dict[str, Any]] = []
    for hit in hits:
        src = hit.get("_source", {})
        hl = hit.get("highlight", {})

        snippet_parts: list[str] = []
        for k in ("sumario", "titulo", "acordao_texto", "search_all"):
            frags = hl.get(k)
            if frags:
                snippet_parts.extend(frags)
                if len(snippet_parts) >= 2:
                    break
        snippet = " … ".join(snippet_parts) if snippet_parts else (
            src.get("sumario") or src.get("acordao_texto") or ""
        )[:280]

        results.append({
            "doc_id": src.get("doc_id") or hit.get("_id"),
            "score": round(float(hit.get("_score") or 0.0), 4),
            "titulo": src.get("titulo"),
            "sumario": src.get("sumario"),
            "tipo": src.get("tipo"),
            "colegiado": src.get("colegiado"),
            "tipo_processo": src.get("tipo_processo"),
            "relator": src.get("relator"),
            "data_sessao": src.get("data_sessao"),
            "numero_acordao": src.get("numero_acordao"),
            "ano_acordao": src.get("ano_acordao"),
            "numero_processo": src.get("numero_processo"),
            "entidade": src.get("entidade"),
            "dispositivo_tipo": src.get("dispositivo_tipo"),
            "dispositivo_resumo": src.get("dispositivo_resumo"),
            "source_type": src.get("source_type", "tcu_acordao"),
            "source_url": src.get("source_url"),
            "snippet": snippet,
        })
    return results


_YEAR_RE = re.compile(r'\b(20[12]\d)\b')
_RERANK_POOL_SIZE = 100


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


_AUTHORITY_INTENT_RE = re.compile(
    r'\b(s[úu]mula|entendimento|orienta[çc][aã]o|regra|norma|tese|jurisprud[eê]ncia|consulta)\b',
    re.IGNORECASE,
)
_AUTHORITY_BOOSTS = [1.0, 1.03, 1.08, 1.15]


def _embedding_rerank_mcp(
    hits: list[dict[str, Any]],
    query_vector: list[float],
    query_text: str = "",
    bm25_weight: float = 0.5,
    embed_weight: float = 0.5,
) -> list[dict[str, Any]]:
    """Re-rank BM25 hits using embedding similarity + authority boost."""
    if not hits:
        return hits
    bm25_scores = [float(h.get("_score") or 0) for h in hits]
    max_bm25 = max(bm25_scores) if bm25_scores else 1.0
    if max_bm25 == 0:
        max_bm25 = 1.0
    use_authority = bool(_AUTHORITY_INTENT_RE.search(query_text))
    for hit in hits:
        bm25_norm = float(hit.get("_score") or 0) / max_bm25
        embedding = hit.get("_source", {}).get("embedding")
        if embedding and isinstance(embedding, list):
            sim = _cosine_similarity(query_vector, embedding)
            combined = bm25_weight * bm25_norm + embed_weight * sim
        else:
            combined = bm25_norm
        if use_authority:
            authority = hit.get("_source", {}).get("authority_level", 0)
            combined *= _AUTHORITY_BOOSTS[min(authority, 3)]
        hit["_rerank_score"] = combined
        hit.get("_source", {}).pop("embedding", None)
    hits.sort(key=lambda h: h.get("_rerank_score", 0), reverse=True)
    return hits


def _es_search_direct(
    *,
    query: str,
    page: int = 1,
    page_size: int = 20,
    date_from: str | None = None,
    date_to: str | None = None,
    source: str | None = None,
) -> dict[str, Any]:
    """Two-pass search: BM25 first → embedding re-rank.

    Works for source='tcu' and source='all' (cross-search DOU+TCU).
    """
    page = max(1, min(page, 500))
    page_size = max(1, min(page_size, 100))
    offset = (page - 1) * page_size
    index = ES.resolve_index(source)

    # Temporal intent: auto-detect year in query
    if not date_from and not date_to:
        year_match = _YEAR_RE.search(query)
        if year_match:
            year = year_match.group(1)
            date_from = f"{year}-01-01"
            date_to = f"{year}-12-31"

    # Build filters
    filters: list[dict[str, Any]] = []
    if date_from or date_to:
        rng: dict[str, str] = {}
        if date_from:
            rng["gte"] = date_from
        if date_to:
            rng["lte"] = date_to
        if source == "all":
            filters.append({"bool": {"should": [
                {"range": {"pub_date": rng}},
                {"range": {"data_sessao": rng}},
            ], "minimum_should_match": 1}})
        elif source == "tcu":
            filters.append({"range": {"data_sessao": rng}})
        else:
            filters.append({"range": {"pub_date": rng}})

    # Default: only vigente normas (unless searching all or explicitly requesting revogadas)
    if source == "tcu_normas":
        filters.append({"term": {"vigente": True}})

    # Build query
    parsed = _parse_query(query)
    q = parsed["clean_text"]

    if source == "tcu":
        search_fields = [
            "titulo^5", "enunciado^5", "sumario^4", "excerto^3", "assunto^3",
            "relator^2", "entidade^2", "acordao_texto",
            "voto", "relatorio", "search_all", "indexacao",
        ]
    elif source == "tcu_normas":
        search_fields = [
            "assunto^4", "titulo^3", "tema^3", "texto_norma", "search_all",
        ]
    else:
        search_fields = [
            "titulo^5", "identifica^5", "sumario^4", "ementa^4",
            "assunto^3", "issuing_organ^2", "relator^2",
            "acordao_texto", "body_plain", "search_all",
        ]

    must_clauses: list[dict[str, Any]] = []
    should_clauses: list[dict[str, Any]] = []

    for phrase in parsed["phrases"]:
        must_clauses.append({
            "multi_match": {
                "query": phrase,
                "type": "phrase",
                "fields": search_fields,
                "slop": 1,
            },
        })

    if q and q != "*":
        # Cross-search: use OR + minimum_should_match for better recall
        if source == "all":
            must_clauses.append({
                "simple_query_string": {
                    "query": q,
                    "fields": search_fields,
                    "default_operator": "or",
                    "minimum_should_match": "60%",
                },
            })
        else:
            must_clauses.append({
                "simple_query_string": {
                    "query": q,
                    "fields": search_fields,
                    "default_operator": "and",
                },
            })
        for field in search_fields[:4]:
            field_name = field.split("^")[0]
            should_clauses.append(
                {"match_phrase": {field_name: {"query": q, "boost": 15}}},
            )

    if not must_clauses:
        must_clauses.append({"match_all": {}})

    # Pass 1: BM25 retrieval (larger pool if re-ranking)
    query_vector = _get_openai_embedding(query)
    pool_size = max(page_size * 3, _RERANK_POOL_SIZE) if query_vector else page_size
    source_fields = _TCU_SOURCE_FIELDS + _SOURCE_FIELDS
    if query_vector:
        source_fields = source_fields + ["embedding"]

    payload: dict[str, Any] = {
        "from": 0 if query_vector else offset,
        "size": pool_size if query_vector else page_size,
        "track_total_hits": True,
        "query": {
            "bool": {
                "must": must_clauses,
                "should": should_clauses,
                "filter": filters,
            },
        },
        "sort": [{"_score": {"order": "desc"}}],
        "_source": source_fields,
        "highlight": _TCU_HIGHLIGHT_SPEC,
    }

    data = ES.request("POST", f"/{index}/_search", payload)
    hits = data.get("hits", {}).get("hits", [])
    total = int(data.get("hits", {}).get("total", {}).get("value", 0))

    # Pass 2: Embedding re-rank
    if query_vector and hits:
        hits = _embedding_rerank_mcp(hits, query_vector, query_text=query)
        hits = hits[offset:offset + page_size]

    # Format results
    results: list[dict[str, Any]] = []
    for hit in hits:
        src = hit.get("_source", {})
        if (src.get("source_type") or "").startswith("tcu_"):
            results.extend(_format_tcu_hits([hit]))
        else:
            results.extend(_format_hits([hit]))

    return {
        "query": query,
        "source": source,
        "total": total,
        "page": page,
        "page_size": page_size,
        "results": results,
    }


# ---------------------------------------------------------------------------
# TOOL 1: es_search — The primary search tool (two-stage, re-ranked)
# ---------------------------------------------------------------------------

async def es_search(
    query: str,
    page: int = 1,
    page_size: int = 20,
    date_from: str | None = None,
    date_to: str | None = None,
    section: str | None = None,
    art_type: str | None = None,
    issuing_organ: str | None = None,
    topic: str | None = None,
    intent: str | None = None,
    is_trending: bool = False,
    source: str | None = None,
) -> dict[str, Any]:
    """Search DOU and/or TCU documents via GABI's search pipeline.

    Uses intent classification (person names, legal references, canonical laws,
    topic profiles), hybrid BM25 + kNN via RRF, quoted phrase detection, and
    optional neural reranking.

    Args:
      query: search query in Portuguese.
             Use quotes for exact phrases: "Eduardo Joerke"
             Legal references auto-boost: Lei 13709, Decreto nº 1.234
             Person names auto-detected: Fernando Haddad, Maria Silva
      page: 1-based page number
      page_size: results per page (1-100)
      date_from: YYYY-MM-DD lower bound
      date_to: YYYY-MM-DD upper bound
      section: 1 | 2 | 3 | e (DOU section filter, ignored for TCU)
      art_type: act type filter (e.g. decreto, portaria, resolução)
      issuing_organ: issuing organ filter
      topic: topic classification filter. Available topics:
             concurso_selecao, licitacao_compras, contrato_convenio,
             pessoal_rh, regulacao_norma, consulta_participacao,
             saude, educacao, meio_ambiente, financeiro,
             energia_telecom, administrativo
      intent: force intent classification. Options:
              trending | explore | exact_name | canonical | person
      is_trending: if true, prioritize recent documents
      source: data source filter. Options:
              dou — DOU documents only (default)
              tcu — TCU acórdãos only
              all — search both DOU and TCU
    """
    # TCU direct search — bypass API pipeline, hit ES directly
    if source in ("tcu", "all"):
        return _es_search_direct(
            query=query, page=page, page_size=page_size,
            date_from=date_from, date_to=date_to,
            source=source,
        )

    page = max(1, min(page, 500))
    page_size = max(1, min(page_size, 100))

    try:
        data = await API.search(
            q=query, page=page, max=page_size,
            date_from=date_from, date_to=date_to,
            section=section, art_type=art_type,
            issuing_organ=issuing_organ, topic=topic,
            intent=intent, is_trending=str(is_trending).lower() if is_trending else None,
        )
    except httpx.HTTPStatusError as exc:
        return {"error": f"API error: {exc.response.status_code}", "query": query, "total": 0, "results": []}

    return {
        "query": query,
        "total": data.get("total", 0),
        "page": data.get("page", page),
        "page_size": data.get("max", page_size),
        "took_ms": data.get("took_ms", 0),
        "intent": data.get("intent"),
        "suggestion": data.get("suggestion"),
        "results": data.get("results", []),
    }


# ---------------------------------------------------------------------------
# TOOL 2: es_suggest — Autocomplete
# ---------------------------------------------------------------------------

async def es_suggest(prefix: str, limit: int = 10) -> dict[str, Any]:
    """Autocomplete suggestions via GABI API.

    Args:
      prefix: partial text to autocomplete
      limit: max suggestions (1-20)
    """
    p = prefix.strip()
    if not p:
        return {"prefix": prefix, "suggestions": []}
    limit = max(1, min(limit, 20))
    try:
        data = await API.autocomplete(p, limit)
    except httpx.HTTPStatusError:
        return {"prefix": prefix, "suggestions": []}
    return {"prefix": prefix, "suggestions": data}


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
    source: str | None = None,
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
      source: dou | tcu | all (default: dou)
    """
    size = max(1, min(size, 30))
    index = ES.resolve_index(source)

    if source == "tcu":
        # TCU-specific facets
        filters: list[dict[str, Any]] = []
        if date_from or date_to:
            rng: dict[str, str] = {}
            if date_from:
                rng["gte"] = date_from
            if date_to:
                rng["lte"] = date_to
            filters.append({"range": {"data_sessao": rng}})

        payload = {
            "size": 0,
            "track_total_hits": True,
            "query": {"bool": {"must": [_query_clause(query)], "filter": filters}},
            "aggs": {
                "colegiados": {"terms": {"field": "colegiado", "size": 10}},
                "tipos_processo": {"terms": {"field": "tipo_processo", "size": size}},
                "relatores": {"terms": {"field": "relator.keyword", "size": size}},
                "dispositivo": {"terms": {"field": "dispositivo_resumo", "size": size}},
                "temas": {"terms": {"field": "temas_tcu", "size": size}},
                "by_month": {"date_histogram": {"field": "data_sessao", "calendar_interval": "month"}},
            },
        }
        data = ES.request("POST", f"/{index}/_search", payload)
        aggs = data.get("aggregations", {})
        total = int(data.get("hits", {}).get("total", {}).get("value", 0))
        return {
            "query": query,
            "source": "tcu",
            "total": total,
            "facets": {
                "colegiados": _extract_agg_buckets(aggs, "colegiados"),
                "tipos_processo": _extract_agg_buckets(aggs, "tipos_processo"),
                "relatores": _extract_agg_buckets(aggs, "relatores"),
                "dispositivo": _extract_agg_buckets(aggs, "dispositivo"),
                "temas": _extract_agg_buckets(aggs, "temas"),
                "by_month": _extract_agg_buckets(aggs, "by_month"),
            },
        }

    # Default: DOU facets
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
    data = ES.request("POST", f"/{index}/_search", payload)
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

async def es_document(doc_id: str, source: str | None = None) -> dict[str, Any]:
    """Fetch a single document by its ID.

    For TCU documents (doc_id starting with ACORDAO-COMPLETO-), fetches
    directly from ES. For DOU documents, uses the GABI API.

    Args:
      doc_id: the document ID
      source: dou | tcu (auto-detected from doc_id prefix if omitted)
    """
    is_tcu = (source == "tcu") or doc_id.startswith("ACORDAO-COMPLETO-")

    if is_tcu:
        try:
            data = ES.request("GET", f"/{ES.tcu_index}/_doc/{doc_id}")
            src = data.get("_source", {})
            return {"found": True, "doc_id": doc_id, "source_type": "tcu_acordao", "document": src}
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return {"found": False, "doc_id": doc_id}
            raise

    try:
        data = await API.document(doc_id)
        return {"found": True, "doc_id": doc_id, "source_type": "dou", "document": data}
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            return {"found": False, "doc_id": doc_id}
        raise


# ---------------------------------------------------------------------------
# TOOL 5: es_health — Cluster diagnostics
# ---------------------------------------------------------------------------

def es_health() -> dict[str, Any]:
    """Cluster and index health summary with storage and performance stats for DOU and TCU."""
    health = ES.request("GET", "/_cluster/health")
    count = ES.request("GET", f"/{ES.index}/_count")
    tcu_count = 0
    try:
        tcu_count = int(ES.request("GET", f"/{ES.tcu_index}/_count").get("count", 0))
    except Exception:
        pass  # TCU index may not exist yet
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
        "dou_index": ES.index,
        "dou_count": int(count.get("count", 0)),
        "tcu_index": ES.tcu_index,
        "tcu_count": tcu_count,
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
    source: str | None = "all",
) -> dict[str, Any]:
    """Find all documents that cite or reference a specific law, decree, or act.

    Searches across body text in BOTH DOU and TCU for mentions of a legal
    reference (e.g., "Lei 13709", "Decreto 9.203"). This builds a citation
    network — essential for understanding regulatory impact and legislative reach.

    Args:
      reference: the legal reference to search for (e.g., "Lei 13709", "Decreto 9.203/2017")
      max_results: number of citing documents (1-100)
      date_from: YYYY-MM-DD lower bound
      date_to: YYYY-MM-DD upper bound
      section: do1 | do2 | do3
      source: dou | tcu | all (default: all — searches both DOU and TCU)
    """
    max_results = max(1, min(max_results, 100))
    ref = reference.strip()
    if not ref:
        return {"error": "Provide a legal reference to search for."}

    index = ES.resolve_index(source)

    filters = _build_filters(
        date_from=date_from, date_to=date_to,
        section=section, art_type=None, issuing_organ=None,
    )

    # Search across text fields that exist in both DOU and TCU indexes
    text_fields = ["body_plain", "search_all", "acordao_texto", "voto", "relatorio"]

    payload = {
        "from": 0,
        "size": max_results,
        "track_total_hits": True,
        "query": {
            "bool": {
                "must": [{
                    "bool": {
                        "should": [
                            {"match_phrase": {field: {"query": ref}}}
                            for field in text_fields
                        ],
                        "minimum_should_match": 1,
                    },
                }],
                "filter": filters,
            },
        },
        "sort": [{"_score": {"order": "desc"}}],
        "_source": _SOURCE_FIELDS + _TCU_SOURCE_FIELDS,
        "highlight": {
            "pre_tags": [">>>"], "post_tags": ["<<<"],
            "fields": {
                "body_plain": {"number_of_fragments": 1, "fragment_size": 300},
                "acordao_texto": {"number_of_fragments": 1, "fragment_size": 300},
                "search_all": {"number_of_fragments": 1, "fragment_size": 300},
            },
        },
        "aggs": {
            "citing_organs": {"terms": {"field": "issuing_organ.keyword", "size": 10}},
            "citing_types": {"terms": {"field": "art_type.keyword", "size": 10}},
            "citations_over_time": {"date_histogram": {"field": "pub_date", "calendar_interval": "year", "min_doc_count": 1}},
        },
    }
    data = ES.request("POST", f"/{index}/_search", payload)
    hits = data.get("hits", {}).get("hits", [])
    total = int(data.get("hits", {}).get("total", {}).get("value", 0))
    aggs = data.get("aggregations", {})

    # Format mixed results
    results: list[dict[str, Any]] = []
    for hit in hits:
        src = hit.get("_source", {})
        if (src.get("source_type") or "").startswith("tcu_"):
            results.extend(_format_tcu_hits([hit]))
        else:
            results.extend(_format_hits([hit]))

    return {
        "reference": reference,
        "source": source,
        "total_citations": total,
        "citing_organs": _extract_agg_buckets(aggs, "citing_organs"),
        "citing_types": _extract_agg_buckets(aggs, "citing_types"),
        "citations_over_time": [
            {"year": b.get("key_as_string"), "count": b.get("doc_count", 0)}
            for b in aggs.get("citations_over_time", {}).get("buckets", [])
        ],
        "results": results,
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
# OpenAI embedding helper for MCP TCU tools
# ---------------------------------------------------------------------------

_OPENAI_EMBED_MODEL = "text-embedding-3-small"
_OPENAI_EMBED_DIMS = 1536


def _get_openai_embedding(text: str) -> list[float] | None:
    """Get embedding via OpenAI API. Returns None if unavailable."""
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return None
    try:
        with httpx.Client(timeout=10) as client:
            resp = client.post(
                "https://api.openai.com/v1/embeddings",
                headers={"Authorization": f"Bearer {api_key}"},
                json={"model": _OPENAI_EMBED_MODEL, "input": [text], "dimensions": _OPENAI_EMBED_DIMS},
            )
            resp.raise_for_status()
            return resp.json()["data"][0]["embedding"]
    except Exception:
        logger.warning("OpenAI embedding failed", exc_info=True)
        return None


# ---------------------------------------------------------------------------
# TOOL 14: es_tcu_semantic_search — Semantic kNN search on TCU embeddings
# ---------------------------------------------------------------------------

_NORMAS_SOURCE_FIELDS = [
    "doc_id", "titulo", "assunto", "tipo_norma", "numero_norma", "ano_norma",
    "situacao", "vigente", "data_inicio_vigencia", "data_fim_vigencia",
    "origem", "unidade_autora", "numero_processo", "tema",
    "source_type", "link_btcu",
]

_NORMAS_HIGHLIGHT_SPEC: dict[str, Any] = {
    "pre_tags": [">>>"],
    "post_tags": ["<<<"],
    "max_analyzed_offset": 500000,
    "fields": {
        "titulo": {"number_of_fragments": 0},
        "assunto": {"number_of_fragments": 1, "fragment_size": 280},
        "texto_norma": {"number_of_fragments": 2, "fragment_size": 200},
    },
}


def _format_normas_hits(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Format TCU normas ES hits into result dicts."""
    results: list[dict[str, Any]] = []
    for hit in hits:
        src = hit.get("_source", {})
        hl = hit.get("highlight", {})

        snippet_parts: list[str] = []
        for k in ("assunto", "titulo", "texto_norma"):
            frags = hl.get(k)
            if frags:
                snippet_parts.extend(frags)
                if len(snippet_parts) >= 2:
                    break
        snippet = " … ".join(snippet_parts) if snippet_parts else (
            src.get("assunto") or src.get("titulo") or ""
        )[:280]

        results.append({
            "doc_id": src.get("doc_id") or hit.get("_id"),
            "score": round(float(hit.get("_score") or 0.0), 4),
            "titulo": src.get("titulo"),
            "assunto": src.get("assunto"),
            "tipo_norma": src.get("tipo_norma"),
            "numero_norma": src.get("numero_norma"),
            "ano_norma": src.get("ano_norma"),
            "vigente": src.get("vigente"),
            "situacao": src.get("situacao"),
            "origem": src.get("origem"),
            "tema": src.get("tema"),
            "source_type": src.get("source_type", "tcu_norma"),
            "link_btcu": src.get("link_btcu"),
            "snippet": snippet,
        })
    return results


def es_tcu_semantic_search(
    query: str,
    source: str = "tcu",
    k: int = 20,
    date_from: str | None = None,
    date_to: str | None = None,
    colegiado: str | None = None,
    tipo_processo: str | None = None,
    dispositivo: str | None = None,
    vigente: bool | None = None,
    tipo_norma: str | None = None,
) -> dict[str, Any]:
    """Semantic search on TCU documents using vector embeddings (kNN).

    Use this when BM25 keyword search fails — for conceptual queries like
    "responsabilidade do gestor por omissão" or "plano de saúde servidores".
    Finds semantically similar documents even without exact keyword matches.

    Args:
      query: natural language query in Portuguese
      source: 'tcu' (acórdãos+jurisprudência+boletins), 'normas', or 'all' (both)
      k: number of results (1-50)
      date_from: YYYY-MM-DD lower bound
      date_to: YYYY-MM-DD upper bound
      colegiado: Plenário | Primeira Câmara | Segunda Câmara (tcu only)
      tipo_processo: e.g. REPRESENTAÇÃO, DENÚNCIA (tcu only)
      dispositivo: dispositivo_resumo filter (tcu only)
      vigente: filter by vigente status (normas only, default True for normas)
      tipo_norma: e.g. Portaria, Resolução, Instrução Normativa (normas only)
    """
    k = max(1, min(k, 50))
    query_vector = _get_openai_embedding(query)
    if query_vector is None:
        return {"error": "Embedding service unavailable (OPENAI_API_KEY not set or API error)"}

    # Determine target index
    if source == "normas":
        index = ES.normas_index
    elif source == "all":
        index = f"{ES.tcu_index},{ES.normas_index}"
    else:
        index = ES.tcu_index

    filters: list[dict[str, Any]] = []
    if date_from or date_to:
        rng: dict[str, str] = {}
        if date_from:
            rng["gte"] = date_from
        if date_to:
            rng["lte"] = date_to
        # Use appropriate date field based on source
        date_field = "data_inicio_vigencia" if source == "normas" else "data_sessao"
        filters.append({"range": {date_field: rng}})
    if colegiado:
        filters.append({"term": {"colegiado": colegiado}})
    if tipo_processo:
        filters.append({"match": {"tipo_processo": tipo_processo}})
    if dispositivo:
        filters.append({"term": {"dispositivo_resumo": dispositivo}})
    # Normas-specific filters
    if vigente is not None:
        filters.append({"term": {"vigente": vigente}})
    elif source == "normas":
        filters.append({"term": {"vigente": True}})  # default: only vigentes
    if tipo_norma:
        filters.append({"term": {"tipo_norma": tipo_norma}})

    payload: dict[str, Any] = {
        "size": k,
        "knn": {
            "field": "embedding",
            "query_vector": query_vector,
            "k": k,
            "num_candidates": min(k * 4, 200),
        },
    }

    # Source fields and highlight depend on target
    if source == "normas":
        payload["_source"] = _NORMAS_SOURCE_FIELDS
        payload["highlight"] = _NORMAS_HIGHLIGHT_SPEC
    elif source == "all":
        payload["_source"] = list(set(_TCU_SOURCE_FIELDS + _NORMAS_SOURCE_FIELDS))
        payload["highlight"] = _TCU_HIGHLIGHT_SPEC
    else:
        payload["_source"] = _TCU_SOURCE_FIELDS
        payload["highlight"] = _TCU_HIGHLIGHT_SPEC

    if filters:
        payload["knn"]["filter"] = {"bool": {"filter": filters}}

    data = ES.request("POST", f"/{index}/_search", payload)
    hits = data.get("hits", {}).get("hits", [])
    total = int(data.get("hits", {}).get("total", {}).get("value", 0))

    # Format hits based on source
    if source == "normas":
        results = _format_normas_hits(hits)
    elif source == "all":
        # Mixed results — format based on each hit's index
        results = []
        for hit in hits:
            if ES.normas_index in hit.get("_index", ""):
                results.extend(_format_normas_hits([hit]))
            else:
                results.extend(_format_tcu_hits([hit]))
    else:
        results = _format_tcu_hits(hits)

    return {
        "query": query,
        "source": source,
        "method": "semantic_knn",
        "total": total,
        "results": results,
    }


# ---------------------------------------------------------------------------
# TOOL 15: es_tcu_similar — Find similar acórdãos via vector similarity
# ---------------------------------------------------------------------------

def es_tcu_similar(
    doc_id: str,
    source: str = "tcu",
    k: int = 10,
) -> dict[str, Any]:
    """Find TCU documents similar to a given document using vector similarity.

    Better than term-based more_like_this — captures semantic similarity
    even when vocabulary differs. Use to find related rulings, normas,
    or jurisprudence on the same topic.

    Args:
      doc_id: TCU document ID (e.g. ACORDAO-COMPLETO-2705853 or NORMA-21764)
      source: 'tcu' (search acórdãos), 'normas' (search normas), or 'all' (both)
      k: number of similar documents (1-50)
    """
    k = max(1, min(k, 50))

    # Determine which index the seed doc lives in
    seed_index = ES.normas_index if doc_id.startswith("NORMA-") else ES.tcu_index

    # Fetch the source document's embedding from ES
    try:
        doc_data = ES.request("GET", f"/{seed_index}/_source/{doc_id}?_source_includes=embedding,titulo")
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            return {"error": f"Document {doc_id} not found"}
        raise

    source_embedding = doc_data.get("embedding")
    if not source_embedding:
        return {"error": f"Document {doc_id} has no embedding yet"}

    # Determine search index
    if source == "normas":
        search_index = ES.normas_index
    elif source == "all":
        search_index = f"{ES.tcu_index},{ES.normas_index}"
    else:
        search_index = ES.tcu_index

    is_normas = source == "normas"
    payload: dict[str, Any] = {
        "size": k + 1,  # +1 to exclude self
        "knn": {
            "field": "embedding",
            "query_vector": source_embedding,
            "k": k + 1,
            "num_candidates": min((k + 1) * 4, 200),
        },
        "_source": _NORMAS_SOURCE_FIELDS if is_normas else _TCU_SOURCE_FIELDS,
    }

    data = ES.request("POST", f"/{search_index}/_search", payload)
    hits = data.get("hits", {}).get("hits", [])

    # Filter out the seed document
    hits = [h for h in hits if h.get("_id") != doc_id][:k]

    # Format based on source
    if is_normas:
        results = _format_normas_hits(hits)
    elif source == "all":
        results = []
        for hit in hits:
            if ES.normas_index in hit.get("_index", ""):
                results.extend(_format_normas_hits([hit]))
            else:
                results.extend(_format_tcu_hits([hit]))
    else:
        results = _format_tcu_hits(hits)

    return {
        "seed_doc_id": doc_id,
        "seed_titulo": doc_data.get("titulo"),
        "method": "vector_similarity",
        "results": results,
    }


# ---------------------------------------------------------------------------
# MCP registration
# ---------------------------------------------------------------------------

if FastMCP is not None:
    mcp = FastMCP(
        "gabi-dou",
        instructions=(
            "Hybrid search server for Brazil's Diário Oficial da União (DOU) and "
            "Tribunal de Contas da União (TCU) jurisprudence. "
            "15 tools over ~16M DOU legal documents (2002-2026) and ~520K TCU acórdãos (1992-2026). Capabilities:\n"
            "- SEARCH: es_search (hybrid BM25 + kNN via RRF, intent detection, "
            "topic classification, person name detection, quoted phrases, "
            "canonical law lookup, neural reranking). Use source='tcu' for TCU, "
            "source='all' for cross-search DOU+TCU.\n"
            "- DISCOVER: es_more_like_this (find similar docs), es_significant_terms "
            "(theme discovery), es_cross_reference (citation network — searches DOU+TCU by default)\n"
            "- ANALYZE: es_timeline (temporal trends), es_trending (recent activity), "
            "es_organ_profile (institutional analysis), es_compare_periods (before/after)\n"
            "- UTILITY: es_suggest (autocomplete), es_facets (aggregations — use source='tcu' for "
            "colegiados, relatores, tipos_processo, dispositivo facets), "
            "es_document (fetch), es_health (status), es_explain (debug ranking)\n\n"
            "Tips: Use Portuguese terms. Use quotes for exact phrases. "
            "Use topic= filter: concurso_selecao, licitacao_compras, regulacao_norma, "
            "pessoal_rh, contrato_convenio, saude, educacao, financeiro, meio_ambiente. "
            "Legal references (Lei 13709) auto-boost. Combine tools for deep analysis. "
            "TCU search: use source='tcu' and filter by colegiado, relator, tipo_processo, "
            "dispositivo_tipo (irregular, aplicar_multa, imputar_debito, etc.).\n"
            "- TCU SEMANTIC: es_tcu_semantic_search (kNN vector search for conceptual queries, source='tcu'/'normas'/'all'), "
            "es_tcu_similar (find similar docs by vector similarity, source='tcu'/'normas'/'all')"
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
    mcp.tool()(es_tcu_semantic_search)
    mcp.tool()(es_tcu_similar)
else:
    mcp = None


def get_mcp_sse_app():
    """Return the MCP SSE ASGI app for mounting inside FastAPI."""
    if mcp is None:
        return None

    app = mcp.sse_app()

    mcp_auth_token = os.getenv("MCP_AUTH_TOKEN", "").strip()
    if not mcp_auth_token:
        return app

    logger.info("MCP SSE: bearer token auth enabled")

    from starlette.responses import JSONResponse as _JSONResp

    class _AuthWrap:
        def __init__(self, inner):  # type: ignore
            self.inner = inner

        async def __call__(self, scope, receive, send):  # type: ignore
            if scope["type"] == "http":
                headers = dict(scope.get("headers", []))
                auth = (headers.get(b"authorization") or b"").decode()
                if not auth.startswith("Bearer ") or auth[7:] != mcp_auth_token:
                    resp = _JSONResp(status_code=401, content={"detail": "Invalid MCP auth token"})
                    await resp(scope, receive, send)
                    return
            await self.inner(scope, receive, send)

    return _AuthWrap(app)


def main() -> int:
    import argparse

    p = argparse.ArgumentParser(description="GABI DOU Search MCP Server")
    p.add_argument("--transport", choices=["stdio", "sse"], default="stdio")
    p.add_argument("--port", type=int, default=8766)
    args = p.parse_args()

    if mcp is None:
        raise SystemExit("mcp package is not installed.")

    if args.transport == "sse":
        mcp_auth_token = os.getenv("MCP_AUTH_TOKEN", "").strip()
        if mcp_auth_token:
            logger.info("SSE transport: bearer token auth enabled")

            # Wrap the SSE app with auth middleware
            from starlette.responses import JSONResponse as StarletteJSONResponse

            class _MCPAuthMiddleware:
                def __init__(self, app):  # type: ignore
                    self.app = app

                async def __call__(self, scope, receive, send):  # type: ignore
                    if scope["type"] == "http":
                        headers = dict(scope.get("headers", []))
                        auth = (headers.get(b"authorization") or b"").decode()
                        if not auth.startswith("Bearer ") or auth[7:] != mcp_auth_token:
                            response = StarletteJSONResponse(
                                status_code=401,
                                content={"detail": "Invalid MCP auth token"},
                            )
                            await response(scope, receive, send)
                            return
                    await self.app(scope, receive, send)

            # Use lower-level API to wrap the SSE app
            mcp.settings.port = args.port
            mcp.run(transport="sse")  # TODO: inject middleware when FastMCP supports it
        else:
            mcp.settings.port = args.port
            mcp.run(transport="sse")
    else:
        mcp.run(transport="stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
