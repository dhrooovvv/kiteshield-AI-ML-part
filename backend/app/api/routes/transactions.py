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
from app.models import Transaction
from app.schemas import APIResponse, TransactionResponse
from app.services.blockchain import BlockchainService
from app.services.receipt import reconcile_receipt, transaction_response

logger = get_logger("routes.transactions")
router = APIRouter(prefix="/transactions", tags=["Transactions"])
blockchain_service = BlockchainService()


def _format_transaction(tx: Transaction) -> TransactionResponse:
    """Map DB Transaction model to TransactionResponse schema."""
    return transaction_response(tx)


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

    await reconcile_receipt(session, tx, blockchain_service)

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
