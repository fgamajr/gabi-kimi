from __future__ import annotations

from src.backend.parsing.pipeline import _llm_allowed_for_source, _normalize_source_filters


def test_normalize_source_filters_keeps_valid_unique_sources() -> None:
    normalized = _normalize_source_filters(
        [
            "tcu_jurisprudencia_selecionada,tcu_btcu",
            "tcu_btcu",
            "invalid_source",
            "dou_documents",
        ]
    )
    assert normalized == (
        "tcu_jurisprudencia_selecionada",
        "tcu_btcu",
        "dou_documents",
    )


def test_llm_allowed_for_source_uses_explicit_filters() -> None:
    assert _llm_allowed_for_source(
        "tcu_jurisprudencia_selecionada",
        ("tcu_jurisprudencia_selecionada",),
    )
    assert not _llm_allowed_for_source(
        "tcu_btcu",
        ("tcu_jurisprudencia_selecionada",),
    )


def test_llm_allowed_for_source_falls_back_to_env(monkeypatch) -> None:
    monkeypatch.setenv("H2_LLM_SOURCE_ALLOWLIST", "tcu_jurisprudencia_selecionada,tcu_sumula")
    assert _llm_allowed_for_source("tcu_sumula")
    assert not _llm_allowed_for_source("tcu_btcu")


def test_llm_allowed_for_source_defaults_to_false_without_filters(monkeypatch) -> None:
    monkeypatch.delenv("H2_LLM_SOURCE_ALLOWLIST", raising=False)
    assert not _llm_allowed_for_source("dou_documents")
