"""
KiteShield Wallet — Integration Tests: Policies API

Tests the policy creation, activation, versioning, and listing endpoints.
"""

import pytest


@pytest.mark.asyncio
async def test_policy_requires_auth(client):
    """Policies endpoint requires X-API-Key header."""
    res = await client.get("/api/v1/policies/active")
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_get_active_policy_empty(auth_client):
    """When no policy exists, returns 404."""
    res = await auth_client.get("/api/v1/policies/active")
    assert res.status_code == 404
    body = res.json()
    assert body["error"]["code"] == "NOT_FOUND"


@pytest.mark.asyncio
async def test_create_and_get_policy(auth_client):
    """Admin can create a policy and retrieve it as active."""
    payload = {
        "max_amount_wei": "1000000000000000000",  # 1 ETH
        "escalation_threshold_wei": "100000000000000000",  # 0.1 ETH
        "allowed_recipients": ["0x742d35Cc6634C0532925a3b844Bc9e7595f2bD1e"],
    }
    create_res = await auth_client.post("/api/v1/policies", json=payload)
    assert create_res.status_code == 200
    create_data = create_res.json()["data"]
    assert create_data["version"] == 1
    assert create_data["is_active"] is True
    assert create_data["max_amount_wei"] == "1000000000000000000"

    # Now get active
    active_res = await auth_client.get("/api/v1/policies/active")
    assert active_res.status_code == 200
    active_data = active_res.json()["data"]
    assert active_data["id"] == create_data["id"]
    assert active_data["version"] == 1


@pytest.mark.asyncio
async def test_update_policy_increments_version(auth_client):
    """Updating a policy creates a new version and deactivates the old."""
    payload = {
        "max_amount_wei": "500000000000000000",  # 0.5 ETH
    }
    create_res = await auth_client.post("/api/v1/policies", json=payload)
    policy_id = create_res.json()["data"]["id"]

    update_payload = {
        "max_amount_wei": "2000000000000000000",  # 2 ETH
    }
    update_res = await auth_client.put(f"/api/v1/policies/{policy_id}", json=update_payload)
    assert update_res.status_code == 200
    new_data = update_res.json()["data"]
    assert new_data["version"] == 2
    assert new_data["max_amount_wei"] == "2000000000000000000"
    assert new_data["is_active"] is True

    # Check active is version 2
    active_res = await auth_client.get("/api/v1/policies/active")
    assert active_res.json()["data"]["version"] == 2

    # List policies shows both versions
    list_res = await auth_client.get("/api/v1/policies")
    assert list_res.status_code == 200
    policies = list_res.json()["data"]
    assert len(policies) >= 2
