from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

if True:
    from src.backend.search.intent import QueryIntent

QUERY_TYPES = (
    "exact_match",
    "aggregation",
    "summary",
    "factual",
    "exploratory",
    "evidential",
    "legal_reference",
    "accountability",
    "recommendation",
)

RISK_WEIGHTS = {
    "hierarchical_query": 0.30,
    "subscope_resolution_risk": 0.25,
    "multi_evidence_required": 0.30,
    "entity_resolution_risk": 0.20,
    "aggregation_precision_risk": 0.20,
    "legal_precision_required": 0.15,
    "recommendation_synthesis_risk": 0.20,
    "low_context": 0.20,
    "cross_source_conflict": 0.15,
    "ranking_ambiguity": 0.15,
    "corpus_stale": 0.25,
}

HIERARCHICAL_RE = re.compile(
    r"\b(se[çc][aã]o|item|inciso|alin[ea]|par[áa]grafo|subitem)\s+"
    r"(?:\d+(?:\.\d+)*|[ivxlcdm]+)\b",
    re.IGNORECASE,
)
SUB_SCOPE_RE = re.compile(
    r"\b(subitem|subpar[áa]grafo|inciso|alin[ea])\s+[a-z0-9]+\b",
    re.IGNORECASE,
)
EXACT_REF_RE = re.compile(
    r'"[^"]{10,}"|'
    r"\bport\.?\s+\S+\s+\d+\b|"
    r"\b(lei|decreto|portaria|ac[óo]rd[ãa]o|instru[çc][ãa]o)\s+\d+",
    re.IGNORECASE,
)

_EXACT_MATCH_TOKENS = frozenset(
    {
        "port",
        "portaria",
        "dec",
        "decreto",
        "lei",
        "mp",
        "in",
        "res",
        "edital",
        "acordao",
    }
)
_AGGREGATION_TOKENS = frozenset(
    {
        "quantas",
        "quantos",
        "quantidade",
        "total",
        "número",
        "numero",
        "lista",
        "liste",
    }
)
_SUMMARY_TOKENS = frozenset({"resuma", "resumo", "síntese", "sintese", "explique"})
_EVIDENTIAL_TOKENS = frozenset(
    {
        "evidência",
        "evidencias",
        "evidências",
        "prova",
        "provaram",
        "provar",
        "comprova",
        "comprovam",
        "comprovação",
        "comprovacao",
        "documento",
        "documentos",
        "base",
        "probatória",
        "proatoria",
        "verificado",
    }
)
_LEGAL_TOKENS = frozenset(
    {
        "legislação",
        "legislacao",
        "norma",
        "normas",
        "lei",
        "decreto",
        "portaria",
        "iso",
        "tcu",
    }
)
_ACCOUNTABILITY_TOKENS = frozenset({"responsável", "responsavel", "responsabilidade"})
_RECOMMENDATION_TOKENS = frozenset(
    {
        "proposta",
        "solução",
        "solucao",
        "recomendação",
        "recomendacao",
        "recomendado",
    }
)
_FACTUAL_TOKENS = frozenset(
    {"quais", "qual", "causas", "causa", "efeitos", "efeito", "riscos", "risco"}
)

_DECRETO_NUM_SHORT_REF = re.compile(r"^\s*decreto\s+\d+\s*$", re.IGNORECASE)
_LEI_NUM_SOBRE_RE = re.compile(r"\blei\s+\d+\s+sobre\b", re.IGNORECASE)


@dataclass(frozen=True)
class QueryClassification:
    query_type: str
    confidence: float
    source: str = "rule"
    used_llm_fallback: bool = False
    facets: tuple[str, ...] = ()
    gabi_intent: Optional["QueryIntent"] = None


@dataclass(frozen=True)
class RiskAssessment:
    flags: tuple[str, ...]
    score: float
    safe_mode: bool


def _detect_facets(query: str) -> tuple[str, ...]:
    if not query:
        return ()
    facets: list[str] = []
    if HIERARCHICAL_RE.search(query):
        facets.append("hierarchical")
    if SUB_SCOPE_RE.search(query):
        facets.append("subscope")
    if EXACT_REF_RE.search(query):
        facets.append("exact_reference")
    return tuple(facets)


def _normalize_for_matching(s: str) -> str:
    import unicodedata

    return (
        unicodedata.normalize("NFD", s.lower().strip())
        .replace("\u0300", "")
        .replace("\u0301", "")
        .replace("\u0303", "")
    )


def _contains_token(lowered: str, token_set: frozenset[str]) -> bool:
    tokens = set(re.findall(r"\b[\w-]+\b", lowered))
    return bool(tokens & token_set)


def gabi_intent_to_query_type(
    gabi_intent: "QueryIntent",
    classification: QueryClassification,
    *,
    query: str = "",
) -> QueryClassification:
    mapping: dict["QueryIntent", tuple[str, float]] = {
        QueryIntent.EXACT_NAME: ("exact_match", 0.95),
        QueryIntent.CANONICAL_LOOKUP: ("legal_reference", 0.90),
        QueryIntent.PERSON_NAME: ("exact_match", 0.90),
        QueryIntent.TRENDING_BROWSE: ("exploratory", 0.80),
        QueryIntent.SUBJECT_EXPLORE: ("exploratory", 0.50),
    }
    caf_type, base_conf = mapping.get(gabi_intent, ("exploratory", 0.50))
    if (
        gabi_intent == QueryIntent.EXACT_NAME
        and classification.query_type == "legal_reference"
        and len(query.split()) > 3
    ):
        return QueryClassification(
            query_type="legal_reference",
            confidence=max(classification.confidence, base_conf),
            source=classification.source,
            used_llm_fallback=classification.used_llm_fallback,
            facets=classification.facets,
            gabi_intent=gabi_intent,
        )
    if caf_type == "exploratory" and classification.confidence > base_conf:
        return QueryClassification(
            query_type=classification.query_type,
            confidence=max(classification.confidence, base_conf),
            source=classification.source,
            used_llm_fallback=classification.used_llm_fallback,
            facets=classification.facets,
            gabi_intent=gabi_intent,
        )
    return QueryClassification(
        query_type=caf_type,
        confidence=max(classification.confidence, base_conf),
        source=classification.source,
        used_llm_fallback=classification.used_llm_fallback,
        facets=classification.facets,
        gabi_intent=gabi_intent,
    )


def _regex_classification(query: str) -> QueryClassification:
    lowered = query.casefold()
    facets = _detect_facets(query)
    if not query:
        return QueryClassification(
            query_type="exploratory", confidence=0.6, facets=facets
        )
    if _DECRETO_NUM_SHORT_REF.match(query):
        return QueryClassification(
            query_type="legal_reference", confidence=0.9, facets=facets
        )
    if _contains_token(lowered, _AGGREGATION_TOKENS):
        return QueryClassification(
            query_type="aggregation", confidence=0.9, facets=facets
        )
    if _contains_token(lowered, _SUMMARY_TOKENS):
        return QueryClassification(query_type="summary", confidence=0.9, facets=facets)
    if _contains_token(lowered, _EVIDENTIAL_TOKENS):
        return QueryClassification(
            query_type="evidential", confidence=0.9, facets=facets
        )
    if _LEI_NUM_SOBRE_RE.search(query):
        return QueryClassification(
            query_type="legal_reference", confidence=0.9, facets=facets
        )
    if EXACT_REF_RE.search(query) or any(
        t in lowered.split()[:3] for t in _EXACT_MATCH_TOKENS if t in lowered
    ):
        if _contains_token(lowered, _AGGREGATION_TOKENS):
            return QueryClassification(
                query_type="aggregation", confidence=0.9, facets=facets
            )
        return QueryClassification(
            query_type="exact_match", confidence=0.95, facets=facets
        )
    if _contains_token(lowered, _LEGAL_TOKENS):
        return QueryClassification(
            query_type="legal_reference", confidence=0.9, facets=facets
        )
    if _contains_token(lowered, _ACCOUNTABILITY_TOKENS):
        return QueryClassification(
            query_type="accountability", confidence=0.88, facets=facets
        )
    if _contains_token(lowered, _RECOMMENDATION_TOKENS):
        return QueryClassification(
            query_type="recommendation", confidence=0.88, facets=facets
        )
    if _contains_token(lowered, _FACTUAL_TOKENS):
        return QueryClassification(query_type="factual", confidence=0.85, facets=facets)
    return QueryClassification(query_type="exploratory", confidence=0.6, facets=facets)


@lru_cache(maxsize=1)
def get_query_classifier() -> "AdaptiveQueryClassifier":
    return AdaptiveQueryClassifier()


def classify_query(
    query: str,
    *,
    gabi_intent_result: Optional[Any] = None,
    llm_provider: Optional[Any] = None,
) -> QueryClassification:
    from src.backend.search.intent import classify_intent as gabi_classify_intent

    if not query:
        return QueryClassification(query_type="exploratory", confidence=0.6)
    query = query[:200]
    gabi_result = (
        gabi_classify_intent(query)
        if gabi_intent_result is None
        else gabi_intent_result
    )
    caf_class = _regex_classification(query)
    caf_class = gabi_intent_to_query_type(gabi_result.intent, caf_class, query=query)
    if _AGGREGATION_TOKENS & set(re.findall(r"\b[\w-]+\b", query.casefold())):
        caf_class = QueryClassification(
            query_type="aggregation",
            confidence=0.9,
            source=caf_class.source,
            used_llm_fallback=caf_class.used_llm_fallback,
            facets=caf_class.facets,
            gabi_intent=caf_class.gabi_intent,
        )
    return caf_class


def assess_query_risk(
    query: str,
    classification: QueryClassification,
    *,
    result_count: Optional[int] = None,
    conflict: Optional[bool] = None,
    score_margin: Optional[float] = None,
    corpus_stale: bool = False,
) -> RiskAssessment:
    flags: list[str] = []
    if "hierarchical" in classification.facets:
        flags.append("hierarchical_query")
    if "subscope" in classification.facets:
        flags.append("subscope_resolution_risk")
    if classification.query_type in {
        "aggregation",
        "summary",
        "evidential",
        "recommendation",
    }:
        flags.append("multi_evidence_required")
    if classification.query_type == "aggregation":
        flags.append("aggregation_precision_risk")
    if classification.query_type == "accountability":
        flags.append("entity_resolution_risk")
    if classification.query_type == "legal_reference":
        flags.append("legal_precision_required")
    if classification.query_type == "recommendation":
        flags.append("recommendation_synthesis_risk")
    if result_count is not None and result_count < 3:
        flags.append("low_context")
    if conflict:
        flags.append("cross_source_conflict")
    if score_margin is not None and score_margin < 0.08:
        flags.append("ranking_ambiguity")
    if corpus_stale:
        flags.append("corpus_stale")
    unique_flags = tuple(dict.fromkeys(flags))
    score = min(sum(RISK_WEIGHTS.get(flag, 0.0) for flag in unique_flags), 1.0)
    return RiskAssessment(
        flags=unique_flags,
        score=round(score, 4),
        safe_mode=score >= 0.5,
    )


class AdaptiveQueryClassifier:
    def __init__(
        self,
        ledger_root: Optional[Path] = None,
        enabled: bool = False,
    ) -> None:
        if ledger_root is None:
            preferred = Path("/data/gabi_dou/answering")
            try:
                preferred.mkdir(parents=True, exist_ok=True)
                ledger_root = preferred
            except OSError:
                ledger_root = Path.home() / ".gabi_dou" / "answering"
        self.ledger_root = Path(ledger_root)
        self.enabled = enabled
        self.ledger_root.mkdir(parents=True, exist_ok=True)
        self._pattern_overrides: dict[str, str] = self._load_patterns()

    def _load_patterns(self) -> dict[str, str]:
        patterns_file = self.ledger_root / "query_patterns.json"
        if not patterns_file.exists():
            return {}
        try:
            payload = json.loads(patterns_file.read_text(encoding="utf-8"))
            patterns = payload.get("patterns", {})
            return {
                pattern.casefold(): label
                for pattern, label in patterns.items()
                if label in QUERY_TYPES
            }
        except Exception:
            return {}

    def _save_patterns(self) -> None:
        payload = {
            "version": 1,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "patterns": dict(sorted(self._pattern_overrides.items())),
        }
        patterns_file = self.ledger_root / "query_patterns.json"
        patterns_file.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def _feedback_rows(self) -> list[dict[str, Any]]:
        feedback_file = self.ledger_root / "query_feedback.jsonl"
        if not feedback_file.exists():
            return []
        rows = []
        for line in feedback_file.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
        return rows

    def _match_override(self, query: str) -> Optional[QueryClassification]:
        if not self.enabled:
            return None
        lowered = query.casefold()
        for pattern, label in sorted(
            self._pattern_overrides.items(), key=lambda item: (-len(item[0]), item[0])
        ):
            if pattern in lowered:
                return QueryClassification(
                    query_type=label,
                    confidence=0.95,
                    source="learned_pattern",
                    facets=_detect_facets(query),
                )
        return None

    def register_feedback(
        self,
        *,
        query: str,
        predicted: str,
        correct: str,
        confidence: float,
        source: str,
    ) -> dict[str, str]:
        if correct not in QUERY_TYPES:
            raise ValueError(f"Unsupported query type: {correct}")
        if predicted not in QUERY_TYPES:
            raise ValueError(f"Unsupported query type: {predicted}")
        row = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "query": query,
            "predicted": predicted,
            "correct": correct,
            "confidence": confidence,
            "source": source,
        }
        feedback_file = self.ledger_root / "query_feedback.jsonl"
        with feedback_file.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        return self.learn()

    def learn(self) -> dict[str, str]:
        if not self.enabled:
            return {}
        rows = self._feedback_rows()
        support: dict[str, dict[str, int]] = {}
        TOKEN_RE = re.compile(r"\b[\w-]+\b", re.UNICODE)
        STOPWORDS = frozenset(
            {"da", "de", "do", "das", "dos", "e", "lei", "decreto", "para", "sobre"}
        )
        for row in rows:
            predicted = row.get("predicted")
            correct = row.get("correct")
            query_text = row.get("query", "")
            if predicted == correct or correct not in QUERY_TYPES:
                continue
            tokens = {
                token.casefold()
                for token in TOKEN_RE.findall(query_text)
                if len(token) >= 4
                and not token.isdigit()
                and token.casefold() not in STOPWORDS
            }
            for token in tokens:
                if token not in support:
                    support[token] = {}
                support[token][correct] = support[token].get(correct, 0) + 1
        learned_patterns: dict[str, str] = {}
        for token, counts in support.items():
            label, count = max(counts.items(), key=lambda item: item[1])
            if count >= 3:
                learned_patterns[token] = label
        self._pattern_overrides = learned_patterns
        self._save_patterns()
        return learned_patterns

    def learn_scoring(self) -> dict[str, Any]:
        from src.backend.answering.feedback import iter_scoring_feedback

        counts: dict[str, dict[str, int]] = defaultdict(
            lambda: {"correct": 0, "partial": 0, "incorrect": 0, "total": 0}
        )
        feedback_file = self.ledger_root / "scoring_feedback.jsonl"
        for row in iter_scoring_feedback(feedback_path=feedback_file):
            raw_score = row.get("score")
            if raw_score is None and "success" in row:
                raw_score = "correct" if row.get("success") else "incorrect"
            if raw_score not in ("correct", "partial", "incorrect"):
                continue
            qt = str(row.get("query_type") or "unknown")
            bucket = counts[qt]
            bucket[str(raw_score)] += 1
            bucket["total"] += 1

        by_query_type: dict[str, Any] = {}
        for qt, bucket in sorted(counts.items()):
            total = bucket["total"]
            success_rate = (
                (bucket["correct"] + bucket["partial"] * 0.5) / total if total else 0.0
            )
            by_query_type[qt] = {
                "correct": bucket["correct"],
                "partial": bucket["partial"],
                "incorrect": bucket["incorrect"],
                "total": total,
                "success_rate": round(success_rate, 4),
            }

        summary: dict[str, Any] = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "by_query_type": by_query_type,
        }
        out_path = self.ledger_root / "scoring_stats.json"
        out_path.write_text(
            json.dumps(summary, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return summary

    def patterns(self) -> dict[str, str]:
        return dict(sorted(self._pattern_overrides.items()))

    def feedback_history(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self._feedback_rows()
        return rows[-limit:]


def register_feedback(
    *,
    query: str,
    predicted: str,
    correct: str,
    confidence: float,
    source: str,
) -> dict[str, str]:
    return get_query_classifier().register_feedback(
        query=query,
        predicted=predicted,
        correct=correct,
        confidence=confidence,
        source=source,
    )
