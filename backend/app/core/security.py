"""
KiteShield Wallet — API Security Utilities

Provides API key authentication and correlation ID middleware.

Security: API key is compared using constant-time comparison
to prevent timing attacks.
"""

import secrets
import uuid
from typing import Annotated

from fastapi import HTTPException, Request, Security
from fastapi.security import APIKeyHeader

from app.core.config import get_settings
from app.core.logging import correlation_id_var
from app.exceptions import ValidationError

# API key header scheme
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def reject_credentials_in_text(text: str) -> None:
    """Do not forward configured credentials to extraction or persist them as prompts."""
    settings = get_settings()
    configured = (
        settings.api_key,
        settings.approver_api_key,
        settings.policy_admin_api_key,
        settings.demo_admin_api_key,
        settings.emergency_stop_admin_api_key,
        settings.signer_private_key,
        settings.capability_token_secret,
        settings.openai_api_key,
    )
    if any(value and value in text for value in configured):
        raise ValidationError("Remove credentials from the request; no proposal was created")


emergency_stop_admin_api_key_header = APIKeyHeader(
    name="X-Emergency-Stop-Admin-Key", auto_error=False
)


async def verify_api_key(
    api_key: Annotated[str | None, Security(api_key_header)],
) -> str:
    """Verify API key from request header.

    Uses constant-time comparison to prevent timing attacks.
    """
    if api_key is None:
        raise HTTPException(
            status_code=401,
            detail={"code": "MISSING_API_KEY", "message": "X-API-Key header is required"},
        )

    settings = get_settings()
    if settings.demo_admin_api_key and secrets.compare_digest(api_key, settings.demo_admin_api_key):
        if (
            settings.app_env != "demo"
            or settings.execution_mode != "simulated"
            or settings.database_url != "sqlite+aiosqlite:///./kiteshield-demo.db"
            or settings.signer_private_key != "b" * 64
        ):
            raise HTTPException(
                403,
                detail={
                    "code": "DEMO_ADMIN_SIMULATION_ONLY",
                    "message": (
                        "Demo administrator requires the isolated simulation profile; "
                        "never live Sepolia"
                    ),
                },
            )
        return "demo_admin"
    if not any(
        configured and secrets.compare_digest(api_key, configured)
        for configured in (
            settings.api_key,
            settings.approver_api_key,
            settings.policy_admin_api_key,
        )
    ):
        raise HTTPException(
            status_code=401,
            detail={"code": "INVALID_API_KEY", "message": "Invalid API key"},
        )

    if secrets.compare_digest(api_key, settings.api_key):
        return "proposer"
    if settings.approver_api_key and secrets.compare_digest(api_key, settings.approver_api_key):
        return "human_approver"
    return "policy_administrator"


async def require_approver(actor: Annotated[str, Security(verify_api_key)]) -> str:
    if actor not in ("human_approver", "demo_admin"):
        raise HTTPException(
            403, detail={"code": "ROLE_FORBIDDEN", "message": "Human approver credential required"}
        )
    return actor


async def require_proposer(actor: Annotated[str, Security(verify_api_key)]) -> str:
    if actor not in ("proposer", "demo_admin"):
        raise HTTPException(
            403, detail={"code": "ROLE_FORBIDDEN", "message": "Proposer credential required"}
        )
    return actor


async def require_policy_admin(actor: Annotated[str, Security(verify_api_key)]) -> str:
    if actor not in ("policy_administrator", "demo_admin"):
        raise HTTPException(
            403,
            detail={
                "code": "ROLE_FORBIDDEN",
                "message": "Policy administrator credential required",
            },
        )
    return actor


async def verify_emergency_stop_admin(
    api_key: Annotated[str | None, Security(emergency_stop_admin_api_key_header)],
) -> str:
    """Verify the dedicated emergency-stop administration credential."""
    if api_key is None:
        raise HTTPException(
            status_code=401,
            detail={
                "code": "MISSING_EMERGENCY_STOP_ADMIN_KEY",
                "message": "Emergency-stop administrator credential is required",
            },
        )

    settings = get_settings()
    if not secrets.compare_digest(api_key, settings.emergency_stop_admin_api_key):
        raise HTTPException(
            status_code=403,
            detail={
                "code": "INVALID_EMERGENCY_STOP_ADMIN_KEY",
                "message": "Invalid emergency-stop administrator credential",
            },
        )

    return "emergency_stop_admin"


def generate_correlation_id() -> str:
    """Generate a new correlation ID."""
    return str(uuid.uuid4())


async def set_correlation_id(request: Request) -> str:
    """Extract or generate correlation ID for request tracing.

    Checks X-Correlation-ID header first, generates new one if absent.
    Stores in context variable for logging access.
    """
    cid = request.headers.get("X-Correlation-ID")
    if not cid:
        cid = generate_correlation_id()

    correlation_id_var.set(cid)
    return cid
