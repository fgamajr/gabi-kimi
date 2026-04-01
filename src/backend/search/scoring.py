from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ScoringWeights:
    relevance: float
    authority: float
    entity_density: float
    evidence_score: float
    policy_mult: bool


SCORING_PROFILES: dict[str, ScoringWeights] = {
    "exact_match": ScoringWeights(
        relevance=0.60,
        authority=0.25,
        entity_density=0.05,
        evidence_score=0.10,
        policy_mult=False,
    ),
    "legal_reference": ScoringWeights(
        relevance=0.45,
        authority=0.35,
        entity_density=0.10,
        evidence_score=0.10,
        policy_mult=True,
    ),
    "aggregation": ScoringWeights(
        relevance=0.30,
        authority=0.20,
        entity_density=0.35,
        evidence_score=0.15,
        policy_mult=True,
    ),
    "accountability": ScoringWeights(
        relevance=0.40,
        authority=0.30,
        entity_density=0.15,
        evidence_score=0.15,
        policy_mult=True,
    ),
    "summary": ScoringWeights(
        relevance=0.40,
        authority=0.25,
        entity_density=0.10,
        evidence_score=0.25,
        policy_mult=True,
    ),
    "factual": ScoringWeights(
        relevance=0.45,
        authority=0.30,
        entity_density=0.10,
        evidence_score=0.15,
        policy_mult=True,
    ),
    "exploratory": ScoringWeights(
        relevance=0.45,
        authority=0.20,
        entity_density=0.15,
        evidence_score=0.20,
        policy_mult=False,
    ),
    "evidential": ScoringWeights(
        relevance=0.35,
        authority=0.20,
        entity_density=0.15,
        evidence_score=0.30,
        policy_mult=True,
    ),
    "recommendation": ScoringWeights(
        relevance=0.40,
        authority=0.25,
        entity_density=0.10,
        evidence_score=0.25,
        policy_mult=True,
    ),
}


def get_profile(query_type: str) -> ScoringWeights:
    return SCORING_PROFILES.get(query_type, SCORING_PROFILES["exploratory"])


def compute_final_score(
    *,
    query_type: str,
    relevance_base: float,
    authority: float,
    entity_density: float,
    evidence_score: float,
    policy_multiplier: float,
    boost_factor: float,
    penalty_factor: float,
) -> float:
    w = get_profile(query_type)
    score = (
        w.relevance * relevance_base
        + w.authority * authority
        + w.entity_density * entity_density
        + w.evidence_score * evidence_score
    )
    if w.policy_mult:
        score *= policy_multiplier
    score *= boost_factor * penalty_factor
    return round(max(0.0, min(1.0, score)), 4)
