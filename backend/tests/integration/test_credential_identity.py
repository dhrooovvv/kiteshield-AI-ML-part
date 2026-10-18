"""Authenticated role introspection never grants or reveals credentials."""

import pytest

from app.core.config import get_settings


@pytest.mark.asyncio
@pytest.mark.parametrize(("key_setting", "role"), [
    ("api_key", "proposer"), ("approver_api_key", "human_approver"),
    ("policy_admin_api_key", "policy_administrator"),
])
async def test_identity_is_derived_from_the_backend_credential(client, key_setting, role):
    key = getattr(get_settings(), key_setting)
    response = await client.get("/api/v1/security/identity",
                                headers={"X-API-Key": key, "X-Role": "policy_administrator"})
    assert response.status_code == 200
    assert response.json()["data"] == {"role": role}
    assert key not in response.text


@pytest.mark.asyncio
async def test_missing_invalid_and_emergency_credentials_have_no_application_role(client):
    missing = await client.get("/api/v1/security/identity")
    assert missing.status_code == 401
    for key in ("invalid", get_settings().emergency_stop_admin_api_key):
        response = await client.get("/api/v1/security/identity", headers={"X-API-Key": key})
        assert response.status_code == 401
        assert "role" not in response.json().get("data", {})
