"""Read-only portfolio with isolated DB and mocked read RPC, never a network request."""

import json
from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import select

from app.api.routes.portfolio import PortfolioRPC, share, units
from app.core.config import PortfolioToken, get_settings
from app.models import ExecutionAttempt, Proposal, SpendingRecord, Transaction
from tests.integration.test_payment_security import ADDRESS, PROPOSER, policy
from tests.integration.test_payment_security import file_client as file_client


@pytest.mark.asyncio
async def test_reader_rejects_execution_methods_and_hides_provider_logs(monkeypatch, caplog):
    monkeypatch.setattr(get_settings(), "sepolia_rpc_url",
                        "https://ethereum-sepolia-rpc.publicnode.com/private-provider-token")
    methods = []

    def response(request):
        methods.append(json.loads(request.content)["method"])
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": "0xaa36a7"})

    caplog.set_level("INFO", logger="httpx")
    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
        assert await PortfolioRPC().call(client, "eth_chainId", []) == "0xaa36a7"
        for method in ("eth_sendRawTransaction", "eth_sendTransaction", "personal_sign"):
            with pytest.raises(ValueError, match="Read-only"):
                await PortfolioRPC().call(client, method, [])
    assert methods == ["eth_chainId"]
    assert "private-provider-token" not in caplog.text


@pytest.fixture
def reads(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "sepolia_rpc_url", "https://ethereum-sepolia-rpc.publicnode.com")
    monkeypatch.setattr(settings, "watched_addresses", [ADDRESS])
    calls = []

    async def call(self, client, method, params):
        calls.append((method, params))
        if method == "eth_chainId":
            return hex(11155111)
        if method == "eth_getBlockByNumber":
            return {"number": "0x64", "timestamp": "0x6553f100"}
        if method == "eth_getBalance":
            return hex(10**18 if params[0] == ADDRESS else 3 * 10**18 + 1)
        if method == "eth_getTransactionCount":
            return "0x2"
        if method == "eth_call":
            return "0x" + hex(1234567)[2:].zfill(64)
        raise AssertionError("Unexpected RPC method")

    monkeypatch.setattr(PortfolioRPC, "call", call)
    return calls


def test_decimal_formatting_not_float():
    assert units(1) == "0.000000000000000001"
    assert units(10**18 + 1) == "1.000000000000000001"
    assert units(1234567, 6) == "1.234567"
    assert units(2**256 - 1, 0) == str(2**256 - 1)
    assert share(1, 4) == "25.000000"
    assert share(0, 0) is None


@pytest.mark.asyncio
async def test_portfolio_auth_and_read_only_snapshot(file_client, reads):
    client, factory = file_client
    assert (await client.get("/api/v1/portfolio")).status_code == 401
    assert reads == []
    response = await client.get("/api/v1/portfolio", headers=PROPOSER)
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["network"]["status"] == "available"
    assert data["network"]["block_number"] == 100
    assert data["network"]["pending_nonce"] == 2
    assert data["network"]["holdings"][0]["balance"] == "3.000000000000000001"
    assert data["network"]["holdings"][1]["role"] == "Watched wallet"
    assert [c[1][1] for c in reads if c[0] == "eth_getBalance"] == ["0x64", "0x64"]
    text = response.text
    settings = get_settings()
    for secret in (
        settings.api_key, settings.signer_private_key, settings.capability_token_secret,
        settings.sepolia_rpc_url, settings.approver_api_key, settings.policy_admin_api_key,
    ):
        assert secret not in text
    assert (await client.post("/api/v1/portfolio", headers=PROPOSER)).status_code == 405
    async with factory() as session:
        assert await session.scalar(select(Proposal)) is None
        assert await session.scalar(select(ExecutionAttempt)) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["wrong_chain", "rpc_error", "malformed"])
async def test_unavailable_has_no_cached_or_made_up_holdings(
    file_client, reads, monkeypatch, failure,
):
    client, _ = file_client
    good = await client.get("/api/v1/portfolio", headers=PROPOSER)
    assert good.json()["data"]["network"]["status"] == "available"

    async def call(*args):
        if failure == "rpc_error":
            raise RuntimeError("secret provider URL and credentials must not escape")
        return "0x1" if failure == "wrong_chain" else "invalid"

    monkeypatch.setattr(PortfolioRPC, "call", call)
    response = await client.get("/api/v1/portfolio", headers=PROPOSER)
    network = response.json()["data"]["network"]
    assert network["status"] == "unavailable"
    assert network["reason"] == ("WRONG_CHAIN" if failure == "wrong_chain" else "RPC_READ_FAILED")
    assert network["holdings"] == [] and network["pending_nonce"] is None
    assert "block_number" not in network
    assert "secret provider" not in response.text


@pytest.mark.asyncio
async def test_budget_pending_across_midnight_and_payment_links(file_client, reads):
    client, factory = file_client
    await policy(client, budget=str(10**18), threshold=str(10**17))
    today = datetime.now(UTC).date().isoformat()
    async with factory() as session:
        for index, (mode, outcome) in enumerate([
            ("simulated", "SIMULATED"), ("sepolia", "CONFIRMED"),
            (None, None), ("sepolia", "REVERTED"),
        ]):
            proposal = Proposal(correlation_id=f"test-{index}", agent_prompt="test",
                                recipient=ADDRESS, amount_wei=str(10**16), chain_id=11155111,
                                asset_type="NATIVE_ETH", status="ALLOWED")
            session.add(proposal)
            await session.flush()
            session.add(Transaction(proposal_id=proposal.id, tx_hash="0x" + str(index) * 64,
                                    execution_mode=mode, execution_outcome=outcome,
                                    status="SUBMITTED"))
            session.add(SpendingRecord(proposal_id=proposal.id, amount_wei=str(10**16),
                                      status="COMMITTED" if index == 0 else "RESERVED",
                                      period_date=today if index == 0 else "2000-01-01"))
        await session.commit()
    data = (await client.get("/api/v1/portfolio", headers=PROPOSER)).json()["data"]
    assert data["budget"]["spent_today_eth"] == "0.01"
    assert data["budget"]["pending_eth"] == "0.03"
    assert data["budget"]["remaining_eth"] == "0.96"
    for payment in data["recent_payments"]:
        if payment["status"] in ("SIMULATED", "UNVERIFIED"):
            assert payment["explorer_url"] is None
        else:
            assert payment["explorer_url"].endswith(payment["tx_hash"])


@pytest.mark.asyncio
async def test_configured_token_balances_only(file_client, reads, monkeypatch):
    client, _ = file_client
    monkeypatch.setattr(get_settings(), "token_allowlist", [PortfolioToken(
        symbol="TEST", address="0x" + "22" * 20, decimals=6,
    )])
    response = await client.get("/api/v1/portfolio", headers=PROPOSER)
    holdings = response.json()["data"]["network"]["holdings"]
    assert len(holdings) == 4
    assert holdings[2]["balance"] == "1.234567"
    assert holdings[2]["share_percent"] == "50.000000"
    token_reads = [call for call in reads if call[0] == "eth_call"]
    assert len(token_reads) == 2
    assert all(call[1][0]["data"].startswith("0x70a08231") for call in token_reads)
    assert "market" not in json.dumps(holdings)
