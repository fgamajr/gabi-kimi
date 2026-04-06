from __future__ import annotations

from src.backend.parsing.h2_quality import evaluate_h2_output


def test_quality_good_output_scores_high() -> None:
    text = "PORTARIA 123. Nomeia servidor. Vigência imediata."
    output = {
        "tag_spans": [
            {"tag": "ementa", "start_char": 0, "end_char": 12, "confidence": 0.9},
            {"tag": "corpo", "start_char": 13, "end_char": len(text), "confidence": 0.9},
        ],
        "summary_short": "Portaria de nomeação.",
        "summary_structured": {"tema": "nomeação"},
        "topics": ["pessoal", "nomeacao"],
    }
    report = evaluate_h2_output(text=text, allowed_tags=("ementa", "corpo"), output=output)
    assert report.score >= 0.8
    assert report.valid_spans is True


def test_quality_invalid_tag_scores_low() -> None:
    text = "Texto de exemplo"
    output = {
        "tag_spans": [{"tag": "decisao", "start_char": 0, "end_char": 5}],
        "summary_short": "",
        "topics": [],
    }
    report = evaluate_h2_output(text=text, allowed_tags=("ementa",), output=output)
    assert report.score < 0.6
    assert report.valid_spans is False
