#!/usr/bin/env python3
"""Hostile verifier for CRSS-1 commitments.

ZERO project imports. ZERO third-party dependencies. Stdlib only.
Implements the CRSS-1 protocol from scratch as an independent verifier.

Usage:
    python3 hostile_verify.py <canonical_records.txt> <envelope.json>

Exit code:
    0 = PASS (commitment cryptographically verified)
    1 = FAIL (commitment falsified)
    2 = usage error

Clean-room verification:
    docker run --rm -v $(pwd):/data python:3.12-slim \\
        python3 /data/hostile_verify.py \\
        /data/proofs/crss1-golden/canonical_records.txt \\
        /data/proofs/crss1-golden/envelope.json
"""
from __future__ import annotations

import hashlib
import json
import sys
import unicodedata


# ---------------------------------------------------------------------------
# CRSS-1 protocol constants (hardcoded — this IS the spec)
# ---------------------------------------------------------------------------

CRSS_VERSION = "CRSS1"

FIELD_ORDER = (
    "event_type",
    "natural_key_hash",
    "strategy",
    "content_hash",
    "occurrence_hash",
    "page_number",
    "source_url",
    "publication_date",
    "edition_number",
    "edition_section",
    "listing_sha256",
)

SORT_KEY_FIELDS = (
    "publication_date",
    "edition_number",
    "page_number",
    "occurrence_hash",
)


# ---------------------------------------------------------------------------
# Step 1: Parse canonical record lines back into fields
# ---------------------------------------------------------------------------

def parse_record_line(line: bytes) -> dict[str, str]:
    """Parse a CRSS1|...|... line into a field dict.

    The line was produced by canonical_bytes() — pipe-delimited, UTF-8 NFC.
    First field is the version tag, remaining 11 fields match FIELD_ORDER.
    """
    text = line.decode("utf-8")
    parts = text.split("|")
    if parts[0] != CRSS_VERSION:
        raise ValueError(f"Expected version tag '{CRSS_VERSION}', got '{parts[0]}'")
    expected_fields = 1 + len(FIELD_ORDER)
    if len(parts) != expected_fields:
        raise ValueError(
            f"Expected {expected_fields} pipe-separated fields, got {len(parts)}"
        )
    return dict(zip(FIELD_ORDER, parts[1:]))


# ---------------------------------------------------------------------------
# Step 2: Reserialize from parsed fields (independent implementation)
# ---------------------------------------------------------------------------

def canonical_bytes_from_record(record: dict[str, str]) -> bytes:
    """Reconstruct canonical bytes from a parsed record.

    MECH-1 rules, implemented independently:
      1. Each field individually NFC-normalized
      2. NULL/missing -> empty string
      3. Join by pipe: CRSS1|f1|f2|...|f11
      4. UTF-8, no BOM, no trailing newline
    """
    parts = [CRSS_VERSION]
    for field in FIELD_ORDER:
        val = record.get(field)
        if val is None:
            val = ""
        val = unicodedata.normalize("NFC", str(val))
        parts.append(val)
    return "|".join(parts).encode("utf-8")


# ---------------------------------------------------------------------------
# Step 3: Merkle tree (independent implementation of MECH-3)
# ---------------------------------------------------------------------------

def merkle_root(leaf_hashes: list[str]) -> str:
    """Compute Merkle root from ordered leaf hashes.

    MECH-3: Internal node = SHA256(bytes.fromhex(left) || bytes.fromhex(right))
    Odd layer -> duplicate last node.
    Empty tree -> SHA256(b"").
    """
    if not leaf_hashes:
        return hashlib.sha256(b"").hexdigest()

    current = list(leaf_hashes)
    while len(current) > 1:
        if len(current) % 2 == 1:
            current.append(current[-1])
        next_layer = []
        for i in range(0, len(current), 2):
            combined = bytes.fromhex(current[i]) + bytes.fromhex(current[i + 1])
            next_layer.append(hashlib.sha256(combined).hexdigest())
        current = next_layer
    return current[0]


# ---------------------------------------------------------------------------
# Step 4: Ordering verification (INV-3)
# ---------------------------------------------------------------------------

def check_ordering(records: list[dict[str, str]]) -> bool:
    """Verify records are in frozen sort order (COLLATE 'C' = bytewise)."""
    keys = []
    for rec in records:
        key = tuple(rec.get(f, "") for f in SORT_KEY_FIELDS)
        keys.append(key)
    return keys == sorted(keys)


# ---------------------------------------------------------------------------
# Step 5: Envelope validation
# ---------------------------------------------------------------------------

def validate_envelope(envelope: dict) -> list[str]:
    """Check envelope has required fields and consistent values."""
    errors = []

    if envelope.get("crss_version") != CRSS_VERSION:
        errors.append(f"crss_version: expected '{CRSS_VERSION}', got '{envelope.get('crss_version')}'")

    if envelope.get("hash_algorithm") != "sha256":
        errors.append(f"hash_algorithm: expected 'sha256', got '{envelope.get('hash_algorithm')}'")

    if envelope.get("tree_structure") != "binary_merkle_duplicate_last":
        errors.append(f"tree_structure: unexpected '{envelope.get('tree_structure')}'")

    if envelope.get("null_encoding") != "empty_string":
        errors.append(f"null_encoding: expected 'empty_string', got '{envelope.get('null_encoding')}'")

    if envelope.get("text_normalization") != "nfc":
        errors.append(f"text_normalization: expected 'nfc', got '{envelope.get('text_normalization')}'")

    if list(envelope.get("field_order", [])) != list(FIELD_ORDER):
        errors.append("field_order: does not match protocol spec")

    expected_sort = list(SORT_KEY_FIELDS)
    actual_sort = envelope.get("ordering", {}).get("clause", [])
    if list(actual_sort) != expected_sort:
        errors.append(f"ordering.clause: expected {expected_sort}, got {actual_sort}")

    obs = envelope.get("observation_stats", {})
    total = obs.get("total_log_entries", 0)
    dup = obs.get("duplicate_skipped_count", 0)
    trans = obs.get("state_transitions", 0)
    if total != trans + dup:
        errors.append(
            f"INV-6: total_log_entries={total} != "
            f"state_transitions={trans} + duplicate_skipped_count={dup}"
        )

    return errors


# ---------------------------------------------------------------------------
# Main verification
# ---------------------------------------------------------------------------

def main() -> None:
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <canonical_records.txt> <envelope.json>",
              file=sys.stderr)
        sys.exit(2)

    records_path = sys.argv[1]
    envelope_path = sys.argv[2]

    # Load envelope
    with open(envelope_path, "r", encoding="utf-8") as f:
        envelope = json.load(f)

    # Load canonical record lines (raw bytes)
    with open(records_path, "rb") as f:
        raw = f.read()

    # Split on newline, filter empty trailing line
    raw_lines = [line for line in raw.split(b"\n") if line]

    print("Hostile CRSS-1 Verifier")
    print("=" * 50)

    # [1] Envelope structure
    print("\n[1] Envelope structure validation")
    errors = validate_envelope(envelope)
    if errors:
        for e in errors:
            print(f"  FAIL: {e}")
        sys.exit(1)
    print("  PASS: all envelope fields match protocol spec")

    # [2] Record count
    expected_count = envelope["record_count"]
    actual_count = len(raw_lines)
    print(f"\n[2] Record count")
    print(f"  Envelope says:    {expected_count}")
    print(f"  Records found:    {actual_count}")
    if expected_count != actual_count:
        print("  FAIL: count mismatch")
        sys.exit(1)
    print("  PASS")

    # [3] Parse + round-trip byte identity
    print(f"\n[3] Parse + re-serialize (round-trip byte identity)")
    records = []
    leaf_hashes = []
    for i, raw_line in enumerate(raw_lines):
        record = parse_record_line(raw_line)
        records.append(record)

        # Re-serialize from parsed fields (independent code path)
        reserialized = canonical_bytes_from_record(record)
        if reserialized != raw_line:
            print(f"  FAIL at record {i}: round-trip byte mismatch")
            print(f"    original:     {raw_line!r}")
            print(f"    reserialized: {reserialized!r}")
            sys.exit(1)

        leaf = hashlib.sha256(raw_line).hexdigest()
        leaf_hashes.append(leaf)
        print(f"  record[{i}]: leaf={leaf[:16]}...  event={record['event_type']}")

    print(f"  PASS: all {actual_count} records round-trip clean")

    # [4] Ordering (INV-3)
    print(f"\n[4] Ordering verification (INV-3)")
    if check_ordering(records):
        print("  PASS: records in frozen sort order")
    else:
        print("  FAIL: records not in sort order")
        for i, rec in enumerate(records):
            key = tuple(rec.get(f, "") for f in SORT_KEY_FIELDS)
            print(f"    [{i}] {key}")
        sys.exit(1)

    # [5] Observation stats (INV-6)
    print(f"\n[5] Observation stats (INV-6)")
    obs = envelope["observation_stats"]
    print(f"  total_log_entries:      {obs['total_log_entries']}")
    print(f"  duplicate_skipped:      {obs['duplicate_skipped_count']}")
    print(f"  state_transitions:      {obs['state_transitions']}")
    print(f"  record_count (tree):    {expected_count}")
    if obs["state_transitions"] != expected_count:
        print("  FAIL: state_transitions != record_count")
        sys.exit(1)
    print(f"  PASS: {obs['total_log_entries']} = {obs['state_transitions']} + {obs['duplicate_skipped_count']}")

    # [6] Merkle root (MECH-3)
    print(f"\n[6] Merkle root computation (MECH-3)")
    computed_root = merkle_root(leaf_hashes)
    expected_root = envelope["commitment_root"]
    print(f"  Expected: {expected_root}")
    print(f"  Computed: {computed_root}")
    match = computed_root == expected_root
    print(f"  Match:    {match}")

    # Final verdict
    print(f"\n{'=' * 50}")
    if match:
        print(f"VERDICT: PASS — commitment cryptographically verified")
        print(f"  {actual_count} records, root {computed_root[:16]}...")
        sys.exit(0)
    else:
        print("VERDICT: FAIL — commitment falsified")
        sys.exit(1)


if __name__ == "__main__":
    main()
