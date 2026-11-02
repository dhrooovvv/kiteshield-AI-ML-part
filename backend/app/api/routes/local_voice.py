"""Bounded local audio intake. Transcription never submits or approves a payment."""

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request

from app.core.config import get_settings
from app.core.security import require_proposer
from app.services.local_voice import LocalTranscriber, pinned_files

router = APIRouter(prefix="/voice", tags=["Local voice"])
transcriber = LocalTranscriber()


@router.get("/health")
async def health():
    settings = get_settings()
    available = False
    if settings.local_voice_enabled:
        try:
            await asyncio.to_thread(pinned_files, settings)
            available = True
        except (OSError, ValueError):
            pass
    return {
        "enabled": settings.local_voice_enabled,
        "available": available,
        "local": True,
        "engine": "whisper.cpp",
        "max_seconds": settings.local_voice_max_seconds,
    }


@router.post("/transcribe", dependencies=[Depends(require_proposer)])
async def transcribe(request: Request):
    settings = get_settings()
    if not settings.local_voice_enabled:
        raise HTTPException(503, "LOCAL_VOICE_DISABLED")
    if request.headers.get("content-type", "").split(";", 1)[0] != "audio/wav":
        raise HTTPException(415, "PCM_WAV_REQUIRED")
    maximum = settings.local_voice_max_seconds * 16000 * 2 + 4096
    data = bytearray()
    async for chunk in request.stream():
        if len(data) + len(chunk) > maximum:
            raise HTTPException(413, "AUDIO_TOO_LARGE")
        data.extend(chunk)
    return await transcriber.transcribe(settings, bytes(data))
