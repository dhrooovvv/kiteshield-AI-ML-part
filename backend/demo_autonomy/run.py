"""Run only the isolated Gate 1 API: python -m demo_autonomy.run [--enable --gemma]."""

import argparse
import secrets
import tempfile
from pathlib import Path

import uvicorn

from demo_autonomy.engine import Settings
from demo_autonomy.server import create_demo


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--enable", action="store_true")
    parser.add_argument("--gemma", action="store_true")
    parser.add_argument("--model", default="gemma3:4b")
    parser.add_argument("--model-digest", default="")
    parser.add_argument("--ollama-version", default="")
    parser.add_argument("--resume", type=Path, help="Existing Gate 1 temp profile")
    parser.add_argument("--workflows", action="store_true")
    parser.add_argument("--quarantine", action="store_true")
    parser.add_argument("--wallet-services", action="store_true")
    args = parser.parse_args()
    # A new private temp profile each launch; restart via create_demo with the SAME
    # saved directory and credentials, never app/.env or existing wallet databases.
    directory = (
        args.resume.resolve()
        if args.resume
        else Path(tempfile.mkdtemp(prefix="kiteshield-gate1-demo-")).resolve()
    )
    if not directory.is_relative_to(
        Path(tempfile.gettempdir()).resolve()
    ) or not directory.name.startswith("kiteshield-gate1-demo-"):
        parser.error("Only Gate 1 temporary profiles may be resumed")
    admin, agent, approver = (secrets.token_urlsafe(32) for _ in range(3))
    credentials = directory / "demo-credentials.json"
    import json
    import os

    if args.resume:
        saved = json.loads(credentials.read_text())
        admin, agent, approver = saved["admin"], saved["agent"], saved.get("approver", "")
    else:
        fd = os.open(credentials, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as stream:
            json.dump({"admin": admin, "agent": agent, "approver": approver}, stream)
    print(f"SIMULATED ONLY; profile and private demo credentials: {directory}", flush=True)
    if args.wallet_services:
        from demo_autonomy.sandbox import bootstrap

        bootstrap(directory, args.model)
    app = create_demo(
        Settings(
            directory,
            args.enable,
            args.gemma,
            args.model,
            model_digest=args.model_digest,
            ollama_version=args.ollama_version,
            workflows_enabled=args.workflows,
            quarantine_enabled=args.quarantine,
            wallet_services_enabled=args.wallet_services,
        ),
        admin,
        agent,
        approver,
    )
    uvicorn.run(app, host="127.0.0.1", port=8001)


if __name__ == "__main__":
    main()
