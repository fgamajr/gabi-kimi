"""CRSS-1 independent verifier — compare registry state against published envelope.

The verifier NEVER relies on internal DB IDs.
Only the envelope contract + data ordering determine the result.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.backend.commitment.anchor import compute_commitment


@dataclass(slots=True)
class VerificationResult:
    """Result of an independent verification."""
    matches: bool
    expected_root: str
    computed_root: str
    expected_count: int
    computed_count: int
    snapshot_match: bool
    details: dict[str, Any] = field(default_factory=dict)


def verify_against_envelope(
    dsn: str,
    envelope_path: Path,
    *,
    sources_yaml: Path | None = None,
    identity_yaml: Path | None = None,
) -> VerificationResult:
    """Verify a registry against a published commitment envelope.

    Recomputes the commitment using the envelope's log_high_water_mark
    to ensure the same snapshot boundary.

    Args:
        dsn: PostgreSQL connection string to the verifier's registry.
        envelope_path: Path to the published commitment envelope JSON.
        sources_yaml: Path to sources YAML (for interpretation contract check).
        identity_yaml: Path to identity YAML (for interpretation contract check).

    Returns:
        VerificationResult with match status and diagnostics.
    """
    envelope = json.loads(envelope_path.read_text(encoding="utf-8"))

    expected_root = envelope["commitment_root"]
    expected_count = envelope["record_count"]
    log_high_water = envelope["snapshot"]["log_high_water_mark"]

    # Recompute using the same snapshot boundary
    computed = compute_commitment(
        dsn,
        log_high_water=log_high_water,
        sources_yaml=sources_yaml,
        identity_yaml=identity_yaml,
    )

    computed_root = computed["commitment_root"]
    computed_count = computed["record_count"]

    root_matches = expected_root == computed_root
    count_matches = expected_count == computed_count
    snapshot_match = (
        log_high_water == computed["snapshot"]["log_high_water_mark"]
    )

    # Check interpretation contract if provided
    contract_match = True
    contract_details: dict[str, Any] = {}
    expected_contract = envelope.get("interpretation_contract", {})
    computed_contract = computed.get("interpretation_contract", {})

    for key in ("sources_yaml_sha256", "identity_yaml_sha256"):
        exp = expected_contract.get(key)
        comp = computed_contract.get(key)
        if exp and comp and exp != comp:
            contract_match = False
            contract_details[key] = {"expected": exp[:16] + "...", "computed": comp[:16] + "..."}

    # Check observation stats
    obs_match = True
    expected_obs = envelope.get("observation_stats", {})
    computed_obs = computed.get("observation_stats", {})
    obs_details: dict[str, Any] = {}
    for key in ("total_log_entries", "duplicate_skipped_count", "state_transitions"):
        exp = expected_obs.get(key)
        comp = computed_obs.get(key)
        if exp is not None and comp is not None and exp != comp:
            obs_match = False
            obs_details[key] = {"expected": exp, "computed": comp}

    matches = root_matches and count_matches and snapshot_match

    return VerificationResult(
        matches=matches,
        expected_root=expected_root,
        computed_root=computed_root,
        expected_count=expected_count,
        computed_count=computed_count,
        snapshot_match=snapshot_match,
        details={
            "root_matches": root_matches,
            "count_matches": count_matches,
            "snapshot_match": snapshot_match,
            "contract_match": contract_match,
            "contract_details": contract_details,
            "observation_match": obs_match,
            "observation_details": obs_details,
        },
    )
