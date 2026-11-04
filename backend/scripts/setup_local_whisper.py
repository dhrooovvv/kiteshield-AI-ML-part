"""Build pinned official whisper.cpp locally; no installer/model-download scripts.

License evaluation: whisper.cpp MIT, Whisper weights MIT, CMake BSD-3-Clause.
Only public source/binary/model downloads occur. No wallet settings are imported.
"""

import hashlib
import json
import os
import subprocess
import tarfile
import urllib.request
from pathlib import Path

VERSION = "1.9.5"
COMMIT = "d1be6fde11ac6e0407606b4e42fe72d34add8037"
CMAKE_VERSION = "4.1.2"
CMAKE_SHA = "3be85f5b999e327b1ac7d804cbc9acd767059e9f603c42ec2765f6ab68fbd367"
MODEL_REV = "5359861c739e955e79d9a303bcbc70fb988958b1"
MODEL_SHA = "a03779c86df3323075f5e796cb2ce5029f00ec8869eee3fdfb897afe36c6d002"


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def download(url, target, expected=None):
    if not url.startswith(
        (
            "https://github.com/Kitware/CMake/releases/download/",
            "https://codeload.github.com/ggml-org/whisper.cpp/",
            "https://huggingface.co/ggerganov/whisper.cpp/resolve/",
        )
    ):
        raise ValueError("Pinned public artifact URL required")
    if not target.exists():
        temporary = target.with_suffix(target.suffix + ".partial")
        with urllib.request.urlopen(url, timeout=60) as source, temporary.open("wb") as out:  # noqa: S310 -- allowlisted HTTPS artifact origins above
            while chunk := source.read(1024 * 1024):
                out.write(chunk)
        temporary.replace(target)
    if expected and sha(target) != expected:
        raise RuntimeError("Downloaded artifact digest mismatch")


def main():
    root = Path.home() / ".local/share/kiteshield/local-voice" / ("whisper-v" + VERSION)
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    cmake_archive = root / "cmake.tar.gz"
    download(
        f"https://github.com/Kitware/CMake/releases/download/v{CMAKE_VERSION}/"
        f"cmake-{CMAKE_VERSION}-macos-universal.tar.gz",
        cmake_archive,
        CMAKE_SHA,
    )
    cmake_root = root / f"cmake-{CMAKE_VERSION}-macos-universal"
    if not cmake_root.exists():
        with tarfile.open(cmake_archive) as archive:
            archive.extractall(root, filter="data")
    source_archive = root / "whisper-source.tar.gz"
    download(f"https://codeload.github.com/ggml-org/whisper.cpp/tar.gz/{COMMIT}", source_archive)
    source = root / ("whisper.cpp-" + COMMIT)
    if not source.exists():
        with tarfile.open(source_archive) as archive:
            archive.extractall(root, filter="data")
    if "MIT License" not in (source / "LICENSE").read_text():
        raise RuntimeError("Pinned source license mismatch")
    model = root / "ggml-base.en.bin"
    download(
        f"https://huggingface.co/ggerganov/whisper.cpp/resolve/{MODEL_REV}/ggml-base.en.bin",
        model,
        MODEL_SHA,
    )
    cmake = cmake_root / "CMake.app/Contents/bin/cmake"
    build = root / "build"
    env = {key: os.environ[key] for key in ("PATH", "TMPDIR") if key in os.environ}
    commands = [
        [
            str(cmake),
            "-S",
            str(source),
            "-B",
            str(build),
            "-DCMAKE_BUILD_TYPE=Release",
            "-DBUILD_SHARED_LIBS=OFF",
            "-DGGML_METAL=OFF",
            "-DWHISPER_BUILD_TESTS=OFF",
        ],
        [str(cmake), "--build", str(build), "--target", "whisper-cli", "-j", "4"],
    ]
    with (root / "build.log").open("w") as log:
        for command in commands:
            subprocess.run(command, env=env, stdout=log, stderr=subprocess.STDOUT, check=True)  # noqa: S603 -- pinned build tools, no shell
    binary = build / "bin/whisper-cli"
    manifest = {
        "version": VERSION,
        "commit": COMMIT,
        "license": "MIT",
        "binary": str(binary),
        "binary_sha256": sha(binary),
        "source_sha256": sha(source_archive),
        "model": str(model),
        "model_name": "base.en",
        "model_revision": MODEL_REV,
        "model_sha256": MODEL_SHA,
        "model_license": "MIT",
        "cmake_version": CMAKE_VERSION,
        "cmake_sha256": CMAKE_SHA,
        "cmake_license": "BSD-3-Clause",
        "sample": str(source / "samples/jfk.wav"),
    }
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(json.dumps(manifest), flush=True)


if __name__ == "__main__":
    main()
