"""Persisted vault task binding and restriction-only safety behavior."""

import pytest

from demo_autonomy.engine import Engine, Settings
from demo_autonomy.vault_safety import VaultSafety
from demo_autonomy.workflows import WorkflowEngine


def test_task_backend_is_frozen_and_historical_tasks_remain_native(tmp_path):
    class BoundEngine(Engine):
        context = {"backend": "NATIVE"}

        def context_for_new_task(self):
            return self.context

    engine = BoundEngine(Settings(tmp_path, enabled=True))
    engine.initialize()
    engine.configure("Acme", "0x" + "1" * 40, 1000, 1000)
    first = engine.create("fund if needed, pay supplier Acme 10 wei, verify", "native_task")
    engine.context = {"backend": "VAULT", "address": "0x" + "d" * 40, "epoch": 1, "revision": 2}
    second = engine.create("fund if needed, pay supplier Acme 10 wei, verify", "vault_task")
    assert engine.task_context(first)["backend"] == "NATIVE"
    assert engine.task_context(second)["epoch"] == 1
    engine.context = {**engine.context, "epoch": 2}
    assert engine.create("fund if needed, pay supplier Acme 10 wei, verify", "vault_task") == second
    assert engine.task_context(second)["epoch"] == 1
    with engine.db() as db:
        db.execute("DELETE FROM task_backend WHERE task_id=?", (first,))
    assert engine.get(first)["payment_backend"] == "NATIVE"


@pytest.mark.asyncio
async def test_quarantine_requests_only_one_pause_and_never_resumes(tmp_path):
    engine = WorkflowEngine(
        Settings(tmp_path, enabled=True, workflows_enabled=True, quarantine_enabled=True)
    )
    engine.initialize()
    calls = []

    async def call(method, path, **kwargs):
        calls.append((method, path, kwargs))
        if path == "/vault/status":
            return {"configured": True, "chain": {"paused": False}}
        if path == "/vault/pause":
            return {"id": "pause-op"}
        return {"status": "SUBMITTED"}

    safety = VaultSafety(engine, call)
    safety.initialize()
    await safety.tick()
    assert not calls
    engine.issue(None, "INJECTION_FLAGGED", anomaly=True)
    await safety.tick()
    await safety.tick()
    assert [path for _, path, _ in calls] == [
        "/vault/status",
        "/vault/pause",
        "/vault/operations/pause-op/execute",
    ]
    assert calls[1][2]["data"]["kind"] == "PAUSE"
    assert engine.control()["quarantined"]
    engine.resume()
    await safety.tick()
    assert len(calls) == 3


@pytest.mark.asyncio
async def test_pause_failure_preserves_quarantine_without_endless_retries(tmp_path):
    engine = WorkflowEngine(
        Settings(tmp_path, enabled=True, workflows_enabled=True, quarantine_enabled=True)
    )
    engine.initialize()
    engine.issue(None, "INJECTION_FLAGGED", anomaly=True)
    # Exercise repeated-block quarantine too: an issue must not grow its epoch.
    engine.issue(None, "BLOCKED")
    engine.issue(None, "BLOCKED")
    epoch = engine.control()["epoch"]
    calls = []

    async def call(*args, **kwargs):
        calls.append(args)
        raise RuntimeError("provider unavailable")

    safety = VaultSafety(engine, call)
    safety.initialize()
    await safety.tick()
    await safety.tick()
    assert len(calls) == 1 and engine.control()["epoch"] == epoch
    with engine.db() as db:
        issue = db.execute(
            "SELECT reason FROM issues WHERE reason='VAULT_PAUSE_REVIEW_REQUIRED'"
        ).fetchone()
    assert issue
