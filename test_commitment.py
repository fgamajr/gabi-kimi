#!/usr/bin/env python3
"""CRSS-1 test harness — determinism, ordering, tree, inclusion proofs.

Phase A tests: pure functions only, no DB dependency.
These MUST pass before any DB code is written.

Run:
    python3 test_commitment.py
"""
from __future__ import annotations

import hashlib
import sys
import unicodedata

from commitment.crss1 import (
    CRSS_VERSION,
    FIELD_ORDER,
    SORT_KEY_FIELDS,
    canonical_bytes,
    leaf_hash,
    sort_key,
    _nfc,
)
from commitment.tree import (
    EMPTY_HASH,
    MerkleTree,
    build_tree,
    inclusion_proof,
    verify_inclusion,
    _combine,
)


# ---------------------------------------------------------------------------
# Test infrastructure
# ---------------------------------------------------------------------------

_passed = 0
_failed = 0


def _assert(condition: bool, name: str, detail: str = "") -> None:
    global _passed, _failed
    if condition:
        _passed += 1
        print(f"  PASS  {name}")
    else:
        _failed += 1
        msg = f"  FAIL  {name}"
        if detail:
            msg += f" — {detail}"
        print(msg)


def _section(title: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


# ---------------------------------------------------------------------------
# Sample records
# ---------------------------------------------------------------------------

RECORD_A = {
    "event_type": "inserted",
    "natural_key_hash": "a" * 64,
    "strategy": "strict",
    "content_hash": "b" * 64,
    "occurrence_hash": "c" * 64,
    "page_number": "5",
    "source_url": "https://example.com/doc1",
    "publication_date": "2024-01-15",
    "edition_number": "180",
    "edition_section": "S1",
    "listing_sha256": "d" * 64,
}

RECORD_B = {
    "event_type": "new_version",
    "natural_key_hash": "a" * 64,
    "strategy": "strict",
    "content_hash": "e" * 64,
    "occurrence_hash": "f" * 64,
    "page_number": "10",
    "source_url": "https://example.com/doc2",
    "publication_date": "2024-02-20",
    "edition_number": "195",
    "edition_section": "S1",
    "listing_sha256": "0" * 64,
}

RECORD_NULLS = {
    "event_type": "inserted",
    "natural_key_hash": "1" * 64,
    "strategy": "fallback",
    "content_hash": "2" * 64,
    "occurrence_hash": "3" * 64,
    "page_number": None,
    "source_url": None,
    "publication_date": "",
    "edition_number": None,
    "edition_section": None,
    "listing_sha256": None,
}


# ---------------------------------------------------------------------------
# Test: Serializer determinism
# ---------------------------------------------------------------------------

def test_determinism_repeated() -> None:
    """Same dict → identical bytes across 10,000 runs."""
    _section("Serializer determinism (10,000 runs)")
    first = canonical_bytes(RECORD_A)
    all_match = True
    for _ in range(10_000):
        if canonical_bytes(RECORD_A) != first:
            all_match = False
            break
    _assert(all_match, "10,000 identical outputs")


def test_determinism_field_permutation() -> None:
    """Field permutations in input dict → identical output."""
    _section("Field permutation invariance")
    import random
    keys = list(RECORD_A.keys())
    baseline = canonical_bytes(RECORD_A)
    for _ in range(100):
        random.shuffle(keys)
        permuted = {k: RECORD_A[k] for k in keys}
        result = canonical_bytes(permuted)
        if result != baseline:
            _assert(False, "permuted dict produces same bytes",
                    f"expected {baseline!r}, got {result!r}")
            return
    _assert(True, "100 permutations all produce identical bytes")


def test_none_vs_empty() -> None:
    """None and empty string produce identical serialization."""
    _section("None vs empty string equivalence")
    rec_none = dict(RECORD_A, page_number=None)
    rec_empty = dict(RECORD_A, page_number="")
    _assert(
        canonical_bytes(rec_none) == canonical_bytes(rec_empty),
        "None and '' produce identical bytes",
    )


def test_missing_key_vs_none() -> None:
    """Missing key and None produce identical serialization."""
    rec_missing = {k: v for k, v in RECORD_A.items() if k != "listing_sha256"}
    rec_none = dict(RECORD_A, listing_sha256=None)
    _assert(
        canonical_bytes(rec_missing) == canonical_bytes(rec_none),
        "missing key and None produce identical bytes",
    )


def test_trailing_pipe() -> None:
    """Empty final field produces trailing pipe (MECH-1 rule 5)."""
    _section("Trailing pipe for empty final field")
    rec = dict(RECORD_A, listing_sha256=None)
    b = canonical_bytes(rec)
    text = b.decode("utf-8")
    _assert(
        text.endswith("|"),
        "ends with pipe when last field is empty",
        f"got: ...{text[-20:]!r}",
    )

    # Non-empty final field should NOT end with pipe
    b2 = canonical_bytes(RECORD_A)
    text2 = b2.decode("utf-8")
    _assert(
        not text2.endswith("|"),
        "does NOT end with pipe when last field has value",
    )


def test_no_bom_no_newline() -> None:
    """MECH-1 rule 4: no BOM, no trailing newline."""
    _section("No BOM, no trailing newline")
    b = canonical_bytes(RECORD_A)
    _assert(not b.startswith(b"\xef\xbb\xbf"), "no UTF-8 BOM")
    _assert(not b.endswith(b"\n"), "no trailing newline")
    _assert(not b.endswith(b"\r\n"), "no trailing CRLF")


def test_version_tag() -> None:
    """Version tag is first element, literal ASCII."""
    _section("Version tag")
    b = canonical_bytes(RECORD_A)
    text = b.decode("utf-8")
    _assert(text.startswith("CRSS1|"), f"starts with CRSS1|, got: {text[:10]!r}")


def test_field_count() -> None:
    """Output has exactly 12 pipe-separated segments (1 version + 11 data)."""
    _section("Field count")
    b = canonical_bytes(RECORD_A)
    text = b.decode("utf-8")
    parts = text.split("|")
    _assert(
        len(parts) == 12,
        f"12 segments (1 version + 11 data), got {len(parts)}",
    )


def test_nfc_normalization() -> None:
    """NFC normalization: composed vs decomposed forms produce identical bytes."""
    _section("NFC normalization")
    # "AÇÃO" composed (NFC) vs decomposed (NFD)
    composed = "A\u00c7\u00c3O"  # Ç, Ã as single codepoints
    decomposed = "AC\u0327A\u0303O"  # C + cedilla, A + tilde

    _assert(composed != decomposed, "composed != decomposed (raw)")
    _assert(
        unicodedata.normalize("NFC", composed) == unicodedata.normalize("NFC", decomposed),
        "NFC(composed) == NFC(decomposed)",
    )

    rec_c = dict(RECORD_A, strategy=composed)
    rec_d = dict(RECORD_A, strategy=decomposed)
    _assert(
        canonical_bytes(rec_c) == canonical_bytes(rec_d),
        "canonical_bytes identical for composed vs decomposed",
    )


def test_event_type_is_first_data_field() -> None:
    """event_type is the first field after version tag (INV-2)."""
    _section("Event type position (INV-2)")
    _assert(FIELD_ORDER[0] == "event_type", "FIELD_ORDER[0] == 'event_type'")
    b = canonical_bytes(RECORD_A)
    text = b.decode("utf-8")
    parts = text.split("|")
    _assert(parts[0] == "CRSS1", "segment 0 is version tag")
    _assert(parts[1] == "inserted", f"segment 1 is event_type, got {parts[1]!r}")


def test_leaf_hash_determinism() -> None:
    """leaf_hash produces consistent 64-char hex."""
    _section("Leaf hash determinism")
    h1 = leaf_hash(RECORD_A)
    h2 = leaf_hash(RECORD_A)
    _assert(h1 == h2, "identical across calls")
    _assert(len(h1) == 64, f"64-char hex, got {len(h1)}")
    _assert(h1 == h1.lower(), "lowercase hex")

    # Different record → different hash
    h3 = leaf_hash(RECORD_B)
    _assert(h1 != h3, "different record → different hash")


# ---------------------------------------------------------------------------
# Test: Sort key
# ---------------------------------------------------------------------------

def test_sort_key_fields() -> None:
    """Sort key uses the frozen ordering contract (INV-3)."""
    _section("Sort key (INV-3)")
    _assert(
        SORT_KEY_FIELDS == ("publication_date", "edition_number", "page_number", "occurrence_hash"),
        "SORT_KEY_FIELDS matches frozen contract",
    )


def test_sort_key_ordering() -> None:
    """Sort key produces correct lexicographic ordering."""
    sk_a = sort_key(RECORD_A)
    sk_b = sort_key(RECORD_B)
    _assert(sk_a < sk_b, f"A < B: {sk_a} < {sk_b}")

    # Empty string sorts before non-empty
    sk_nulls = sort_key(RECORD_NULLS)
    _assert(sk_nulls < sk_a, f"nulls < A: {sk_nulls} < {sk_a}")


def test_sort_key_none_handling() -> None:
    """None in sort key fields → empty string."""
    sk = sort_key(RECORD_NULLS)
    _assert(sk[0] == "", "publication_date None → empty string")
    _assert(sk[2] == "", "page_number None → empty string")


def test_sort_key_tiebreaker() -> None:
    """occurrence_hash guarantees total ordering."""
    rec1 = dict(RECORD_A, occurrence_hash="a" * 64)
    rec2 = dict(RECORD_A, occurrence_hash="b" * 64)
    sk1 = sort_key(rec1)
    sk2 = sort_key(rec2)
    _assert(sk1 != sk2, "different occurrence_hash → different sort key")
    _assert(sk1 < sk2, "lexicographic order by occurrence_hash")


# ---------------------------------------------------------------------------
# Test: Merkle tree
# ---------------------------------------------------------------------------

def test_empty_tree() -> None:
    """Empty tree root = SHA256(b'')."""
    _section("Merkle tree — empty")
    tree = build_tree([])
    _assert(tree.root == EMPTY_HASH, f"empty root matches, got {tree.root[:16]}...")
    _assert(tree.leaf_count == 0, "leaf_count == 0")


def test_single_leaf() -> None:
    """Single leaf: root == leaf hash."""
    _section("Merkle tree — single leaf")
    h = leaf_hash(RECORD_A)
    tree = build_tree([h])
    _assert(tree.root == h, "root == leaf hash for single leaf")
    _assert(tree.leaf_count == 1, "leaf_count == 1")


def test_two_leaves() -> None:
    """Two leaves: root = combine(left, right)."""
    _section("Merkle tree — two leaves")
    h_a = leaf_hash(RECORD_A)
    h_b = leaf_hash(RECORD_B)
    tree = build_tree([h_a, h_b])

    expected = _combine(h_a, h_b)
    _assert(tree.root == expected, "root = combine(leaf_a, leaf_b)")
    _assert(tree.leaf_count == 2, "leaf_count == 2")


def test_three_leaves_odd_duplication() -> None:
    """Three leaves: last is duplicated for pairing."""
    _section("Merkle tree — three leaves (odd duplication)")
    h_a = leaf_hash(RECORD_A)
    h_b = leaf_hash(RECORD_B)
    h_c = leaf_hash(RECORD_NULLS)
    tree = build_tree([h_a, h_b, h_c])

    # Layer 1: [combine(a,b), combine(c,c)]
    left = _combine(h_a, h_b)
    right = _combine(h_c, h_c)
    expected = _combine(left, right)
    _assert(tree.root == expected, "odd duplication produces correct root")
    _assert(tree.leaf_count == 3, "leaf_count == 3")


def test_order_sensitivity() -> None:
    """Swapping two leaves → different root."""
    _section("Merkle tree — order sensitivity")
    h_a = leaf_hash(RECORD_A)
    h_b = leaf_hash(RECORD_B)
    tree_ab = build_tree([h_a, h_b])
    tree_ba = build_tree([h_b, h_a])
    _assert(tree_ab.root != tree_ba.root, "swapped leaves → different root")


def test_mech3_byte_concatenation() -> None:
    """MECH-3: internal node uses raw byte concatenation, not hex string."""
    _section("MECH-3 — byte-level concatenation")
    left = "aa" * 32  # 64 hex chars
    right = "bb" * 32

    # Correct: raw bytes
    expected = hashlib.sha256(bytes.fromhex(left) + bytes.fromhex(right)).hexdigest()
    actual = _combine(left, right)
    _assert(actual == expected, "combine uses bytes.fromhex concatenation")

    # Wrong: hex string concatenation (what we do NOT want)
    wrong = hashlib.sha256((left + right).encode("utf-8")).hexdigest()
    _assert(actual != wrong, "NOT hex string concatenation (128-byte input)")


# ---------------------------------------------------------------------------
# Test: Inclusion proofs
# ---------------------------------------------------------------------------

def test_inclusion_proof_single() -> None:
    """Inclusion proof for single-leaf tree."""
    _section("Inclusion proof — single leaf")
    h = leaf_hash(RECORD_A)
    tree = build_tree([h])
    proof = inclusion_proof(tree, 0)
    _assert(proof.leaf_hash == h, "proof.leaf_hash matches")
    _assert(proof.root == tree.root, "proof.root matches tree.root")
    _assert(len(proof.siblings) == 0, "no siblings for single leaf")
    _assert(verify_inclusion(proof), "proof verifies")


def test_inclusion_proof_two_leaves() -> None:
    """Inclusion proofs for two-leaf tree."""
    _section("Inclusion proof — two leaves")
    h_a = leaf_hash(RECORD_A)
    h_b = leaf_hash(RECORD_B)
    tree = build_tree([h_a, h_b])

    proof_0 = inclusion_proof(tree, 0)
    _assert(verify_inclusion(proof_0), "proof for leaf 0 verifies")
    _assert(proof_0.siblings[0] == (h_b, "right"), "leaf 0 sibling is h_b on right")

    proof_1 = inclusion_proof(tree, 1)
    _assert(verify_inclusion(proof_1), "proof for leaf 1 verifies")
    _assert(proof_1.siblings[0] == (h_a, "left"), "leaf 1 sibling is h_a on left")


def test_inclusion_proof_many_leaves() -> None:
    """Inclusion proofs for 7-leaf tree (multiple levels, odd duplication)."""
    _section("Inclusion proof — 7 leaves")
    leaves = [hashlib.sha256(f"leaf-{i}".encode()).hexdigest() for i in range(7)]
    tree = build_tree(leaves)

    for i in range(7):
        proof = inclusion_proof(tree, i)
        ok = verify_inclusion(proof)
        _assert(ok, f"proof for leaf {i} verifies")


def test_inclusion_proof_out_of_range() -> None:
    """Out-of-range leaf index raises IndexError."""
    _section("Inclusion proof — out of range")
    h = leaf_hash(RECORD_A)
    tree = build_tree([h])
    try:
        inclusion_proof(tree, 1)
        _assert(False, "should have raised IndexError")
    except IndexError:
        _assert(True, "IndexError raised for out-of-range index")

    try:
        inclusion_proof(tree, -1)
        _assert(False, "should have raised IndexError for negative")
    except IndexError:
        _assert(True, "IndexError raised for negative index")


# ---------------------------------------------------------------------------
# Test: Cross-cutting invariants
# ---------------------------------------------------------------------------

def test_canonical_bytes_all_nulls() -> None:
    """Record with all optional fields NULL serializes correctly."""
    _section("All-nulls record")
    b = canonical_bytes(RECORD_NULLS)
    text = b.decode("utf-8")
    parts = text.split("|")
    _assert(parts[0] == "CRSS1", "version tag present")
    _assert(parts[1] == "inserted", "event_type present")
    # page_number (index 6), source_url (7) should be empty
    _assert(parts[6] == "", f"page_number is empty, got {parts[6]!r}")
    _assert(parts[7] == "", f"source_url is empty, got {parts[7]!r}")
    # listing_sha256 is last (index 11) and None → trailing pipe
    _assert(text.endswith("|"), "trailing pipe for None final field")


def test_leaf_hash_changes_with_event_type() -> None:
    """Changing event_type changes the leaf hash (INV-2 consequence)."""
    _section("Event type affects leaf hash")
    rec_inserted = dict(RECORD_A, event_type="inserted")
    rec_new_version = dict(RECORD_A, event_type="new_version")
    _assert(
        leaf_hash(rec_inserted) != leaf_hash(rec_new_version),
        "different event_type → different leaf hash",
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print("CRSS-1 Phase A — Pure Function Tests")
    print("=" * 60)

    # Serializer determinism
    test_determinism_repeated()
    test_determinism_field_permutation()
    test_none_vs_empty()
    test_missing_key_vs_none()
    test_trailing_pipe()
    test_no_bom_no_newline()
    test_version_tag()
    test_field_count()
    test_nfc_normalization()
    test_event_type_is_first_data_field()
    test_leaf_hash_determinism()

    # Sort key
    test_sort_key_fields()
    test_sort_key_ordering()
    test_sort_key_none_handling()
    test_sort_key_tiebreaker()

    # Merkle tree
    test_empty_tree()
    test_single_leaf()
    test_two_leaves()
    test_three_leaves_odd_duplication()
    test_order_sensitivity()
    test_mech3_byte_concatenation()

    # Inclusion proofs
    test_inclusion_proof_single()
    test_inclusion_proof_two_leaves()
    test_inclusion_proof_many_leaves()
    test_inclusion_proof_out_of_range()

    # Cross-cutting
    test_canonical_bytes_all_nulls()
    test_leaf_hash_changes_with_event_type()

    # Summary
    print(f"\n{'='*60}")
    total = _passed + _failed
    print(f"  Results: {_passed}/{total} passed, {_failed} failed")
    print(f"{'='*60}")
    sys.exit(1 if _failed else 0)


if __name__ == "__main__":
    main()
