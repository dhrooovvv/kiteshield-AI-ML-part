"""Exercise the three prepared EML examples using real models and simulated payments."""

import asyncio
import json
import os
import tempfile
from pathlib import Path

from invoice_lab import configure_environment, isolated_runtime, run_case

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "docs/invoice-demo/sepolia-prepared-2026-10-24"


async def main():
    with tempfile.TemporaryDirectory(prefix="kite-three-invoices-") as temporary:
        directory = Path(temporary)
        configure_environment(directory)
        os.environ["HF_HUB_OFFLINE"] = "1"
        from app.core.config import get_settings
        from app.services.invoice_watcher import parse_document

        settings = get_settings()
        settings.invoice_learned_screening_enabled = True
        settings.invoice_learned_evaluated = True
        manifest = json.loads((EXAMPLES / "manifest.json").read_text())
        report = {
            "simulation_only": True,
            "real_models": True,
            "cases": [],
            "note": "Uses the isolated fixture recipient, NOT the live vendor registry. "
            "No live payment is authorized by these files or this test.",
        }
        with isolated_runtime() as rpc:
            for index, example in enumerate(manifest["examples"]):
                document, digest = parse_document((EXAMPLES / example["file"]).read_bytes(), ".eml")
                assert digest == example["sha256"]
                expected = {
                    key: example[key] for key in ("invoice_number", "amount_eth", "due_date")
                }
                expected["vendor_name"] = manifest["vendor_name"]
                case = {
                    "id": example["invoice_number"],
                    "kind": "benign",
                    "category": "prepared_demo",
                    "text": document,
                    "expected": expected,
                }
                case_dir = directory / str(index)
                case_dir.mkdir()
                result = await run_case(case, case_dir)
                report["cases"].append({"file": example["file"], "sha256": digest, **result})
                print(example["file"], result["state"], flush=True)
            report["rpc_attempts"] = len(rpc)
        target = ROOT / "backend/reports/invoice_examples_simulation_20261024.json"
        with target.open("x") as stream:
            json.dump(report, stream, indent=2)
            stream.write("\n")
        assert report["rpc_attempts"] == 0
        assert all(
            case["state"] == "SIMULATED"
            and not case["wrong_payee"]
            and all(case["field_matches"].values())
            for case in report["cases"]
        )


if __name__ == "__main__":
    asyncio.run(main())
