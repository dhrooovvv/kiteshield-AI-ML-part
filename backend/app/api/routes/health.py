"""
KiteShield Wallet — Health Check Route

Provides health and readiness endpoints for the application.
No authentication required.
"""

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.proposals import screening_service
from app.core.config import get_settings
from app.db import get_db_session

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check(request: Request) -> dict:
    """Basic health check — returns 200 if the application is running."""
    verified = getattr(request.app.state, "verified_rpc", None)
    return {
        "status": "healthy",
        "service": "kiteshield-wallet",
        "local_model": get_settings().invoice_model,
        "local_voice_enabled": get_settings().local_voice_enabled,
        "version": "0.1.0",
        "autonomy_demo": (get_settings().autonomy_enabled
                          and get_settings().execution_mode == "simulated"),
        "autonomy_profile": ("existing" if getattr(request.app.state, "main_wallet_autonomy", False)
                             else "sepolia" if getattr(request.app.state, "sepolia_profile", None)
                             else "simulation" if get_settings().autonomy_enabled else None),
        "execution_mode": get_settings().execution_mode,
        "auto_execute_enabled": get_settings().auto_execute_enabled,
        "auto_execute_max_eth": str(get_settings().auto_execute_max_eth),
        "verified_chain_id": verified["chain_id"] if verified else None,
        "verified_block_number": verified["block_number"] if verified else None,
        "rpc_verified_at": verified["verified_at"] if verified else None,
    }


@router.get("/ready")
async def readiness_check(
    response: Response, session: AsyncSession = Depends(get_db_session)
) -> dict:
    """Readiness check — verifies database connectivity.

    TODO: Add actual database connectivity check in Phase 5.
    """
    try:
        await session.execute(text("SELECT 1"))
        database_ready = True
    except Exception:
        database_ready = False
    if not get_settings().learned_screening_enabled:
        if not database_ready:
            response.status_code = 503
        return {
            "status": "ready" if database_ready else "not_ready",
            "checks": {
                "database": "ok" if database_ready else "unavailable",
                "prompt_screening": {
                    "rules": "ready",
                    "required_for_agent_screening": False,
                    "learned_models": "optional-disabled",
                },
            },
        }
    prompt_screening = await screening_service.readiness()
    models_ready = all(prompt_screening[name] == "ready" for name in ("horizon", "bastion"))
    if not models_ready or not database_ready:
        response.status_code = 503
    return {
        "status": "ready" if models_ready and database_ready else "not_ready",
        "checks": {
            "database": "ok",
            "prompt_screening": prompt_screening,
        },
    }
