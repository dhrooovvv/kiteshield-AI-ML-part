"""Read-only RPC reconciliation of durable payments; never signs or broadcasts."""

import json
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import RPCError
from app.models import (
    AutonomousIntent,
    ExecutionAttempt,
    Proposal,
    SpendingRecord,
    Transaction,
    utc_now_str,
)
from app.schemas import TransactionResponse
from app.services.audit import AuditService
from app.services.blockchain import BlockchainService
from app.services.execution_lock import lock_execution


def transaction_response(tx: Transaction) -> TransactionResponse:
    return TransactionResponse(
        id=tx.id,
        tx_hash=tx.tx_hash,
        status=tx.status,
        execution_mode=tx.execution_mode,
        execution_outcome=tx.execution_outcome,
        receipt=json.loads(tx.receipt_json) if tx.receipt_json else None,
        explorer_url=(
            f"https://sepolia.etherscan.io/tx/{tx.tx_hash}"
            if tx.execution_mode == "sepolia" and tx.tx_hash
            else None
        ),
        block_number=tx.block_number,
        gas_used=tx.gas_used,
        error_message=tx.error_message,
        created_at=tx.created_at,
        updated_at=tx.updated_at,
    )


async def reconcile_receipt(
    session: AsyncSession,
    tx: Transaction,
    blockchain: BlockchainService,
) -> bool:
    """Persist one matching mined receipt, even if approval/policy since expired.

    Confirmation observes an existing side effect; it cannot grant new authority.
    One matching receipt is one confirmation, not a promise of chain finality.
    Unknown outcomes retain their budget reservation indefinitely.
    """
    if tx.execution_mode != "sepolia" or not tx.tx_hash or tx.status in ("CONFIRMED", "FAILED"):
        return False
    receipt = await blockchain.get_transaction_receipt(tx.tx_hash)
    if receipt is None:
        return False
    if (
        not isinstance(receipt, dict)
        or not isinstance(receipt.get("transactionHash"), str)
        or receipt["transactionHash"].lower() != tx.tx_hash.lower()
        or type(receipt.get("status")) is not int
        or receipt["status"] not in (0, 1)
        or type(receipt.get("blockNumber")) is not int
        or receipt["blockNumber"] < 0
        or type(receipt.get("gasUsed")) is not int
        or receipt["gasUsed"] < 0
    ):
        raise RPCError("Receipt does not match the durable transaction")
    await lock_execution(session)
    await session.refresh(tx)
    if tx.status in ("CONFIRMED", "FAILED"):
        return True
    proposal = await session.get(Proposal, tx.proposal_id, populate_existing=True)
    attempt = await session.scalar(
        select(ExecutionAttempt).where(ExecutionAttempt.proposal_id == tx.proposal_id)
    )
    if proposal is None:
        raise RPCError("Receipt has no matching proposal")
    success = receipt["status"] == 1
    tx.status = "CONFIRMED" if success else "FAILED"
    tx.execution_outcome = "CONFIRMED" if success else "REVERTED"
    tx.receipt_json = json.dumps(receipt, sort_keys=True, separators=(",", ":"))
    tx.block_number, tx.gas_used = receipt["blockNumber"], receipt["gasUsed"]
    tx.error_message = None if success else "On-chain execution reverted"
    tx.updated_at = utc_now_str()
    proposal.status = "CONFIRMED" if success else "TX_FAILED"
    proposal.updated_at = tx.updated_at
    if attempt:
        attempt.status = tx.execution_outcome
        reservation = await session.get(SpendingRecord, attempt.id)
        if reservation:
            reservation.status = "COMMITTED" if success else "RELEASED"
            if success:
                reservation.period_date = datetime.now(UTC).date().isoformat()
    await AuditService().record_event(
        session,
        event_type="TX_CONFIRMED" if success else "TX_REVERTED",
        correlation_id=proposal.correlation_id,
        actor="receipt_reconciler",
        details={
            "proposal_id": proposal.id,
            "tx_hash": tx.tx_hash,
            "execution_id": attempt.id if attempt else None,
            "policy_version": attempt.policy_version if attempt else None,
            "block_number": tx.block_number,
            "gas_used": tx.gas_used,
            "execution_mode": "sepolia",
        },
    )
    await session.flush()
    intent = await session.get(AutonomousIntent, proposal.id)
    if intent and intent.started:
        await AuditService().record_event(
            session, event_type="AUTO_EXECUTION_CONFIRM" if success else "AUTO_EXECUTION_FAILURE",
            correlation_id=proposal.correlation_id, actor="autonomous_executor",
            details={"proposal_id": proposal.id, "tx_hash": tx.tx_hash},
        )
    return True
