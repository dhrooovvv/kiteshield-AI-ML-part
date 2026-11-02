"""Main KiteShield Sepolia service. Starting this process can execute authorized duties.

No fixture credentials, simulator adapters or policy overrides. Startup uses the
normal app's RPC identity verification and existing authorization boundaries.
"""

from pathlib import Path

from app.core.config import get_settings
from scripts.run_invoice_sepolia_preview import apply_evaluated_invoice_profile


def main():
    settings = get_settings()
    if settings.execution_mode != "sepolia" or settings.chain_id != 11155111:
        raise ValueError("The live main service requires Sepolia chain 11155111")
    settings.app_debug = False
    if settings.invoice_intake_enabled:
        Path(settings.invoice_inbox).expanduser().mkdir(parents=True, exist_ok=True)
        if settings.invoice_learned_screening_enabled:
            apply_evaluated_invoice_profile(settings)
    origins = settings.app_cors_origins.split(",")
    for origin in ("http://localhost:3000", "http://127.0.0.1:3000"):
        if origin not in origins:
            origins.append(origin)
    settings.app_cors_origins = ",".join(origins)
    print("Main Sepolia API: 127.0.0.1:8128; use normal role credentials.", flush=True)
    print("Eligible commands and authorized watched-folder duties can send real test ETH.", flush=True)
    print(f"Configured automation limit: {settings.auto_execute_max_eth} ETH; policy and vendor caps also apply.", flush=True)
    import uvicorn

    from app.main import app

    uvicorn.run(app, host="127.0.0.1", port=8128, log_level="info")


if __name__ == "__main__":
    main()
