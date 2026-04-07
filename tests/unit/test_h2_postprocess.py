from __future__ import annotations

from src.backend.parsing.h2_postprocess import (
    build_summary_short,
    classify_enrichment_mode,
    classify_enrichment_status,
    clean_text,
    derive_heuristic_spans,
    derive_legal_entities,
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


def test_derive_legal_entities_extracts_cpf_and_processo() -> None:
    entities = derive_legal_entities(
        "Processo nº 12345.678901/2024-11 referente ao CPF 123.456.789-10.",
        {},
    )
    entity_pairs = {(item["type"], item["value"]) for item in entities}
    assert ("processo", "Processo nº 12345.678901/2024-11") in entity_pairs
    assert ("cpf", "123.456.789-10") in entity_pairs


def test_derive_heuristic_spans_uses_section_map_and_regex() -> None:
    text = (
        "<identifica>PORTARIA Nº 10</identifica>\n"
        "<corpo>Processo nº 12345.678901/2024-11. JOAO DA SILVA Diretor.</corpo>\n"
        "<fundamento_legal>Lei 8.666/1993</fundamento_legal>"
    )
    section_map = {
        "identifica": {"start": 0, "len": len("<identifica>PORTARIA Nº 10</identifica>")},
        "fundamento_legal": {
            "start": text.index("<fundamento_legal>"),
            "len": len("<fundamento_legal>Lei 8.666/1993</fundamento_legal>"),
        },
    }
    spans = derive_heuristic_spans(
        source_type="dou_documents",
        text=text,
        section_map=section_map,
        allowed_tags=("identifica", "fundamento_legal", "processo", "assinatura"),
    )
    tags = [item["tag"] for item in spans]
    assert "identifica" in tags
    assert "fundamento_legal" in tags
    assert "processo" in tags
    assert "assinatura" in tags
