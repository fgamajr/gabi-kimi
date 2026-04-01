from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from typing import Any

from src.backend.repo_index.config import settings
from src.backend.repo_index.embeddings import get_embedding_provider
from src.backend.repo_index.retrieval.scoring import get_scoring_policy
from src.backend.repo_index.storage.db import get_connection

STACK_TRACE_RE = re.compile(
    r"(traceback \(most recent call last\):|exception in thread|^\s*file \".*\", line \d+, in |\bat\s+\S+\([^)]*:\d+\))",
    re.IGNORECASE | re.MULTILINE,
)
HARD_FILTER_MARKERS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("debug_marker", re.compile(r"\b(?:bug:|debug:)\b", re.IGNORECASE)),
    ("stack_trace", STACK_TRACE_RE),
    (
        "generated_file",
        re.compile(
            r"\bgenerated\s+by\b|\bauto-generated\b|\bdo not edit\b", re.IGNORECASE
        ),
    ),
)


@dataclass(frozen=True)
class SearchHit:
    chunk_id: str
    doc_id: str
    path: str
    symbol: str | None
    start_line: int
    end_line: int
    content: str
    score: float
    score_breakdown: dict[str, Any]
    reasons: list[str]


@dataclass(frozen=True)
class QueryContext:
    query_type: str
    has_exact_match: bool
    exact_term: str | None
    preferred_section_types: tuple[str, ...]
    candidate_limit: int
    safe_mode: bool


def _classify_query(query: str, top_k: int) -> QueryContext:
    lowered = query.casefold()
    exact_match = re.search(r'"([^"]+)"', query)
    symbol_match = re.search(r"\b([A-Za-z_][A-Za-z0-9_]*)\b", query)
    exact_term = None
    if exact_match:
        exact_term = exact_match.group(1)
    elif symbol_match:
        exact_term = symbol_match.group(1)

    query_type = "factual"
    preferred_section_types: tuple[str, ...] = ()
    candidate_limit = max(top_k * 4, 20)

    if any(token in lowered for token in ["how", "como", "funciona", "works"]):
        query_type = "summary"
        preferred_section_types = ("class", "function", "markdown_section")
        candidate_limit = max(candidate_limit, 40)
    elif any(
        token in lowered for token in ["where", "onde", "find", "achar", "localizar"]
    ):
        query_type = "evidential"
        preferred_section_types = ("symbol", "function", "class")
        candidate_limit = max(candidate_limit, 40)
    elif any(token in lowered for token in ["list", "lista", "all", "todos", "todas"]):
        query_type = "aggregation"
        preferred_section_types = ("symbol", "class", "function", "config")
        candidate_limit = max(candidate_limit, 50)
    elif exact_term:
        query_type = "exact_match"
        preferred_section_types = ("symbol", "class", "function")
        candidate_limit = max(candidate_limit, 30)

    safe_mode = "?" in query or "não sei" in lowered or "not sure" in lowered
    if safe_mode:
        candidate_limit = max(candidate_limit, top_k + 20)

    return QueryContext(
        query_type=query_type,
        has_exact_match=exact_term is not None,
        exact_term=exact_term,
        preferred_section_types=preferred_section_types,
        candidate_limit=candidate_limit,
        safe_mode=safe_mode,
    )


def _normalize_fts_query(query: str) -> str:
    tokens = re.findall(r"[A-Za-z0-9_./:-]+", query)
    if not tokens:
        raise ValueError("Query must contain at least one searchable token")
    return " ".join(
        f'"{token.replace('"', " ").strip()}"' for token in tokens if token.strip()
    )


def _lexical_results(conn, query: str, limit: int) -> list[dict[str, Any]]:
    fts_query = _normalize_fts_query(query)
    rows = conn.execute(
        """
        SELECT
            c.id,
            c.chunk_id,
            c.doc_id,
            c.path,
            c.symbol,
            c.start_line,
            c.end_line,
            c.text,
            c.source_type,
            c.authority_weight,
            c.section_type,
            c.entity_density,
            c.importance_score,
            bm25(chunks_fts, 1.2, 0.5, 1.0) AS score
        FROM chunks_fts
        JOIN chunks AS c ON c.id = chunks_fts.rowid
        WHERE chunks_fts MATCH ?
        ORDER BY score
        LIMIT ?
        """,
        (fts_query, limit),
    ).fetchall()
    return [
        {
            "chunk_id": row["chunk_id"],
            "doc_id": row["doc_id"],
            "path": row["path"],
            "symbol": row["symbol"],
            "start_line": row["start_line"],
            "end_line": row["end_line"],
            "content": row["text"],
            "score": float(row["score"]),
            "source_type": row["source_type"],
            "authority_weight": row["authority_weight"],
            "section_type": row["section_type"],
            "entity_density": row["entity_density"],
            "importance_score": row["importance_score"],
        }
        for row in rows
    ]


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def _semantic_results(conn, query: str, limit: int, provider) -> list[dict[str, Any]]:
    query_vector = provider.embed([query])[0]
    dims = settings.embedding_dims or len(query_vector)
    rows = conn.execute(
        """
        SELECT
            c.id,
            c.chunk_id,
            c.doc_id,
            c.path,
            c.symbol,
            c.start_line,
            c.end_line,
            c.text,
            c.source_type,
            c.authority_weight,
            c.section_type,
            c.entity_density,
            c.importance_score,
            e.vector_json
        FROM chunks AS c
        JOIN embeddings AS e ON e.chunk_id = c.chunk_id
        WHERE e.provider = ? AND e.model = ? AND e.dims = ?
        """,
        (settings.embedding_provider, settings.embedding_model, dims),
    ).fetchall()
    scored: list[dict[str, Any]] = []
    for row in rows:
        similarity = _cosine_similarity(query_vector, json.loads(row["vector_json"]))
        scored.append(
            {
                "chunk_id": row["chunk_id"],
                "doc_id": row["doc_id"],
                "path": row["path"],
                "symbol": row["symbol"],
                "start_line": row["start_line"],
                "end_line": row["end_line"],
                "content": row["text"],
                "score": similarity,
                "source_type": row["source_type"],
                "authority_weight": row["authority_weight"],
                "section_type": row["section_type"],
                "entity_density": row["entity_density"],
                "importance_score": row["importance_score"],
            }
        )
    scored.sort(key=lambda item: item["score"], reverse=True)
    return scored[:limit]


def _rrf_fuse(
    result_sets: list[list[dict[str, Any]]], limit: int
) -> list[dict[str, Any]]:
    rank_scores: dict[str, float] = {}
    rows_by_id: dict[str, dict[str, Any]] = {}
    for results in result_sets:
        for rank, row in enumerate(results, start=1):
            chunk_id = row["chunk_id"]
            rank_scores[chunk_id] = rank_scores.get(chunk_id, 0.0) + 1.0 / (60 + rank)
            rows_by_id.setdefault(chunk_id, row)
    fused = []
    for chunk_id, score in sorted(
        rank_scores.items(), key=lambda item: item[1], reverse=True
    ):
        row = dict(rows_by_id[chunk_id])
        row["score"] = score
        fused.append(row)
    return fused[:limit]


def _hard_filter_reasons(row: dict[str, Any]) -> list[str]:
    haystack = "\n".join(
        part for part in [row["content"], row["path"], row.get("symbol") or ""] if part
    )
    return [label for label, pattern in HARD_FILTER_MARKERS if pattern.search(haystack)]


def _policy_adjustments(
    row: dict[str, Any],
    query_context: QueryContext,
) -> tuple[float, list[str]]:
    score = 1.0
    reasons: list[str] = []
    section_type = (row.get("section_type") or "body").lower()
    source_type = (row.get("source_type") or "unknown").lower()

    if section_type in {"imports", "boilerplate"}:
        score *= 0.85
        reasons.append(f"penalized: {section_type}")
    if section_type == "config" and query_context.query_type != "exact_match":
        score *= 0.9
        reasons.append("penalized: config_section")
    if source_type in {"tests"} and query_context.query_type not in {
        "exact_match",
        "evidential",
    }:
        score *= 0.9
        reasons.append("penalized: test_source")
    if section_type in {"class", "function", "symbol"}:
        score *= 1.10
        reasons.append(f"boosted: {section_type}")
    if (
        query_context.preferred_section_types
        and section_type in query_context.preferred_section_types
    ):
        score *= 1.15
        reasons.append(f"boosted: preferred_section {section_type}")
    if query_context.has_exact_match and query_context.exact_term:
        exact = query_context.exact_term.casefold()
        content = (row["content"] or "").casefold()
        symbol = (row.get("symbol") or "").casefold()
        path = (row["path"] or "").casefold()
        if exact in content or exact in symbol or exact in path:
            score *= 1.20
            reasons.append("boosted: exact_match")
    return score, reasons


class RetrievalService:
    def __init__(self) -> None:
        try:
            self.embedding_provider = get_embedding_provider()
        except Exception:
            self.embedding_provider = None

    def search(
        self,
        query: str,
        top_k: int = 8,
        mode: str = "hybrid",
        explain: bool = False,
    ) -> tuple[list[SearchHit], dict[str, Any]]:
        query_context = _classify_query(query, top_k)
        conn = get_connection()
        lexical = (
            _lexical_results(conn, query, max(query_context.candidate_limit, top_k * 3))
            if mode in {"lexical", "hybrid"}
            else []
        )
        semantic: list[dict[str, Any]] = []
        actual_mode = mode
        if mode in {"semantic", "hybrid"}:
            try:
                has_cache = (
                    conn.execute("SELECT 1 FROM embeddings LIMIT 1").fetchone()
                    is not None
                )
                if has_cache and self.embedding_provider is not None:
                    semantic = _semantic_results(
                        conn,
                        query,
                        max(query_context.candidate_limit, top_k * 3),
                        self.embedding_provider,
                    )
                elif mode == "semantic":
                    raise RuntimeError(
                        "Semantic mode requires embeddings. Run build --with-embeddings first."
                    )
                else:
                    actual_mode = "lexical"
            except RuntimeError:
                if mode == "semantic":
                    raise
                actual_mode = "lexical"

        if actual_mode == "lexical":
            merged = lexical
        elif actual_mode == "semantic":
            merged = semantic
        else:
            merged = _rrf_fuse([lexical, semantic], query_context.candidate_limit)

        scoring_profile = get_scoring_policy().profile_for(query_context.query_type)
        results: list[SearchHit] = []
        retrieval_trace = []
        filtered_trace = []
        scoring_trace = []

        # normalize bm25 and vector scores across merged
        bm25_lookup = {row["chunk_id"]: row["score"] for row in lexical}
        vector_lookup = {row["chunk_id"]: row["score"] for row in semantic}

        def normalize(values: dict[str, float]) -> dict[str, float]:
            if not values:
                return {}
            minimum = min(values.values())
            maximum = max(values.values())
            if maximum == minimum:
                return {key: 1.0 for key in values}
            return {
                key: (value - minimum) / (maximum - minimum)
                for key, value in values.items()
            }

        norm_bm25 = normalize(bm25_lookup)
        norm_vector = normalize(vector_lookup)

        for row in merged:
            hard_reasons = _hard_filter_reasons(row)
            if hard_reasons:
                filtered_trace.append(
                    {
                        "chunk_id": row["chunk_id"],
                        "path": row["path"],
                        "reasons": hard_reasons,
                    }
                )
                continue

            bm25 = norm_bm25.get(row["chunk_id"], 0.0)
            vector = norm_vector.get(row["chunk_id"], 0.0)
            authority = row.get("authority_weight", 0.5)
            entity_density = min(row.get("entity_density", 0.0) * 25, 1.0)
            policy_multiplier, policy_reasons = _policy_adjustments(row, query_context)
            weights = scoring_profile.weights
            final = (
                (vector * weights.get("vector", 0.0))
                + (bm25 * weights.get("bm25", 0.0))
                + (authority * weights.get("authority", 0.0))
                + (entity_density * weights.get("entity", 0.0))
            )
            final *= policy_multiplier

            penalties = [
                reason for reason in policy_reasons if reason.startswith("penalized")
            ]
            boosts = [
                reason for reason in policy_reasons if reason.startswith("boosted")
            ]
            reasons = list(policy_reasons)
            if bm25 >= 0.8:
                reasons.append("alta aderência lexical")
            elif bm25 >= 0.4:
                reasons.append("aderência lexical moderada")
            if vector >= 0.8:
                reasons.append("alta relevância vetorial")
            elif vector >= 0.4:
                reasons.append("relevância vetorial moderada")
            if authority >= 0.9:
                reasons.append("fonte de alta autoridade")
            if entity_density >= 0.5:
                reasons.append("alta densidade de entidades")

            retrieval_trace.append(
                {
                    "chunk_id": row["chunk_id"],
                    "bm25_raw": round(bm25_lookup.get(row["chunk_id"], 0.0), 6),
                    "bm25": round(bm25, 6),
                    "vector_raw": round(vector_lookup.get(row["chunk_id"], 0.0), 6),
                    "vector": round(vector, 6),
                    "filtered": False,
                }
            )
            scoring_trace.append(
                {
                    "chunk_id": row["chunk_id"],
                    "bm25": round(bm25, 6),
                    "vector": round(vector, 6),
                    "authority": round(authority, 6),
                    "entity_density": round(entity_density, 6),
                    "policy_multiplier": round(policy_multiplier, 6),
                    "penalties": penalties,
                    "boosts": boosts,
                    "scoring_profile": scoring_profile.weights,
                    "scoring_profile_source": scoring_profile.source,
                    "final_score": round(final, 6),
                    "reasons": reasons,
                }
            )
            results.append(
                SearchHit(
                    chunk_id=row["chunk_id"],
                    doc_id=row["doc_id"],
                    path=row["path"],
                    symbol=row.get("symbol"),
                    start_line=row["start_line"],
                    end_line=row["end_line"],
                    content=row["content"],
                    score=round(final, 6),
                    score_breakdown={
                        "bm25": round(bm25, 6),
                        "vector": round(vector, 6),
                        "authority": round(authority, 6),
                        "entityDensity": round(entity_density, 6),
                        "policyMultiplier": round(policy_multiplier, 6),
                        "finalScore": round(final, 6),
                        "scoringProfile": scoring_profile.weights,
                        "scoringProfileSource": scoring_profile.source,
                    },
                    reasons=reasons,
                )
            )

        ranked = sorted(results, key=lambda item: item.score, reverse=True)[:top_k]
        trace = {
            "query": query,
            "mode": actual_mode,
            "query_context": {
                "query_type": query_context.query_type,
                "candidate_limit": query_context.candidate_limit,
                "preferred_section_types": list(query_context.preferred_section_types),
                "has_exact_match": query_context.has_exact_match,
                "exact_term": query_context.exact_term,
                "safe_mode": query_context.safe_mode,
            },
            "retrieval": retrieval_trace,
            "filtered_out": filtered_trace,
            "scoring": scoring_trace,
            "final": [
                {
                    "rank": idx,
                    "chunk_id": hit.chunk_id,
                    "path": hit.path,
                    "symbol": hit.symbol,
                    "score": hit.score,
                    "reasons": hit.reasons,
                }
                for idx, hit in enumerate(ranked, start=1)
            ],
        }
        conn.close()
        metadata = {
            "mode": actual_mode,
            "conflict": False,
            "trace": trace if explain else None,
        }
        return ranked, metadata
