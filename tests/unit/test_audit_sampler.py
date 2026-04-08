from __future__ import annotations

from src.backend.parsing.audit_sampler import VersionState, deterministic_pick, stable_rank


def _state(raw_id: str) -> VersionState:
    return VersionState(
        source_type="dou_documents",
        raw_id=raw_id,
        content_hash=f"hash-{raw_id}",
        parser_version="1.0.0",
        h2_version="1.2.0",
        h3_version="1.0.0",
        h3_prompt_version="h3_v1_2_prompt_v2",
        h1_status="ok",
        h2_status="done_full",
        h3_status="done_full",
    )


def test_stable_rank_is_deterministic() -> None:
    assert stable_rank("doc-1", 42) == stable_rank("doc-1", 42)
    assert stable_rank("doc-1", 42) != stable_rank("doc-1", 43)


def test_deterministic_pick_returns_same_order_for_same_seed() -> None:
    states = [_state("doc-1"), _state("doc-2"), _state("doc-3")]
    left = [item.raw_id for item in deterministic_pick(states, seed=42, limit=3)]
    right = [item.raw_id for item in deterministic_pick(states, seed=42, limit=3)]
    assert left == right


def test_deterministic_pick_changes_with_seed() -> None:
    states = [_state("doc-1"), _state("doc-2"), _state("doc-3"), _state("doc-4")]
    left = [item.raw_id for item in deterministic_pick(states, seed=41, limit=4)]
    right = [item.raw_id for item in deterministic_pick(states, seed=42, limit=4)]
    assert left != right
