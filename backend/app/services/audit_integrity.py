"""Pure Merkle-tree utilities for tamper-evident audit checkpoints.

This module deliberately has no application, database, or signing dependencies.
Its root convention follows China-main's ``audit_chain.py``: SHA-256 leaves,
duplicate the final node at odd levels, and use a fixed SHA-256 value for an
empty tree. Inclusion proofs are added here because China-main does not provide
them.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from typing import TypedDict

_EMPTY_TREE_DOMAIN = b"KITESHIELD_EMPTY_AUDIT_TREE"
_HASH_HEX_LENGTH = 64


class ProofStep(TypedDict):
    """One sibling in an inclusion proof."""

    position: str
    hash: str


def _validate_hash(value: str, field_name: str = "hash") -> bytes:
    if not isinstance(value, str) or len(value) != _HASH_HEX_LENGTH:
        raise ValueError(f"{field_name} must be a 32-byte hexadecimal hash")
    try:
        return bytes.fromhex(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be a 32-byte hexadecimal hash") from exc


def compute_merkle_root(leaf_hashes: Sequence[str]) -> str:
    """Return a deterministic SHA-256 Merkle root.

    Odd levels duplicate the final node, matching China-main. The empty-tree
    value also matches China-main exactly.
    """
    if not leaf_hashes:
        return hashlib.sha256(_EMPTY_TREE_DOMAIN).hexdigest()

    current = [_validate_hash(value, "leaf hash") for value in leaf_hashes]
    while len(current) > 1:
        next_level: list[bytes] = []
        for index in range(0, len(current), 2):
            left = current[index]
            right = current[index + 1] if index + 1 < len(current) else left
            next_level.append(hashlib.sha256(left + right).digest())
        current = next_level
    return current[0].hex()


def generate_inclusion_proof(leaf_hashes: Sequence[str], index: int) -> list[ProofStep]:
    """Generate a sibling proof for ``leaf_hashes[index]``.

    The proof includes a duplicated self-sibling when an odd level duplicates
    its final node. This makes the proof explicit and unambiguous.
    """
    if not leaf_hashes:
        raise ValueError("cannot generate a proof for an empty tree")
    if not isinstance(index, int) or isinstance(index, bool):
        raise ValueError("index must be an integer")
    if index < 0 or index >= len(leaf_hashes):
        raise ValueError("index is outside the tree")

    current = [_validate_hash(value, "leaf hash") for value in leaf_hashes]
    proof: list[ProofStep] = []
    position = index
    while len(current) > 1:
        if position % 2 == 0:
            sibling_index = position + 1
            sibling_position = "right"
        else:
            sibling_index = position - 1
            sibling_position = "left"
        if sibling_index >= len(current):
            sibling_index = position
        proof.append({"position": sibling_position, "hash": current[sibling_index].hex()})

        next_level: list[bytes] = []
        for offset in range(0, len(current), 2):
            left = current[offset]
            right = current[offset + 1] if offset + 1 < len(current) else left
            next_level.append(hashlib.sha256(left + right).digest())
        current = next_level
        position //= 2
    return proof


def verify_inclusion_proof(
    leaf_hash: str,
    index: int,
    proof: Sequence[Mapping[str, str]],
    root: str,
    total_leaves: int,
) -> bool:
    """Verify a proof without raising on malformed untrusted proof data."""
    try:
        if not isinstance(index, int) or isinstance(index, bool):
            return False
        if not isinstance(total_leaves, int) or isinstance(total_leaves, bool):
            return False
        if total_leaves <= 0 or index < 0 or index >= total_leaves:
            return False
        if not isinstance(proof, Sequence) or isinstance(proof, (str, bytes)):
            return False

        current = _validate_hash(leaf_hash, "leaf hash")
        expected_levels = 0
        level_width = total_leaves
        while level_width > 1:
            expected_levels += 1
            level_width = (level_width + 1) // 2
        if len(proof) != expected_levels:
            return False

        position = index
        for step in proof:
            if not isinstance(step, Mapping):
                return False
            direction = step.get("position")
            sibling = step.get("hash")
            if direction not in {"left", "right"} or not isinstance(sibling, str):
                return False
            expected_direction = "left" if position % 2 else "right"
            if direction != expected_direction:
                return False
            sibling_bytes = _validate_hash(sibling, "proof hash")
            if direction == "left":
                current = hashlib.sha256(sibling_bytes + current).digest()
            else:
                current = hashlib.sha256(current + sibling_bytes).digest()
            position //= 2

        _validate_hash(root, "root")
        return current.hex() == root.lower()
    except (TypeError, ValueError, KeyError):
        return False


def compute_checkpoint_digest(
    merkle_root: str,
    latest_entry_hash: str,
    total_entries: int,
) -> str:
    """Build China-main-compatible deterministic checkpoint digest.

    Signing is intentionally outside this module. The digest uses the exact
    ``merkle_root:latest_entry_hash:total_entries`` UTF-8 convention from
    China-main and returns a ``0x``-prefixed SHA-256 hex string.
    """
    _validate_hash(merkle_root, "merkle_root")
    _validate_hash(latest_entry_hash, "latest_entry_hash")
    if not isinstance(total_entries, int) or isinstance(total_entries, bool) or total_entries < 0:
        raise ValueError("total_entries must be a non-negative integer")
    payload = f"{merkle_root.lower()}:{latest_entry_hash.lower()}:{total_entries}".encode()
    return "0x" + hashlib.sha256(payload).hexdigest()
