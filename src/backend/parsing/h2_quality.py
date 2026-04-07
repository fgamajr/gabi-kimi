from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.backend.parsing.h2_semantic import TagSpan, parse_spans, tags_flat, validate_spans


@dataclass(frozen=True)
class SemanticQualityReport:
    valid_schema: bool
    valid_spans: bool
    allowed_tags_only: bool
    non_overlapping: bool
    coverage_ratio: float
    summary_present: bool
    topics_present: bool
    score: float
    issues: tuple[str, ...]


def evaluate_h2_output(
    *,
    text: str,
    allowed_tags: tuple[str, ...],
    output: dict[str, Any],
    min_coverage_ratio: float = 0.05,
) -> SemanticQualityReport:
    issues: list[str] = []
    spans: list[TagSpan] = []
    valid_schema = True
    valid_spans = True
    allowed_tags_only = True
    non_overlapping = True

    try:
        spans = parse_spans(output.get("tag_spans", []))
    except Exception as exc:
        valid_schema = False
        valid_spans = False
        issues.append(f"schema_error:{exc}")
        spans = []

    if spans:
        try:
            validate_spans(text=text, spans=spans, allowed_tags=allowed_tags)
        except Exception as exc:
            valid_spans = False
            msg = str(exc)
            issues.append(f"span_error:{msg}")
            if "not allowed" in msg:
                allowed_tags_only = False
            if "overlapping" in msg:
                non_overlapping = False

    covered = sum(max(0, span.end_char - span.start_char) for span in spans)
    text_len = max(1, len(text))
    coverage_ratio = min(1.0, covered / text_len)
    if coverage_ratio < min_coverage_ratio:
        issues.append(f"low_coverage:{coverage_ratio:.4f}")

    summary_short = (output.get("summary_short") or "").strip()
    summary_long = (output.get("summary_long") or "").strip()
    summary_structured = output.get("summary_structured")
    summary_present = bool(summary_short or summary_long or summary_structured)
    if not summary_present:
        issues.append("missing_summary")

    topics = output.get("topics") or []
    topics_present = isinstance(topics, list) and len(topics) > 0
    if not topics_present:
        issues.append("missing_topics")

    unique_tags = tags_flat(spans)
    useful_tags = [tag for tag in unique_tags if tag != "assinatura"]
    if not unique_tags:
        issues.append("missing_tags")
    if unique_tags and not useful_tags:
        issues.append("signature_only")

    score = 0.0
    if valid_schema:
        score += 0.25
    if valid_spans:
        score += 0.25
    if coverage_ratio >= min_coverage_ratio:
        score += 0.2
    if summary_present:
        score += 0.15
    if topics_present:
        score += 0.1
    if useful_tags:
        score += 0.05
    if unique_tags and not useful_tags:
        score = min(score, 0.55)

    return SemanticQualityReport(
        valid_schema=valid_schema,
        valid_spans=valid_spans,
        allowed_tags_only=allowed_tags_only,
        non_overlapping=non_overlapping,
        coverage_ratio=round(coverage_ratio, 6),
        summary_present=summary_present,
        topics_present=topics_present,
        score=round(score, 4),
        issues=tuple(issues),
    )
