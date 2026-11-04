"""Bounded local invoice discovery and durable commands; existing intake keeps authority."""

import asyncio
import hashlib
import json
import os
import re
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select

from app.core.config import get_settings
from app.core.security import reject_credentials_in_text
from app.models import ExecutionAttempt, Proposal, Transaction, utc_now_str
from app.models.invoice_agent import InvoiceAgentItem, InvoiceAgentTask
from app.models.invoices import InvoiceRecord
from app.services.audit import AuditService
from app.services.execution_lock import lock_execution
from app.services.funding import refuse
from app.services.invoice_watcher import MAX_FILE_BYTES, parse_document
from app.services.invoices import emit, execute_invoice, ingest

FINAL = {"COMPLETED", "NEEDS_ATTENTION", "CANCELLED", "FAILED"}
FILENAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._()-]{0,119}\.(?:pdf|eml|txt)$", re.I)


class CommandCancelled(asyncio.CancelledError):
    pass


def roots():
    s = get_settings()
    configured = s.invoice_search_roots or [s.invoice_inbox]
    return list(dict.fromkeys(Path(value).expanduser().resolve() for value in configured))


def command_filename(prompt):
    # A model never supplies a path. The filename must occur explicitly in the user command.
    value = re.sub(r"^\s*(?:hey\s+)?(?:kiteshield|kite shield|mango)[, :]*", "", prompt, flags=re.I)
    match = re.fullmatch(
        r'\s*(?:find|process|pay)\s+["\']?(.+?\.(?:pdf|txt|eml))["\']?'
        r"(?:\s+and\s+(?:pay|process)(?:\s+it)?)?[.!]?\s*",
        value,
        re.I,
    )
    if not match or not FILENAME.fullmatch(match[1]) or ".." in match[1]:
        refuse(
            "FILENAME_REQUIRED",
            "Say: Find invoice.pdf and pay it. Use a filename, not a path or URL.",
        )
    return match[1]


def discover(filename):
    found = []
    for root in roots():
        if not root.is_dir():
            continue
        # One explicitly configured directory level; never recurse through the user's disk.
        with os.scandir(root) as entries:
            for count, entry in enumerate(entries):
                if count >= 1000:
                    refuse(
                        "FOLDER_TOO_LARGE",
                        "Use a dedicated invoice folder with fewer than 1000 entries.",
                    )
                if entry.name.casefold() != filename.casefold() or not entry.is_file(
                    follow_symlinks=False
                ):
                    continue
                info = entry.stat(follow_symlinks=False)
                if not 0 < info.st_size <= MAX_FILE_BYTES:
                    continue
                identity = (
                    f"{root}/{entry.name}:{info.st_dev}:{info.st_ino}:"
                    f"{info.st_mtime_ns}:{info.st_size}"
                )
                found.append(
                    {
                        "id": hashlib.sha256(identity.encode()).hexdigest(),
                        "name": entry.name,
                        "folder": root.name,
                        "_root": root,
                        "_stat": (info.st_dev, info.st_ino, info.st_mtime_ns, info.st_size),
                    }
                )
                if len(found) > 20:
                    refuse(
                        "TOO_MANY_MATCHES",
                        "Use a more specific filename or a smaller search scope.",
                    )
    return found


def read_choice(choice):
    # A held directory descriptor prevents symlink/rename races in parent directories.
    directory = os.open(choice["_root"], os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        fd = os.open(choice["name"], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
        with os.fdopen(fd, "rb") as handle:
            info = os.fstat(handle.fileno())
            if (
                not stat.S_ISREG(info.st_mode)
                or (info.st_dev, info.st_ino, info.st_mtime_ns, info.st_size) != choice["_stat"]
            ):
                raise ValueError("DOCUMENT_CHANGED")
            raw = handle.read(MAX_FILE_BYTES + 1)
            after = os.fstat(handle.fileno())
            if (after.st_mtime_ns, after.st_size) != (info.st_mtime_ns, info.st_size):
                raise ValueError("DOCUMENT_CHANGED")
    finally:
        os.close(directory)
    return parse_document(raw, Path(choice["name"]).suffix)


async def create_task(session, prompt, actor, *, selected_id=None, pending=False):
    if not get_settings().invoice_intake_enabled:
        refuse("INVOICE_INTAKE_DISABLED", "Invoice intake is disabled on this backend.")
    reject_credentials_in_text(prompt)
    content = []
    if pending:
        # Only already checked, unexecuted invoices. Never reopen blocked/terminal states.
        rows = (
            await session.scalars(
                select(InvoiceRecord)
                .where(InvoiceRecord.state == "CHECKED")
                .order_by(InvoiceRecord.created_at)
                .limit(get_settings().invoice_agent_batch_limit)
            )
        ).all()
        content = [
            {
                "name": "Checked invoice",
                "text": None,
                "digest": row.document_hash,
                "invoice_id": row.id,
            }
            for row in rows
        ]
        if not content:
            return {
                "kind": "help",
                "title": "No eligible pending invoices",
                "message": "No checked invoices are waiting. "
                "Blocked and unknown-vendor invoices need review.",
            }
    else:
        filename = command_filename(prompt)
        choices = await asyncio.to_thread(discover, filename)
        if not choices:
            return {
                "kind": "help",
                "title": "Invoice not found",
                "message": "Put that file in the configured invoice folder. "
                "Only its PDF, TXT or EML files are searchable.",
            }
        if selected_id:
            choices = [row for row in choices if row["id"] == selected_id]
            if not choices:
                refuse("FILE_SELECTION_CHANGED", "File selection changed. Search again.")
        if len(choices) > 1:
            return {
                "kind": "invoice_choices",
                "title": "Which invoice?",
                "data": {
                    "choices": [{k: row[k] for k in ("id", "name", "folder")} for row in choices]
                },
                "message": "Several configured folders contain that filename. Choose one.",
            }
        try:
            text, digest = await asyncio.to_thread(read_choice, choices[0])
            reject_credentials_in_text(text)
            settings = get_settings()
            if any(
                value and value in text
                for value in (settings.cdp_api_key_id, settings.cdp_api_key_secret)
            ):
                raise ValueError("CREDENTIAL_IN_DOCUMENT")
        except Exception:
            refuse(
                "INVOICE_UNREADABLE",
                "Cannot read that invoice. Use a small text PDF, UTF-8 TXT or supported EML.",
            )
        content = [{"name": choices[0]["name"], "text": text, "digest": digest, "invoice_id": None}]
    key = hashlib.sha256(
        (
            actor
            + ":"
            + get_settings().execution_mode
            + ":"
            + ":".join(row["digest"] for row in content)
        ).encode()
    ).hexdigest()
    await lock_execution(session)
    previous = await session.scalar(
        select(InvoiceAgentTask)
        .where(
            InvoiceAgentTask.command_digest == key,
            InvoiceAgentTask.created_at >= (datetime.now(UTC) - timedelta(minutes=5)).isoformat(),
        )
        .order_by(InvoiceAgentTask.created_at.desc())
        .limit(1)
    )
    if previous:
        snapshot = await task_data(session, previous)
        settings = get_settings()
        if (previous.state == "COMPLETED" and not previous.cancel_requested
                and settings.auto_execute_enabled and settings.invoice_auto_execute_enabled
                and (settings.execution_mode == "simulated" or settings.invoice_live_execution_enabled)
                and snapshot["items"]
                and all(item["state"] == "CHECKED" for item in snapshot["items"])):
            previous.state, previous.stage, previous.reason = "QUEUED", "QUEUED", None
            await AuditService().record_event(
                session, "INVOICE_COMMAND_RESUMED", previous.id, actor,
                {"reason": "EXPLICIT_REQUEST_FOR_EXISTING_CHECKED_INVOICE"},
            )
            return {
                "kind": "invoice_task", "title": "Invoice task",
                "message": "Resuming the same checked invoice under current authorization. "
                "No duplicate invoice or payment is created.",
                "data": await task_data(session, previous),
            }
        return {
            "kind": "invoice_task",
            "title": "Invoice task",
            "message": "This document already has a task. "
            "Showing the same result; no second payment.",
            "data": await task_data(session, previous),
        }
    task = InvoiceAgentTask(actor=actor, command_digest=key, mode=get_settings().execution_mode)
    session.add(task)
    await session.flush()
    for index, item in enumerate(content):
        session.add(
            InvoiceAgentItem(
                task_id=task.id,
                position=index,
                filename=item["name"],
                document_text=item["text"],
                document_hash=item["digest"],
                invoice_id=item["invoice_id"],
            )
        )
    await AuditService().record_event(
        session,
        "INVOICE_COMMAND_QUEUED",
        task.id,
        actor,
        {"file_count": len(content), "mode": task.mode},
    )
    await session.flush()
    return {"kind": "invoice_task", "title": "Invoice task", "data": await task_data(session, task)}


async def task_data(session, task):
    items = (
        await session.scalars(
            select(InvoiceAgentItem)
            .where(InvoiceAgentItem.task_id == task.id)
            .order_by(InvoiceAgentItem.position)
        )
    ).all()
    results = []
    for item in items:
        row = await session.get(InvoiceRecord, item.invoice_id) if item.invoice_id else None
        transaction = (
            await session.scalar(
                select(Transaction).where(Transaction.proposal_id == row.proposal_id)
            )
            if row and row.proposal_id
            else None
        )
        proposal = await session.get(Proposal, row.proposal_id) if row and row.proposal_id else None
        explorer = (
            f"https://sepolia.etherscan.io/tx/{transaction.tx_hash}"
            if transaction
            and proposal
            and proposal.chain_id == 11155111
            and transaction.execution_mode == "sepolia"
            and re.fullmatch(r"0x[0-9a-fA-F]{64}", transaction.tx_hash or "")
            and transaction.execution_outcome in ("SUBMITTED", "CONFIRMED", "REVERTED", "UNCERTAIN")
            else None
        )
        fields = json.loads(row.extraction_json) if row and row.extraction_json else {}
        results.append(
            {
                "filename": item.filename,
                "invoice_id": item.invoice_id,
                "state": row.state if row else "QUEUED",
                "reason": row.reason if row else None,
                "proposal_id": row.proposal_id if row else None,
                "explorer_url": explorer,
                "amount_eth": fields.get("amount_eth"),
                "vendor_name": fields.get("vendor_name"),
            }
        )
    return {
        "task_id": task.id,
        "state": task.state,
        "stage": task.stage,
        "mode": task.mode,
        "reason": task.reason,
        "cancel_requested": task.cancel_requested,
        "items": results,
        "created_at": task.created_at,
        "can_cancel": task.state not in FINAL,
    }


async def cancel_task(session, task_id, actor):
    await lock_execution(session)
    task = await session.get(InvoiceAgentTask, task_id, populate_existing=True)
    if task is None:
        refuse("NOT_FOUND", "Invoice task not found.", 404)
    if task.actor != actor:
        refuse("ROLE_FORBIDDEN", "This role cannot cancel that task.", 403)
    if task.state not in FINAL:
        task.cancel_requested = True
        if task.state == "QUEUED":
            task.state, task.stage = "CANCELLED", "CANCELLED"
        await AuditService().record_event(
            session, "INVOICE_COMMAND_CANCEL_REQUESTED", task.id, actor, {"state": task.state}
        )
    return await task_data(session, task)


async def require_not_cancelled(session, invoice_id):
    cancelled = await session.scalar(
        select(InvoiceAgentTask.id)
        .join(InvoiceAgentItem, InvoiceAgentItem.task_id == InvoiceAgentTask.id)
        .where(
            InvoiceAgentItem.invoice_id == invoice_id, InvoiceAgentTask.cancel_requested.is_(True)
        )
    )
    if cancelled:
        from app.exceptions import SigningRejectedError

        raise SigningRejectedError("INVOICE_COMMAND_CANCELLED")


async def run_one(factory):
    async with factory() as session:
        await lock_execution(session)
        now = utc_now_str()
        for stale in (
            await session.scalars(
                select(InvoiceAgentTask).where(
                    InvoiceAgentTask.state == "RUNNING", InvoiceAgentTask.lease_until < now
                )
            )
        ).all():
            stale.state, stale.reason = (
                "NEEDS_ATTENTION",
                "WORKER_INTERRUPTED_CHECK_EXISTING_INVOICES",
            )
        if await session.scalar(
            select(InvoiceAgentTask.id).where(InvoiceAgentTask.state == "RUNNING")
        ):
            await session.commit()
            return False
        task = await session.scalar(
            select(InvoiceAgentTask)
            .where(InvoiceAgentTask.state == "QUEUED")
            .order_by(InvoiceAgentTask.created_at)
            .limit(1)
        )
        if not task:
            await session.commit()
            return False
        task.state, task.stage = "RUNNING", "PROCESSING_INVOICE"
        task.lease_until = (datetime.now(UTC) + timedelta(seconds=300)).isoformat()
        task_id, mode = task.id, task.mode
        items = (
            await session.scalars(
                select(InvoiceAgentItem)
                .where(InvoiceAgentItem.task_id == task_id)
                .order_by(InvoiceAgentItem.position)
            )
        ).all()
        await session.commit()
    try:
        for item in items:

            async def progress(stage, invoice_id, item_id=item.id):
                async with factory() as session:
                    await lock_execution(session)
                    task = await session.get(InvoiceAgentTask, task_id, populate_existing=True)
                    if task.cancel_requested:
                        raise CommandCancelled()
                    if task.state != "RUNNING":
                        raise ValueError("TASK_LEASE_LOST")
                    if mode != get_settings().execution_mode:
                        raise ValueError("EXECUTION_MODE_CHANGED")
                    task.stage, task.updated_at = stage, utc_now_str()
                    task.lease_until = (datetime.now(UTC) + timedelta(seconds=300)).isoformat()
                    if invoice_id:
                        (await session.get(InvoiceAgentItem, item_id)).invoice_id = invoice_id
                    await session.commit()

            await progress("PROCESSING_INVOICE", item.invoice_id)
            if item.document_text is None:
                await progress("EXECUTION_CHECK", item.invoice_id)
                await execute_invoice(factory, item.invoice_id)
            else:
                invoice_id = await ingest(
                    factory, item.document_text, content_hash=item.document_hash, progress=progress
                )
                # An explicitly requested, previously CHECKED invoice may now be eligible.
                # The existing service revalidates authority and ignores terminal records.
                await progress("EXECUTION_CHECK", invoice_id)
                await execute_invoice(factory, invoice_id)
                await progress("RESULT_RECORDED", invoice_id)
        async with factory() as session:
            await lock_execution(session)
            task = await session.get(InvoiceAgentTask, task_id)
            result = await task_data(session, task)
            attention = any(
                item["state"] not in ("SIMULATED", "VERIFIED", "PAID", "CHECKED")
                for item in result["items"]
            )
            task.state = "NEEDS_ATTENTION" if attention else "COMPLETED"
            task.stage = "RESULT_RECORDED"
            settings = get_settings()
            enabled = (settings.auto_execute_enabled and settings.invoice_auto_execute_enabled
                       and (settings.execution_mode == "simulated" or settings.invoice_live_execution_enabled))
            task.reason = (
                ("EXECUTION_NOT_STARTED_CHECK_EXISTING_PROPOSAL" if enabled else "AUTOMATION_DISABLED")
                if any(item["state"] == "CHECKED" for item in result["items"])
                else None
            )
            await session.commit()
    except CommandCancelled:
        async with factory() as session:
            await lock_execution(session)
            task = await session.get(InvoiceAgentTask, task_id)
            task.state, task.stage = "CANCELLED", "CANCELLED"
            for item in (
                await session.scalars(
                    select(InvoiceAgentItem).where(InvoiceAgentItem.task_id == task_id)
                )
            ).all():
                row = await session.get(InvoiceRecord, item.invoice_id) if item.invoice_id else None
                if row is None:
                    row = await session.scalar(
                        select(InvoiceRecord).where(
                            InvoiceRecord.document_hash == item.document_hash
                        )
                    )
                    if row:
                        item.invoice_id = row.id
                attempt = (
                    await session.scalar(
                        select(ExecutionAttempt).where(
                            ExecutionAttempt.proposal_id == row.proposal_id
                        )
                    )
                    if row and row.proposal_id
                    else None
                )
                if (
                    row
                    and not (attempt and attempt.raw_transaction)
                    and row.state in ("OBSERVED", "CHECKED")
                ):
                    await emit(session, row, "NEEDS_HUMAN_REVIEW", "AGENT_TASK_CANCELLED")
            await session.commit()
    except asyncio.CancelledError:
        raise
    except Exception:
        async with factory() as session:
            await lock_execution(session)
            task = await session.get(InvoiceAgentTask, task_id)
            task.state, task.reason = "NEEDS_ATTENTION", "TASK_INTERRUPTED_CHECK_EXISTING_INVOICES"
            await session.commit()
    return True


async def monitor(factory):
    while True:
        try:
            await run_one(factory)
        except asyncio.CancelledError:
            raise
        except Exception:
            from app.core.logging import get_logger

            get_logger("invoice_commands").warning(
                "Invoice command worker unavailable; no authority inferred"
            )
        await asyncio.sleep(2)
