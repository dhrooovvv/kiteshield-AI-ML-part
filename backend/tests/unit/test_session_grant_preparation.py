"""Bonus groundwork is deterministic and cannot authorize execution."""

import pytest

from scripts.prepare_session_grant import build_manifest


def example():
    return dict(
        wallet="0x" + "11" * 20,
        session_address="0x" + "22" * 20,
        recipient="0x" + "33" * 20,
        max_payment_wei="100",
        total_budget_wei="200",
        valid_after=100,
        valid_until=200,
        grant_nonce=0,
        policy_version=1,
    )


def test_unsigned_manifest_binds_scope_context_and_contract():
    first = build_manifest(**example())
    assert first == build_manifest(**example())
    assert first["status"] == "UNSIGNED_NOT_EXECUTABLE"
    assert first["onchain_verifier_implemented"] is False
    assert first["erc4337_implemented"] is False
    for change in (
        {"recipient": "0x" + "44" * 20},
        {"grant_nonce": 1},
        {"policy_version": 2},
        {"wallet": "0x" + "55" * 20},
    ):
        assert build_manifest(**(example() | change))["digest"] != first["digest"]


@pytest.mark.parametrize(
    "change",
    [
        {"valid_until": 5000},
        {"max_payment_wei": "300"},
        {"grant_nonce": -1},
        {"total_budget_wei": "-2"},
        {"recipient": "0x" + "00" * 20},
    ],
)
def test_unbounded_or_invalid_grants_rejected(change):
    with pytest.raises(ValueError):
        build_manifest(**(example() | change))
