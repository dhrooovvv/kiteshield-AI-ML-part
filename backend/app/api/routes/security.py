"""Administrative security controls."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import correlation_id_var
from app.core.security import verify_api_key, verify_emergency_stop_admin
from app.db import get_db_session
from app.schemas import APIResponse, EmergencyStopRequest, EmergencyStopResponse
from app.services.audit import AuditService
from app.services.emergency_stop import EmergencyStopService

router = APIRouter(prefix="/security", tags=["Security"])
emergency_stop_service = EmergencyStopService()
audit_service = AuditService()


@router.get("/identity", response_model=APIResponse)
async def credential_identity(actor: Annotated[str, Depends(verify_api_key)]) -> APIResponse:
    """Report the authenticated role, never a key or caller-supplied role claim."""
    return APIResponse(
        data={"role": actor},
        meta={"correlation_id": correlation_id_var.get()},
    )


def _response(state) -> APIResponse:
    # Prevent accidental reflection if an operator includes the credential in
    # an incident reason. The credential itself is never returned or logged.
    safe_reason = state.reason.replace(get_settings().emergency_stop_admin_api_key, "[REDACTED]")
    return APIResponse(
        data=EmergencyStopResponse(
            active=state.active,
            reason=safe_reason,
            version=state.version,
            updated_at=state.updated_at,
        ),
        meta={"correlation_id": correlation_id_var.get()},
    )


@router.get("/kill-switch", dependencies=[Depends(verify_api_key)])
async def get_kill_switch(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> APIResponse:
    """Read the authoritative execution-stop state."""
    return _response(await emergency_stop_service.read_state(session))


@router.post("/kill-switch")
async def set_kill_switch(
    request: EmergencyStopRequest,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    _: Annotated[str, Depends(verify_emergency_stop_admin)],
) -> APIResponse:
    """Activate or deactivate the execution stop with admin authorization."""
    admin_key = get_settings().emergency_stop_admin_api_key
    if admin_key in request.reason:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "INVALID_EMERGENCY_STOP_REASON",
                "message": "Incident reason must not contain administrator credentials",
            },
        )
    state = await emergency_stop_service.set_active(
        session,
        active=request.active,
        reason=request.reason,
        changed_by="emergency_stop_admin",
    )
    await audit_service.record_event(
        session=session,
        event_type=(
            "EMERGENCY_STOP_ACTIVATED"
            if state.active
            else "EMERGENCY_STOP_DEACTIVATED"
        ),
        correlation_id=correlation_id_var.get(),
        actor="emergency_stop_admin",
        details={"active": state.active, "version": state.version},
    )
    return _response(state)
