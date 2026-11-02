"""Main-wallet integration against test-owned in-memory DBs; no network or signing."""

import json

import pytest
import pytest_asyncio
from eth_account import Account
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.config import get_settings
from app.exceptions import SigningRejectedError
from app.models import AutonomousIntent, Policy, Proposal
from app.models.assistant import AssistantPaymentDraft
from app.models.invoices import Vendor
from app.schemas import NormalizedAction
from demo_autonomy.engine import HumanRequiredError
from demo_autonomy.main_wallet import MainAuthority, MainWalletAdapter, mount_main_wallet

RECIPIENT = "0x229D5588641f2614e3F486c853D8BA0eC5FFe811"


@pytest_asyncio.fixture
async def durable(app, test_engine, client, monkeypatch, tmp_path):
    s = get_settings()
    for key, value in {
        "execution_mode": "sepolia",
        "auto_execute_enabled": True,
        "autonomy_enabled": True,
        "autonomy_live_enabled": True,
        "autonomy_quarantine_enabled": True,
        "autonomy_recipient": RECIPIENT,
        "autonomy_payment_budget_wei": 1000,
        "autonomy_session_fee_budget_wei": 100000,
        "autonomy_funding_budget_wei": 0,
        "autonomy_faucet_grant_ceiling_wei": 0,
        "autonomy_profile_dir": str(tmp_path / "private-tasks"),
        "autonomy_model_digest": "a" * 64,
        "autonomy_ollama_version": "fixture",
    }.items():
        monkeypatch.setattr(s, key, value)
    factory = async_sessionmaker(test_engine, expire_on_commit=False)
    monkeypatch.setattr("app.db.get_session_factory", lambda: factory)
    app.state.verified_rpc = {"chain_id": 11155111}
    # Production rejects the public fixture wallet; only these tests skip that
    # identity gate. All core roles/policy/vendor checks remain real.
    monkeypatch.setattr(MainWalletAdapter, "validate_profile", lambda self: None)
    mount_main_wallet(app, s)
    child = app.state.autonomy_app
    engine = child.state.engine
    engine.initialize()
    adapter = MainWalletAdapter(
        engine, app, MainAuthority.from_settings(s), Account.from_key("b" * 64).address
    )
    await adapter.initialize()
    child.state.adapter = adapter
    async with factory() as session:
        session.add(
            Policy(
                version=1,
                is_active=True,
                max_amount_wei="1000",
                daily_limit_wei="10000",
                allowed_recipients=json.dumps([RECIPIENT]),
                escalation_threshold_wei="50",
            )
        )
        session.add(
            Vendor(
                id="vendor",
                name="Acme",
                payout_address=RECIPIENT,
                maximum_wei="1000",
                version=1,
                active=True,
                updated_by="policy_admin",
            )
        )
        await session.commit()
    result = await client.put(
        "/api/v1/autonomy/mandate",
        headers={"X-API-Key": s.policy_admin_api_key},
        json={
            "supplier": "Acme",
            "recipient": RECIPIENT,
            "payment_cap": 1000,
            "funding_cap": "0",
            "approval_threshold": "50",
        },
    )
    assert result.status_code == 200
    yield engine, adapter, factory
    await adapter.client.aclose()


async def new_task(engine, amount=10, key="main_task_fixture"):
    task_id = engine.create(f"fund if needed, pay supplier Acme {amount} wei, verify", key)

    async def planner(_):
        return {"steps": ["balance", "fund", "payment", "receipt"]}

    await engine.plan(task_id, planner)
    return task_id


@pytest.mark.asyncio
async def test_main_mandate_preserves_policy_and_role_separation(durable, client):
    engine, adapter, factory = durable
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(Policy)) == 1
        policy = await session.scalar(select(Policy))
        assert policy.max_amount_wei == "1000" and policy.escalation_threshold_wei == "50"
    for path in ("/quarantine/resume", "/approvals/task/decision"):
        response = await client.post(
            "/api/v1/autonomy" + path,
            headers={"X-API-Key": get_settings().api_key},
            json={"decision": "APPROVE"},
        )
        assert response.status_code == 403
    with pytest.raises(HumanRequiredError, match="EXISTING_POLICY_LIMITS"):
        await adapter.configure(RECIPIENT, 1001, 50)


@pytest.mark.asyncio
async def test_evaluation_never_runs_legacy_autopay_before_budget_reservation(durable, monkeypatch):
    engine, adapter, factory = durable
    task_id = await new_task(engine)
    calls = []

    async def forbidden_sign(*args, **kwargs):
        calls.append("sign")
        raise AssertionError("Evaluation must not execute a durable task")

    async def stop_before_sign(_):
        raise HumanRequiredError("PREFLIGHT_FIXTURE_STOP")

    monkeypatch.setattr("app.api.routes.proposals.execute_payment", forbidden_sign)
    monkeypatch.setattr(adapter, "limits", stop_before_sign)
    with pytest.raises(HumanRequiredError, match="PREFLIGHT_FIXTURE_STOP"):
        await adapter.payment(engine.get(task_id))
    assert calls == []
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(AutonomousIntent)) == 0
        proposal = await session.scalar(select(Proposal))
        assert proposal.status == "ALLOWED"
        draft = await session.get(AssistantPaymentDraft, task_id)
        assert draft.proposal_id == proposal.id
    with engine.db() as db:
        assert db.execute("SELECT count(*) FROM fee_claims").fetchone()[0] == 0


@pytest.mark.asyncio
async def test_saved_vendor_binding_is_enforced_by_existing_core(durable):
    from app.services.vendor_payments import validate_vendor_authority

    engine, adapter, factory = durable
    task_id = await new_task(engine)
    task = engine.get(task_id)
    created = await adapter.call(
        "POST",
        "/proposals",
        data={
            "prompt": f"Send 10 wei to {RECIPIENT}",
            "recipient": RECIPIENT,
            "amount_wei": "10",
            "chain_id": 11155111,
        },
        correlation="goal-" + task_id,
    )
    await adapter.proposal_ready(task, created["id"])
    async with factory() as session:
        vendor = await session.get(Vendor, "vendor")
        vendor.active = False
        await session.commit()
    async with factory() as session:
        with pytest.raises(SigningRejectedError, match="vendor changed"):
            await validate_vendor_authority(
                session,
                NormalizedAction(
                    proposal_id=created["id"],
                    correlation_id="goal-" + task_id,
                    recipient=RECIPIENT,
                    amount_wei=10,
                    chain_id=11155111,
                ),
            )
    with pytest.raises(HumanRequiredError):
        await adapter.payment_guard(task)


@pytest.mark.asyncio
async def test_main_policy_escalation_pauses_only_its_task(durable, monkeypatch, client):
    engine, adapter, _ = durable
    waiting = await new_task(engine, 60, "main_waiting_fixture")
    other = await new_task(engine, 10, "main_other_fixture")

    async def rpc(method, params):
        return "0xaa36a7" if method == "eth_chainId" else hex(10**18)

    monkeypatch.setattr(adapter, "rpc", rpc)
    for task_id in (waiting, other):
        await engine.tick(task_id, adapter)
        await engine.tick(task_id, adapter)
    await engine.tick(waiting, adapter)
    assert engine.get(waiting)["state"] == "WAITING_APPROVAL"
    assert engine.get(other)["state"] == "READY"
    assert engine.get(other)["steps"][0]["state"] == "COMPLETED"
    assert engine.get(other)["steps"][1]["state"] == "COMPLETED"
    # A real human role decision resumes this same task; stop before signing.
    response = await client.post(
        f"/api/v1/autonomy/approvals/{waiting}/decision",
        headers={"X-API-Key": get_settings().approver_api_key},
        json={"decision": "APPROVE"},
    )
    assert response.status_code == 200

    async def stop_before_sign(_):
        raise HumanRequiredError("PREFLIGHT_FIXTURE_STOP")

    monkeypatch.setattr(adapter, "limits", stop_before_sign)
    await engine.tick(waiting, adapter)
    assert engine.get(waiting)["reason"] == "PREFLIGHT_FIXTURE_STOP"
    assert engine.get(other)["state"] == "READY"


@pytest.mark.asyncio
async def test_main_fee_claims_reserve_preflight_amount_and_survive_restart(durable):
    from demo_autonomy.main_wallet import MainWorkflowEngine

    engine, _, _ = durable
    with engine.db() as db:
        db.execute(
            "INSERT INTO chain_links VALUES(?,?,0)",
            ("one", json.dumps({"max_total_cost_wei": "110"})),
        )
        db.execute(
            "INSERT INTO chain_links VALUES(?,?,0)",
            ("two", json.dumps({"max_total_cost_wei": "100010"})),
        )
    engine.reserve_fee({"id": "one", "amount": 10})
    restarted = MainWorkflowEngine(engine.settings, engine.authority)
    restarted.initialize()
    restarted.reserve_fee({"id": "one", "amount": 10})
    with pytest.raises(HumanRequiredError, match="SESSION_FEE_BUDGET"):
        restarted.reserve_fee({"id": "two", "amount": 10})
    with restarted.db() as db:
        assert db.execute("SELECT sum(amount) FROM fee_claims").fetchone()[0] == 100


@pytest.mark.asyncio
async def test_exact_eth_goal_and_profile_cannot_expand_existing_authority(durable, monkeypatch):
    engine, _, _ = durable
    task_id = engine.create(
        "Fund my wallet if needed, then pay 0.00000000000000001 ETH to supplier Acme and verify.",
        "exact_eth_fixture",
    )
    assert engine.get(task_id)["amount"] == 10
    monkeypatch.setattr(get_settings(), "autonomy_payment_budget_wei", 10**15)
    with pytest.raises(ValueError, match="existing automatic payment limit"):
        MainAuthority.from_settings(get_settings())


@pytest.mark.asyncio
async def test_main_preflight_headroom_stays_inside_existing_gas_limits(durable, monkeypatch):
    engine, adapter, _ = durable
    task_id = await new_task(engine)
    adapter.link(task_id)
    adapter.save(task_id, "proposal_id", "fixture-proposal")
    envelope = {"gas": 25200, "maxFeePerGas": 34, "maxPriorityFeePerGas": 1, "nonce": 0}

    async def prepare(*args):
        from web3 import Web3

        assert args[-1].recipient == Web3.to_checksum_address(RECIPIENT)
        return envelope

    async def balance():
        return 10**18

    monkeypatch.setattr("app.services.blockchain.BlockchainService.prepare_transaction", prepare)
    monkeypatch.setattr(adapter, "balance", balance)
    limits = await adapter.limits(engine.get(task_id))
    assert limits["max_gas_units"] == 30240
    assert limits["max_fee_per_gas_wei"] == 68
    assert int(limits["max_total_cost_wei"]) == 10 + 30240 * 68
    envelope.update(
        gas=adapter.authority.max_gas_units,
        maxFeePerGas=adapter.authority.max_fee_per_gas_wei,
        maxPriorityFeePerGas=adapter.authority.max_priority_fee_per_gas_wei,
    )
    limits = await adapter.limits(engine.get(task_id))
    assert limits["max_gas_units"] == adapter.authority.max_gas_units
    assert limits["max_fee_per_gas_wei"] == adapter.authority.max_fee_per_gas_wei


async def retryable_proposal(engine, adapter):
    task_id = await new_task(engine)
    answer = await adapter.call(
        "POST",
        "/proposals",
        data={
            "prompt": f"Send 10 wei to {RECIPIENT}",
            "recipient": RECIPIENT,
            "amount_wei": "10",
            "chain_id": 11155111,
        },
        correlation="goal-" + task_id,
    )
    proposal = answer["id"]
    adapter.link(task_id)
    adapter.save(task_id, "proposal_id", proposal)
    await adapter.proposal_ready(engine.get(task_id), proposal)
    await adapter.call("POST", f"/proposals/{proposal}/evaluate")
    engine.hold(task_id, "PREFLIGHT_UNAVAILABLE")
    return task_id, proposal


@pytest.mark.asyncio
async def test_only_admin_can_retry_same_proposal_with_proven_no_execution(durable, client):
    engine, adapter, factory = durable
    task_id, proposal = await retryable_proposal(engine, adapter)
    path = f"/api/v1/autonomy/goals/{task_id}/resume-before-signing"
    for key in (get_settings().api_key, get_settings().approver_api_key):
        assert (await client.post(path, headers={"X-API-Key": key})).status_code == 403
    response = await client.post(path, headers={"X-API-Key": get_settings().policy_admin_api_key})
    assert response.status_code == 200 and response.json()["proposal_id"] == proposal
    assert engine.get(task_id)["state"] == "READY"
    assert engine.get(task_id)["payment_cap"] == 1000
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(Proposal)) == 1
    assert adapter.link(task_id)["proposal_id"] == proposal


@pytest.mark.asyncio
async def test_admin_retry_never_clears_a_sign_started_marker(durable, client):
    engine, adapter, _ = durable
    task_id, _ = await retryable_proposal(engine, adapter)
    with engine.db() as db:
        db.execute("INSERT INTO chain_links VALUES(?,?,1)", (task_id, "{}"))
    response = await client.post(
        f"/api/v1/autonomy/goals/{task_id}/resume-before-signing",
        headers={"X-API-Key": get_settings().policy_admin_api_key},
    )
    assert (
        response.status_code == 409
        and response.json()["detail"] == "SIGNED_OUTCOME_RECONCILE_REQUIRED"
    )
    assert engine.get(task_id)["state"] == "HUMAN_REQUIRED"
    with engine.db() as db:
        assert db.execute("SELECT sign_started FROM chain_links").fetchone()[0] == 1
