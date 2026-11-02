"""Opt-in real Sepolia main app on 8001, using a separate durable wallet/profile."""

import argparse
import json
import os
import shutil
import sys
import time
import urllib.request
from pathlib import Path

from demo_autonomy.sepolia_profile import DIGEST, MODEL, bootstrap, prepare


def build_app(directory, *, enabled=False, quarantine=False):
    settings, authority, address, credentials = bootstrap(directory)
    from app.main import app
    from demo_autonomy.engine import Settings
    from demo_autonomy.sepolia import SepoliaAdapter, SepoliaWorkflowEngine
    from demo_autonomy.server import create_demo

    child = create_demo(
        Settings(
            directory,
            enabled=enabled,
            planner_enabled=enabled,
            model=MODEL,
            model_digest=DIGEST,
            ollama_version="0.40.8",
            workflows_enabled=True,
            quarantine_enabled=quarantine,
            wallet_services_enabled=True,
            mode="SEPOLIA",
            wallet_source="separate-sepolia",
        ),
        credentials["policyAdmin"],
        credentials["proposer"],
        credentials["approver"],
        core_app=app,
        engine_factory=lambda config: SepoliaWorkflowEngine(config, authority),
        adapter_factory=lambda engine, core: SepoliaAdapter(engine, core, authority, address),
    )
    app.state.autonomy_app = child
    app.mount("/api/v1/autonomy", child)
    # Import happened with main's simulation-only integration disabled. Enable
    # assistant delegation only after attaching this separately guarded adapter.
    settings.autonomy_enabled = enabled
    app.state.sepolia_profile = str(directory)
    return app


def start_local(args):
    from demo_autonomy.start_local import free, launch

    if not free(8001) or not free(3000):
        raise RuntimeError("3000 or 8001 is occupied; no existing service was stopped")
    root = Path(__file__).resolve().parents[1]
    logs = args.profile / "logs"
    logs.mkdir(mode=0o700, exist_ok=True)
    env = {k: os.environ[k] for k in ("PATH", "HOME", "TMPDIR") if k in os.environ}
    env["PYTHONPATH"] = str(root)
    if args.enable_autonomy and free(11434):
        executable = shutil.which("ollama")
        if executable:
            launch(
                [executable, "serve"],
                logs,
                {**env, "OLLAMA_NO_CLOUD": "true", "OLLAMA_NOPRUNE": "true"},
                "ollama",
            )
    command = [
        sys.executable,
        "-u",
        "-m",
        "demo_autonomy.sepolia_run",
        "--profile",
        str(args.profile),
    ]
    if args.enable_autonomy:
        command.append("--enable-autonomy")
    if args.enable_quarantine:
        command.append("--enable-quarantine")
    api = launch(command, logs, env, "backend")
    ui = None
    try:
        for _ in range(50):
            if api.poll() is not None:
                raise RuntimeError("Sepolia startup refused; inspect the private backend log")
            try:
                with urllib.request.urlopen(
                    "http://127.0.0.1:8001/api/v1/health", timeout=1
                ) as response:
                    health = json.load(response)
                if health.get("verified_chain_id") == 11155111:
                    break
            except (OSError, ValueError):
                pass
            time.sleep(0.5)
        else:
            raise RuntimeError("Sepolia startup timed out; no simulation fallback")
        ui = launch(
            [sys.executable, "-u", "-m", "demo_autonomy.main_ui", "--port", "3000"],
            logs,
            env,
            "frontend",
        )
        for _ in range(40):
            if ui.poll() is not None:
                raise RuntimeError("Frontend startup failed")
            try:
                with urllib.request.urlopen("http://127.0.0.1:3000", timeout=1) as response:
                    if response.status == 200:
                        break
            except OSError:
                pass
            time.sleep(0.25)
        else:
            raise RuntimeError("Frontend startup timed out")
    except Exception:
        api.terminate()
        if ui is not None:
            ui.terminate()
        raise
    state = {
        "backend_pid": api.pid,
        "frontend_pid": ui.pid,
        "profile": str(args.profile),
        "url": "http://localhost:3000",
        "mode": "SEPOLIA",
    }
    from demo_autonomy.sepolia_profile import private_json

    state_path = logs / "state.json"
    if state_path.exists():
        state_path.unlink()
    private_json(state_path, state)
    print(json.dumps(state))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--rpc-url")
    parser.add_argument("--enable-autonomy", action="store_true")
    parser.add_argument("--enable-quarantine", action="store_true")
    parser.add_argument("--start-local", action="store_true")
    args = parser.parse_args()
    args.profile = args.profile.expanduser().resolve()
    if args.prepare:
        if not args.rpc_url:
            parser.error("--rpc-url is required to prepare the fixed Sepolia connection")
        print(json.dumps(prepare(args.profile, args.rpc_url)))
        return
    if args.start_local:
        start_local(args)
        return
    import uvicorn

    uvicorn.run(
        build_app(args.profile, enabled=args.enable_autonomy, quarantine=args.enable_quarantine),
        host="127.0.0.1",
        port=8001,
    )


if __name__ == "__main__":
    main()
