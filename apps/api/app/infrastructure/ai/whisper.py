"""HTTP client for the isolated local Whisper transcription service."""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
from pydantic import ValidationError

from app.application.ports.ai import (
    AudioPayload,
    STTHealth,
    TranscriptionResult,
)
from app.config import AISettings, get_ai_settings


class WhisperSidecarError(RuntimeError):
    """The sidecar rejected audio or could not produce a valid transcript."""


_ALLOWED_CONTENT_TYPES = {
    "audio/aac",
    "audio/m4a",
    "audio/mp4",
    "audio/mpeg",
    "audio/ogg",
    "audio/wav",
    "audio/wave",
    "audio/webm",
    "audio/x-m4a",
    "audio/x-wav",
    "application/octet-stream",
}
_ALLOWED_SUFFIXES = {".aac", ".caf", ".m4a", ".mp3", ".mp4", ".ogg", ".wav", ".webm"}


class WhisperSidecarAdapter:
    def __init__(
        self,
        settings: AISettings | None = None,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.settings = settings or get_ai_settings()
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=self.settings.whisper_base_url,
            timeout=httpx.Timeout(
                self.settings.whisper_request_timeout_seconds,
                connect=self.settings.whisper_connect_timeout_seconds,
            ),
            limits=httpx.Limits(
                max_connections=max(2, self.settings.whisper_max_concurrency),
                max_keepalive_connections=max(1, self.settings.whisper_max_concurrency),
            ),
            headers={"Accept": "application/json"},
        )
        self._semaphore = asyncio.Semaphore(self.settings.whisper_max_concurrency)

    async def __aenter__(self) -> "WhisperSidecarAdapter":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    @staticmethod
    def _safe_filename(filename: str) -> str:
        safe = Path(filename).name
        if not safe or Path(safe).suffix.casefold() not in _ALLOWED_SUFFIXES:
            raise WhisperSidecarError("unsupported audio filename")
        return safe

    async def transcribe(self, audio: AudioPayload) -> TranscriptionResult:
        if not audio.data:
            raise WhisperSidecarError("audio cannot be empty")
        if len(audio.data) > self.settings.whisper_max_upload_bytes:
            raise WhisperSidecarError("audio exceeds the configured upload limit")
        if audio.content_type.casefold() not in _ALLOWED_CONTENT_TYPES:
            raise WhisperSidecarError("unsupported audio content type")

        filename = self._safe_filename(audio.filename)
        language = audio.language or self.settings.whisper_default_language
        try:
            async with asyncio.timeout(self.settings.whisper_request_timeout_seconds):
                async with self._semaphore:
                    response = await self._client.post(
                        "/v1/audio/transcriptions",
                        files={
                            "file": (filename, audio.data, audio.content_type),
                        },
                        data={"language": language},
                    )
            response.raise_for_status()
            return TranscriptionResult.model_validate(response.json())
        except (httpx.HTTPError, ValidationError, ValueError, TimeoutError) as exc:
            message = " ".join(str(exc).split())[:180]
            raise WhisperSidecarError(
                f"transcription sidecar failed: {type(exc).__name__}: {message}"
            ) from exc

    async def health(self) -> STTHealth:
        try:
            async with asyncio.timeout(self.settings.whisper_request_timeout_seconds):
                async with self._semaphore:
                    response = await self._client.get("/health")
            response.raise_for_status()
            return STTHealth.model_validate(response.json())
        except Exception as exc:
            message = " ".join(str(exc).split())[:180]
            return STTHealth(
                status="unavailable",
                model=self.settings.whisper_model,
                detail=f"{type(exc).__name__}: {message}" if message else type(exc).__name__,
            )
