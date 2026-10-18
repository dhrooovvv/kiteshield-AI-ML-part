"""Integration tests for persisted audit checkpoint endpoints."""

import os

import pytest


@pytest.mark.asyncio
async def test_checkpoint_endpoint_creates_and_retrieves_checkpoint(auth_client):
    await auth_client.post(
        "/api/v1/policies",
        headers={"X-API-Key": "test-policy-admin-key-only"},
        json={
            "max_amount_wei": "1000000000000000000",
            "allowed_recipients": ["0x742d35Cc6634C0532925a3b844Bc9e7595f2bD1e"],
        },
    )
    proposal = await auth_client.post(
        "/api/v1/proposals",
        json={
            "prompt": "Send 0.01 ETH",
            "recipient": "0x742d35Cc6634C0532925a3b844Bc9e7595f2bD1e",
            "amount_wei": "10000000000000000",
            "chain_id": 11155111,
        },
    )
    proposal_id = proposal.json()["data"]["id"]
    await auth_client.post(f"/api/v1/proposals/{proposal_id}/evaluate")

    created = await auth_client.post("/api/v1/audit/checkpoints", json={})
    assert created.status_code == 200
    checkpoint = created.json()["data"]
    assert checkpoint["event_count"] >= 2
    assert len(checkpoint["merkle_root"]) == 64

    retrieved = await auth_client.get(f"/api/v1/audit/checkpoints/{checkpoint['id']}")
    assert retrieved.status_code == 200
    assert retrieved.json()["data"] == checkpoint

    proof_response = await auth_client.get(
        f"/api/v1/audit/checkpoints/{checkpoint['id']}/proofs/{checkpoint['first_event_id']}"
    )
    assert proof_response.status_code == 200
    proof = proof_response.json()["data"]
    assert proof["event_id"] == checkpoint["first_event_id"]

    verified = await auth_client.post(
        f"/api/v1/audit/checkpoints/{checkpoint['id']}/proofs/verify",
        json={
            "event_id": proof["event_id"],
            "index": proof["index"],
            "leaf_hash": proof["leaf_hash"],
            "proof": proof["proof"],
        },
    )
    assert verified.status_code == 200
    assert verified.json()["data"]["valid"] is True

    tampered = dict(proof)
    tampered["leaf_hash"] = "0" * 64
    invalid = await auth_client.post(
        f"/api/v1/audit/checkpoints/{checkpoint['id']}/proofs/verify",
        json={
            "event_id": tampered["event_id"],
            "index": tampered["index"],
            "leaf_hash": tampered["leaf_hash"],
            "proof": tampered["proof"],
        },
    )
    assert invalid.status_code == 422


@pytest.mark.asyncio
async def test_empty_checkpoint_is_explicit(auth_client):
    created = await auth_client.post("/api/v1/audit/checkpoints", json={})
    assert created.status_code == 200
    data = created.json()["data"]
    assert data["event_count"] == 0
    assert data["first_event_id"] is None
    assert data["last_event_id"] is None

    proof = await auth_client.get(f"/api/v1/audit/checkpoints/{data['id']}/proofs/missing")
    assert proof.status_code == 422


@pytest.mark.asyncio
async def test_checkpoint_endpoints_require_api_auth(client):
    response = await client.post("/api/v1/audit/checkpoints", json={})
    assert response.status_code == 401

    response = await client.get(
        "/api/v1/audit/checkpoints/missing",
        headers={"X-API-Key": os.environ["API_KEY"]},
    )
    assert response.status_code == 404
