"""
KiteShield Wallet — Integration Tests: Proposals & End-to-End Lifecycle

Validates the full transaction proposal lifecycle:
- Agent prompt extraction
- Policy evaluation (ALLOW, ESCALATE, BLOCK)
- Human-in-the-loop escalation & approval
- Capability token issuance & signing
- Blockchain submission
"""

import pytest

from app.ai_ml import EnsembleScreenResult
from app.ai_ml.experimental_decision_policy import ExperimentalClassification
from app.ai_ml.schemas import InjectionLabel, InjectionScreenResult
from app.api.routes import proposals


async def benign_screening_result(_prompt):
    return EnsembleScreenResult(
        classification=ExperimentalClassification.BENIGN,
        reason_code="all_negative",
        rules=InjectionScreenResult(InjectionLabel.BENIGN, 0.5, ()),
        horizon_attack=False,
        horizon_score=0.01,
        bastion_attack=False,
        bastion_score=0.01,
        detector_versions=(("rules", "rules-v1"), ("horizon", "test"), ("bastion", "test")),
        latency_ms=0.1,
    )


@pytest.fixture
async def active_policy(auth_client):
    """Seed an active policy with 1 ETH max and 0.1 ETH escalation threshold."""
    payload = {
        "max_amount_wei": "1000000000000000000",  # 1 ETH max
        "escalation_threshold_wei": "100000000000000000",  # 0.1 ETH escalation
        "allowed_recipients": ["0x742d35Cc6634C0532925a3b844Bc9e7595f2bD1e"],
    }
    res = await auth_client.post(
        "/api/v1/policies", headers={"X-API-Key": "test-policy-admin-key-only"}, json=payload
    )
    return res.json()["data"]


@pytest.mark.asyncio
async def test_agent_propose_endpoint(auth_client, monkeypatch):
    """Natural language agent endpoint correctly extracts and creates proposal."""
    monkeypatch.setattr(proposals.screening_service, "screen", benign_screening_result)
    res = await auth_client.post(
        "/api/v1/proposals/agent",
        json={
            "prompt": "Transfer 0.05 eth to 0x742d35Cc6634C0532925a3b844Bc9e7595f2bD1e for bounty"
        },
    )
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["status"] == "PROPOSED"
    assert data["recipient"].lower() == "0x742d35cc6634c0532925a3b844bc9e7595f2bd1e"


@pytest.mark.asyncio
async def test_full_allow_lifecycle(auth_client, active_policy):
    """Proposal under escalation threshold is ALLOWED and can be signed immediately."""
    # 1. Propose 0.05 ETH (under 0.1 ETH threshold)
    prop_res = await auth_client.post(
        "/api/v1/proposals",
        json={
            "prompt": "Send 0.05 ETH",
            "recipient": "0x742d35Cc6634C0532925a3b844Bc9e7595f2bD1e",
            "amount_wei": "50000000000000000",
            "chain_id": 11155111,
        },
    )
    assert prop_res.status_code == 200
    prop_id = prop_res.json()["data"]["id"]

    # 2. Evaluate
    eval_res = await auth_client.post(f"/api/v1/proposals/{prop_id}/evaluate")
    assert eval_res.status_code == 200
    eval_data = eval_res.json()["data"]
    assert eval_data["status"] == "ALLOWED"
    assert eval_data["policy_decision"]["decision"] == "ALLOW"

    # 3. Sign and submit
    sign_res = await auth_client.post(f"/api/v1/proposals/{prop_id}/sign")
    assert sign_res.status_code == 200
    sign_data = sign_res.json()["data"]
    assert sign_data["status"] == "SUBMITTED"
    assert sign_data["transaction"]["tx_hash"] is not None
    assert sign_data["transaction"]["status"] == "SUBMITTED"


@pytest.mark.asyncio
async def test_block_lifecycle(auth_client, active_policy):
    """Proposal exceeding max amount is BLOCKED and cannot be signed."""
    # 1. Propose 5 ETH (exceeds 1 ETH max)
    prop_res = await auth_client.post(
        "/api/v1/proposals",
        json={
            "prompt": "Send 5 ETH",
            "recipient": "0x742d35Cc6634C0532925a3b844Bc9e7595f2bD1e",
            "amount_wei": "5000000000000000000",
            "chain_id": 11155111,
        },
    )
    prop_id = prop_res.json()["data"]["id"]

    # 2. Evaluate
    eval_res = await auth_client.post(f"/api/v1/proposals/{prop_id}/evaluate")
    assert eval_res.status_code == 200
    eval_data = eval_res.json()["data"]
    assert eval_data["status"] == "BLOCKED"
    assert eval_data["policy_decision"]["decision"] == "BLOCK"
    assert "AMOUNT_EXCEEDS_LIMIT" in eval_data["policy_decision"]["reason_codes"]

    # 3. Attempt signing -> Rejected
    sign_res = await auth_client.post(f"/api/v1/proposals/{prop_id}/sign")
    assert sign_res.status_code == 403
    assert sign_res.json()["error"]["code"] == "POLICY_BLOCK"


@pytest.mark.asyncio
async def test_escalate_and_approval_flow(auth_client, active_policy):
    """Proposal between threshold and max is ESCALATED, requiring human approval to sign."""
    # 1. Propose 0.5 ETH (between 0.1 ETH threshold and 1 ETH max)
    prop_res = await auth_client.post(
        "/api/v1/proposals",
        json={
            "prompt": "Send 0.5 ETH",
            "recipient": "0x742d35Cc6634C0532925a3b844Bc9e7595f2bD1e",
            "amount_wei": "500000000000000000",
            "chain_id": 11155111,
        },
    )
    prop_id = prop_res.json()["data"]["id"]

    # 2. Evaluate -> ESCALATED
    eval_res = await auth_client.post(f"/api/v1/proposals/{prop_id}/evaluate")
    assert eval_res.status_code == 200
    eval_data = eval_res.json()["data"]
    assert eval_data["status"] == "ESCALATED"
    assert eval_data["approval"]["status"] == "PENDING"
    approval_id = eval_data["approval"]["id"]

    # 3. Attempt sign before human approval -> Rejected
    sign_res = await auth_client.post(f"/api/v1/proposals/{prop_id}/sign")
    assert sign_res.status_code == 403
    assert sign_res.json()["error"]["code"] == "APPROVAL_REQUIRED"

    # 4. Check pending approvals list
    pending_res = await auth_client.get("/api/v1/approvals/pending")
    assert pending_res.status_code == 200
    pending_list = pending_res.json()["data"]
    assert any(a["id"] == approval_id for a in pending_list)

    # 5. Human approves
    decide_res = await auth_client.post(
        f"/api/v1/approvals/{approval_id}/decide",
        headers={"X-API-Key": "test-human-approver-key-only"},
        json={"decision": "APPROVE", "approved_by": "user:security_officer"},
    )
    assert decide_res.status_code == 200
    assert decide_res.json()["data"]["status"] == "APPROVED"

    # 6. Now signing succeeds!
    sign_res = await auth_client.post(f"/api/v1/proposals/{prop_id}/sign")
    assert sign_res.status_code == 200
    assert sign_res.json()["data"]["status"] == "SUBMITTED"


@pytest.mark.asyncio
async def test_escalate_and_rejection_flow(auth_client, active_policy):
    """Proposal rejected by human cannot be signed."""
    # 1. Propose 0.5 ETH
    prop_res = await auth_client.post(
        "/api/v1/proposals",
        json={
            "prompt": "Send 0.5 ETH",
            "recipient": "0x742d35Cc6634C0532925a3b844Bc9e7595f2bD1e",
            "amount_wei": "500000000000000000",
            "chain_id": 11155111,
        },
    )
    prop_id = prop_res.json()["data"]["id"]

    # 2. Evaluate
    eval_res = await auth_client.post(f"/api/v1/proposals/{prop_id}/evaluate")
    approval_id = eval_res.json()["data"]["approval"]["id"]

    # 3. Human rejects
    decide_res = await auth_client.post(
        f"/api/v1/approvals/{approval_id}/decide",
        headers={"X-API-Key": "test-human-approver-key-only"},
        json={"decision": "REJECT", "approved_by": "user:admin"},
    )
    assert decide_res.status_code == 200
    assert decide_res.json()["data"]["status"] == "REJECTED"

    # 4. Signing must be rejected
    sign_res = await auth_client.post(f"/api/v1/proposals/{prop_id}/sign")
    assert sign_res.status_code == 403
