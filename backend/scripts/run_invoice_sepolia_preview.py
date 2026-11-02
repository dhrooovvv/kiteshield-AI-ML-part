"""Connect the normal wallet/registry and real Sepolia RPC without invoice broadcasting.

Run from backend with: .venv/bin/python -m scripts.run_invoice_sepolia_preview
This preparation profile has deliberately no execution-enable argument.
"""

import json
from pathlib import Path

from eth_account import Account

from app.core.config import get_settings


def preparation_settings(settings):
    if settings.execution_mode != "sepolia" or settings.chain_id != 11155111:
        raise ValueError("Verified Sepolia configuration is required")
    settings.app_debug = False  # Never echo database parameters in this live-wallet profile.
    settings.invoice_intake_enabled = True
    settings.invoice_learned_screening_enabled = True
    settings.invoice_auto_execute_enabled = False
    settings.invoice_live_execution_enabled = False
    settings.auto_execute_enabled = False
    settings.treasury_monitor_enabled = False
    # Use the operator's persistent, explicit scope. Restarts must not silently
    # move file lookup/watching into a new temporary directory.
    Path(settings.invoice_inbox).expanduser().mkdir(parents=True, exist_ok=True)
    origins = settings.app_cors_origins.split(",")
    for origin in (
        "http://127.0.0.1:3000",
        "http://localhost:3000",
        "http://127.0.0.1:4317",
        "http://localhost:4317",
        "http://127.0.0.1:4318",
        "http://localhost:4318",
    ):
        if origin not in origins:
            origins.append(origin)
    settings.app_cors_origins = ",".join(origins)
    return settings


def apply_evaluated_invoice_profile(settings):
    """Accept only the existing measured screening profile; never infer clearance."""
    from app.services.invoice_screening import profile

    report = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "reports/invoice_examples_simulation_20261024.json"
        ).read_text()
    )
    cases = report.get("cases", [])
    if len(cases) != 3 or not all(
        row["state"] == "SIMULATED" and row.get("screening", {}).get("profile") == profile()
        for row in cases
    ):
        raise ValueError("The prepared examples must pass this exact classifier profile first")
    settings.invoice_learned_evaluated = True  # Measured, not a security certification.


def main():
    settings = preparation_settings(get_settings())
    apply_evaluated_invoice_profile(settings)
    sender = Account.from_key(settings.signer_private_key).address
    print(f"Sepolia preparation API on 127.0.0.1:8128. Signer address: {sender}")
    print("Invoice and treasury automation disabled in this process. No settings file changed.")
    print("Use normal backend role credentials, not the simulation fixture credentials.")
    print("Voice/file commands use configured invoice folders and the normal vendor registry.")
    # Normal main startup verifies the live RPC chain; no simulation or signer replacement.
    import uvicorn

    from app.main import app

    uvicorn.run(app, host="127.0.0.1", port=8128, log_level="info")


if __name__ == "__main__":
    main()
