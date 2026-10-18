"""One-key simulation convenience never grants live or emergency authority."""

from unittest.mock import Mock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.config import Settings, get_settings
from app.models import AuditEvent, ExecutionAttempt
from app.services.blockchain import BlockchainService

DEMO = {"X-API-Key": "test-demo-admin-credential-only"}
ADDRESS = "0x229D5588641f2614e3F486c853D8BA0eC5FFe811"


@pytest.fixture
def demo_profile(monkeypatch):
    settings = get_settings()
    for name, value in {
        "demo_admin_api_key": DEMO["X-API-Key"],
        "app_env": "demo",
        "execution_mode": "simulated",
        "database_url": "sqlite+aiosqlite:///./kiteshield-demo.db",
    }.items():
        monkeypatch.setattr(settings, name, value)
    return settings


@pytest.mark.asyncio
async def test_demo_admin_policy_approval_and_simulated_execution(
    client, test_engine, demo_profile, monkeypatch
):
    rpc = Mock(side_effect=AssertionError("Demo must never call blockchain RPC"))
    monkeypatch.setattr(BlockchainService, "_get_w3", rpc)
    identity = await client.get("/api/v1/security/identity", headers=DEMO)
    assert identity.json()["data"] == {"role": "demo_admin"}
    policy = await client.post(
        "/api/v1/policies",
        headers=DEMO,
        json={
            "max_amount_wei": str(10**18),
            "daily_limit_wei": str(10**18),
            "escalation_threshold_wei": "1",
            "allowed_recipients": [ADDRESS],
        },
    )
    assert policy.status_code == 200, policy.text
    proposed = await client.post(
        "/api/v1/proposals/agent", headers=DEMO, json={"prompt": f"Send 0.00001 ETH to {ADDRESS}"}
    )
    assert proposed.status_code == 200
    pid = proposed.json()["data"]["id"]
    evaluated = await client.post(f"/api/v1/proposals/{pid}/evaluate", headers=DEMO)
    assert evaluated.json()["data"]["status"] == "ESCALATED"
    assert (await client.post(f"/api/v1/proposals/{pid}/sign", headers=DEMO)).status_code == 403
    aid = evaluated.json()["data"]["approval"]["id"]
    approved = await client.post(
        f"/api/v1/approvals/{aid}/decide", headers=DEMO, json={"decision": "APPROVE"}
    )
    assert approved.status_code == 200 and approved.json()["data"]["approved_by"] == "demo_admin"
    submitted = await client.post(f"/api/v1/proposals/{pid}/sign", headers=DEMO)
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["data"]["transaction"]["execution_outcome"] == "SIMULATED"
    assert DEMO["X-API-Key"] not in submitted.text
    rpc.assert_not_called()
    async with async_sessionmaker(test_engine)() as session:
        attempt = await session.scalar(
            select(ExecutionAttempt).where(ExecutionAttempt.proposal_id == pid)
        )
        assert attempt.execution_mode == "simulated"
        event = await session.scalar(
            select(AuditEvent).where(AuditEvent.event_type == "POLICY_CREATED")
        )
        assert event.actor == "demo_admin" and DEMO["X-API-Key"] not in event.details


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value",
    [
        ("execution_mode", "sepolia"),
        ("app_env", "development"),
        ("database_url", "sqlite+aiosqlite:///./kiteshield.db"),
        ("signer_private_key", "c" * 64),
    ],
)
async def test_demo_key_rejected_outside_isolated_profile(
    client, demo_profile, monkeypatch, field, value
):
    monkeypatch.setattr(demo_profile, field, value)
    for method, endpoint, body in [
        ("GET", "/api/v1/security/identity", None),
        ("POST", "/api/v1/policies", {"max_amount_wei": "1"}),
        ("POST", "/api/v1/approvals/any/decide", {"decision": "APPROVE"}),
        ("POST", "/api/v1/proposals/any/sign", None),
    ]:
        response = await client.request(method, endpoint, headers=DEMO, json=body)
        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "DEMO_ADMIN_SIMULATION_ONLY"
        assert DEMO["X-API-Key"] not in response.text


@pytest.mark.asyncio
async def test_demo_cannot_operate_emergency_stop_or_persist_credential(client, demo_profile):
    stop = await client.post(
        "/api/v1/security/kill-switch",
        headers={
            **DEMO,
            "X-Emergency-Stop-Admin-Key": DEMO["X-API-Key"],
        },
        json={"active": True, "reason": "demo"},
    )
    assert stop.status_code == 403
    prompt = await client.post(
        "/api/v1/proposals/agent",
        headers=DEMO,
        json={"prompt": f"Send 0.00001 ETH to {ADDRESS} {DEMO['X-API-Key']}"},
    )
    assert prompt.status_code == 422
    assert DEMO["X-API-Key"] not in prompt.text


@pytest.mark.parametrize(
    "changes",
    [
        {"execution_mode": "sepolia"},
        {"database_url": "sqlite+aiosqlite:///./kiteshield.db"},
        {"signer_private_key": "c" * 64},
        {"app_debug": True},
    ],
)
def test_demo_configuration_refuses_live_mode_database_or_owner_signer(demo_profile, changes):
    with pytest.raises(ValueError) as error:
        Settings(_env_file=None, **{**demo_profile.model_dump(), **changes})
    assert DEMO["X-API-Key"] not in str(error.value)


def test_demo_key_must_be_distinct(demo_profile):
    with pytest.raises(ValueError):
        Settings(
            _env_file=None,
            **{**demo_profile.model_dump(), "demo_admin_api_key": demo_profile.api_key},
        )


def test_demo_database_cannot_be_reused_by_a_live_profile(demo_profile):
    with pytest.raises(ValueError, match="demo database"):
        Settings(
            _env_file=None,
            **{**demo_profile.model_dump(), "app_env": "development", "execution_mode": "sepolia"},
        )
