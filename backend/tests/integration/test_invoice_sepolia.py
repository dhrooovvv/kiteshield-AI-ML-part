"""Real invoice coordinator and test signer, strictly fake Sepolia RPC."""

import pytest
from sqlalchemy import select

from app.models import ExecutionAttempt
from app.services import invoices
from tests.integration.test_invoices import (
    extractor,
    fields,
    setup,
    text,
)
from tests.integration.test_invoices import (
    invoice_settings as invoice_settings,
)
from tests.integration.test_payment_security import PROPOSER
from tests.integration.test_payment_security import file_client as file_client
from tests.integration.test_sepolia_execution import mined
from tests.integration.test_sepolia_execution import rpc as rpc


@pytest.mark.asyncio
async def test_three_invoice_payments_use_live_adapter_and_receipt_recovery(
    file_client, invoice_settings, rpc, monkeypatch
):
    client, factory = file_client
    await setup(client)
    monkeypatch.setattr(invoice_settings, "invoice_live_execution_enabled", True)
    for index, amount in enumerate(("0.00001", "0.00002", "0.00003")):
        f = fields(number=f"SEPOLIA-INVOICE-{index}", amount=amount)
        invoice_id = await invoices.ingest(factory, text(f), extractor=extractor(f))
        data = (await client.get("/api/v1/invoices", headers=PROPOSER)).json()["data"]
        item = next(row for row in data["items"] if row["id"] == invoice_id)
        assert item["state"] == "PAID", item
        tx_hash = item["transaction_hash"]
        assert item["explorer_url"] == f"https://sepolia.etherscan.io/tx/{tx_hash}"
        rpc.receipts[tx_hash] = mined(tx_hash)
        await invoices.reconcile_invoices(factory)
        async with factory() as session:
            from app.models.invoices import InvoiceRecord

            record = await session.get(InvoiceRecord, invoice_id)
            assert record.state == "VERIFIED"
            attempt = await session.scalar(
                select(ExecutionAttempt).where(ExecutionAttempt.proposal_id == record.proposal_id)
            )
            assert attempt.nonce == 7 + index
        assert await invoices.ingest(factory, text(f), extractor=extractor(f)) == invoice_id
        assert rpc.eth.send_raw_transaction.call_count == index + 1
    assert len(rpc.payloads) == 3
