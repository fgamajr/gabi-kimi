"""Merkle tree — binary, order-preserving, with inclusion proof support.

Specification reference: CRSS-1

Invariants enforced:
  MECH-3  Internal node = SHA256(bytes.fromhex(left) || bytes.fromhex(right))
          Raw 32-byte concatenation, NOT hex-string concatenation.
  INV-3   Input order is preserved (NOT sorted by hash value).
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

EMPTY_HASH = hashlib.sha256(b"").hexdigest()


@dataclass(slots=True)
class MerkleTree:
    """Complete Merkle tree with proof support."""
    root: str
    leaf_count: int
    layers: list[list[str]] = field(default_factory=list)
    # layers[0] = leaves, layers[-1] = [root]


@dataclass(slots=True)
class InclusionProof:
    """Merkle inclusion proof for a single leaf."""
    leaf_index: int
    leaf_hash: str
    siblings: list[tuple[str, str]]  # list of (hash, "left"|"right")
    root: str


def _combine(left: str, right: str) -> str:
    """Hash two hex digests to produce parent node (MECH-3).

    Uses raw byte concatenation: SHA256(bytes(left) || bytes(right))
    This produces a 64-byte input (32 per child), matching the standard
    Merkle construction used by Bitcoin, Certificate Transparency, etc.
    """
    return hashlib.sha256(bytes.fromhex(left) + bytes.fromhex(right)).hexdigest()


def build_tree(leaf_hashes: list[str]) -> MerkleTree:
    """Build a binary Merkle tree from ordered leaf hashes.

    IMPORTANT: Does NOT sort leaves. Input order is the canonical order (INV-3).
    Odd layers are padded by duplicating the last element.

    Args:
        leaf_hashes: List of 64-char hex SHA256 digests in canonical order.

    Returns:
        MerkleTree with root, leaf_count, and full layer structure.
    """
    if not leaf_hashes:
        return MerkleTree(root=EMPTY_HASH, leaf_count=0, layers=[[EMPTY_HASH]])

    layers: list[list[str]] = [list(leaf_hashes)]
    current = list(leaf_hashes)

    while len(current) > 1:
        if len(current) % 2 == 1:
            current.append(current[-1])
        next_layer: list[str] = []
        for i in range(0, len(current), 2):
            next_layer.append(_combine(current[i], current[i + 1]))
        layers.append(next_layer)
        current = next_layer

    return MerkleTree(root=current[0], leaf_count=len(leaf_hashes), layers=layers)


def inclusion_proof(tree: MerkleTree, leaf_index: int) -> InclusionProof:
    """Extract an inclusion proof for the leaf at the given index.

    Args:
        tree: A MerkleTree built by build_tree().
        leaf_index: Zero-based index into the original leaf list.

    Returns:
        InclusionProof with the sibling path from leaf to root.

    Raises:
        IndexError: if leaf_index is out of range.
    """
    if leaf_index < 0 or leaf_index >= tree.leaf_count:
        raise IndexError(f"leaf_index {leaf_index} out of range [0, {tree.leaf_count})")

    siblings: list[tuple[str, str]] = []
    idx = leaf_index

    for layer_idx in range(len(tree.layers) - 1):
        layer = tree.layers[layer_idx]
        # Pad layer for odd-length (same logic as build_tree)
        padded = list(layer)
        if len(padded) % 2 == 1:
            padded.append(padded[-1])

        if idx % 2 == 0:
            siblings.append((padded[idx + 1], "right"))
        else:
            siblings.append((padded[idx - 1], "left"))
        idx //= 2

    return InclusionProof(
        leaf_index=leaf_index,
        leaf_hash=tree.layers[0][leaf_index],
        siblings=siblings,
        root=tree.root,
    )


def verify_inclusion(proof: InclusionProof) -> bool:
    """Verify an inclusion proof against the root.

    Recomputes the root from the leaf hash and sibling path using MECH-3
    byte-level concatenation.
    """
    current = proof.leaf_hash
    for sibling_hash, side in proof.siblings:
        if side == "left":
            current = _combine(sibling_hash, current)
        else:
            current = _combine(current, sibling_hash)
    return current == proof.root
