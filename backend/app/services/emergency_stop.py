"""Persistent, fail-closed emergency execution stop."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import EmergencyStopActiveError, EmergencyStopUnavailableError
from app.models import ExecutionControl, utc_now_str

_GLOBAL_CONTROL_ID = "global"


@dataclass(frozen=True)
class EmergencyStopState:
    active: bool
    reason: str
    changed_by: str
    version: int
    updated_at: str


class EmergencyStopService:
    """Reads and changes the single authoritative execution-control row."""

    async def read_state(self, session: AsyncSession) -> EmergencyStopState:
        try:
            state = await session.scalar(
                select(ExecutionControl).where(ExecutionControl.id == _GLOBAL_CONTROL_ID)
            )
        except SQLAlchemyError as exc:
            raise EmergencyStopUnavailableError(
                "Emergency-stop state could not be read; execution is halted"
            ) from exc

        if state is None or not isinstance(state.active, bool):
            raise EmergencyStopUnavailableError(
                "Emergency-stop state is unavailable; execution is halted"
            )
        return EmergencyStopState(
            active=state.active,
            reason=state.reason,
            changed_by=state.changed_by,
            version=state.version,
            updated_at=state.updated_at,
        )

    async def require_running(self, session: AsyncSession) -> EmergencyStopState:
        state = await self.read_state(session)
        if state.active:
            raise EmergencyStopActiveError(
                "Emergency stop is active; execution is temporarily halted"
            )
        return state

    async def set_active(
        self,
        session: AsyncSession,
        *,
        active: bool,
        reason: str,
        changed_by: str,
    ) -> EmergencyStopState:
        try:
            state = await session.scalar(
                select(ExecutionControl)
                .where(ExecutionControl.id == _GLOBAL_CONTROL_ID)
                .with_for_update()
            )
            if state is None:
                state = ExecutionControl(
                    id=_GLOBAL_CONTROL_ID,
                    active=active,
                    reason=reason,
                    changed_by=changed_by,
                    version=1,
                    updated_at=utc_now_str(),
                )
                session.add(state)
            else:
                state.active = active
                state.reason = reason
                state.changed_by = changed_by
                state.version += 1
                state.updated_at = utc_now_str()
            await session.flush()
            return await self.read_state(session)
        except SQLAlchemyError as exc:
            raise EmergencyStopUnavailableError(
                "Emergency-stop state could not be changed"
            ) from exc
