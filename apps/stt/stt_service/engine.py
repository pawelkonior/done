"""Lazy, process-local Whisper model owner."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any, Protocol

from .config import STTSettings


class ModelUnavailableError(RuntimeError):
    pass


class WhisperModel(Protocol):
    def transcribe(self, audio: str, **options: Any) -> dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class EngineTranscript:
    text: str
    language: str
    duration_ms: int
    segments: int


ModelLoader = Callable[[STTSettings], WhisperModel]


def _default_loader(settings: STTSettings) -> WhisperModel:
    if not settings.model_path.is_file() and not settings.allow_model_download:
        raise ModelUnavailableError(
            f"Whisper checkpoint not found at {settings.model_path}; "
            "mount the existing cache or explicitly allow downloads"
        )
    try:
        import whisper
    except ImportError as exc:
        raise ModelUnavailableError("openai-whisper is not installed") from exc
    return whisper.load_model(
        settings.model,
        device=settings.device,
        download_root=str(settings.model_dir),
    )


class WhisperEngine:
    """Loads one model lazily and serializes CPU inference."""

    def __init__(
        self,
        settings: STTSettings,
        *,
        loader: ModelLoader | None = None,
    ) -> None:
        self.settings = settings
        self._loader = loader or _default_loader
        self._model: WhisperModel | None = None
        self._load_lock = asyncio.Lock()
        self._inference_gate = asyncio.Semaphore(settings.max_concurrency)

    @property
    def loaded(self) -> bool:
        return self._model is not None

    @property
    def model_cached(self) -> bool:
        return self.settings.model_path.is_file()

    async def _get_model(self) -> WhisperModel:
        if self._model is not None:
            return self._model
        async with self._load_lock:
            if self._model is None:
                self._model = await asyncio.to_thread(self._loader, self.settings)
            return self._model

    async def transcribe(self, audio_path: Path, *, language: str) -> EngineTranscript:
        async with self._inference_gate:
            model = await self._get_model()
            started = perf_counter()
            result = await asyncio.to_thread(
                model.transcribe,
                str(audio_path),
                language=language,
                task="transcribe",
                fp16=False,
                temperature=0,
                condition_on_previous_text=False,
                word_timestamps=False,
                verbose=False,
            )
            duration_ms = round((perf_counter() - started) * 1_000)

        if not isinstance(result, dict):
            raise RuntimeError("Whisper returned an invalid result")
        text = result.get("text")
        detected_language = result.get("language", language)
        segments = result.get("segments", [])
        if not isinstance(text, str) or not text.strip():
            raise RuntimeError("Whisper returned an empty transcript")
        return EngineTranscript(
            text=text.strip(),
            language=(detected_language if isinstance(detected_language, str) else language),
            duration_ms=duration_ms,
            segments=len(segments) if isinstance(segments, list) else 0,
        )
