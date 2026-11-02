"""Download/verify the pinned public GGUF and register a text-only Ollama model.

No KiteShield settings, credentials, wallet services or downloaded code are loaded.
Run from backend: .venv/bin/python -m scripts.setup_gemma12b_q4km
"""

import hashlib
import subprocess
import tempfile
from pathlib import Path

from huggingface_hub import hf_hub_download

REPOSITORY = "unsloth/gemma-4-12b-it-GGUF"
REVISION = "fc034cfff751157913579611efad8462ac1be606"
FILENAME = "gemma-4-12b-it-Q4_K_M.gguf"
SHA256 = "0a270ec9fe6b34f4a0d33992b6135117b484ebc4766ab76b51d4ae8c457e4c42"
ALIAS = "kiteshield-gemma4:12b-q4km"


def main():
    source = Path(hf_hub_download(REPOSITORY, FILENAME, revision=REVISION))
    digest = hashlib.sha256()
    with source.open("rb") as handle:
        if handle.read(4) != b"GGUF":
            raise ValueError("Model is not a GGUF file")
        handle.seek(0)
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != SHA256:
        raise ValueError("Model checksum mismatch; refusing import")
    with tempfile.TemporaryDirectory(prefix="kite-model-import-") as directory:
        model = Path(directory) / "Modelfile"
        model.write_text(
            f"FROM {source}\nPARAMETER temperature 0\n"
            "PARAMETER num_ctx 8192\nPARAMETER num_predict 384\n"
        )
        subprocess.run(["ollama", "create", ALIAS, "-f", str(model)], check=True)  # noqa: S603,S607
    print(f"Verified and registered {ALIAS}. No app settings were changed.")


if __name__ == "__main__":
    main()
