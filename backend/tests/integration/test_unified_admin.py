"""One human administrator is explicit opt-in; worker credentials stay restricted."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from app.core.config import get_settings
from app.core.security import require_approver, require_policy_admin, require_proposer
from demo_autonomy.engine import Settings
from demo_autonomy.server import create_demo


@pytest.mark.asyncio
async def test_unified_admin_identity_and_all_human_gates(client, monkeypatch):
    settings = get_settings()
    headers = {"X-API-Key": settings.policy_admin_api_key}
    before = await client.get("/api/v1/security/identity", headers=headers)
    assert before.json()["data"]["role"] == "policy_administrator"
    monkeypatch.setattr(settings, "unified_admin_enabled", True)
    identity = await client.get("/api/v1/security/identity", headers=headers)
    assert identity.json()["data"]["role"] == "administrator"
    for gate in (require_proposer, require_approver, require_policy_admin):
        assert await gate("administrator") == "administrator"
    stopped = await client.post(
        "/api/v1/security/kill-switch",
        headers=headers,
        json={"active": True, "reason": "operator review"},
    )
    assert stopped.status_code == 200
    assert stopped.json()["data"]["active"] is True
    monkeypatch.setattr(settings, "unified_admin_enabled", False)
    for gate in (require_proposer, require_approver, require_policy_admin):
        with pytest.raises(Exception) as error:
            await gate("administrator")
        assert error.value.status_code == 403


@pytest.mark.asyncio
async def test_worker_cannot_approve_or_stop_with_unified_admin_enabled(client, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "unified_admin_enabled", True)
    headers = {"X-API-Key": settings.api_key}
    identity = await client.get("/api/v1/security/identity", headers=headers)
    assert identity.json()["data"]["role"] == "proposer"
    denied = await client.post(
        "/api/v1/approvals/missing/decide", headers=headers, json={"decision": "APPROVE"}
    )
    assert denied.status_code == 403
    stopped = await client.post(
        "/api/v1/security/kill-switch",
        headers=headers,
        json={"active": True, "reason": "operator review"},
    )
    assert stopped.status_code == 401


@pytest.mark.asyncio
async def test_admin_credential_cannot_be_recorded_in_incident_reason(client, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "unified_admin_enabled", True)
    key = settings.policy_admin_api_key
    result = await client.post(
        "/api/v1/security/kill-switch",
        headers={"X-API-Key": key},
        json={"active": True, "reason": "incident " + key},
    )
    assert result.status_code == 422
    assert key not in result.text


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [False, True])
async def test_child_api_accepts_admin_for_purchase_only_when_opted_in(tmp_path, enabled):
    settings = Settings(
        tmp_path, enabled=True, commerce_enabled=True, unified_admin_enabled=enabled
    )
    app = create_demo(settings, "a" * 32, "b" * 32)
    engine = app.state.engine
    engine.initialize()
    from demo_autonomy.commerce import Commerce

    Commerce(engine).initialize()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        result = await client.get(
            "/commerce/catalog", headers={"Authorization": "Bearer " + "a" * 32}
        )
        assert result.status_code == (200 if enabled else 403)


@pytest.mark.asyncio
async def test_admin_can_retrieve_legacy_funding_without_new_side_effect(monkeypatch):
    from app.services import funding

    settings = get_settings()
    monkeypatch.setattr(settings, "unified_admin_enabled", True)
    row = SimpleNamespace(actor="proposer", state="REQUESTING")
    session = SimpleNamespace(get=AsyncMock(return_value=row))
    monkeypatch.setattr(funding, "lock_execution", AsyncMock())
    monkeypatch.setattr(funding, "public", lambda value: {"state": value.state})
    assert await funding.submit(session, "legacy", "administrator") == {"state": "REQUESTING"}
    monkeypatch.setattr(settings, "unified_admin_enabled", False)
    with pytest.raises(Exception) as error:
        await funding.submit(session, "legacy", "administrator")
    assert error.value.status_code == 403


@pytest.mark.asyncio
async def test_admin_can_cancel_legacy_invoice_task(monkeypatch):
    from app.services import invoice_agent

    settings = get_settings()
    monkeypatch.setattr(settings, "unified_admin_enabled", True)
    row = SimpleNamespace(actor="proposer", state="CANCELLED")
    session = SimpleNamespace(get=AsyncMock(return_value=row))
    monkeypatch.setattr(invoice_agent, "lock_execution", AsyncMock())
    monkeypatch.setattr(invoice_agent, "task_data", AsyncMock(return_value={"state": "CANCELLED"}))
    assert await invoice_agent.cancel_task(session, "legacy", "administrator") == {
        "state": "CANCELLED"
    }
    monkeypatch.setattr(settings, "unified_admin_enabled", False)
    with pytest.raises(Exception) as error:
        await invoice_agent.cancel_task(session, "legacy", "administrator")
    assert error.value.status_code == 403
