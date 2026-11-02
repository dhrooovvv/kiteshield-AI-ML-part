"""Keep the isolated main app available on localhost:3000 after the chat turn ends."""

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path


def free(port):
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def launch(command, directory, env, name):
    with (directory / (name + ".log")).open("ab") as log:
        return subprocess.Popen(  # noqa: S603 -- fixed local executables, no shell
            command,
            cwd=directory,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            start_new_session=True,
        )


def main():
    if not free(3000) or not free(8001):
        raise RuntimeError("3000 or 8001 is occupied; refusing to replace an unrelated listener")
    backend = Path(__file__).resolve().parents[1]
    directory = Path(tempfile.mkdtemp(prefix="kiteshield-local-3000-"))
    env = {k: os.environ[k] for k in ("PATH", "HOME", "TMPDIR") if k in os.environ}
    env["PYTHONPATH"] = str(backend)
    if free(11434):
        executable = shutil.which("ollama")
        if not executable:
            raise RuntimeError("Existing Ollama installation required")
        launch(
            [executable, "serve"],
            directory,
            {**env, "OLLAMA_NO_CLOUD": "true", "OLLAMA_NOPRUNE": "true"},
            "ollama",
        )
    api = launch(
        [
            sys.executable,
            "-u",
            "-m",
            "demo_autonomy.main_run",
            "--enable-autonomy",
            "--enable-quarantine",
        ],
        directory,
        env,
        "backend",
    )
    ui = launch(
        [sys.executable, "-u", "-m", "demo_autonomy.main_ui", "--port", "3000"],
        directory,
        env,
        "frontend",
    )
    for _ in range(40):
        if api.poll() is not None or ui.poll() is not None:
            raise RuntimeError(f"Startup failed; inspect logs in {directory}")
        try:
            with urllib.request.urlopen(
                "http://127.0.0.1:8001/api/v1/autonomy/health", timeout=1
            ) as r:
                ready = json.load(r).get("enabled")
            with urllib.request.urlopen("http://127.0.0.1:3000", timeout=1) as r:
                ready = ready and r.status == 200
            if ready:
                break
        except (OSError, ValueError):
            pass
        time.sleep(0.5)
    else:
        raise RuntimeError(f"Startup timed out; inspect logs in {directory}")
    lines = (directory / "backend.log").read_text().splitlines()
    profile = next(
        line.split(": ", 1)[1]
        for line in lines
        if line.startswith("Main app isolated demo profile:")
    )
    state = {
        "backend_pid": api.pid,
        "frontend_pid": ui.pid,
        "profile": profile,
        "url": "http://localhost:3000",
        "logs": str(directory),
    }
    (directory / "state.json").write_text(json.dumps(state, indent=2))
    print(json.dumps(state))


if __name__ == "__main__":
    main()
