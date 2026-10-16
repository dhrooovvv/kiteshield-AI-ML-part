"""
KiteShield Wallet — Audit Trail Endpoints

Provides cryptographically chained, immutable audit event retrieval and verification.

Security:
- Never returns private keys or secrets.
- Verifies SHA-256 hash chaining to detect tampering or corruption.
"""

import json
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import correlation_id_var, get_logger
from app.core.security import verify_api_key
from app.db import get_db_session
from app.schemas import (
    APIResponse,
    AuditCheckpointRequest,
    AuditCheckpointResponse,
    AuditEventResponse,
    AuditProofResponse,
    AuditProofVerificationRequest,
    AuditTrailResponse,
)
from app.services.audit import AuditService
from app.services.audit_checkpoint import AuditCheckpointService

logger = get_logger("routes.audit")
router = APIRouter(prefix="/audit", tags=["Audit"])
audit_service = AuditService()
checkpoint_service = AuditCheckpointService()


def _checkpoint_response(checkpoint: Any) -> APIResponse:
    return APIResponse(
        data=AuditCheckpointResponse.model_validate(checkpoint, from_attributes=True),
        meta={"correlation_id": correlation_id_var.get()},
    )


@router.post("/checkpoints", response_model=APIResponse)
async def create_audit_checkpoint(
    request: AuditCheckpointRequest,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    _: Annotated[str, Depends(verify_api_key)],
) -> APIResponse:
    """Create and persist a Merkle checkpoint over an audit-event range."""
    checkpoint = await checkpoint_service.create_checkpoint(
        session=session,
        first_event_id=request.first_event_id,
        last_event_id=request.last_event_id,
    )
    return _checkpoint_response(checkpoint)


@router.get("/checkpoints/{checkpoint_id}", response_model=APIResponse)
async def get_audit_checkpoint(
    checkpoint_id: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    _: Annotated[str, Depends(verify_api_key)],
) -> APIResponse:
    """Retrieve a persisted Merkle checkpoint."""
    checkpoint = await checkpoint_service.get_checkpoint(session, checkpoint_id)
    return _checkpoint_response(checkpoint)


@router.get(
    "/checkpoints/{checkpoint_id}/proofs/{event_id}", response_model=APIResponse
)
async def generate_audit_proof(
    checkpoint_id: str,
    event_id: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    _: Annotated[str, Depends(verify_api_key)],
) -> APIResponse:
    """Generate an inclusion proof for an event in a persisted checkpoint."""
    proof = await checkpoint_service.generate_proof(
        session=session, checkpoint_id=checkpoint_id, event_id=event_id
    )
    return APIResponse(
        data=AuditProofResponse.model_validate(proof),
        meta={"correlation_id": correlation_id_var.get()},
    )


@router.post(
    "/checkpoints/{checkpoint_id}/proofs/verify", response_model=APIResponse
)
async def verify_audit_proof(
    checkpoint_id: str,
    request: AuditProofVerificationRequest,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    _: Annotated[str, Depends(verify_api_key)],
) -> APIResponse:
    """Verify an inclusion proof against the persisted checkpoint root."""
    proof = await checkpoint_service.verify_proof(
        session=session,
        checkpoint_id=checkpoint_id,
        event_id=request.event_id,
        index=request.index,
        leaf_hash=request.leaf_hash,
        proof=request.proof,
    )
    return APIResponse(
        data=AuditProofResponse.model_validate(proof),
        meta={"correlation_id": correlation_id_var.get()},
    )


@router.get("/integrity/verify", response_model=APIResponse)
async def verify_audit_integrity(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    _: Annotated[str, Depends(verify_api_key)],
    limit: int = 100,
) -> APIResponse:
    """Verify integrity of the global audit hash chain."""
    cid = correlation_id_var.get()
    is_valid, errors = await audit_service.verify_chain_integrity(session=session, limit=limit)
    return APIResponse(
        data={"is_valid": is_valid, "errors": errors, "checked_limit": limit},
        meta={"correlation_id": cid},
    )


@router.get("/{correlation_id}", response_model=APIResponse)
async def get_audit_trail(
    correlation_id: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    _: Annotated[str, Depends(verify_api_key)],
) -> APIResponse:
    """Retrieve full chronological audit trail for a correlation ID."""
    cid = correlation_id_var.get()
    events = await audit_service.get_events_by_correlation(
        session=session, correlation_id=correlation_id
    )

    formatted_events: list[AuditEventResponse] = []
    for ev in events:
        details_dict = json.loads(ev.details) if isinstance(ev.details, str) else ev.details
        formatted_events.append(
            AuditEventResponse(
                id=ev.id,
                correlation_id=ev.correlation_id,
                event_type=ev.event_type,
                actor=ev.actor,
                details=details_dict,
                policy_version=ev.policy_version,
                previous_hash=ev.previous_hash,
                event_hash=ev.event_hash,
                created_at=ev.created_at,
            )
        )

    # Check chain integrity for this set of events
    is_valid, _ = await audit_service.verify_chain_integrity(session=session, limit=200)

    trail = AuditTrailResponse(
        correlation_id=correlation_id,
        events=formatted_events,
        chain_valid=is_valid,
    )
    return APIResponse(
        data=trail, meta={"correlation_id": cid, "total_events": len(formatted_events)}
    )
