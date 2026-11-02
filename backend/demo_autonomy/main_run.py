"""Main application, strictly isolated to port 8001 and fresh test-only configuration."""

import argparse
import json
import os
import tempfile
from pathlib import Path

import uvicorn

from demo_autonomy.sandbox import bootstrap


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--enable-autonomy", action="store_true")
    parser.add_argument("--enable-quarantine", action="store_true")
    parser.add_argument("--resume", type=Path)
    args = parser.parse_args()
    directory = (
        args.resume.resolve()
        if args.resume
        else Path(tempfile.mkdtemp(prefix="kiteshield-gate-main-")).resolve()
    )
    if not directory.is_relative_to(
        Path(tempfile.gettempdir()).resolve()
    ) or not directory.name.startswith("kiteshield-gate-main-"):
        parser.error("Only an isolated main demo profile may be resumed")
    model = "kiteshield-gemma4:12b-q4km"
    bootstrap(directory, model)
    # The bootstrap disabled env-file loading before any main app import.
    from app.core.config import get_settings

    settings = get_settings()
    settings.app_port = 8001
    settings.app_cors_origins = (
        "http://127.0.0.1:3000,http://localhost:3000,http://127.0.0.1:3001,http://localhost:3001"
    )
    settings.autonomy_enabled = args.enable_autonomy
    settings.autonomy_quarantine_enabled = args.enable_quarantine
    settings.autonomy_profile_dir = str(directory)
    settings.autonomy_model = model
    settings.autonomy_model_digest = (
        "13478e018db994bfea035644c1774abc573381ee0ff7e11ad59f3fbc89fd1519"
    )
    settings.autonomy_ollama_version = "0.40.8"
    credentials = directory / "main-demo-credentials.json"
    if args.resume:
        saved = json.loads(credentials.read_text())
        settings.api_key = saved["proposer"]
        settings.policy_admin_api_key = saved["policyAdmin"]
        settings.approver_api_key = saved["approver"]
    else:
        fd = os.open(credentials, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as stream:
            json.dump(
                {
                    "proposer": settings.api_key,
                    "policyAdmin": settings.policy_admin_api_key,
                    "approver": settings.approver_api_key,
                },
                stream,
            )
    from app.main import app

    print(f"Main app isolated demo profile: {directory}", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=8001)


if __name__ == "__main__":
    main()
