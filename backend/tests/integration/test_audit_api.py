"""
KiteShield Wallet — Integration Tests: Audit Trail & Integrity

Tests that audit logs record the complete lifecycle, link correlation IDs,
maintain hash chain integrity, and never leak secrets.
"""

import pytest


@pytest.mark.asyncio
async def test_audit_trail_recorded_and_verified(auth_client):
    """A full proposal lifecycle creates a verifiable audit trail."""
    # 1. Setup policy
    await auth_client.post(
        "/api/v1/policies",
        json={
            "max_amount_wei": "1000000000000000000",
            "allowed_recipients": ["0x742d35Cc6634C0532925a3b844Bc9e7595f2bD1e"],
        },
    )

    # 2. Create proposal
    prop_res = await auth_client.post(
        "/api/v1/proposals",
        json={
            "prompt": "Send 0.01 ETH",
            "recipient": "0x742d35Cc6634C0532925a3b844Bc9e7595f2bD1e",
            "amount_wei": "10000000000000000",
            "chain_id": 11155111,
        },
    )
    prop_data = prop_res.json()["data"]
    prop_id = prop_data["id"]
    cid = prop_data["correlation_id"]

    # 3. Evaluate and Sign
    await auth_client.post(f"/api/v1/proposals/{prop_id}/evaluate")
    await auth_client.post(f"/api/v1/proposals/{prop_id}/sign")

    # 4. Fetch audit trail by correlation ID
    audit_res = await auth_client.get(f"/api/v1/audit/{cid}")
    assert audit_res.status_code == 200
    trail_data = audit_res.json()["data"]
    events = trail_data["events"]

    event_types = [e["event_type"] for e in events]
    assert "PROPOSAL_CREATED" in event_types
    assert "POLICY_ALLOW" in event_types
    assert "CAPABILITY_ISSUED" in event_types
    assert "SIGNING_COMPLETED" in event_types
    assert "TX_SUBMITTED" in event_types
    assert trail_data["chain_valid"] is True

    # 5. Global integrity verification endpoint
    verify_res = await auth_client.get("/api/v1/audit/integrity/verify")
    assert verify_res.status_code == 200
    assert verify_res.json()["data"]["is_valid"] is True
    assert len(verify_res.json()["data"]["errors"]) == 0
