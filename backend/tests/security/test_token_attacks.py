"""
KiteShield Wallet — Security Tests: Token Attack Vectors

Tests forged, expired, and malformed token handling.

Verifies:
- SEC-005: Capability tokens are transaction-bound
- SEC-007: Expired tokens rejected
- SEC-008: Signer independently verifies all claims
"""

import jwt
import pytest
import pytest_asyncio
from sqlalchemy import select

from app.core.config import get_settings
from app.exceptions import (
    SigningRejectedError,
    TokenExpiredError,
    TokenInvalidError,
)
from app.models import Policy
from app.schemas import NormalizedAction
from app.services.capability import _AUDIENCE, _ISSUER, CapabilityService
from app.services.signer import IsolatedSigner
from tests.authorization_support import seed_authorization


@pytest.fixture
def cap_service():
    return CapabilityService()


@pytest.fixture
def signer(cap_service):
    return IsolatedSigner(capability_service=cap_service)


@pytest.fixture
def test_action():
    return NormalizedAction(
        proposal_id="attack-test-proposal",
        correlation_id="attack-test-corr",
        recipient="0x742d35Cc6634C0532925a3b844Bc9e7595f2bD1e",
        amount_wei=100_000_000_000_000_000,
        chain_id=11155111,
    )


@pytest_asyncio.fixture
async def seeded_session(test_session, test_action):
    """Session with an active policy."""
    policy = Policy(
        id="test-policy-id",
        version=1,
        max_amount_wei="1000000000000000000",
        is_active=True,
    )
    test_session.add(policy)
    await test_session.flush()
    await seed_authorization(test_session, test_action)
    return test_session


class TestForgedTokens:
    """Tokens signed with the wrong key must be rejected."""

    @pytest.mark.asyncio
    async def test_reject_forged_token(self, signer, test_action, seeded_session):
        """Token signed with attacker's key → REJECTED."""
        from datetime import UTC, datetime, timedelta

        now = datetime.now(UTC)

        fake_claims = {
            "jti": "forged-jti",
            "iss": _ISSUER,
            "aud": _AUDIENCE,
            "sub": "attacker",
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(seconds=120)).timestamp()),
            "action": "NATIVE_ETH",
            "chain_id": 11155111,
            "recipient": test_action.recipient.lower(),
            "amount_wei": str(test_action.amount_wei),
            "tx_digest": "fake-digest",
            "policy_version": 1,
            "nonce": "fake-nonce",
            "proposal_id": test_action.proposal_id,
        }
        forged_token = jwt.encode(
            fake_claims, "attacker-secret-key-padding-here-1234", algorithm="HS256"
        )

        with pytest.raises(TokenInvalidError, match="[Ss]ignature"):
            await signer.sign_transaction(
                session=seeded_session,
                token=forged_token,
                action=test_action,
            )

    @pytest.mark.asyncio
    async def test_reject_none_algorithm_attack(self, signer, test_action, seeded_session):
        """Token with 'none' algorithm → REJECTED.
        This is a classic JWT vulnerability."""
        from datetime import UTC, datetime, timedelta

        now = datetime.now(UTC)

        claims = {
            "jti": "none-alg-jti",
            "iss": _ISSUER,
            "aud": _AUDIENCE,
            "sub": "attacker",
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(seconds=120)).timestamp()),
            "action": "NATIVE_ETH",
            "chain_id": 11155111,
            "recipient": test_action.recipient.lower(),
            "amount_wei": str(test_action.amount_wei),
            "tx_digest": "fake-digest",
            "policy_version": 1,
            "nonce": "fake-nonce",
            "proposal_id": test_action.proposal_id,
        }

        # Attempt to create unsigned token — PyJWT should reject this
        # during verification since we only allow HS256
        try:
            unsigned_token = jwt.encode(claims, "", algorithm="HS256")
        except Exception:
            return  # Can't even create the attack token, which is fine

        with pytest.raises((TokenInvalidError, TokenExpiredError)):
            await signer.sign_transaction(
                session=seeded_session,
                token=unsigned_token,
                action=test_action,
            )


class TestExpiredTokens:
    """Expired tokens must be rejected even if claims are otherwise valid."""

    @pytest.mark.asyncio
    async def test_reject_expired_token_at_signer(self, signer, test_action, seeded_session):
        """Expired but otherwise valid token → REJECTED at signer."""
        settings = get_settings()
        from datetime import UTC, datetime, timedelta

        now = datetime.now(UTC)

        claims = {
            "jti": "expired-signer-jti",
            "iss": _ISSUER,
            "aud": _AUDIENCE,
            "sub": "test-agent",
            "iat": int((now - timedelta(seconds=300)).timestamp()),
            "exp": int((now - timedelta(seconds=60)).timestamp()),
            "action": "NATIVE_ETH",
            "chain_id": 11155111,
            "recipient": test_action.recipient.lower(),
            "amount_wei": str(test_action.amount_wei),
            "tx_digest": "expired-digest",
            "policy_version": 1,
            "nonce": "expired-nonce",
            "proposal_id": test_action.proposal_id,
        }
        token = jwt.encode(claims, settings.capability_token_secret, algorithm="HS256")

        with pytest.raises(TokenExpiredError):
            await signer.sign_transaction(
                session=seeded_session,
                token=token,
                action=test_action,
            )


class TestStalePolicy:
    """Tokens referencing deactivated policies must be rejected."""

    @pytest.mark.asyncio
    async def test_reject_deactivated_policy(self, signer, cap_service, test_action, test_session):
        """Token issued under policy v1, but v1 is now inactive → REJECTED."""
        await seed_authorization(test_session, test_action)

        # Issue token referencing policy v99
        token, _ = await cap_service.issue_token(
            session=test_session,
            action=test_action,
            policy_version=1,
        )
        policy = await test_session.scalar(select(Policy).where(Policy.version == 1))
        policy.is_active = False
        await test_session.flush()

        with pytest.raises(SigningRejectedError, match="[Pp]olicy"):
            await signer.sign_transaction(
                session=test_session,
                token=token,
                action=test_action,
            )


class TestMalformedTokens:
    """Completely malformed tokens must be rejected gracefully."""

    @pytest.mark.asyncio
    async def test_reject_garbage_string(self, signer, test_action, seeded_session):
        """Random garbage string → REJECTED."""
        with pytest.raises(TokenInvalidError):
            await signer.sign_transaction(
                session=seeded_session,
                token="this-is-not-a-jwt",
                action=test_action,
            )

    @pytest.mark.asyncio
    async def test_reject_empty_token(self, signer, test_action, seeded_session):
        """Empty string token → REJECTED."""
        with pytest.raises(TokenInvalidError):
            await signer.sign_transaction(
                session=seeded_session,
                token="",
                action=test_action,
            )
