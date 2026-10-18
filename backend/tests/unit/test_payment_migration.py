"""Additive initialization preserves historical records; no live database used."""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import db


@pytest.mark.asyncio
async def test_additive_authorization_migration_preserves_legacy_rows(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'legacy.sqlite'}")
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "CREATE TABLE execution_attempts "
                "(id TEXT PRIMARY KEY, status TEXT, sender TEXT, chain_id INTEGER)"
            )
        )
        await conn.execute(
            text(
                "INSERT INTO execution_attempts VALUES "
                "('legacy-execution', 'SIGNED', 'old-sender', 11155111)"
            )
        )
        await conn.execute(
            text(
                "CREATE TABLE policy_decisions (id TEXT PRIMARY KEY, proposal_id TEXT, "
                "decision TEXT, "
                "reason_codes TEXT, policy_version INTEGER, evaluated_at TEXT)"
            )
        )
        await conn.execute(
            text(
                "INSERT INTO policy_decisions VALUES ('historical', 'old', 'ALLOW', '[]', 1, 'old')"
            )
        )
        await conn.execute(
            text(
                "CREATE TABLE approval_requests (id TEXT PRIMARY KEY, proposal_id TEXT, "
                "action_digest TEXT, "
                "status TEXT, expires_at TEXT, approved_by TEXT, decided_at TEXT, created_at TEXT)"
            )
        )
        await conn.execute(
            text(
                "INSERT INTO approval_requests VALUES ('historical-approval', 'old', 'digest', "
                "'APPROVED', 'old', 'historical-actor', 'old', 'old')"
            )
        )
    monkeypatch.setattr(db, "get_engine", lambda: engine)
    monkeypatch.setattr(
        db, "get_session_factory", lambda: async_sessionmaker(engine, expire_on_commit=False)
    )
    await db.init_db()
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO proposals (id, correlation_id, agent_prompt, recipient, amount_wei, "
                "chain_id, asset_type, status, created_at, updated_at) VALUES "
                "('legacy-payment', 'c', 'old', '0x1111111111111111111111111111111111111111', "
                "'100', 11155111, 'NATIVE_ETH', 'SUBMITTED', '2026-10-17T00:00:00Z', 'old')"
            )
        )
        await conn.execute(
            text(
                "INSERT INTO transactions (id, proposal_id, status, created_at, updated_at) VALUES "
                "('old-tx', 'legacy-payment', 'SUBMITTED', '2026-10-17T00:00:00Z', 'old')"
            )
        )
    await db.init_db()
    await db.init_db()
    async with engine.connect() as conn:
        legacy_execution = (
            await conn.execute(text("SELECT id, status, execution_mode FROM execution_attempts"))
        ).one()
        assert tuple(legacy_execution) == ("legacy-execution", "SIGNED", None)
        row = (
            await conn.execute(text("SELECT id, decision, action_digest FROM policy_decisions"))
        ).one()
        assert tuple(row) == ("historical", "ALLOW", None)
        approval = (
            await conn.execute(
                text("SELECT id, approved_by, policy_version FROM approval_requests")
            )
        ).one()
        assert tuple(approval) == ("historical-approval", "historical-actor", None)
        spending = (
            await conn.execute(text("SELECT proposal_id, amount_wei, status FROM spending_records"))
        ).all()
        assert [tuple(row) for row in spending] == [("legacy-payment", "100", "COMMITTED")]
    from app.exceptions import TransactionSubmissionError
    from app.schemas import NormalizedAction
    from app.services.blockchain import BlockchainService

    async with async_sessionmaker(engine)() as session:
        with pytest.raises(TransactionSubmissionError, match="Legacy execution mode"):
            await BlockchainService().prepare_transaction(
                session,
                "old-sender",
                NormalizedAction(
                    proposal_id="preview",
                    correlation_id="preview",
                    recipient="0x1111111111111111111111111111111111111111",
                    amount_wei=1,
                ),
            )
    await engine.dispose()
