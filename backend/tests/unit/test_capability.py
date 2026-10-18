"""
KiteShield Wallet — Capability Token Unit Tests

Tests JWT capability token issuance and verification.
Verifies SEC-005 (transaction-bound tokens), SEC-007 (expired rejected).
"""

import jwt
import pytest

from app.core.config import get_settings
from app.exceptions import (
    ApprovalRequiredError,
    TokenExpiredError,
    TokenInvalidError,
)
from app.schemas import NormalizedAction
from app.services.capability import _AUDIENCE, _ISSUER, CapabilityService
from tests.authorization_support import seed_authorization


@pytest.fixture(autouse=True)
async def authorized_context(test_session, test_action):
    await seed_authorization(test_session, test_action)


@pytest.fixture
def cap_service():
    """Fresh capability service instance."""
    return CapabilityService()


@pytest.fixture
def test_action():
    """Standard test action."""
    return NormalizedAction(
        proposal_id="test-proposal-123",
        correlation_id="test-corr-456",
        recipient="0x742d35Cc6634C0532925a3b844Bc9e7595f2bD1e",
        amount_wei=100_000_000_000_000_000,  # 0.1 ETH
        chain_id=11155111,
    )


class TestTokenIssuance:
    """Tests for capability token issuance."""

    @pytest.mark.asyncio
    async def test_issue_valid_token(self, cap_service, test_action, test_session):
        """Should issue a valid JWT with all required claims."""
        token, claims = await cap_service.issue_token(
            session=test_session,
            action=test_action,
            policy_version=1,
        )
        assert isinstance(token, str)
        assert len(token) > 0
        assert claims["iss"] == _ISSUER
        assert claims["aud"] == _AUDIENCE
        assert claims["action"] == "NATIVE_ETH"
        assert claims["chain_id"] == 11155111
        assert claims["recipient"] == test_action.recipient.lower()
        assert claims["amount_wei"] == str(test_action.amount_wei)
        assert claims["policy_version"] == 1
        assert claims["proposal_id"] == "test-proposal-123"
        assert "jti" in claims
        assert "nonce" in claims
        assert "tx_digest" in claims
        assert "iat" in claims
        assert "exp" in claims

    @pytest.mark.asyncio
    async def test_issue_requires_approval_id_for_escalated(
        self, cap_service, test_action, test_session
    ):
        """Escalated actions must have approval_id."""
        with pytest.raises(ApprovalRequiredError):
            await cap_service.issue_token(
                session=test_session,
                action=test_action,
                policy_version=1,
                requires_approval=True,
                approval_id=None,
            )

    @pytest.mark.asyncio
    async def test_issue_with_approval(self, cap_service, test_action, test_session):
        """Escalated action with valid approval → token issued."""
        await seed_authorization(test_session, test_action, approval_id="approval-789")
        token, claims = await cap_service.issue_token(
            session=test_session,
            action=test_action,
            policy_version=1,
            requires_approval=True,
            approval_id="approval-789",
        )
        assert claims["approval_id"] == "approval-789"

    @pytest.mark.asyncio
    async def test_different_actions_produce_different_digests(self, cap_service, test_session):
        """Different recipients should produce different tx_digests."""
        action1 = NormalizedAction(
            proposal_id="p1",
            correlation_id="c1",
            recipient="0x742d35Cc6634C0532925a3b844Bc9e7595f2bD1e",
            amount_wei=100,
        )
        action2 = NormalizedAction(
            proposal_id="p2",
            correlation_id="c2",
            recipient="0x0000000000000000000000000000000000000001",
            amount_wei=100,
        )
        await seed_authorization(test_session, action1)
        await seed_authorization(test_session, action2)
        _, claims1 = await cap_service.issue_token(test_session, action1, policy_version=1)
        _, claims2 = await cap_service.issue_token(test_session, action2, policy_version=1)
        assert claims1["tx_digest"] != claims2["tx_digest"]

    @pytest.mark.asyncio
    async def test_unique_jti_per_issuance(self, cap_service, test_action, test_session):
        """Each token should have a unique JTI."""
        _, c1 = await cap_service.issue_token(test_session, test_action, policy_version=1)
        _, c2 = await cap_service.issue_token(test_session, test_action, policy_version=1)
        assert c1["jti"] != c2["jti"]


class TestTokenVerification:
    """Tests for capability token verification."""

    @pytest.mark.asyncio
    async def test_verify_valid_token(self, cap_service, test_action, test_session):
        """Valid token should verify successfully."""
        token, expected_claims = await cap_service.issue_token(
            session=test_session,
            action=test_action,
            policy_version=1,
        )
        verified = cap_service.verify_token(token)
        assert verified["jti"] == expected_claims["jti"]
        assert verified["recipient"] == expected_claims["recipient"]
        assert verified["amount_wei"] == expected_claims["amount_wei"]

    def test_reject_expired_token(self, cap_service, test_action):
        """Expired token → TokenExpiredError."""
        settings = get_settings()
        # Manually create an already-expired token
        from datetime import UTC, datetime, timedelta

        now = datetime.now(UTC)
        claims = {
            "jti": "expired-jti",
            "iss": _ISSUER,
            "aud": _AUDIENCE,
            "sub": "test-agent",
            "iat": int((now - timedelta(seconds=300)).timestamp()),
            "exp": int((now - timedelta(seconds=60)).timestamp()),  # Expired
            "action": "NATIVE_ETH",
            "chain_id": 11155111,
            "recipient": "0x742d35cc6634c0532925a3b844bc9e7595f2bd1e",
            "amount_wei": "100",
            "tx_digest": "abc123",
            "policy_version": 1,
            "nonce": "test-nonce",
            "proposal_id": "test-prop",
        }
        token = jwt.encode(claims, settings.capability_token_secret, algorithm="HS256")

        with pytest.raises(TokenExpiredError):
            cap_service.verify_token(token)

    def test_reject_wrong_signature(self, cap_service):
        """Token signed with wrong key → TokenInvalidError."""
        from datetime import UTC, datetime, timedelta

        now = datetime.now(UTC)
        claims = {
            "jti": "wrong-sig-jti",
            "iss": _ISSUER,
            "aud": _AUDIENCE,
            "sub": "test-agent",
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(seconds=120)).timestamp()),
            "action": "NATIVE_ETH",
            "chain_id": 11155111,
            "recipient": "0x742d35cc6634c0532925a3b844bc9e7595f2bd1e",
            "amount_wei": "100",
            "tx_digest": "abc123",
            "policy_version": 1,
            "nonce": "test-nonce",
            "proposal_id": "test-prop",
        }
        # Sign with a different key
        token = jwt.encode(claims, "wrong-secret-key" * 4, algorithm="HS256")

        with pytest.raises(TokenInvalidError, match="signature"):
            cap_service.verify_token(token)

    def test_reject_wrong_issuer(self, cap_service):
        """Token with wrong issuer → TokenInvalidError."""
        settings = get_settings()
        from datetime import UTC, datetime, timedelta

        now = datetime.now(UTC)
        claims = {
            "jti": "wrong-iss-jti",
            "iss": "evil-issuer",  # Wrong issuer
            "aud": _AUDIENCE,
            "sub": "test-agent",
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(seconds=120)).timestamp()),
            "action": "NATIVE_ETH",
            "chain_id": 11155111,
            "recipient": "0x742d35cc6634c0532925a3b844bc9e7595f2bd1e",
            "amount_wei": "100",
            "tx_digest": "abc123",
            "policy_version": 1,
            "nonce": "test-nonce",
            "proposal_id": "test-prop",
        }
        token = jwt.encode(claims, settings.capability_token_secret, algorithm="HS256")

        with pytest.raises(TokenInvalidError, match="issuer"):
            cap_service.verify_token(token)

    def test_reject_wrong_audience(self, cap_service):
        """Token with wrong audience → TokenInvalidError."""
        settings = get_settings()
        from datetime import UTC, datetime, timedelta

        now = datetime.now(UTC)
        claims = {
            "jti": "wrong-aud-jti",
            "iss": _ISSUER,
            "aud": "evil-audience",  # Wrong audience
            "sub": "test-agent",
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(seconds=120)).timestamp()),
            "action": "NATIVE_ETH",
            "chain_id": 11155111,
            "recipient": "0x742d35cc6634c0532925a3b844bc9e7595f2bd1e",
            "amount_wei": "100",
            "tx_digest": "abc123",
            "policy_version": 1,
            "nonce": "test-nonce",
            "proposal_id": "test-prop",
        }
        token = jwt.encode(claims, settings.capability_token_secret, algorithm="HS256")

        with pytest.raises(TokenInvalidError, match="audience"):
            cap_service.verify_token(token)

    def test_reject_wrong_chain_id(self, cap_service):
        """Token with non-Sepolia chain_id → TokenInvalidError."""
        settings = get_settings()
        from datetime import UTC, datetime, timedelta

        now = datetime.now(UTC)
        claims = {
            "jti": "wrong-chain-jti",
            "iss": _ISSUER,
            "aud": _AUDIENCE,
            "sub": "test-agent",
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(seconds=120)).timestamp()),
            "action": "NATIVE_ETH",
            "chain_id": 1,  # Mainnet — not allowed
            "recipient": "0x742d35cc6634c0532925a3b844bc9e7595f2bd1e",
            "amount_wei": "100",
            "tx_digest": "abc123",
            "policy_version": 1,
            "nonce": "test-nonce",
            "proposal_id": "test-prop",
        }
        token = jwt.encode(claims, settings.capability_token_secret, algorithm="HS256")

        with pytest.raises(TokenInvalidError, match="chain_id"):
            cap_service.verify_token(token)

    def test_reject_missing_claims(self, cap_service):
        """Token with missing required claims → TokenInvalidError."""
        settings = get_settings()
        from datetime import UTC, datetime, timedelta

        now = datetime.now(UTC)
        claims = {
            "jti": "incomplete-jti",
            "iss": _ISSUER,
            "aud": _AUDIENCE,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(seconds=120)).timestamp()),
            # Missing: sub, action, chain_id, recipient, amount_wei, etc.
        }
        token = jwt.encode(claims, settings.capability_token_secret, algorithm="HS256")

        with pytest.raises(TokenInvalidError):
            cap_service.verify_token(token)
