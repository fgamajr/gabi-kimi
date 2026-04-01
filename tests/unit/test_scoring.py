from __future__ import annotations

from src.backend.answering.classifier import QUERY_TYPES
from src.backend.answering.trace_builder import build_chunk_traces
from src.backend.search.scoring import (
    SCORING_PROFILES,
    compute_final_score,
    get_profile,
)


def test_all_query_types_have_profiles() -> None:
    for qt in QUERY_TYPES:
        assert qt in SCORING_PROFILES


def test_aggregation_entity_density_higher_than_exact_match() -> None:
    agg = get_profile("aggregation")
    exact = get_profile("exact_match")
    assert agg.entity_density > exact.entity_density


def test_compute_final_score_clamps_to_one() -> None:
    out = compute_final_score(
        query_type="legal_reference",
        relevance_base=1.0,
        authority=1.0,
        entity_density=1.0,
        evidence_score=1.0,
        policy_multiplier=2.0,
        boost_factor=2.0,
        penalty_factor=1.0,
    )
    assert out == 1.0


def test_build_chunk_traces_accepts_query_type() -> None:
    docs = [
        {
            "_id": "doc-a",
            "_score": 1.0,
            "_source": {
                "body_plain": "Texto com lei e decreto para densidade.",
                "section": "do1",
                "issuing_organ": "Ministério X",
            },
        }
    ]
    result = build_chunk_traces(docs, query_type="aggregation")
    assert len(result.chunk_traces) == 1
    assert result.chunk_traces[0].chunk_id == "doc-a"
