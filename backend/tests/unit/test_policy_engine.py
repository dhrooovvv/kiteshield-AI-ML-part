"""
KiteShield Wallet — Policy Engine Unit Tests

Tests deterministic policy evaluation for all decision types.
Verifies SEC-002 (deterministic), SEC-003 (BLOCK never → signing).

Coverage target: 100% branch coverage on PolicyEngine.evaluate()
"""

import pytest

from app.schemas import NormalizedAction, PolicyDecisionType
from app.services.policy_engine import PolicyConfig, PolicyEngine


@pytest.fixture
def engine():
    """Fresh policy engine instance."""
    return PolicyEngine()


@pytest.fixture
def default_policy():
    """Standard test policy."""
    return PolicyConfig(
        version=1,
        max_amount_wei=1_000_000_000_000_000_000,  # 1 ETH
        daily_limit_wei=5_000_000_000_000_000_000,  # 5 ETH
        allowed_recipients=["0x742d35cc6634c0532925a3b844bc9e7595f2bd1e"],
        blocked_recipients=["0xdead000000000000000000000000000000000000"],
        escalation_threshold_wei=500_000_000_000_000_000,  # 0.5 ETH
    )


@pytest.fixture
def permissive_policy():
    """Policy with no allowlist (any recipient OK)."""
    return PolicyConfig(
        version=2,
        max_amount_wei=10_000_000_000_000_000_000,  # 10 ETH
        daily_limit_wei=None,
        allowed_recipients=None,
        blocked_recipients=None,
        escalation_threshold_wei=None,
    )


def make_action(
    recipient: str = "0x742d35Cc6634C0532925a3b844Bc9e7595f2bD1e",
    amount_wei: int = 100_000_000_000_000_000,  # 0.1 ETH
    chain_id: int = 11155111,
) -> NormalizedAction:
    """Create a test action."""
    return NormalizedAction(
        proposal_id="test-proposal-id",
        correlation_id="test-correlation-id",
        recipient=recipient,
        amount_wei=amount_wei,
        chain_id=chain_id,
    )


class TestPolicyEngineAllow:
    """Tests for ALLOW decisions."""

    def test_allow_basic_valid_transfer(self, engine, default_policy):
        """Valid transfer within all limits → ALLOW."""
        action = make_action(amount_wei=100_000_000_000_000_000)  # 0.1 ETH
        result = engine.evaluate(action, default_policy)
        assert result.decision == PolicyDecisionType.ALLOW
        assert "AMOUNT_WITHIN_LIMIT" in result.reason_codes
        assert "RECIPIENT_ALLOWED" in result.reason_codes
        assert result.policy_version == 1

    def test_allow_exact_limit(self, engine, default_policy):
        """Amount exactly at limit → ALLOW (boundary)."""
        # Below escalation threshold, so ALLOW
        action = make_action(amount_wei=499_999_999_999_999_999)
        result = engine.evaluate(action, default_policy)
        assert result.decision == PolicyDecisionType.ALLOW

    def test_allow_with_permissive_policy(self, engine, permissive_policy):
        """No allowlist + under limit → ALLOW any recipient."""
        action = make_action(
            recipient="0x1234567890123456789012345678901234567890",
            amount_wei=1_000_000_000_000_000_000,
        )
        result = engine.evaluate(action, permissive_policy)
        assert result.decision == PolicyDecisionType.ALLOW

    def test_allow_deterministic(self, engine, default_policy):
        """Same input × 100 → same output (SEC-002)."""
        action = make_action(amount_wei=100_000_000_000_000_000)
        results = [engine.evaluate(action, default_policy) for _ in range(100)]
        decisions = {r.decision for r in results}
        assert len(decisions) == 1
        assert PolicyDecisionType.ALLOW in decisions


class TestPolicyEngineEscalate:
    """Tests for ESCALATE decisions."""

    def test_escalate_above_threshold(self, engine, default_policy):
        """Amount at escalation threshold → ESCALATE."""
        action = make_action(amount_wei=500_000_000_000_000_000)  # 0.5 ETH
        result = engine.evaluate(action, default_policy)
        assert result.decision == PolicyDecisionType.ESCALATE
        assert "AMOUNT_REQUIRES_APPROVAL" in result.reason_codes

    def test_escalate_between_threshold_and_max(self, engine, default_policy):
        """Amount between escalation threshold and max → ESCALATE."""
        action = make_action(amount_wei=750_000_000_000_000_000)  # 0.75 ETH
        result = engine.evaluate(action, default_policy)
        assert result.decision == PolicyDecisionType.ESCALATE

    def test_escalate_at_exact_max(self, engine, default_policy):
        """Amount exactly at max → ESCALATE (within limit but above threshold)."""
        action = make_action(amount_wei=1_000_000_000_000_000_000)  # 1 ETH
        result = engine.evaluate(action, default_policy)
        assert result.decision == PolicyDecisionType.ESCALATE

    def test_no_escalation_without_threshold(self, engine, permissive_policy):
        """No escalation threshold → ALLOW even large amounts."""
        action = make_action(amount_wei=9_999_999_999_999_999_999)
        result = engine.evaluate(action, permissive_policy)
        assert result.decision == PolicyDecisionType.ALLOW


class TestPolicyEngineBlock:
    """Tests for BLOCK decisions — SEC-003: BLOCK never leads to signing."""

    def test_block_over_max_amount(self, engine, default_policy):
        """Amount exceeding max limit → BLOCK."""
        action = make_action(amount_wei=2_000_000_000_000_000_000)  # 2 ETH
        result = engine.evaluate(action, default_policy)
        assert result.decision == PolicyDecisionType.BLOCK
        assert "AMOUNT_EXCEEDS_LIMIT" in result.reason_codes

    def test_block_recipient_not_in_allowlist(self, engine, default_policy):
        """Recipient not in allowlist → BLOCK."""
        action = make_action(recipient="0x1234567890123456789012345678901234567890")
        result = engine.evaluate(action, default_policy)
        assert result.decision == PolicyDecisionType.BLOCK
        assert "RECIPIENT_NOT_IN_ALLOWLIST" in result.reason_codes

    def test_block_explicitly_blocked_recipient(self, engine, default_policy):
        """Explicitly blocked recipient → BLOCK."""
        action = make_action(recipient="0xDEAD000000000000000000000000000000000000")
        result = engine.evaluate(action, default_policy)
        assert result.decision == PolicyDecisionType.BLOCK
        assert "RECIPIENT_BLOCKED" in result.reason_codes

    def test_block_daily_limit_exceeded(self, engine, default_policy):
        """Daily spending limit exceeded → BLOCK."""
        action = make_action(amount_wei=100_000_000_000_000_000)  # 0.1 ETH
        # Already spent 4.95 ETH today
        result = engine.evaluate(
            action,
            default_policy,
            current_daily_spending_wei=4_950_000_000_000_000_000,
        )
        assert result.decision == PolicyDecisionType.BLOCK
        assert "DAILY_LIMIT_EXCEEDED" in result.reason_codes

    def test_block_unsupported_chain(self, engine, default_policy):
        """Non-Sepolia chain → BLOCK."""
        action = make_action(chain_id=1)  # Mainnet
        result = engine.evaluate(action, default_policy)
        assert result.decision == PolicyDecisionType.BLOCK
        assert "UNSUPPORTED_CHAIN" in result.reason_codes

    def test_block_overrides_escalate(self, engine, default_policy):
        """Block takes priority over escalation threshold.
        Amount over max AND over threshold → BLOCK (not ESCALATE)."""
        action = make_action(amount_wei=2_000_000_000_000_000_000)  # 2 ETH
        result = engine.evaluate(action, default_policy)
        # Over max → BLOCK, even though it's also over escalation threshold
        assert result.decision == PolicyDecisionType.BLOCK

    def test_block_unknown_recipient_with_allowlist(self, engine, default_policy):
        """Unknown recipient when allowlist exists → BLOCK."""
        action = make_action(recipient="0xABCDABCDABCDABCDABCDABCDABCDABCDABCDABCD")
        result = engine.evaluate(action, default_policy)
        assert result.decision == PolicyDecisionType.BLOCK


class TestPolicyDecisionMetadata:
    """Tests for decision metadata and audit trail support."""

    def test_decision_has_policy_version(self, engine, default_policy):
        """Every decision should reference the policy version."""
        action = make_action()
        result = engine.evaluate(action, default_policy)
        assert result.policy_version == default_policy.version

    def test_block_has_reason_codes(self, engine, default_policy):
        """Blocked decisions should explain why."""
        action = make_action(amount_wei=999_000_000_000_000_000_000)
        result = engine.evaluate(action, default_policy)
        assert result.decision == PolicyDecisionType.BLOCK
        assert len(result.reason_codes) > 0

    def test_allow_has_positive_reasons(self, engine, default_policy):
        """Allowed decisions should list checks that passed."""
        action = make_action(amount_wei=100_000_000_000_000_000)
        result = engine.evaluate(action, default_policy)
        assert result.decision == PolicyDecisionType.ALLOW
        assert len(result.reason_codes) > 0


class TestPolicyConfigParsing:
    """Tests for PolicyConfig construction."""

    def test_parse_empty_allowlist(self):
        """No allowlist → any recipient allowed."""
        config = PolicyConfig(
            version=1,
            max_amount_wei=1_000_000_000_000_000_000,
            allowed_recipients=None,
        )
        assert config.allowed_recipients is None

    def test_parse_allowlist_lowercase(self):
        """Allowlist addresses should be lowercased for comparison."""
        config = PolicyConfig(
            version=1,
            max_amount_wei=1_000_000_000_000_000_000,
            allowed_recipients=["0xABCD1234"],
        )
        assert "0xabcd1234" in config.allowed_recipients


class TestPolicyEdgeCases:
    """Edge cases and boundary conditions."""

    def test_zero_daily_spending(self, engine, default_policy):
        """Zero current spending → should not trigger daily limit."""
        action = make_action(amount_wei=100_000_000_000_000_000)
        result = engine.evaluate(action, default_policy, current_daily_spending_wei=0)
        assert result.decision == PolicyDecisionType.ALLOW

    def test_exact_daily_limit(self, engine, default_policy):
        """Spending exactly at daily limit → should still be OK."""
        action = make_action(amount_wei=100_000_000_000_000_000)  # 0.1 ETH
        # Already spent 4.9 ETH → total would be 5.0 = limit
        result = engine.evaluate(
            action,
            default_policy,
            current_daily_spending_wei=4_900_000_000_000_000_000,
        )
        assert result.decision == PolicyDecisionType.ALLOW

    def test_one_wei_over_daily_limit(self, engine, default_policy):
        """One wei over daily limit → BLOCK."""
        action = make_action(amount_wei=100_000_000_000_000_001)
        result = engine.evaluate(
            action,
            default_policy,
            current_daily_spending_wei=4_900_000_000_000_000_000,
        )
        assert result.decision == PolicyDecisionType.BLOCK

    def test_blocked_recipient_takes_priority(self, engine):
        """Blocked recipient overrides allowlist membership."""
        # Recipient is in BOTH allowed and blocked lists
        policy = PolicyConfig(
            version=1,
            max_amount_wei=10_000_000_000_000_000_000,
            allowed_recipients=["0xdead000000000000000000000000000000000000"],
            blocked_recipients=["0xdead000000000000000000000000000000000000"],
        )
        action = make_action(
            recipient="0xDEAD000000000000000000000000000000000000",
            amount_wei=1,
        )
        result = engine.evaluate(action, policy)
        assert result.decision == PolicyDecisionType.BLOCK
        assert "RECIPIENT_BLOCKED" in result.reason_codes
