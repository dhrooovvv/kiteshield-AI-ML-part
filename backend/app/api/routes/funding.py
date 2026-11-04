"""Authenticated incoming test ETH. No outgoing payment/signing interface."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import require_proposer, verify_api_key
from app.db import get_db_session
from app.models.funding import FundingRequest
from app.schemas import APIResponse
from app.services import funding

router = APIRouter(prefix="/funding", tags=["Testnet funding"])
Session = Annotated[AsyncSession, Depends(get_db_session)]
Proposer = Annotated[str, Depends(require_proposer)]


class FundingPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    prompt: str = Field(min_length=5, max_length=500)
    address: str | None = Field(default=None, pattern=r"^0x[0-9a-fA-F]{40}$")


@router.get("")
async def status(session: Session, _: Annotated[str, Depends(verify_api_key)]) -> APIResponse:
    rows = (
        await session.scalars(
            select(FundingRequest).order_by(FundingRequest.created_at.desc()).limit(10)
        )
    ).all()
    return APIResponse(
        data={
            "wallets": funding.wallets(),
            "mode": get_settings().faucet_mode,
            "unavailable_reason": funding.available(),
            "requests": [funding.public(row) for row in rows],
        }
    )


@router.post("/plan")
async def plan(payload: FundingPlan, session: Session, actor: Proposer) -> APIResponse:
    return APIResponse(data=await funding.prepare(session, payload.prompt, payload.address, actor))


@router.post("/{request_id}/request")
async def request(request_id: UUID, session: Session, actor: Proposer) -> APIResponse:
    return APIResponse(data=await funding.submit(session, str(request_id), actor))


@router.get("/{request_id}")
async def receipt(
    request_id: UUID, session: Session, _: Annotated[str, Depends(verify_api_key)]
) -> APIResponse:
    return APIResponse(data=await funding.reconcile(session, str(request_id)))
