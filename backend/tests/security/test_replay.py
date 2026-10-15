"""
KiteShield Wallet — Security Tests: Token Replay

Tests that consumed capability tokens cannot be reused.

Verifies:
- SEC-006: Tokens are single-use
"""

import pytest
import pytest_asyncio

from app.exceptions import TokenConsumedError
from app.models import Policy
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
def test_action():
    return NormalizedAction(
        proposal_id="replay-test-proposal",
        correlation_id="replay-test-corr",
        recipient="0x742d35Cc6634C0532925a3b844Bc9e7595f2bD1e",
        amount_wei=100_000_000_000_000_000,
        chain_id=11155111,
    )


@pytest_asyncio.fixture
async def seeded_session(test_session):
    """Session with an active policy for signer verification."""
    policy = Policy(
        id="test-policy-id",
        version=1,
        max_amount_wei="1000000000000000000",
        is_active=True,
    )
    test_session.add(policy)
    await test_session.flush()
    return test_session


class TestTokenReplay:
    """SEC-006: Tokens must be single-use. Replay must be detected."""

    @pytest.mark.asyncio
    async def test_first_use_succeeds(self, signer, cap_service, test_action, seeded_session):
        """First use of a valid token should succeed (signs the tx)."""
        token, claims = await cap_service.issue_token(
            session=seeded_session,
            action=test_action,
            policy_version=1,
        )

        # First use should succeed
        result = await signer.sign_transaction(
            session=seeded_session,
            token=token,
            action=test_action,
        )
        assert "tx_hash" in result
        assert "raw_transaction" in result

    @pytest.mark.asyncio
    async def test_second_use_rejected(self, signer, cap_service, test_action, seeded_session):
        """Second use of the same token → TokenConsumedError."""
        token, claims = await cap_service.issue_token(
            session=seeded_session,
            action=test_action,
            policy_version=1,
        )

        # First use succeeds
        await signer.sign_transaction(
            session=seeded_session,
            token=token,
            action=test_action,
        )

        # Second use MUST fail
        with pytest.raises(TokenConsumedError, match="[Cc]onsumed|[Rr]eplay"):
            await signer.sign_transaction(
                session=seeded_session,
                token=token,
                action=test_action,
            )

    @pytest.mark.asyncio
    async def test_different_tokens_for_same_action(
        self, signer, cap_service, test_action, seeded_session
    ):
        """Different tokens for the same action should each work once."""
        token1, _ = await cap_service.issue_token(
            session=seeded_session, action=test_action, policy_version=1
        )
        token2, _ = await cap_service.issue_token(
            session=seeded_session, action=test_action, policy_version=1
        )

        # Both should be different tokens
        assert token1 != token2

        # First token works
        result1 = await signer.sign_transaction(
            session=seeded_session,
            token=token1,
            action=test_action,
        )
        assert "tx_hash" in result1

        # Second token also works (it's a different token)
        result2 = await signer.sign_transaction(
            session=seeded_session,
            token=token2,
            action=test_action,
        )
        assert "tx_hash" in result2
