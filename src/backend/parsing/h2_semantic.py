from __future__ import annotations

import html
import re
import unicodedata
from typing import Any

from pydantic import BaseModel, Field, ValidationError, field_validator


class TagSpan(BaseModel):
    tag: str = Field(min_length=1, max_length=64)
    start_char: int = Field(ge=0)
    end_char: int = Field(ge=1)
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)

    @field_validator("tag")
    @classmethod
    def _normalize_tag(cls, value: str) -> str:
        return canonicalize_tag(value)

    @field_validator("end_char")
    @classmethod
    def _end_gt_start(cls, value: int, info: Any) -> int:
        start = info.data.get("start_char")
        if start is not None and value <= start:
            raise ValueError("end_char must be greater than start_char")
        return value


def parse_spans(payload: list[dict[str, Any]]) -> list[TagSpan]:
    try:
        spans = [TagSpan.model_validate(item) for item in payload]
    except ValidationError as exc:
        raise ValueError(str(exc)) from exc
    return sorted(spans, key=lambda x: (x.start_char, x.end_char, x.tag))


TAG_MAP: dict[str, str] = {
    "licitacao": "licitacao",
    "licitações": "licitacao",
    "licitacoes": "licitacao",
    "processo_licitatorio": "licitacao",
    "processo_licitatório": "licitacao",
    "fundamentacao_legal": "base_legal",
    "fundamentacao": "fundamentacao",
    "decisao": "decisao",
    "decisão": "decisao",
    "texto_acordao": "texto_acordao",
    "texto_acórdão": "texto_acordao",
}


def canonicalize_tag(value: str) -> str:
    raw = value.strip().lower()
    raw = unicodedata.normalize("NFKD", raw)
    raw = "".join(ch for ch in raw if not unicodedata.combining(ch))
    raw = re.sub(r"[^a-z0-9_]+", "_", raw).strip("_")
    return TAG_MAP.get(raw, raw)


def validate_spans(text: str, spans: list[TagSpan], allowed_tags: tuple[str, ...]) -> None:
    allowed = {x.lower() for x in allowed_tags}
    text_len = len(text)
    previous_end = 0
    for span in spans:
        if span.tag not in allowed:
            raise ValueError(f"tag not allowed for source: {span.tag}")
        if span.end_char > text_len:
            raise ValueError(f"span out of bounds: {span.start_char}:{span.end_char} > {text_len}")
        if span.start_char < previous_end:
            raise ValueError("overlapping spans are not allowed")
        previous_end = span.end_char


def tags_flat(spans: list[TagSpan]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for span in spans:
        if span.tag not in seen:
            seen.add(span.tag)
            out.append(span.tag)
    return out


def render_tagged_xml(text: str, spans: list[TagSpan]) -> str:
    if not spans:
        return ""
    parts: list[str] = []
    for span in spans:
        raw = text[span.start_char:span.end_char]
        if not raw.strip():
            continue
        tag = re.sub(r"[^a-z0-9_]+", "_", span.tag.lower())
        parts.append(f"<{tag}>{html.escape(raw)}</{tag}>")
    return "\n".join(parts)
