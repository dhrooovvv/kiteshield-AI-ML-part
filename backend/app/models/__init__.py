"""
KiteShield Wallet — SQLAlchemy Database Models

Defines all database tables with appropriate constraints for
security-critical state management.

Key constraints:
- No floating point for amounts (stored as TEXT for exact integers)
- UNIQUE constraints for replay protection
- Foreign keys for referential integrity
- CHECK constraints for valid state values
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    """SQLAlchemy declarative base."""

    pass


def generate_uuid() -> str:
    """Generate a new UUID string."""
    return str(uuid.uuid4())


def utc_now() -> datetime:
    """Get current UTC datetime."""
    return datetime.now(UTC)


def utc_now_str() -> str:
    """Get current UTC datetime as ISO 8601 string."""
    return datetime.now(UTC).isoformat()


class Policy(Base):
    """Transaction policy configuration.

    Policies are versioned. Only one policy can be active at a time.
    Policy version is bound into capability tokens to detect stale authorization.
    """

    __tablename__ = "policies"

    id = Column(String, primary_key=True, default=generate_uuid)
    version = Column(Integer, nullable=False, unique=True)
    max_amount_wei = Column(String, nullable=False)  # Exact integer as string
    daily_limit_wei = Column(String, nullable=True)
    allowed_recipients = Column(Text, nullable=True)  # JSON array
    blocked_recipients = Column(Text, nullable=True)  # JSON array
    escalation_threshold_wei = Column(String, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(String, nullable=False, default=utc_now_str)


class Proposal(Base):
    """Transaction proposal from agent or user.

    Tracks the full lifecycle from proposal through signing and submission.
    """

    __tablename__ = "proposals"

    id = Column(String, primary_key=True, default=generate_uuid)
    correlation_id = Column(String, nullable=False, default=generate_uuid)
    agent_prompt = Column(Text, nullable=False)
    recipient = Column(String(42), nullable=False)  # Checksummed address
    amount_wei = Column(String, nullable=False)  # Exact integer as string
    chain_id = Column(Integer, nullable=False, default=11155111)
    asset_type = Column(String, nullable=False, default="NATIVE_ETH")
    status = Column(
        String,
        nullable=False,
        default="PROPOSED",
    )
    created_at = Column(String, nullable=False, default=utc_now_str)
    updated_at = Column(String, nullable=False, default=utc_now_str)

    # Relationships
    policy_decision = relationship(
        "PolicyDecision", back_populates="proposal", uselist=False, lazy="selectin"
    )
    approval_request = relationship(
        "ApprovalRequest", back_populates="proposal", uselist=False, lazy="selectin"
    )
    capability_tokens = relationship(
        "CapabilityToken", back_populates="proposal", lazy="selectin"
    )
    transaction = relationship(
        "Transaction", back_populates="proposal", uselist=False, lazy="selectin"
    )


class PolicyDecision(Base):
    """Policy evaluation result for a proposal.

    One decision per proposal (UNIQUE constraint).
    Stores the decision type, reason codes, and policy version used.
    """

    __tablename__ = "policy_decisions"

    id = Column(String, primary_key=True, default=generate_uuid)
    proposal_id = Column(String, ForeignKey("proposals.id"), nullable=False, unique=True)
    decision = Column(String, nullable=False)
    reason_codes = Column(Text, nullable=False)  # JSON array
    policy_version = Column(Integer, nullable=False)
    evaluated_at = Column(String, nullable=False, default=utc_now_str)

    # Relationship
    proposal = relationship("Proposal", back_populates="policy_decision", lazy="selectin")

    __table_args__ = (
        CheckConstraint("decision IN ('ALLOW', 'ESCALATE', 'BLOCK')", name="ck_decision_type"),
    )


class ApprovalRequest(Base):
    """Human approval request for escalated transactions.

    Bound to the exact action via action_digest.
    One approval per proposal (UNIQUE constraint).
    """

    __tablename__ = "approval_requests"

    id = Column(String, primary_key=True, default=generate_uuid)
    proposal_id = Column(String, ForeignKey("proposals.id"), nullable=False, unique=True)
    action_digest = Column(String, nullable=False)  # SHA-256 of canonical action
    status = Column(String, nullable=False, default="PENDING")
    expires_at = Column(String, nullable=False)
    approved_by = Column(String, nullable=True)
    decided_at = Column(String, nullable=True)
    created_at = Column(String, nullable=False, default=utc_now_str)

    # Relationship
    proposal = relationship("Proposal", back_populates="approval_request", lazy="selectin")

    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING', 'APPROVED', 'REJECTED', 'EXPIRED')",
            name="ck_approval_status",
        ),
    )


class CapabilityToken(Base):
    """Record of issued capability tokens.

    Tracks token consumption for replay protection.
    The jti (JWT ID) is the primary key — each token is uniquely identified.

    Security invariant (SI-6): Tokens are single-use.
    The consumed flag + unique constraint prevents replay.
    """

    __tablename__ = "capability_tokens"

    jti = Column(String, primary_key=True)  # JWT ID — unique token identifier
    proposal_id = Column(String, ForeignKey("proposals.id"), nullable=False)
    tx_digest = Column(String, nullable=False)
    consumed = Column(Boolean, nullable=False, default=False)
    consumed_at = Column(String, nullable=True)
    expires_at = Column(String, nullable=False)
    created_at = Column(String, nullable=False, default=utc_now_str)

    # Relationship
    proposal = relationship("Proposal", back_populates="capability_tokens", lazy="selectin")


class Transaction(Base):
    """Blockchain transaction record.

    Tracks the signing and submission lifecycle.
    tx_hash is UNIQUE to prevent duplicate submissions.
    """

    __tablename__ = "transactions"

    id = Column(String, primary_key=True, default=generate_uuid)
    proposal_id = Column(String, ForeignKey("proposals.id"), nullable=False, unique=True)
    tx_hash = Column(String, unique=True, nullable=True)
    status = Column(String, nullable=False, default="SIGNING")
    block_number = Column(Integer, nullable=True)
    gas_used = Column(Integer, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(String, nullable=False, default=utc_now_str)
    updated_at = Column(String, nullable=False, default=utc_now_str)

    # Relationship
    proposal = relationship("Proposal", back_populates="transaction", lazy="selectin")

    __table_args__ = (
        CheckConstraint(
            "status IN ('SIGNING', 'SIGNED', 'SUBMITTED', 'CONFIRMED', 'FAILED')",
            name="ck_tx_status",
        ),
    )


class AuditEvent(Base):
    """Immutable audit event record.

    Events are linked by correlation_id and ordered by created_at.
    Hash chain provides tamper detection (informational, not cryptographic
    tamper-proof — see SECURITY.md for limitations).

    Security: Never stores private keys, seed phrases, or token secrets.
    """

    __tablename__ = "audit_events"

    id = Column(String, primary_key=True, default=generate_uuid)
    correlation_id = Column(String, nullable=False, index=True)
    event_type = Column(String, nullable=False, index=True)
    actor = Column(String, nullable=False)
    details = Column(Text, nullable=False)  # JSON, sanitized — no secrets
    policy_version = Column(Integer, nullable=True)
    previous_hash = Column(String, nullable=True)
    event_hash = Column(String, nullable=False)
    created_at = Column(String, nullable=False, default=utc_now_str, index=True)


class AuditCheckpoint(Base):
    """Persisted Merkle checkpoint over an ordered audit-event range."""

    __tablename__ = "audit_checkpoints"

    id = Column(String, primary_key=True, default=generate_uuid)
    merkle_root = Column(String, nullable=False)
    first_event_id = Column(String, nullable=True)
    last_event_id = Column(String, nullable=True)
    event_count = Column(Integer, nullable=False)
    created_at = Column(String, nullable=False, default=utc_now_str, index=True)


class SpendingRecord(Base):
    """Spending tracker for rate/daily limits.

    Tracks reserved and committed spending to prevent exceeding limits
    even under concurrent requests.
    """

    __tablename__ = "spending_records"

    id = Column(String, primary_key=True, default=generate_uuid)
    proposal_id = Column(String, ForeignKey("proposals.id"), nullable=False)
    amount_wei = Column(String, nullable=False)
    status = Column(String, nullable=False, default="RESERVED")
    period_date = Column(String, nullable=False)  # YYYY-MM-DD
    created_at = Column(String, nullable=False, default=utc_now_str)

    __table_args__ = (
        CheckConstraint(
            "status IN ('RESERVED', 'COMMITTED', 'RELEASED')",
            name="ck_spending_status",
        ),
        Index("idx_spending_period", "period_date", "status"),
    )


class ExecutionControl(Base):
    """Persistent singleton controlling whether execution is permitted."""

    __tablename__ = "execution_control"

    id = Column(String, primary_key=True)
    active = Column(Boolean, nullable=False, default=False)
    reason = Column(Text, nullable=False, default="")
    changed_by = Column(String, nullable=False, default="system")
    version = Column(Integer, nullable=False, default=0)
    updated_at = Column(String, nullable=False, default=utc_now_str)
