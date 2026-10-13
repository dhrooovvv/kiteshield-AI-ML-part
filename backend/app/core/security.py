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

# API key header scheme
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


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
    if not secrets.compare_digest(api_key, settings.api_key):
        raise HTTPException(
            status_code=401,
            detail={"code": "INVALID_API_KEY", "message": "Invalid API key"},
        )

    return api_key


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
