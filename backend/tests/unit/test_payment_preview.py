"""Read-only payment previews never reserve, sign or broadcast."""

from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.config import get_settings
from scripts import preview_sepolia_payments as module

RECIPIENT = "0x229D5588641f2614e3F486c853D8BA0eC5FFe811"


@pytest.mark.asyncio
async def test_preview_has_provisional_successive_nonces_and_exact_costs(test_engine, monkeypatch):
    monkeypatch.setattr(get_settings(), "execution_mode", "simulated")
    monkeypatch.setattr(module, "get_session_factory", lambda: async_sessionmaker(test_engine))
    prepare = AsyncMock(
        return_value={
            "nonce": 7,
            "gas": 25200,
            "maxFeePerGas": 3000000000,
            "maxPriorityFeePerGas": 1000000000,
        }
    )
    monkeypatch.setattr(module.BlockchainService, "prepare_transaction", prepare)
    monkeypatch.setattr(module.BlockchainService, "get_balance", AsyncMock(return_value=10**18))
    send = AsyncMock(side_effect=AssertionError("Preview must not broadcast"))
    monkeypatch.setattr(module.BlockchainService, "submit_raw_transaction", send)
    result = await module.preview(RECIPIENT, ["0.00001", "0.00002"])
    first, second = result["payments"]
    assert [first["candidate_nonce"], second["candidate_nonce"]] == [7, 8]
    assert first["maximum_total_cost_wei"] == str(10**13 + 25200 * 3000000000)
    assert result["required_balance_upper_bound_wei"] == str(3 * 10**13 + 2 * 25200 * 3000000000)
    assert result["sufficient_funds"] is True
    send.assert_not_awaited()


@pytest.mark.asyncio
async def test_preview_rejects_nonce_state_changing_between_quotes(test_engine, monkeypatch):
    monkeypatch.setattr(get_settings(), "execution_mode", "simulated")
    monkeypatch.setattr(module, "get_session_factory", lambda: async_sessionmaker(test_engine))
    base = {"gas": 25200, "maxFeePerGas": 3, "maxPriorityFeePerGas": 1}
    monkeypatch.setattr(
        module.BlockchainService,
        "prepare_transaction",
        AsyncMock(side_effect=[{**base, "nonce": 7}, {**base, "nonce": 9}]),
    )
    with pytest.raises(ValueError, match="Nonce state changed"):
        await module.preview(RECIPIENT, ["0.00001", "0.00002"])
