"""
KiteShield Wallet — Proposal Lifecycle Endpoints

Orchestrates the constrained authorization lifecycle:
1. Agent proposes (Natural Language or Normalized schema)
2. Deterministic policy evaluation (ALLOW / ESCALATE / BLOCK)
3. Human approval for escalated proposals
4. Capability token issuance
5. Isolated signer verification & atomic token consumption
6. Sepolia blockchain submission
7. Chained audit event recording

Security Invariants:
- SI-1: Model output is untrusted.
- SI-2: Invalid proposals cannot be signed.
- SI-3: BLOCK never leads to signing.
- SI-4: Autonomous execution only within verified limits.
- SI-5: Escalated proposals strictly require human approval.
- SI-6: Capability tokens are single-use.
- SI-7: Tokens strictly transaction-bound.
- SI-8: Approvals bound to exact action digest.
- SI-9: Signer independently verifies all claims.
- SI-10: Private keys never sent to browser/LLM.
- SI-11: No secrets in audit logs.
- SI-12: Fail-closed on any uncertainty.
"""

import json
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.logging import correlation_id_var, get_logger
from app.core.security import verify_api_key
from app.db import get_db_session
from app.exceptions import (
    ApprovalRequiredError,
    NotFoundError,
    PolicyBlockError,
    PolicyNotFoundError,
    SigningRejectedError,
)
from app.models import (
    ApprovalRequest,
    Policy,
    Proposal,
    SpendingRecord,
    utc_now_str,
)
from app.models import (
    PolicyDecision as PolicyDecisionModel,
)
from app.models import (
    Transaction as TransactionModel,
)
from app.schemas import (
    AgentPromptRequest,
    AgentProposalRequest,
    APIResponse,
    ApprovalResponse,
    AssetType,
    NormalizedAction,
    PolicyDecisionResponse,
    PolicyDecisionType,
    ProposalListResponse,
    ProposalResponse,
    ProposalStatus,
    TransactionResponse,
)
from app.services.agent import AgentService
from app.services.audit import AuditService
from app.services.blockchain import BlockchainService
from app.services.capability import CapabilityService
from app.services.policy_engine import PolicyConfig, PolicyEngine
from app.services.signer import IsolatedSigner

logger = get_logger("routes.proposals")
router = APIRouter(prefix="/proposals", tags=["Proposals"])

agent_service = AgentService()
policy_engine = PolicyEngine()
capability_service = CapabilityService()
isolated_signer = IsolatedSigner(capability_service=capability_service)
blockchain_service = BlockchainService()
audit_service = AuditService()


def _model_to_proposal_response(p: Proposal) -> ProposalResponse:
    """Format Proposal model with nested relationships into ProposalResponse."""
    amount_eth = f"{int(p.amount_wei) / 10**18:.18f}".rstrip("0").rstrip(".")
    if not amount_eth:
        amount_eth = "0"

    policy_dec = p.__dict__.get("policy_decision")
    decision_resp = None
    if policy_dec:
        reason_codes = (
            json.loads(policy_dec.reason_codes)
            if isinstance(policy_dec.reason_codes, str)
            else policy_dec.reason_codes
        )
        decision_resp = PolicyDecisionResponse(
            decision=PolicyDecisionType(policy_dec.decision),
            reason_codes=reason_codes,
            policy_version=policy_dec.policy_version,
            evaluated_at=policy_dec.evaluated_at,
        )

    app_req = p.__dict__.get("approval_request")
    approval_resp = None
    if app_req:
        approval_resp = ApprovalResponse(
            id=app_req.id,
            status=app_req.status,
            action_digest=app_req.action_digest,
            expires_at=app_req.expires_at,
            decided_at=app_req.decided_at,
        )

    tx_rec = p.__dict__.get("transaction")
    tx_resp = None
    if tx_rec:
        tx_resp = TransactionResponse(
            id=tx_rec.id,
            tx_hash=tx_rec.tx_hash,
            status=tx_rec.status,
            block_number=tx_rec.block_number,
            gas_used=tx_rec.gas_used,
            error_message=tx_rec.error_message,
            created_at=tx_rec.created_at,
            updated_at=tx_rec.updated_at,
        )

    return ProposalResponse(
        id=p.id,
        correlation_id=p.correlation_id,
        prompt=p.agent_prompt,
        recipient=p.recipient,
        amount_wei=p.amount_wei,
        amount_eth=amount_eth,
        chain_id=p.chain_id,
        asset_type=p.asset_type,
        status=ProposalStatus(p.status),
        created_at=p.created_at,
        updated_at=p.updated_at,
        policy_decision=decision_resp,
        approval=approval_resp,
        transaction=tx_resp,
    )


@router.post("", response_model=APIResponse)
async def create_proposal(
    request: AgentProposalRequest,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    _: Annotated[str, Depends(verify_api_key)],
) -> APIResponse:
    """Create a structured proposal directly (from agent or caller)."""
    cid = correlation_id_var.get()
    now_str = utc_now_str()

    proposal = Proposal(
        correlation_id=cid,
        agent_prompt=request.prompt,
        recipient=request.recipient,
        amount_wei=request.amount_wei,
        chain_id=request.chain_id,
        asset_type=request.asset_type.value,
        status=ProposalStatus.PROPOSED.value,
        created_at=now_str,
        updated_at=now_str,
    )
    session.add(proposal)
    await session.flush()

    await audit_service.record_event(
        session=session,
        event_type="PROPOSAL_CREATED",
        correlation_id=cid,
        actor="agent",
        details={
            "proposal_id": proposal.id,
            "recipient": proposal.recipient,
            "amount_wei": proposal.amount_wei,
            "chain_id": proposal.chain_id,
            "prompt": proposal.agent_prompt,
        },
    )

    logger.info(
        "Proposal created: id=%s (recipient=%s, amount=%s)",
        proposal.id,
        proposal.recipient,
        proposal.amount_wei,
    )
    return APIResponse(data=_model_to_proposal_response(proposal), meta={"correlation_id": cid})


@router.post("/agent", response_model=APIResponse)
async def agent_propose(
    request: AgentPromptRequest,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    _: Annotated[str, Depends(verify_api_key)],
) -> APIResponse:
    """AI Agent endpoint: transforms natural language instructions into a proposal."""
    cid = correlation_id_var.get()

    # Call agent service to extract structured parameters
    structured_proposal = await agent_service.propose_transaction_from_prompt(request.prompt)

    now_str = utc_now_str()
    proposal = Proposal(
        correlation_id=cid,
        agent_prompt=structured_proposal.prompt,
        recipient=structured_proposal.recipient,
        amount_wei=structured_proposal.amount_wei,
        chain_id=structured_proposal.chain_id,
        asset_type=structured_proposal.asset_type.value,
        status=ProposalStatus.PROPOSED.value,
        created_at=now_str,
        updated_at=now_str,
    )
    session.add(proposal)
    await session.flush()

    await audit_service.record_event(
        session=session,
        event_type="PROPOSAL_CREATED",
        correlation_id=cid,
        actor="agent:gpt-4o",
        details={
            "proposal_id": proposal.id,
            "recipient": proposal.recipient,
            "amount_wei": proposal.amount_wei,
            "chain_id": proposal.chain_id,
            "prompt": proposal.agent_prompt,
        },
    )

    logger.info("Agent proposal created: id=%s from prompt='%s'", proposal.id, request.prompt[:50])
    return APIResponse(data=_model_to_proposal_response(proposal), meta={"correlation_id": cid})


@router.get("", response_model=APIResponse)
async def list_proposals(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    _: Annotated[str, Depends(verify_api_key)],
    status: ProposalStatus | None = Query(None, description="Filter by status"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> APIResponse:
    """List proposals with pagination and optional status filter."""
    cid = correlation_id_var.get()
    stmt = (
        select(Proposal)
        .options(
            selectinload(Proposal.policy_decision),
            selectinload(Proposal.approval_request),
            selectinload(Proposal.transaction),
        )
        .order_by(desc(Proposal.created_at))
    )
    if status is not None:
        stmt = stmt.where(Proposal.status == status.value)

    count_stmt = select(func.count()).select_from(Proposal)
    if status is not None:
        count_stmt = count_stmt.where(Proposal.status == status.value)

    total_res = await session.execute(count_stmt)
    total_count = total_res.scalar_one()

    stmt = stmt.limit(limit).offset(offset)
    result = await session.execute(stmt)
    proposals = result.scalars().all()

    resp = ProposalListResponse(
        proposals=[_model_to_proposal_response(p) for p in proposals],
        total=total_count,
    )
    return APIResponse(data=resp.model_dump(), meta={"correlation_id": cid, "total": total_count})


@router.get("/{proposal_id}", response_model=APIResponse)
async def get_proposal(
    proposal_id: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    _: Annotated[str, Depends(verify_api_key)],
) -> APIResponse:
    """Retrieve complete proposal details by ID."""
    cid = correlation_id_var.get()
    stmt = (
        select(Proposal)
        .options(
            selectinload(Proposal.policy_decision),
            selectinload(Proposal.approval_request),
            selectinload(Proposal.transaction),
        )
        .where(Proposal.id == proposal_id)
    )
    result = await session.execute(stmt)
    proposal = result.scalar_one_or_none()

    if not proposal:
        raise NotFoundError(f"Proposal {proposal_id} not found")

    return APIResponse(data=_model_to_proposal_response(proposal), meta={"correlation_id": cid})


@router.post("/{proposal_id}/evaluate", response_model=APIResponse)
async def evaluate_proposal(
    proposal_id: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    _: Annotated[str, Depends(verify_api_key)],
) -> APIResponse:
    """Evaluate proposal against current active policy.

    Transitions status to ALLOWED, ESCALATED, or BLOCKED.
    If ESCALATED, creates an ApprovalRequest awaiting human authorization.
    """
    cid = correlation_id_var.get()
    stmt = (
        select(Proposal)
        .options(
            selectinload(Proposal.policy_decision),
            selectinload(Proposal.approval_request),
            selectinload(Proposal.transaction),
        )
        .where(Proposal.id == proposal_id)
    )
    result = await session.execute(stmt)
    proposal = result.scalar_one_or_none()

    if not proposal:
        raise NotFoundError(f"Proposal {proposal_id} not found")

    # Fetch active policy
    policy_stmt = (
        select(Policy).where(Policy.is_active.is_(True)).order_by(desc(Policy.version)).limit(1)
    )
    policy_res = await session.execute(policy_stmt)
    active_policy = policy_res.scalar_one_or_none()

    if not active_policy:
        raise PolicyNotFoundError(
            "No active policy found. An administrator must configure a policy first."
        )

    # Calculate daily spending for today (YYYY-MM-DD)
    today_date = datetime.now(UTC).strftime("%Y-%m-%d")
    spending_stmt = (
        select(SpendingRecord.amount_wei)
        .where(SpendingRecord.period_date == today_date)
        .where(SpendingRecord.status.in_(["RESERVED", "COMMITTED"]))
    )
    spending_res = await session.execute(spending_stmt)
    daily_spent_wei = sum(int(amt) for amt in spending_res.scalars().all())

    # Build canonical action
    action = NormalizedAction(
        proposal_id=proposal.id,
        correlation_id=proposal.correlation_id,
        action_type=AssetType(proposal.asset_type),
        recipient=proposal.recipient,
        amount_wei=int(proposal.amount_wei),
        chain_id=proposal.chain_id,
    )

    # Evaluate deterministically
    policy_cfg = PolicyConfig.from_db_row(active_policy)
    decision = policy_engine.evaluate(
        action=action,
        policy=policy_cfg,
        current_daily_spending_wei=daily_spent_wei,
    )

    # Record or update PolicyDecision
    existing_dec_stmt = select(PolicyDecisionModel).where(
        PolicyDecisionModel.proposal_id == proposal.id
    )
    dec_res = await session.execute(existing_dec_stmt)
    policy_decision_record = dec_res.scalar_one_or_none()

    reasons_json = json.dumps(decision.reason_codes)
    now_str = utc_now_str()

    if policy_decision_record:
        policy_decision_record.decision = decision.decision.value
        policy_decision_record.reason_codes = reasons_json
        policy_decision_record.policy_version = decision.policy_version
        policy_decision_record.evaluated_at = now_str
    else:
        policy_decision_record = PolicyDecisionModel(
            proposal_id=proposal.id,
            decision=decision.decision.value,
            reason_codes=reasons_json,
            policy_version=decision.policy_version,
            evaluated_at=now_str,
        )
        session.add(policy_decision_record)

    # Transition proposal state
    if decision.decision == PolicyDecisionType.ALLOW:
        proposal.status = ProposalStatus.ALLOWED.value
        event_type = "POLICY_ALLOW"
    elif decision.decision == PolicyDecisionType.ESCALATE:
        proposal.status = ProposalStatus.ESCALATED.value
        event_type = "POLICY_ESCALATE"

        # Create or update ApprovalRequest
        existing_app_stmt = select(ApprovalRequest).where(
            ApprovalRequest.proposal_id == proposal.id
        )
        app_res = await session.execute(existing_app_stmt)
        app_req = app_res.scalar_one_or_none()

        expires_at = (datetime.now(UTC) + timedelta(minutes=15)).isoformat()
        action_digest = action.action_digest_without_nonce()

        if app_req:
            app_req.status = "PENDING"
            app_req.action_digest = action_digest
            app_req.expires_at = expires_at
        else:
            app_req = ApprovalRequest(
                proposal_id=proposal.id,
                action_digest=action_digest,
                status="PENDING",
                expires_at=expires_at,
            )
            session.add(app_req)

        proposal.approval_request = app_req

    else:  # BLOCK
        proposal.status = ProposalStatus.BLOCKED.value
        event_type = "POLICY_BLOCK"

    proposal.updated_at = now_str
    await session.flush()

    # Record audit event
    await audit_service.record_event(
        session=session,
        event_type=event_type,
        correlation_id=proposal.correlation_id,
        actor="policy_engine",
        details={
            "proposal_id": proposal.id,
            "decision": decision.decision.value,
            "reason_codes": decision.reason_codes,
            "policy_version": decision.policy_version,
            "daily_spent_wei": str(daily_spent_wei),
        },
        policy_version=decision.policy_version,
    )

    # Refresh relationship
    proposal.policy_decision = policy_decision_record
    return APIResponse(data=_model_to_proposal_response(proposal), meta={"correlation_id": cid})


@router.post("/{proposal_id}/sign", response_model=APIResponse)
async def sign_and_submit_proposal(
    proposal_id: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    _: Annotated[str, Depends(verify_api_key)],
) -> APIResponse:
    """Sign and broadcast an authorized transaction proposal.

    Security Gate:
    - Proposal must be ALLOWED or APPROVED.
    - Active policy must match evaluation version.
    - Single-use capability token issued and verified.
    - Signer independently checks parameters, digests, and token replay before signing.
    - Broadcasts to Sepolia and updates transaction status.
    """
    cid = correlation_id_var.get()
    stmt = (
        select(Proposal)
        .options(
            selectinload(Proposal.policy_decision),
            selectinload(Proposal.approval_request),
            selectinload(Proposal.transaction),
        )
        .where(Proposal.id == proposal_id)
    )
    result = await session.execute(stmt)
    proposal = result.scalar_one_or_none()

    if not proposal:
        raise NotFoundError(f"Proposal {proposal_id} not found")

    # Invariant: Must be in ALLOWED or APPROVED status
    if proposal.status == ProposalStatus.BLOCKED.value:
        raise PolicyBlockError(
            "Proposal was BLOCKED by policy and cannot be signed.",
            details={"status": proposal.status},
        )
    if proposal.status == ProposalStatus.ESCALATED.value:
        raise ApprovalRequiredError(
            "Proposal is ESCALATED and requires human approval before signing.",
            details={"status": proposal.status},
        )
    if proposal.status not in (ProposalStatus.ALLOWED.value, ProposalStatus.APPROVED.value):
        raise SigningRejectedError(
            f"Proposal in invalid state for signing: {proposal.status}",
            details={"status": proposal.status},
        )

    # Fetch active policy
    policy_stmt = (
        select(Policy).where(Policy.is_active.is_(True)).order_by(desc(Policy.version)).limit(1)
    )
    policy_res = await session.execute(policy_stmt)
    active_policy = policy_res.scalar_one_or_none()

    if not active_policy:
        raise PolicyNotFoundError("No active policy found")

    # Construct canonical action
    action = NormalizedAction(
        proposal_id=proposal.id,
        correlation_id=proposal.correlation_id,
        action_type=AssetType(proposal.asset_type),
        recipient=proposal.recipient,
        amount_wei=int(proposal.amount_wei),
        chain_id=proposal.chain_id,
    )

    # Check approval if required
    approval_id = None
    if proposal.status == ProposalStatus.APPROVED.value:
        if not proposal.approval_request or proposal.approval_request.status != "APPROVED":
            raise ApprovalRequiredError("Valid approved human authorization is required")

        # Verify action digest matches
        expected_approval_digest = action.action_digest_without_nonce()
        if proposal.approval_request.action_digest != expected_approval_digest:
            raise SigningRejectedError(
                "Approval action digest does not match current transaction parameters",
                details={
                    "approval_digest": proposal.approval_request.action_digest,
                    "computed_digest": expected_approval_digest,
                },
            )
        approval_id = proposal.approval_request.id

    # Step 1: Issue capability token
    token, claims = await capability_service.issue_token(
        session=session,
        action=action,
        policy_version=active_policy.version,
        approval_id=approval_id,
    )

    await audit_service.record_event(
        session=session,
        event_type="CAPABILITY_ISSUED",
        correlation_id=proposal.correlation_id,
        actor="capability_service",
        details={
            "proposal_id": proposal.id,
            "jti": claims["jti"],
            "policy_version": active_policy.version,
            "tx_digest": claims["tx_digest"],
        },
        policy_version=active_policy.version,
    )

    # Step 2: Isolated signer independently verifies and signs
    proposal.status = ProposalStatus.SIGNING.value
    await session.flush()

    signed_result = await isolated_signer.sign_transaction(
        session=session,
        token=token,
        action=action,
    )

    await audit_service.record_event(
        session=session,
        event_type="SIGNING_COMPLETED",
        correlation_id=proposal.correlation_id,
        actor="isolated_signer",
        details={
            "proposal_id": proposal.id,
            "jti": claims["jti"],
            "signed_tx_hash": signed_result.get("tx_hash"),
        },
        policy_version=active_policy.version,
    )

    # Step 3: Broadcast transaction to Sepolia
    proposal.status = ProposalStatus.SIGNED.value
    await session.flush()

    submission = await blockchain_service.submit_raw_transaction(
        signed_result["raw_transaction"], session=session
    )
    final_tx_hash = submission["tx_hash"]

    # Step 4: Record Transaction record
    now_str = utc_now_str()
    tx_record = TransactionModel(
        proposal_id=proposal.id,
        tx_hash=final_tx_hash,
        status="SUBMITTED",
        created_at=now_str,
        updated_at=now_str,
    )
    session.add(tx_record)

    proposal.status = ProposalStatus.SUBMITTED.value
    proposal.updated_at = now_str
    proposal.transaction = tx_record
    await session.flush()

    await audit_service.record_event(
        session=session,
        event_type="TX_SUBMITTED",
        correlation_id=proposal.correlation_id,
        actor="blockchain_service",
        details={
            "proposal_id": proposal.id,
            "tx_hash": final_tx_hash,
            "network": submission.get("network", "sepolia"),
        },
        policy_version=active_policy.version,
    )

    logger.info(
        "Proposal %s successfully signed and submitted. tx_hash=%s", proposal.id, final_tx_hash
    )
    return APIResponse(data=_model_to_proposal_response(proposal), meta={"correlation_id": cid})
