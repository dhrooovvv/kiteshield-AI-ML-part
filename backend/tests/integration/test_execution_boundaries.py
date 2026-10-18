"""Required stop-state checks and durable state survive independent connections."""

from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.api.routes import proposals as routes
from app.exceptions import EmergencyStopUnavailableError
from app.models import ExecutionAttempt, Proposal, SpendingRecord
from app.schemas import NormalizedAction
from app.services.blockchain import BlockchainService
from app.services.capability import CapabilityService
from app.services.emergency_stop import EmergencyStopService
from app.services.signer import IsolatedSigner
from tests.authorization_support import seed_authorization
from tests.integration.test_payment_security import ADDRESS, PROPOSER, policy, proposed
from tests.integration.test_payment_security import file_client as file_client


@pytest.mark.asyncio
@pytest.mark.parametrize("boundary", ["authorization", "signing", "submission"])
async def test_state_read_failure_blocks_each_boundary(test_session, monkeypatch, boundary):
    action = NormalizedAction(
        proposal_id="stop-boundary", correlation_id="s", recipient=ADDRESS, amount_wei=100
    )
    await seed_authorization(test_session, action)
    capability = CapabilityService()
    token, _ = await capability.issue_token(test_session, action, 1)
    monkeypatch.setattr(
        EmergencyStopService,
        "read_state",
        AsyncMock(side_effect=EmergencyStopUnavailableError("State unavailable")),
    )
    with pytest.raises(EmergencyStopUnavailableError):
        if boundary == "authorization":
            await capability.issue_token(test_session, action, 1)
        elif boundary == "signing":
            await IsolatedSigner(capability).sign_transaction(test_session, token, action)
        else:
            await BlockchainService().submit_raw_transaction("00", session=test_session)


@pytest.mark.asyncio
async def test_stop_after_durable_signing_prevents_submission(file_client, monkeypatch):
    client, factory = file_client
    await policy(client)
    item = await proposed(client, "10000000000000000")
    actual = routes.blockchain_service.submit_raw_transaction

    async def stop_before_send(payload, *, session):
        await EmergencyStopService().set_active(
            session, active=True, reason="isolated test", changed_by="admin"
        )
        await actual(payload, session=session)

    monkeypatch.setattr(routes.blockchain_service, "submit_raw_transaction", stop_before_send)
    response = await client.post(f"/api/v1/proposals/{item['id']}/sign", headers=PROPOSER)
    assert response.status_code == 403
    async with factory() as session:
        attempt = await session.scalar(select(ExecutionAttempt))
        assert attempt.status == "UNCERTAIN"
        assert (await session.get(SpendingRecord, attempt.id)).status == "RESERVED"
        assert (await session.get(Proposal, item["id"])).status == "SIGNED"


@pytest.mark.asyncio
async def test_fresh_connections_keep_reservation_and_nonce(file_client):
    client, factory = file_client
    await policy(client)
    first = await proposed(client, "10000000000000000")
    assert (
        await client.post(f"/api/v1/proposals/{first['id']}/sign", headers=PROPOSER)
    ).status_code == 200
    # Close the whole connection pool; persisted ownership must not reset.
    await factory.kw["bind"].dispose()
    second = await proposed(client, "10000000000000000")
    assert (
        await client.post(f"/api/v1/proposals/{second['id']}/sign", headers=PROPOSER)
    ).status_code == 200
    async with factory() as session:
        nonces = (
            await session.scalars(select(ExecutionAttempt.nonce).order_by(ExecutionAttempt.nonce))
        ).all()
        assert nonces == [0, 1]
