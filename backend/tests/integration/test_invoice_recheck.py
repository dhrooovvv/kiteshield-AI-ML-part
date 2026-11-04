"""Recheck missing-vendor intake only; never reopen an execution or bypass gates."""

import asyncio
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select

from app.models import AuditEvent, ExecutionAttempt, ExecutionControl, Proposal
from app.models.invoices import InvoiceRecord, Vendor
from app.services import invoices
from tests.integration.test_invoices import extractor, fields, setup, text
from tests.integration.test_invoices import invoice_settings as invoice_settings
from tests.integration.test_payment_security import ADMIN, APPROVER, PROPOSER, policy
from tests.integration.test_payment_security import file_client as file_client


async def missing_vendor(client, factory):
    await policy(client)
    f = fields("VENDOR-RECHECK-1")
    id_ = await invoices.ingest(factory, text(f), extractor=extractor(f))
    async with factory() as session:
        row = await session.get(InvoiceRecord, id_)
        assert row.state == "BLOCKED" and row.reason == "EXACT_VENDOR_REQUIRED"
        assert row.proposal_id is None
    return id_, f


@pytest.mark.asyncio
async def test_recheck_after_registration_is_atomic_and_keeps_original_history(
    file_client, invoice_settings, monkeypatch
):
    client, factory = file_client
    id_, f = await missing_vendor(client, factory)
    await setup(client)
    model = extractor(f)
    monkeypatch.setattr(invoices, "extract_invoice", model)
    responses = await asyncio.gather(
        *[client.post(f"/api/v1/invoices/{id_}/recheck", headers=PROPOSER) for _ in range(2)]
    )
    assert sorted(response.status_code for response in responses) == [200, 422]
    model.assert_awaited_once()
    async with factory() as session:
        row = await session.get(InvoiceRecord, id_)
        assert row.state == "SIMULATED" and row.proposal_id
        assert await session.scalar(select(func.count()).select_from(InvoiceRecord)) == 1
        assert await session.scalar(select(func.count()).select_from(ExecutionAttempt)) == 1
        assert await session.scalar(select(func.count()).select_from(Proposal)) == 1
        events = list((await session.scalars(select(AuditEvent.event_type))).all())
        assert "INVOICE_BLOCKED" in events and "INVOICE_RECHECK_REQUESTED" in events
    result = (await client.get("/api/v1/invoices", headers=PROPOSER)).json()["data"]["items"][0]
    assert result["can_recheck"] is False


@pytest.mark.asyncio
async def test_recheck_requires_proposer(file_client, invoice_settings):
    client, factory = file_client
    id_, _ = await missing_vendor(client, factory)
    for headers, status in (({}, 401), (ADMIN, 403), (APPROVER, 403)):
        assert (
            await client.post(f"/api/v1/invoices/{id_}/recheck", headers=headers)
        ).status_code == status


@pytest.mark.asyncio
async def test_recheck_does_not_enable_live_execution(file_client, invoice_settings, monkeypatch):
    client, factory = file_client
    id_, f = await missing_vendor(client, factory)
    await setup(client)
    monkeypatch.setattr(invoice_settings, "execution_mode", "sepolia")
    monkeypatch.setattr(invoices, "extract_invoice", extractor(f))
    assert not invoice_settings.invoice_live_execution_enabled
    response = await client.post(f"/api/v1/invoices/{id_}/recheck", headers=PROPOSER)
    assert response.status_code == 200
    async with factory() as session:
        assert (await session.get(InvoiceRecord, id_)).state == "CHECKED"
        assert await session.scalar(select(func.count()).select_from(ExecutionAttempt)) == 0


@pytest.mark.asyncio
async def test_recheck_refuses_a_preexisting_proposal_even_if_record_link_is_missing(
    file_client, invoice_settings
):
    from tests.integration.test_payment_security import ADDRESS

    client, factory = file_client
    id_, _ = await missing_vendor(client, factory)
    async with factory() as session:
        session.add(
            Proposal(
                correlation_id=id_,
                agent_prompt="Previous rejected proposal",
                recipient=ADDRESS,
                amount_wei="1",
                chain_id=11155111,
                asset_type="NATIVE_ETH",
                status="REJECTED",
            )
        )
        await session.commit()
    assert (
        await client.post(f"/api/v1/invoices/{id_}/recheck", headers=PROPOSER)
    ).status_code == 422
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(Proposal)) == 1
        assert (await session.get(InvoiceRecord, id_)).state == "BLOCKED"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "state", ["CHECKED", "PAID", "VERIFIED", "UNCERTAIN", "REVERTED", "REJECTED"]
)
async def test_recheck_never_reopens_later_states(file_client, invoice_settings, state):
    client, factory = file_client
    id_, _ = await missing_vendor(client, factory)
    async with factory() as session:
        (await session.get(InvoiceRecord, id_)).state = state
        await session.commit()
    assert (
        await client.post(f"/api/v1/invoices/{id_}/recheck", headers=PROPOSER)
    ).status_code == 422
    async with factory() as session:
        assert (await session.get(InvoiceRecord, id_)).state == state
        assert await session.scalar(select(func.count()).select_from(ExecutionAttempt)) == 0


@pytest.mark.asyncio
async def test_recheck_runs_screening_again_before_extraction(
    file_client, invoice_settings, monkeypatch
):
    from tests.unit.test_invoice_screening import clearance

    client, factory = file_client
    id_, f = await missing_vendor(client, factory)
    await setup(client)
    monkeypatch.setattr(invoice_settings, "invoice_learned_screening_enabled", True)
    monkeypatch.setattr(invoice_settings, "invoice_learned_evaluated", True)
    proof = {**clearance(text(f)), "classification": "ATTACK"}
    monkeypatch.setattr(invoices.invoice_screening, "screen", AsyncMock(return_value=proof))
    model = extractor(f)
    monkeypatch.setattr(invoices, "extract_invoice", model)
    assert (
        await client.post(f"/api/v1/invoices/{id_}/recheck", headers=PROPOSER)
    ).status_code == 200
    model.assert_not_awaited()
    async with factory() as session:
        row = await session.get(InvoiceRecord, id_)
        assert row.state == "BLOCKED" and row.reason == "LEARNED_ATTACK"
        assert row.proposal_id is None


@pytest.mark.asyncio
@pytest.mark.parametrize("violation", ["stop", "budget", "vendor_cap", "duplicate"])
async def test_recheck_enforces_current_limits_and_duplicates(
    file_client, invoice_settings, monkeypatch, violation
):
    client, factory = file_client
    id_, f = await missing_vendor(client, factory)
    await setup(client)
    monkeypatch.setattr(invoices, "extract_invoice", extractor(f))
    if violation == "budget":
        await policy(client, budget="1")
    elif violation == "duplicate":
        await invoices.ingest(factory, text(f) + "\nDescription: Services.", extractor=extractor(f))
    else:
        async with factory() as session:
            if violation == "stop":
                (await session.get(ExecutionControl, "global")).active = True
            else:
                (await session.scalar(select(Vendor))).maximum_wei = "1"
            await session.commit()
    response = await client.post(f"/api/v1/invoices/{id_}/recheck", headers=PROPOSER)
    assert response.status_code == 200, response.text
    async with factory() as session:
        row = await session.get(InvoiceRecord, id_)
        assert row.state == "BLOCKED" and row.proposal_id is None
        assert await session.scalar(select(func.count()).select_from(ExecutionAttempt)) == (
            1 if violation == "duplicate" else 0
        )
