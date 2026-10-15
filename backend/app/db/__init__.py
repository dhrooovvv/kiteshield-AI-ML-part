"""
KiteShield Wallet — Database Session Management

Provides async SQLAlchemy session factory with SQLite WAL mode
for concurrent read support.
"""

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
    from sqlalchemy import text

    async with engine.begin() as conn:
        await conn.execute(text("PRAGMA journal_mode=WAL"))
        await conn.execute(text("PRAGMA foreign_keys=ON"))
        # Create all tables
        await conn.run_sync(Base.metadata.create_all)

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
