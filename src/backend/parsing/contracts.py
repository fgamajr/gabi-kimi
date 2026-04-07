from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Protocol

EnrichmentStatus = Literal["pending", "running", "done_full", "done_partial", "done_fallback", "failed", "skipped"]
EnrichmentMode = Literal["llm", "heuristic", "fallback"] | None


@dataclass(frozen=True)
class H1ClassificationResult:
    tipo: str | None
    subtipo: str | None
    confidence: float
    method: str
    version: str
    status: str


@dataclass(frozen=True)
class ParsedDocument:
    raw_id: str
    source_type: str
    parser_version: str
    content_hash: str
    structured_fields: dict[str, Any]
    sections: dict[str, str] = field(default_factory=dict)
    body_tagged_xml: str = ""
    section_map: dict[str, Any] = field(default_factory=dict)
    h1: H1ClassificationResult | None = None
    parsed_at: datetime = field(default_factory=datetime.utcnow)


@dataclass(frozen=True)
class EnrichmentPayload:
    raw_id: str
    source_type: str
    text: str
    allowed_tags: tuple[str, ...]
    prompt_version: str
    h2_version: str


@dataclass(frozen=True)
class EnrichmentResult:
    enrichment_status: EnrichmentStatus
    enrichment_mode: EnrichmentMode
    h2_version: str
    prompt_version: str
    tag_spans: list[dict[str, Any]]
    tags_flat: list[str]
    body_tagged_xml: str
    summary_short: str | None
    summary_long: str | None
    summary_structured: dict[str, Any] | None
    legal_entities: list[dict[str, Any]] | None
    topics: list[str] | None
    confidence_fields: dict[str, float] | None
    chunk_summaries: list[dict[str, Any]] | None
    enrichment_input_hash: str
    error: str | None = None


class SourceParser(Protocol):
    source_type: str
    parser_version: str

    def parse(self, raw_id: str, raw_data: dict[str, Any]) -> ParsedDocument: ...

    def extract_tags(self, text: str, raw_data: dict[str, Any]) -> dict[str, str]: ...

    def build_enrichment_prompt(
        self,
        parsed: ParsedDocument,
        prompt_version: str,
    ) -> str: ...
