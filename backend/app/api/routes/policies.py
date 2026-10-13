"""
KiteShield Wallet — Policy Management Endpoints

Handles policy creation, activation, and versioning.
Policies govern which transactions can be executed, escalated, or blocked.

Security:
- All mutations increment the policy version (policies are immutable snapshots).
- Stale capability tokens bound to prior deactivated policy versions will fail.
- Audit events recorded for all policy configuration changes.
"""

import json
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import correlation_id_var, get_logger
from app.core.security import verify_api_key
from app.db import get_db_session
from app.exceptions import NotFoundError
from app.models import Policy
from app.schemas import (
    APIResponse,
    PolicyCreateRequest,
    PolicyResponse,
    PolicyUpdateRequest,
)
from app.services.audit import AuditService

logger = get_logger("routes.policies")
router = APIRouter(prefix="/policies", tags=["Policies"])
audit_service = AuditService()


def _model_to_response(policy: Policy) -> PolicyResponse:
    """Map DB Policy model to PolicyResponse schema."""
    allowed = json.loads(policy.allowed_recipients) if policy.allowed_recipients else None
    blocked = json.loads(policy.blocked_recipients) if policy.blocked_recipients else None
    return PolicyResponse(
        id=policy.id,
        version=policy.version,
        max_amount_wei=policy.max_amount_wei,
        daily_limit_wei=policy.daily_limit_wei,
        allowed_recipients=allowed,
        blocked_recipients=blocked,
        escalation_threshold_wei=policy.escalation_threshold_wei,
        is_active=policy.is_active,
        created_at=policy.created_at,
    )


@router.post("", response_model=APIResponse)
async def create_policy(
    request: PolicyCreateRequest,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    _: Annotated[str, Depends(verify_api_key)],
) -> APIResponse:
    """Create a new policy version and set it as active."""
    cid = correlation_id_var.get()

    # Determine next version
    latest_stmt = select(Policy).order_by(desc(Policy.version)).limit(1)
    latest_result = await session.execute(latest_stmt)
    latest_policy = latest_result.scalar_one_or_none()
    next_version = (latest_policy.version + 1) if latest_policy else 1

    # Deactivate any previous active policy
    if latest_policy and latest_policy.is_active:
        active_policies_stmt = select(Policy).where(Policy.is_active.is_(True))
        active_res = await session.execute(active_policies_stmt)
        for p in active_res.scalars().all():
            p.is_active = False

    allowed_json = json.dumps(request.allowed_recipients) if request.allowed_recipients else None
    blocked_json = json.dumps(request.blocked_recipients) if request.blocked_recipients else None

    new_policy = Policy(
        version=next_version,
        max_amount_wei=request.max_amount_wei,
        daily_limit_wei=request.daily_limit_wei,
        allowed_recipients=allowed_json,
        blocked_recipients=blocked_json,
        escalation_threshold_wei=request.escalation_threshold_wei,
        is_active=True,
    )
    session.add(new_policy)
    await session.flush()

    # Record audit event
    await audit_service.record_event(
        session=session,
        event_type="POLICY_CREATED",
        correlation_id=cid,
        actor="admin",
        details={
            "policy_id": new_policy.id,
            "version": new_policy.version,
            "max_amount_wei": new_policy.max_amount_wei,
            "escalation_threshold_wei": new_policy.escalation_threshold_wei,
        },
        policy_version=new_policy.version,
    )

    logger.info("Policy created: version=%d (id=%s)", new_policy.version, new_policy.id)
    return APIResponse(data=_model_to_response(new_policy), meta={"correlation_id": cid})


@router.get("/active", response_model=APIResponse)
async def get_active_policy(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    _: Annotated[str, Depends(verify_api_key)],
) -> APIResponse:
    """Retrieve the currently active policy configuration."""
    cid = correlation_id_var.get()
    stmt = select(Policy).where(Policy.is_active.is_(True)).order_by(desc(Policy.version)).limit(1)
    result = await session.execute(stmt)
    policy = result.scalar_one_or_none()

    if not policy:
        raise NotFoundError("No active policy found. Please create a policy first.")

    return APIResponse(data=_model_to_response(policy), meta={"correlation_id": cid})


@router.get("", response_model=APIResponse)
async def list_policies(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    _: Annotated[str, Depends(verify_api_key)],
) -> APIResponse:
    """List all historical and active policies."""
    cid = correlation_id_var.get()
    stmt = select(Policy).order_by(desc(Policy.version))
    result = await session.execute(stmt)
    policies = result.scalars().all()

    return APIResponse(
        data=[_model_to_response(p) for p in policies],
        meta={"correlation_id": cid, "total": len(policies)},
    )


@router.put("/{policy_id}", response_model=APIResponse)
async def update_policy(
    policy_id: str,
    request: PolicyUpdateRequest,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    _: Annotated[str, Depends(verify_api_key)],
) -> APIResponse:
    """Update a policy by creating a new version with the updated parameters."""
    cid = correlation_id_var.get()
    existing_stmt = select(Policy).where(Policy.id == policy_id)
    existing_res = await session.execute(existing_stmt)
    existing = existing_res.scalar_one_or_none()

    if not existing:
        raise NotFoundError(f"Policy with id {policy_id} not found")

    # Deactivate all active policies
    active_stmt = select(Policy).where(Policy.is_active.is_(True))
    active_res = await session.execute(active_stmt)
    for p in active_res.scalars().all():
        p.is_active = False

    # Get max version
    max_ver_res = await session.execute(
        select(Policy.version).order_by(desc(Policy.version)).limit(1)
    )
    next_ver = (max_ver_res.scalar_one() or 1) + 1

    existing_allowed = (
        json.loads(existing.allowed_recipients) if existing.allowed_recipients else None
    )
    existing_blocked = (
        json.loads(existing.blocked_recipients) if existing.blocked_recipients else None
    )

    new_allowed = (
        request.allowed_recipients if request.allowed_recipients is not None else existing_allowed
    )
    new_blocked = (
        request.blocked_recipients if request.blocked_recipients is not None else existing_blocked
    )

    new_policy = Policy(
        version=next_ver,
        max_amount_wei=request.max_amount_wei or existing.max_amount_wei,
        daily_limit_wei=request.daily_limit_wei
        if request.daily_limit_wei is not None
        else existing.daily_limit_wei,
        allowed_recipients=json.dumps(new_allowed) if new_allowed else None,
        blocked_recipients=json.dumps(new_blocked) if new_blocked else None,
        escalation_threshold_wei=(
            request.escalation_threshold_wei
            if request.escalation_threshold_wei is not None
            else existing.escalation_threshold_wei
        ),
        is_active=True,
    )
    session.add(new_policy)
    await session.flush()

    await audit_service.record_event(
        session=session,
        event_type="POLICY_UPDATED",
        correlation_id=cid,
        actor="admin",
        details={
            "previous_policy_id": existing.id,
            "new_policy_id": new_policy.id,
            "version": new_policy.version,
        },
        policy_version=new_policy.version,
    )

    return APIResponse(data=_model_to_response(new_policy), meta={"correlation_id": cid})
