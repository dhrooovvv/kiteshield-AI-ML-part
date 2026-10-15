"""
KiteShield Wallet — Security Tests: Parameter Tampering

Tests that the signer rejects transactions where parameters have
been modified after capability token issuance.

Verifies:
- SEC-005: Capability tokens are transaction-bound
- SEC-011: Recipient substitution detected
- SEC-012: Amount manipulation detected
"""

import pytest

from app.exceptions import SigningRejectedError, TokenMismatchError
from app.schemas import NormalizedAction
from app.services.capability import CapabilityService
from app.services.signer import IsolatedSigner


@pytest.fixture
def cap_service():
    return CapabilityService()


@pytest.fixture
def signer(cap_service):
    return IsolatedSigner(capability_service=cap_service)


@pytest.fixture
def original_action():
    return NormalizedAction(
        proposal_id="tamper-test-proposal",
        correlation_id="tamper-test-corr",
        recipient="0x742d35Cc6634C0532925a3b844Bc9e7595f2bD1e",
        amount_wei=100_000_000_000_000_000,  # 0.1 ETH
        chain_id=11155111,
    )


class TestRecipientSubstitution:
    """SEC-011: Recipient substitution must be detected and rejected."""

    @pytest.mark.asyncio
    async def test_reject_different_recipient(
        self, signer, cap_service, original_action, test_session
    ):
        """Token for address A, transaction to address B → REJECTED."""
        # Issue token for original recipient
        token, claims = await cap_service.issue_token(
            session=test_session,
            action=original_action,
            policy_version=1,
        )

        # Create modified action with different recipient
        tampered_action = NormalizedAction(
            proposal_id="tamper-test-proposal",
            correlation_id="tamper-test-corr",
            recipient="0x0000000000000000000000000000000000000001",  # DIFFERENT
            amount_wei=100_000_000_000_000_000,
            chain_id=11155111,
        )

        with pytest.raises(TokenMismatchError, match="[Rr]ecipient"):
            await signer.sign_transaction(
                session=test_session,
                token=token,
                action=tampered_action,
            )


class TestAmountManipulation:
    """SEC-012: Amount manipulation must be detected and rejected."""

    @pytest.mark.asyncio
    async def test_reject_increased_amount(
        self, signer, cap_service, original_action, test_session
    ):
        """Token for 0.1 ETH, transaction for 10 ETH → REJECTED."""
        token, claims = await cap_service.issue_token(
            session=test_session,
            action=original_action,
            policy_version=1,
        )

        tampered_action = NormalizedAction(
            proposal_id="tamper-test-proposal",
            correlation_id="tamper-test-corr",
            recipient="0x742d35Cc6634C0532925a3b844Bc9e7595f2bD1e",
            amount_wei=10_000_000_000_000_000_000,  # 10 ETH — DIFFERENT
            chain_id=11155111,
        )

        with pytest.raises(TokenMismatchError, match="[Aa]mount"):
            await signer.sign_transaction(
                session=test_session,
                token=token,
                action=tampered_action,
            )

    @pytest.mark.asyncio
    async def test_reject_decreased_amount(
        self, signer, cap_service, original_action, test_session
    ):
        """Token for 0.1 ETH, transaction for 0.01 ETH → REJECTED.
        Even smaller amounts are rejected — the token authorizes EXACTLY one amount.
        """
        token, _ = await cap_service.issue_token(
            session=test_session,
            action=original_action,
            policy_version=1,
        )

        tampered_action = NormalizedAction(
            proposal_id="tamper-test-proposal",
            correlation_id="tamper-test-corr",
            recipient="0x742d35Cc6634C0532925a3b844Bc9e7595f2bD1e",
            amount_wei=10_000_000_000_000_000,  # 0.01 ETH — smaller but DIFFERENT
            chain_id=11155111,
        )

        with pytest.raises(TokenMismatchError, match="[Aa]mount"):
            await signer.sign_transaction(
                session=test_session,
                token=token,
                action=tampered_action,
            )


class TestChainIdSubstitution:
    """Signer must reject chain ID mismatches."""

    @pytest.mark.asyncio
    async def test_reject_wrong_chain_in_action(
        self, signer, cap_service, original_action, test_session
    ):
        """Token for Sepolia, action claims different chain → REJECTED."""
        token, _ = await cap_service.issue_token(
            session=test_session,
            action=original_action,
            policy_version=1,
        )

        tampered_action = NormalizedAction(
            proposal_id="tamper-test-proposal",
            correlation_id="tamper-test-corr",
            recipient="0x742d35Cc6634C0532925a3b844Bc9e7595f2bD1e",
            amount_wei=100_000_000_000_000_000,
            chain_id=1,  # Mainnet — DIFFERENT
        )

        with pytest.raises((TokenMismatchError, SigningRejectedError)):
            await signer.sign_transaction(
                session=test_session,
                token=token,
                action=tampered_action,
            )


class TestProposalIdMismatch:
    """Signer must reject proposal ID mismatches."""

    @pytest.mark.asyncio
    async def test_reject_different_proposal_id(
        self, signer, cap_service, original_action, test_session
    ):
        """Token for proposal A, signing request for proposal B → REJECTED."""
        token, _ = await cap_service.issue_token(
            session=test_session,
            action=original_action,
            policy_version=1,
        )

        tampered_action = NormalizedAction(
            proposal_id="DIFFERENT-proposal-id",  # DIFFERENT
            correlation_id="tamper-test-corr",
            recipient="0x742d35Cc6634C0532925a3b844Bc9e7595f2bD1e",
            amount_wei=100_000_000_000_000_000,
            chain_id=11155111,
        )

        with pytest.raises(TokenMismatchError):
            await signer.sign_transaction(
                session=test_session,
                token=token,
                action=tampered_action,
            )
