"""Unit tests for pure audit Merkle and checkpoint utilities."""

import hashlib

import pytest

from app.services.audit_integrity import (
    compute_checkpoint_digest,
    compute_merkle_root,
    generate_inclusion_proof,
    verify_inclusion_proof,
)


def leaf(number: int) -> str:
    return hashlib.sha256(f"leaf-{number}".encode()).hexdigest()


def test_empty_tree_matches_china_convention():
    expected = hashlib.sha256(b"KITESHIELD_EMPTY_AUDIT_TREE").hexdigest()
    assert compute_merkle_root([]) == expected


def test_single_leaf_root_and_empty_proof():
    value = leaf(0)
    assert compute_merkle_root([value]) == value
    proof = generate_inclusion_proof([value], 0)
    assert proof == []
    assert verify_inclusion_proof(value, 0, proof, value, 1)


@pytest.mark.parametrize("count", [2, 4, 6])
def test_even_leaf_counts_have_valid_proofs(count):
    leaves = [leaf(index) for index in range(count)]
    root = compute_merkle_root(leaves)
    for index, value in enumerate(leaves):
        proof = generate_inclusion_proof(leaves, index)
        assert verify_inclusion_proof(value, index, proof, root, count)


def test_odd_leaf_count_duplicates_final_node_and_proofs_verify():
    leaves = [leaf(index) for index in range(3)]
    root = compute_merkle_root(leaves)
    proof = generate_inclusion_proof(leaves, 2)
    assert proof[0]["position"] == "right"
    assert proof[0]["hash"] == leaves[2]
    assert verify_inclusion_proof(leaves[2], 2, proof, root, len(leaves))


def test_roots_and_proofs_are_deterministic():
    leaves = [leaf(index) for index in range(5)]
    assert compute_merkle_root(leaves) == compute_merkle_root(list(leaves))
    assert generate_inclusion_proof(leaves, 3) == generate_inclusion_proof(leaves, 3)


@pytest.mark.parametrize("index", [-1, 3])
def test_invalid_generation_indexes_are_rejected(index):
    with pytest.raises(ValueError):
        generate_inclusion_proof([leaf(0), leaf(1), leaf(2)], index)


def test_invalid_proofs_and_modified_leaves_fail_safely():
    leaves = [leaf(index) for index in range(3)]
    root = compute_merkle_root(leaves)
    proof = generate_inclusion_proof(leaves, 1)

    assert not verify_inclusion_proof(leaf(99), 1, proof, root, 3)
    assert not verify_inclusion_proof(leaves[1], 0, proof, root, 3)
    assert not verify_inclusion_proof(leaves[1], 1, [], root, 3)
    malformed = [dict(proof[0], hash="not-a-hash"), *proof[1:]]
    assert not verify_inclusion_proof(leaves[1], 1, malformed, root, 3)
    assert not verify_inclusion_proof(leaves[1], 1, proof, leaf(99), 3)


def test_invalid_tree_sizes_and_empty_proofs_fail():
    value = leaf(0)
    assert not verify_inclusion_proof(value, 0, [], value, 0)
    with pytest.raises(ValueError):
        generate_inclusion_proof([], 0)


def test_checkpoint_digest_is_deterministic_and_prefixed():
    root = compute_merkle_root([leaf(0), leaf(1)])
    digest_a = compute_checkpoint_digest(root, leaf(1), 2)
    digest_b = compute_checkpoint_digest(root, leaf(1), 2)
    assert digest_a == digest_b
    assert digest_a.startswith("0x")
    assert len(digest_a) == 66


def test_checkpoint_digest_rejects_invalid_inputs():
    with pytest.raises(ValueError):
        compute_checkpoint_digest("bad", leaf(1), 2)
    with pytest.raises(ValueError):
        compute_checkpoint_digest(leaf(0), leaf(1), -1)
