"""
KiteShield Wallet — Structured Logging

Provides structured JSON logging with correlation ID support.
Automatically filters sensitive fields to prevent secret leakage.

Security invariant (SI-11): No secrets in logs.
"""

import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

# Context variable for correlation ID (thread/async-safe)
correlation_id_var: ContextVar[str] = ContextVar("correlation_id", default="no-correlation-id")


# Fields that must never appear in logs
SENSITIVE_FIELDS = frozenset(
    {
        "private_key",
        "signer_private_key",
        "secret",
        "capability_token_secret",
        "api_key",
        "openai_api_key",
        "password",
        "seed_phrase",
        "mnemonic",
        "token_secret",
        "signing_key",
        "authorization",
    }
)


def _sanitize_value(key: str, value: Any) -> Any:
    """Replace sensitive field values with a redacted marker."""
    if isinstance(key, str) and key.lower() in SENSITIVE_FIELDS:
        return "[REDACTED]"
    if isinstance(value, dict):
        return {k: _sanitize_value(k, v) for k, v in value.items()}
    return value


class StructuredFormatter(logging.Formatter):
    """JSON log formatter with correlation ID and secret filtering."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "correlation_id": correlation_id_var.get(),
        }

        # Add extra fields (sanitized)
        if hasattr(record, "extra_data"):
            extra = record.extra_data  # type: ignore[attr-defined]
            if isinstance(extra, dict):
                log_entry["data"] = {k: _sanitize_value(k, v) for k, v in extra.items()}

        # Add exception info if present
        if record.exc_info and record.exc_info[1] is not None:
            log_entry["exception"] = {
                "type": type(record.exc_info[1]).__name__,
                "message": str(record.exc_info[1]),
                # Do not include full traceback in structured logs to avoid leaking internals
            }

        return json.dumps(log_entry, default=str)


def setup_logging(level: str = "INFO") -> None:
    """Configure structured logging for the application."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(StructuredFormatter())

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Reduce noise from third-party libraries
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Get a named logger instance."""
    return logging.getLogger(f"kiteshield.{name}")


def log_with_context(logger: logging.Logger, level: int, message: str, **kwargs: Any) -> None:
    """Log a message with structured extra data (sanitized)."""
    record = logger.makeRecord(
        name=logger.name,
        level=level,
        fn="",
        lno=0,
        msg=message,
        args=(),
        exc_info=None,
    )
    record.extra_data = kwargs  # type: ignore[attr-defined]
    logger.handle(record)
