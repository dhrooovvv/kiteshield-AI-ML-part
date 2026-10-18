"""
KiteShield Wallet — Input Normalization Unit Tests

Tests the validation and normalization of transaction proposals.
Verifies SEC-001: Model output is treated as untrusted input.
"""

import pytest
from pydantic import ValidationError

from app.schemas import (
    AgentProposalRequest,
    NormalizedAction,
    validate_eth_address,
)


class TestEthAddressValidation:
    """Test Ethereum address validation and checksumming."""

    def test_valid_lowercase_address(self):
        """Valid lowercase address should be checksummed."""
        addr = "0x742d35cc6634c0532925a3b844bc9e7595f2bd1e"
        result = validate_eth_address(addr)
        assert result.startswith("0x")
        assert len(result) == 42
        from web3 import Web3

        assert Web3.is_checksum_address(result)

    def test_valid_checksummed_address(self):
        """Already checksummed address should pass."""
        addr = "0x742d35Cc6634C0532925a3b844Bc9e7595f2bD1e"
        result = validate_eth_address(addr)
        assert result.startswith("0x")

    def test_invalid_too_short(self):
        """Address too short should fail."""
        with pytest.raises(ValueError, match="Invalid Ethereum address"):
            validate_eth_address("0x742d35")

    def test_invalid_no_prefix(self):
        """Address without 0x prefix should fail."""
        with pytest.raises(ValueError, match="Invalid Ethereum address"):
            validate_eth_address("742d35Cc6634C0532925a3b844Bc9e7595f2bD1e")

    def test_invalid_characters(self):
        """Address with invalid characters should fail."""
        with pytest.raises(ValueError, match="Invalid Ethereum address"):
            validate_eth_address("0xGGGd35Cc6634C0532925a3b844Bc9e7595f2bD1e")

    def test_empty_string(self):
        """Empty string should fail."""
        with pytest.raises(ValueError, match="Invalid Ethereum address"):
            validate_eth_address("")

    def test_zero_address(self):
        """Zero address should be valid (used as burn address)."""
        result = validate_eth_address("0x0000000000000000000000000000000000000000")
        assert result == "0x0000000000000000000000000000000000000000"


class TestAgentProposalRequest:
    """Test proposal request validation — SEC-001 enforcement."""

    def test_valid_proposal(self):
        """Valid proposal should parse successfully."""
        req = AgentProposalRequest(
            prompt="Send 0.01 ETH to test address",
            recipient="0x742d35Cc6634C0532925a3b844Bc9e7595f2bD1e",
            amount_wei="10000000000000000",
            chain_id=11155111,
        )
        assert int(req.amount_wei) == 10000000000000000
        assert req.chain_id == 11155111

    def test_reject_negative_amount(self):
        """Negative amount must be rejected."""
        with pytest.raises(ValidationError, match="positive"):
            AgentProposalRequest(
                prompt="Send ETH",
                recipient="0x742d35Cc6634C0532925a3b844Bc9e7595f2bD1e",
                amount_wei="-1",
            )

    def test_reject_zero_amount(self):
        """Zero amount must be rejected."""
        with pytest.raises(ValidationError, match="positive"):
            AgentProposalRequest(
                prompt="Send ETH",
                recipient="0x742d35Cc6634C0532925a3b844Bc9e7595f2bD1e",
                amount_wei="0",
            )

    def test_reject_float_amount(self):
        """Float amount must be rejected (no implicit conversion)."""
        with pytest.raises(ValidationError, match="integer"):
            AgentProposalRequest(
                prompt="Send ETH",
                recipient="0x742d35Cc6634C0532925a3b844Bc9e7595f2bD1e",
                amount_wei="1.5",
            )

    def test_reject_wrong_chain_id(self):
        """Non-Sepolia chain ID must be rejected."""
        with pytest.raises(ValidationError, match="11155111"):
            AgentProposalRequest(
                prompt="Send ETH",
                recipient="0x742d35Cc6634C0532925a3b844Bc9e7595f2bD1e",
                amount_wei="1000000000000000",
                chain_id=1,  # Mainnet — not allowed
            )

    def test_reject_invalid_recipient(self):
        """Invalid recipient address must be rejected."""
        with pytest.raises(ValidationError, match="Invalid Ethereum"):
            AgentProposalRequest(
                prompt="Send ETH",
                recipient="not-an-address",
                amount_wei="1000000000000000",
            )

    def test_reject_empty_prompt(self):
        """Empty prompt must be rejected."""
        with pytest.raises(ValidationError):
            AgentProposalRequest(
                prompt="",
                recipient="0x742d35Cc6634C0532925a3b844Bc9e7595f2bD1e",
                amount_wei="1000000000000000",
            )

    def test_reject_oversized_prompt(self):
        """Prompt exceeding max length must be rejected."""
        with pytest.raises(ValidationError):
            AgentProposalRequest(
                prompt="x" * 2001,
                recipient="0x742d35Cc6634C0532925a3b844Bc9e7595f2bD1e",
                amount_wei="1000000000000000",
            )

    def test_reject_insanely_large_amount(self):
        """Amount exceeding sanity cap must be rejected."""
        with pytest.raises(ValidationError, match="sanity cap"):
            AgentProposalRequest(
                prompt="Send all ETH",
                recipient="0x742d35Cc6634C0532925a3b844Bc9e7595f2bD1e",
                amount_wei="99999999999999999999999999",  # > 10^24
            )

    def test_amount_normalized_to_string(self):
        """Amount with leading zeros should normalize to clean integer string."""
        req = AgentProposalRequest(
            prompt="Send ETH",
            recipient="0x742d35Cc6634C0532925a3b844Bc9e7595f2bD1e",
            amount_wei="00100",
        )
        assert req.amount_wei == "100"


class TestNormalizedAction:
    """Test canonical representation and digest computation."""

    def test_canonical_string_format(self):
        """Canonical string should follow defined format."""
        action = NormalizedAction(
            proposal_id="test-id",
            correlation_id="test-corr",
            recipient="0x742d35Cc6634C0532925a3b844Bc9e7595f2bD1e",
            amount_wei=10000000000000000,
            chain_id=11155111,
        )
        nonce = "test-nonce"
        canonical = action.canonical_string(nonce)
        assert canonical == (
            "11155111:NATIVE_ETH:"
            "0x742d35cc6634c0532925a3b844bc9e7595f2bd1e:"
            "10000000000000000:test-nonce"
        )

    def test_digest_deterministic(self):
        """Same input should always produce same digest."""
        action = NormalizedAction(
            proposal_id="test-id",
            correlation_id="test-corr",
            recipient="0x742d35Cc6634C0532925a3b844Bc9e7595f2bD1e",
            amount_wei=10000000000000000,
        )
        nonce = "test-nonce"
        d1 = action.compute_digest(nonce)
        d2 = action.compute_digest(nonce)
        assert d1 == d2
        assert len(d1) == 64  # SHA-256 hex

    def test_different_nonce_different_digest(self):
        """Different nonces should produce different digests."""
        action = NormalizedAction(
            proposal_id="test-id",
            correlation_id="test-corr",
            recipient="0x742d35Cc6634C0532925a3b844Bc9e7595f2bD1e",
            amount_wei=10000000000000000,
        )
        d1 = action.compute_digest("nonce-1")
        d2 = action.compute_digest("nonce-2")
        assert d1 != d2

    def test_different_recipient_different_digest(self):
        """Different recipients should produce different digests."""
        a1 = NormalizedAction(
            proposal_id="test-id",
            correlation_id="test-corr",
            recipient="0x742d35Cc6634C0532925a3b844Bc9e7595f2bD1e",
            amount_wei=10000000000000000,
        )
        a2 = NormalizedAction(
            proposal_id="test-id",
            correlation_id="test-corr",
            recipient="0x0000000000000000000000000000000000000001",
            amount_wei=10000000000000000,
        )
        nonce = "same-nonce"
        assert a1.compute_digest(nonce) != a2.compute_digest(nonce)

    def test_different_amount_different_digest(self):
        """Different amounts should produce different digests."""
        a1 = NormalizedAction(
            proposal_id="test-id",
            correlation_id="test-corr",
            recipient="0x742d35Cc6634C0532925a3b844Bc9e7595f2bD1e",
            amount_wei=10000000000000000,
        )
        a2 = NormalizedAction(
            proposal_id="test-id",
            correlation_id="test-corr",
            recipient="0x742d35Cc6634C0532925a3b844Bc9e7595f2bD1e",
            amount_wei=20000000000000000,
        )
        nonce = "same-nonce"
        assert a1.compute_digest(nonce) != a2.compute_digest(nonce)

    def test_eth_display_amount(self):
        """Human-readable ETH should be correctly formatted."""
        action = NormalizedAction(
            proposal_id="test-id",
            correlation_id="test-corr",
            recipient="0x742d35Cc6634C0532925a3b844Bc9e7595f2bD1e",
            amount_wei=10000000000000000,  # 0.01 ETH
        )
        assert action.amount_eth == "0.01"

    def test_action_digest_without_nonce(self):
        """Action digest without nonce should be deterministic."""
        action = NormalizedAction(
            proposal_id="test-id",
            correlation_id="test-corr",
            recipient="0x742d35Cc6634C0532925a3b844Bc9e7595f2bD1e",
            amount_wei=10000000000000000,
        )
        d1 = action.action_digest_without_nonce()
        d2 = action.action_digest_without_nonce()
        assert d1 == d2
        assert len(d1) == 64
