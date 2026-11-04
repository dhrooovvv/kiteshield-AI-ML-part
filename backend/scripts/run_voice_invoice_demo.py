"""Isolated simulation for voice/file commands. No funded config or blockchain RPC.

Run from backend: .venv/bin/python -m scripts.run_voice_invoice_demo
"""

import argparse
import asyncio
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path


def write_pdf(path, lines):
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    writer = PdfWriter()
    page = writer.add_blank_page(width=595, height=842)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
    )
    stream = DecodedStreamObject()
    escaped = [line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") for line in lines]
    stream.set_data(
        (
            "BT /F1 12 Tf 48 780 Td 18 TL "
            + "\n".join(f"({line}) Tj T*" for line in escaped)
            + " ET"
        ).encode("ascii")
    )
    page[NameObject("/Contents")] = writer._add_object(stream)
    with path.open("wb") as handle:
        writer.write(handle)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--port", type=int, default=8130)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--documents", type=Path, help="Explicit directory of synthetic demo files")
    parser.add_argument("--inbox", type=Path, help="Explicit watched simulation inbox")
    parser.add_argument(
        "--hackathon-pack", action="store_true", help="Larger fixture-only daily budget"
    )
    args = parser.parse_args()
    directory = (args.directory or Path(tempfile.mkdtemp(prefix="kite-voice-demo-"))).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    documents = (args.documents or directory / "documents").resolve()
    inbox = (args.inbox or directory / "inbox").resolve()
    for folder in (documents, inbox):
        folder.mkdir(parents=True, exist_ok=True)
    from scripts.invoice_lab import configure_environment

    configure_environment(directory)
    os.environ.update(
        {
            "INVOICE_MODEL": "kiteshield-gemma4:12b-q4km",
            "INVOICE_INBOX": str(inbox),
            "INVOICE_SEARCH_ROOTS": json.dumps([str(documents)]),
            "INVOICE_LEARNED_SCREENING_ENABLED": "true",
            "INVOICE_POLL_SECONDS": "5",
            "APP_CORS_ORIGINS": "http://localhost:3000,http://127.0.0.1:3000,http://localhost:4319,http://127.0.0.1:4319",
            "FAUCET_ENABLED": "false",
            "CDP_API_KEY_ID": "",
            "CDP_API_KEY_SECRET": "",
        }
    )
    from app.core.config import get_settings

    get_settings.cache_clear()
    settings = get_settings()
    from app.services.blockchain import BlockchainService

    def forbidden(*args, **kwargs):
        raise RuntimeError("Blockchain RPC forbidden in this isolated simulation")

    BlockchainService._get_w3 = forbidden
    from app.services.invoice_screening import profile

    try:
        report = json.loads(
            (
                Path(__file__).resolve().parents[1]
                / "reports/invoice_horizon_bastion_development.json"
            ).read_text()
        )
        clear = [row for row in report["cases"] if row["kind"] == "benign_invoice"]
        settings.invoice_learned_evaluated = (
            report["profile"] == profile()
            and len(clear) >= 4
            and all(row["combined"]["classification"] == "BENIGN" for row in clear)
        )
    except (OSError, KeyError, ValueError, TypeError):
        settings.invoice_learned_evaluated = False
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.models import Base, ExecutionControl, Policy
    from app.models.invoices import Vendor

    async def seed():
        engine = create_async_engine(settings.database_url)
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            if not await session.scalar(select(Policy.id).limit(1)):
                session.add(
                    Policy(
                        version=1,
                        is_active=True,
                        max_amount_wei=str(10**14),
                        daily_limit_wei=str(10**15 if args.hackathon_pack else 10**14),
                        escalation_threshold_wei=str(8 * 10**13),
                        allowed_recipients=json.dumps(["0x" + "1" * 40]),
                    )
                )
                session.add(
                    ExecutionControl(id="global", active=False, reason="", changed_by="simulation")
                )
                session.add(
                    Vendor(
                        id="development-workshop",
                        name="Development Workshop",
                        payout_address="0x" + "1" * 40,
                        maximum_wei=str(5 * 10**13),
                        version=1,
                        active=True,
                        updated_by="simulation-setup",
                    )
                )
                await session.commit()
        await engine.dispose()

    asyncio.run(seed())
    today = datetime.now(UTC).date().isoformat()
    prefix = datetime.now(UTC).strftime("%Y%m%d")
    for filename, vendor, amount, number, extra in [
        ("acme.pdf", "Development Workshop", "0.00001", "001", []),
        ("newvendor.pdf", "New Vendor Services", "0.00002", "002", []),
        ("swapped.pdf", "Development Workshop", "0.00001", "003", ["Payout: 0x" + "2" * 40]),
    ]:
        path = documents / filename
        if not path.exists():
            write_pdf(
                path,
                [
                    f"Vendor: {vendor}",
                    f"Invoice number: VOICE-{prefix}-{number}",
                    f"Amount: {amount} ETH",
                    f"Due date: {today}",
                    *extra,
                ],
            )
    source = documents / "acme.pdf"
    duplicate = documents / "duplicate.pdf"
    if not duplicate.exists():
        duplicate.write_bytes(source.read_bytes())
    proactive = documents / "proactive.txt"
    if not proactive.exists():
        proactive.write_text(
            f"Vendor: Development Workshop\nInvoice number: VOICE-{prefix}-004\n"
            f"Amount: 0.00001 ETH\nDue date: {today}"
        )
    print(f"Simulation API: http://127.0.0.1:{args.port}", flush=True)
    print(f"Authorized documents: {documents}", flush=True)
    print(f"Proactive inbox: {inbox}", flush=True)
    print("Public simulation Proposer: invoice-lab-proposer-fixture", flush=True)
    print("Public simulation Policy administrator: invoice-lab-policy-admin-fixture", flush=True)
    print("Horizon + Bastion enabled; no real wallet or blockchain RPC.", flush=True)
    if args.prepare_only:
        return
    import uvicorn

    from app.main import app

    uvicorn.run(app, host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
