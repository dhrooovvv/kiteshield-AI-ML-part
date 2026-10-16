"""
KiteShield Wallet — Audit Service

Records security-relevant lifecycle events with hash chaining.
Provides tamper detection (not tamper-proof — see SECURITY.md).

Security invariants enforced:
- SI-11: No secrets in audit events (caller responsibility + sanitization)
- Events are append-only at the application layer
- Hash chain links each event to its predecessor

Event types:
- PROPOSAL_CREATED
- POLICY_EVALUATED / POLICY_ALLOW / POLICY_ESCALATE / POLICY_BLOCK
- APPROVAL_REQUESTED / APPROVAL_APPROVED / APPROVAL_REJECTED / APPROVAL_EXPIRED
- CAPABILITY_ISSUED / CAPABILITY_CONSUMED / CAPABILITY_REJECTED
- SIGNING_REQUESTED / SIGNING_COMPLETED / SIGNING_REJECTED
- TX_SUBMITTED / TX_CONFIRMED / TX_FAILED
"""

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models import AuditEvent

logger = get_logger("audit")

_CHRONOLOGICAL_ORDER = (AuditEvent.created_at.asc(), AuditEvent.id.asc())
_REVERSE_CHRONOLOGICAL_ORDER = (AuditEvent.created_at.desc(), AuditEvent.id.desc())

# Fields that must never appear in audit event details
_FORBIDDEN_FIELDS = frozenset(
    {
        "private_key",
        "signer_private_key",
        "secret",
        "capability_token_secret",
        "api_key",
        "openai_api_key",
        "password",
        "seed_phrase",
        "mnemonic",
        "signing_key",
        "token_secret",
        "raw_token",
    }
)


def _sanitize_details(details: dict[str, Any]) -> dict[str, Any]:
    """Remove sensitive fields from audit event details."""
    sanitized = {}
    for key, value in details.items():
        if key.lower() in _FORBIDDEN_FIELDS:
            sanitized[key] = "[REDACTED]"
        elif isinstance(value, dict):
            sanitized[key] = _sanitize_details(value)
        else:
            sanitized[key] = value
    return sanitized


def _compute_event_hash(
    event_type: str,
    correlation_id: str,
    actor: str,
    details_json: str,
    previous_hash: str | None,
    created_at: str,
) -> str:
    """Compute SHA-256 hash for audit event chain.

    Canonical format: previous_hash|event_type|correlation_id|actor|details|created_at
    """
    canonical = (
        f"{previous_hash or 'GENESIS'}|{event_type}|"
        f"{correlation_id}|{actor}|{details_json}|{created_at}"
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class AuditService:
    """Append-only audit event recording with hash chaining.

    Thread/async safety: Each call creates its own event with the latest
    chain hash. For SQLite, writes are serialized so the chain is consistent.
    """

    async def record_event(
        self,
        session: AsyncSession,
        event_type: str,
        correlation_id: str,
        actor: str,
        details: dict[str, Any],
        policy_version: int | None = None,
    ) -> AuditEvent:
        """Record a new audit event.

        Args:
            session: Database session (caller manages transaction)
            event_type: Event type identifier (e.g., POLICY_ALLOW)
            correlation_id: Links related events across the lifecycle
            actor: Who/what caused this event (e.g., "policy_engine", "user:admin")
            details: Structured event data (sanitized, no secrets)
            policy_version: Policy version in effect, if applicable

        Returns:
            The created AuditEvent
        """
        # Sanitize details to prevent secret leakage
        safe_details = _sanitize_details(details)
        details_json = json.dumps(safe_details, sort_keys=True, default=str)

        # Get the previous event's hash for chain linking
        result = await session.execute(
            select(AuditEvent.event_hash).order_by(*_REVERSE_CHRONOLOGICAL_ORDER).limit(1)
        )
        previous_hash = result.scalar_one_or_none()

        now = datetime.now(UTC).isoformat()
        event_hash = _compute_event_hash(
            event_type=event_type,
            correlation_id=correlation_id,
            actor=actor,
            details_json=details_json,
            previous_hash=previous_hash,
            created_at=now,
        )

        event = AuditEvent(
            id=str(uuid.uuid4()),
            correlation_id=correlation_id,
            event_type=event_type,
            actor=actor,
            details=details_json,
            policy_version=policy_version,
            previous_hash=previous_hash,
            event_hash=event_hash,
            created_at=now,
        )
        session.add(event)
        await session.flush()

        logger.info(
            "Audit event recorded: %s (correlation=%s, actor=%s)",
            event_type,
            correlation_id,
            actor,
        )
        return event

    async def get_events_by_correlation(
        self,
        session: AsyncSession,
        correlation_id: str,
    ) -> list[AuditEvent]:
        """Retrieve all audit events for a correlation ID, ordered chronologically."""
        result = await session.execute(
            select(AuditEvent)
            .where(AuditEvent.correlation_id == correlation_id)
            .order_by(*_CHRONOLOGICAL_ORDER)
        )
        return list(result.scalars().all())

    async def verify_chain_integrity(
        self,
        session: AsyncSession,
        limit: int = 100,
    ) -> tuple[bool, list[str]]:
        """Verify the integrity of the audit hash chain.

        Returns (is_valid, list_of_errors).
        Note: This detects accidental corruption but cannot prevent
        a determined attacker with database access.
        """
        result = await session.execute(
            select(AuditEvent).order_by(*_CHRONOLOGICAL_ORDER).limit(limit)
        )
        events = list(result.scalars().all())

        errors: list[str] = []
        previous_hash: str | None = None

        for event in events:
            # Verify chain linkage
            if event.previous_hash != previous_hash:
                errors.append(
                    f"Event {event.id}: expected previous_hash "
                    f"'{previous_hash}', got '{event.previous_hash}'"
                )

            # Verify event hash
            expected_hash = _compute_event_hash(
                event_type=event.event_type,
                correlation_id=event.correlation_id,
                actor=event.actor,
                details_json=event.details,
                previous_hash=event.previous_hash,
                created_at=event.created_at,
            )
            if event.event_hash != expected_hash:
                errors.append(
                    f"Event {event.id}: hash mismatch "
                    f"(expected '{expected_hash[:16]}...', got '{event.event_hash[:16]}...')"
                )

            previous_hash = event.event_hash

        return len(errors) == 0, errors
