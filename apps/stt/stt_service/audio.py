"""Validation and ffmpeg normalization for untrusted audio uploads."""

from __future__ import annotations

import asyncio
from pathlib import Path
import shutil
import wave

from .config import STTSettings


ALLOWED_CONTENT_TYPES = {
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
ALLOWED_SUFFIXES = {".aac", ".caf", ".m4a", ".mp3", ".mp4", ".ogg", ".wav", ".webm"}


class AudioRejected(ValueError):
    def __init__(self, message: str, *, status_code: int = 422) -> None:
        super().__init__(message)
        self.status_code = status_code


def validate_upload_metadata(filename: str | None, content_type: str | None) -> str:
    if not filename:
        raise AudioRejected("audio filename is required")
    suffix = Path(filename).suffix.casefold()
    if suffix not in ALLOWED_SUFFIXES:
        raise AudioRejected("unsupported audio file extension", status_code=415)
    normalized_type = (content_type or "application/octet-stream").casefold()
    if normalized_type not in ALLOWED_CONTENT_TYPES:
        raise AudioRejected("unsupported audio content type", status_code=415)
    return suffix


class AudioNormalizer:
    def __init__(self, settings: STTSettings) -> None:
        self.settings = settings

    @property
    def available(self) -> bool:
        return shutil.which(self.settings.ffmpeg_binary) is not None

    async def normalize(self, source: Path, target: Path) -> float:
        if not self.available:
            raise AudioRejected("ffmpeg is not available", status_code=503)
        process = await asyncio.create_subprocess_exec(
            self.settings.ffmpeg_binary,
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(source),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-f",
            "wav",
            str(target),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            _, stderr = await asyncio.wait_for(
                process.communicate(), timeout=self.settings.ffmpeg_timeout_seconds
            )
        except TimeoutError as exc:
            process.kill()
            await process.communicate()
            raise AudioRejected("audio normalization timed out") from exc
        if process.returncode != 0:
            detail = stderr.decode("utf-8", errors="replace").strip()[:240]
            raise AudioRejected(f"invalid or unreadable audio: {detail}")

        try:
            with wave.open(str(target), "rb") as recording:
                frame_rate = recording.getframerate()
                frames = recording.getnframes()
        except (wave.Error, OSError) as exc:
            raise AudioRejected("normalized audio is invalid") from exc
        if frame_rate <= 0 or frames <= 0:
            raise AudioRejected("audio is empty")
        duration = frames / frame_rate
        if duration > self.settings.max_audio_seconds:
            raise AudioRejected(
                f"audio exceeds {self.settings.max_audio_seconds:g} seconds",
                status_code=413,
            )
        return duration
