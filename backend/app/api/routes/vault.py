"""Typed vault controls. Administrator intent is never inferred from a prompt."""

import time
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import correlation_id_var
from app.core.security import require_policy_admin, require_proposer, verify_api_key
from app.db import get_db_session
from app.exceptions import NotFoundError, SigningRejectedError
from app.models import Policy, Proposal, VaultOperation, VaultRegistry, generate_uuid
from app.schemas import APIResponse
from app.schemas.vault import VaultExecutionLimits, VaultKind, VaultPayload
from app.services.audit import AuditService
from app.services.blockchain import BlockchainService
from app.services.capability import CapabilityService
from app.services.execution_lock import lock_execution
from app.services.signer import IsolatedSigner
from app.services.vault import (
    artifact,
    canonical,
    chain_state,
    digest,
    owner_address,
    runtime_hash,
    validate_operation,
)
from app.services.vault_execution import (
    execute_operation,
    execute_vault_payment,
    prepare_operation,
    reconcile_operation,
)

router = APIRouter(prefix="/vault", tags=["Guarded vault"])
Session = Annotated[AsyncSession, Depends(get_db_session)]
Admin = Annotated[str, Depends(require_policy_admin)]
Proposer = Annotated[str, Depends(require_proposer)]
Reader = Annotated[str, Depends(verify_api_key)]
blockchain = BlockchainService()
capability = CapabilityService()
signer = IsolatedSigner(capability)
audit = AuditService()


class OwnerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    request_key: str = Field(min_length=16, max_length=100, pattern=r"^[a-zA-Z0-9_-]+$")
    kind: VaultKind = Field(strict=False)
    amount_wei: int = Field(default=0, ge=0, le=10**15)


class PayoutRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    request_key: str = Field(min_length=16, max_length=100, pattern=r"^[a-zA-Z0-9_-]+$")
    amount_wei: int = Field(gt=0, le=10**15)
    expected_epoch: int = Field(ge=1)
    expected_revision: int = Field(ge=1)


class TightenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    request_key: str = Field(min_length=16, max_length=100, pattern=r"^[a-zA-Z0-9_-]+$")
    remaining_wei: int = Field(ge=0, le=10**15)
    per_payment_wei: int = Field(ge=0, le=10**15)
    expires: int = Field(ge=0)


def public(op):
    return dict(
        id=op.id,
        request_key=op.request_key,
        kind=op.kind,
        proposal_id=op.proposal_id,
        payload=VaultPayload.model_validate_json(op.payload).model_dump(mode="json"),
        payload_digest=op.authority_digest,
        status=op.status,
        sender=op.sender,
        nonce=op.nonce,
        tx_hash=op.tx_hash,
        receipt=__import__("json").loads(op.receipt) if op.receipt else None,
        envelope=__import__("json").loads(op.envelope) if op.envelope else None,
        envelope_digest=digest(op.envelope) if op.envelope else None,
        created_at=op.created_at,
    )


async def current_policy(session):
    policy = await session.scalar(select(Policy).where(Policy.is_active.is_(True)))
    if not policy:
        raise SigningRejectedError("An active policy is required")
    return policy


async def saved(session, request_key, kind, actor, amount=None):
    op = await session.scalar(
        select(VaultOperation).where(VaultOperation.request_key == request_key)
    )
    if op:
        payload = VaultPayload.model_validate_json(op.payload)
        if (
            op.kind != kind.value
            or op.authorized_by != actor
            or (amount is not None and payload.amount_wei != amount)
        ):
            raise SigningRejectedError("Idempotency key conflicts with its immutable vault intent")
    return op


async def create_operation(session, payload, request_key, actor, proposal_id=None):
    policy = await current_policy(session)
    op = VaultOperation(
        id=generate_uuid(),
        request_key=request_key,
        proposal_id=proposal_id,
        kind=payload.kind.value,
        payload=canonical(payload.model_dump(mode="json")),
        authority_digest=payload.digest(),
        authorized_by=actor,
        policy_version=policy.version,
        sender=(payload.agent if payload.agent_operation else payload.owner).lower(),
        execution_mode="sepolia",
        status="DRAFT",
    )
    session.add(op)
    await session.flush()
    await audit.record_event(
        session,
        event_type="VAULT_INTENT_CREATED",
        correlation_id=op.id,
        actor=actor,
        details={
            "kind": op.kind,
            "operation_id": op.id,
            "payload_digest": op.authority_digest,
            "proposal_id": proposal_id,
        },
    )
    return op


def payload_base(registry):
    settings = get_settings()
    return dict(
        owner=registry.owner,
        agent=registry.agent,
        recipient=settings.autonomy_recipient,
        vault=registry.address,
        epoch=registry.epoch,
        artifact_hash=settings.vault_artifact_sha256,
    )


@router.get("/status")
async def status(session: Session, _: Reader):
    settings = get_settings()
    if not settings.vault_enabled:
        return APIResponse(data={"enabled": False, "payments_enabled": False})
    artifact()
    registry = await session.get(VaultRegistry, "global")
    result = dict(
        enabled=True,
        payments_enabled=settings.autonomy_vault_payments_enabled,
        deployed=bool(registry and registry.address),
        configured=False,
        owner=owner_address(),
        agent=settings.vault_agent_address,
        recipient=settings.autonomy_recipient,
    )
    if registry:
        result.update(
            address=registry.address,
            epoch=registry.epoch,
            revision=registry.revision,
            configured=registry.configured,
            runtime_hash=registry.runtime_hash,
        )
        if registry.address:
            chain = await chain_state(blockchain, registry)
            for key in ("remaining", "perPayment", "balance", "agent_balance"):
                chain[key] = str(chain[key])
            result["chain"] = chain
    rows = (
        await session.scalars(
            select(VaultOperation).order_by(VaultOperation.created_at.desc()).limit(20)
        )
    ).all()
    result["operations"] = [public(op) for op in rows]
    return APIResponse(data=result)


@router.post("/owner-intents")
async def owner_intent(request: OwnerRequest, session: Session, actor: Admin):
    artifact()
    if request.kind in (VaultKind.PAY, VaultKind.TIGHTEN, VaultKind.PAUSE):
        raise SigningRejectedError("This route cannot create an agent operation")
    if (
        request.kind not in (VaultKind.DEPOSIT, VaultKind.GAS_FUND, VaultKind.RECOVER)
        and request.amount_wei
    ):
        raise SigningRejectedError("Unexpected value for this owner operation")
    await lock_execution(session)
    existing = await saved(session, request.request_key, request.kind, actor, request.amount_wei)
    if existing:
        return APIResponse(data=public(existing))
    settings = get_settings()
    registry = await session.get(VaultRegistry, "global")
    if not registry:
        if request.kind != VaultKind.DEPLOY:
            raise SigningRejectedError("Deploy the vault before creating owner controls")
        registry = VaultRegistry(
            id="global",
            owner=owner_address(),
            agent=settings.vault_agent_address,
            runtime_hash=runtime_hash(owner_address()),
            epoch=0,
            revision=0,
            configured=False,
        )
        session.add(registry)
        await session.flush()
    fields = payload_base(registry)
    if request.kind == VaultKind.CONFIGURE:
        state = await chain_state(blockchain, registry)
        fields.update(
            budget_wei=settings.vault_escrow_budget_wei,
            per_payment_wei=settings.vault_escrow_budget_wei,
            expires=state["timestamp"] + settings.vault_session_ttl_seconds - 30,
        )
    payload = VaultPayload(kind=request.kind, amount_wei=request.amount_wei, **fields)
    op = await create_operation(session, payload, request.request_key, actor)
    await validate_operation(session, op, blockchain)
    return APIResponse(data=public(op))


@router.post("/payments")
async def payout(request: PayoutRequest, session: Session, actor: Proposer):
    artifact()
    if not get_settings().autonomy_vault_payments_enabled:
        raise SigningRejectedError("Vault payments are disabled")
    await lock_execution(session)
    op = await saved(session, request.request_key, VaultKind.PAY, actor, request.amount_wei)
    if op:
        return APIResponse(data=public(op))
    registry = await session.get(VaultRegistry, "global")
    if (
        not registry
        or not registry.configured
        or registry.epoch != request.expected_epoch
        or registry.revision != request.expected_revision
    ):
        raise SigningRejectedError("The task's frozen administrator vault grant changed")
    state = await chain_state(blockchain, registry)
    if state["paused"] or state["expires"] <= int(time.time()):
        raise SigningRejectedError("Vault session is paused or expired")
    recipient = get_settings().autonomy_recipient
    proposal = Proposal(
        id=generate_uuid(),
        correlation_id=correlation_id_var.get(),
        agent_prompt=f"Guarded vault payment of {request.amount_wei} wei to {recipient}",
        recipient=recipient,
        amount_wei=str(request.amount_wei),
        chain_id=11155111,
        asset_type="NATIVE_ETH",
        status="PROPOSED",
    )
    session.add(proposal)
    await session.flush()
    payload = VaultPayload(
        kind=VaultKind.PAY,
        amount_wei=request.amount_wei,
        session_nonce=state["nonce"],
        **payload_base(registry),
    )
    op = await create_operation(session, payload, request.request_key, actor, proposal.id)
    return APIResponse(data=public(op))


@router.post("/tighten")
async def tighten(request: TightenRequest, session: Session, actor: Proposer):
    artifact()
    await lock_execution(session)
    op = await saved(session, request.request_key, VaultKind.TIGHTEN, actor)
    if op:
        payload = VaultPayload.model_validate_json(op.payload)
        if (payload.budget_wei, payload.per_payment_wei, payload.expires) != (
            request.remaining_wei,
            request.per_payment_wei,
            request.expires,
        ):
            raise SigningRejectedError("Tightening key conflicts with its saved intent")
        return APIResponse(data=public(op))
    registry = await session.get(VaultRegistry, "global")
    if not registry:
        raise SigningRejectedError("Vault has not been configured")
    payload = VaultPayload(
        kind=VaultKind.TIGHTEN,
        budget_wei=request.remaining_wei,
        per_payment_wei=request.per_payment_wei,
        expires=request.expires,
        **payload_base(registry),
    )
    op = await create_operation(session, payload, request.request_key, actor)
    await validate_operation(session, op, blockchain)
    return APIResponse(data=public(op))


@router.post("/pause")
async def pause(request: OwnerRequest, session: Session, actor: Proposer):
    if request.kind != VaultKind.PAUSE or request.amount_wei:
        raise SigningRejectedError("Only a zero-value pause is allowed")
    artifact()
    await lock_execution(session)
    op = await saved(session, request.request_key, VaultKind.PAUSE, actor, 0)
    if not op:
        registry = await session.get(VaultRegistry, "global")
        if not registry or not registry.configured:
            raise SigningRejectedError("No agent session to pause")
        op = await create_operation(
            session,
            VaultPayload(kind=VaultKind.PAUSE, **payload_base(registry)),
            request.request_key,
            actor,
        )
        await validate_operation(session, op, blockchain)
    return APIResponse(data=public(op))


async def operation(session, operation_id):
    op = await session.get(VaultOperation, operation_id)
    if not op:
        raise NotFoundError("Vault operation not found")
    return op


@router.get("/operations/{operation_id}")
async def get_operation(operation_id: str, session: Session, _: Reader):
    return APIResponse(data=public(await operation(session, operation_id)))


@router.post("/operations/{operation_id}/prepare")
async def prepare(operation_id: str, session: Session, actor: Reader):
    op = await operation(session, operation_id)
    if actor != op.authorized_by:
        raise SigningRejectedError("The matching role is required")
    if op.proposal_id:
        from app.services.vault_execution import proposal_with_relations

        proposal = await proposal_with_relations(session, op.proposal_id)
        if not proposal.policy_decision:
            raise SigningRejectedError("Evaluate the payout before preparing")
        op.policy_version = proposal.policy_decision.policy_version
        op.approval_id = (
            proposal.approval_request.id
            if proposal.policy_decision.decision == "ESCALATE" and proposal.approval_request
            else None
        )
    await prepare_operation(session, op, blockchain)
    return APIResponse(data=public(op))


@router.post("/operations/{operation_id}/execute")
async def execute(
    operation_id: str, session: Session, actor: Reader, limits: VaultExecutionLimits | None = None
):
    op = await operation(session, operation_id)
    if actor != op.authorized_by:
        raise SigningRejectedError("Only the role that created this typed intent may execute it")
    if op.proposal_id:
        await execute_vault_payment(session, op, capability, signer, blockchain, audit, limits)
    else:
        if limits:
            raise SigningRejectedError("Owner controls do not accept payout limits")
        await execute_operation(session, op, capability, signer, blockchain, audit)
    return APIResponse(data=public(op))


@router.post("/operations/{operation_id}/reconcile")
async def reconcile(operation_id: str, session: Session, _: Reader):
    op = await operation(session, operation_id)
    await reconcile_operation(session, op, blockchain, audit)
    return APIResponse(data=public(op))
