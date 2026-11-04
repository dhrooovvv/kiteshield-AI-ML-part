"""Download/verify the pinned public GGUF and register a text-only Ollama model.

No KiteShield settings, credentials, wallet services or downloaded code are loaded.
Run from backend: .venv/bin/python -m scripts.setup_gemma26b
"""

import hashlib
import subprocess
import tempfile
from pathlib import Path

from huggingface_hub import hf_hub_download

REPOSITORY = "unsloth/gemma-4-26B-A4B-it-GGUF"
REVISION = "c099eb48e663fd284577b04978a94ffccb261841"
FILENAME = "gemma-4-26B-A4B-it-UD-IQ4_NL.gguf"
SHA256 = "eeb867f279ea5a3d52a0dc15fe8ada677b3328a328530957f3f9a5da93cb10b8"
ALIAS = "kiteshield-gemma4:26b-a4b-iq4nl"


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
