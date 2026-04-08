from __future__ import annotations

from src.backend.parsing.source_parsers import SOURCE_TYPES
from src.backend.parsing.source_semantics import get_semantic_contract, load_source_semantics


def test_all_sources_have_semantic_contracts() -> None:
    contracts = load_source_semantics()
    assert set(contracts) == set(SOURCE_TYPES)


def test_tcu_acordao_contract_declares_semantic_sections_and_fields() -> None:
    contract = get_semantic_contract("tcu_acordao_completo")
    assert contract.primary_sections == ("decisao", "voto", "relatorio")
    assert "problematica" in contract.semantic_fields
    assert "decisao" in contract.semantic_fields
    assert contract.year_field == "ano_acordao"
