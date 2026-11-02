"""Mocked evidence tests only: these tests never sign, broadcast or contact a faucet."""

import json

import pytest
from pydantic import ValidationError

from demo_autonomy.engine import HumanRequiredError, Settings
from demo_autonomy.sandbox import WaitingError
from demo_autonomy.sepolia import SepoliaAdapter, SepoliaWorkflowEngine
from demo_autonomy.sepolia_profile import Authority, prepare, read_private

RECIPIENT = "0x" + "1" * 40
SENDER = "0x" + "2" * 40
TX = "0x" + "a" * 64
BLOCK = "0x" + "b" * 64


def authority(**kw):
    return Authority(
        **(
            {
                "payments_enabled": True,
                "recipient": RECIPIENT,
                "payment_budget_wei": 100,
                "max_payment_fee_wei": 25200,
                "session_fee_budget_wei": 25200,
                "max_fee_per_gas_wei": 1,
                "funding_budget_wei": 100,
                "max_priority_fee_per_gas_wei": 1,
            }
            | kw
        )
    )


@pytest.fixture
def engine(tmp_path):
    result = SepoliaWorkflowEngine(
        Settings(tmp_path, enabled=True, mode="SEPOLIA", quarantine_enabled=True, lease_seconds=0),
        authority(),
    )
    result.initialize()
    result.configure("Acme", RECIPIENT, 100, 100)
    return result


@pytest.fixture
def adapter(engine):
    # Avoid importing or constructing the core app (and any wallet) in unit tests.
    a = object.__new__(SepoliaAdapter)
    a.engine, a.authority, a.address = engine, engine.authority, SENDER
    with engine.db() as db:
        db.executescript("""
            CREATE TABLE wallet_links (task_id TEXT PRIMARY KEY, proposal_id TEXT,
              funding_id TEXT, payment_started INTEGER DEFAULT 0,
              funding_started INTEGER DEFAULT 0);
            CREATE TABLE chain_links (task_id TEXT PRIMARY KEY, limits_json TEXT NOT NULL,
              sign_started INTEGER NOT NULL DEFAULT 0);
        """)
    a.limits_fixture = {
        "sender": SENDER,
        "recipient": RECIPIENT,
        "amount_wei": "10",
        "nonce": 0,
        "max_gas_units": 25200,
        "max_fee_per_gas_wei": 1,
        "max_priority_fee_per_gas_wei": 1,
        "max_total_cost_wei": "25210",
    }
    a.chain = {
        "eth_chainId": "0xaa36a7",
        "eth_getBalance": hex(30000),
        "eth_getTransactionByHash": {
            "hash": TX,
            "from": SENDER,
            "to": RECIPIENT,
            "value": "0xa",
            "input": "0x",
            "chainId": "0xaa36a7",
            "nonce": "0x0",
            "gas": hex(25200),
            "maxFeePerGas": "0x1",
            "maxPriorityFeePerGas": "0x1",
            "blockHash": BLOCK,
            "blockNumber": "0x64",
        },
        "eth_getTransactionReceipt": {
            "transactionHash": TX,
            "blockHash": BLOCK,
            "blockNumber": "0x64",
            "status": "0x1",
            "gasUsed": hex(21000),
            "effectiveGasPrice": "0x1",
        },
        "eth_getBlockByNumber": {"hash": BLOCK},
    }

    async def rpc(method, _):
        return a.chain[method]

    a.rpc = rpc
    return a


def test_default_authority_off_and_private_profile_survives_preparation(tmp_path):
    path = tmp_path / "kiteshield-sepolia-test"
    metadata = prepare(path, "https://rpc.sepolia.org")
    assert not metadata["payments_enabled"] and not metadata["faucet_enabled"]
    assert metadata["address"] == read_private(path / "wallet.json")["address"]
    assert len(read_private(path / "credentials.json")["capability"]) == 64
    assert not list(path.glob("*.sqlite3"))
    (path / "wallet.json").chmod(0o644)
    with pytest.raises(ValueError, match="private"):
        read_private(path / "wallet.json")


def test_no_implicit_authority_or_underbudget_faucet():
    with pytest.raises(ValidationError):
        Authority(payments_enabled=True)
    with pytest.raises(ValidationError):
        Authority(faucet_enabled=True, faucet_grant_ceiling_wei=100, funding_budget_wei=99)


def test_recipient_and_budget_cannot_exceed_frozen_profile(engine):
    with pytest.raises(HumanRequiredError):
        engine.configure("Acme", SENDER, 100, 100)
    with pytest.raises(HumanRequiredError):
        engine.configure("Acme", RECIPIENT, 101, 100)
    with pytest.raises(HumanRequiredError):
        engine.configure("Acme", RECIPIENT, 100, 101)


def test_funded_wallet_can_use_zero_funding_allowance(engine):
    engine.authority = authority(funding_budget_wei=0)
    engine.configure("Acme", RECIPIENT, 100, 0)
    task_id = engine.create("fund if needed, pay supplier Acme 10 wei, verify", "zero_funding_cap")
    assert engine.get(task_id)["funding_cap"] == 0


@pytest.mark.asyncio
async def test_disabled_profile_on_restart_revokes_old_tasks(engine):
    task_id = engine.create(
        "fund if needed, pay supplier Acme 10 wei, verify", "disable_on_restart"
    )

    async def planner(_):
        return {"steps": ["balance", "fund", "payment", "receipt"]}

    await engine.plan(task_id, planner)
    restarted = SepoliaWorkflowEngine(engine.settings, Authority())
    restarted.initialize()
    with pytest.raises(HumanRequiredError, match="PROFILE_ADMIN_LIMITS_REQUIRED"):
        restarted.allowed(restarted.get(task_id))


def test_fee_reservations_are_durable_idempotent_and_bounded(engine):
    engine.reserve_fee({"id": "one"})
    restarted = SepoliaWorkflowEngine(engine.settings, engine.authority)
    restarted.reserve_fee({"id": "one"})
    with pytest.raises(HumanRequiredError, match="FEE_BUDGET"):
        restarted.reserve_fee({"id": "two"})


@pytest.mark.asyncio
async def test_wrong_chain_is_never_a_balance(adapter):
    adapter.chain["eth_chainId"] = "0x1"
    with pytest.raises(HumanRequiredError, match="CHAIN_MISMATCH"):
        await adapter.balance()


@pytest.mark.asyncio
async def test_matching_mined_payment_and_pending_receipt(adapter):
    task = {"id": "task", "amount": 10}
    result = await adapter.verify_payment(task, TX, adapter.limits_fixture)
    assert result["verified"] and result["mode"] == "SEPOLIA"
    assert result["fee_paid_wei"] == "21000"
    adapter.chain["eth_getTransactionReceipt"] = None
    with pytest.raises(WaitingError, match="PENDING"):
        await adapter.verify_payment(task, TX, adapter.limits_fixture)


@pytest.mark.parametrize(
    "field,value",
    [
        ("to", SENDER),
        ("value", "0xb"),
        ("nonce", "0x1"),
        ("gas", hex(100000)),
        ("input", "0x1234"),
        ("chainId", "0x1"),
    ],
)
@pytest.mark.asyncio
async def test_mismatched_payment_quarantines(adapter, field, value):
    adapter.chain["eth_getTransactionByHash"][field] = value
    with pytest.raises(HumanRequiredError, match="EVIDENCE_MISMATCH"):
        await adapter.verify_payment({"id": "task", "amount": 10}, TX, adapter.limits_fixture)
    assert adapter.engine.control()["quarantined"]


@pytest.mark.asyncio
async def test_pending_transaction_mined_receipt_race_waits_without_quarantine(adapter):
    adapter.chain["eth_getTransactionByHash"]["blockHash"] = None
    adapter.chain["eth_getTransactionByHash"]["blockNumber"] = None
    with pytest.raises(WaitingError, match="BLOCK_EVIDENCE_PENDING"):
        await adapter.verify_payment({"id": "task", "amount": 10}, TX, adapter.limits_fixture)
    assert not adapter.engine.control()["quarantined"]


@pytest.mark.asyncio
async def test_read_only_reconciliation_is_idempotent_and_does_not_resume_quarantine(adapter):
    engine = adapter.engine
    task_id = engine.create(
        "fund if needed, pay supplier Acme 10 wei, verify", "saved_mined_fixture"
    )

    async def planner(_):
        return {"steps": ["balance", "fund", "payment", "receipt"]}

    await engine.plan(task_id, planner)
    adapter.link(task_id)
    adapter.save(task_id, "proposal_id", "proposal")
    with engine.db() as db:
        db.execute("UPDATE steps SET state='COMPLETED' WHERE task_id=? AND position<2", (task_id,))
        db.execute(
            "INSERT INTO chain_links VALUES(?,?,1)", (task_id, json.dumps(adapter.limits_fixture))
        )
    engine.hold(task_id, "CHAIN_EVIDENCE_MISMATCH")
    engine.issue(task_id, "CHAIN_EVIDENCE_MISMATCH", anomaly=True)
    calls = []

    async def call(method, path, **kwargs):
        assert method == "GET"
        calls.append(path)
        if path.startswith("/proposals/"):
            return {"transaction": {"id": "tx", "execution_mode": "sepolia", "tx_hash": TX}}
        return {"execution_outcome": "CONFIRMED"}

    adapter.call = call
    for _ in range(2):
        result = await adapter.reconcile_existing_payment(task_id)
        assert result["read_only_reconciliation"]
    assert engine.get(task_id)["state"] == "COMPLETED"
    assert engine.control()["quarantined"]
    with engine.db() as db:
        assert db.execute("SELECT balance FROM ledger").fetchone()[0] == -10
        assert db.execute("SELECT sign_started FROM chain_links").fetchone()[0] == 1
    assert calls == ["/proposals/proposal", "/transactions/tx"] * 2


@pytest.mark.asyncio
async def test_reverted_receipt_never_completes(adapter):
    adapter.chain["eth_getTransactionReceipt"]["status"] = "0x0"
    with pytest.raises(HumanRequiredError, match="REVERTED"):
        await adapter.verify_payment({"id": "task", "amount": 10}, TX, adapter.limits_fixture)


@pytest.mark.asyncio
async def test_unknown_signing_result_does_not_sign_again_after_restart(adapter):
    task = {"id": "task", "amount": 10}
    adapter.link("task")
    adapter.save("task", "proposal_id", "proposal")
    with adapter.engine.db() as db:
        db.execute(
            "INSERT INTO chain_links VALUES(?,?,1)", ("task", json.dumps(adapter.limits_fixture))
        )
    calls = []

    async def call(method, path, **kw):
        calls.append((method, path))
        return {"status": "ALLOWED", "transaction": None}

    adapter.call = call
    with pytest.raises(HumanRequiredError, match="UNRESOLVED_SIGNING"):
        await adapter.payment(task, reconcile=True)
    assert calls == [("GET", "/proposals/proposal")]


@pytest.mark.asyncio
async def test_receipt_step_does_not_debit_twice(adapter):
    async def call(*a, **kw):
        return {"is_valid": True}

    adapter.call = call
    with adapter.engine.db() as db:
        db.execute("INSERT INTO effects VALUES(?,?)", ("task:2", json.dumps({"tx_hash": TX})))
        db.execute(
            "INSERT INTO chain_links VALUES(?,?,1)", ("task", json.dumps(adapter.limits_fixture))
        )
    result = await adapter.run({"id": "task", "amount": 10}, "receipt", "task:3")
    assert result["tool"] == "receipt" and "paid_wei" not in result


@pytest.mark.asyncio
async def test_sufficient_real_balance_skips_faucet_and_never_credits_fake_funds(adapter):
    result = await adapter.engine.fund({"id": "task", "amount": 10}, "task:1", adapter, False)
    assert result["skipped"] and result["funded_wei"] == 0


@pytest.mark.asyncio
async def test_faucet_unavailable_stops_without_provider_call(adapter):
    adapter.chain["eth_getBalance"] = "0x0"
    with pytest.raises(HumanRequiredError, match="FAUCET_NOT_CONFIGURED"):
        await adapter.engine.fund({"id": "task", "amount": 10}, "task:1", adapter, False)


@pytest.mark.asyncio
async def test_whole_workflow_restarts_without_a_second_payment(adapter):
    engine = adapter.engine
    task_id = engine.create("fund if needed, pay supplier Acme 10 wei, verify", "real_path_fixture")

    async def planner(_):
        return {"steps": ["balance", "fund", "payment", "receipt"]}

    await engine.plan(task_id, planner)
    state = {"status": "PROPOSED", "transaction": None}
    calls = []

    async def find(_):
        return None

    async def limits(_):
        return adapter.limits_fixture

    async def call(method, path, **kwargs):
        calls.append((method, path))
        if path.startswith("/audit/"):
            return {"is_valid": True}
        if path == "/proposals":
            assert kwargs["data"]["amount_wei"] == "10"
            assert kwargs["data"]["recipient"] == RECIPIENT
            return {"id": "proposal"}
        if path.endswith("/evaluate"):
            state["status"] = "ALLOWED"
        if path.endswith("/sign"):
            state.update(
                status="SUBMITTED",
                transaction={"id": "tx", "execution_mode": "sepolia", "tx_hash": TX},
            )
            assert kwargs["data"] == adapter.limits_fixture
        return dict(state)

    adapter.find_proposal, adapter.limits, adapter.call = find, limits, call
    for _ in range(5):
        await engine.tick(task_id, adapter)
    task = engine.get(task_id)
    assert task["state"] == "COMPLETED"
    assert json.loads(task["steps"][1]["result"])["funded_wei"] == 0
    assert len([1 for _, path in calls if path.endswith("/sign")]) == 1
    restarted = SepoliaWorkflowEngine(engine.settings, engine.authority)
    restarted.initialize()
    adapter.engine = restarted
    await restarted.tick(task_id, adapter)
    assert len([1 for _, path in calls if path.endswith("/sign")]) == 1
    with restarted.db() as db:
        assert db.execute("SELECT balance FROM ledger").fetchone()[0] == -10


@pytest.mark.asyncio
async def test_faucet_receipt_records_actual_grant_not_reserved_ceiling(adapter):
    engine = adapter.engine
    engine.authority = adapter.authority = authority(
        faucet_enabled=True, faucet_grant_ceiling_wei=100, funding_budget_wei=100
    )
    task_id = engine.create("fund if needed, pay supplier Acme 10 wei, verify", "funding_fixture")

    async def planner(_):
        return {"steps": ["balance", "fund", "payment", "receipt"]}

    await engine.plan(task_id, planner)
    adapter.chain["eth_getBalance"] = "0x0"
    calls = []

    async def call(method, path, **kwargs):
        calls.append((method, path))
        if path.startswith("/audit/"):
            return {"is_valid": True}
        if path == "/funding/plan":
            return {"id": "funding"}
        return {
            "id": "funding",
            "state": "CONFIRMED",
            "mode": "sepolia",
            "amount_wei": "90",
            "tx_hash": TX,
            "explorer_url": "https://sepolia.etherscan.io/tx/" + TX,
        }

    adapter.call = call
    await engine.tick(task_id, adapter)
    await engine.tick(task_id, adapter)
    result = json.loads(engine.get(task_id)["steps"][1]["result"])
    assert result["funded_wei"] == 90
    with engine.db() as db:
        assert db.execute("SELECT balance FROM ledger").fetchone()[0] == 90
    assert calls.count(("POST", "/funding/funding/request")) == 1
