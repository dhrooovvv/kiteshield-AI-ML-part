"""
KiteShield Wallet — Pydantic Schemas for Transaction Proposals

Defines input validation, normalization, and response schemas for
the transaction proposal lifecycle.

Security invariant (SI-1): Model output is untrusted.
All incoming data is validated and normalized before policy evaluation.
"""

import enum
import re
from typing import Any

from pydantic import BaseModel, Field, field_validator

# ---- Enums ----


class ProposalStatus(enum.StrEnum):
    """Transaction proposal lifecycle states.

    State machine transitions are enforced in the service layer.
    See ARCHITECTURE.md §7.3 for the state diagram.
    """

    PROPOSED = "PROPOSED"
    EVALUATING = "EVALUATING"
    ALLOWED = "ALLOWED"
    ESCALATED = "ESCALATED"
    BLOCKED = "BLOCKED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED_APPROVAL = "EXPIRED_APPROVAL"
    AUTHORIZED = "AUTHORIZED"
    SIGNING = "SIGNING"
    SIGNED = "SIGNED"
    SUBMITTED = "SUBMITTED"
    CONFIRMED = "CONFIRMED"
    FAILED = "FAILED"
    SIGN_FAILED = "SIGN_FAILED"
    TX_FAILED = "TX_FAILED"


class AssetType(enum.StrEnum):
    """Supported asset types. MVP: native ETH only."""

    NATIVE_ETH = "NATIVE_ETH"


class PolicyDecisionType(enum.StrEnum):
    """The three possible policy decisions."""

    ALLOW = "ALLOW"
    ESCALATE = "ESCALATE"
    BLOCK = "BLOCK"


# ---- Ethereum Address Validation ----

_ETH_ADDRESS_PATTERN = re.compile(r"^0x[0-9a-fA-F]{40}$")


def validate_eth_address(address: str) -> str:
    """Validate and normalize an Ethereum address.

    Returns checksummed address. Rejects invalid formats.
    Uses EIP-55 checksum validation.
    """
    if not _ETH_ADDRESS_PATTERN.match(address):
        raise ValueError("Invalid Ethereum address format")

    from web3 import Web3

    return Web3.to_checksum_address(address)


# ---- Request Schemas ----


class AgentProposalRequest(BaseModel):
    """Raw proposal from the AI agent or user.

    This is UNTRUSTED input. All fields are validated and normalized
    before being used for policy evaluation.
    """

    prompt: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="Natural language transaction request from agent/user",
    )
    recipient: str = Field(
        ...,
        description="Destination Ethereum address",
    )
    amount_wei: str = Field(
        ...,
        description="Amount in wei as a decimal string (no floating point)",
    )
    chain_id: int = Field(
        default=11155111,
        description="Target chain ID (must be Sepolia: 11155111)",
    )
    asset_type: AssetType = Field(
        default=AssetType.NATIVE_ETH,
        description="Asset type to transfer",
    )

    @field_validator("recipient")
    @classmethod
    def validate_recipient(cls, v: str) -> str:
        """Validate and checksum the recipient address."""
        return validate_eth_address(v)

    @field_validator("amount_wei")
    @classmethod
    def validate_amount(cls, v: str) -> str:
        """Validate amount is a positive integer string."""
        if not re.fullmatch(r"[0-9]+", v):
            raise ValueError("amount_wei must be a positive integer string of decimal digits only")
        try:
            amount = int(v)
        except (ValueError, TypeError):
            raise ValueError(f"amount_wei must be a valid integer string, got: {v}") from None
        if amount <= 0:
            raise ValueError(f"amount_wei must be positive, got: {amount}")
        if amount > 10**24:  # Sanity cap: ~1M ETH
            raise ValueError(f"amount_wei exceeds sanity cap: {amount}")
        return str(amount)

    @field_validator("chain_id")
    @classmethod
    def validate_chain(cls, v: int) -> int:
        """Restrict to Sepolia testnet."""
        if v != 11155111:
            raise ValueError(f"Only Sepolia (11155111) is supported. Got: {v}")
        return v


class EvaluateProposalRequest(BaseModel):
    """Request to evaluate a proposal against policy."""

    proposal_id: str = Field(..., description="UUID of the proposal to evaluate")


class SignProposalRequest(BaseModel):
    """Request to sign and submit an authorized proposal."""

    proposal_id: str = Field(..., description="UUID of the proposal to sign")


class ExecutionLimits(BaseModel):
    """Optional caller restrictions; never a substitute for persisted authorization."""

    model_config = {"extra": "forbid", "strict": True}
    sender: str
    recipient: str
    amount_wei: str = Field(pattern=r"^[1-9][0-9]{0,24}$")
    chain_id: int = Field(ge=11155111, le=11155111)
    nonce: int = Field(ge=0)
    max_gas_units: int = Field(ge=21000, le=1000000)
    max_fee_per_gas_wei: int = Field(ge=1)
    max_priority_fee_per_gas_wei: int = Field(ge=1)
    max_total_cost_wei: str = Field(pattern=r"^[1-9][0-9]{0,30}$")

    @field_validator("sender", "recipient")
    @classmethod
    def checksum_address(cls, value: str) -> str:
        return validate_eth_address(value)

    def check_envelope(self, sender: str, envelope: dict) -> None:
        from app.exceptions import SigningRejectedError

        if (
            sender.lower() != self.sender.lower()
            or envelope.get("to", "").lower() != self.recipient.lower()
            or envelope.get("value") != int(self.amount_wei)
            or envelope.get("chainId") != self.chain_id
            or envelope.get("nonce") != self.nonce
            or envelope["gas"] > self.max_gas_units
            or envelope["maxFeePerGas"] > self.max_fee_per_gas_wei
            or envelope["maxPriorityFeePerGas"] > self.max_priority_fee_per_gas_wei
            or envelope["value"] + envelope["gas"] * envelope["maxFeePerGas"]
            > int(self.max_total_cost_wei)
        ):
            raise SigningRejectedError("Execution exceeds explicitly approved payment limits")


class EmergencyStopRequest(BaseModel):
    """Administrative request to change the execution stop state."""

    active: bool
    reason: str = Field(..., min_length=1, max_length=512)


class EmergencyStopResponse(BaseModel):
    """Public emergency-stop state; no credential material is included."""

    active: bool
    reason: str
    version: int
    updated_at: str


class AuditCheckpointRequest(BaseModel):
    """Optional inclusive audit-event range for a checkpoint."""

    first_event_id: str | None = None
    last_event_id: str | None = None


class AuditCheckpointResponse(BaseModel):
    """Persisted Merkle checkpoint metadata."""

    id: str
    merkle_root: str
    first_event_id: str | None
    last_event_id: str | None
    event_count: int
    created_at: str


class AuditProofVerificationRequest(BaseModel):
    """Untrusted proof material submitted for verification."""

    event_id: str
    index: int
    leaf_hash: str
    proof: list[dict[str, str]]


class AuditProofResponse(BaseModel):
    """Inclusion proof bound to a persisted checkpoint and event."""

    checkpoint_id: str
    event_id: str
    index: int
    leaf_hash: str
    proof: list[dict[str, str]]
    total_leaves: int
    merkle_root: str
    valid: bool | None = None


# ---- Response Schemas ----


class ProposalResponse(BaseModel):
    """Transaction proposal response, including operator-configured automation limits."""

    auto_execution_enabled: bool = False
    auto_execution_max_wei: str = "100000000000000"
    provenance: str = "AGENT_OR_STRUCTURED"
    mandate_version: int | None = None

    id: str
    correlation_id: str
    prompt: str
    recipient: str
    amount_wei: str
    amount_eth: str  # Human-readable conversion
    chain_id: int
    asset_type: str
    status: ProposalStatus
    created_at: str
    updated_at: str

    # Related data (populated when available)
    policy_decision: "PolicyDecisionResponse | None" = None
    approval: "ApprovalResponse | None" = None
    transaction: "TransactionResponse | None" = None


class PolicyDecisionResponse(BaseModel):
    """Policy evaluation result."""

    decision: PolicyDecisionType
    reason_codes: list[str]
    policy_version: int
    evaluated_at: str


class ApprovalResponse(BaseModel):
    """Approval request status."""

    id: str
    status: str
    action_digest: str
    expires_at: str
    decided_at: str | None = None


class TransactionResponse(BaseModel):
    """Blockchain transaction status."""

    id: str
    tx_hash: str | None = None
    status: str
    execution_mode: str | None = None
    execution_outcome: str | None = None
    receipt: dict | None = None
    explorer_url: str | None = None
    block_number: int | None = None
    gas_used: int | None = None
    error_message: str | None = None
    created_at: str
    updated_at: str


class ProposalListResponse(BaseModel):
    """List of proposals."""

    proposals: list[ProposalResponse]
    total: int


# ---- Internal Domain Types ----


class NormalizedAction(BaseModel):
    """Validated, normalized transaction action.

    This is the canonical representation used by the policy engine,
    capability tokens, and signer verification.

    Security: This type is ONLY created after full validation.
    It is the bridge between untrusted input and trusted evaluation.
    """

    proposal_id: str
    correlation_id: str
    action_type: AssetType = AssetType.NATIVE_ETH
    recipient: str  # Checksummed address
    amount_wei: int = Field(gt=0, le=10**24, strict=True)  # Exact integer
    chain_id: int = 11155111

    @property
    def amount_eth(self) -> str:
        """Human-readable ETH amount (for display only, not for computation)."""
        from app.services.amounts import wei_to_eth

        return wei_to_eth(self.amount_wei)

    def canonical_string(self, nonce: str) -> str:
        """Canonical representation for digest computation.

        Used for transaction binding in capability tokens.
        Field order and encoding are fixed and must not change.
        """
        return (
            f"{self.chain_id}:{self.action_type.value}:"
            f"{self.recipient.lower()}:{self.amount_wei}:{nonce}"
        )

    def compute_digest(self, nonce: str) -> str:
        """Compute SHA-256 digest of the canonical action representation.

        This digest is bound into the capability token to prevent
        parameter modification after authorization.
        """
        import hashlib

        canonical = self.canonical_string(nonce)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def action_digest_without_nonce(self) -> str:
        """Compute digest for approval binding (without nonce).

        Used to bind an approval to the exact action parameters.
        The nonce is excluded because it's generated at token issuance time,
        which happens after approval.
        """
        import hashlib

        canonical = (
            f"{self.chain_id}:{self.action_type.value}:{self.recipient.lower()}:{self.amount_wei}"
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ---- Standard API Envelope ----


class APIResponse(BaseModel):
    """Standard API response wrapper."""

    data: Any
    meta: dict[str, Any] = Field(default_factory=dict)


class APIError(BaseModel):
    """Standard API error response."""

    error: dict[str, Any]


# ---- Policy Schemas ----


class PolicyCreateRequest(BaseModel):
    """Request to create a new transaction policy."""

    max_amount_wei: str = Field(..., description="Max amount in wei per transaction")
    daily_limit_wei: str | None = Field(default=None, description="Daily limit in wei")
    allowed_recipients: list[str] | None = Field(default=None, description="Allowlist of addresses")
    blocked_recipients: list[str] | None = Field(default=None, description="Blocklist of addresses")
    escalation_threshold_wei: str | None = Field(
        default=None, description="Threshold above which human approval is required"
    )

    @field_validator("max_amount_wei")
    @classmethod
    def validate_max_amount(cls, v: str) -> str:
        if not re.fullmatch(r"[0-9]+", v):
            raise ValueError("Amount must contain decimal digits only")
        try:
            amount = int(v)
        except (ValueError, TypeError):
            raise ValueError(f"max_amount_wei must be a valid integer string, got: {v}") from None
        if amount <= 0:
            raise ValueError(f"max_amount_wei must be positive, got: {amount}")
        return str(amount)

    @field_validator("daily_limit_wei", "escalation_threshold_wei")
    @classmethod
    def validate_optional_amount(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if not re.fullmatch(r"[0-9]+", v):
            raise ValueError("Amount must contain decimal digits only")
        try:
            amount = int(v)
        except (ValueError, TypeError):
            raise ValueError(f"Amount must be a valid integer string, got: {v}") from None
        if amount <= 0:
            raise ValueError(f"Amount must be positive, got: {amount}")
        return str(amount)

    @field_validator("allowed_recipients", "blocked_recipients")
    @classmethod
    def validate_recipients(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return None
        return [validate_eth_address(addr) for addr in v]


class PolicyUpdateRequest(BaseModel):
    """Request to update an existing policy (creates a new active version)."""

    max_amount_wei: str | None = Field(
        default=None, description="Max amount in wei per transaction"
    )
    daily_limit_wei: str | None = Field(default=None, description="Daily limit in wei")
    allowed_recipients: list[str] | None = Field(default=None, description="Allowlist of addresses")
    blocked_recipients: list[str] | None = Field(default=None, description="Blocklist of addresses")
    escalation_threshold_wei: str | None = Field(
        default=None, description="Threshold above which human approval is required"
    )

    @field_validator("max_amount_wei", "daily_limit_wei", "escalation_threshold_wei")
    @classmethod
    def validate_optional_amount(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if not re.fullmatch(r"[0-9]+", v):
            raise ValueError("Amount must be a positive integer string of decimal digits only")
        try:
            amount = int(v)
        except (ValueError, TypeError):
            raise ValueError(f"Amount must be a valid integer string, got: {v}") from None
        if amount <= 0:
            raise ValueError(f"Amount must be positive, got: {amount}")
        return str(amount)

    @field_validator("allowed_recipients", "blocked_recipients")
    @classmethod
    def validate_recipients(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return None
        return [validate_eth_address(addr) for addr in v]


class PolicyResponse(BaseModel):
    """Policy details response."""

    id: str
    version: int
    max_amount_wei: str
    daily_limit_wei: str | None
    allowed_recipients: list[str] | None
    blocked_recipients: list[str] | None
    escalation_threshold_wei: str | None
    is_active: bool
    created_at: str


# ---- Approval Decision Schemas ----


class ApprovalDecisionRequest(BaseModel):
    """Human approval or rejection decision."""

    decision: str = Field(..., description="APPROVE or REJECT")
    approved_by: str = Field(default="user:admin", description="Identifier of the approver")

    @field_validator("decision")
    @classmethod
    def validate_decision(cls, v: str) -> str:
        v_upper = v.upper()
        if v_upper not in ("APPROVE", "REJECT"):
            raise ValueError("decision must be either APPROVE or REJECT")
        return v_upper


# ---- Agent Prompt Schemas ----


class AgentPromptRequest(BaseModel):
    """Natural language instruction for the AI agent to propose a transaction."""

    prompt: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="Natural language instruction for transaction proposal",
    )


# ---- Audit Schemas ----


class AuditEventResponse(BaseModel):
    """Sanitized audit event representation."""

    id: str
    correlation_id: str
    event_type: str
    actor: str
    details: dict[str, Any]
    policy_version: int | None
    previous_hash: str | None
    event_hash: str
    created_at: str


class AuditTrailResponse(BaseModel):
    """Audit trail response with chain integrity status."""

    correlation_id: str
    events: list[AuditEventResponse]
    chain_valid: bool
