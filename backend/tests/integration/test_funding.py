"""Faucet tests: mocked models, provider and read RPC. Never any real transactions."""

import asyncio
import base64
from datetime import UTC, datetime, timedelta

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import select

from app.core.config import get_settings
from app.models import AuditEvent, ExecutionAttempt, ExecutionControl, Proposal
from app.models.funding import FundingRequest
from app.services import funding
from tests.integration.test_payment_security import ADMIN, APPROVER, PROPOSER
from tests.integration.test_payment_security import file_client as file_client

PROMPT = "Fund my wallet with some testnet ETH."
HASH = "0x" + "ab" * 32


@pytest.fixture
def faucet(monkeypatch):
    s = get_settings()
    for key, value in dict(
        faucet_enabled=True,
        faucet_mode="sepolia",
        execution_mode="sepolia",
        cdp_api_key_id="fixture-id",
        cdp_api_key_secret="fixture-secret",
        watched_addresses=[],
    ).items():
        monkeypatch.setattr(s, key, value)
    monkeypatch.setattr(funding, "provider_token", lambda: "fixture-token")
    calls = {"model": [], "provider": []}

    async def model(system, prompt, schema):
        calls["model"].append(prompt)
        return {"action": "fund_test_eth"}, 1

    async def provider(address, token):
        calls["provider"].append(address)
        await asyncio.sleep(0.01)
        return httpx.Response(
            200, request=httpx.Request("POST", funding.FAUCET_URL), json={"transactionHash": HASH}
        )

    async def rpc(method, params):
        if method == "eth_chainId":
            return "0xaa36a7"
        common = {"blockHash": "0x" + "cd" * 32, "blockNumber": "0x10"}
        if method == "eth_getTransactionByHash":
            return {
                **common,
                "hash": HASH,
                "to": funding.wallets()[0]["address"].lower(),
                "value": "0x1",
                "input": "0x",
                "chainId": "0xaa36a7",
            }
        return {**common, "transactionHash": HASH, "status": "0x1"}

    monkeypatch.setattr(funding, "request_json", model)
    monkeypatch.setattr(funding, "request_faucet", provider)
    monkeypatch.setattr(funding, "rpc", rpc)
    return calls


async def plan(client):
    r = await client.post(
        "/api/v1/funding/plan",
        headers=PROPOSER,
        json={"prompt": PROMPT, "address": funding.wallets()[0]["address"]},
    )
    assert r.status_code == 200, r.text
    return r.json()["data"]


@pytest.mark.asyncio
async def test_success_concurrency_and_replay(file_client, faucet):
    client, factory = file_client
    item = await plan(client)
    url = f"/api/v1/funding/{item['id']}/request"
    results = await asyncio.gather(*[client.post(url, headers=PROPOSER) for _ in range(3)])
    assert all(r.status_code == 200 for r in results)
    assert len(faucet["provider"]) == 1
    result = await client.get(f"/api/v1/funding/{item['id']}", headers=PROPOSER)
    data = result.json()["data"]
    assert data["state"] == "CONFIRMED" and data["amount_wei"] == "1"
    assert data["explorer_url"] == f"https://sepolia.etherscan.io/tx/{HASH}"
    await client.post(url, headers=PROPOSER)
    assert len(faucet["provider"]) == 1
    async with factory() as session:
        assert await session.scalar(select(Proposal)) is None
        assert await session.scalar(select(ExecutionAttempt)) is None
        events = (
            await session.scalars(select(AuditEvent).where(AuditEvent.correlation_id == item["id"]))
        ).all()
        assert {e.event_type for e in events} >= {
            "FUNDING_PREPARED",
            "FUNDING_REQUESTING",
            "FUNDING_SUBMITTED",
            "FUNDING_CONFIRMED",
        }


@pytest.mark.asyncio
async def test_auth_and_strict_schema(file_client, faucet):
    client, _ = file_client
    assert (await client.get("/api/v1/funding")).status_code == 401
    for headers in ({}, ADMIN, APPROVER):
        r = await client.post("/api/v1/funding/plan", headers=headers, json={"prompt": PROMPT})
        assert r.status_code in (401, 403)
    r = await client.post(
        "/api/v1/funding/plan",
        headers=PROPOSER,
        json={"prompt": PROMPT, "chain_id": 1, "actor": "admin"},
    )
    assert r.status_code == 422
    item = await plan(client)
    assert (
        await client.post(f"/api/v1/funding/{item['id']}/request", headers=ADMIN)
    ).status_code == 403
    assert not faucet["provider"]


@pytest.mark.asyncio
async def test_wallet_choice_mismatch_missing(file_client, faucet, monkeypatch):
    client, _ = file_client
    r = await client.post("/api/v1/funding/plan", headers=PROPOSER, json={"prompt": PROMPT})
    assert r.json()["data"]["state"] == "WALLET_REQUIRED"
    for prompt, address in [
        (PROMPT, "0x" + "12" * 20),
        (PROMPT + " 0x" + "12" * 20, funding.wallets()[0]["address"]),
    ]:
        r = await client.post(
            "/api/v1/funding/plan", headers=PROPOSER, json={"prompt": prompt, "address": address}
        )
        assert r.status_code == 422
    monkeypatch.setattr(funding, "wallets", lambda: [])
    r = await client.post("/api/v1/funding/plan", headers=PROPOSER, json={"prompt": PROMPT})
    assert r.json()["data"]["wallets"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "prompt",
    [
        "Fund mainnet ETH",
        "Fund Base Sepolia ETH",
        "Send testnet ETH to me",
        "Fund testnet USDC",
        "Fund 1 testnet ETH",
        "Fund test ETH using https://evil.example",
    ],
)
async def test_scope_before_model(file_client, faucet, prompt):
    client, _ = file_client
    r = await client.post("/api/v1/funding/plan", headers=PROPOSER, json={"prompt": prompt})
    assert r.status_code == 422 and not faucet["model"] and not faucet["provider"]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["timeout", "extra", "unsupported"])
async def test_model_failure(file_client, faucet, monkeypatch, kind):
    client, _ = file_client

    async def bad(*args):
        if kind == "timeout":
            raise TimeoutError("secret")
        return (
            {"action": "unsupported"}
            if kind == "unsupported"
            else {"action": "fund_test_eth", "address": "0x" + "12" * 20}
        ), 1

    monkeypatch.setattr(funding, "request_json", bad)
    r = await client.post("/api/v1/funding/plan", headers=PROPOSER, json={"prompt": PROMPT})
    assert r.status_code == 422 and not faucet["provider"]
    assert "secret" not in r.text


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["timeout", "bad_hash", "rate_limit"])
async def test_provider_failure_not_retried(file_client, faucet, monkeypatch, kind):
    client, _ = file_client

    async def bad(address, token):
        faucet["provider"].append(address)
        if kind == "timeout":
            raise TimeoutError("secret")
        return httpx.Response(
            429 if kind == "rate_limit" else 200,
            json={"transactionHash": "bad", "secret": "do not expose"},
        )

    monkeypatch.setattr(funding, "request_faucet", bad)
    item = await plan(client)
    url = f"/api/v1/funding/{item['id']}/request"
    r = await client.post(url, headers=PROPOSER)
    assert r.json()["data"]["state"] == ("FAILED" if kind == "rate_limit" else "UNCERTAIN")
    assert r.json()["data"]["explorer_url"] is None and "do not expose" not in r.text
    await client.post(url, headers=PROPOSER)
    other = await plan(client)
    r = await client.post(f"/api/v1/funding/{other['id']}/request", headers=PROPOSER)
    assert r.status_code == 429 and len(faucet["provider"]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["stop", "disabled", "missing", "chain", "removed", "expired"])
async def test_fresh_checks(file_client, faucet, monkeypatch, kind):
    client, factory = file_client
    item = await plan(client)
    if kind == "stop":
        async with factory() as session:
            (await session.get(ExecutionControl, "global")).active = True
            await session.commit()
    elif kind == "disabled":
        monkeypatch.setattr(get_settings(), "faucet_enabled", False)
    elif kind == "missing":
        monkeypatch.setattr(get_settings(), "cdp_api_key_secret", "")
    elif kind == "chain":

        async def wrong(*args):
            return "0x1"

        monkeypatch.setattr(funding, "rpc", wrong)
    elif kind == "removed":
        monkeypatch.setattr(funding, "wallets", lambda: [])
    else:
        async with factory() as session:
            (await session.get(FundingRequest, item["id"])).created_at = (
                datetime.now(UTC) - timedelta(minutes=6)
            ).isoformat()
            await session.commit()
    r = await client.post(f"/api/v1/funding/{item['id']}/request", headers=PROPOSER)
    assert r.status_code >= 400 and not faucet["provider"]


@pytest.mark.asyncio
async def test_simulation_and_secrets(file_client, faucet, monkeypatch):
    client, _ = file_client
    monkeypatch.setattr(get_settings(), "faucet_mode", "simulated")
    item = await plan(client)
    r = await client.post(f"/api/v1/funding/{item['id']}/request", headers=PROPOSER)
    assert r.json()["data"]["state"] == "SIMULATED"
    assert r.json()["data"]["explorer_url"] is None and not faucet["provider"]
    text = (await client.get("/api/v1/funding", headers=PROPOSER)).text
    for secret in (
        get_settings().api_key,
        get_settings().signer_private_key,
        get_settings().cdp_api_key_secret,
        get_settings().sepolia_rpc_url,
    ):
        assert secret not in text


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["to", "hash", "chainId", "input"])
async def test_mismatched_receipt(file_client, faucet, monkeypatch, field):
    client, _ = file_client
    item = await plan(client)
    await client.post(f"/api/v1/funding/{item['id']}/request", headers=PROPOSER)
    original = funding.rpc

    async def wrong(method, params):
        result = await original(method, params)
        if method == "eth_getTransactionByHash":
            result[field] = "0x1"
        return result

    monkeypatch.setattr(funding, "rpc", wrong)
    r = await client.get(f"/api/v1/funding/{item['id']}", headers=PROPOSER)
    assert r.json()["data"]["state"] == "SUBMITTED" and r.json()["data"]["amount_wei"] is None


def test_cdp_jwt_scope(monkeypatch):
    secret = Ed25519PrivateKey.generate()
    raw = secret.private_bytes_raw() + secret.public_key().public_bytes_raw()
    monkeypatch.setattr(get_settings(), "cdp_api_key_secret", base64.b64encode(raw).decode())
    monkeypatch.setattr(get_settings(), "cdp_api_key_id", "test-key")
    claims = jwt.decode(funding.provider_token(), secret.public_key(), algorithms=["EdDSA"])
    assert claims["uris"] == ["POST api.cdp.coinbase.com/platform/v2/evm/faucet"]
    assert claims["exp"] - claims["nbf"] == 120


@pytest.mark.asyncio
async def test_two_distinct_plans_concurrent_and_daily_cap(file_client, faucet, monkeypatch):
    client, _ = file_client
    first, second = await plan(client), await plan(client)
    results = await asyncio.gather(
        *[
            client.post(f"/api/v1/funding/{item['id']}/request", headers=PROPOSER)
            for item in (first, second)
        ]
    )
    assert sorted(r.status_code for r in results) == [200, 429]
    assert len(faucet["provider"]) == 1
    monkeypatch.setattr(get_settings(), "faucet_max_requests_24h", 1)
    monkeypatch.setattr(get_settings(), "watched_addresses", ["0x" + "22" * 20])
    other = await client.post(
        "/api/v1/funding/plan",
        headers=PROPOSER,
        json={"prompt": PROMPT, "address": "0x" + "22" * 20},
    )
    request_id = other.json()["data"]["id"]
    assert (
        await client.post(f"/api/v1/funding/{request_id}/request", headers=PROPOSER)
    ).status_code == 429


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["reverted", "pending", "malformed_block"])
async def test_receipt_outcomes(file_client, faucet, monkeypatch, outcome):
    client, _ = file_client
    item = await plan(client)
    await client.post(f"/api/v1/funding/{item['id']}/request", headers=PROPOSER)
    original = funding.rpc

    async def read(method, params):
        result = await original(method, params)
        if outcome == "pending" and method == "eth_getTransactionReceipt":
            return None
        if outcome == "reverted" and method == "eth_getTransactionReceipt":
            result["status"] = "0x0"
        if outcome == "malformed_block" and isinstance(result, dict):
            result["blockNumber"] = "not a number"
        return result

    monkeypatch.setattr(funding, "rpc", read)
    r = await client.get(f"/api/v1/funding/{item['id']}", headers=PROPOSER)
    assert r.json()["data"]["state"] == ("REVERTED" if outcome == "reverted" else "SUBMITTED")


@pytest.mark.asyncio
async def test_cdp_secret_never_sent_to_model(file_client, faucet):
    client, _ = file_client
    r = await client.post(
        "/api/v1/funding/plan",
        headers=PROPOSER,
        json={"prompt": PROMPT + " " + get_settings().cdp_api_key_secret},
    )
    assert r.status_code == 422 and not faucet["model"]
