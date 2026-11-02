"""Local model boundary tests; no real Ollama, RPC or signing calls."""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest

from app.services import invoice_llm


@pytest.mark.asyncio
async def test_model_receives_only_redacted_document_and_schema(monkeypatch):
    request = AsyncMock(
        return_value=(
            {
                "vendor_name": "Development Workshop",
                "invoice_number": "DEV-01",
                "amount_eth": ".03",
                "due_date": "2026-10-24",
            },
            7,
        )
    )
    monkeypatch.setattr(invoice_llm, "request_json", request)
    output, _ = await invoice_llm.extract_invoice(
        "Development Workshop DEV-01 .03 ETH 2026-10-24 0x" + "22" * 20
    )
    assert output.amount_eth == ".03"
    system, document, schema = request.call_args.args
    assert "0x" + "22" * 20 not in document
    assert "[ADDRESS_IGNORED]" in document and "<UNTRUSTED_INVOICE>" in document
    assert schema["additionalProperties"] is False
    assert set(schema["properties"]) == {
        "vendor_name",
        "invoice_number",
        "amount_eth",
        "due_date",
    }
    assert "untrusted" in system


def test_duplicate_json_keys_rejected():
    with pytest.raises(ValueError, match="Duplicate"):
        invoice_llm.strict_json('{"amount_eth":".03","amount_eth":".04"}')


@pytest.mark.asyncio
async def test_transport_fixed_loopback_no_tools_timeout_and_incomplete_output(monkeypatch):
    calls = []

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"done": False, "message": {"content": "{}"}}

    class Client:
        def __init__(self, **kwargs):
            assert kwargs == {"timeout": 60, "trust_env": False, "follow_redirects": False}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, url, json):
            calls.append((url, json))
            return Response()

    @asynccontextmanager
    async def unlocked():
        yield

    monkeypatch.setattr(invoice_llm.httpx, "AsyncClient", Client)
    monkeypatch.setattr(invoice_llm, "serialized_model", unlocked)
    with pytest.raises(invoice_llm.ModelReviewRequiredError):
        await invoice_llm.request_json("extract", "invoice", {"type": "object"})
    url, payload = calls[0]
    assert url == "http://127.0.0.1:11434/api/chat"
    assert "tools" not in payload and payload["options"]["temperature"] == 0
    assert payload["stream"] is False
