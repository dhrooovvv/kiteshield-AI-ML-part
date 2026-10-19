"""Admin-only draft extraction; read-only database context, no RPC or audit writes."""

import json
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.security import reject_credentials_in_text, require_policy_admin
from app.db import get_db_session
from app.models import Policy
from app.schemas import APIResponse
from app.schemas.mandate_draft import DraftRequest, DraftResult
from app.services.mandate_drafter import DraftContext, interpret
from app.services.treasury import sender_address

router = APIRouter(prefix="/treasury", tags=["Mandate drafting"])
logger = get_logger("mandate_draft")


@router.post("/draft", response_model=APIResponse)
async def draft_mandate(
    request: DraftRequest,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    actor: Annotated[str, Depends(require_policy_admin)],
):
    # Existing helper detects configured secrets; never forward these to the model.
    reject_credentials_in_text(request.instruction)
    logger.info("MANDATE_DRAFT_REQUESTED actor=%s", actor)
    settings = get_settings()
    policy = await session.scalar(select(Policy).where(Policy.is_active.is_(True)))
    if not policy:
        return APIResponse(
            data=DraftResult(
                status="invalid",
                validation=[
                    (
                        "An active policy with an explicit allowlist and approval threshold "
                        "is required."
                    )
                ],
            ).model_dump()
        )
    allowlist = tuple(json.loads(policy.allowed_recipients or "[]"))
    denied = {a.lower() for a in json.loads(policy.blocked_recipients or "[]")}
    context = DraftContext(
        aliases=settings.drafter_recipient_aliases,
        allowed_recipients=tuple(a for a in allowlist if a.lower() not in denied),
        sender=sender_address(),
        chain_id=settings.chain_id,
        automation_cap_wei=min(
            int(settings.auto_execute_max_eth * 10**18), int(policy.max_amount_wei)
        ),
        approval_threshold_wei=int(policy.escalation_threshold_wei)
        if policy.escalation_threshold_wei
        else None,
        policy_version=policy.version,
    )
    result = await interpret(
        request.instruction,
        context,
        enabled=settings.drafter_llm_enabled,
        endpoint=settings.drafter_llm_endpoint,
        model=settings.drafter_llm_model,
        timeout=settings.drafter_llm_timeout_seconds,
    )
    return APIResponse(data={**result.model_dump(), "policy_version": policy.version})
