"""KiteShield Wallet — API Routes Package."""

from app.api.routes.approvals import router as approvals_router
from app.api.routes.audit import router as audit_router
from app.api.routes.health import router as health_router
from app.api.routes.policies import router as policies_router
from app.api.routes.proposals import router as proposals_router
from app.api.routes.transactions import router as transactions_router

__all__ = [
    "approvals_router",
    "audit_router",
    "health_router",
    "policies_router",
    "proposals_router",
    "transactions_router",
]
