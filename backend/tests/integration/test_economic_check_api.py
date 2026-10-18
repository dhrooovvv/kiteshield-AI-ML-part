"""Authenticated fee advice must not mutate transaction or security state."""

import pytest
from sqlalchemy import func, select

from app.models import ApprovalRequest, AuditEvent, ExecutionControl, Policy, Proposal

PAYLOAD = {"value_wei": "10000000000000000", "estimated_gas": 21000, "gas_price_gwei": "20"}


async def test_requires_api_authentication(client):
    response = await client.post("/api/v1/security/economic-check", json=PAYLOAD)
    assert response.status_code == 401
    response = await client.post(
        "/api/v1/security/economic-check", json=PAYLOAD, headers={"X-API-Key": "invalid"}
    )
    assert response.status_code == 401


async def test_advisory_response_and_exact_decimal_gwei(auth_client):
    response = await auth_client.post(
        "/api/v1/security/economic-check", json={**PAYLOAD, "gas_price_gwei": "20.000000001"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["meta"]["correlation_id"]
    result = body["data"]
    assert result["advisory_only"] is True
    assert result["estimate_source"] == "CALLER_SUPPLIED"
    assert result["gas_cost_wei"] == "420000000021000"
    assert result["gas_cost_eth"] == "0.000420000000021"
    assert result["is_economically_viable"] is True
    assert "capability_payload" not in result
    assert "proposal_id" not in result


async def test_high_fee_response_is_advice_not_a_policy_decision(auth_client):
    response = await auth_client.post(
        "/api/v1/security/economic-check",
        json={**PAYLOAD, "value_wei": "1", "max_gas_price_gwei": "0"},
    )
    assert response.status_code == 200
    result = response.json()["data"]
    assert result["advisory_only"] is True
    assert result["is_economically_viable"] is False
    assert result["warnings"] == ["GAS_PRICE_ABOVE_CEILING", "GAS_FEE_EXCEEDS_TRANSFER_VALUE"]


@pytest.mark.parametrize(
    "override",
    [
        {"value_wei": "-1"}, {"value_wei": "abc"}, {"value_wei": "0x10"},
        {"value_wei": "1.5"}, {"value_wei": str(2**256)}, {"value_wei": 10},
        {"estimated_gas": 0}, {"estimated_gas": 30_000_001}, {"estimated_gas": True},
        {"gas_price_gwei": "-1"}, {"gas_price_gwei": "NaN"},
        {"gas_price_gwei": "Infinity"}, {"gas_price_gwei": "0.0000000001"},
        {"gas_price_gwei": "1000000001"}, {"max_gas_price_gwei": "-1"},
        {"max_gas_price_gwei": None}, {"authorize": True},
    ],
)
async def test_invalid_inputs_never_return_success(auth_client, override):
    response = await auth_client.post(
        "/api/v1/security/economic-check", json={**PAYLOAD, **override}
    )
    assert response.status_code == 422


async def test_zero_value_call_has_no_ratio(auth_client):
    response = await auth_client.post(
        "/api/v1/security/economic-check", json={**PAYLOAD, "value_wei": "0"}
    )
    result = response.json()["data"]
    assert result["gas_to_value_ratio"] is None
    assert result["warnings"] == ["ZERO_VALUE_RATIO_UNAVAILABLE"]


async def test_advice_does_not_create_records_or_change_emergency_stop(auth_client, test_session):
    state = await test_session.get(ExecutionControl, "global")
    state.active = True
    await test_session.commit()
    for value in ("1", PAYLOAD["value_wei"]):
        response = await auth_client.post(
            "/api/v1/security/economic-check", json={**PAYLOAD, "value_wei": value}
        )
        assert response.status_code == 200
    for model in (Proposal, ApprovalRequest, AuditEvent, Policy):
        assert await test_session.scalar(select(func.count()).select_from(model)) == 0
    await test_session.refresh(state)
    assert state.active is True
