"""API authorization and audit tests for emergency-stop administration."""

import os
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.api.routes import security as security_routes
from app.exceptions import EmergencyStopUnavailableError
from app.models import AuditEvent, ExecutionControl


@pytest.mark.asyncio
async def test_kill_switch_requires_dedicated_admin_key(client):
    body = {"active": True, "reason": "security incident"}

    missing = await client.post("/api/v1/security/kill-switch", json=body)
    assert missing.status_code == 401

    invalid = await client.post(
        "/api/v1/security/kill-switch",
        json=body,
        headers={"X-Emergency-Stop-Admin-Key": "wrong-admin-key"},
    )
    assert invalid.status_code == 403


@pytest.mark.asyncio
async def test_activation_deactivation_and_audit(client, test_session):
    admin_headers = {"X-Emergency-Stop-Admin-Key": os.environ["EMERGENCY_STOP_ADMIN_API_KEY"]}

    activated = await client.post(
        "/api/v1/security/kill-switch",
        json={"active": True, "reason": "security incident"},
        headers=admin_headers,
    )
    assert activated.status_code == 200
    assert activated.json()["data"]["active"] is True

    observed = await client.get(
        "/api/v1/security/kill-switch",
        headers={"X-API-Key": os.environ["API_KEY"]},
    )
    assert observed.status_code == 200
    assert observed.json()["data"]["active"] is True

    deactivated = await client.post(
        "/api/v1/security/kill-switch",
        json={"active": False, "reason": "incident resolved"},
        headers=admin_headers,
    )
    assert deactivated.status_code == 200
    assert deactivated.json()["data"]["active"] is False

    events = (await test_session.execute(select(AuditEvent))).scalars().all()
    assert [event.event_type for event in events] == [
        "EMERGENCY_STOP_ACTIVATED",
        "EMERGENCY_STOP_DEACTIVATED",
    ]
    assert all("admin-key" not in event.details for event in events)


@pytest.mark.asyncio
async def test_reason_containing_admin_credential_is_rejected(client, test_session):
    admin_key = os.environ["EMERGENCY_STOP_ADMIN_API_KEY"]
    response = await client.post(
        "/api/v1/security/kill-switch",
        json={"active": True, "reason": f"incident {admin_key}"},
        headers={"X-Emergency-Stop-Admin-Key": admin_key},
    )

    assert response.status_code == 422
    assert admin_key not in response.text
    state = await test_session.get(ExecutionControl, "global")
    assert state.reason == ""


@pytest.mark.asyncio
async def test_unavailable_state_returns_503_and_fails_closed(client, monkeypatch):
    monkeypatch.setattr(
        security_routes.emergency_stop_service,
        "read_state",
        AsyncMock(side_effect=EmergencyStopUnavailableError("state unavailable")),
    )
    response = await client.get(
        "/api/v1/security/kill-switch",
        headers={"X-API-Key": os.environ["API_KEY"]},
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "EMERGENCY_STOP_UNAVAILABLE"
