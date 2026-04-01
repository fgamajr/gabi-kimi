from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class AnswerRequest(BaseModel):
    query: str = Field(..., min_length=3, max_length=500)
    date_from: str | None = None
    date_to: str | None = None
    section: str | None = None
    source: str | None = None
    intent_override: str | None = None
    stream: bool = False


class Citation(BaseModel):
    doc_id: str
    snippet: str
    url: str
    organ: str | None = None
    pub_date: str | None = None
    art_type: str | None = None


class RiskSummary(BaseModel):
    score: float
    flags: list[str]
    safe_mode: bool


class SourceFreshnessSummary(BaseModel):
    name: str
    stale: bool
    gap_hours: float | None = None


class CorpusFreshnessSummary(BaseModel):
    any_stale: bool
    sources: list[SourceFreshnessSummary]
    disclaimer: str | None = None


class AnswerResponse(BaseModel):
    query_id: str
    query: str
    answer: str
    citations: list[Citation]
    confidence: float
    risk: RiskSummary
    corpus_freshness: CorpusFreshnessSummary
    query_type: str
    fallback: bool = False
    fallback_reason: str | None = None
    latency_ms: int | None = None
    model: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class AnswerTrace(BaseModel):
    query_id: str
    query: str
    query_type: str
    risk_score: float
    risk_flags: list[str]
    evidence_doc_ids: list[str]
    answer_text: str
    citations_extracted: int
    hallucinated_citations_removed: int
    model: str
    latency_ms: int
    corpus_freshness: dict[str, Any]
    created_at: datetime
    trace_detail: dict[str, Any] | None = None
