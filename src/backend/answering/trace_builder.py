"""FASE 6: per-chunk trace with 13 analytical components + confidence disclosure.

Each retrieved chunk gets a ChunkTrace with scores and reasons.
ConfidenceDisclosure aggregates chunk-level data for user-facing transparency.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from src.backend.search.scoring import compute_final_score


# ---------------------------------------------------------------------------
# Authority scoring — normative sources score higher
# ---------------------------------------------------------------------------

_HIGH_AUTHORITY_PATTERNS = re.compile(
    r"\b(minist[eé]rio|presid[eê]ncia|congresso|senado|c[âa]mara|tribunal|tcu|"
    r"supremo|stf|stj|secretaria.especial|conselho.nacional|casa.civil)\b",
    re.IGNORECASE,
)
_LOW_AUTHORITY_PATTERNS = re.compile(
    r"\b(autarquia|fundac[ãa]o|empresa.p[uú]blica|sociedade.de.economia.mista)\b",
    re.IGNORECASE,
)

_NORMATIVE_TYPES = frozenset(
    {
        "Portaria",
        "Decreto",
        "Lei",
        "Instrução Normativa",
        "Resolução",
        "Medida Provisória",
        "Acórdão",
    }
)
_INFORMATIVE_TYPES = frozenset(
    {"Aviso", "Comunicado", "Edital", "Extrato", "Despacho", "Apostila"}
)


def _compute_authority(source: dict[str, Any]) -> float:
    organ = source.get("issuing_organ") or source.get("organ") or ""
    art_type = source.get("art_type") or source.get("tipo_processo") or ""
    section = source.get("section") or ""

    score = 0.5
    if _HIGH_AUTHORITY_PATTERNS.search(organ):
        score += 0.3
    elif _LOW_AUTHORITY_PATTERNS.search(organ):
        score -= 0.1

    if art_type in _NORMATIVE_TYPES:
        score += 0.2
    elif art_type in _INFORMATIVE_TYPES:
        score -= 0.1

    if section in ("do1", "tcu"):
        score += 0.1
    elif section in ("do2", "do3"):
        score -= 0.05

    return round(min(1.0, max(0.0, score)), 3)


# ---------------------------------------------------------------------------
# Entity density — legal entity mentions per 100 chars
# ---------------------------------------------------------------------------

_LEGAL_ENTITY_RE = re.compile(
    r"\b(lei|decreto|portaria|resolu[çc][ãa]o|instru[çc][ãa]o|ac[oó]rd[ãa]o|"
    r"art\.|artigo|inciso|par[áa]grafo|alin[eé]a|cnpj|cpf|processo)\b",
    re.IGNORECASE,
)


def _compute_entity_density(text: str) -> float:
    if not text:
        return 0.0
    matches = len(_LEGAL_ENTITY_RE.findall(text))
    density = (matches / max(len(text), 1)) * 100
    return round(min(1.0, density), 4)


# ---------------------------------------------------------------------------
# Evidence score — presence of evidence-signaling language
# ---------------------------------------------------------------------------

_EVIDENCE_SIGNALS = re.compile(
    r"\b(comprova|demonstra|evidencia|constata|verifica|apura|registra|"
    r"consigna|atesta|conforme|nos termos|de acordo|estabelece|determina|"
    r"dispõe|prevê|autoriza)\b",
    re.IGNORECASE,
)
_BOILERPLATE_SIGNALS = re.compile(
    r"\b(bug:|debug|test[e]?:|fixme|todo:|xxx|lorem ipsum|placeholder)\b",
    re.IGNORECASE,
)


def _compute_evidence_score(text: str) -> float:
    if not text:
        return 0.0
    signals = len(_EVIDENCE_SIGNALS.findall(text))
    density = (signals / max(len(text), 1)) * 100
    return round(min(1.0, density * 2), 4)


# ---------------------------------------------------------------------------
# Policy multiplier — section/type preference per query
# ---------------------------------------------------------------------------

_NORMATIVE_SECTION_BOOST = {"do1": 1.10, "tcu": 1.15}
_SECTION_PENALTY = {"do3": 0.90}


def _compute_policy_multiplier(source: dict[str, Any]) -> float:
    section = (source.get("section") or "").lower()
    art_type = source.get("art_type") or ""
    multiplier = 1.0
    multiplier *= _NORMATIVE_SECTION_BOOST.get(section, 1.0)
    multiplier *= _SECTION_PENALTY.get(section, 1.0)
    if art_type in _NORMATIVE_TYPES:
        multiplier *= 1.05
    return round(multiplier, 4)


# ---------------------------------------------------------------------------
# Boosts and penalties detection
# ---------------------------------------------------------------------------

_BOOST_PATTERNS = [
    (re.compile(r"\bsíntese\b|\bsínteses\b", re.IGNORECASE), "boost_sintese", 1.10),
    (
        re.compile(r"\bnormativo\b|\bnormativa\b", re.IGNORECASE),
        "boost_normative",
        1.08,
    ),
    (re.compile(r"\bjurisprud[êe]ncia\b", re.IGNORECASE), "boost_jurisprudencia", 1.12),
    (re.compile(r"\bac[óo]rd[ãa]o\b", re.IGNORECASE), "boost_acordao", 1.10),
]

_PENALTY_PATTERNS = [
    (
        re.compile(r"\bboilerplate\b|lorem ipsum", re.IGNORECASE),
        "penalty_boilerplate",
        0.60,
    ),
    (
        re.compile(r"\bbug:|debug:|fixme:", re.IGNORECASE),
        "penalty_debug_artifact",
        0.40,
    ),
    (re.compile(r"^[\s\.\-]{10,}$", re.MULTILINE), "penalty_low_content", 0.80),
]


def _compute_boosts_penalties(
    text: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    boosts: list[dict[str, Any]] = []
    penalties: list[dict[str, Any]] = []
    for pattern, label, factor in _BOOST_PATTERNS:
        if pattern.search(text):
            boosts.append({"pattern": label, "factor": factor})
    for pattern, label, factor in _PENALTY_PATTERNS:
        if pattern.search(text):
            penalties.append({"pattern": label, "factor": factor})
    return boosts, penalties


# ---------------------------------------------------------------------------
# Normalisation helpers
# ---------------------------------------------------------------------------


def _normalise_scores(values: list[float]) -> list[float]:
    if not values:
        return values
    max_val = max(values) or 1.0
    return [round(v / max_val, 4) for v in values]


# ---------------------------------------------------------------------------
# Main dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ChunkTrace:
    chunk_id: str
    bm25_raw: float
    bm25_norm: float
    vector_raw: float | None
    vector_norm: float | None
    rerank_raw: float | None
    rerank_norm: float | None
    authority: float
    entity_density: float
    evidence_score: float
    policy_multiplier: float
    boosts: tuple[dict[str, Any], ...]
    penalties: tuple[dict[str, Any], ...]
    final_score: float
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class FilteredChunk:
    chunk_id: str
    reason: str
    pattern: str


@dataclass(frozen=True)
class ConfidenceDisclosure:
    score: float
    below_threshold: bool
    disclaimer: str
    doc_count: int
    safe_mode: bool


@dataclass
class AnswerTraceDetail:
    chunk_traces: list[ChunkTrace] = field(default_factory=list)
    filtered_out: list[FilteredChunk] = field(default_factory=list)
    confidence_disclosure: ConfidenceDisclosure | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunk_traces": [_chunk_to_dict(c) for c in self.chunk_traces],
            "filtered_out": [
                {"chunk_id": f.chunk_id, "reason": f.reason, "pattern": f.pattern}
                for f in self.filtered_out
            ],
            "confidence_disclosure": (
                {
                    "score": self.confidence_disclosure.score,
                    "below_threshold": self.confidence_disclosure.below_threshold,
                    "disclaimer": self.confidence_disclosure.disclaimer,
                    "doc_count": self.confidence_disclosure.doc_count,
                    "safe_mode": self.confidence_disclosure.safe_mode,
                }
                if self.confidence_disclosure
                else None
            ),
        }


def _chunk_to_dict(c: ChunkTrace) -> dict[str, Any]:
    return {
        "chunk_id": c.chunk_id,
        "bm25_raw": c.bm25_raw,
        "bm25_norm": c.bm25_norm,
        "vector_raw": c.vector_raw,
        "vector_norm": c.vector_norm,
        "rerank_raw": c.rerank_raw,
        "rerank_norm": c.rerank_norm,
        "authority": c.authority,
        "entity_density": c.entity_density,
        "evidence_score": c.evidence_score,
        "policy_multiplier": c.policy_multiplier,
        "boosts": list(c.boosts),
        "penalties": list(c.penalties),
        "final_score": c.final_score,
        "reasons": list(c.reasons),
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_CONFIDENCE_THRESHOLD = 0.4


def build_chunk_traces(
    docs: list[dict[str, Any]],
    *,
    safe_mode: bool = False,
    query_type: str = "exploratory",
) -> AnswerTraceDetail:
    """Build per-chunk traces from ES hits.

    ES hits have _score (BM25 or RRF combined).  Vector/rerank fields are None
    when those subsystems are disabled (production default).
    """
    if not docs:
        return AnswerTraceDetail(
            confidence_disclosure=ConfidenceDisclosure(
                score=0.0,
                below_threshold=True,
                disclaimer="Nenhum documento recuperado.",
                doc_count=0,
                safe_mode=safe_mode,
            )
        )

    bm25_raws = [float(d.get("_score") or 0.0) for d in docs]
    bm25_norms = _normalise_scores(bm25_raws)

    rerank_raws: list[float | None] = []
    for d in docs:
        rs = d.get("_rerank_score")
        if rs is not None:
            rerank_raws.append(float(rs))
        else:
            rerank_raws.append(None)
    rerank_vals = [r for r in rerank_raws if r is not None]
    rerank_norm_map: dict[int, float] = {}
    if rerank_vals:
        norm_list = _normalise_scores(rerank_vals)
        j = 0
        for i, r in enumerate(rerank_raws):
            if r is not None:
                rerank_norm_map[i] = norm_list[j]
                j += 1

    chunk_traces: list[ChunkTrace] = []
    filtered_out: list[FilteredChunk] = []

    for idx, (doc, bm25_raw, bm25_norm) in enumerate(zip(docs, bm25_raws, bm25_norms)):
        chunk_id = str(doc.get("_id") or doc.get("id") or "")
        source = doc.get("_source", doc)
        body = source.get("body_plain") or source.get("ementa") or ""

        boosts, penalties = _compute_boosts_penalties(body)

        if any(p["pattern"] == "penalty_debug_artifact" for p in penalties):
            filtered_out.append(
                FilteredChunk(
                    chunk_id=chunk_id,
                    reason="debug_artifact",
                    pattern="bug:/debug:/fixme:",
                )
            )
            continue

        authority = _compute_authority(source)
        entity_density = _compute_entity_density(body)
        evidence_score = _compute_evidence_score(body)
        policy_mult = _compute_policy_multiplier(source)

        boost_factor = 1.0
        for b in boosts:
            boost_factor *= b["factor"]
        penalty_factor = 1.0
        for p in penalties:
            penalty_factor *= p["factor"]

        rr_raw = rerank_raws[idx]
        rr_norm = rerank_norm_map.get(idx)
        relevance_base = rr_norm if rr_norm is not None else bm25_norm
        final_score = compute_final_score(
            query_type=query_type,
            relevance_base=relevance_base,
            authority=authority,
            entity_density=entity_density,
            evidence_score=evidence_score,
            policy_multiplier=policy_mult,
            boost_factor=boost_factor,
            penalty_factor=penalty_factor,
        )

        reasons: list[str] = []
        if rr_norm is not None:
            reasons.append("rerank_applied")
        if authority > 0.8:
            reasons.append("authority_normative")
        if evidence_score > 0.3:
            reasons.append("high_evidence_density")
        for b in boosts:
            reasons.append(b["pattern"])

        chunk_traces.append(
            ChunkTrace(
                chunk_id=chunk_id,
                bm25_raw=bm25_raw,
                bm25_norm=bm25_norm,
                vector_raw=None,
                vector_norm=None,
                rerank_raw=rr_raw,
                rerank_norm=rr_norm,
                authority=authority,
                entity_density=entity_density,
                evidence_score=evidence_score,
                policy_multiplier=policy_mult,
                boosts=tuple(boosts),
                penalties=tuple(penalties),
                final_score=final_score,
                reasons=tuple(reasons),
            )
        )

    avg_score = (
        sum(c.final_score for c in chunk_traces) / len(chunk_traces)
        if chunk_traces
        else 0.0
    )
    avg_score = round(avg_score, 3)
    below = avg_score < _CONFIDENCE_THRESHOLD

    if below:
        disclaimer = (
            f"Confiança baixa ({avg_score:.0%}). Verifique os documentos originais."
        )
    else:
        doc_count = len(chunk_traces)
        disclaimer = (
            f"Resposta baseada em {doc_count} documento{'s' if doc_count != 1 else ''}."
        )

    disclosure = ConfidenceDisclosure(
        score=avg_score,
        below_threshold=below,
        disclaimer=disclaimer,
        doc_count=len(chunk_traces),
        safe_mode=safe_mode,
    )

    return AnswerTraceDetail(
        chunk_traces=chunk_traces,
        filtered_out=filtered_out,
        confidence_disclosure=disclosure,
    )
