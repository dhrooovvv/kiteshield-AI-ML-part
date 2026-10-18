"""
KiteShield Wallet — API Error Handlers

Converts domain exceptions to consistent JSON error responses.
Prevents stack traces, secrets, and internal details from leaking.
"""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError as PydanticValidationError

from app.core.logging import correlation_id_var, get_logger
from app.exceptions import KiteShieldError

logger = get_logger("error_handler")


def register_error_handlers(app: FastAPI) -> None:
    """Register global exception handlers on the FastAPI app."""

    @app.exception_handler(KiteShieldError)
    async def handle_domain_error(request: Request, exc: KiteShieldError) -> JSONResponse:
        """Handle all KiteShield domain exceptions."""
        cid = correlation_id_var.get()
        logger.warning(
            "Domain error: %s - %s (correlation_id=%s)",
            exc.error_code,
            exc.message,
            cid,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": exc.error_code,
                    "message": exc.message,
                    "correlation_id": cid,
                    "details": exc.details,
                }
            },
        )

    @app.exception_handler(RequestValidationError)
    @app.exception_handler(PydanticValidationError)
    async def handle_validation_error(
        request: Request, exc: PydanticValidationError
    ) -> JSONResponse:
        """Handle Pydantic validation errors."""
        cid = correlation_id_var.get()
        # Sanitize validation errors — don't expose internal field names
        safe_errors = []
        for error in exc.errors():
            safe_errors.append(
                {
                    "field": ".".join(str(loc) for loc in error["loc"]),
                    "message": error["msg"],
                    "type": error["type"],
                }
            )

        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "Request validation failed",
                    "correlation_id": cid,
                    "details": {"errors": safe_errors},
                }
            },
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        """Handle unexpected errors.

        Never returns stack traces or internal details to the client.
        Logs the full error server-side for debugging.
        """
        cid = correlation_id_var.get()
        logger.error(
            "Unexpected error (correlation_id=%s, type=%s)",
            cid,
            type(exc).__name__,
        )
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": "An unexpected error occurred. Please try again.",
                    "correlation_id": cid,
                    "details": {},
                }
            },
        )
