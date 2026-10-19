"""File-backed SQLite, fake network, public test key; no live services or funds."""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import pytest
from sqlalchemy import func, select

from app.core.config import get_settings
from app.models import (
    AutonomousIntent,
    CapabilityToken,
    ExecutionAttempt,
    ExecutionControl,
    Policy,
    Proposal,
    TreasuryAction,
    TreasuryMandate,
)
from app.services import treasury
from tests.integration.test_payment_security import ADDRESS, ADMIN, APPROVER, PROPOSER, policy
from tests.integration.test_payment_security import file_client as file_client
from tests.integration.test_sepolia_execution import mined
from tests.integration.test_sepolia_execution import rpc as rpc


def mandate():
    return {
        "expected_version": 0,
        "sender": treasury.sender_address(),
        "recipient": ADDRESS,
        "chain_id": 11155111,
        "target_balance_wei": "1000000000000000",
        "sweep_maximum_wei": "30000000000000",
        "minimum_excess_wei": "20000000000000",
        "cooldown_seconds": 600,
        "daily_action_limit": 3,
        "freshness_seconds": 60,
    }


@pytest.fixture
def treasury_rpc(rpc, monkeypatch):
    monkeypatch.setattr(get_settings(), "treasury_monitor_enabled", True)
    monkeypatch.setattr(get_settings(), "auto_execute_enabled", True)
    rpc.eth.get_block = Mock(
        return_value={
            "baseFeePerGas": 1,
            "number": 123,
            "timestamp": int(datetime.now(UTC).timestamp()),
            "hash": bytes.fromhex("ab" * 32),
        }
    )
    rpc.eth.max_priority_fee = 1
    rpc.eth.get_balance = Mock(return_value=1040000000000000)
    return rpc


async def configure(client):
    await policy(client, threshold="1000000000000000")
    response = await client.put("/api/v1/treasury/mandate", headers=ADMIN, json=mandate())
    assert response.status_code == 200, response.text
    assert response.json()["data"]["mode"] == "off"
    response = await client.post(
        "/api/v1/treasury/mode", headers=ADMIN, json={"expected_version": 1, "mode": "plan_only"}
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


async def activate(client):
    await configure(client)
    observation = await client.post("/api/v1/treasury/observe", headers=ADMIN)
    assert observation.status_code == 200, observation.text
    assert observation.json()["data"]["plan"]["state"] == "ELIGIBLE"
    response = await client.post(
        "/api/v1/treasury/mode",
        headers=ADMIN,
        json={"expected_version": 2, "mode": "execute", "confirm_standing_permission": True},
    )
    assert response.status_code == 200, response.text


@pytest.mark.asyncio
async def test_roles_and_plan_only_never_create_authority(file_client, treasury_rpc):
    client, factory = file_client
    assert (await client.get("/api/v1/treasury")).status_code == 401
    for role in [PROPOSER, APPROVER]:
        assert (
            await client.put("/api/v1/treasury/mandate", headers=role, json=mandate())
        ).status_code == 403
        assert (await client.post("/api/v1/treasury/observe", headers=role)).status_code == 403
    await configure(client)
    await asyncio.gather(
        *[client.post("/api/v1/treasury/observe", headers=ADMIN) for _ in range(3)]
    )
    async with factory() as session:
        for model in [Proposal, ExecutionAttempt, CapabilityToken, AutonomousIntent]:
            assert await session.scalar(select(func.count()).select_from(model)) == 0
    assert treasury_rpc.payloads == []
    data = (await client.get("/api/v1/treasury", headers=PROPOSER)).json()["data"]
    assert data["plan"]["proposed_amount_wei"] == "30000000000000"
    assert data["observation"]["block_hash"] == "0x" + "ab" * 32
    assert get_settings().signer_private_key not in json.dumps(data)
    assert get_settings().sepolia_rpc_url not in json.dumps(data)


@pytest.mark.asyncio
async def test_concurrent_execute_existing_pipeline_and_receipt(file_client, treasury_rpc):
    client, factory = file_client
    await activate(client)
    await asyncio.gather(*(treasury.tick(factory) for _ in range(4)))
    assert len(treasury_rpc.payloads) == 1
    async with factory() as session:
        rows = (
            await session.scalars(
                select(TreasuryAction).where(TreasuryAction.proposal_id.is_not(None))
            )
        ).all()
        assert len(rows) == 1
        row = rows[0]
        proposal = await session.get(Proposal, row.proposal_id)
        attempt = await session.scalar(select(ExecutionAttempt))
        assert proposal.status == "SUBMITTED"
        assert attempt.nonce == 7
        assert await session.scalar(select(func.count()).select_from(AutonomousIntent)) == 0
        treasury_rpc.receipts[attempt.tx_hash] = mined(attempt.tx_hash)
    await treasury.tick(factory)
    assert len(treasury_rpc.payloads) == 1
    await treasury.reconcile_outstanding(factory)
    actions = (await client.get("/api/v1/treasury/actions", headers=PROPOSER)).json()["data"]
    executed = next(a for a in actions if a["proposal_id"])
    assert executed["state"] == "CONFIRMED"
    assert executed["explorer_url"].startswith("https://sepolia.etherscan.io/tx/")
    data = (await client.get("/api/v1/treasury", headers=PROPOSER)).json()["data"]
    assert data["daily_actions_used"] == 1 and data["cooldown_active"]


@pytest.mark.asyncio
async def test_invalidated_pending_proposal_cannot_execute_manually(
    file_client, treasury_rpc, monkeypatch
):
    client, factory = file_client
    await activate(client)

    async def no_execution(*args):
        pass

    monkeypatch.setattr(treasury, "run_execution", no_execution)
    await treasury.tick(factory)
    async with factory() as session:
        row = await session.scalar(
            select(TreasuryAction).where(TreasuryAction.proposal_id.is_not(None))
        )
        pid = row.proposal_id
    off = await client.post(
        "/api/v1/treasury/mode", headers=ADMIN, json={"expected_version": 3, "mode": "off"}
    )
    assert off.status_code == 200
    response = await client.post(f"/api/v1/proposals/{pid}/sign", headers=PROPOSER)
    assert response.status_code == 403, response.text
    assert treasury_rpc.payloads == []
    status = (await client.get("/api/v1/treasury", headers=PROPOSER)).json()["data"]
    assert status["daily_actions_used"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case",
    [
        "global_off",
        "stop",
        "wrong_chain",
        "stale",
        "fee",
        "budget",
        "recipient",
        "cap",
        "threshold",
        "balance",
    ],
)
async def test_suppression_and_network_errors_fail_closed(
    file_client, treasury_rpc, monkeypatch, case
):
    client, factory = file_client
    await activate(client)
    if case == "global_off":
        monkeypatch.setattr(get_settings(), "auto_execute_enabled", False)
    elif case == "wrong_chain":
        treasury_rpc.eth.chain_id = 1
    elif case == "stale":
        treasury_rpc.eth.get_block.return_value["timestamp"] -= 1000
    elif case == "fee":
        treasury_rpc.eth.estimate_gas.return_value = 500000
    elif case == "balance":
        treasury_rpc.eth.get_balance.return_value = 1
    else:
        async with factory() as session:
            if case == "stop":
                (await session.get(ExecutionControl, "global")).active = True
            else:
                p = await session.scalar(select(Policy).where(Policy.is_active.is_(True)))
                if case == "budget":
                    p.daily_limit_wei = "1"
                if case == "recipient":
                    p.allowed_recipients = "[]"
                if case == "cap":
                    monkeypatch.setattr(
                        get_settings(),
                        "auto_execute_max_eth",
                        __import__("decimal").Decimal("0.000001"),
                    )
                if case == "threshold":
                    p.escalation_threshold_wei = "30000000000000"
            await session.commit()
    await treasury.tick(factory)
    assert treasury_rpc.payloads == []
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(Proposal)) == 0
    data = (await client.get("/api/v1/treasury", headers=PROPOSER)).json()["data"]
    if case == "balance":
        assert data["plan"]["state"] == "BELOW_TARGET"


@pytest.mark.asyncio
async def test_expired_claim_restart_and_uncertain_identity(file_client, treasury_rpc):
    client, factory = file_client
    await activate(client)
    async with factory() as session:
        m = await session.get(TreasuryMandate, "global")
        m.claim_token, m.claim_until = (
            "crashed-worker",
            (datetime.now(UTC) - timedelta(seconds=1)).isoformat(),
        )
        await session.commit()
    treasury_rpc.eth.send_raw_transaction.side_effect = TimeoutError("fake timeout")
    await treasury.tick(factory)
    async with factory() as session:
        attempt = await session.scalar(select(ExecutionAttempt))
        assert attempt.status == "UNCERTAIN"
        raw, tx_hash, pid = attempt.raw_transaction, attempt.tx_hash, attempt.proposal_id
    for _ in range(2):
        await treasury.tick(factory)
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(ExecutionAttempt)) == 1
        assert (await session.scalar(select(ExecutionAttempt))).raw_transaction == raw
    # Existing manual recovery retains identity even after mandate disabling.
    await client.post(
        "/api/v1/treasury/mode", headers=ADMIN, json={"expected_version": 3, "mode": "off"}
    )
    from web3 import Web3

    treasury_rpc.eth.send_raw_transaction.side_effect = lambda b: Web3.keccak(b)
    response = await client.post(f"/api/v1/proposals/{pid}/sign", headers=PROPOSER)
    assert response.status_code == 200, response.text
    assert response.json()["data"]["transaction"]["tx_hash"] == tx_hash


@pytest.mark.asyncio
async def test_activation_is_separate_and_manual_observation_never_executes(
    file_client, treasury_rpc
):
    client, factory = file_client
    await policy(client, threshold="1000000000000000")
    await client.put("/api/v1/treasury/mandate", headers=ADMIN, json=mandate())
    premature = await client.post(
        "/api/v1/treasury/mode",
        headers=ADMIN,
        json={"expected_version": 1, "mode": "execute", "confirm_standing_permission": True},
    )
    assert premature.status_code == 422
    await client.post(
        "/api/v1/treasury/mode", headers=ADMIN, json={"expected_version": 1, "mode": "plan_only"}
    )
    await client.post("/api/v1/treasury/observe", headers=ADMIN)
    unconfirmed = await client.post(
        "/api/v1/treasury/mode", headers=ADMIN, json={"expected_version": 2, "mode": "execute"}
    )
    assert unconfirmed.status_code == 422
    await client.post(
        "/api/v1/treasury/mode",
        headers=ADMIN,
        json={"expected_version": 2, "mode": "execute", "confirm_standing_permission": True},
    )
    await client.post("/api/v1/treasury/observe", headers=ADMIN)
    await client.get("/api/v1/treasury", headers=PROPOSER)
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(Proposal)) == 0
    assert treasury_rpc.payloads == []


@pytest.mark.asyncio
async def test_edit_during_rpc_invalidates_claim_without_holding_write_lock(
    file_client, treasury_rpc, monkeypatch
):
    client, factory = file_client
    await activate(client)
    entered, release = asyncio.Event(), asyncio.Event()
    original = treasury.observe

    async def slow(config, factory):
        entered.set()
        await release.wait()
        return await original(config, factory)

    monkeypatch.setattr(treasury, "observe", slow)
    task = asyncio.create_task(treasury.tick(factory))
    await asyncio.wait_for(entered.wait(), 1)
    updated = mandate() | {"expected_version": 3}
    response = await asyncio.wait_for(
        client.put("/api/v1/treasury/mandate", headers=ADMIN, json=updated), 2
    )
    assert response.status_code == 200, response.text
    release.set()
    await task
    assert treasury_rpc.payloads == []
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(Proposal)) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["edit", "balance", "global_off", "fees", "stop"])
async def test_shared_boundary_rechecks_before_fresh_capability(
    file_client, treasury_rpc, monkeypatch, change
):
    from app.api.routes.proposals import capability_service
    from app.exceptions import SigningRejectedError
    from app.schemas import NormalizedAction

    client, factory = file_client
    await activate(client)

    async def defer(*args):
        pass

    monkeypatch.setattr(treasury, "run_execution", defer)
    await treasury.tick(factory)
    async with factory() as session:
        row = await session.scalar(
            select(TreasuryAction).where(TreasuryAction.proposal_id.is_not(None))
        )
        pid = row.proposal_id
        proposal = await session.get(Proposal, pid)
        action = NormalizedAction(
            proposal_id=pid,
            correlation_id=proposal.correlation_id,
            recipient=proposal.recipient,
            amount_wei=int(proposal.amount_wei),
            chain_id=11155111,
        )
        # A policy ALLOW is not a substitute for fresh mandate authority, even
        # when the capability issuer is called directly inside this process.
        with pytest.raises(SigningRejectedError):
            await capability_service.issue_token(session, action, 1)
        await session.rollback()
    if change == "edit":
        result = await client.put(
            "/api/v1/treasury/mandate", headers=ADMIN, json=mandate() | {"expected_version": 3}
        )
        assert result.status_code == 200
    if change == "balance":
        treasury_rpc.eth.get_balance.return_value = 1
    if change == "global_off":
        monkeypatch.setattr(get_settings(), "auto_execute_enabled", False)
    if change == "fees":
        treasury_rpc.eth.estimate_gas.return_value = 500000
    if change == "stop":
        async with factory() as session:
            (await session.get(ExecutionControl, "global")).active = True
            await session.commit()
    result = await client.post(f"/api/v1/proposals/{pid}/sign", headers=PROPOSER)
    assert result.status_code >= 400, result.text
    assert treasury_rpc.payloads == []
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(CapabilityToken)) == 0
        assert await session.scalar(select(func.count()).select_from(ExecutionAttempt)) == 0


@pytest.mark.asyncio
async def test_utc_limit_and_cooldown_survive_edits(file_client, treasury_rpc, monkeypatch):
    client, factory = file_client
    await configure(client)
    fixed = datetime(2026, 10, 20, 0, 1, tzinfo=UTC)
    monkeypatch.setattr(treasury, "now", lambda: fixed)
    async with factory() as session:
        m = await session.get(TreasuryMandate, "global")
        config = json.loads(m.config_json)
        # One action from the previous day still applies to cooldown, not the
        # new UTC day's count. No actual execution is created by these fixtures.
        for index in range(4):
            at = fixed - timedelta(minutes=2) if index == 0 else fixed - timedelta(seconds=30)
            session.add(
                TreasuryAction(
                    mandate_id="global",
                    mandate_version=m.version,
                    config_json=m.config_json,
                    observation_json="{}",
                    plan_json="{}",
                    state="FAILED",
                    reason="FIXTURE",
                    claim_token=f"history-{index}",
                    initiated_at=at.isoformat(),
                )
            )
        await session.commit()
        assert await treasury.history_limits(session, config) == (3, True)
    result = await client.put(
        "/api/v1/treasury/mandate", headers=ADMIN, json=mandate() | {"expected_version": 2}
    )
    assert result.status_code == 200
    data = result.json()["data"]
    assert data["daily_actions_used"] == 3 and data["cooldown_active"]
    monkeypatch.setattr(treasury, "now", lambda: fixed + timedelta(days=1))
    data = (await client.get("/api/v1/treasury", headers=PROPOSER)).json()["data"]
    assert data["daily_actions_used"] == 0 and not data["cooldown_active"]


@pytest.mark.asyncio
async def test_first_funding_cost_and_stable_plan_logging(file_client, treasury_rpc, monkeypatch):
    client, factory = file_client
    await configure(client)
    monkeypatch.setattr(get_settings(), "max_gas_units", 248870)
    treasury_rpc.eth.estimate_gas.return_value = 207391
    response = await client.post("/api/v1/treasury/observe", headers=ADMIN)
    data = response.json()["data"]
    assert data["observation"]["fee_quote"]["gas"] == 248870
    assert data["observation"]["maximum_fee_reserve_wei"] == str(248870 * 3)
    assert data["plan"]["state"] == "ELIGIBLE"
    async with factory() as session:
        before = await session.scalar(select(func.count()).select_from(TreasuryAction))
    treasury_rpc.eth.get_block.return_value["baseFeePerGas"] = 2
    await client.post("/api/v1/treasury/observe", headers=ADMIN)
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(TreasuryAction)) == before
    assert treasury_rpc.payloads == []


@pytest.mark.asyncio
async def test_simulation_reports_execution_unavailable(file_client, treasury_rpc, monkeypatch):
    client, factory = file_client
    await configure(client)
    monkeypatch.setattr(get_settings(), "execution_mode", "simulated")
    await client.post("/api/v1/treasury/observe", headers=ADMIN)
    response = await client.post(
        "/api/v1/treasury/mode",
        headers=ADMIN,
        json={"expected_version": 2, "mode": "execute", "confirm_standing_permission": True},
    )
    assert response.status_code == 422
    assert treasury_rpc.payloads == []


@pytest.mark.asyncio
async def test_competing_execution_between_observation_and_lock_invalidates_proof(
    file_client, treasury_rpc, monkeypatch
):
    from app.api.routes.proposals import capability_service
    from app.exceptions import SigningRejectedError
    from app.models import SpendingRecord
    from app.schemas import NormalizedAction

    client, factory = file_client
    await activate(client)

    async def defer(*args):
        pass

    monkeypatch.setattr(treasury, "run_execution", defer)
    await treasury.tick(factory)
    async with factory() as session:
        row = await session.scalar(
            select(TreasuryAction).where(TreasuryAction.proposal_id.is_not(None))
        )
        pid = row.proposal_id
        proposal = await session.get(Proposal, pid)
        action = NormalizedAction(
            proposal_id=pid,
            correlation_id=proposal.correlation_id,
            recipient=proposal.recipient,
            amount_wei=int(proposal.amount_wei),
            chain_id=11155111,
        )
        await treasury.prepare_authority_context(session, pid)
        async with factory() as competing:
            other = Proposal(
                agent_prompt="Synthetic competing payment",
                recipient=ADDRESS,
                amount_wei="1",
                chain_id=11155111,
                status="CONFIRMED",
            )
            competing.add(other)
            await competing.flush()
            competing.add(
                SpendingRecord(
                    proposal_id=other.id,
                    amount_wei="1",
                    status="COMMITTED",
                    period_date=datetime.now(UTC).date().isoformat(),
                )
            )
            await competing.commit()
        with pytest.raises(SigningRejectedError):
            await capability_service.issue_token(session, action, 1)
        await session.rollback()
    assert treasury_rpc.payloads == []


@pytest.mark.asyncio
async def test_rpc_failure_never_becomes_zero_balance(file_client, treasury_rpc):
    client, factory = file_client
    await configure(client)
    treasury_rpc.eth.get_balance.side_effect = TimeoutError("sensitive-provider-url-must-not-leak")
    response = await client.post("/api/v1/treasury/observe", headers=ADMIN)
    data = response.json()["data"]
    assert data["observation"]["status"] == "unavailable"
    assert "balance_wei" not in data["observation"]
    assert data["plan"]["state"] == "NETWORK_UNAVAILABLE"
    assert "sensitive-provider" not in response.text
    assert treasury_rpc.payloads == []
