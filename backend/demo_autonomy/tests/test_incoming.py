"""Synthetic logs and isolated task journals; no RPC or wallet activity."""

import pytest

from demo_autonomy.engine import Settings
from demo_autonomy.incoming import APPROVAL_ALL, TRANSFER, IncomingWatcher
from demo_autonomy.workflows import WorkflowEngine


@pytest.fixture
def observer(tmp_path):
    engine = WorkflowEngine(Settings(tmp_path, enabled=True, quarantine_enabled=True))
    engine.initialize()
    state = {"head": 100, "logs": [], "calls": []}

    async def rpc(method, params):
        state["calls"].append((method, params))
        if method == "eth_chainId":
            return "0xaa36a7"
        if method == "eth_blockNumber":
            return hex(state["head"])
        return state["logs"] if len(params[0]["topics"]) == 3 else []

    watcher = IncomingWatcher(engine, rpc, "0x" + "1" * 40)
    watcher.initialize()
    return watcher, state


def log(watcher, kind=TRANSFER):
    return {
        "address": "0x" + "2" * 40,
        "topics": [kind, "0x" + "0" * 64, watcher.wallet_topic],
        "transactionHash": "0x" + "a" * 64,
        "blockHash": "0x" + "b" * 64,
        "blockNumber": hex(95),
        "logIndex": "0x0",
        "removed": False,
    }


@pytest.mark.asyncio
async def test_incoming_starts_at_confirmed_head_without_replaying_history(observer):
    watcher, state = observer
    await watcher.tick()
    assert watcher.status()["block"] == 94
    assert not any(method == "eth_getLogs" for method, _ in state["calls"])


@pytest.mark.asyncio
async def test_incoming_tokens_are_deduplicated_data_not_authority(observer):
    watcher, state = observer
    await watcher.tick()
    state.update(head=102, logs=[log(watcher)])
    await watcher.tick()
    assert not watcher.engine.control()["quarantined"]
    with watcher.engine.db() as db:
        assert db.execute("SELECT count(*) FROM incoming_events").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM mandates").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM tasks").fetchone()[0] == 0
        db.execute("UPDATE incoming_cursor SET block=94")
    await watcher.tick()
    with watcher.engine.db() as db:
        assert db.execute("SELECT count(*) FROM incoming_events").fetchone()[0] == 1


@pytest.mark.asyncio
async def test_unexpected_onchain_permission_claim_quarantines(observer):
    watcher, state = observer
    await watcher.tick()
    state.update(head=102, logs=[log(watcher, APPROVAL_ALL)])
    await watcher.tick()
    assert watcher.engine.control()["quarantined"]
    with watcher.engine.db() as db:
        assert (
            db.execute("SELECT reason FROM issues").fetchone()[0]
            == "UNTRUSTED_ONCHAIN_PERMISSION_EVENT"
        )
        assert db.execute("SELECT count(*) FROM mandates").fetchone()[0] == 0


@pytest.mark.asyncio
async def test_observer_has_bounded_failures_and_only_admin_resume_retries(observer):
    watcher, state = observer
    for _ in range(3):
        watcher.failure()
    before = len(state["calls"])
    await watcher.tick()
    assert len(state["calls"]) == before
    watcher.engine.resume()  # Administrator endpoint is the only runtime caller.
    await watcher.tick()
    assert len(state["calls"]) > before and watcher.status()["failures"] == 0


@pytest.mark.asyncio
async def test_malformed_or_removed_logs_do_not_advance_the_cursor(observer):
    watcher, state = observer
    await watcher.tick()
    bad = log(watcher)
    bad["removed"] = True
    state.update(head=102, logs=[bad])
    with pytest.raises(ValueError):
        await watcher.tick()
    assert watcher.status()["block"] == 94


@pytest.mark.asyncio
async def test_event_flood_is_bounded_without_cursor_skip(observer):
    watcher, state = observer
    await watcher.tick()
    state.update(head=102, logs=[log(watcher)] * 201)
    with pytest.raises(ValueError, match="limit"):
        await watcher.tick()
    assert watcher.status()["block"] == 94
