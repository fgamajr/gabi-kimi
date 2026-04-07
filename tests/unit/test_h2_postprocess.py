from __future__ import annotations

from src.backend.parsing.h2_postprocess import (
    build_summary_short,
    classify_enrichment_mode,
    classify_enrichment_status,
    clean_text,
    derive_topics,
    normalize_topics,
    validate_summary_structured,
)


def test_clean_text_removes_markup() -> None:
    assert clean_text("<ementa>PORTARIA</ementa> <corpo>Nomeia servidor.</corpo>") == "PORTARIA Nomeia servidor."


def test_clean_text_unescapes_html_entities() -> None:
    assert clean_text("&lt;p&gt;Relatório:&lt;/p&gt;") == "Relatório:"


def test_derive_topics_never_uses_source_name() -> None:
    topics = derive_topics("dou_documents", "PORTARIA que nomeia servidor", {"art_type": "portaria"})
    assert "dou_documents" not in topics
    assert "pessoal" in topics or "normativo" in topics


def test_normalize_topics_enforces_taxonomy() -> None:
    topics = normalize_topics("dou_documents", ["dou_documents", "saude", "tema_invalido"], "ANVISA publicou portaria", {})
    assert topics == ["saude_publica"]


def test_classify_done_fallback() -> None:
    status = classify_enrichment_status(
        "dou_documents",
        used_fallback=True,
        spans_count=0,
        tags_count=1,
        summary_short="Resumo limpo",
        summary_structured={"tipo_ato": "PORTARIA"},
        topics=["pessoal"],
        legal_entities=[],
    )
    assert status == "done_fallback"


def test_classify_enrichment_mode_heuristic() -> None:
    mode = classify_enrichment_mode(
        used_fallback=False,
        llm_summary_used=False,
        llm_structured_used=False,
        llm_topics_used=False,
        llm_entities_used=False,
        llm_spans_used=False,
    )
    assert mode == "heuristic"


def test_build_summary_short_is_clean_text() -> None:
    summary = build_summary_short("dou_documents", "<identifica>PORTARIA</identifica> <corpo>Nomeia servidor.</corpo>", {}, ["pessoal"])
    assert "<" not in summary


def test_validate_summary_structured_rejects_extra_keys() -> None:
    summary = validate_summary_structured("tcu_sumula", {"numero": "123", "tema": "licitacao", "extra": "x"})
    assert summary is None
