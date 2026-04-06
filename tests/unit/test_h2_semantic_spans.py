from __future__ import annotations

import pytest

from src.backend.parsing.h2_semantic import parse_spans, render_tagged_xml, validate_spans


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
