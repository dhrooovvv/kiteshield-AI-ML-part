"""
KiteShield Wallet — Database Session Management

Provides async SQLAlchemy session factory with SQLite WAL mode
for concurrent read support.
"""

import json

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings


def create_engine():
    """Create the async SQLAlchemy engine."""
    settings = get_settings()
    engine = create_async_engine(
        settings.database_url,
        echo=settings.app_debug,
        # SQLite-specific: enable WAL mode and foreign keys
        connect_args={"check_same_thread": False},
    )
    return engine


def create_session_factory(engine=None):
    """Create an async session factory."""
    if engine is None:
        engine = create_engine()
    return async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )


# Module-level engine and session factory (lazily initialized)
_engine = None
_session_factory = None


def get_engine():
    """Get or create the global engine."""
    global _engine
    if _engine is None:
        _engine = create_engine()
    return _engine


def get_session_factory():
    """Get or create the global session factory."""
    global _session_factory
    if _session_factory is None:
        _session_factory = create_session_factory(get_engine())
    return _session_factory


async def get_db_session():
    """FastAPI dependency: yield an async database session.

    Sessions are automatically committed on success and rolled back on error.
    """
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db():
    """Initialize database tables and enable WAL mode for SQLite."""
    from app.models import Base

    engine = get_engine()

    # Enable WAL mode and foreign keys for SQLite
    async with engine.begin() as conn:
        await conn.execute(text("PRAGMA journal_mode=WAL"))
        await conn.execute(text("PRAGMA foreign_keys=ON"))
        # Create all tables
        await conn.run_sync(Base.metadata.create_all)

        # Additive migration only. Historical decisions/approvals remain NULL
        # and must be reevaluated; never backfill invented authorization.
        for table, column, sql_type in (
            ("policy_decisions", "action_digest", "VARCHAR"),
            ("approval_requests", "policy_version", "INTEGER"),
            ("transactions", "execution_mode", "VARCHAR"),
            ("transactions", "execution_outcome", "VARCHAR"),
            ("transactions", "receipt_json", "TEXT"),
            # Unknown historical modes must remain unknown, never inferred live.
            ("execution_attempts", "execution_mode", "VARCHAR"),
        ):
            result = await conn.execute(text(f"PRAGMA table_info({table})"))
            if column not in {row[1] for row in result.fetchall()}:
                await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {sql_type}"))

        # Existing known executions must not disappear from aggregate spending.
        # Unknown signed attempts remain reserved; do not infer that they failed.
        await conn.execute(
            text(
                "INSERT INTO spending_records "
                "(id, proposal_id, amount_wei, status, period_date, created_at) "
                "SELECT 'legacy-' || p.id, p.id, p.amount_wei, "
                "CASE WHEN t.status IN ('SUBMITTED', 'CONFIRMED') THEN 'COMMITTED' "
                "ELSE 'RESERVED' END, substr(t.created_at, 1, 10), t.created_at "
                "FROM transactions t JOIN proposals p ON p.id = t.proposal_id "
                "WHERE t.status IN ('SIGNING', 'SIGNED', 'SUBMITTED', 'CONFIRMED') "
                "AND NOT EXISTS (SELECT 1 FROM spending_records s WHERE s.proposal_id = p.id)"
            )
        )

        columns = await conn.execute(text("PRAGMA table_info(audit_events)"))
        column_names = {row[1] for row in columns.fetchall()}
        if "review_dedupe_key" not in column_names:
            await conn.execute(
                text("ALTER TABLE audit_events ADD COLUMN review_dedupe_key VARCHAR(64)")
            )

        # Preserve every historical event. Only the earliest event for a
        # digest receives the new key; older duplicates remain queryable.
        rows = await conn.execute(
            text(
                "SELECT id, details FROM audit_events "
                "WHERE event_type = 'PROMPT_SCREENING_REVIEW_REQUIRED' "
                "ORDER BY created_at ASC, id ASC"
            )
        )
        seen: set[str] = set()
        for event_id, details_json in rows.fetchall():
            try:
                digest = json.loads(details_json).get("prompt_digest")
            except (TypeError, json.JSONDecodeError):
                digest = None
            if not digest or digest in seen:
                continue
            seen.add(digest)
            await conn.execute(
                text("UPDATE audit_events SET review_dedupe_key = :digest WHERE id = :event_id"),
                {"digest": digest, "event_id": event_id},
            )

        await conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_audit_review_dedupe_key "
                "ON audit_events (review_dedupe_key) "
                "WHERE review_dedupe_key IS NOT NULL"
            )
        )

    # Bootstrap only when absent; an active switch is never reset on restart.
    from sqlalchemy import select

    from app.models import ExecutionControl

    async with get_session_factory()() as session:
        state = await session.scalar(
            select(ExecutionControl).where(ExecutionControl.id == "global")
        )
        if state is None:
            session.add(
                ExecutionControl(
                    id="global",
                    active=False,
                    reason="",
                    changed_by="system",
                    version=0,
                )
            )
            await session.commit()
