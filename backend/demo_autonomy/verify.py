"""Run regression checks in disposable profiles without wallet configuration."""

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[2]
    backend = root / "backend"
    directory = Path(tempfile.mkdtemp(prefix="kiteshield-gate1-verification-"))
    guard = directory / "guard"
    guard.mkdir()
    (guard / "sitecustomize.py").write_text(
        "import socket\n"
        "ports = set()\n"
        "original_bind = socket.socket.bind\n"
        "original_connect = socket.socket.connect\n"
        "def bound(self, address):\n"
        "    result = original_bind(self, address)\n"
        "    if isinstance(address, tuple) and address[0] == '127.0.0.1' and address[1] == 0:\n"
        "        ports.add(self.getsockname()[1])\n"
        "    return result\n"
        "def guarded(self, address):\n"
        "    if isinstance(address, tuple) and address[0] == '127.0.0.1' and address[1] in ports:\n"
        "        return original_connect(self, address)\n"
        "    raise RuntimeError('Only test-owned ephemeral loopback servers permitted')\n"
        "socket.socket.bind = bound\n"
        "socket.socket.connect = guarded\n"
        "socket.socket.connect_ex = lambda *args: 111\n"
    )
    env = {key: os.environ[key] for key in ("PATH", "HOME", "TMPDIR") if key in os.environ}
    env.update(
        {
            "PYTHONPATH": str(guard) + os.pathsep + str(backend),
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "KITESHIELD_DEMO_BACKEND_PORT": "8001",
            "KITESHIELD_DEMO_FRONTEND_PORT": "3001",
        }
    )
    python = str(backend / ".venv/bin/python")
    frontend = directory / "frontend"
    shutil.copytree(
        root / "frontend",
        frontend,
        ignore=shutil.ignore_patterns("node_modules", "dist", ".env*", "*.tsbuildinfo"),
    )
    (frontend / "node_modules").symlink_to(root / "frontend/node_modules", target_is_directory=True)
    checks = [
        (
            "gate1",
            [
                python,
                "-m",
                "pytest",
                "--confcutdir=" + str(backend / "demo_autonomy/tests"),
                str(backend / "demo_autonomy/tests"),
                "-q",
            ],
            directory,
        ),
        ("backend", [python, "-m", "pytest", str(backend / "tests"), "-q"], directory),
        ("frontend-test", ["npm", "test"], frontend),
        ("frontend-lint", ["npm", "run", "lint"], frontend),
        ("frontend-build", ["npm", "run", "build"], frontend),
        (
            "gate1-lint",
            [str(backend / ".venv/bin/ruff"), "check", str(backend / "demo_autonomy")],
            directory,
        ),
    ]
    results = []
    for name, command, cwd in checks:
        log = directory / (name + ".log")
        with log.open("w") as stream:
            try:
                completed = subprocess.run(  # noqa: S603 -- fixed local command list, no shell
                    command,
                    cwd=cwd,
                    env=env,
                    stdout=stream,
                    stderr=subprocess.STDOUT,
                    timeout=240,
                    check=False,
                )
                code = completed.returncode
            except subprocess.TimeoutExpired:
                code = 124
        results.append({"check": name, "exit_code": code, "log": str(log)})
        print(json.dumps(results[-1]), flush=True)
    (directory / "results.json").write_text(json.dumps(results, indent=2))
    print("Disposable verification profile: " + str(directory), flush=True)


if __name__ == "__main__":
    main()
