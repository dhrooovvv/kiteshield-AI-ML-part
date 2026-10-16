"""Persistent Merkle checkpoints over KiteShield audit events."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import (
    AuditCheckpointError,
    AuditCheckpointNotFoundError,
    AuditCheckpointRangeError,
    AuditProofEventNotFoundError,
    AuditProofInvalidError,
)
from app.models import AuditCheckpoint, AuditEvent, utc_now_str
from app.services.audit_integrity import (
    compute_merkle_root,
    generate_inclusion_proof,
    verify_inclusion_proof,
)

_EVENT_ORDER = (AuditEvent.created_at.asc(), AuditEvent.id.asc())


class AuditCheckpointService:
    """Creates and retrieves checkpoint metadata in the existing database."""

    async def create_checkpoint(
        self,
        session: AsyncSession,
        *,
        first_event_id: str | None = None,
        last_event_id: str | None = None,
    ) -> AuditCheckpoint:
        """Persist a checkpoint over an inclusive, deterministically ordered range."""
        try:
            result = await session.execute(select(AuditEvent).order_by(*_EVENT_ORDER))
            events = list(result.scalars().all())
        except SQLAlchemyError as exc:
            raise AuditCheckpointError(
                "Audit events could not be read; checkpoint creation failed"
            ) from exc

        selected = self._select_range(events, first_event_id, last_event_id)
        checkpoint = AuditCheckpoint(
            id=str(uuid.uuid4()),
            merkle_root=compute_merkle_root([event.event_hash for event in selected]),
            first_event_id=selected[0].id if selected else None,
            last_event_id=selected[-1].id if selected else None,
            event_count=len(selected),
            created_at=utc_now_str(),
        )
        try:
            session.add(checkpoint)
            await session.flush()
        except SQLAlchemyError as exc:
            raise AuditCheckpointError(
                "Audit checkpoint could not be persisted"
            ) from exc
        return checkpoint

    async def get_checkpoint(
        self, session: AsyncSession, checkpoint_id: str
    ) -> AuditCheckpoint:
        try:
            checkpoint = await session.scalar(
                select(AuditCheckpoint).where(AuditCheckpoint.id == checkpoint_id)
            )
        except SQLAlchemyError as exc:
            raise AuditCheckpointError(
                "Audit checkpoint could not be read"
            ) from exc
        if checkpoint is None:
            raise AuditCheckpointNotFoundError("Audit checkpoint was not found")
        return checkpoint

    async def generate_proof(
        self,
        session: AsyncSession,
        *,
        checkpoint_id: str,
        event_id: str,
    ) -> dict[str, object]:
        """Generate a proof only for an event inside the persisted range."""
        checkpoint = await self.get_checkpoint(session, checkpoint_id)
        events = await self._load_events(session)
        selected = self._events_for_checkpoint(checkpoint, events)
        if not selected:
            raise AuditCheckpointRangeError("Empty checkpoints contain no proofable events")

        positions = {event.id: index for index, event in enumerate(selected)}
        index = positions.get(event_id)
        if index is None:
            raise AuditProofEventNotFoundError(
                "Audit event is not included in this checkpoint"
            )
        leaf_hashes = [event.event_hash for event in selected]
        return {
            "checkpoint_id": checkpoint.id,
            "event_id": event_id,
            "index": index,
            "leaf_hash": selected[index].event_hash,
            "proof": generate_inclusion_proof(leaf_hashes, index),
            "total_leaves": checkpoint.event_count,
            "merkle_root": checkpoint.merkle_root,
        }

    async def verify_proof(
        self,
        session: AsyncSession,
        *,
        checkpoint_id: str,
        event_id: str,
        index: int,
        leaf_hash: str,
        proof: list[dict[str, str]],
    ) -> dict[str, object]:
        """Verify proof material against current persisted checkpoint data."""
        checkpoint = await self.get_checkpoint(session, checkpoint_id)
        events = await self._load_events(session)
        selected = self._events_for_checkpoint(checkpoint, events)
        positions = {event.id: position for position, event in enumerate(selected)}
        expected_index = positions.get(event_id)
        if expected_index is None:
            raise AuditProofEventNotFoundError(
                "Audit event is not included in this checkpoint"
            )
        if index != expected_index or leaf_hash != selected[index].event_hash:
            raise AuditProofInvalidError("Proof event, index, or leaf hash does not match")
        if not verify_inclusion_proof(
            leaf_hash,
            index,
            proof,
            checkpoint.merkle_root,
            checkpoint.event_count,
        ):
            raise AuditProofInvalidError("Inclusion proof does not match checkpoint root")
        return {
            "checkpoint_id": checkpoint.id,
            "event_id": event_id,
            "index": index,
            "leaf_hash": leaf_hash,
            "proof": proof,
            "total_leaves": checkpoint.event_count,
            "merkle_root": checkpoint.merkle_root,
            "valid": True,
        }

    async def _load_events(self, session: AsyncSession) -> list[AuditEvent]:
        try:
            result = await session.execute(select(AuditEvent).order_by(*_EVENT_ORDER))
            return list(result.scalars().all())
        except SQLAlchemyError as exc:
            raise AuditCheckpointError("Audit events could not be read") from exc

    @staticmethod
    def _events_for_checkpoint(
        checkpoint: AuditCheckpoint, events: list[AuditEvent]
    ) -> list[AuditEvent]:
        if checkpoint.event_count == 0:
            if checkpoint.first_event_id is not None or checkpoint.last_event_id is not None:
                raise AuditCheckpointError("Empty checkpoint has an invalid event range")
            if compute_merkle_root([]) != checkpoint.merkle_root:
                raise AuditCheckpointError("Empty checkpoint root does not match its range")
            return []
        positions = {event.id: index for index, event in enumerate(events)}
        start = positions.get(checkpoint.first_event_id)
        end = positions.get(checkpoint.last_event_id)
        if start is None or end is None or start > end:
            raise AuditCheckpointError("Checkpoint event range is no longer available")
        selected = events[start : end + 1]
        if len(selected) != checkpoint.event_count:
            raise AuditCheckpointError("Checkpoint event count no longer matches")
        if compute_merkle_root([event.event_hash for event in selected]) != checkpoint.merkle_root:
            raise AuditCheckpointError("Checkpoint root no longer matches its event range")
        return selected

    @staticmethod
    def _select_range(
        events: list[AuditEvent],
        first_event_id: str | None,
        last_event_id: str | None,
    ) -> list[AuditEvent]:
        if first_event_id is None and last_event_id is None:
            return events

        positions = {event.id: index for index, event in enumerate(events)}
        start = positions.get(first_event_id) if first_event_id is not None else 0
        end = positions.get(last_event_id) if last_event_id is not None else len(events) - 1
        if (first_event_id is not None and start is None) or (
            last_event_id is not None and end is None
        ):
            raise AuditCheckpointRangeError("Checkpoint event range contains an unknown event")
        if start > end:
            return []
        return events[start : end + 1]
