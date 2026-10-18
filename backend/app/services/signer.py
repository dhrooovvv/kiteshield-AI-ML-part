"""
KiteShield Wallet — Isolated Signer

Independently verifies capability tokens and transaction parameters
before signing. This is logical isolation inside the same process, not hardware/process isolation.

Security invariants enforced:
- SI-7: Signer independently verifies authorization
- SI-6: Tokens are single-use (atomic DB consumption)
- SI-8: Parameter changes invalidate authorization
- SI-9: Expired tokens rejected
- SI-10: Private keys never sent to browser or LLM
- SI-12: Fail-closed on missing/invalid authorization

The signer does NOT trust:
- The API's assertion that a transaction is authorized
- The frontend's transaction parameters
- The capability service's decision alone

The signer DOES verify:
1. JWT signature is valid (HS256)
2. Issuer == kiteshield-capability-service
3. Audience == kiteshield-signer
4. Token is not expired (with clock skew tolerance)
5. Chain ID matches Sepolia (11155111)
6. Recipient matches token claim
7. Amount matches token claim
8. Transaction digest matches recomputed digest
9. Token has not been previously consumed (DB check + atomic consumption)
10. Approval ID present if required
11. Policy version is still active
"""

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.exceptions import (
    SigningRejectedError,
    TokenConsumedError,
    TokenMismatchError,
)
from app.models import CapabilityToken, ExecutionAttempt, Policy, SpendingRecord
from app.schemas import NormalizedAction
from app.services.authorization import validate_authorization
from app.services.capability import CapabilityService
from app.services.emergency_stop import EmergencyStopService
from app.services.execution_lock import lock_execution

logger = get_logger("signer")
emergency_stop_service = EmergencyStopService()


class IsolatedSigner:
    """Independent transaction signer with full verification.

    This module is designed as a separate trust boundary.
    It re-verifies everything before signing.

    The private key is loaded once at construction and never
    exposed through any public method, response schema, or log.
    """

    def __init__(self, capability_service: CapabilityService):
        self._capability_service = capability_service
        self._private_key: str | None = None

    def _load_key(self) -> str:
        """Load the private key from configuration.

        Called lazily to avoid loading at import time.
        Key is cached in memory but never exposed.
        """
        if self._private_key is None:
            settings = get_settings()
            self._private_key = settings.signer_private_key
            logger.info("Signer key loaded (never logged or exposed)")
        return self._private_key

    async def sign_transaction(
        self,
        session: AsyncSession,
        token: str,
        action: NormalizedAction,
    ) -> dict[str, Any]:
        """Independently verify authorization and sign a transaction.

        This is the critical security gate. ALL checks must pass.

        Args:
            session: Database session for token consumption
            token: JWT capability token string
            action: The transaction action to sign

        Returns:
            Dict with signed transaction data and tx_hash

        Raises:
            TokenExpiredError: Token has expired
            TokenInvalidError: Token signature or claims invalid
            TokenConsumedError: Token already used (replay attempt)
            TokenMismatchError: Transaction params don't match token
            SigningRejectedError: Any other verification failure
        """
        await lock_execution(session)
        await emergency_stop_service.require_running(session)
        # ===== STEP 1: Verify JWT signature and basic claims =====
        # This re-verifies independently — does not trust API assertion
        claims = self._capability_service.verify_token(token)
        jti = claims["jti"]
        known_token = await session.get(CapabilityToken, jti, populate_existing=True)
        if known_token is not None and known_token.consumed:
            raise TokenConsumedError("Authorization already consumed")

        logger.info("Signer: verifying token jti=%s for proposal=%s", jti, claims["proposal_id"])

        # ===== STEP 2: Verify chain ID =====
        if claims["chain_id"] != 11155111:
            raise SigningRejectedError(
                f"Chain ID mismatch: token={claims['chain_id']}, expected=11155111",
                details={"check": "chain_id"},
            )

        if action.chain_id != claims["chain_id"]:
            raise TokenMismatchError(
                f"Action chain_id ({action.chain_id}) does not match token ({claims['chain_id']})",
            )

        # ===== STEP 3: Verify recipient =====
        if action.recipient.lower() != claims["recipient"].lower():
            raise TokenMismatchError(
                "Recipient mismatch: transaction recipient does not match "
                "authorized recipient in capability token",
                details={
                    "token_recipient": claims["recipient"],
                    "action_recipient": action.recipient,
                },
            )

        # ===== STEP 4: Verify amount =====
        if str(action.amount_wei) != claims["amount_wei"]:
            raise TokenMismatchError(
                "Amount mismatch: transaction amount does not match "
                "authorized amount in capability token",
                details={
                    "token_amount": claims["amount_wei"],
                    "action_amount": str(action.amount_wei),
                },
            )

        # ===== STEP 5: Verify transaction digest =====
        nonce = claims["nonce"]
        expected_digest = action.compute_digest(nonce)
        if expected_digest != claims["tx_digest"]:
            raise TokenMismatchError(
                "Transaction digest mismatch: the action parameters "
                "have been modified since authorization",
                details={
                    "expected_digest": expected_digest[:16] + "...",
                    "token_digest": claims["tx_digest"][:16] + "...",
                },
            )

        # ===== STEP 6: Verify proposal ID =====
        if action.proposal_id != claims["proposal_id"]:
            raise TokenMismatchError(
                "Proposal ID mismatch",
            )

        # ===== STEP 7: Check policy version is still active =====
        policy_result = await session.execute(
            select(Policy)
            .where(Policy.version == claims["policy_version"])
            .where(Policy.is_active.is_(True))
        )
        active_policy = policy_result.scalar_one_or_none()
        if active_policy is None:
            raise SigningRejectedError(
                f"Policy version {claims['policy_version']} is no longer active",
                details={"check": "policy_version"},
            )

        await validate_authorization(
            session, action, claims["policy_version"], claims.get("approval_id")
        )
        attempt = await session.get(
            ExecutionAttempt, claims.get("execution_id"), populate_existing=True
        )
        if (
            not attempt
            or attempt.proposal_id != action.proposal_id
            or attempt.status != "PREPARED"
            or hashlib.sha256(attempt.envelope.encode()).hexdigest()
            != claims.get("envelope_digest")
        ):
            raise SigningRejectedError("Missing or mismatched executable authorization")
        reservation = await session.get(SpendingRecord, attempt.id)
        if (
            not reservation
            or reservation.status != "RESERVED"
            or int(reservation.amount_wei) != action.amount_wei
        ):
            raise SigningRejectedError("Execution has no valid spending reservation")
        envelope = json.loads(attempt.envelope)
        settings = get_settings()
        from eth_account import Account

        sender = Account.from_key(self._load_key()).address.lower()
        integer_fields = (
            "value",
            "chainId",
            "nonce",
            "gas",
            "maxFeePerGas",
            "maxPriorityFeePerGas",
            "type",
        )
        if not isinstance(envelope, dict) or any(
            type(envelope.get(field)) is not int for field in integer_fields
        ):
            raise SigningRejectedError("Malformed executable envelope")
        if (
            sender != attempt.sender
            or envelope.get("to", "").lower() != action.recipient.lower()
            or envelope.get("value") != action.amount_wei
            or envelope.get("chainId") != action.chain_id
            or envelope.get("nonce") != attempt.nonce
            or not 21000 <= envelope.get("gas", 0) <= settings.max_gas_units
            or not 0
            < envelope.get("maxPriorityFeePerGas", 0)
            <= envelope.get("maxFeePerGas", 0)
            <= settings.max_fee_per_gas_wei
            or envelope.get("maxPriorityFeePerGas", 0) > settings.max_priority_fee_per_gas_wei
            or set(envelope)
            != {
                "to",
                "value",
                "chainId",
                "nonce",
                "gas",
                "maxFeePerGas",
                "maxPriorityFeePerGas",
                "type",
            }
            or envelope.get("type") != 2
        ):
            raise SigningRejectedError("Executable envelope violates signer constraints")
        consumed = await session.execute(
            update(CapabilityToken)
            .where(
                CapabilityToken.jti == jti,
                CapabilityToken.proposal_id == action.proposal_id,
                CapabilityToken.tx_digest == claims["tx_digest"],
                CapabilityToken.consumed.is_(False),
            )
            .values(consumed=True, consumed_at=datetime.now(UTC).isoformat())
        )
        if consumed.rowcount != 1:
            raise TokenConsumedError("Unknown or already consumed authorization")

        # ===== STEP 9: Sign the transaction =====
        logger.info(
            "Signer: all %d checks passed for jti=%s, proceeding to sign",
            8,
            jti,
        )

        private_key = self._load_key()

        try:
            signed_tx = self._sign_eth_transaction(
                private_key=private_key,
                to_address=action.recipient,
                amount_wei=action.amount_wei,
                chain_id=action.chain_id,
                envelope=envelope,
            )
        except Exception as e:
            raise SigningRejectedError(
                "Transaction signing failed",
            ) from e

        logger.info(
            "Signer: transaction signed for proposal=%s, tx_hash=%s",
            action.proposal_id,
            signed_tx.get("tx_hash", "unknown"),
        )
        attempt.status = "SIGNED"
        await session.flush()

        return signed_tx

    def _sign_eth_transaction(
        self,
        private_key: str,
        to_address: str,
        amount_wei: int,
        chain_id: int,
        envelope: dict[str, Any],
    ) -> dict[str, Any]:
        """Sign an Ethereum transaction using web3.py.

        This is the ONLY place the private key is used.
        The key is never returned, logged, or included in the result.

        Returns:
            Dict with raw_transaction, tx_hash (for local tracking)
        """
        from eth_account import Account

        tx = envelope

        # Sign the transaction
        signed = Account.sign_transaction(tx, private_key)

        return {
            "raw_transaction": signed.raw_transaction.hex(),
            "tx_hash": signed.hash.hex(),
            "to": to_address,
            "value_wei": str(amount_wei),
            "chain_id": chain_id,
        }
