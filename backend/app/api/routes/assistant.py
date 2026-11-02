"""Bounded local assistant. All payment authority stays in existing routes/services."""

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.proposals import agent_propose, evaluate_proposal, get_proposal
from app.core.config import get_settings
from app.core.security import require_proposer, verify_api_key
from app.db import get_db_session
from app.models.assistant import AssistantPaymentDraft
from app.models.invoice_agent import InvoiceAgentTask
from app.schemas import AgentPromptRequest, APIResponse
from app.services.assistant import query
from app.services.execution_lock import lock_execution
from app.services.funding import refuse

router = APIRouter(prefix="/assistant", tags=["KiteShield assistant"])
Session = Annotated[AsyncSession, Depends(get_db_session)]


class AssistantQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    prompt: str = Field(min_length=3, max_length=2000)
    selected_file_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


@router.post("/query")
async def ask(
    payload: AssistantQuery, request: Request, session: Session,
    actor: Annotated[str, Depends(verify_api_key)]
) -> APIResponse:
    settings = get_settings()
    if settings.autonomy_enabled:
        from demo_autonomy.integration import assistant_goal

        goal = await assistant_goal(request.app, payload.prompt, actor)
        if goal is not None:
            return APIResponse(data=goal)
    answer = await query(session, payload.prompt, actor, selected_file_id=payload.selected_file_id)
    settings = get_settings()
    if answer.get("kind") == "payment":
        draft = answer["data"]
        if (settings.auto_execute_enabled and settings.execution_mode == "sepolia"
                and settings.chain_id == 11155111
                and int(draft["amount_wei"]) <= int(settings.auto_execute_max_eth * 10**18)):
            verified = getattr(request.app.state, "verified_rpc", None)
            if not isinstance(verified, dict) or verified.get("chain_id") != 11155111:
                refuse("LIVE_CHAIN_UNVERIFIED", "Sepolia RPC verification is required before execution.")
            # Persist the immutable draft before calling the SAME authenticated submission
            # path used by its button. Policy, capability, signer and ownership checks remain.
            await session.commit()
            result = await submit(UUID(draft["draft_id"]), request, session, actor)
            draft["proposal_id"] = result.data.id
            draft["submitted_proposal"] = result.data.model_dump(mode="json")
            answer["title"] = "Payment status"
            answer["message"] = "Request processed through the existing policy and execution path. "
            answer["message"] += "The recorded status below determines whether it was submitted or confirmed."
    return APIResponse(data=answer)


@router.get("/invoice-tasks")
async def invoice_tasks(
    session: Session, _: Annotated[str, Depends(verify_api_key)]
) -> APIResponse:
    from app.services.invoice_agent import task_data

    rows = (
        await session.scalars(
            select(InvoiceAgentTask).order_by(InvoiceAgentTask.created_at.desc()).limit(5)
        )
    ).all()
    return APIResponse(data=[await task_data(session, row) for row in rows])


@router.get("/invoice-tasks/{task_id}")
async def invoice_task(
    task_id: UUID, session: Session, _: Annotated[str, Depends(verify_api_key)]
) -> APIResponse:
    from app.services.invoice_agent import task_data

    row = await session.get(InvoiceAgentTask, str(task_id))
    if row is None:
        refuse("NOT_FOUND", "Invoice task not found.", 404)
    return APIResponse(data=await task_data(session, row))


@router.post("/invoice-tasks/{task_id}/cancel")
async def cancel_invoice_task(
    task_id: UUID, session: Session, actor: Annotated[str, Depends(require_proposer)]
) -> APIResponse:
    from app.services.invoice_agent import cancel_task

    return APIResponse(data=await cancel_task(session, str(task_id), actor))


@router.post("/payments/{draft_id}/submit")
async def submit(
    draft_id: UUID,
    request: Request,
    session: Session,
    actor: Annotated[str, Depends(require_proposer)],
) -> APIResponse:
    await lock_execution(session)
    draft = await session.get(AssistantPaymentDraft, str(draft_id), populate_existing=True)
    if draft is None:
        refuse("NOT_FOUND", "Payment draft not found.", 404)
    if draft.actor != actor:
        refuse("ROLE_FORBIDDEN", "This role cannot submit the payment draft.", 403)
    # A replay only reads the same proposal, even after confirmation/expiry/rejection.
    # It never reevaluates, signs again or creates another payment.
    if draft.proposal_id:
        return await get_proposal(draft.proposal_id, session, actor)
    from app.services.vendor_payments import validate_binding

    await validate_binding(session, draft)
    if (
        datetime.now(UTC) - datetime.fromisoformat(draft.created_at)
    ).total_seconds() > 300 or draft.mode != get_settings().execution_mode:
        refuse("DRAFT_EXPIRED", "Payment draft expired or execution mode changed. Ask again.")
    created = await agent_propose(AgentPromptRequest(prompt=draft.prompt), session, actor)
    draft.proposal_id = created.data.id
    await session.commit()  # Link the one screened proposal BEFORE evaluation can execute it.
    return await evaluate_proposal(draft.proposal_id, request, session, actor)
