"""Opt-in observer for stable TXT, text-PDF and bounded EML documents."""

import asyncio
import fcntl
import hashlib
import io
import stat
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

from app.core.config import get_settings
from app.models import utc_now_str
from app.models.invoices import InvoiceIdleState, InvoiceRecord
from app.services.execution_lock import lock_execution
from app.services.invoices import emit, ingest, reconcile_invoices

MAX_FILE_BYTES = 1_000_000
SUPPORTED_DOCUMENT_SUFFIXES = (".txt", ".pdf", ".eml")


def parse_document(raw, suffix):
    """Shared bounded parser for watched files and browser uploads."""
    if not raw or len(raw) > MAX_FILE_BYTES:
        raise ValueError("DOCUMENT_SIZE_INVALID")
    suffix = suffix.lower()
    if suffix not in SUPPORTED_DOCUMENT_SUFFIXES:
        raise ValueError("UNSUPPORTED_DOCUMENT_TYPE")
    if suffix == ".eml":
        from app.services.email_documents import email_text

        text = email_text(raw, parse_document)
    elif suffix == ".pdf":
        from pypdf import PdfReader

        pdf = PdfReader(io.BytesIO(raw))
        if pdf.is_encrypted or len(pdf.pages) > 10:
            raise ValueError("PLAIN_TEXT_PDF_REQUIRED")
        text = "\n".join(page.extract_text() or "" for page in pdf.pages)
    else:
        text = raw.decode("utf-8", errors="strict")
    if not text.strip() or len(text) > 20000:
        raise ValueError("NO_BOUNDED_TEXT_AVAILABLE")
    return text, hashlib.sha256(raw).hexdigest()


def read_document(path):
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_FILE_BYTES:
        raise ValueError("REGULAR_SMALL_DOCUMENT_REQUIRED")
    if path.suffix.lower() not in SUPPORTED_DOCUMENT_SUFFIXES:
        raise ValueError("UNSUPPORTED_DOCUMENT_TYPE")
    # Reject symlink races using O_NOFOLLOW; inspect the opened descriptor too.
    import os

    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as handle:
        opened = os.fstat(handle.fileno())
        if (opened.st_ino, opened.st_dev) != (before.st_ino, before.st_dev):
            raise ValueError("DOCUMENT_CHANGED")
        raw = handle.read(MAX_FILE_BYTES + 1)
    after = path.lstat()
    if len(raw) > MAX_FILE_BYTES or (before.st_mtime_ns, before.st_size, before.st_ino) != (
        after.st_mtime_ns,
        after.st_size,
        after.st_ino,
    ):
        raise ValueError("DOCUMENT_CHANGED")
    return parse_document(raw, path.suffix)


async def watch_once(factory):
    settings = get_settings()
    if not settings.invoice_intake_enabled:
        return
    directory = Path(settings.invoice_inbox).resolve()
    if not directory.is_dir():
        return  # Never create or trust a new arbitrary folder implicitly.
    # File lock also serializes multiple workers sharing the watched folder.
    with (directory / ".kiteshield-watcher.lock").open("a") as guard:
        try:
            fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        try:
            async with factory() as session:
                await lock_execution(session)
                for row in (
                    await session.scalars(
                        select(InvoiceRecord).where(InvoiceRecord.state == "OBSERVED")
                    )
                ).all():
                    if row.claim_until and row.claim_until < utc_now_str():
                        await emit(session, row, "NEEDS_HUMAN_REVIEW", "INTAKE_INTERRUPTED")
                await session.commit()
            observed = False
            quiet_reason = "NO_NEW_FILES"
            for path in sorted(directory.iterdir()):
                if (
                    path.name.startswith(".")
                    or path.suffix.lower() not in SUPPORTED_DOCUMENT_SUFFIXES
                ):
                    continue
                try:
                    text, digest = await asyncio.to_thread(read_document, path)
                    async with factory() as session:
                        exists = await session.scalar(
                            select(InvoiceRecord.id).where(InvoiceRecord.document_hash == digest)
                        )
                    if exists:
                        continue
                    await ingest(factory, text, content_hash=digest)
                    observed = True
                    break  # One new file per pass, one extraction at a time.
                except Exception:
                    # No raw filenames/document/provider errors in logs. Quiet state only.
                    quiet_reason = "UNREADABLE_DOCUMENT_NEEDS_REVIEW"
            if not observed:
                await idle(factory, quiet_reason)
            await reconcile_invoices(factory)
        finally:
            fcntl.flock(guard, fcntl.LOCK_UN)


async def idle(factory, reason):
    async with factory() as session:
        await lock_execution(session)
        row = await session.get(InvoiceIdleState, "global")
        if not row:
            row = InvoiceIdleState(id="global", count=0)
            session.add(row)
        row.count += 1
        row.last_reason, row.observed_at = reason, datetime.now(UTC).isoformat()
        await session.commit()


async def monitor(factory):
    while True:
        try:
            await watch_once(factory)
        except asyncio.CancelledError:
            raise
        except Exception:
            from app.core.logging import get_logger

            get_logger("invoice_intake").warning(
                "Invoice observation unavailable; no authority inferred"
            )
        await asyncio.sleep(get_settings().invoice_poll_seconds)
