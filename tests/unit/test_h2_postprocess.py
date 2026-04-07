from __future__ import annotations

from src.backend.parsing.h2_postprocess import (
    build_confidence_fields,
    build_summary_short,
    build_summary_structured,
    classify_enrichment_mode,
    classify_enrichment_status,
    clean_text,
    derive_heuristic_spans,
    derive_legal_entities,
    derive_topics,
    normalize_topics,
    summarize_text,
    validate_legal_entities,
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
        tags=["identifica"],
        summary_short="Resumo limpo",
        summary_structured={"tipo_ato": "PORTARIA"},
        topics=["pessoal"],
        legal_entities=[],
        confidence_fields={"overall": 0.0},
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


def test_classify_done_partial_when_only_assinatura() -> None:
    confidence = build_confidence_fields(
        "tcu_jurisprudencia_selecionada",
        tags=["assinatura"],
        summary_structured={"area": "Pessoal", "tema": "Aposentadoria", "subtema": "Revisão"},
        topics=["pessoal"],
        legal_entities=[{"type": "relator", "value": "MINISTRO X"}],
    )
    status = classify_enrichment_status(
        "tcu_jurisprudencia_selecionada",
        used_fallback=False,
        tags=["assinatura"],
        summary_short="Resumo válido",
        summary_structured={"area": "Pessoal", "tema": "Aposentadoria", "subtema": "Revisão"},
        topics=["pessoal"],
        legal_entities=[{"type": "relator", "value": "MINISTRO X"}],
        confidence_fields=confidence,
    )
    assert status == "done_partial"


def test_build_summary_structured_dou_does_not_duplicate_fields() -> None:
    summary = build_summary_structured(
        "dou_documents",
        "Primeira frase do ato. Segunda frase com efeito. Terceira frase.",
        {"h1_tipo": "NORMATIVO", "h1_subtipo": "PORTARIA", "pub_date": "2026-01-01"},
        ["normativo"],
        [{"type": "base_legal", "value": "Lei 8.666/1993"}],
    )
    assert summary["objeto"] != summary["efeito_principal"]


def test_build_confidence_fields_penalizes_signature_only() -> None:
    confidence = build_confidence_fields(
        "tcu_btcu",
        tags=["assinatura", "assinatura"],
        summary_structured={"section_title": "Resumo", "assunto": "Assunto"},
        topics=["controle_externo"],
        legal_entities=[],
    )
    assert confidence["tag_spans"] < 0.3
    assert confidence["overall"] < 0.7


def test_validate_legal_entities_deduplicates_by_casing() -> None:
    entities = validate_legal_entities(
        [
            {"type": "base_legal", "value": "Lei 8.666/1993"},
            {"type": "base_legal", "value": "lei 8.666/1993"},
        ]
    )
    assert len(entities) == 1


def test_derive_legal_entities_ignores_truncated_base_legal() -> None:
    entities = derive_legal_entities("RESOLUÇÃO- Lei n. PORTARIA- Decreto-", {})
    assert not any(item["type"] == "base_legal" for item in entities)


def test_summarize_text_preserves_word_boundary() -> None:
    summary = summarize_text(
        "Primeira frase completa. Segunda frase muito longa com varias palavras relevantes.",
        limit=40,
    )
    assert summary == "Primeira frase completa."


def test_summarize_text_can_extend_to_sentence_boundary() -> None:
    text = "Texto inicial sem ponto até perto do limite mas com sentido suficiente para continuar. Segunda frase curta."
    summary = summarize_text(text, limit=50)
    assert summary.endswith(".")
    assert "Segunda frase curta" not in summary


def test_build_summary_structured_btcu_has_dedicated_fields() -> None:
    summary = build_summary_structured(
        "tcu_btcu",
        "Decisão principal do boletim. Segunda frase com contexto adicional.",
        {"section_title": "Controle Externo", "assunto": "Pessoal"},
        ["controle_externo", "pessoal"],
        [{"type": "base_legal", "value": "Lei 8.112/1990"}],
    )
    assert summary["section_title"] == "Controle Externo"
    assert summary["assunto"] == "Pessoal"
    assert summary["base_legal"] == "Lei 8.112/1990"


def test_build_summary_structured_publicacoes_uses_specific_topic() -> None:
    summary = build_summary_structured(
        "tcu_publicacoes",
        "Fichas-Síntese sobre relações exteriores. Texto introdutório.",
        {"title": "Fichas-Síntese Relações Exteriores", "pub_type": "ficha-sintese"},
        ["controle_externo", "licitacao"],
        [],
    )
    assert summary["assunto"] == "licitacao"


def test_build_confidence_fields_penalizes_generic_topics() -> None:
    generic = build_confidence_fields(
        "tcu_acordao_completo",
        tags=["sumario", "processo"],
        summary_structured={"numero": "1", "colegiado": "Plenário", "relator": "X"},
        topics=["controle_externo"],
        legal_entities=[],
    )
    specific = build_confidence_fields(
        "tcu_acordao_completo",
        tags=["sumario", "processo"],
        summary_structured={"numero": "1", "colegiado": "Plenário", "relator": "X"},
        topics=["controle_externo", "licitacao"],
        legal_entities=[],
    )
    assert generic["topics"] < specific["topics"]


def test_classify_btcu_never_promotes_done_full() -> None:
    confidence = build_confidence_fields(
        "tcu_btcu",
        tags=["section_title", "assunto", "processo"],
        summary_structured={
            "section_title": "Portaria",
            "assunto": "Pessoal",
            "base_legal": "Lei 8.112/1990",
            "decisao_principal": "Nomeia servidor.",
        },
        topics=["pessoal", "normativo"],
        legal_entities=[{"type": "processo", "value": "TC 123/2025"}],
    )
    status = classify_enrichment_status(
        "tcu_btcu",
        used_fallback=False,
        tags=["section_title", "assunto", "processo"],
        summary_short="Resumo válido",
        summary_structured={
            "section_title": "Portaria",
            "assunto": "Pessoal",
            "base_legal": "Lei 8.112/1990",
            "decisao_principal": "Nomeia servidor.",
        },
        topics=["pessoal", "normativo"],
        legal_entities=[{"type": "processo", "value": "TC 123/2025"}],
        confidence_fields=confidence,
    )
    assert status == "done_partial"


def test_derive_heuristic_spans_uses_publicacoes_alias_tags() -> None:
    text = "<title>Fichas-Síntese</title><description>Resumo da publicação.</description>"
    spans = derive_heuristic_spans(
        source_type="tcu_publicacoes",
        text=text,
        section_map={
            "title": {"start": 0, "len": 29},
            "description": {"start": 29, "len": 47},
        },
        allowed_tags=("titulo", "descricao"),
    )
    tags = [item["tag"] for item in spans]
    assert "titulo" in tags
    assert "descricao" in tags
