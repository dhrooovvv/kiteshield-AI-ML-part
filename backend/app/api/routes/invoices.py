"""Invoice administration and observation. No HTTP endpoint activates live execution."""

import asyncio
import json
from pathlib import Path

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.core.security import require_policy_admin, require_proposer, verify_api_key
from app.db import get_db_session
from app.exceptions import ValidationError
from app.models import ExecutionAttempt, Proposal, Transaction
from app.models.invoices import InvoiceEvent, InvoiceIdleState, InvoiceRecord, Vendor
from app.schemas import APIResponse
from app.schemas.invoices import InvoiceTextInput, VendorInput
from app.services.invoice_screening import enabled as learned_invoice_screening_enabled
from app.services.invoice_watcher import (
    MAX_FILE_BYTES,
    SUPPORTED_DOCUMENT_SUFFIXES,
    parse_document,
    watch_once,
)
from app.services.invoices import can_recheck_invoice, ingest, recheck_invoice, save_vendor

router = APIRouter(prefix="/invoices", tags=["Accounts payable"])


@router.get("/red-team", response_model=APIResponse)
async def red_team(_: str = Depends(verify_api_key)):
    """Only a local offline simulation report; never triggers a model or execution."""
    path = Path(__file__).resolve().parents[3] / "reports" / "invoice_redteam_latest.json"
    try:
        if path.stat().st_size > 2_000_000:
            raise ValueError("Report too large")
        data = json.loads(path.read_text())
        if data.get("simulation_only") is not True:
            raise ValueError("Simulation report required")
        return APIResponse(data={**data, "available": True})
    except (OSError, ValueError, TypeError):
        return APIResponse(data={"available": False, "simulation_only": True, "attempts": []})


def vendor_data(row):
    return {
        "id": row.id,
        "name": row.name,
        "payout_address": row.payout_address,
        "maximum_wei": row.maximum_wei,
        "version": row.version,
        "active": row.active,
    }


@router.get("/vendors", response_model=APIResponse)
async def vendors(
    session: AsyncSession = Depends(get_db_session), _: str = Depends(verify_api_key)
):
    return APIResponse(data=[vendor_data(v) for v in (await session.scalars(select(Vendor))).all()])


@router.put("/vendors/{vendor_id}", response_model=APIResponse)
async def vendor_update(
    vendor_id: str,
    request: VendorInput,
    session: AsyncSession = Depends(get_db_session),
    actor: str = Depends(require_policy_admin),
):
    return APIResponse(data=vendor_data(await save_vendor(session, vendor_id, request, actor)))


@router.post("/intake", response_model=APIResponse)
async def intake(
    request: InvoiceTextInput,
    session: AsyncSession = Depends(get_db_session),
    _: str = Depends(require_proposer),
):
    factory = async_sessionmaker(session.bind, expire_on_commit=False)
    await session.commit()
    return APIResponse(data={"invoice_id": await ingest(factory, request.text)})


@router.post("/observe", response_model=APIResponse)
async def observe(
    session: AsyncSession = Depends(get_db_session), _: str = Depends(require_policy_admin)
):
    factory = async_sessionmaker(session.bind, expire_on_commit=False)
    await session.commit()
    await watch_once(factory)
    return APIResponse(data={"observed": True, "execution_activated": False})


@router.post("/{invoice_id}/recheck", response_model=APIResponse)
async def recheck(
    invoice_id: str,
    session: AsyncSession = Depends(get_db_session),
    actor: str = Depends(require_proposer),
):
    factory = async_sessionmaker(session.bind, expire_on_commit=False)
    await session.commit()
    return APIResponse(data={"invoice_id": await recheck_invoice(factory, invoice_id, actor)})


@router.post("/upload", response_model=APIResponse)
async def upload(
    request: Request,
    filename: str = Query(min_length=1, max_length=200),
    session: AsyncSession = Depends(get_db_session),
    _: str = Depends(require_proposer),
):
    """One bounded document; uses the same hash claim, checks and execution path."""
    if not get_settings().invoice_intake_enabled:
        raise ValidationError("INVOICE_INTAKE_DISABLED")
    if (
        "/" in filename
        or "\\" in filename
        or Path(filename).suffix.lower() not in SUPPORTED_DOCUMENT_SUFFIXES
    ):
        raise ValidationError("Upload a TXT, text-based PDF or EML invoice")
    raw = bytearray()
    async for chunk in request.stream():
        if len(raw) + len(chunk) > MAX_FILE_BYTES:
            raise ValidationError("Invoice must be no larger than 1 MB")
        raw.extend(chunk)
    try:
        text, digest = await asyncio.to_thread(parse_document, bytes(raw), Path(filename).suffix)
    except Exception as error:
        messages = {
            "MULTIPLE_EMAIL_ATTACHMENTS": "Multiple email attachments. Upload one invoice directly",
            "UNSUPPORTED_EMAIL_ATTACHMENT": "Upload the TXT or text PDF attachment directly",
            "UNSUPPORTED_EMAIL_CONTENT": (
                "Signed, encrypted or nested email unsupported. Upload the invoice directly"
            ),
            "EMAIL_TEXT_TOO_LARGE": "Email text exceeds 20,000 characters",
        }
        raise ValidationError(
            messages.get(
                str(error),
                "Cannot read invoice. Use UTF-8 TXT, text PDF (up to 10 pages) or valid EML",
            )
        ) from None
    factory = async_sessionmaker(session.bind, expire_on_commit=False)
    await session.commit()
    return APIResponse(data={"invoice_id": await ingest(factory, text, content_hash=digest)})


@router.get("", response_model=APIResponse)
async def status(session: AsyncSession = Depends(get_db_session), _: str = Depends(verify_api_key)):
    records = list(
        (
            await session.scalars(
                select(InvoiceRecord).order_by(InvoiceRecord.created_at.desc()).limit(50)
            )
        ).all()
    )
    items = []
    for row in records:
        tx = await session.scalar(
            select(Transaction).where(Transaction.proposal_id == row.proposal_id)
        )
        proposal = await session.get(Proposal, row.proposal_id) if row.proposal_id else None
        attempt = (
            await session.scalar(
                select(ExecutionAttempt).where(ExecutionAttempt.proposal_id == row.proposal_id)
            )
            if row.proposal_id
            else None
        )
        items.append(
            {
                "id": row.id,
                "document_hash": row.document_hash,
                "state": row.state,
                "reason": row.reason,
                "can_recheck": can_recheck_invoice(row),
                "vendor_id": row.vendor_id,
                "proposal_id": row.proposal_id,
                "extraction": json.loads(row.extraction_json) if row.extraction_json else None,
                "checks": json.loads(row.checks_json) if row.checks_json else None,
                "latency_ms": row.latency_ms,
                "created_at": row.created_at,
                "provenance": "invoice_intake",
                "proposal_status": proposal.status if proposal else None,
                "execution_mode": attempt.execution_mode if attempt else None,
                "transaction_hash": tx.tx_hash if tx and tx.execution_mode == "sepolia" else None,
                "explorer_url": f"https://sepolia.etherscan.io/tx/{tx.tx_hash}"
                if tx and tx.execution_mode == "sepolia" and tx.tx_hash
                else None,
                "events": [
                    {"stage": event.stage, "reason": event.reason, "at": event.created_at}
                    for event in (
                        await session.scalars(
                            select(InvoiceEvent)
                            .where(InvoiceEvent.invoice_id == row.id)
                            .order_by(InvoiceEvent.created_at)
                        )
                    ).all()
                ],
            }
        )
    quiet = await session.get(InvoiceIdleState, "global")
    settings = get_settings()
    return APIResponse(
        data={
            "items": items,
            "intake_enabled": settings.invoice_intake_enabled,
            "automatic_execution_enabled": settings.invoice_auto_execute_enabled,
            "live_execution_enabled": settings.invoice_live_execution_enabled,
            "execution_mode": settings.execution_mode,
            "horizon_bastion_enabled": learned_invoice_screening_enabled(),
            "horizon_bastion_evaluated": settings.invoice_learned_evaluated,
            "no_action": {
                "count": quiet.count,
                "reason": quiet.last_reason,
                "at": quiet.observed_at,
            }
            if quiet
            else None,
        }
    )
