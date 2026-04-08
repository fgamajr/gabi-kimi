from __future__ import annotations

from src.backend.parsing.h3_pipeline import SemanticResolver
from src.backend.parsing.h3_semantic import (
    OPTIONAL_H3_INPUT_FIELDS,
    REQUIRED_H3_INPUT_FIELDS,
    H3Input,
    _clean_trailing_crossref,
    _extract_sumario_dispositivo,
    build_h3_input,
    build_h3_input_hash,
    build_semantic_view_from_h2,
    derive_quality_flags,
    project_semantic_status,
    project_semantic_row,
)


def _sample_h2_row() -> dict:
    return {
        "raw_id": "DOC-1",
        "source_type": "tcu_jurisprudencia_selecionada",
        "summary_short": "Resumo limpo",
        "summary_structured": {"area": "Pessoal", "tema": "Aposentadoria"},
        "topics": ["pessoal"],
        "enrichment_status": "done_full",
        "enrichment_mode": "heuristic",
        "confidence_fields": {"overall": 0.81},
        "legal_entities": [{"type": "processo", "value": "TC 1/2025"}],
        "tags_flat": ["enunciado", "excerto"],
        "structured_fields": {"orgao_emissor": "TCU"},
        "body_tagged_xml": "<corpo>nao deve entrar no H3Input</corpo>",
    }


def test_build_h3_input_ignores_raw_text_fields() -> None:
    inp = build_h3_input(_sample_h2_row())
    assert isinstance(inp, H3Input)
    assert "body_tagged_xml" not in inp.__dataclass_fields__
    assert "raw_text" not in inp.__dataclass_fields__


def test_build_h3_input_hash_is_stable_for_dict_order() -> None:
    row_a = _sample_h2_row()
    row_b = _sample_h2_row()
    row_b["summary_structured"] = {"tema": "Aposentadoria", "area": "Pessoal"}
    hash_a = build_h3_input_hash(build_h3_input(row_a))
    hash_b = build_h3_input_hash(build_h3_input(row_b))
    assert hash_a == hash_b


def test_project_semantic_row_is_projection_and_copies_confidence() -> None:
    projected = project_semantic_row(build_h3_input(_sample_h2_row()))
    assert projected["semantic_summary_short"] == "Resumo limpo"
    assert projected["semantic_topics"] == ["pessoal"]
    assert projected["semantic_mode"] == "heuristic"
    assert projected["extraction_confidence_overall"] == 0.81
    assert projected["interpretation_confidence_overall"] == 0.81


def test_derive_quality_flags_marks_conservative_sources() -> None:
    row = _sample_h2_row()
    row["source_type"] = "tcu_btcu"
    row["enrichment_status"] = "done_partial"
    row["topics"] = ["controle_externo"]
    row["legal_entities"] = []
    flags = derive_quality_flags(build_h3_input(row))
    assert "source_conservative" in flags
    assert "generic_topics" in flags
    assert "sparse_entities" in flags


def test_derive_quality_flags_always_marks_fallback_only_for_h2_fallback() -> None:
    row = _sample_h2_row()
    row["enrichment_status"] = "done_fallback"
    row["enrichment_mode"] = "fallback"
    flags = derive_quality_flags(build_h3_input(row))
    assert "fallback_only" in flags


def test_project_semantic_status_uses_only_quality_flag_for_fallback_decision() -> None:
    row = _sample_h2_row()
    row["enrichment_mode"] = "fallback"
    inp = build_h3_input(row)
    assert project_semantic_status(inp, []) == "done_full"
    assert project_semantic_status(inp, ["fallback_only"]) == "done_fallback"


def test_clean_trailing_crossref_removes_subitem_reference() -> None:
    assert _clean_trailing_crossref(
        "9.4. julgar irregulares as contas, nos termos do subitem 9.3."
    ) == "9.4. julgar irregulares as contas"
    assert _clean_trailing_crossref(
        "9.4. julgar irregulares as contas, de acordo com 9.3."
    ) == "9.4. julgar irregulares as contas"
    assert _clean_trailing_crossref(
        "9.4. julgar irregulares as contas"
    ) == "9.4. julgar irregulares as contas"


def test_extract_sumario_dispositivo_returns_last_known_dispositivo() -> None:
    assert _extract_sumario_dispositivo(
        "CONVÊNIO. CITAÇÃO. NEGATIVA DE PROVIMENTO."
    ) == "NEGATIVA DE PROVIMENTO"
    assert _extract_sumario_dispositivo(
        "CONVÊNIO. INEXECUÇÃO PARCIAL."
    ) is None


def test_project_semantic_status_maps_h2_failed_to_done_fallback() -> None:
    row = _sample_h2_row()
    row["enrichment_status"] = "failed"
    inp = build_h3_input(row)
    assert project_semantic_status(inp, []) == "done_fallback"


def test_project_semantic_row_keeps_h2_fallback_as_single_source_of_truth() -> None:
    row = _sample_h2_row()
    row["enrichment_status"] = "done_fallback"
    row["enrichment_mode"] = "fallback"
    projected = project_semantic_row(build_h3_input(row))
    assert projected["semantic_mode"] == "fallback"
    assert projected["semantic_status"] == "done_fallback"
    assert "fallback_only" in projected["quality_flags"]
    assert projected["gate_decision"]["primary_code"] == "fallback_only"


class _FakeConn:
    def __init__(self) -> None:
        self.committed = False

    def commit(self) -> None:
        self.committed = True


class _ResolverStub(SemanticResolver):
    def __init__(self, routing_status: str, h2_row: dict | None, h3_row: dict | None):
        super().__init__(dsn="postgresql://unused")
        self.routing_status = routing_status
        self.h2_row = h2_row
        self.h3_row = h3_row
        self.fallbacks: list[tuple[str, str, str]] = []

    def _load_routing_status(self, conn, source_type: str) -> str:  # type: ignore[override]
        return self.routing_status

    def _load_h2_row(self, conn, source_type: str, raw_id: str):  # type: ignore[override]
        return self.h2_row

    def _load_h3_row(self, conn, source_type: str, raw_id: str):  # type: ignore[override]
        return self.h3_row

    def _record_fallback(
        self,
        conn,
        source_type: str,
        raw_id: str,
        *,
        view_context: str,
        reason_code: str,
    ) -> None:  # type: ignore[override]
        self.fallbacks.append((source_type, raw_id, reason_code))


def test_semantic_resolver_active_falls_back_to_h2_with_log() -> None:
    resolver = _ResolverStub("active", _sample_h2_row(), None)
    view = resolver._get_view_conn(
        _FakeConn(), "DOC-1", "tcu_jurisprudencia_selecionada", view_context="audit"
    )
    assert view is not None
    assert view.view_layer == "h2_fallback"
    assert resolver.fallbacks == [
        ("tcu_jurisprudencia_selecionada", "DOC-1", "missing_h3_row")
    ]


def test_semantic_resolver_returns_h3_when_available() -> None:
    resolver = _ResolverStub(
        "active",
        _sample_h2_row(),
        {
            "raw_id": "DOC-1",
            "source_type": "tcu_jurisprudencia_selecionada",
            "semantic_status": "done_full",
            "semantic_mode": "heuristic",
            "semantic_summary_short": "Resumo H3",
            "semantic_summary_structured": {"area": "Pessoal"},
            "semantic_topics": ["pessoal"],
            "gate_decision": {"primary_code": "source_residual"},
            "quality_flags": [],
            "extraction_confidence_overall": 0.81,
            "interpretation_confidence_overall": 0.81,
        },
    )
    view = resolver._get_view_conn(
        _FakeConn(), "DOC-1", "tcu_jurisprudencia_selecionada", view_context="mcp"
    )
    assert view is not None
    assert view.view_layer == "h3"
    assert view.summary_short == "Resumo H3"


def test_build_semantic_view_from_h2_uses_requested_view_layer() -> None:
    view = build_semantic_view_from_h2(_sample_h2_row(), view_layer="h2")
    assert view.view_layer == "h2"
    assert view.status == "done_full"


def test_h3_ros_contract_stays_compact() -> None:
    assert 6 <= len(REQUIRED_H3_INPUT_FIELDS) <= 8
    assert "body_tagged_xml" not in REQUIRED_H3_INPUT_FIELDS
    assert "raw_text" not in REQUIRED_H3_INPUT_FIELDS
    assert "body_tagged_xml" not in OPTIONAL_H3_INPUT_FIELDS
    assert "raw_text" not in OPTIONAL_H3_INPUT_FIELDS


def test_project_semantic_row_for_tcu_acordao_uses_decisao_relatorio_voto_and_year() -> (
    None
):
    row = {
        "raw_id": "ACORDAO-COMPLETO-2659936",
        "source_type": "tcu_acordao_completo",
        "summary_short": "Acórdão 48 Segunda Câmara. NÃO COMPROVAÇÃO DA REGULAR APLICAÇÃO DE RECURSOS REPASSADOS PELA UNIÃO POR MEIO DO FNS.",
        "summary_structured": {
            "numero": 48,
            "colegiado": "Segunda Câmara",
            "relator": "AROLDO CEDRAZ",
            "tipo_processo": "TOMADA DE CONTAS ESPECIAL (TCE)",
            "objeto": "Tomada de Contas Especial instaurada pelo Fundo Nacional de Saúde (FNS).",
            "decisao_principal": "NÃO COMPROVAÇÃO DA REGULAR APLICAÇÃO DE RECURSOS REPASSADOS PELA UNIÃO POR MEIO DO FNS.",
        },
        "topics": ["saude_publica", "infraestrutura"],
        "enrichment_status": "done_full",
        "enrichment_mode": "heuristic",
        "confidence_fields": {"overall": 0.832},
        "legal_entities": [{"type": "relator", "value": "AROLDO CEDRAZ"}],
        "tags_flat": ["sumario", "relatorio", "voto", "decisao"],
        "structured_fields": {
            "numero_acordao": 48,
            "ano_acordao": 2017,
            "colegiado": "Segunda Câmara",
            "tipo_processo": "TOMADA DE CONTAS ESPECIAL (TCE)",
            "relator": "AROLDO CEDRAZ",
            "assunto": "Tomada de Contas Especial no Fundo Nacional de Saúde",
            "data_sessao": "2017-02-14",
        },
        "body_tagged_xml": (
            "<sumario>Tomada de Contas Especial instaurada pelo Fundo Nacional de Saúde em razão da não comprovação "
            "da regular aplicação de recursos repassados pela União.</sumario>\n"
            "<relatorio>Trata-se de tomada de contas especial instaurada em razão da não comprovação da regular "
            "aplicação dos recursos transferidos pelo FNS ao município. O fundamento para a instauração da TCE foi "
            "a constatação das seguintes irregularidades: não apresentação de documentação comprobatória da despesa, "
            "medicamentos fora da validade e não comprovação do serviço prestado.</relatorio>\n"
            "<voto>O voto conclui que restou caracterizada a omissão no dever de comprovar a correta aplicação dos "
            "recursos e propõe o julgamento pela irregularidade das contas. Entendo presentes todos os fundamentos "
            "para julgar irregulares as contas e imputar débito às responsáveis.</voto>\n"
            "<decisao>9.1. considerar revel a responsável; 9.3. rejeitar as alegações de defesa apresentadas; "
            "9.4. julgar irregulares as contas das responsáveis e condená-las ao pagamento do débito; "
            "9.5. aplicar multa individual.</decisao>"
        ),
    }
    projected = project_semantic_row(build_h3_input(row))
    assert projected["semantic_summary_structured"]["ano_acordao"] == "2017"
    problematica = projected["semantic_summary_structured"]["problematica"].lower()
    assert "irregularidades" in problematica or "não comprovação" in problematica
    assert (
        "documentação comprobatória" in problematica
        or "aplicação dos recursos" in problematica
    )
    assert projected["semantic_summary_structured"]["relatorio_resumo"]
    assert projected["semantic_summary_structured"]["voto_resumo"]
    assert "9.4." in projected["semantic_summary_structured"]["decisao"]
    assert (
        "julgar irregulares as contas"
        in projected["semantic_summary_structured"]["decisao"].lower()
    )
    assert "9.4." in projected["semantic_summary_structured"]["decisao_principal"]
    assert "infraestrutura" not in projected["semantic_topics"]
    # topic granularity (fiscal vs saude_publica) is LLM's job, not heuristic
    assert "/2017" in projected["semantic_summary_short"]
    # TCE case must have fiscalizacao; regulacao must NOT appear (false positive via \bregistro\b)
    assert "fiscalizacao" in projected["semantic_topics"]
    assert "regulacao" not in projected["semantic_topics"]


def test_derive_topics_preserves_pessoal_for_aposentadoria_row() -> None:
    row = {
        "raw_id": "ACORDAO-PESSOAL-1",
        "source_type": "tcu_acordao_completo",
        "summary_short": "Acórdão 100 Segunda Câmara. APOSENTADORIA.",
        "summary_structured": {"colegiado": "Segunda Câmara"},
        "topics": ["pessoal", "previdencia"],
        "enrichment_status": "done_full",
        "enrichment_mode": "heuristic",
        "confidence_fields": {"overall": 0.80},
        "legal_entities": [],
        "tags_flat": ["sumario", "decisao"],
        "structured_fields": {"ano_acordao": 2020, "colegiado": "Segunda Câmara"},
        "body_tagged_xml": (
            "<sumario>APOSENTADORIA. NEGATIVA DE REGISTRO.</sumario>"
            "<decisao>9.1. conhecer do pedido de reexame para, no mérito, negar-lhe provimento.</decisao>"
        ),
    }
    projected = project_semantic_row(build_h3_input(row))
    topics = projected["semantic_topics"]
    assert "previdencia" in topics
    assert "pessoal" in topics
