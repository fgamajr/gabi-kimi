from __future__ import annotations

from src.backend.parsing.h1_dou_classifier import classify_dou_document


def test_classify_portaria() -> None:
    out = classify_dou_document(
        {
            "identifica": "PORTARIA Nº 123, DE 5 DE MAIO DE 2026",
            "ementa": "Nomeia servidor para cargo em comissão",
            "texto": "O MINISTRO ... resolve nomear ...",
        }
    )
    assert out.tipo in {"NORMATIVO", "PESSOAL"}
    assert out.subtipo in {"PORTARIA", "NOMEACAO"}
    assert out.confidence > 0.6


def test_classify_licitacao_edital() -> None:
    out = classify_dou_document(
        {
            "titulo": "EDITAL DE PREGÃO ELETRÔNICO Nº 17/2026",
            "texto": "Aviso de licitação para contratação de serviços",
        }
    )
    assert out.tipo == "LICITACAO"
    assert out.subtipo in {"EDITAL", "AVISO_LICITACAO"}


def test_classify_unknown_goes_done_with_low_confidence() -> None:
    out = classify_dou_document({"texto": "texto sem padrão explícito"})
    assert out.status == "done"
    assert out.confidence == 0.35


def test_classify_retificacao() -> None:
    out = classify_dou_document({"identifica": "RETIFICAÇÃO", "texto": "Retificação de resolução anterior."})
    assert out.tipo == "CORRETIVO"
    assert out.subtipo == "RETIFICACAO"


def test_classify_despacho() -> None:
    out = classify_dou_document({"identifica": "DESPACHO Nº 12/2026", "texto": "Despacho decisório do órgão."})
    assert out.tipo == "DECISORIO"
    assert out.subtipo == "DESPACHO"


def test_art_type_hint_stabilizes_status() -> None:
    out = classify_dou_document(
        {
            "art_type": "portaria",
            "texto": "Texto com referência cruzada a lei anterior, mas o ato é portaria.",
        }
    )
    assert out.subtipo == "PORTARIA"
    assert out.status == "done"
