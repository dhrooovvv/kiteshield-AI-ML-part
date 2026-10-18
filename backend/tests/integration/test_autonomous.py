"""Isolated SQLite and fake RPC only; never contacts Sepolia."""

import asyncio

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.models import AutonomousIntent, ExecutionAttempt
from tests.integration.test_payment_security import ADDRESS, PROPOSER, policy
from tests.integration.test_payment_security import file_client as file_client
from tests.integration.test_sepolia_execution import rpc as rpc


async def agent(client, amount="0.00002"):
    response = await client.post("/api/v1/proposals/agent", headers=PROPOSER,
                                 json={"prompt": f"Send {amount} ETH to {ADDRESS}"})
    assert response.status_code == 200, response.text
    return response.json()["data"]["id"]


def enable(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "auto_execute_enabled", True)
    client._transport.app.state.verified_rpc = {"chain_id": 11155111}


@pytest.mark.asyncio
async def test_autonomous_real_coordinator_fake_rpc_concurrent(file_client, rpc, monkeypatch):
    client, factory = file_client
    enable(client, monkeypatch)
    await policy(client, threshold="1000000000000000")
    item = await agent(client)
    replies = await asyncio.gather(*[
        client.post(f"/api/v1/proposals/{item}/evaluate", headers=PROPOSER) for _ in range(2)
    ])
    assert any(r.status_code == 200 for r in replies)
    assert len(rpc.payloads) == 1
    # Re-evaluation cannot create a replacement transaction.
    await client.post(f"/api/v1/proposals/{item}/evaluate", headers=PROPOSER)
    assert len(rpc.payloads) == 1
    async with factory() as session:
        assert len((await session.scalars(select(ExecutionAttempt))).all()) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("case", [
    "off", "unverified", "simulated", "over_limit", "escalate", "deny",
    "REVIEW", "BLOCK", "unlisted", "stop",
])
async def test_ineligible_never_executes(file_client, rpc, monkeypatch, case):
    client, factory = file_client
    enable(client, monkeypatch)
    await policy(client, budget="1" if case == "deny" else "100000000000000000",
                 threshold="1" if case == "escalate" else "1000000000000000")
    item = await agent(client, "0.0002" if case == "over_limit" else "0.00002")
    if case == "off":
        monkeypatch.setattr(get_settings(), "auto_execute_enabled", False)
    if case == "unverified":
        client._transport.app.state.verified_rpc = None
    if case == "simulated":
        monkeypatch.setattr(get_settings(), "execution_mode", "simulated")
    async with factory() as session:
        if case in ("REVIEW", "BLOCK"):
            (await session.get(AutonomousIntent, item)).outcome = case
        if case == "unlisted":
            from app.models import Policy
            p = await session.scalar(select(Policy))
            p.allowed_recipients = "[]"
        if case == "stop":
            from app.models import ExecutionControl
            (await session.get(ExecutionControl, "global")).active = True
        await session.commit()
    await client.post(f"/api/v1/proposals/{item}/evaluate", headers=PROPOSER)
    assert rpc.payloads == []
    async with factory() as session:
        assert (await session.scalar(select(ExecutionAttempt.id))) is None


@pytest.mark.asyncio
async def test_confirmation_then_successive_nonce_and_same_bytes_recovery(
    file_client, rpc, monkeypatch,
):
    from app.models import AuditEvent
    from tests.integration.test_sepolia_execution import mined

    client, factory = file_client
    enable(client, monkeypatch)
    await policy(client, threshold="1000000000000000")
    first = await agent(client)
    response = await client.post(f"/api/v1/proposals/{first}/evaluate", headers=PROPOSER)
    assert response.status_code == 200, response.text
    tx = response.json()["data"]["transaction"]
    second = await agent(client)
    waiting = await client.post(f"/api/v1/proposals/{second}/evaluate", headers=PROPOSER)
    assert waiting.json()["data"]["status"] == "ALLOWED"
    assert len(rpc.payloads) == 1
    rpc.receipts[tx["tx_hash"]] = mined(tx["tx_hash"])
    assert (await client.get(f"/api/v1/transactions/{tx['id']}", headers=PROPOSER)
            ).json()["data"]["status"] == "CONFIRMED"
    rpc.eth.send_raw_transaction.side_effect = TimeoutError("isolated timeout")
    failed = await client.post(f"/api/v1/proposals/{second}/evaluate", headers=PROPOSER)
    assert failed.status_code >= 400
    async with factory() as session:
        attempts = (await session.scalars(select(ExecutionAttempt).order_by(
            ExecutionAttempt.nonce))).all()
        assert [a.nonce for a in attempts] == [7, 8]
        signed_hash = attempts[1].tx_hash
        signed_bytes = attempts[1].raw_transaction
        events = (await session.scalars(select(AuditEvent).where(
            AuditEvent.actor == "autonomous_executor"))).all()
        assert "AUTO_EXECUTION_CONFIRM" in [e.event_type for e in events]
        assert "AUTO_EXECUTION_FAILURE" in [e.event_type for e in events]
    from web3 import Web3
    rpc.eth.send_raw_transaction.side_effect = lambda payload: Web3.keccak(payload)
    retried = await client.post(f"/api/v1/proposals/{second}/sign", headers=PROPOSER)
    assert retried.status_code == 200, retried.text
    assert retried.json()["data"]["transaction"]["tx_hash"] == signed_hash
    async with factory() as session:
        attempts = (await session.scalars(select(ExecutionAttempt))).all()
        assert len(attempts) == 2
        assert next(a for a in attempts if a.nonce == 8).raw_transaction == signed_bytes
