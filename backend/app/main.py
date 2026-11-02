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

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager, suppress

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
from app.api.routes.assistant import router as assistant_router
from app.api.routes.economics import router as economics_router
from app.api.routes.funding import router as funding_router
from app.api.routes.invoices import router as invoices_router
from app.api.routes.local_voice import router as local_voice_router
from app.api.routes.vault import router as vault_router
from app.api.routes.mandate_draft import router as mandate_draft_router
from app.api.routes.portfolio import router as portfolio_router
from app.api.routes.treasury import router as treasury_router
from app.core.config import get_settings
from app.core.live_rpc import verify_live_rpc
from app.core.logging import correlation_id_var, get_logger, setup_logging
from app.core.security import generate_correlation_id
from app.db import init_db

logger = get_logger("main")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator:
    """Application startup and shutdown lifecycle."""
    # Startup
    settings = get_settings()
    app.state.verified_rpc = None
    setup_logging(settings.app_log_level)
    # Validate live connectivity before DB initialization or accepting any requests.
    app.state.verified_rpc = await verify_live_rpc(settings)
    logger.info(
        "Starting KiteShield Wallet backend (env=%s, chain_id=%s)",
        settings.app_env,
        settings.chain_id,
    )

    # Initialize database
    await init_db()
    logger.info("Database initialized")

    autonomy_context = None
    autonomy_app = getattr(app.state, "autonomy_app", None)
    if autonomy_app is not None:
        autonomy_context = autonomy_app.router.lifespan_context(autonomy_app)
        await autonomy_context.__aenter__()

    monitor_task = None
    invoice_task = None
    invoice_agent_task = None
    if settings.invoice_intake_enabled:
        from app.db import get_session_factory
        from app.services.invoice_watcher import monitor as invoice_monitor

        invoice_task = asyncio.create_task(
            invoice_monitor(get_session_factory()), name="invoice-monitor"
        )
        from app.services.invoice_agent import monitor as command_monitor

        invoice_agent_task = asyncio.create_task(
            command_monitor(get_session_factory()), name="invoice-command-monitor"
        )
    if settings.treasury_monitor_enabled:
        from app.db import get_session_factory
        from app.services.treasury import monitor

        monitor_task = asyncio.create_task(monitor(get_session_factory()), name="treasury-monitor")

    try:
        yield
    finally:
        if invoice_agent_task:
            invoice_agent_task.cancel()
            with suppress(asyncio.CancelledError):
                await invoice_agent_task
        if invoice_task:
            invoice_task.cancel()
            with suppress(asyncio.CancelledError):
                await invoice_task
        if monitor_task:
            monitor_task.cancel()
            with suppress(asyncio.CancelledError):
                await monitor_task
        if autonomy_context is not None:
            await autonomy_context.__aexit__(None, None, None)
        app.state.verified_rpc = None
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
    app.include_router(economics_router, prefix="/api/v1")
    app.include_router(portfolio_router, prefix="/api/v1")
    app.include_router(funding_router, prefix="/api/v1")
    app.include_router(assistant_router, prefix="/api/v1")
    app.include_router(treasury_router, prefix="/api/v1")
    app.include_router(mandate_draft_router, prefix="/api/v1")
    app.include_router(invoices_router, prefix="/api/v1")
    app.include_router(local_voice_router, prefix="/api/v1")
    app.include_router(vault_router, prefix="/api/v1")

    if settings.autonomy_enabled:
        from demo_autonomy.integration import mount_autonomy

        mount_autonomy(app, settings)

    return app


# Application instance for uvicorn
app = create_app()
