from __future__ import annotations

import pytest

from src.backend.parsing import h3_pipeline
from src.backend.parsing.h3_llm import (
    H3_PROMPT_TEMPLATE,
    apply_h3_llm_output,
    build_h3_prompt,
    refine_semantic_projection_with_llm,
)
from src.backend.parsing.h3_semantic import build_h3_input, project_semantic_row


def _sample_h2_row() -> dict:
    return {
        "raw_id": "DOC-1",
        "source_type": "tcu_jurisprudencia_selecionada",
        "summary_short": "Resumo base",
        "summary_structured": {
            "area": "Pessoal",
            "tema": "Aposentadoria",
            "subtema": None,
            "tese_central": "Texto base",
        },
        "topics": ["controle_externo"],
        "enrichment_status": "done_partial",
        "enrichment_mode": "heuristic",
        "confidence_fields": {"overall": 0.72},
        "legal_entities": [{"type": "processo", "value": "TC 1/2025"}],
        "tags_flat": ["enunciado", "excerto"],
        "structured_fields": {"area": "Pessoal", "tema": "Aposentadoria", "subtema": "Reforma"},
    }


def test_build_h3_prompt_mentions_seed_constraints() -> None:
    inp = build_h3_input(_sample_h2_row())
    prompt = build_h3_prompt("<enunciado>Texto</enunciado>", inp)
    assert "Seed summary_short" in prompt
    assert "Retorne APENAS JSON" in prompt
    assert "Você NÃO pode gerar spans" in prompt
    assert "verbos deônticos" in prompt


def test_h3_prompt_template_stays_static() -> None:
    assert "{source_type}" in H3_PROMPT_TEMPLATE
    assert "{schema_keys}" in H3_PROMPT_TEMPLATE
    assert "{text}" in H3_PROMPT_TEMPLATE
    assert "Resumo base" not in H3_PROMPT_TEMPLATE


def test_apply_h3_llm_output_refines_semantics_without_touching_extraction() -> None:
    inp = build_h3_input(_sample_h2_row())
    projected = project_semantic_row(inp)
    refined = apply_h3_llm_output(
        inp,
        projected,
        raw_text="<enunciado>Texto sobre aposentadoria e pessoal.</enunciado>",
        llm_output={
            "summary_short": "Jurisprudência do TCU sobre aposentadoria em pessoal.",
            "summary_structured": {
                "area": "Pessoal",
                "tema": "Aposentadoria",
                "subtema": "Reforma",
                "tese_central": "Define orientação sobre aposentadoria.",
            },
            "topics": ["pessoal", "aposentadoria"],
        },
    )
    assert refined["semantic_mode"] == "llm"
    assert refined["used_layers"] == ["heuristic", "llm"]
    assert refined["extraction_confidence_overall"] == projected["extraction_confidence_overall"]
    assert refined["interpretation_confidence_overall"] >= 0.72
    assert "pessoal" in refined["semantic_topics"]


def test_apply_h3_llm_output_keeps_heuristic_when_output_is_equivalent() -> None:
    inp = build_h3_input(_sample_h2_row())
    projected = project_semantic_row(inp)
    refined = apply_h3_llm_output(
        inp,
        projected,
        raw_text="<enunciado>Texto sobre aposentadoria e pessoal.</enunciado>",
        llm_output={
            "summary_short": "  resumo base  ",
            "summary_structured": {
                "tema": "Aposentadoria",
                "area": "Pessoal",
                "tese_central": "Texto base",
            },
            "topics": ["controle_externo"],
        },
    )
    assert refined == projected
    assert refined["semantic_mode"] == "heuristic"
    assert refined["used_layers"] == ["heuristic"]


def test_apply_h3_llm_output_keeps_heuristic_on_summary_only_paraphrase_that_weakens_normative_tone() -> None:
    row = _sample_h2_row()
    row["summary_short"] = (
        "Deve-se evitar prorrogações em prazos diferentes dos originalmente estabelecidos."
    )
    row["summary_structured"] = {
        "area": "Licitação",
        "tema": "Contratos",
        "subtema": None,
        "tese_central": "Deve-se evitar prorrogações em prazos diferentes dos originalmente estabelecidos.",
    }
    row["topics"] = ["licitacao"]
    inp = build_h3_input(row)
    projected = project_semantic_row(inp)
    refined = apply_h3_llm_output(
        inp,
        projected,
        raw_text=(
            "<enunciado>Deve-se evitar prorrogações em prazos diferentes "
            "dos originalmente estabelecidos.</enunciado>"
        ),
        llm_output={
            "summary_short": (
                "O texto enfatiza a necessidade de evitar prorrogações em "
                "prazos diferentes dos originalmente estabelecidos."
            ),
            "summary_structured": {
                "area": "Licitação",
                "tema": "Contratos",
                "subtema": None,
                "tese_central": (
                    "Deve-se evitar prorrogações em prazos diferentes "
                    "dos originalmente estabelecidos."
                ),
            },
            "topics": ["licitacao"],
        },
    )
    assert refined == projected


def test_apply_h3_llm_output_keeps_heuristic_when_llm_output_is_empty() -> None:
    inp = build_h3_input(_sample_h2_row())
    projected = project_semantic_row(inp)
    refined = apply_h3_llm_output(
        inp,
        projected,
        raw_text="<enunciado>Texto sobre aposentadoria e pessoal.</enunciado>",
        llm_output={"summary_short": None, "summary_structured": None, "topics": []},
    )
    assert refined == projected


def test_refine_semantic_projection_with_llm_returns_delta_meta(monkeypatch: pytest.MonkeyPatch) -> None:
    inp = build_h3_input(_sample_h2_row())
    projected = project_semantic_row(inp)

    monkeypatch.setattr(
        "src.backend.parsing.h3_llm.call_local_llm",
        lambda **_kwargs: {
            "summary_short": "Tese refinada sobre aposentadoria.",
            "summary_structured": {
                "area": "Pessoal",
                "tema": "Aposentadoria",
                "subtema": "Reforma",
                "tese_central": "Tese refinada.",
            },
            "topics": ["aposentadoria"],
            "__meta": {"provider": "ollama", "usage": {"total_tokens": 42}},
        },
    )

    refined, meta = refine_semantic_projection_with_llm(
        inp,
        projected,
        raw_text="<enunciado>Texto sobre aposentadoria.</enunciado>",
        model="qwen3",
        llm_mode="fast",
    )

    assert refined["semantic_mode"] == "llm"
    assert meta["delta_material"] is True
    assert meta["promoted"] is True
    assert "summary_short" in meta["changed_fields"]
    assert meta["provider"] == "ollama"


class _FakeConn:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def commit(self) -> None:
        return None


def test_process_one_semantic_does_not_persist_prompt_version_without_material_delta(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    saved: dict[str, object] = {}
    prompt_registry_calls: list[dict[str, object]] = []

    monkeypatch.setattr(h3_pipeline.psycopg, "connect", lambda *_args, **_kwargs: _FakeConn())
    monkeypatch.setattr(
        h3_pipeline,
        "_acquire_h3_queue_item",
        lambda *_args, **_kwargs: h3_pipeline.H3QueueItem(
            queue_id=1,
            source_type="tcu_jurisprudencia_selecionada",
            raw_id="DOC-1",
            h3_version="1.0.0",
            hash_version="1",
            input_hash="hash-1",
        ),
    )
    monkeypatch.setattr(h3_pipeline, "_load_parsed_row", lambda *_args, **_kwargs: _sample_h2_row())
    monkeypatch.setattr(h3_pipeline, "_mark_h3_queue_done", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(h3_pipeline, "_mark_h3_queue_failed", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(h3_pipeline, "_llm_allowed_for_source", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        h3_pipeline.H3RawAccess,
        "fetch_body_tagged_xml",
        lambda *_args, **_kwargs: "<enunciado>Texto</enunciado>",
    )
    monkeypatch.setattr(
        h3_pipeline,
        "refine_semantic_projection_with_llm",
        lambda _inp, projected, **_kwargs: (dict(projected), {"model": "qwen3"}),
    )
    monkeypatch.setattr(
        h3_pipeline,
        "_ensure_prompt_registry_entry",
        lambda *_args, **kwargs: prompt_registry_calls.append(kwargs),
    )
    monkeypatch.setattr(
        h3_pipeline,
        "_upsert_semantic_projection",
        lambda _conn, _source_type, row: saved.update(row),
    )

    assert h3_pipeline.process_one_semantic("worker-1", llm_source_filters=("tcu_jurisprudencia_selecionada",))
    assert saved["semantic_mode"] == "heuristic"
    assert saved["prompt_version"] is None
    assert prompt_registry_calls == []


def test_process_one_semantic_preserves_heuristic_projection_on_llm_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    saved: dict[str, object] = {}

    monkeypatch.setattr(h3_pipeline.psycopg, "connect", lambda *_args, **_kwargs: _FakeConn())
    monkeypatch.setattr(
        h3_pipeline,
        "_acquire_h3_queue_item",
        lambda *_args, **_kwargs: h3_pipeline.H3QueueItem(
            queue_id=1,
            source_type="tcu_jurisprudencia_selecionada",
            raw_id="DOC-1",
            h3_version="1.0.0",
            hash_version="1",
            input_hash="hash-1",
        ),
    )
    monkeypatch.setattr(h3_pipeline, "_load_parsed_row", lambda *_args, **_kwargs: _sample_h2_row())
    monkeypatch.setattr(h3_pipeline, "_mark_h3_queue_done", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(h3_pipeline, "_mark_h3_queue_failed", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(h3_pipeline, "_llm_allowed_for_source", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        h3_pipeline.H3RawAccess,
        "fetch_body_tagged_xml",
        lambda *_args, **_kwargs: "<enunciado>Texto</enunciado>",
    )

    def _raise_llm_failure(*_args, **_kwargs):
        raise RuntimeError("timeout")

    monkeypatch.setattr(h3_pipeline, "refine_semantic_projection_with_llm", _raise_llm_failure)
    monkeypatch.setattr(
        h3_pipeline,
        "_ensure_prompt_registry_entry",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("prompt registry should not be touched")),
    )
    monkeypatch.setattr(
        h3_pipeline,
        "_upsert_semantic_projection",
        lambda _conn, _source_type, row: saved.update(row),
    )

    assert h3_pipeline.process_one_semantic("worker-1", llm_source_filters=("tcu_jurisprudencia_selecionada",))
    assert saved["semantic_mode"] == "heuristic"
    assert saved["used_layers"] == ["heuristic"]
    assert saved["prompt_version"] is None


def test_process_one_semantic_records_llm_attempt_without_material_delta(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    saved: dict[str, object] = {}

    monkeypatch.setattr(h3_pipeline.psycopg, "connect", lambda *_args, **_kwargs: _FakeConn())
    monkeypatch.setattr(
        h3_pipeline,
        "_acquire_h3_queue_item",
        lambda *_args, **_kwargs: h3_pipeline.H3QueueItem(
            queue_id=1,
            source_type="tcu_jurisprudencia_selecionada",
            raw_id="DOC-1",
            h3_version="1.0.0",
            hash_version="1",
            input_hash="hash-1",
        ),
    )
    monkeypatch.setattr(h3_pipeline, "_load_parsed_row", lambda *_args, **_kwargs: _sample_h2_row())
    monkeypatch.setattr(h3_pipeline, "_mark_h3_queue_done", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(h3_pipeline, "_mark_h3_queue_failed", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(h3_pipeline, "_llm_allowed_for_source", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        h3_pipeline.H3RawAccess,
        "fetch_body_tagged_xml",
        lambda *_args, **_kwargs: "<enunciado>Texto</enunciado>",
    )
    monkeypatch.setattr(
        h3_pipeline,
        "refine_semantic_projection_with_llm",
        lambda _inp, projected, **_kwargs: (
            dict(projected),
            {
                "provider": "ollama",
                "usage": {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20},
                "delta_material": False,
                "changed_fields": [],
            },
        ),
    )
    monkeypatch.setattr(h3_pipeline, "_ensure_prompt_registry_entry", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        h3_pipeline,
        "_upsert_semantic_projection",
        lambda _conn, _source_type, row: saved.update(row),
    )

    assert h3_pipeline.process_one_semantic("worker-1", llm_source_filters=("tcu_jurisprudencia_selecionada",))
    evidence = saved["gate_decision"]["evidence"]
    assert evidence["llm_allowed"] is True
    assert evidence["llm_attempted"] is True
    assert evidence["llm_delta_material"] is False
    assert evidence["llm_promoted"] is False
