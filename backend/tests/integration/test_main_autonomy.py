"""Main assistant goal delegation keeps proposer authority and durable replay semantics."""

from types import SimpleNamespace

import pytest

from app.core.config import get_settings
from demo_autonomy.engine import Settings
from demo_autonomy.workflows import WorkflowEngine


@pytest.mark.asyncio
async def test_main_assistant_creates_one_task_for_replayed_goal(
    auth_client, app, monkeypatch, tmp_path
):
    engine = WorkflowEngine(Settings(tmp_path, enabled=True, workflows_enabled=True))
    engine.initialize()
    engine.configure("Acme", "0x" + "1" * 40, 100, 100)
    app.state.autonomy_app = SimpleNamespace(state=SimpleNamespace(engine=engine))
    monkeypatch.setattr(get_settings(), "autonomy_enabled", True)
    payload = {"prompt": "Fund my wallet if needed, then pay 10 wei to supplier Acme and verify."}
    first = await auth_client.post("/api/v1/assistant/query", json=payload)
    assert first.status_code == 200
    assert first.json()["data"]["kind"] == "autonomous_task"
    repeated = await auth_client.post("/api/v1/assistant/query", json=payload)
    assert repeated.status_code == 200
    assert repeated.json()["data"]["data"]["task_id"] == first.json()["data"]["data"]["task_id"]
    assert engine.get(first.json()["data"]["data"]["task_id"])["state"] == "PLANNING"
    with engine.db() as db:
        assert db.execute("SELECT count(*) FROM tasks").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM effects").fetchone()[0] == 0


@pytest.mark.asyncio
async def test_human_approver_cannot_start_an_autonomous_goal(client, app, monkeypatch, tmp_path):
    engine = WorkflowEngine(Settings(tmp_path, enabled=True, workflows_enabled=True))
    engine.initialize()
    engine.configure("Acme", "0x" + "1" * 40, 100, 100)
    app.state.autonomy_app = SimpleNamespace(state=SimpleNamespace(engine=engine))
    monkeypatch.setattr(get_settings(), "autonomy_enabled", True)
    result = await client.post(
        "/api/v1/assistant/query",
        headers={"X-API-Key": get_settings().approver_api_key},
        json={"prompt": "fund if needed, pay supplier Acme 10 wei, verify"},
    )
    assert result.status_code == 403
    with engine.db() as db:
        assert db.execute("SELECT count(*) FROM tasks").fetchone()[0] == 0
