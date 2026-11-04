"""Offline transcription only. This service has no wallet or task-execution tools."""

import asyncio
import hashlib
import io
import os
import re
import tempfile
import wave
from array import array
from pathlib import Path

from fastapi import HTTPException


def pinned_files(settings):
    files = [
        (settings.local_voice_binary, settings.local_voice_binary_sha256),
        (settings.local_voice_model, settings.local_voice_model_sha256),
    ]
    for name, expected in files:
        path = Path(name)
        if (
            not path.is_absolute()
            or not path.is_file()
            or path.is_symlink()
            or not re.fullmatch(r"[0-9a-f]{64}", expected)
        ):
            raise ValueError("LOCAL_VOICE_PINS_REQUIRED")
        with path.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != expected:
                raise ValueError("LOCAL_VOICE_DIGEST_MISMATCH")
    if not os.access(settings.local_voice_binary, os.X_OK):
        raise ValueError("LOCAL_VOICE_BINARY_UNAVAILABLE")


def validate_audio(data, max_seconds):
    try:
        with wave.open(io.BytesIO(data), "rb") as audio:
            if (
                audio.getnchannels() != 1
                or audio.getsampwidth() != 2
                or audio.getframerate() != 16000
                or audio.getcomptype() != "NONE"
                or not 1600 <= audio.getnframes() <= 16000 * max_seconds
            ):
                raise ValueError("Invalid WAV")
            samples = array("h", audio.readframes(audio.getnframes()))
            if len(samples) != audio.getnframes() or max(map(abs, samples), default=0) < 128:
                raise ValueError("Silent or truncated WAV")
    except (EOFError, ValueError, wave.Error):
        raise HTTPException(
            422, "Use audible mono 16-bit 16 kHz WAV within the recording limit"
        ) from None


class LocalTranscriber:
    def __init__(self):
        self.lock = asyncio.Lock()

    async def transcribe(self, settings, data):
        if not settings.local_voice_enabled:
            raise HTTPException(503, "LOCAL_VOICE_DISABLED")
        validate_audio(data, settings.local_voice_max_seconds)
        try:
            await asyncio.to_thread(pinned_files, settings)
        except (OSError, ValueError):
            raise HTTPException(503, "LOCAL_VOICE_UNAVAILABLE") from None
        if self.lock.locked():
            raise HTTPException(429, "LOCAL_VOICE_BUSY")
        async with self.lock:
            with tempfile.TemporaryDirectory(prefix="kiteshield-voice-") as directory:
                audio = Path(directory) / "recording.wav"
                audio.write_bytes(data)
                # No inherited API keys, wallet keys, cloud settings or tools.
                process = await asyncio.create_subprocess_exec(
                    settings.local_voice_binary,
                    "-m",
                    settings.local_voice_model,
                    "-f",
                    str(audio),
                    "-l",
                    "en",
                    "-t",
                    "4",
                    "-tp",
                    "0",
                    "-nf",
                    "-ng",
                    "-nt",
                    "-np",
                    env={"PATH": "/usr/bin:/bin", "TMPDIR": directory},
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                try:
                    output, _ = await asyncio.wait_for(
                        process.communicate(), settings.local_voice_timeout_seconds
                    )
                except (TimeoutError, asyncio.CancelledError) as exc:
                    process.kill()
                    await process.wait()
                    if isinstance(exc, asyncio.CancelledError):
                        raise
                    raise HTTPException(503, "LOCAL_VOICE_TIMEOUT") from None
                text = " ".join(output.decode("utf-8", errors="replace").split())
                if process.returncode or not text or len(text) > 2000:
                    raise HTTPException(422, "TRANSCRIPT_REVIEW_REQUIRED")
                return {
                    "transcript": text,
                    "untrusted": True,
                    "authorizes": False,
                    "requires_review": True,
                    "local": True,
                    "engine": "whisper.cpp",
                }
