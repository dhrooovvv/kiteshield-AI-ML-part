"""Opening an old SQLite DB creates only additive treasury tables."""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import db
from app.models import Base


@pytest.mark.asyncio
async def test_additive_treasury_schema_preserves_old_database(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'treasury-old.sqlite'}")
    async with engine.begin() as conn:
        # Simulate current release before treasury existed.
        for table in Base.metadata.sorted_tables:
            if not table.name.startswith("treasury_"):
                await conn.run_sync(lambda c, t=table: t.create(c, checkfirst=True))
        await conn.execute(
            text(
                "INSERT INTO policies (id, version, max_amount_wei, is_active, created_at) "
                "VALUES ('old', 1, '100', 1, 'old')"
            )
        )
    monkeypatch.setattr(db, "_engine", engine)
    monkeypatch.setattr(db, "_session_factory", async_sessionmaker(engine, expire_on_commit=False))
    await db.init_db()
    await db.init_db()
    async with engine.connect() as conn:
        assert (
            await conn.execute(text("SELECT id, version, max_amount_wei FROM policies"))
        ).one() == ("old", 1, "100")
        assert (await conn.execute(text("SELECT count(*) FROM treasury_mandates"))).scalar() == 0
        assert (await conn.execute(text("SELECT count(*) FROM treasury_actions"))).scalar() == 0
    await engine.dispose()
