"""
KiteShield Wallet — FastAPI Application Factory

Creates and configures the FastAPI application with:
- CORS middleware
- Correlation ID middleware
- Error handlers
- Route registration
- Database initialization
- Structured logging

This is the single entry point for the backend application.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from app.api.error_handlers import register_error_handlers
from app.api.routes import (
    approvals_router,
    audit_router,
    health_router,
    policies_router,
    proposals_router,
    security_router,
    transactions_router,
)
from app.core.config import get_settings
from app.core.logging import correlation_id_var, get_logger, setup_logging
from app.core.security import generate_correlation_id
from app.db import init_db

logger = get_logger("main")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator:
    """Application startup and shutdown lifecycle."""
    # Startup
    settings = get_settings()
    setup_logging(settings.app_log_level)
    logger.info(
        "Starting KiteShield Wallet backend (env=%s, chain_id=%s)",
        settings.app_env,
        settings.chain_id,
    )

    # Initialize database
    await init_db()
    logger.info("Database initialized")

    yield

    # Shutdown
    logger.info("Shutting down KiteShield Wallet backend")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    # Validate settings at startup (fail fast)
    settings = get_settings()

    app = FastAPI(
        title="KiteShield Wallet API",
        description=(
            "Constrained AI Agent Authorization for Blockchain Transactions. "
            "Give the agent hands, not the keys."
        ),
        version="0.1.0",
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )

    # ---- CORS ----
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["X-Correlation-ID"],
    )

    # ---- Correlation ID Middleware ----
    @app.middleware("http")
    async def correlation_id_middleware(request: Request, call_next) -> Response:
        """Inject correlation ID into every request/response."""
        cid = request.headers.get("X-Correlation-ID", generate_correlation_id())
        correlation_id_var.set(cid)
        response = await call_next(request)
        response.headers["X-Correlation-ID"] = cid
        return response

    # ---- Error Handlers ----
    register_error_handlers(app)

    # ---- Routes ----
    app.include_router(health_router, prefix="/api/v1")
    app.include_router(policies_router, prefix="/api/v1")
    app.include_router(proposals_router, prefix="/api/v1")
    app.include_router(approvals_router, prefix="/api/v1")
    app.include_router(transactions_router, prefix="/api/v1")
    app.include_router(audit_router, prefix="/api/v1")
    app.include_router(security_router, prefix="/api/v1")

    return app


# Application instance for uvicorn
app = create_app()
