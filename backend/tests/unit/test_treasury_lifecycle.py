import asyncio

import pytest

from app.core.config import get_settings
from app.services import treasury


@pytest.mark.asyncio
async def test_monitor_cancels_and_awaits_cleanly(monkeypatch):
    reached = asyncio.Event()
    calls = []

    async def tick(factory):
        calls.append(factory)
        reached.set()

    async def reconcile(factory):
        pass

    monkeypatch.setattr(treasury, "tick", tick)
    monkeypatch.setattr(treasury, "reconcile_outstanding", reconcile)
    task = asyncio.create_task(treasury.monitor("isolated-factory"))
    await asyncio.wait_for(reached.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert calls == ["isolated-factory"]


def test_monitor_safe_defaults_and_interval_bounds():
    from pydantic import ValidationError

    from app.core.config import Settings

    assert get_settings().treasury_monitor_enabled is False
    with pytest.raises(ValidationError):
        Settings(treasury_monitor_interval_seconds=1)


@pytest.mark.asyncio
async def test_lifespan_starts_only_opt_in_monitor_and_awaits_shutdown(monkeypatch):
    from app import db, main

    reached, stopped = asyncio.Event(), asyncio.Event()

    async def noop(*args):
        return None

    async def fake_monitor(factory):
        reached.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    monkeypatch.setattr(main, "init_db", noop)
    monkeypatch.setattr(main, "verify_live_rpc", noop)
    monkeypatch.setattr(db, "get_session_factory", lambda: "isolated-factory")
    monkeypatch.setattr(treasury, "monitor", fake_monitor)
    async with main.lifespan(main.create_app()):
        await asyncio.sleep(0)
        assert not reached.is_set()
    monkeypatch.setattr(get_settings(), "treasury_monitor_enabled", True)
    async with main.lifespan(main.create_app()):
        await asyncio.wait_for(reached.wait(), 1)
    assert stopped.is_set()


@pytest.mark.asyncio
async def test_local_read_only_fixture_supports_real_observer(test_engine, monkeypatch):
    import threading
    from http.server import HTTPServer

    from sqlalchemy.ext.asyncio import async_sessionmaker

    from scripts.treasury_demo_rpc import Handler, answer

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(get_settings(), "sepolia_rpc_url", f"http://127.0.0.1:{server.server_port}")
    config = {
        "sender": treasury.sender_address(),
        "recipient": "0x" + "11" * 20,
        "target_balance_wei": "49000000000000000",
        "sweep_maximum_wei": "30000000000000",
    }
    try:
        observation = await treasury.observe(config, async_sessionmaker(test_engine))
        assert observation["status"] == "available"
        assert observation["balance_wei"] == "50000000000000000"
        assert observation["simulation"] is True
        assert observation["fee_quote"]["value"] == "30000000000000"
        for method in ["eth_sendRawTransaction", "eth_sendTransaction", "eth_sign"]:
            with pytest.raises(ValueError):
                answer(method, [])
    finally:
        await asyncio.to_thread(server.shutdown)
        server.server_close()
        thread.join(timeout=1)
