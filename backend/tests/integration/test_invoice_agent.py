"""Only feature regressions: isolated SQLite, fake extraction, simulated execution."""

import asyncio
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select

from app.core.config import get_settings
from app.models import ExecutionAttempt, Proposal
from app.models.invoice_agent import InvoiceAgentTask
from app.models.invoices import InvoiceRecord
from app.services import invoice_agent, invoices
from app.services.blockchain import BlockchainService
from tests.integration.test_invoices import fields, setup, text
from tests.integration.test_payment_security import ADMIN, APPROVER, PROPOSER
from tests.integration.test_payment_security import file_client as file_client


@pytest.fixture
def enabled(tmp_path, monkeypatch):
    settings = get_settings()
    for key, value in {
        "invoice_intake_enabled": True,
        "invoice_auto_execute_enabled": True,
        "auto_execute_enabled": True,
        "invoice_learned_screening_enabled": False,
        "learned_screening_enabled": False,
        "invoice_live_execution_enabled": False,
        "execution_mode": "simulated",
        "invoice_search_roots": [str(tmp_path)],
    }.items():
        monkeypatch.setattr(settings, key, value)
    monkeypatch.setattr(invoices, "extract_invoice", AsyncMock(return_value=(fields(), 1)))

    def no_rpc(*args):
        raise AssertionError("No RPC permitted in these tests")

    monkeypatch.setattr(BlockchainService, "_get_w3", no_rpc)
    return tmp_path


async def queue(client, prompt="Find acme.txt and pay it.", **extra):
    r = await client.post(
        "/api/v1/assistant/query", headers=PROPOSER, json={"prompt": prompt, **extra}
    )
    assert r.status_code == 200, r.text
    return r.json()["data"]


@pytest.mark.asyncio
async def test_autonomous_invoice_command_and_duplicate(file_client, enabled):
    client, factory = file_client
    await setup(client)
    (enabled / "acme.txt").write_text(text(fields()))
    answers = await asyncio.gather(queue(client), queue(client))
    ids = {a["data"]["task_id"] for a in answers}
    assert len(ids) == 1
    await asyncio.gather(invoice_agent.run_one(factory), invoice_agent.run_one(factory))
    task_id = ids.pop()
    r = await client.get(f"/api/v1/assistant/invoice-tasks/{task_id}", headers=PROPOSER)
    data = r.json()["data"]
    assert data["state"] == "COMPLETED"
    assert data["items"][0]["state"] == "SIMULATED"
    assert data["items"][0]["explorer_url"] is None
    assert data["items"][0]["amount_eth"] == "0.00001"
    await queue(client)
    await invoice_agent.run_one(factory)
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(ExecutionAttempt)) == 1
        assert await session.scalar(select(func.count()).select_from(InvoiceRecord)) == 1


@pytest.mark.asyncio
async def test_scope_and_ambiguity(file_client, enabled, monkeypatch, tmp_path):
    client, factory = file_client
    await setup(client)
    (enabled / "acme.txt").write_text(text(fields()))
    second = tmp_path / "second"
    second.mkdir()
    (second / "acme.txt").write_text(text(fields("OTHER-001")))
    monkeypatch.setattr(get_settings(), "invoice_search_roots", [str(enabled), str(second)])
    answer = await queue(client)
    assert answer["kind"] == "invoice_choices" and len(answer["data"]["choices"]) == 2
    for choice in answer["data"]["choices"]:
        assert set(choice) == {"id", "name", "folder"}
    chosen = await queue(client, selected_file_id=answer["data"]["choices"][0]["id"])
    assert chosen["kind"] == "invoice_task"
    for command in [
        "Find ../acme.txt and pay it",
        "Find /etc/acme.txt and pay it",
        "Find https://evil.example/acme.txt and pay it",
    ]:
        r = await client.post("/api/v1/assistant/query", headers=PROPOSER, json={"prompt": command})
        assert r.status_code == 422
    (enabled / "alias.txt").symlink_to(enabled / "acme.txt")
    assert (await queue(client, "Find alias.txt and pay it"))["kind"] == "help"
    for headers in (ADMIN, APPROVER, {}):
        r = await client.post(
            "/api/v1/assistant/query", headers=headers, json={"prompt": "Find acme.txt and pay it"}
        )
        assert r.status_code in (401, 403)
    async with factory() as session:
        assert await session.scalar(select(ExecutionAttempt)) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["unknown", "address_swap", "model_failure", "auto_off"])
async def test_exceptions_and_flags(file_client, enabled, monkeypatch, variant):
    client, factory = file_client
    await setup(client)
    f = fields(vendor="Unknown Services") if variant == "unknown" else fields()
    document = text(f)
    if variant == "address_swap":
        document += "\nPayout: 0x" + "22" * 20
    (enabled / "acme.txt").write_text(document)
    monkeypatch.setattr(invoices, "extract_invoice", AsyncMock(return_value=(f, 1)))
    if variant == "model_failure":
        monkeypatch.setattr(invoices, "extract_invoice", AsyncMock(side_effect=TimeoutError()))
    if variant == "auto_off":
        monkeypatch.setattr(get_settings(), "auto_execute_enabled", False)
    answer = await queue(client)
    await invoice_agent.run_one(factory)
    data = (
        await client.get(
            "/api/v1/assistant/invoice-tasks/" + answer["data"]["task_id"], headers=PROPOSER
        )
    ).json()["data"]
    assert data["items"][0]["state"] == (
        "CHECKED"
        if variant == "auto_off"
        else "NEEDS_HUMAN_REVIEW"
        if variant == "model_failure"
        else "BLOCKED"
    )
    async with factory() as session:
        assert await session.scalar(select(ExecutionAttempt)) is None


@pytest.mark.asyncio
async def test_cancellation_before_execution(file_client, enabled, monkeypatch):
    client, factory = file_client
    await setup(client)
    (enabled / "acme.txt").write_text(text(fields()))
    started, release = asyncio.Event(), asyncio.Event()

    async def extract(document):
        started.set()
        await release.wait()
        return fields(), 1

    monkeypatch.setattr(invoices, "extract_invoice", extract)
    answer = await queue(client)
    task_id = answer["data"]["task_id"]
    work = asyncio.create_task(invoice_agent.run_one(factory))
    await asyncio.wait_for(started.wait(), 5)
    assert (
        await client.post(f"/api/v1/assistant/invoice-tasks/{task_id}/cancel", headers=ADMIN)
    ).status_code == 403
    assert (
        await client.post(f"/api/v1/assistant/invoice-tasks/{task_id}/cancel", headers=PROPOSER)
    ).status_code == 200
    release.set()
    await work
    data = (
        await client.get(f"/api/v1/assistant/invoice-tasks/{task_id}", headers=PROPOSER)
    ).json()["data"]
    assert data["state"] == "CANCELLED"
    async with factory() as session:
        assert await session.scalar(select(Proposal)) is None
        assert await session.scalar(select(ExecutionAttempt)) is None


@pytest.mark.asyncio
async def test_stale_worker_not_replayed(file_client, enabled):
    client, factory = file_client
    await setup(client)
    (enabled / "acme.txt").write_text(text(fields()))
    answer = await queue(client)
    task_id = answer["data"]["task_id"]
    async with factory() as session:
        row = await session.get(InvoiceAgentTask, task_id)
        row.state = "RUNNING"
        row.lease_until = "2020-01-01T00:00:00+00:00"
        await session.commit()
    await invoice_agent.run_one(factory)
    data = (
        await client.get(f"/api/v1/assistant/invoice-tasks/{task_id}", headers=PROPOSER)
    ).json()["data"]
    assert data["state"] == "NEEDS_ATTENTION"
    async with factory() as session:
        assert await session.scalar(select(ExecutionAttempt)) is None


@pytest.mark.asyncio
async def test_pending_batch_requires_explicit_command(file_client, enabled, monkeypatch):
    from app.services import assistant

    client, factory = file_client
    await setup(client)
    monkeypatch.setattr(
        assistant, "request_json", AsyncMock(return_value=({"action": "pay_pending_invoices"}, 1))
    )
    response = await client.post(
        "/api/v1/assistant/query",
        headers=PROPOSER,
        json={"prompt": "What invoices are pending?"},
    )
    assert response.status_code == 422
    monkeypatch.setattr(get_settings(), "auto_execute_enabled", False)
    invoice_id = await invoices.ingest(factory, text(fields()))
    async with factory() as session:
        invoice = await session.get(InvoiceRecord, invoice_id)
        assert invoice.state == "CHECKED"
    monkeypatch.setattr(get_settings(), "auto_execute_enabled", True)
    answer = await queue(client, "Pay all pending invoices from approved vendors.")
    await invoice_agent.run_one(factory)
    data = (
        await client.get(
            "/api/v1/assistant/invoice-tasks/" + answer["data"]["task_id"],
            headers=PROPOSER,
        )
    ).json()["data"]
    assert data["items"][0]["state"] == "SIMULATED"
    assert (await queue(client, "Pay all pending invoices from approved vendors."))[
        "kind"
    ] == "help"
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(ExecutionAttempt)) == 1


@pytest.mark.asyncio
async def test_saved_vendor_payment_binding(file_client, enabled, monkeypatch):
    from app.exceptions import SigningRejectedError
    from app.models.assistant import AssistantPaymentDraft
    from app.models.invoices import Vendor
    from app.schemas import NormalizedAction
    from app.services import assistant
    from app.services.vendor_payments import validate_binding, validate_vendor_authority

    client, factory = file_client
    await setup(client)
    monkeypatch.setattr(
        assistant, "request_json", AsyncMock(return_value=({"action": "payment"}, 1))
    )
    answer = await queue(client, "Pay Workshop Services 0.00001 ETH")
    assert answer["kind"] == "payment" and answer["data"]["amount_eth"] == "0.00001"
    draft_id = answer["data"]["draft_id"]
    async with factory() as session:
        draft = await session.get(AssistantPaymentDraft, draft_id)
        await validate_binding(session, draft)
        draft.proposal_id = "binding-fixture"
        session.add(
            Proposal(
                id="binding-fixture",
                recipient=draft.recipient,
                amount_wei=draft.amount_wei,
                chain_id=11155111,
                agent_prompt=draft.prompt,
            )
        )
        await session.commit()
        vendor = await session.get(Vendor, "workshop")
        vendor.version += 1
        await session.commit()
        action = NormalizedAction(
            proposal_id="binding-fixture",
            correlation_id="binding",
            recipient=draft.recipient,
            amount_wei=int(draft.amount_wei),
        )
        with pytest.raises(SigningRejectedError):
            await validate_vendor_authority(session, action)
    for prompt in [
        "Pay Unknown 0.00001 ETH",
        "Pay Workshop Services 0.1 ETH",
        "Pay Workshop Services 5000 INR",
    ]:
        response = await client.post(
            "/api/v1/assistant/query", headers=PROPOSER, json={"prompt": prompt}
        )
        assert response.status_code == 422
