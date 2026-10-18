"""
KiteShield Wallet — Domain Exceptions

Defines all application-specific exceptions with machine-readable error codes.
These exceptions are caught by the global error handler and converted to
consistent API error responses.

Design: Each exception carries a stable error code for frontend consumption
and a human-readable message that is safe to return to clients.
"""

from typing import Any


class KiteShieldError(Exception):
    """Base exception for all KiteShield domain errors."""

    error_code: str = "INTERNAL_ERROR"
    status_code: int = 500

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        self.message = message
        self.details = details or {}
        super().__init__(message)


# ---- Validation Errors ----


class ValidationError(KiteShieldError):
    """Input validation failed."""

    error_code = "VALIDATION_ERROR"
    status_code = 422


class PromptInjectionDetectedError(ValidationError):
    """Untrusted agent input was rejected by the prompt-injection screen."""

    error_code = "PROMPT_INJECTION_DETECTED"


class PromptScreeningReviewRequiredError(KiteShieldError):
    """Learned detectors disagree and normal proposal creation is paused."""

    error_code = "PROMPT_SCREENING_REVIEW_REQUIRED"
    status_code = 409


class PromptScreeningUnavailableError(KiteShieldError):
    """The required prompt-injection screen could not produce a result."""

    error_code = "PROMPT_SCREENING_UNAVAILABLE"
    status_code = 503


class InvalidAddressError(ValidationError):
    """Ethereum address is invalid or not checksummed."""

    error_code = "INVALID_ADDRESS"


class InvalidAmountError(ValidationError):
    """Transaction amount is invalid (negative, zero, non-integer)."""

    error_code = "INVALID_AMOUNT"


class UnsupportedChainError(ValidationError):
    """Chain ID is not supported."""

    error_code = "UNSUPPORTED_CHAIN"


class UnsupportedActionError(ValidationError):
    """Action type is not supported."""

    error_code = "UNSUPPORTED_ACTION"


# ---- Policy Errors ----


class PolicyError(KiteShieldError):
    """Policy-related error."""

    error_code = "POLICY_ERROR"
    status_code = 403


class PolicyBlockError(PolicyError):
    """Transaction blocked by policy."""

    error_code = "POLICY_BLOCK"


class PolicyNotFoundError(PolicyError):
    """No active policy found."""

    error_code = "POLICY_NOT_FOUND"
    status_code = 404


class PolicyVersionMismatchError(PolicyError):
    """Policy version has changed since authorization."""

    error_code = "POLICY_VERSION_MISMATCH"
    status_code = 409


# ---- Approval Errors ----


class ApprovalError(KiteShieldError):
    """Approval-related error."""

    error_code = "APPROVAL_ERROR"
    status_code = 403


class ApprovalRequiredError(ApprovalError):
    """Transaction requires human approval before proceeding."""

    error_code = "APPROVAL_REQUIRED"


class ApprovalExpiredError(ApprovalError):
    """Approval request has expired."""

    error_code = "APPROVAL_EXPIRED"


class ApprovalNotFoundError(ApprovalError):
    """Approval request not found."""

    error_code = "APPROVAL_NOT_FOUND"
    status_code = 404


class ApprovalAlreadyDecidedError(ApprovalError):
    """Approval has already been decided."""

    error_code = "APPROVAL_ALREADY_DECIDED"
    status_code = 409


# ---- Authorization Errors ----


class AuthorizationError(KiteShieldError):
    """Capability authorization error."""

    error_code = "AUTHORIZATION_ERROR"
    status_code = 403


class TokenExpiredError(AuthorizationError):
    """Capability token has expired."""

    error_code = "TOKEN_EXPIRED"


class TokenInvalidError(AuthorizationError):
    """Capability token signature or claims are invalid."""

    error_code = "TOKEN_INVALID"


class TokenConsumedError(AuthorizationError):
    """Capability token has already been consumed (replay attempt)."""

    error_code = "TOKEN_CONSUMED"
    status_code = 409


class TokenMismatchError(AuthorizationError):
    """Transaction parameters do not match capability token claims."""

    error_code = "TOKEN_MISMATCH"


# ---- Signer Errors ----


class SignerError(KiteShieldError):
    """Signing-related error."""

    error_code = "SIGNER_ERROR"
    status_code = 500


class SigningRejectedError(SignerError):
    """Signer rejected the transaction after independent verification."""

    error_code = "SIGNING_REJECTED"
    status_code = 403


class EmergencyStopError(KiteShieldError):
    """Emergency-stop state prevented or prevented determining execution."""

    error_code = "EMERGENCY_STOP"
    status_code = 503


class EmergencyStopActiveError(EmergencyStopError):
    """Execution is halted by the authoritative emergency stop."""

    error_code = "EMERGENCY_STOP_ACTIVE"
    status_code = 403


class EmergencyStopUnavailableError(EmergencyStopError):
    """Authoritative emergency-stop state could not be read."""

    error_code = "EMERGENCY_STOP_UNAVAILABLE"
    status_code = 503


class AuditCheckpointError(KiteShieldError):
    """Base error for persistent audit checkpoint operations."""

    error_code = "AUDIT_CHECKPOINT_ERROR"
    status_code = 503


class AuditCheckpointRangeError(AuditCheckpointError):
    """Requested checkpoint range is invalid."""

    error_code = "AUDIT_CHECKPOINT_RANGE_INVALID"
    status_code = 422


class AuditCheckpointNotFoundError(AuditCheckpointError):
    """Requested checkpoint does not exist."""

    error_code = "AUDIT_CHECKPOINT_NOT_FOUND"
    status_code = 404


class AuditProofEventNotFoundError(AuditCheckpointError):
    """Requested audit event does not exist."""

    error_code = "AUDIT_PROOF_EVENT_NOT_FOUND"
    status_code = 404


class AuditProofInvalidError(AuditCheckpointError):
    """Inclusion proof does not match the persisted checkpoint."""

    error_code = "AUDIT_PROOF_INVALID"
    status_code = 422


# ---- Blockchain Errors ----


class BlockchainError(KiteShieldError):
    """Blockchain interaction error."""

    error_code = "BLOCKCHAIN_ERROR"
    status_code = 502


class TransactionSubmissionError(BlockchainError):
    """Failed to submit transaction to the network."""

    error_code = "TX_SUBMISSION_ERROR"


class RPCError(BlockchainError):
    """RPC provider returned an error or timed out."""

    error_code = "RPC_ERROR"


# ---- Resource Errors ----


class NotFoundError(KiteShieldError):
    """Requested resource not found."""

    error_code = "NOT_FOUND"
    status_code = 404


class ConflictError(KiteShieldError):
    """Operation conflicts with current state."""

    error_code = "CONFLICT"
    status_code = 409


# ---- Authentication Errors ----


class AuthenticationError(KiteShieldError):
    """API authentication failed."""

    error_code = "AUTHENTICATION_ERROR"
    status_code = 401
