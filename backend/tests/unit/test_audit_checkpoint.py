"""Unit tests for persistent audit checkpoints."""

import hashlib
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.exceptions import (
    AuditCheckpointError,
    AuditCheckpointRangeError,
    AuditProofEventNotFoundError,
    AuditProofInvalidError,
)
from app.models import AuditEvent
from app.services.audit import AuditService
from app.services.audit_checkpoint import AuditCheckpointService
from app.services.audit_integrity import compute_merkle_root


def event_hash(number: int) -> str:
    return hashlib.sha256(f"event-{number}".encode()).hexdigest()


@pytest.mark.asyncio
async def test_checkpoint_creation_persistence_and_retrieval(test_session):
    audit = AuditService()
    events = [
        await audit.record_event(
            test_session,
            event_type=f"EVENT_{index}",
            correlation_id="checkpoint-test",
            actor="test",
            details={"index": index},
        )
        for index in range(3)
    ]
    service = AuditCheckpointService()

    checkpoint = await service.create_checkpoint(test_session)
    await test_session.commit()
    retrieved = await service.get_checkpoint(test_session, checkpoint.id)

    assert retrieved.id == checkpoint.id
    assert retrieved.event_count == 3
    assert retrieved.first_event_id == events[0].id
    assert retrieved.last_event_id == events[-1].id
    assert retrieved.merkle_root == compute_merkle_root([event.event_hash for event in events])


@pytest.mark.asyncio
async def test_checkpoint_order_is_deterministic_for_equal_timestamps(test_session):
    events = [
        AuditEvent(
            id=event_id,
            correlation_id="ordering",
            event_type="TEST",
            actor="test",
            details="{}",
            event_hash=event_hash(index),
            created_at="2026-01-01T00:00:00+00:00",
        )
        for index, event_id in enumerate(["event-b", "event-a", "event-c"])
    ]
    test_session.add_all(events)
    await test_session.flush()

    checkpoint = await AuditCheckpointService().create_checkpoint(test_session)
    ordered = sorted(events, key=lambda event: event.id)
    assert checkpoint.first_event_id == "event-a"
    assert checkpoint.last_event_id == "event-c"
    assert checkpoint.merkle_root == compute_merkle_root([event.event_hash for event in ordered])


@pytest.mark.asyncio
async def test_checkpoint_range_and_empty_range(test_session):
    audit = AuditService()
    events = [
        await audit.record_event(
            test_session,
            event_type=f"EVENT_{index}",
            correlation_id="range-test",
            actor="test",
            details={"index": index},
        )
        for index in range(3)
    ]
    service = AuditCheckpointService()

    ranged = await service.create_checkpoint(
        test_session,
        first_event_id=events[1].id,
        last_event_id=events[2].id,
    )
    assert ranged.event_count == 2
    assert ranged.first_event_id == events[1].id
    assert ranged.last_event_id == events[2].id

    empty = await service.create_checkpoint(
        test_session,
        first_event_id=events[2].id,
        last_event_id=events[1].id,
    )
    assert empty.event_count == 0
    assert empty.first_event_id is None
    assert empty.last_event_id is None
    assert empty.merkle_root == compute_merkle_root([])

    with pytest.raises(AuditCheckpointRangeError):
        await service.create_checkpoint(test_session, first_event_id="missing")


@pytest.mark.asyncio
async def test_proof_generation_and_verification_bind_event_and_checkpoint(test_session):
    audit = AuditService()
    events = [
        await audit.record_event(
            test_session,
            event_type=f"EVENT_{index}",
            correlation_id="proof-test",
            actor="test",
            details={"index": index},
        )
        for index in range(3)
    ]
    service = AuditCheckpointService()
    checkpoint = await service.create_checkpoint(test_session)

    generated = await service.generate_proof(
        test_session, checkpoint_id=checkpoint.id, event_id=events[2].id
    )
    verified = await service.verify_proof(
        test_session,
        checkpoint_id=checkpoint.id,
        event_id=events[2].id,
        index=generated["index"],
        leaf_hash=generated["leaf_hash"],
        proof=generated["proof"],
    )
    assert verified["valid"] is True

    with pytest.raises(AuditProofEventNotFoundError):
        await service.generate_proof(
            test_session, checkpoint_id=checkpoint.id, event_id="missing"
        )

    with pytest.raises(AuditProofInvalidError):
        await service.verify_proof(
            test_session,
            checkpoint_id=checkpoint.id,
            event_id=events[2].id,
            index=generated["index"],
            leaf_hash=event_hash(999),
            proof=generated["proof"],
        )

    with pytest.raises(AuditProofInvalidError):
        await service.verify_proof(
            test_session,
            checkpoint_id=checkpoint.id,
            event_id=events[2].id,
            index=0,
            leaf_hash=generated["leaf_hash"],
            proof=generated["proof"],
        )


@pytest.mark.asyncio
async def test_checkpoint_database_failure_fails_closed():
    session = AsyncMock()
    session.execute.side_effect = SQLAlchemyError("database unavailable")

    with pytest.raises(AuditCheckpointError):
        await AuditCheckpointService().create_checkpoint(session)
