"""Run the main frontend on 3001 from a disposable copy excluding all env files."""

import argparse
import os
import shutil
import tempfile
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, choices=(3000, 3001), default=3001)
    args = parser.parse_args()
    source = Path(__file__).resolve().parents[2] / "frontend"
    directory = Path(tempfile.mkdtemp(prefix="kiteshield-main-ui-")) / "frontend"
    shutil.copytree(
        source,
        directory,
        ignore=shutil.ignore_patterns("node_modules", "dist", ".env*", "*.tsbuildinfo"),
    )
    # Vite's default cache lives inside the shared node_modules symlink. A private
    # cache prevents parallel verification copies invalidating this running UI.
    config = directory / "vite.config.ts"
    config.write_text(
        config.read_text().replace("return {", "return {\n  cacheDir: '.vite-main-demo',", 1)
    )
    (directory / "node_modules").symlink_to(source / "node_modules", target_is_directory=True)
    env = {k: os.environ[k] for k in ("PATH", "HOME", "TMPDIR") if k in os.environ}
    env["KITESHIELD_API_PROXY_TARGET"] = "http://127.0.0.1:8001"
    executable = str(source / "node_modules/.bin/vite")
    os.chdir(directory)
    print(f"Main frontend disposable demo copy: {directory}", flush=True)
    os.execve(  # noqa: S606 -- fixed local Vite executable and arguments
        executable,
        [executable, "--host", "127.0.0.1", "--port", str(args.port), "--strictPort"],
        env,
    )


if __name__ == "__main__":
    main()
