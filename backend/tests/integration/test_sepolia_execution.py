"""Real signer + file SQLite + fake Sepolia RPC; no network or funds used."""

import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eth_account import Account
from hexbytes import HexBytes
from sqlalchemy import select
from web3 import Web3

from app.api.routes import proposals as routes
from app.core.config import get_settings
from app.models import AuditEvent, ExecutionAttempt, SpendingRecord, Transaction
from app.services.blockchain import BlockchainService
from tests.integration.test_payment_security import ADDRESS, APPROVER, PROPOSER, policy, proposed
from tests.integration.test_payment_security import file_client as file_client


@pytest.fixture
def rpc(monkeypatch):
    monkeypatch.setattr(get_settings(), "execution_mode", "sepolia")
    # Fake RPC only; real transaction bytes and hashes are produced by the signer.
    receipts = {}
    payloads = []

    def send(payload):
        payloads.append(payload)
        return Web3.keccak(payload)

    eth = SimpleNamespace(
        chain_id=11155111,
        get_code=Mock(return_value=b""),
        get_transaction_count=Mock(return_value=7),
        estimate_gas=Mock(return_value=21000),
        get_block=Mock(return_value={"baseFeePerGas": 10**9}),
        max_priority_fee=10**9,
        send_raw_transaction=Mock(side_effect=send),
        get_transaction_receipt=Mock(side_effect=lambda h: receipts.get(h)),
    )
    monkeypatch.setattr(BlockchainService, "_get_w3", lambda self: SimpleNamespace(eth=eth))
    return SimpleNamespace(eth=eth, receipts=receipts, payloads=payloads)


def mined(tx_hash, status=1):
    return {
        "transactionHash": HexBytes(tx_hash),
        "status": status,
        "blockNumber": 123,
        "blockHash": HexBytes("0x" + "aa" * 32),
        "gasUsed": 21000,
        "effectiveGasPrice": 2 * 10**9,
        "transactionIndex": 0,
    }


async def sign(client, item):
    return await client.post(f"/api/v1/proposals/{item['id']}/sign", headers=PROPOSER)


@pytest.mark.asyncio
async def test_agent_approval_live_rpc_submission_and_durable_receipt(file_client, rpc):
    client, factory = file_client
    await policy(client, threshold="1")
    created = await client.post(
        "/api/v1/proposals/agent",
        headers=PROPOSER,
        json={"prompt": f"Send .00001 ETH to {ADDRESS}"},
    )
    assert created.status_code == 200, created.text
    item = created.json()["data"]
    assert item["amount_wei"] == "10000000000000"
    evaluated = await client.post(f"/api/v1/proposals/{item['id']}/evaluate", headers=PROPOSER)
    item = evaluated.json()["data"]
    assert (await sign(client, item)).status_code == 403
    approval_id = item["approval"]["id"]
    approved = await client.post(
        f"/api/v1/approvals/{approval_id}/decide", headers=APPROVER, json={"decision": "APPROVE"}
    )
    assert approved.status_code == 200
    submitted = await sign(client, item)
    assert submitted.status_code == 200, submitted.text
    tx = submitted.json()["data"]["transaction"]
    assert tx["execution_outcome"] == "SUBMITTED" and tx["receipt"] is None
    rpc.receipts[tx["tx_hash"]] = mined(tx["tx_hash"])
    confirmed = await client.get(f"/api/v1/transactions/{tx['id']}", headers=PROPOSER)
    data = confirmed.json()["data"]
    assert data["status"] == data["execution_outcome"] == "CONFIRMED"
    assert data["receipt"]["transactionHash"] == tx["tx_hash"]
    assert data["explorer_url"].endswith(tx["tx_hash"])
    await factory.kw["bind"].dispose()
    # Restart/connection replacement preserves receipt and exactly one audit event.
    await client.get(f"/api/v1/transactions/{tx['id']}", headers=PROPOSER)
    async with factory() as session:
        saved = await session.get(Transaction, tx["id"])
        assert saved.receipt_json and saved.status == "CONFIRMED"
        events = (
            await session.scalars(select(AuditEvent).where(AuditEvent.event_type == "TX_CONFIRMED"))
        ).all()
        assert len(events) == 1
        assert (await session.scalar(select(SpendingRecord))).status == "COMMITTED"
    from unittest.mock import patch

    from scripts import export_payment_evidence

    with patch.object(export_payment_evidence, "get_session_factory", return_value=factory):
        exported = (await export_payment_evidence.export([item["id"]]))[0]
    assert exported["transaction"]["receipt"]["status"] == 1
    assert exported["policy_version"] == 1 and exported["approval_id"] == approval_id
    assert exported["audit_references"] and exported["nonce"] == 7
    assert "raw_transaction" not in exported and "prompt" not in exported
    assert (await sign(client, item)).status_code == 200
    assert (
        await client.post(f"/api/v1/proposals/{item['id']}/evaluate", headers=PROPOSER)
    ).status_code == 403
    assert rpc.eth.send_raw_transaction.call_count == 1


@pytest.mark.asyncio
async def test_two_successive_live_nonces_and_durable_before_send(file_client, rpc):
    client, factory = file_client
    await policy(client)
    original = routes.blockchain_service.submit_raw_transaction

    async def observe(raw, *, session):
        async with factory() as observer:
            saved = await observer.scalar(
                select(ExecutionAttempt).where(ExecutionAttempt.raw_transaction == raw)
            )
            assert saved and saved.status == "SIGNED" and saved.tx_hash
        return await original(raw, session=session)

    from unittest.mock import patch

    with patch.object(routes.blockchain_service, "submit_raw_transaction", side_effect=observe):
        for _ in range(2):
            item = await proposed(client, "10000000000000")
            assert (await sign(client, item)).status_code == 200
    async with factory() as session:
        assert (
            await session.scalars(select(ExecutionAttempt.nonce).order_by(ExecutionAttempt.nonce))
        ).all() == [7, 8]
    assert rpc.eth.get_transaction_count.call_args.args[1] == "pending"
    assert len(rpc.payloads) == 2 and rpc.payloads[0] != rpc.payloads[1]


@pytest.mark.asyncio
async def test_lost_broadcast_response_reconciles_receipt_without_resigning(file_client, rpc):
    client, factory = file_client
    await policy(client)
    item = await proposed(client, "10000000000000")

    def accepted_but_timeout(raw):
        tx_hash = "0x" + Web3.keccak(raw).hex().removeprefix("0x")
        rpc.receipts[tx_hash] = mined(tx_hash)
        raise TimeoutError("mock timeout after acceptance")

    rpc.eth.send_raw_transaction.side_effect = accepted_but_timeout
    assert (await sign(client, item)).status_code == 502
    async with factory() as session:
        attempt = await session.scalar(select(ExecutionAttempt))
        raw, tx_hash = attempt.raw_transaction, attempt.tx_hash
        assert attempt.status == "UNCERTAIN"
        assert (await session.scalar(select(Transaction))).execution_outcome == "UNCERTAIN"
    # Even if a policy change would now prohibit rebroadcast, receipt observation
    # must still reconcile the already accepted transaction.
    await policy(client, budget="1")
    result = await sign(client, item)
    assert result.status_code == 200, result.text
    assert result.json()["data"]["transaction"]["execution_outcome"] == "CONFIRMED"
    async with factory() as session:
        attempt = await session.scalar(select(ExecutionAttempt))
        assert (attempt.raw_transaction, attempt.tx_hash) == (raw, tx_hash)
    assert rpc.eth.send_raw_transaction.call_count == 1


@pytest.mark.asyncio
async def test_timeout_retry_uses_identical_bytes_and_pending_budget_stays_reserved(
    file_client, rpc
):
    client, factory = file_client
    await policy(client, budget="10000000000000")
    item = await proposed(client, "10000000000000")
    received = []

    def timeout(raw):
        received.append(raw)
        raise TimeoutError("mock")

    rpc.eth.send_raw_transaction.side_effect = timeout
    assert (await sign(client, item)).status_code == 502
    rpc.eth.send_raw_transaction.side_effect = lambda raw: received.append(raw) or Web3.keccak(raw)
    assert (await sign(client, item)).status_code == 200
    assert received[0] == received[1]
    second = await proposed(client, "1")
    assert (await sign(client, second)).status_code == 403
    async with factory() as session:
        assert (await session.scalar(select(SpendingRecord))).status == "RESERVED"
        assert len((await session.scalars(select(ExecutionAttempt))).all()) == 1


@pytest.mark.asyncio
async def test_unauthorized_roles_policy_and_wrong_chain_never_broadcast(file_client, rpc):
    client, _ = file_client
    assert (
        await client.post("/api/v1/policies", headers=PROPOSER, json={"max_amount_wei": "1"})
    ).status_code == 403
    await policy(client)
    item = await proposed(client, "1")
    assert (
        await client.post(f"/api/v1/proposals/{item['id']}/sign", headers=APPROVER)
    ).status_code == 403
    rpc.eth.chain_id = 1
    assert (await sign(client, item)).status_code == 502
    rpc.eth.send_raw_transaction.assert_not_called()


@pytest.mark.asyncio
async def test_reverted_receipt_releases_principal_but_never_reopens(file_client, rpc):
    client, factory = file_client
    await policy(client)
    item = await proposed(client, "10000000000000")
    response = await sign(client, item)
    tx = response.json()["data"]["transaction"]
    rpc.receipts[tx["tx_hash"]] = mined(tx["tx_hash"], status=0)
    result = await client.get(f"/api/v1/transactions/{tx['id']}", headers=PROPOSER)
    assert result.json()["data"]["execution_outcome"] == "REVERTED"
    async with factory() as session:
        assert (await session.scalar(select(SpendingRecord))).status == "RELEASED"
    assert (
        await client.post(f"/api/v1/proposals/{item['id']}/evaluate", headers=PROPOSER)
    ).status_code == 403
    assert (await sign(client, item)).status_code == 200  # idempotent observation, never resends
    assert rpc.eth.send_raw_transaction.call_count == 1


@pytest.mark.asyncio
async def test_wrong_receipt_hash_never_confirms_or_releases_budget(file_client, rpc):
    client, factory = file_client
    await policy(client)
    item = await proposed(client, "10000000000000")
    tx = (await sign(client, item)).json()["data"]["transaction"]
    rpc.receipts[tx["tx_hash"]] = mined("0x" + "ff" * 32)
    result = await client.get(f"/api/v1/transactions/{tx['id']}", headers=PROPOSER)
    assert result.status_code == 502
    async with factory() as session:
        assert (await session.scalar(select(Transaction))).status == "SUBMITTED"
        assert (await session.scalar(select(SpendingRecord))).status == "RESERVED"


@pytest.mark.asyncio
async def test_live_concurrent_budget_contention_allows_only_one_broadcast(file_client, rpc):
    client, factory = file_client
    await policy(client, budget="10000000000000")
    first = await proposed(client, "6000000000000")
    second = await proposed(client, "6000000000000")
    results = await asyncio.gather(sign(client, first), sign(client, second))
    assert sorted(r.status_code for r in results) == [200, 403]
    assert rpc.eth.send_raw_transaction.call_count == 1
    async with factory() as session:
        reservations = (await session.scalars(select(SpendingRecord))).all()
        assert len(reservations) == 1 and reservations[0].status == "RESERVED"


@pytest.mark.asyncio
async def test_concurrent_receipt_refresh_records_one_confirmation(file_client, rpc):
    client, factory = file_client
    await policy(client)
    item = await proposed(client, "1")
    tx = (await sign(client, item)).json()["data"]["transaction"]
    rpc.receipts[tx["tx_hash"]] = mined(tx["tx_hash"])
    results = await asyncio.gather(
        *[client.get(f"/api/v1/transactions/{tx['id']}", headers=PROPOSER) for _ in range(2)]
    )
    assert all(r.status_code == 200 for r in results)
    async with factory() as session:
        events = (
            await session.scalars(select(AuditEvent).where(AuditEvent.event_type == "TX_CONFIRMED"))
        ).all()
        assert len(events) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "violation",
    [
        None,
        "sender",
        "recipient",
        "amount",
        "nonce",
        "gas",
        "fee",
        "total",
        "fee_race",
    ],
)
async def test_explicit_payment_limits_checked_before_signing(file_client, rpc, violation):
    client, factory = file_client
    await policy(client)
    item = await proposed(client, "10000000000000")
    rpc.eth.get_block.return_value = {"baseFeePerGas": 16}
    rpc.eth.max_priority_fee = 1
    limits = {
        "sender": Account.from_key(get_settings().signer_private_key).address,
        "recipient": ADDRESS,
        "amount_wei": "10000000000000",
        "chain_id": 11155111,
        "nonce": 7,
        "max_gas_units": 25200,
        "max_fee_per_gas_wei": 33,
        "max_priority_fee_per_gas_wei": 1,
        "max_total_cost_wei": str(10**13 + 25200 * 33),
    }
    if violation == "sender":
        limits["sender"] = ADDRESS
    elif violation == "recipient":
        limits["recipient"] = "0x" + "11" * 20
    elif violation == "amount":
        limits["amount_wei"] = "20000000000000"
    elif violation == "nonce":
        limits["nonce"] = 6
    elif violation == "gas":
        limits["max_gas_units"] = 25199
    elif violation == "fee":
        limits["max_fee_per_gas_wei"] = 32
    elif violation == "total":
        limits["max_total_cost_wei"] = str(10**13 + 25200 * 33 - 1)
    elif violation == "fee_race":
        rpc.eth.get_block.return_value = {"baseFeePerGas": 17}
    result = await client.post(
        f"/api/v1/proposals/{item['id']}/sign", headers=PROPOSER, json=limits
    )
    assert result.status_code == (403 if violation else 200), result.text
    if violation:
        rpc.eth.send_raw_transaction.assert_not_called()
        async with factory() as session:
            assert (await session.scalar(select(ExecutionAttempt))) is None
            assert (await session.scalar(select(SpendingRecord))) is None
    else:
        assert rpc.eth.send_raw_transaction.call_count == 1
        async with factory() as session:
            event = await session.scalar(
                select(AuditEvent).where(AuditEvent.event_type == "EXECUTION_LIMITS_CHECKED")
            )
            assert event is not None
