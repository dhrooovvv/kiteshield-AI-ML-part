"""
KiteShield Wallet — Transactions Endpoints

Query transaction status, on-chain execution, and receipt tracking.
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.logging import correlation_id_var, get_logger
from app.core.security import verify_api_key
from app.db import get_db_session
from app.exceptions import NotFoundError
from app.models import Transaction, utc_now_str
from app.schemas import APIResponse, TransactionResponse
from app.services.blockchain import BlockchainService

logger = get_logger("routes.transactions")
router = APIRouter(prefix="/transactions", tags=["Transactions"])
blockchain_service = BlockchainService()


def _format_transaction(tx: Transaction) -> TransactionResponse:
    """Map DB Transaction model to TransactionResponse schema."""
    return TransactionResponse(
        id=tx.id,
        tx_hash=tx.tx_hash,
        status=tx.status,
        block_number=tx.block_number,
        gas_used=tx.gas_used,
        error_message=tx.error_message,
        created_at=tx.created_at,
        updated_at=tx.updated_at,
    )


@router.get("/{tx_id}", response_model=APIResponse)
async def get_transaction(
    tx_id: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    _: Annotated[str, Depends(verify_api_key)],
) -> APIResponse:
    """Retrieve transaction details and update status from blockchain receipt if available."""
    cid = correlation_id_var.get()
    stmt = (
        select(Transaction)
        .options(selectinload(Transaction.proposal))
        .where((Transaction.id == tx_id) | (Transaction.tx_hash == tx_id))
    )
    result = await session.execute(stmt)
    tx = result.scalar_one_or_none()

    if not tx:
        raise NotFoundError(f"Transaction {tx_id} not found")

    # If status is SUBMITTED and tx_hash is present, try checking receipt
    if tx.status == "SUBMITTED" and tx.tx_hash:
        receipt = await blockchain_service.get_transaction_receipt(tx.tx_hash)
        if receipt:
            if receipt.get("status") == 1:
                tx.status = "CONFIRMED"
                tx.block_number = receipt.get("blockNumber")
                tx.gas_used = receipt.get("gasUsed")
                tx.updated_at = utc_now_str()
                if tx.proposal:
                    tx.proposal.status = "CONFIRMED"
                    tx.proposal.updated_at = utc_now_str()
            elif receipt.get("status") == 0:
                tx.status = "FAILED"
                tx.error_message = "On-chain execution reverted"
                tx.updated_at = utc_now_str()
                if tx.proposal:
                    tx.proposal.status = "TX_FAILED"
                    tx.proposal.updated_at = utc_now_str()
            await session.flush()

    return APIResponse(data=_format_transaction(tx), meta={"correlation_id": cid})


@router.get("", response_model=APIResponse)
async def list_transactions(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    _: Annotated[str, Depends(verify_api_key)],
    limit: int = 20,
) -> APIResponse:
    """List recent blockchain transactions."""
    cid = correlation_id_var.get()
    stmt = select(Transaction).order_by(desc(Transaction.created_at)).limit(limit)
    result = await session.execute(stmt)
    txs = result.scalars().all()

    return APIResponse(
        data=[_format_transaction(tx) for tx in txs],
        meta={"correlation_id": cid, "total": len(txs)},
    )
