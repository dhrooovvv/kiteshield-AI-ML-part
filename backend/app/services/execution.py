"""Single native-payment execution coordinator, inside the modular monolith."""

import json
from datetime import UTC, datetime

from eth_account import Account
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.exceptions import (
    ApprovalRequiredError,
    NotFoundError,
    PolicyBlockError,
    SigningRejectedError,
    TransactionSubmissionError,
)
from app.models import ExecutionAttempt, Proposal, SpendingRecord, Transaction, generate_uuid
from app.schemas import ExecutionLimits, NormalizedAction
from app.services.audit import AuditService
from app.services.authorization import validate_authorization
from app.services.blockchain import BlockchainService
from app.services.capability import CapabilityService
from app.services.emergency_stop import EmergencyStopService
from app.services.execution_lock import lock_execution
from app.services.receipt import reconcile_receipt
from app.services.signer import IsolatedSigner


async def execute_payment(
    session: AsyncSession,
    proposal_id: str,
    capability: CapabilityService,
    signer: IsolatedSigner,
    blockchain: BlockchainService,
    audit: AuditService,
    limits: ExecutionLimits | None = None,
) -> Proposal:
    from app.services.treasury import prepare_authority_context

    await prepare_authority_context(session, proposal_id)
    await lock_execution(session)
    await EmergencyStopService().require_running(session)
    proposal = await session.scalar(
        select(Proposal)
        .where(Proposal.id == proposal_id)
        .options(
            selectinload(Proposal.policy_decision),
            selectinload(Proposal.approval_request),
            selectinload(Proposal.transaction),
        )
        .execution_options(populate_existing=True)
    )
    if not proposal:
        raise NotFoundError("Proposal not found")
    if proposal.status == "BLOCKED":
        raise PolicyBlockError("Policy blocked this proposal")
    if proposal.status == "ESCALATED":
        raise ApprovalRequiredError("Human approval is required")
    attempt = await session.scalar(
        select(ExecutionAttempt)
        .where(ExecutionAttempt.proposal_id == proposal_id)
        .execution_options(populate_existing=True)
    )
    if attempt and limits:
        limits.check_envelope(attempt.sender, json.loads(attempt.envelope))
    if attempt and attempt.status in ("SIGNED", "UNCERTAIN", "SUBMITTED", "CONFIRMED", "REVERTED"):
        if proposal.transaction:
            await reconcile_receipt(session, proposal.transaction, blockchain)
        if attempt.status in ("SUBMITTED", "CONFIRMED", "REVERTED"):
            return proposal
    action = NormalizedAction(
        proposal_id=proposal.id,
        correlation_id=proposal.correlation_id,
        recipient=proposal.recipient,
        amount_wei=int(proposal.amount_wei),
        chain_id=proposal.chain_id,
    )
    decision = proposal.policy_decision
    if not decision:
        raise SigningRejectedError("Evaluate the proposal before execution")
    approval_id = (
        proposal.approval_request.id
        if decision.decision == "ESCALATE" and proposal.approval_request
        else None
    )
    await validate_authorization(session, action, decision.policy_version, approval_id)
    if attempt is None:
        sender = Account.from_key(get_settings().signer_private_key).address
        envelope = await blockchain.prepare_transaction(session, sender, action)
        if limits:
            limits.check_envelope(sender, envelope)
            await audit.record_event(
                session, event_type="EXECUTION_LIMITS_CHECKED",
                correlation_id=proposal.correlation_id, actor="execution_coordinator",
                details={"proposal_id": proposal.id, "limits": limits.model_dump()},
            )
        attempt = ExecutionAttempt(
            id=generate_uuid(),
            proposal_id=proposal.id,
            sender=sender.lower(),
            chain_id=action.chain_id,
            nonce=envelope["nonce"],
            envelope=json.dumps(envelope, sort_keys=True, separators=(",", ":")),
            policy_version=decision.policy_version,
            approval_id=approval_id,
            status="PREPARED",
            execution_mode=get_settings().execution_mode,
        )
        session.add(attempt)
        session.add(
            SpendingRecord(
                id=attempt.id,
                proposal_id=proposal.id,
                amount_wei=str(action.amount_wei),
                status="RESERVED",
                period_date=datetime.now(UTC).date().isoformat(),
            )
        )
        await session.flush()
        token, claims = await capability.issue_token(
            session, action, decision.policy_version, approval_id, decision.decision == "ESCALATE"
        )
        await audit.record_event(
            session,
            event_type="CAPABILITY_ISSUED",
            correlation_id=proposal.correlation_id,
            actor="capability_service",
            details={"proposal_id": proposal.id, "jti": claims["jti"]},
        )
        signed = await signer.sign_transaction(session, token, action)
        attempt.raw_transaction = signed["raw_transaction"]
        attempt.tx_hash = "0x" + signed["tx_hash"].removeprefix("0x")
        attempt.status = "SIGNED"
        proposal.status = "SIGNED"
        tx = Transaction(
            proposal_id=proposal.id,
            tx_hash=attempt.tx_hash,
            status="SIGNED",
            execution_mode=attempt.execution_mode,
            execution_outcome="SIGNED",
        )
        session.add(tx)
        proposal.transaction = tx
        await audit.record_event(
            session,
            event_type="SIGNING_COMPLETED",
            correlation_id=proposal.correlation_id,
            actor="logical_signer",
            details={
                "execution_id": attempt.id,
                "proposal_id": proposal.id,
                "tx_hash": attempt.tx_hash,
                "nonce": attempt.nonce,
                "mode": get_settings().execution_mode,
            },
        )
        # No network side effect before durable execution, reservation, token
        # consumption, and signed bytes are committed together.
        await session.commit()
    elif attempt.status not in ("SIGNED", "UNCERTAIN"):
        raise SigningRejectedError("Execution is not resumable")

    await lock_execution(session)
    if attempt.execution_mode != get_settings().execution_mode:
        raise SigningRejectedError("Execution mode changed; do not broadcast a simulated payload")
    await session.refresh(attempt)
    proposal = await session.scalar(
        select(Proposal)
        .where(Proposal.id == proposal_id)
        .options(
            selectinload(Proposal.policy_decision),
            selectinload(Proposal.approval_request),
            selectinload(Proposal.transaction),
        )
        .execution_options(populate_existing=True)
    )
    if proposal is None:
        raise SigningRejectedError("Execution proposal is unavailable")
    if attempt.status == "SUBMITTED":
        return proposal
    if attempt.status in ("CONFIRMED", "REVERTED"):
        return proposal
    await EmergencyStopService().require_running(session)
    await validate_authorization(session, action, attempt.policy_version, attempt.approval_id)
    try:
        submitted = await blockchain.submit_raw_transaction(
            attempt.raw_transaction, session=session
        )
        if (
            submitted["tx_hash"].removeprefix("0x").lower()
            != attempt.tx_hash.removeprefix("0x").lower()
        ):
            raise TransactionSubmissionError(
                "RPC response hash does not match the signed execution"
            )
    except Exception:
        # Never release on timeout/rejection text: acceptance may be unknown.
        attempt.status = "UNCERTAIN"
        proposal.transaction.execution_outcome = "UNCERTAIN"
        proposal.transaction.error_message = (
            "Broadcast outcome uncertain; reconcile this same transaction"
        )
        await audit.record_event(
            session, event_type="TX_UNCERTAIN", correlation_id=proposal.correlation_id,
            actor="blockchain_service",
            details={"proposal_id": proposal.id, "execution_id": attempt.id,
                     "tx_hash": attempt.tx_hash},
        )
        await session.commit()
        raise
    attempt.status = "SUBMITTED"
    proposal.status = "SUBMITTED"
    proposal.transaction.status = "SUBMITTED"
    proposal.transaction.execution_outcome = (
        "SIMULATED" if attempt.execution_mode == "simulated" else "SUBMITTED"
    )
    proposal.transaction.error_message = None
    reservation = await session.get(SpendingRecord, attempt.id)
    if reservation is None:
        raise SigningRejectedError("Execution reservation is unavailable")
    # A live pending transaction may mine on a later UTC day. Keep it reserved
    # across midnight until its matching receipt establishes the outcome.
    reservation.status = "COMMITTED" if attempt.execution_mode == "simulated" else "RESERVED"
    await audit.record_event(
        session,
        event_type="TX_SUBMITTED",
        correlation_id=proposal.correlation_id,
        actor="blockchain_service",
        details={
            "proposal_id": proposal.id,
            "tx_hash": attempt.tx_hash,
            "network": submitted.get("network"),
            "mode": get_settings().execution_mode,
        },
    )
    await session.commit()
    return proposal
