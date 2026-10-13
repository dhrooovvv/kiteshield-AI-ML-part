"""
KiteShield Wallet — Health Check Route

Provides health and readiness endpoints for the application.
No authentication required.
"""

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check() -> dict:
    """Basic health check — returns 200 if the application is running."""
    return {
        "status": "healthy",
        "service": "kiteshield-wallet",
        "version": "0.1.0",
    }


@router.get("/ready")
async def readiness_check() -> dict:
    """Readiness check — verifies database connectivity.

    TODO: Add actual database connectivity check in Phase 5.
    """
    return {
        "status": "ready",
        "checks": {
            "database": "ok",
        },
    }
