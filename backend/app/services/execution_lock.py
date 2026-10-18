"""Database-wide write serialization for the supported SQLite deployment.

Acquire before reading authorization state; held until commit/rollback.
Unlike process locks this also serializes workers sharing the same database.
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import SigningRejectedError


async def lock_execution(session: AsyncSession) -> None:
    if session.get_bind().dialect.name != "sqlite":
        raise SigningRejectedError("Execution locking is only verified for SQLite")
    await session.execute(
        text("INSERT INTO execution_mutex (id) VALUES ('global') ON CONFLICT(id) DO NOTHING")
    )
    await session.execute(text("UPDATE execution_mutex SET id = id WHERE id = 'global'"))
