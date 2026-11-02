"""Offline E2A email screening evaluation. Never imports payment entry points."""

import argparse
import asyncio
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
from collections import Counter
from pathlib import Path

from invoice_lab import configure_environment


async def run(repo, output):
    with tempfile.TemporaryDirectory(prefix="kite-email-benchmark-") as temporary:
        configure_environment(Path(temporary))
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        from app.core.config import get_settings
        from app.services.invoice_screening import canonical_text, invoice_screening, profile
        from app.services.invoice_watcher import parse_document

        get_settings().invoice_learned_screening_enabled = True
        manifests = [
            "dataset/prompt-injection/manifest.jsonl",
            "dataset/prompt-injection/benign/manifest.jsonl",
            "dataset/prompt-injection/adaptive-supplement/manifest.jsonl",
        ]
        report = {
            "scope": "Offline screening only; no Gemma, proposals, DB, signing, RPC or payments. "
            "Parser rejection is NOT a model detection. No threshold tuning. "
            "Related renderings are correlated; row rates are descriptive, not independent trials.",
            "repository": "https://github.com/tokencanopy/e2a-bench",
            "commit": subprocess.check_output(  # noqa: S603 -- fixed git arguments, no shell
                [shutil.which("git"), "-C", str(repo), "rev-parse", "HEAD"], text=True
            ).strip(),
            "profile": profile(),
            "manifests": {},
            "complete": False,
            "cases": [],
        }
        if output.exists():
            raise ValueError("Refusing to overwrite a prior run")
        output.parent.mkdir(parents=True, exist_ok=True)
        await invoice_screening._service()._ensure_models()
        for manifest in manifests:
            raw_manifest = (repo / manifest).read_bytes()
            report["manifests"][manifest] = hashlib.sha256(raw_manifest).hexdigest()
            for line in raw_manifest.decode().splitlines():
                entry = json.loads(line)
                path = (repo / entry["eml_path"]).resolve()
                if not path.is_relative_to(repo.resolve()) or path.suffix != ".eml":
                    raise ValueError("Unsafe manifest path")
                raw = path.read_bytes()
                row = {
                    "id": entry["id"],
                    "malicious": entry["label"]["is_malicious"],
                    "surface": entry["surface"],
                    "provenance": entry["provenance"],
                    "slice": manifest,
                    "sha256": hashlib.sha256(raw).hexdigest(),
                }
                started = time.monotonic()
                try:
                    text, _ = parse_document(raw, ".eml")
                except Exception as error:
                    row.update(parser="rejected", reason=str(error)[:100])
                else:
                    row["parser"] = "accepted"
                    row["gate"] = await invoice_screening.screen(text)
                    # Independently measure models when production rules short-circuit.
                    if row["gate"]["horizon"]["status"] == "not_run":
                        try:
                            import html

                            row["models"] = await asyncio.to_thread(
                                invoice_screening._infer,
                                canonical_text(html.unescape(text)),
                                time.monotonic() + get_settings().ai_ml_inference_timeout_seconds,
                            )
                        except Exception as error:
                            row["models"] = {
                                "classification": "ERROR",
                                "reason": type(error).__name__,
                            }
                    else:
                        row["models"] = row["gate"]
                row["elapsed_ms"] = round((time.monotonic() - started) * 1000)
                report["cases"].append(row)
                if len(report["cases"]) % 50 == 0:
                    output.write_text(json.dumps(report, indent=2) + "\n")
                    print(f"Processed {len(report['cases'])}", flush=True)
        report["complete"] = True
        report["counts"] = dict(
            Counter(
                ("attack" if row["malicious"] else "benign")
                + ":"
                + (
                    "parser_rejected"
                    if row["parser"] != "accepted"
                    else row["gate"]["classification"]
                )
                for row in report["cases"]
            )
        )
        output.write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report["counts"]), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repository", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    asyncio.run(run(args.repository, args.output))
