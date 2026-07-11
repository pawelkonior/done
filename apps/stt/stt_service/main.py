"""FastAPI entrypoint for local, private Whisper transcription."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import re
from tempfile import TemporaryDirectory

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, ConfigDict, Field

from .audio import AudioNormalizer, AudioRejected, validate_upload_metadata
from .config import STTSettings, get_settings
from .engine import ModelUnavailableError, WhisperEngine


_LANGUAGE_PATTERN = re.compile(r"^[a-z]{2,3}(?:-[A-Z]{2})?$")


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    model: str
    model_cached: bool
    model_loaded: bool
    ffmpeg: bool
    detail: str | None = None


class TranscriptionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    language: str
    duration_ms: int = Field(ge=0)
    audio_duration_seconds: float = Field(ge=0)
    model: str
    segments: int = Field(ge=0)


async def _save_upload(
    upload: UploadFile,
    destination: Path,
    *,
    max_bytes: int,
    chunk_bytes: int,
) -> int:
    total = 0
    with destination.open("wb") as output:
        while chunk := await upload.read(chunk_bytes):
            total += len(chunk)
            if total > max_bytes:
                raise AudioRejected("audio exceeds the upload limit", status_code=413)
            output.write(chunk)
    if total == 0:
        raise AudioRejected("audio is empty")
    return total


def create_app(
    settings: STTSettings | None = None,
    *,
    engine: WhisperEngine | None = None,
    normalizer: AudioNormalizer | None = None,
) -> FastAPI:
    resolved_settings = settings or get_settings()
    resolved_engine = engine or WhisperEngine(resolved_settings)
    resolved_normalizer = normalizer or AudioNormalizer(resolved_settings)

    application = FastAPI(
        title="Done Local STT",
        version="0.1.0",
        docs_url="/docs",
        redoc_url=None,
    )

    @application.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        whisper_installed = importlib.util.find_spec("whisper") is not None
        model_ready = resolved_engine.model_cached or resolved_settings.allow_model_download
        available = whisper_installed and resolved_normalizer.available and model_ready
        details: list[str] = []
        if not whisper_installed:
            details.append("openai-whisper is not installed")
        if not resolved_normalizer.available:
            details.append("ffmpeg is not available")
        if not model_ready:
            details.append(f"checkpoint is missing: {resolved_settings.model_path}")
        return HealthResponse(
            status="available" if available else "degraded",
            model=resolved_settings.model,
            model_cached=resolved_engine.model_cached,
            model_loaded=resolved_engine.loaded,
            ffmpeg=resolved_normalizer.available,
            detail="; ".join(details) or None,
        )

    @application.post(
        "/v1/audio/transcriptions",
        response_model=TranscriptionResponse,
    )
    async def transcribe(
        file: UploadFile = File(...),
        language: str | None = Form(default=None),
    ) -> TranscriptionResponse:
        selected_language = language or resolved_settings.default_language
        if not _LANGUAGE_PATTERN.fullmatch(selected_language):
            raise HTTPException(status_code=422, detail="invalid language code")
        try:
            suffix = validate_upload_metadata(file.filename, file.content_type)
            with TemporaryDirectory(prefix="done-stt-") as temporary_directory:
                directory = Path(temporary_directory)
                source = directory / f"input{suffix}"
                normalized = directory / "normalized.wav"
                await _save_upload(
                    file,
                    source,
                    max_bytes=resolved_settings.max_upload_bytes,
                    chunk_bytes=resolved_settings.upload_chunk_bytes,
                )
                audio_duration = await resolved_normalizer.normalize(source, normalized)
                transcript = await resolved_engine.transcribe(
                    normalized,
                    language=selected_language,
                )
            return TranscriptionResponse(
                text=transcript.text,
                language=transcript.language,
                duration_ms=transcript.duration_ms,
                audio_duration_seconds=round(audio_duration, 3),
                model=resolved_settings.model,
                segments=transcript.segments,
            )
        except AudioRejected as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
        except ModelUnavailableError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail="transcription failed") from exc
        finally:
            await file.close()

    return application


app = create_app()
