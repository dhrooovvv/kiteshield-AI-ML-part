"""Tests for the persistent, fail-closed emergency execution stop."""

from unittest.mock import AsyncMock

import pytest
from sqlalchemy import delete
from sqlalchemy.exc import SQLAlchemyError

from app.exceptions import EmergencyStopActiveError, EmergencyStopUnavailableError
from app.models import ExecutionControl, Policy
from app.schemas import NormalizedAction
from app.services.blockchain import BlockchainService
from app.services.capability import CapabilityService
from app.services.emergency_stop import EmergencyStopService
from app.services.signer import IsolatedSigner
from tests.authorization_support import seed_authorization


@pytest.fixture
def action():
    return NormalizedAction(
        proposal_id="stop-test-proposal",
        correlation_id="stop-test-correlation",
        recipient="0x742d35Cc6634C0532925a3b844Bc9e7595f2bD1e",
        amount_wei=100,
        chain_id=11155111,
    )


@pytest.mark.asyncio
async def test_activation_deactivation_persists(test_session):
    service = EmergencyStopService()

    initial = await service.read_state(test_session)
    assert initial.active is False

    active = await service.set_active(
        test_session, active=True, reason="incident", changed_by="admin"
    )
    assert active.active is True
    assert active.version == 1

    await test_session.commit()
    persisted = await service.read_state(test_session)
    assert persisted.active is True
    assert persisted.reason == "incident"

    inactive = await service.set_active(
        test_session, active=False, reason="resolved", changed_by="admin"
    )
    assert inactive.active is False
    assert inactive.version == 2


@pytest.mark.asyncio
async def test_missing_state_fails_closed(test_session):
    await test_session.execute(delete(ExecutionControl))
    await test_session.flush()

    with pytest.raises(EmergencyStopUnavailableError):
        await EmergencyStopService().require_running(test_session)


@pytest.mark.asyncio
async def test_capability_issuance_is_blocked(test_session, action):
    service = EmergencyStopService()
    await service.set_active(
        test_session, active=True, reason="incident", changed_by="admin"
    )

    with pytest.raises(EmergencyStopActiveError):
        await CapabilityService().issue_token(test_session, action, policy_version=1)


@pytest.mark.asyncio
async def test_existing_token_cannot_bypass_stop_at_signing(test_session, action):
    test_session.add(
        Policy(
            id="stop-policy",
            version=1,
            max_amount_wei="1000",
            is_active=True,
        )
    )
    await test_session.flush()
    capability = CapabilityService()
    await seed_authorization(test_session, action)
    token, _ = await capability.issue_token(test_session, action, policy_version=1)
    await EmergencyStopService().set_active(
        test_session, active=True, reason="incident", changed_by="admin"
    )

    with pytest.raises(EmergencyStopActiveError):
        await IsolatedSigner(capability).sign_transaction(test_session, token, action)


@pytest.mark.asyncio
async def test_submission_is_blocked_before_network_access(test_session):
    await EmergencyStopService().set_active(
        test_session, active=True, reason="incident", changed_by="admin"
    )
    service = BlockchainService()

    with pytest.raises(EmergencyStopActiveError):
        await service.submit_raw_transaction("00", session=test_session)


@pytest.mark.asyncio
async def test_state_read_failure_fails_closed():
    session = AsyncMock()
    session.scalar.side_effect = SQLAlchemyError("database unavailable")

    with pytest.raises(EmergencyStopUnavailableError):
        await EmergencyStopService().require_running(session)
