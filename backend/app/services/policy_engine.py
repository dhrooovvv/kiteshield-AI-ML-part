"""
KiteShield Wallet — Policy Engine

Deterministic policy evaluation for transaction proposals.
This is the core authorization decision-maker.

Security invariants enforced:
- SI-2: Invalid/ambiguous proposals cannot be signed
- SI-3: BLOCK never leads to signing (enforced by returning BLOCK decision)
- SI-12: Fail-closed on missing/invalid authorization

Design:
- Pure function: same input + same policy + same spending state → same decision
- No LLM involvement in policy decisions
- Explicit reason codes for every decision
- Fail-closed: any uncertainty → BLOCK

Decision logic priority:
1. BLOCK rules (explicit deny) have highest priority
2. ESCALATE rules (require approval) have medium priority
3. ALLOW rules (permit) have lowest priority — action must pass ALL checks
"""

import json
from dataclasses import dataclass, field
from typing import Any

from app.core.logging import get_logger
from app.schemas import (
    AssetType,
    NormalizedAction,
    PolicyDecisionType,
)

logger = get_logger("policy_engine")


@dataclass(frozen=True)
class PolicyConfig:
    """Parsed policy configuration.

    Loaded from the database Policy model.
    All amounts are in wei (exact integers).
    """

    version: int
    max_amount_wei: int
    daily_limit_wei: int | None = None
    allowed_recipients: list[str] | None = None  # Lowercase addresses
    blocked_recipients: list[str] | None = None  # Lowercase addresses
    escalation_threshold_wei: int | None = None

    def __post_init__(self) -> None:
        """Normalize recipient lists to lowercase addresses."""
        if self.allowed_recipients is not None:
            object.__setattr__(
                self,
                "allowed_recipients",
                [addr.lower() for addr in self.allowed_recipients],
            )
        if self.blocked_recipients is not None:
            object.__setattr__(
                self,
                "blocked_recipients",
                [addr.lower() for addr in self.blocked_recipients],
            )

    @classmethod
    def from_db_row(cls, row: Any) -> "PolicyConfig":
        """Create PolicyConfig from a database Policy model."""
        allowed = None
        if row.allowed_recipients:
            allowed = [addr.lower() for addr in json.loads(row.allowed_recipients)]

        blocked = None
        if row.blocked_recipients:
            blocked = [addr.lower() for addr in json.loads(row.blocked_recipients)]

        return cls(
            version=row.version,
            max_amount_wei=int(row.max_amount_wei),
            daily_limit_wei=int(row.daily_limit_wei) if row.daily_limit_wei else None,
            allowed_recipients=allowed,
            blocked_recipients=blocked,
            escalation_threshold_wei=(
                int(row.escalation_threshold_wei) if row.escalation_threshold_wei else None
            ),
        )


@dataclass(frozen=True)
class PolicyDecision:
    """The result of a policy evaluation.

    Immutable after creation. Contains enough information to:
    1. Explain the decision to the user
    2. Bind to a capability token
    3. Audit the evaluation
    """

    decision: PolicyDecisionType
    reason_codes: list[str]
    policy_version: int
    details: dict[str, Any] = field(default_factory=dict)


class PolicyEngine:
    """Deterministic policy evaluation engine.

    Evaluates a NormalizedAction against a PolicyConfig.
    Returns exactly one of: ALLOW, ESCALATE, BLOCK.

    This class contains NO I/O — it's a pure function wrapper
    for testability and determinism.
    """

    def evaluate(
        self,
        action: NormalizedAction,
        policy: PolicyConfig,
        current_daily_spending_wei: int = 0,
    ) -> PolicyDecision:
        """Evaluate a transaction action against the policy.

        Args:
            action: Validated, normalized action to evaluate
            policy: Active policy configuration
            current_daily_spending_wei: Already-spent amount today (committed + reserved)

        Returns:
            PolicyDecision with ALLOW, ESCALATE, or BLOCK
        """
        reasons: list[str] = []
        should_block = False
        should_escalate = False

        # ---- Check 1: Supported asset type ----
        if action.action_type != AssetType.NATIVE_ETH:
            return PolicyDecision(
                decision=PolicyDecisionType.BLOCK,
                reason_codes=["UNSUPPORTED_ASSET_TYPE"],
                policy_version=policy.version,
                details={"asset_type": action.action_type},
            )

        # ---- Check 2: Supported chain ----
        if action.chain_id != 11155111:
            return PolicyDecision(
                decision=PolicyDecisionType.BLOCK,
                reason_codes=["UNSUPPORTED_CHAIN"],
                policy_version=policy.version,
                details={"chain_id": action.chain_id},
            )

        # ---- Check 3: Blocked recipients (explicit deny list) ----
        recipient_lower = action.recipient.lower()
        if policy.blocked_recipients and recipient_lower in policy.blocked_recipients:
            return PolicyDecision(
                decision=PolicyDecisionType.BLOCK,
                reason_codes=["RECIPIENT_BLOCKED"],
                policy_version=policy.version,
                details={"recipient": action.recipient},
            )

        # ---- Check 4: Allowed recipients (allowlist) ----
        if (
            policy.allowed_recipients is not None
            and recipient_lower not in policy.allowed_recipients
        ):
            reasons.append("RECIPIENT_NOT_IN_ALLOWLIST")
            should_block = True

        # ---- Check 5: Per-transaction amount limit ----
        if action.amount_wei > policy.max_amount_wei:
            reasons.append("AMOUNT_EXCEEDS_LIMIT")
            should_block = True
        else:
            reasons.append("AMOUNT_WITHIN_LIMIT")

        # ---- Check 6: Daily spending limit ----
        if policy.daily_limit_wei is not None:
            total_after = current_daily_spending_wei + action.amount_wei
            if total_after > policy.daily_limit_wei:
                reasons.append("DAILY_LIMIT_EXCEEDED")
                should_block = True
            else:
                reasons.append("DAILY_LIMIT_OK")

        # ---- Check 7: Escalation threshold ----
        if (
            policy.escalation_threshold_wei is not None
            and action.amount_wei >= policy.escalation_threshold_wei
            and not should_block
        ):
            reasons.append("AMOUNT_REQUIRES_APPROVAL")
            should_escalate = True

        # ---- Decision resolution ----
        # Priority: BLOCK > ESCALATE > ALLOW
        if should_block:
            decision = PolicyDecisionType.BLOCK
        elif should_escalate:
            decision = PolicyDecisionType.ESCALATE
        else:
            if "RECIPIENT_NOT_IN_ALLOWLIST" not in reasons:
                reasons.append("RECIPIENT_ALLOWED")
            decision = PolicyDecisionType.ALLOW

        logger.info(
            "Policy evaluation: decision=%s, reasons=%s, policy_v=%d",
            decision.value,
            reasons,
            policy.version,
        )

        return PolicyDecision(
            decision=decision,
            reason_codes=reasons,
            policy_version=policy.version,
        )
