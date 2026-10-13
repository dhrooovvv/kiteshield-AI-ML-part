"""
KiteShield Wallet — Approvals Management Endpoints

Handles human review and approval/rejection for escalated transactions.

Security Invariants:
- SI-5: Escalated proposals strictly require human approval before capability token issuance.
- SI-8: Approvals are cryptographically bound to the exact transaction action via action_digest.
- Approvals cannot be decided twice (conflict / idempotent check).
- Expired approvals cannot be approved.
"""

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.logging import correlation_id_var, get_logger
from app.core.security import verify_api_key
from app.db import get_db_session
from app.exceptions import (
    ApprovalAlreadyDecidedError,
    ApprovalExpiredError,
    NotFoundError,
)
from app.models import ApprovalRequest, Proposal, utc_now_str
from app.schemas import (
    APIResponse,
    ApprovalDecisionRequest,
    ProposalStatus,
)
from app.services.audit import AuditService

logger = get_logger("routes.approvals")
router = APIRouter(prefix="/approvals", tags=["Approvals"])
audit_service = AuditService()


def _format_approval(approval: ApprovalRequest, proposal: Proposal | None = None) -> dict[str, Any]:
    """Format approval data with proposal details."""
    data: dict[str, Any] = {
        "id": approval.id,
        "proposal_id": approval.proposal_id,
        "action_digest": approval.action_digest,
        "status": approval.status,
        "expires_at": approval.expires_at,
        "approved_by": approval.approved_by,
        "decided_at": approval.decided_at,
        "created_at": approval.created_at,
    }
    if proposal:
        data["proposal"] = {
            "prompt": proposal.agent_prompt,
            "recipient": proposal.recipient,
            "amount_wei": proposal.amount_wei,
            "amount_eth": f"{int(proposal.amount_wei) / 10**18:.6f}".rstrip("0").rstrip("."),
            "chain_id": proposal.chain_id,
        }
    return data


@router.get("/pending", response_model=APIResponse)
async def list_pending_approvals(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    _: Annotated[str, Depends(verify_api_key)],
) -> APIResponse:
    """List all pending approval requests awaiting human authorization."""
    cid = correlation_id_var.get()
    stmt = (
        select(ApprovalRequest)
        .options(selectinload(ApprovalRequest.proposal))
        .where(ApprovalRequest.status == "PENDING")
        .order_by(ApprovalRequest.created_at.asc())
    )
    result = await session.execute(stmt)
    approvals = result.scalars().all()

    now = datetime.now(UTC)
    active_pending = []
    for app_req in approvals:
        exp = datetime.fromisoformat(app_req.expires_at)
        prop = app_req.__dict__.get("proposal")
        if exp < now:
            # Mark expired
            app_req.status = "EXPIRED"
            if prop:
                prop.status = ProposalStatus.EXPIRED_APPROVAL
        else:
            active_pending.append(_format_approval(app_req, prop))

    await session.flush()
    return APIResponse(
        data=active_pending,
        meta={"correlation_id": cid, "total_pending": len(active_pending)},
    )


@router.post("/{approval_id}/decide", response_model=APIResponse)
async def decide_approval(
    approval_id: str,
    request: ApprovalDecisionRequest,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    _: Annotated[str, Depends(verify_api_key)],
) -> APIResponse:
    """Approve or reject an escalated proposal."""
    cid = correlation_id_var.get()
    stmt = (
        select(ApprovalRequest)
        .options(selectinload(ApprovalRequest.proposal))
        .where(ApprovalRequest.id == approval_id)
    )
    result = await session.execute(stmt)
    approval = result.scalar_one_or_none()

    if not approval:
        raise NotFoundError(f"Approval request {approval_id} not found")

    if approval.status != "PENDING":
        raise ApprovalAlreadyDecidedError(
            f"Approval request has already been decided: current status is {approval.status}",
            details={"status": approval.status, "decided_at": approval.decided_at},
        )

    # Query proposal explicitly
    prop_stmt = select(Proposal).where(Proposal.id == approval.proposal_id)
    prop_res = await session.execute(prop_stmt)
    proposal = prop_res.scalar_one_or_none()

    # Check expiration
    now = datetime.now(UTC)
    exp = datetime.fromisoformat(approval.expires_at)
    if exp < now:
        approval.status = "EXPIRED"
        if proposal:
            proposal.status = ProposalStatus.EXPIRED_APPROVAL
        await session.flush()
        raise ApprovalExpiredError(
            f"Approval request expired at {approval.expires_at}",
            details={"expires_at": approval.expires_at},
        )

    now_str = utc_now_str()

    if request.decision == "APPROVE":
        approval.status = "APPROVED"
        approval.approved_by = request.approved_by
        approval.decided_at = now_str
        if proposal:
            proposal.status = ProposalStatus.APPROVED
            proposal.updated_at = now_str

        await audit_service.record_event(
            session=session,
            event_type="APPROVAL_APPROVED",
            correlation_id=proposal.correlation_id if proposal else cid,
            actor=request.approved_by,
            details={
                "approval_id": approval.id,
                "proposal_id": approval.proposal_id,
                "action_digest": approval.action_digest,
            },
        )
        logger.info("Approval %s APPROVED by %s", approval.id, request.approved_by)

    else:
        approval.status = "REJECTED"
        approval.approved_by = request.approved_by
        approval.decided_at = now_str
        if proposal:
            proposal.status = ProposalStatus.REJECTED
            proposal.updated_at = now_str

        await audit_service.record_event(
            session=session,
            event_type="APPROVAL_REJECTED",
            correlation_id=proposal.correlation_id if proposal else cid,
            actor=request.approved_by,
            details={
                "approval_id": approval.id,
                "proposal_id": approval.proposal_id,
                "action_digest": approval.action_digest,
            },
        )
        logger.info("Approval %s REJECTED by %s", approval.id, request.approved_by)

    await session.flush()
    return APIResponse(
        data=_format_approval(approval, proposal),
        meta={"correlation_id": cid},
    )
