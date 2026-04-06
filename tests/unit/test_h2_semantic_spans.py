from __future__ import annotations

import pytest

from src.backend.parsing.h2_semantic import parse_spans, parse_spans_tolerant, render_tagged_xml, validate_spans


def test_validate_spans_ok() -> None:
    text = "abc def ghi"
    spans = parse_spans(
        [
            {"tag": "ementa", "start_char": 0, "end_char": 3, "confidence": 0.9},
            {"tag": "corpo", "start_char": 4, "end_char": 11, "confidence": 0.8},
        ]
    )
    validate_spans(text, spans, allowed_tags=("ementa", "corpo"))


def test_validate_spans_overlap_fails() -> None:
    text = "abcdefghij"
    spans = parse_spans(
        [
            {"tag": "ementa", "start_char": 0, "end_char": 5},
            {"tag": "corpo", "start_char": 4, "end_char": 8},
        ]
    )
    with pytest.raises(ValueError, match="overlapping"):
        validate_spans(text, spans, allowed_tags=("ementa", "corpo"))


def test_render_tagged_xml_deterministic() -> None:
    text = "PORTARIA 123"
    spans = parse_spans([{"tag": "ementa", "start_char": 0, "end_char": 8}])
    xml = render_tagged_xml(text, spans)
    assert xml == "<ementa>PORTARIA</ementa>"


def test_parse_spans_tolerant_accepts_aliases_and_skips_invalid() -> None:
    spans, issues = parse_spans_tolerant(
        [
            {"tag_name": "Ementa", "start": 0, "end": 7, "confidence": 0.8},
            {"section": "corpo", "start_idx": 8, "end_idx": 12},
            {"foo": "bar"},
        ]
    )
    assert len(spans) == 2
    assert spans[0].tag == "ementa"
    assert spans[1].tag == "corpo"
    assert len(issues) == 1
