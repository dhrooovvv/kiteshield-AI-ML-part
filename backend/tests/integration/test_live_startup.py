"""Only mocked, read-only RPC calls; never sign, send or touch the application DB."""

from unittest.mock import AsyncMock

import httpx
import pytest

import app.api.routes.health as health_routes
import app.main as main
from app.core import live_rpc
from app.core.config import get_settings

RealAsyncClient = httpx.AsyncClient


@pytest.fixture
def live_settings():
    return get_settings().model_copy(update={
        "execution_mode": "sepolia",
        "sepolia_rpc_url": "https://eth-sepolia.g.alchemy.com/v2/test-fixture-secret",
    })


def mock_rpc(monkeypatch, handler):
    monkeypatch.setattr(
        live_rpc.httpx, "AsyncClient",
        lambda **kwargs: RealAsyncClient(transport=httpx.MockTransport(handler), **kwargs),
    )


@pytest.mark.parametrize("url", [
    "http://eth-sepolia.g.alchemy.com/v2/key",
    "https://eth-sepolia.g.alchemy.com/v2/YOUR_API_KEY",
    "https://eth-sepolia.g.alchemy.com/v2/YOUR_ALCHEMY_API_KEY",
    "https://eth-sepolia.g.alchemy.com/v2/%59OUR_API_KEY",
    "https://rpc.example.com/key", "https://mock-rpc.sepolia.org",
    "https://localhost:8545", "https://localhost.", "https://rpc.localhost",
    "https://localhost.localdomain", "https://rpc.local", "https://127.0.0.1",
    "https://127.1", "https://2130706433", "https://[::1]", "https://10.0.0.1",
    "https://192.168.1.1", "https://169.254.169.254", "https:///missing-host",
    "https://rpc.invalid", "https://rpc.provider.com:invalid",
])
async def test_bad_live_url_stops_startup_before_rpc_or_database(
    monkeypatch, live_settings, url,
):
    live_settings.sepolia_rpc_url = url
    monkeypatch.setattr(main, "get_settings", lambda: live_settings)
    database = AsyncMock()
    monkeypatch.setattr(main, "init_db", database)

    def forbidden_rpc(_request):
        pytest.fail("Invalid endpoint must be rejected before any RPC call")

    mock_rpc(monkeypatch, forbidden_rpc)
    app = main.create_app()
    with pytest.raises(RuntimeError, match="HTTPS RPC endpoint"):
        async with app.router.lifespan_context(app):
            pytest.fail("Startup must not complete")
    database.assert_not_awaited()
    assert app.state.verified_rpc is None


@pytest.mark.parametrize("failure", [
    "wrong_chain", "chain_error", "block_error", "timeout", "http_error", "redirect",
    "invalid_json", "null_block", "boolean_block", "negative_block", "missing_result",
    "wrong_response_id",
])
async def test_rpc_failures_abort_startup(monkeypatch, live_settings, failure):
    import json

    calls = []

    def handler(request):
        payload = json.loads(request.content)
        method = payload["method"]
        calls.append(method)
        result = "0xaa36a7" if method == "eth_chainId" else "0x1234"
        if failure == "timeout":
            raise httpx.ReadTimeout("Do not expose fixture secret", request=request)
        if failure == "http_error":
            return httpx.Response(503)
        if failure == "redirect":
            return httpx.Response(302, headers={"location": "https://localhost"})
        if failure == "invalid_json":
            return httpx.Response(200, text="not JSON")
        if failure == "wrong_chain" and method == "eth_chainId":
            result = "0x1"
        if (failure == "chain_error" and method == "eth_chainId") or (
            failure == "block_error" and method == "eth_blockNumber"
        ):
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": payload["id"],
                "error": {"code": -32000, "message": "Do not expose fixture secret"}})
        if method == "eth_blockNumber":
            if failure == "null_block":
                result = None
            elif failure == "boolean_block":
                result = True
            elif failure == "negative_block":
                result = "-0x1"
            elif failure == "missing_result":
                return httpx.Response(200, json={"jsonrpc": "2.0", "id": payload["id"]})
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": (
            999 if failure == "wrong_response_id" else payload["id"]), "result": result})

    mock_rpc(monkeypatch, handler)
    monkeypatch.setattr(main, "get_settings", lambda: live_settings)
    database = AsyncMock()
    monkeypatch.setattr(main, "init_db", database)
    app = main.create_app()
    with pytest.raises(RuntimeError, match="Live Sepolia startup") as error:
        async with app.router.lifespan_context(app):
            pytest.fail("Startup must not complete")
    assert "fixture-secret" not in str(error.value)
    assert "Do not expose" not in str(error.value)
    database.assert_not_awaited()
    assert app.state.verified_rpc is None
    if failure == "wrong_chain":
        assert calls == ["eth_chainId"]


async def test_verified_startup_exposes_chain_and_block_in_health(monkeypatch, live_settings):
    import json

    calls = []

    def handler(request):
        payload = json.loads(request.content)
        calls.append(payload["method"])
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": payload["id"],
            "result": "0xaa36a7" if payload["method"] == "eth_chainId" else "0x1234"})

    mock_rpc(monkeypatch, handler)
    monkeypatch.setattr(main, "get_settings", lambda: live_settings)
    monkeypatch.setattr(health_routes, "get_settings", lambda: live_settings)
    monkeypatch.setattr(main, "setup_logging", lambda _level: None)
    database = AsyncMock()
    monkeypatch.setattr(main, "init_db", database)
    app = main.create_app()
    async with app.router.lifespan_context(app):
        database.assert_awaited_once()
        async with RealAsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test",
        ) as client:
            response = await client.get("/api/v1/health")
        data = response.json()
        assert data["execution_mode"] == "sepolia"
        assert data["verified_chain_id"] == 11155111
        assert data["verified_block_number"] == 4660
        assert data["rpc_verified_at"]
        assert "fixture-secret" not in response.text
    assert calls == ["eth_chainId", "eth_blockNumber"]
    assert app.state.verified_rpc is None


async def test_simulated_startup_makes_no_rpc_calls(monkeypatch):
    settings = get_settings().model_copy(update={"execution_mode": "simulated"})
    monkeypatch.setattr(main, "get_settings", lambda: settings)
    monkeypatch.setattr(main, "setup_logging", lambda _level: None)
    monkeypatch.setattr(main, "init_db", AsyncMock())
    mock_rpc(monkeypatch, lambda _request: pytest.fail("Simulation must not call RPC"))
    app = main.create_app()
    async with app.router.lifespan_context(app):
        assert app.state.verified_rpc is None
