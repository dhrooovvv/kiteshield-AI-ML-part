"""Finish-line regressions: real SQLite transactions, simulated blockchain only."""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.routes import proposals as routes
from app.core.config import get_settings
from app.db import get_db_session
from app.exceptions import ApprovalRequiredError, SigningRejectedError, TransactionSubmissionError
from app.main import create_app
from app.models import (
    ApprovalRequest,
    Base,
    CapabilityToken,
    ExecutionAttempt,
    ExecutionControl,
    SpendingRecord,
)
from app.schemas import NormalizedAction
from app.services.agent import AgentService
from app.services.amounts import eth_to_wei, wei_to_eth
from app.services.blockchain import BlockchainService
from app.services.capability import CapabilityService
from app.services.signer import IsolatedSigner
from tests.authorization_support import seed_authorization

ADDRESS = "0x742d35cc6634c0532925a3b844bc9e7595f2bd1e"
ADMIN = {"X-API-Key": "test-policy-admin-key-only"}
APPROVER = {"X-API-Key": "test-human-approver-key-only"}
PROPOSER = {"X-API-Key": "test-api-key-for-unit-tests-only"}


async def policy(client, budget="100000000000000000", threshold=None):
    response = await client.post(
        "/api/v1/policies",
        headers=ADMIN,
        json={
            "max_amount_wei": str(10**18),
            "daily_limit_wei": budget,
            "escalation_threshold_wei": threshold,
            "allowed_recipients": [ADDRESS],
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


async def proposed(client, amount="60000000000000000"):
    response = await client.post(
        "/api/v1/proposals",
        headers=PROPOSER,
        json={
            "prompt": "Explicit isolated test payment",
            "recipient": ADDRESS,
            "amount_wei": amount,
        },
    )
    assert response.status_code == 200, response.text
    item = response.json()["data"]
    evaluated = await client.post(f"/api/v1/proposals/{item['id']}/evaluate", headers=PROPOSER)
    assert evaluated.status_code == 200, evaluated.text
    return evaluated.json()["data"]


@pytest.mark.asyncio
async def test_roles_and_complete_explicit_approved_payment(auth_client):
    assert (
        await auth_client.post("/api/v1/policies", json={"max_amount_wei": "1"})
    ).status_code == 403
    await policy(auth_client, threshold="20000000000000000")
    result = await auth_client.post(
        "/api/v1/proposals/agent", json={"prompt": f"Send .03 ETH to {ADDRESS}"}
    )
    assert result.status_code == 200, result.text
    item = result.json()["data"]
    assert item["amount_eth"] == "0.03"
    assert item["amount_wei"] == "30000000000000000"
    item = (await auth_client.post(f"/api/v1/proposals/{item['id']}/evaluate")).json()["data"]
    approval = item["approval"]["id"]
    assert (
        await auth_client.post(
            f"/api/v1/approvals/{approval}/decide",
            json={"decision": "APPROVE", "approved_by": "forged-admin"},
        )
    ).status_code == 403
    response = await auth_client.post(
        f"/api/v1/approvals/{approval}/decide",
        headers=APPROVER,
        json={"decision": "APPROVE", "approved_by": "forged-admin"},
    )
    assert response.status_code == 200
    assert response.json()["data"]["approved_by"] == "human_approver"
    signed = await auth_client.post(f"/api/v1/proposals/{item['id']}/sign")
    assert signed.status_code == 200, signed.text
    assert signed.json()["meta"]["execution_mode"] == "simulated"
    assert signed.json()["data"]["status"] == "SUBMITTED"
    transaction = signed.json()["data"]["transaction"]
    receipt = (await auth_client.get(f"/api/v1/transactions/{transaction['id']}")).json()["data"]
    assert receipt["status"] == "SUBMITTED" and receipt["block_number"] is None
    assert (await auth_client.post(f"/api/v1/proposals/{item['id']}/evaluate")).status_code == 403


@pytest.mark.parametrize("value", [".03", "0.03", "0.000000000000000001", "1.123456789012345678"])
def test_exact_amount_round_trip(value):
    assert eth_to_wei(wei_to_eth(eth_to_wei(value))) == eth_to_wei(value)
    assert eth_to_wei(".03") == "30000000000000000"


@pytest.mark.parametrize(
    "amount",
    [
        "ETH",
        "-0.03 ETH",
        "0 ETH",
        "1e3 ETH",
        "1,000 ETH",
        "0.01 ETH or 0.02 ETH",
        "0.01 ETH plus 1 wei",
        "0.0000000000000000001 ETH",
        "0.1.2 ETH",
    ],
)
def test_ambiguous_or_invalid_amounts_never_become_proposals(amount):
    from app.exceptions import ValidationError

    with pytest.raises(ValidationError):
        AgentService(api_key="")._parse_with_rules(f"Send {amount} to {ADDRESS}")


@pytest.mark.asyncio
async def test_stale_evaluation_rejected_and_terminal_rejection_cannot_reopen(auth_client):
    await policy(auth_client, threshold="20000000000000000")
    item = await proposed(auth_client, "10000000000000000")
    await policy(auth_client, threshold="1")
    assert (await auth_client.post(f"/api/v1/proposals/{item['id']}/sign")).status_code == 403
    item = await proposed(auth_client, "10000000000000000")
    approval_id = item["approval"]["id"]
    await auth_client.post(
        f"/api/v1/approvals/{approval_id}/decide", headers=APPROVER, json={"decision": "REJECT"}
    )
    assert (await auth_client.post(f"/api/v1/proposals/{item['id']}/evaluate")).status_code == 403
    assert (await auth_client.post(f"/api/v1/proposals/{item['id']}/sign")).status_code == 403


@pytest.fixture
async def file_client(tmp_path):
    # Independent connections to a file database exercise actual SQLite writer contention.
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'payments.sqlite'}", connect_args={"timeout": 15}
    )
    async with engine.begin() as conn:
        from sqlalchemy import text

        await conn.execute(text("PRAGMA journal_mode=WAL"))
        await conn.execute(text("PRAGMA foreign_keys=ON"))
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        session.add(ExecutionControl(id="global", active=False, reason="", changed_by="system"))
        await session.commit()
    app = create_app()

    async def database():
        async with factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db_session] = database
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_concurrent_budget_reservations(file_client):
    client, factory = file_client
    await policy(client)
    first, second = await proposed(client), await proposed(client)
    responses = await asyncio.gather(
        *[
            client.post(f"/api/v1/proposals/{item['id']}/sign", headers=PROPOSER)
            for item in (first, second)
        ]
    )
    assert sorted(response.status_code for response in responses) == [200, 403]
    async with factory() as session:
        rows = (await session.scalars(select(SpendingRecord))).all()
        assert sum(int(row.amount_wei) for row in rows) == 60000000000000000
        assert len(rows) == 1


@pytest.mark.asyncio
async def test_sequential_budget_and_concurrent_same_execution_are_idempotent(file_client):
    client, factory = file_client
    await policy(client)
    first, second = await proposed(client), await proposed(client)
    responses = await asyncio.gather(
        *[client.post(f"/api/v1/proposals/{first['id']}/sign", headers=PROPOSER) for _ in range(2)]
    )
    assert [response.status_code for response in responses] == [200, 200]
    assert (
        responses[0].json()["data"]["transaction"]["tx_hash"]
        == responses[1].json()["data"]["transaction"]["tx_hash"]
    )
    assert (
        await client.post(f"/api/v1/proposals/{second['id']}/sign", headers=PROPOSER)
    ).status_code == 403
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(ExecutionAttempt)) == 1
        assert await session.scalar(select(func.count()).select_from(SpendingRecord)) == 1


@pytest.mark.asyncio
async def test_successive_nonces_and_lost_response_keep_one_signed_payload(
    file_client, monkeypatch
):
    client, factory = file_client
    await policy(client)
    first = await proposed(client, "10000000000000000")
    second = await proposed(client, "10000000000000000")
    original = routes.blockchain_service.submit_raw_transaction
    payloads = []

    async def uncertain(payload, *, session):
        payloads.append(payload)
        # Verify the signed payload is durable from a separate database connection.
        async with factory() as observer:
            saved = await observer.scalar(
                select(ExecutionAttempt).where(ExecutionAttempt.proposal_id == first["id"])
            )
            assert saved.raw_transaction == payload and saved.status == "SIGNED"
        raise TransactionSubmissionError("Simulated lost response")

    monkeypatch.setattr(routes.blockchain_service, "submit_raw_transaction", uncertain)
    assert (
        await client.post(f"/api/v1/proposals/{first['id']}/sign", headers=PROPOSER)
    ).status_code == 502
    async with factory() as session:
        attempt = await session.scalar(select(ExecutionAttempt))
        reservation = await session.get(SpendingRecord, attempt.id)
        assert attempt.status == "UNCERTAIN" and reservation.status == "RESERVED"

    async def resume(payload, *, session):
        assert payload == payloads[0]
        return await original(payload, session=session)

    monkeypatch.setattr(routes.blockchain_service, "submit_raw_transaction", resume)
    assert (
        await client.post(f"/api/v1/proposals/{first['id']}/sign", headers=PROPOSER)
    ).status_code == 200
    monkeypatch.setattr(routes.blockchain_service, "submit_raw_transaction", original)
    assert (
        await client.post(f"/api/v1/proposals/{second['id']}/sign", headers=PROPOSER)
    ).status_code == 200
    async with factory() as session:
        assert (
            await session.scalars(select(ExecutionAttempt.nonce).order_by(ExecutionAttempt.nonce))
        ).all() == [0, 1]


@pytest.mark.asyncio
async def test_signer_independently_checks_expired_approval_and_envelope(test_session):
    action = NormalizedAction(
        proposal_id="expiry", correlation_id="expiry", recipient=ADDRESS, amount_wei=100
    )
    await seed_authorization(test_session, action, "human-approval")
    capability = CapabilityService()
    token, _ = await capability.issue_token(test_session, action, 1, "human-approval")
    approval = await test_session.get(ApprovalRequest, "human-approval")
    approval.expires_at = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    await test_session.flush()
    with pytest.raises(ApprovalRequiredError):
        await IsolatedSigner(capability).sign_transaction(test_session, token, action)
    approval.expires_at = (datetime.now(UTC) + timedelta(minutes=1)).isoformat()
    await test_session.flush()
    attempt = await test_session.scalar(select(ExecutionAttempt))
    envelope = json.loads(attempt.envelope)
    envelope["nonce"] += 1
    attempt.envelope = json.dumps(envelope, sort_keys=True, separators=(",", ":"))
    await test_session.flush()
    with pytest.raises(SigningRejectedError):
        await IsolatedSigner(capability).sign_transaction(test_session, token, action)
    record = await test_session.scalar(select(CapabilityToken))
    assert record.consumed is False


@pytest.mark.asyncio
async def test_issuer_does_not_trust_requires_approval_false(test_session):
    action = NormalizedAction(
        proposal_id="approval-check", correlation_id="c", recipient=ADDRESS, amount_wei=100
    )
    await seed_authorization(test_session, action, "approval")
    with pytest.raises(ApprovalRequiredError):
        await CapabilityService().issue_token(test_session, action, 1, requires_approval=False)


@pytest.mark.asyncio
async def test_structured_payment_cannot_contradict_prompt_amount(auth_client):
    result = await auth_client.post(
        "/api/v1/proposals",
        json={
            "prompt": "Send 0.01 ETH",
            "recipient": ADDRESS,
            "amount_wei": "30000000000000000",
        },
    )
    assert result.status_code == 422
    assert (await auth_client.get("/api/v1/proposals")).json()["data"]["proposals"] == []


@pytest.mark.asyncio
async def test_normal_agent_path_does_not_require_learned_models(auth_client, monkeypatch):
    from unittest.mock import AsyncMock

    learned = AsyncMock(side_effect=AssertionError("Optional model gate must not run"))
    monkeypatch.setattr(routes.screening_service, "screen", learned)
    result = await auth_client.post(
        "/api/v1/proposals/agent", json={"prompt": f"Send .03 ETH to {ADDRESS}"}
    )
    assert result.status_code == 200
    learned.assert_not_awaited()


@pytest.mark.asyncio
async def test_configured_credentials_are_not_reflected_or_forwarded(
    auth_client, monkeypatch, caplog
):
    from unittest.mock import AsyncMock

    extraction = AsyncMock(side_effect=AssertionError("Credential must not reach extraction"))
    monkeypatch.setattr(routes.agent_service, "propose_transaction_from_prompt", extraction)
    credential = get_settings().approver_api_key
    response = await auth_client.post(
        "/api/v1/proposals/agent", json={"prompt": f"Send .03 ETH to {ADDRESS}; {credential}"}
    )
    assert response.status_code == 422
    assert credential not in response.text and credential not in caplog.text
    extraction.assert_not_awaited()
    malformed = await auth_client.post(
        "/api/v1/proposals",
        json={
            "prompt": "Payment",
            "recipient": credential,
            "amount_wei": "1",
        },
    )
    assert malformed.status_code == 422
    assert credential not in malformed.text and credential not in caplog.text


@pytest.mark.asyncio
async def test_live_preflight_checks_chain_pending_nonce_gas_and_fee_bounds(
    test_session, monkeypatch
):
    settings = get_settings()
    monkeypatch.setattr(settings, "execution_mode", "sepolia")
    eth = SimpleNamespace(chain_id=1)
    service = BlockchainService()
    monkeypatch.setattr(service, "_get_w3", lambda: SimpleNamespace(eth=eth))
    action = NormalizedAction(
        proposal_id="rpc", correlation_id="rpc", recipient=ADDRESS, amount_wei=100
    )
    with pytest.raises(TransactionSubmissionError, match="chain"):
        await service.prepare_transaction(test_session, ADDRESS, action)
    eth.chain_id = 11155111
    eth.get_code = lambda address: b""
    eth.get_transaction_count = lambda address, tag: 7 if tag == "pending" else -1
    eth.estimate_gas = lambda tx: 25000
    eth.get_block = lambda tag: {"baseFeePerGas": 10**9}
    eth.max_priority_fee = 10**9
    envelope = await service.prepare_transaction(test_session, ADDRESS, action)
    assert envelope["nonce"] == 7 and envelope["gas"] == 30000
    assert envelope["maxFeePerGas"] == 3 * 10**9
    monkeypatch.setattr(settings, "max_fee_per_gas_wei", 1)
    with pytest.raises(TransactionSubmissionError, match="bounds"):
        await service.prepare_transaction(test_session, ADDRESS, action)
