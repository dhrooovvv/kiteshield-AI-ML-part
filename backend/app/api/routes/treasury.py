"""Read-only GETs; administrator-only standing-mandate write operations."""

import json
import re
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import require_policy_admin, verify_api_key
from app.db import get_db_session
from app.models import ExecutionAttempt, Proposal, TreasuryAction, TreasuryMandate
from app.schemas import APIResponse
from app.schemas.treasury import MandateInput, ModeInput
from app.services.treasury import (
    availability,
    change_mode,
    configured,
    fresh,
    history_limits,
    save_mandate,
    sender_address,
    tick,
)

router = APIRouter(prefix="/treasury", tags=["Treasury Autopilot"])
Session = Annotated[AsyncSession, Depends(get_db_session)]
Reader = Annotated[str, Depends(verify_api_key)]
Admin = Annotated[str, Depends(require_policy_admin)]


async def status_data(session):
    m = await session.get(TreasuryMandate, "global", populate_existing=True)
    result = {
        "mode": "off",
        "mandate": None,
        "observation": None,
        "plan": None,
        "execution": availability(),
        "sender": sender_address(),
        "daily_actions_used": 0,
        "cooldown_active": False,
        "observation_fresh": False,
    }
    if not m:
        return result
    c = configured(m)
    used, cooldown = await history_limits(session, c)
    snapshot = json.loads(m.observation_json) if m.observation_json else None
    result.update(
        mode=m.mode if m.enabled else "off",
        mandate={
            "id": m.id,
            "version": m.version,
            **c,
            "enabled": m.enabled,
            "created_by": m.created_by,
            "updated_by": m.updated_by,
            "updated_at": m.updated_at,
        },
        observation=snapshot,
        state=m.last_state,
        plan=json.loads(m.last_plan_json) if m.last_plan_json else None,
        daily_actions_used=used,
        cooldown_active=cooldown,
        observation_fresh=bool(snapshot and fresh(snapshot, c["freshness_seconds"])),
    )
    return result


@router.get("", response_model=APIResponse)
async def read_status(session: Session, _: Reader):
    return APIResponse(data=await status_data(session))


@router.put("/mandate", response_model=APIResponse)
async def put_mandate(request: MandateInput, session: Session, actor: Admin):
    await save_mandate(session, request, actor)
    await session.commit()
    return APIResponse(data=await status_data(session))


@router.post("/mode", response_model=APIResponse)
async def set_mode(request: ModeInput, session: Session, actor: Admin):
    await change_mode(session, request, actor)
    await session.commit()
    return APIResponse(data=await status_data(session))


@router.post("/observe", response_model=APIResponse)
async def plan_observation(session: Session, _: Admin):
    from sqlalchemy.ext.asyncio import async_sessionmaker

    # Never execute from a manual observation, even for an execute-mode mandate.
    factory = async_sessionmaker(session.bind, expire_on_commit=False)
    await session.commit()
    await tick(factory, plan_only=True)
    return APIResponse(data=await status_data(session))


@router.get("/actions", response_model=APIResponse)
async def actions(session: Session, _: Reader):
    rows = (
        await session.scalars(
            select(TreasuryAction).order_by(TreasuryAction.created_at.desc()).limit(20)
        )
    ).all()
    result = []
    for row in rows:
        attempt = (
            await session.scalar(
                select(ExecutionAttempt).where(ExecutionAttempt.proposal_id == row.proposal_id)
            )
            if row.proposal_id
            else None
        )
        proposal = await session.get(Proposal, row.proposal_id) if row.proposal_id else None
        real = bool(
            attempt
            and attempt.execution_mode == "sepolia"
            and re.fullmatch(r"0x[0-9a-fA-F]{64}", attempt.tx_hash or "")
        )
        result.append(
            {
                "id": row.id,
                "mandate_version": row.mandate_version,
                "state": row.state,
                "reason": row.reason,
                "plan": json.loads(row.plan_json),
                "observation": json.loads(row.observation_json),
                "proposal_id": row.proposal_id,
                "proposal_status": proposal.status if proposal else None,
                "execution_status": attempt.status if attempt else None,
                "simulation": attempt.execution_mode == "simulated" if attempt else False,
                "tx_hash": attempt.tx_hash if attempt else None,
                "explorer_url": f"https://sepolia.etherscan.io/tx/{attempt.tx_hash}"
                if real
                else None,
                "initiated_at": row.initiated_at,
                "created_at": row.created_at,
            }
        )
    return APIResponse(data=result)
