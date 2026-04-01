from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx

from src.backend.answering.aggregation import build_aggregation_summary
from src.backend.answering.citations import extract_and_validate_citations
from src.backend.answering.classifier import assess_query_risk, classify_query
from src.backend.answering.freshness import CorpusFreshness, check_corpus_freshness
from src.backend.answering.ledger import append_trace
from src.backend.answering.models import (
    AnswerRequest,
    AnswerResponse,
    AnswerTrace,
    CorpusFreshnessSummary,
    RiskSummary,
    SourceFreshnessSummary,
)
from src.backend.answering.prompts import SYSTEM_PROMPT, build_user_prompt
from src.backend.answering.trace_builder import build_chunk_traces
from src.backend.core.config import settings
from src.backend.search.reranker import rerank

logger = logging.getLogger(__name__)

_SECTION_LABELS = {
    "do1": "DOU Seção 1 (Atos Normativos)",
    "do2": "DOU Seção 2 (Atos de Pessoal)",
    "do3": "DOU Seção 3 (Contratos/Extratos)",
    "do_e": "DOU Seção Extra",
    "tcu": "TCU — Jurisprudência",
    "btcu": "TCU — Boletim",
    "publicacoes": "TCU — Publicações",
    "normas": "TCU — Normas",
}

_EVIDENCE_FIELDS = [
    "_id",
    "title",
    "ementa",
    "body_plain",
    "issuing_organ",
    "organ",
    "pub_date",
    "data_sessao",
    "art_type",
    "tipo_processo",
    "section",
    "relator",
]

_FALLBACK_REASON_LLM_UNAVAILABLE = "LLM indisponível — exibindo resultados da busca"
_FALLBACK_REASON_DISABLED = "RAG desabilitado neste ambiente"


def _evidence_limit_for_query_type(query_type: str, *, safe_mode: bool) -> int:
    base = settings.RAG_MAX_EVIDENCE_CHUNKS
    if query_type in ("aggregation", "summary"):
        limit = min(30, base + 13)
    elif query_type in ("exact_match", "legal_reference"):
        limit = max(8, min(base, 12))
    else:
        limit = base
    if safe_mode:
        limit = min(30, limit + 8)
    return limit


def _freshness_to_summary(freshness: CorpusFreshness) -> CorpusFreshnessSummary:
    return CorpusFreshnessSummary(
        any_stale=freshness.any_stale,
        sources=[
            SourceFreshnessSummary(
                name=s.name,
                stale=s.stale,
                gap_hours=s.gap_hours,
            )
            for s in freshness.sources
        ],
        disclaimer=freshness.disclaimer(),
    )


async def _fetch_evidence(
    query: str,
    client: httpx.AsyncClient,
    *,
    filters: list[dict[str, Any]],
    size: int,
    source: str | None,
    intent: str | None,
) -> list[dict[str, Any]]:
    from src.backend.search.hybrid import hybrid_search

    highlight_spec: dict[str, Any] = {}
    result = await hybrid_search(
        query=query,
        filters=filters,
        size=size,
        from_=0,
        source_fields=_EVIDENCE_FIELDS,
        highlight_spec=highlight_spec,
        client=client,
        intent=intent,
    )
    hits = result.get("hits", {}).get("hits", [])
    return hits


def _build_evidence_text(docs: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for doc in docs:
        doc_id = doc.get("_id") or doc.get("id") or ""
        source = doc.get("_source", doc)
        title = source.get("title") or source.get("ementa") or "(sem título)"
        body = source.get("body_plain") or ""
        organ = source.get("issuing_organ") or source.get("organ") or ""
        pub_date = source.get("pub_date") or source.get("data_sessao") or ""
        section_raw = source.get("section") or ""
        section_label = _SECTION_LABELS.get(section_raw, section_raw or "Desconhecida")
        art_type = source.get("art_type") or source.get("tipo_processo") or ""
        chunk = (
            f"[{doc_id}] {title}\n"
            f"Fonte: {section_label} | Tipo: {art_type} | Órgão: {organ} | Data: {pub_date}\n"
            f"{body[:2000]}"
        )
        parts.append(chunk)
    return "\n\n---\n\n".join(parts)


async def _call_claude(
    system: str,
    user: str,
    client: httpx.AsyncClient,
) -> str | None:
    api_key = settings.ANTHROPIC_API_KEY
    if not api_key:
        logger.warning("ANTHROPIC_API_KEY not set")
        return None
    try:
        resp = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": settings.RAG_MODEL,
                "max_tokens": 2048,
                "temperature": 0.2,
                "system": system,
                "messages": [{"role": "user", "content": user}],
            },
            timeout=settings.RAG_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("content", [{}])[0].get("text", "")
    except Exception as exc:
        logger.warning("Claude API call failed: %s", exc)
        return None


async def generate_answer(
    request: AnswerRequest,
) -> AnswerResponse:
    if not settings.RAG_ENABLED:
        return AnswerResponse(
            query_id=str(uuid.uuid4()),
            query=request.query,
            answer="",
            citations=[],
            confidence=0.0,
            risk=RiskSummary(score=0.0, flags=[], safe_mode=False),
            corpus_freshness=CorpusFreshnessSummary(any_stale=False, sources=[]),
            query_type="unknown",
            fallback=True,
            fallback_reason=_FALLBACK_REASON_DISABLED,
        )

    start_ms = int(time.monotonic() * 1000)
    query_id = str(uuid.uuid4())

    http_timeout = 60.0 if settings.RERANKER_ENABLED else 15.0
    async with httpx.AsyncClient(timeout=http_timeout) as client:
        freshness = await check_corpus_freshness(client)

        classification = classify_query(request.query)
        intent_str = (
            classification.gabi_intent.value
            if classification.gabi_intent is not None
            else None
        )

        filters: list[dict[str, Any]] = []
        if request.date_from:
            filters.append({"range": {"pub_date": {"gte": request.date_from}}})
        if request.date_to:
            filters.append({"range": {"pub_date": {"lte": request.date_to}}})
        if request.section:
            filters.append({"term": {"section": request.section}})

        risk_pre = assess_query_risk(
            request.query,
            classification,
            corpus_stale=freshness.any_stale,
        )

        prior_limit = _evidence_limit_for_query_type(
            classification.query_type,
            safe_mode=risk_pre.safe_mode,
        )
        fetch_extra = (
            15 if settings.RERANKER_ENABLED else (10 if risk_pre.safe_mode else 8)
        )
        fetch_size = prior_limit + fetch_extra
        if settings.RERANKER_ENABLED:
            fetch_size = min(settings.RERANKER_MAX_DOCS, fetch_size + 10)

        docs = await _fetch_evidence(
            query=request.query,
            client=client,
            filters=filters,
            size=fetch_size,
            source=request.source,
            intent=request.intent_override or intent_str,
        )

        if settings.RERANKER_ENABLED:
            docs = await rerank(
                request.query,
                docs,
                top_k=min(len(docs), fetch_size),
                client=client,
            )

        risk = assess_query_risk(
            request.query,
            classification,
            result_count=len(docs),
            corpus_stale=freshness.any_stale,
        )

        freshness_summary = _freshness_to_summary(freshness)
        risk_summary = RiskSummary(
            score=risk.score,
            flags=list(risk.flags),
            safe_mode=risk.safe_mode,
        )

        evidence_limit = _evidence_limit_for_query_type(
            classification.query_type,
            safe_mode=risk.safe_mode,
        )
        docs_for_llm = docs[:evidence_limit]

        evidence_text = _build_evidence_text(docs_for_llm)

        if len(evidence_text) > settings.RAG_MAX_CONTEXT_CHARS:
            evidence_text = evidence_text[: settings.RAG_MAX_CONTEXT_CHARS]

        user_prompt = build_user_prompt(
            query=request.query,
            evidence_text=evidence_text,
            query_type=classification.query_type,
            safe_mode=risk.safe_mode,
        )

        llm_response = await _call_claude(SYSTEM_PROMPT, user_prompt, client)

    latency_ms = int(time.monotonic() * 1000) - start_ms

    if llm_response is None:
        fallback_answer = _build_fallback_answer(docs_for_llm)
        response = AnswerResponse(
            query_id=query_id,
            query=request.query,
            answer=fallback_answer,
            citations=[],
            confidence=0.0,
            risk=risk_summary,
            corpus_freshness=freshness_summary,
            query_type=classification.query_type,
            fallback=True,
            fallback_reason=_FALLBACK_REASON_LLM_UNAVAILABLE,
            latency_ms=latency_ms,
        )
        return response

    citations, hallucinated = extract_and_validate_citations(llm_response, docs_for_llm)
    confidence = _compute_confidence(classification, risk, len(citations))

    trace_detail = build_chunk_traces(
        docs_for_llm,
        safe_mode=risk.safe_mode,
        query_type=classification.query_type,
    )

    aggregation: dict[str, Any] | None = None
    if classification.query_type == "aggregation":
        aggregation = build_aggregation_summary(docs, request.query)

    if aggregation:
        agg_note = (
            f"\n\n**Dados estruturados**: {aggregation['total_after_dedup']} documentos "
            f"(após deduplicação de {aggregation['total_retrieved']} recuperados). "
            f"{aggregation['note']}"
        )
        llm_response = llm_response + agg_note

    trace = AnswerTrace(
        query_id=query_id,
        query=request.query,
        query_type=classification.query_type,
        risk_score=risk.score,
        risk_flags=list(risk.flags),
        evidence_doc_ids=[str(d.get("_id") or d.get("id") or "") for d in docs_for_llm],
        answer_text=llm_response,
        citations_extracted=len(citations),
        hallucinated_citations_removed=hallucinated,
        model=settings.RAG_MODEL,
        latency_ms=latency_ms,
        corpus_freshness=freshness_summary.model_dump(),
        created_at=datetime.now(timezone.utc),
        trace_detail=trace_detail.to_dict(),
    )
    append_trace(trace)

    return AnswerResponse(
        query_id=query_id,
        query=request.query,
        answer=llm_response,
        citations=citations,
        confidence=confidence,
        risk=risk_summary,
        corpus_freshness=freshness_summary,
        query_type=classification.query_type,
        fallback=False,
        latency_ms=latency_ms,
        model=settings.RAG_MODEL,
    )


def _build_fallback_answer(docs: list[dict[str, Any]]) -> str:
    if not docs:
        return "Nenhum documento relevante encontrado para esta consulta."
    lines = ["Documentos mais relevantes encontrados:\n"]
    for doc in docs[:5]:
        doc_id = doc.get("_id") or ""
        source = doc.get("_source", doc)
        title = source.get("title") or source.get("ementa") or "(sem título)"
        organ = source.get("issuing_organ") or source.get("organ") or ""
        pub_date = source.get("pub_date") or source.get("data_sessao") or ""
        lines.append(f"- [{doc_id}] {title} | {organ} | {pub_date}")
    return "\n".join(lines)


def _compute_confidence(
    classification: Any,
    risk: Any,
    citation_count: int,
) -> float:
    base = classification.confidence * 0.5
    risk_penalty = risk.score * 0.3
    citation_bonus = min(citation_count * 0.05, 0.2)
    return round(max(0.0, min(1.0, base - risk_penalty + citation_bonus)), 3)
