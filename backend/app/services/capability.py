"""
KiteShield Wallet — Capability Authorization Service

Issues narrowly-scoped JWT capability tokens that authorize exactly
one transaction action.

Security invariants enforced:
- SI-5: Approval bound to exact action (action_digest checked)
- SI-6: Tokens are single-use (DB consumption record)
- SI-8: Parameter changes invalidate authorization (tx_digest binding)

Token spec (see ADR-003):
- Format: JWT (RFC 7519)
- Algorithm: HS256
- Lifetime: configurable (default 120s)
- Single-use: enforced by DB consumption record
"""

import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.exceptions import (
    ApprovalRequiredError,
    TokenExpiredError,
    TokenInvalidError,
)
from app.models import CapabilityToken, ExecutionAttempt
from app.schemas import NormalizedAction
from app.services.authorization import validate_authorization
from app.services.emergency_stop import EmergencyStopService
from app.services.execution_lock import lock_execution

logger = get_logger("capability")
emergency_stop_service = EmergencyStopService()

# JWT constants
_ISSUER = "kiteshield-capability-service"
_AUDIENCE = "kiteshield-signer"


def _build_claims(
    action: NormalizedAction,
    nonce: str,
    tx_digest: str,
    policy_version: int,
    approval_id: str | None = None,
    agent_id: str = "default-agent",
) -> dict[str, Any]:
    """Build JWT claims for a capability token.

    All security-relevant fields are bound into the token.
    """
    settings = get_settings()
    now = datetime.now(UTC)
    exp = now + timedelta(seconds=settings.capability_token_ttl_seconds)

    return {
        # Standard JWT claims
        "jti": str(uuid.uuid4()),
        "iss": _ISSUER,
        "aud": _AUDIENCE,
        "sub": agent_id,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
        # KiteShield-specific claims
        "action": action.action_type.value,
        "chain_id": action.chain_id,
        "recipient": action.recipient.lower(),
        "amount_wei": str(action.amount_wei),
        "tx_digest": tx_digest,
        "policy_version": policy_version,
        "approval_id": approval_id,
        "nonce": nonce,
        "proposal_id": action.proposal_id,
    }


class CapabilityService:
    """Issues and manages capability authorization tokens.

    Responsibilities:
    - Validate preconditions (policy decision, approval if escalated)
    - Build transaction-bound JWT claims
    - Sign tokens with HS256
    - Record token metadata for replay protection
    """

    async def issue_token(
        self,
        session: AsyncSession,
        action: NormalizedAction,
        policy_version: int,
        approval_id: str | None = None,
        requires_approval: bool = False,
    ) -> tuple[str, dict[str, Any]]:
        """Issue a capability token for an authorized action.

        Args:
            action: The normalized action to authorize
            policy_version: Version of the policy that allowed/escalated this
            approval_id: Approval record ID (required if requires_approval=True)
            requires_approval: Whether this action was escalated

        Returns:
            Tuple of (jwt_token_string, claims_dict)

        Raises:
            ApprovalRequiredError: If requires_approval but no approval_id
            AuthorizationError: If preconditions are not met
        """
        await lock_execution(session)
        await emergency_stop_service.require_running(session)

        # Validate escalation has approval
        if requires_approval and not approval_id:
            raise ApprovalRequiredError(
                "Escalated action requires human approval before token issuance"
            )
        await validate_authorization(session, action, policy_version, approval_id)
        attempt = await session.scalar(
            select(ExecutionAttempt).where(ExecutionAttempt.proposal_id == action.proposal_id)
        )
        if attempt is None or attempt.status != "PREPARED":
            raise TokenInvalidError("A reserved execution envelope is required")

        # Generate nonce and compute transaction digest
        nonce = str(uuid.uuid4())
        tx_digest = action.compute_digest(nonce)

        # Build claims
        claims = _build_claims(
            action=action,
            nonce=nonce,
            tx_digest=tx_digest,
            policy_version=policy_version,
            approval_id=approval_id,
        )
        claims["execution_id"] = attempt.id
        claims["envelope_digest"] = hashlib.sha256(attempt.envelope.encode()).hexdigest()
        if approval_id:
            from app.models import ApprovalRequest

            approval = await session.get(ApprovalRequest, approval_id)
            if approval is None:
                raise ApprovalRequiredError("Approval is unavailable")
            claims["exp"] = min(
                claims["exp"], int(datetime.fromisoformat(approval.expires_at).timestamp())
            )

        # Sign token
        settings = get_settings()
        token = jwt.encode(
            claims,
            settings.capability_token_secret,
            algorithm="HS256",
        )
        session.add(
            CapabilityToken(
                jti=claims["jti"],
                proposal_id=action.proposal_id,
                tx_digest=tx_digest,
                consumed=False,
                expires_at=datetime.fromtimestamp(claims["exp"], tz=UTC).isoformat(),
            )
        )
        await session.flush()

        logger.info(
            "Capability token issued: jti=%s, proposal=%s, recipient=%s, amount=%s, expires_in=%ds",
            claims["jti"],
            action.proposal_id,
            claims["recipient"],
            claims["amount_wei"],
            settings.capability_token_ttl_seconds,
        )

        return token, claims

    def verify_token(self, token: str) -> dict[str, Any]:
        """Verify a capability token's signature and basic claims.

        This is the FIRST verification step. The signer performs
        additional checks (parameter matching, consumption, etc.).

        Args:
            token: JWT token string

        Returns:
            Decoded claims dictionary

        Raises:
            TokenExpiredError: Token has expired
            TokenInvalidError: Signature invalid or claims malformed
        """
        settings = get_settings()

        try:
            claims = jwt.decode(
                token,
                settings.capability_token_secret,
                algorithms=["HS256"],
                issuer=_ISSUER,
                audience=_AUDIENCE,
                leeway=0,
                options={
                    "require": [
                        "jti",
                        "iss",
                        "aud",
                        "sub",
                        "iat",
                        "exp",
                        "action",
                        "chain_id",
                        "recipient",
                        "amount_wei",
                        "tx_digest",
                        "policy_version",
                        "nonce",
                        "proposal_id",
                    ],
                },
            )
        except jwt.ExpiredSignatureError as e:
            raise TokenExpiredError("Capability token has expired") from e
        except jwt.InvalidIssuerError as e:
            raise TokenInvalidError(f"Invalid token issuer (expected '{_ISSUER}')") from e
        except jwt.InvalidAudienceError as e:
            raise TokenInvalidError(f"Invalid token audience (expected '{_AUDIENCE}')") from e
        except jwt.InvalidSignatureError as e:
            raise TokenInvalidError("Invalid token signature — possible forgery attempt") from e
        except jwt.DecodeError as e:
            raise TokenInvalidError(f"Token decode error: {e}") from e
        except jwt.MissingRequiredClaimError as e:
            raise TokenInvalidError(f"Missing required claim: {e}") from e
        except jwt.InvalidTokenError as e:
            raise TokenInvalidError(f"Invalid token: {e}") from e

        # Validate chain ID
        if claims.get("chain_id") != 11155111:
            raise TokenInvalidError(
                f"Token chain_id {claims.get('chain_id')} does not match Sepolia (11155111)"
            )
        if (
            any(
                not isinstance(claims.get(key), str) or not claims[key]
                for key in ("jti", "proposal_id", "nonce", "tx_digest", "recipient", "amount_wei")
            )
            or type(claims.get("policy_version")) is not int
            or not claims["amount_wei"].isdigit()
            or int(claims["amount_wei"]) <= 0
        ):
            raise TokenInvalidError("Malformed authorization claims")
        if claims.get("approval_id") is not None and not isinstance(claims["approval_id"], str):
            raise TokenInvalidError("Malformed approval claim")

        logger.info(
            "Capability token verified: jti=%s, proposal=%s",
            claims["jti"],
            claims["proposal_id"],
        )

        return claims
