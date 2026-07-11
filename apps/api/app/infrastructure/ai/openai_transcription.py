"""OpenAI Audio API adapter for high-accuracy file transcription."""

from __future__ import annotations

import asyncio
from pathlib import Path
from time import perf_counter
from typing import Any

import httpx

from app.application.ports.ai import AudioPayload, STTHealth, TranscriptionResult
from app.config import TranscriptionSettings, get_transcription_settings


class OpenAITranscriptionError(RuntimeError):
    """OpenAI rejected audio or could not produce a safe transcript."""

    def __init__(self, message: str, *, client_error: bool = False) -> None:
        super().__init__(message)
        self.client_error = client_error


_ALLOWED_CONTENT_TYPES = {
    "audio/m4a",
    "audio/flac",
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
_ALLOWED_SUFFIXES = {
    ".flac",
    ".m4a",
    ".mp3",
    ".mp4",
    ".mpeg",
    ".mpga",
    ".ogg",
    ".wav",
    ".webm",
}
_ENGLISH_DOMAIN_PROMPT = (
    "This is a shopping or errand request for Done. Preserve exact quantities, prices, "
    "currencies, dates, times, names, product names, allergens, constraints, and negations."
)
_POLISH_DOMAIN_PROMPT = (
    "To jest polecenie zakupowe lub zadanie dla Done. Zachowaj dokładnie ilości, ceny, "
    "waluty, daty, godziny, nazwy, produkty, alergeny, ograniczenia i przeczenia."
)


def _provider_error(response: httpx.Response) -> OpenAITranscriptionError:
    request_id = response.headers.get("x-request-id")
    suffix = f" (request {request_id})" if request_id else ""
    if response.status_code in {415, 422}:
        return OpenAITranscriptionError(
            f"OpenAI rejected the audio file or format{suffix}",
            client_error=True,
        )
    if response.status_code == 413:
        return OpenAITranscriptionError(
            f"Audio exceeds the OpenAI upload limit{suffix}",
            client_error=True,
        )
    if response.status_code in {401, 403}:
        return OpenAITranscriptionError(
            f"OpenAI transcription credentials were rejected{suffix}"
        )
    if response.status_code == 429:
        return OpenAITranscriptionError(
            f"OpenAI transcription is rate-limited or has no available quota{suffix}"
        )
    return OpenAITranscriptionError(
        f"OpenAI transcription returned HTTP {response.status_code}{suffix}"
    )


class OpenAITranscriptionAdapter:
    def __init__(
        self,
        settings: TranscriptionSettings | None = None,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.settings = settings or get_transcription_settings()
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=self.settings.base_url,
            timeout=httpx.Timeout(
                self.settings.request_timeout_seconds,
                connect=self.settings.connect_timeout_seconds,
            ),
            limits=httpx.Limits(
                max_connections=max(2, self.settings.max_concurrency),
                max_keepalive_connections=max(1, self.settings.max_concurrency),
            ),
            headers={"Accept": "application/json"},
        )
        self._semaphore = asyncio.Semaphore(self.settings.max_concurrency)

    async def __aenter__(self) -> "OpenAITranscriptionAdapter":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    def _authorization_headers(self) -> dict[str, str]:
        if not self.settings.configured or self.settings.api_key is None:
            raise OpenAITranscriptionError(
                "OpenAI transcription is not configured on this server"
            )
        return {"Authorization": f"Bearer {self.settings.api_key}"}

    @staticmethod
    def _safe_filename(filename: str) -> str:
        safe = Path(filename).name
        if not safe or Path(safe).suffix.casefold() not in _ALLOWED_SUFFIXES:
            raise OpenAITranscriptionError(
                "unsupported audio filename",
                client_error=True,
            )
        return safe

    def _language(self, language: str | None) -> str:
        normalized = (language or self.settings.default_language).split("-", 1)[0]
        normalized = normalized.strip().casefold()
        return normalized or self.settings.default_language

    @staticmethod
    def _prompt(language: str) -> str | None:
        if language == "pl":
            return _POLISH_DOMAIN_PROMPT
        if language == "en":
            return _ENGLISH_DOMAIN_PROMPT
        return None

    async def transcribe(self, audio: AudioPayload) -> TranscriptionResult:
        if not audio.data:
            raise OpenAITranscriptionError("audio cannot be empty", client_error=True)
        if len(audio.data) > self.settings.max_upload_bytes:
            raise OpenAITranscriptionError(
                "audio exceeds the configured upload limit",
                client_error=True,
            )
        content_type = audio.content_type.split(";", 1)[0].strip().casefold()
        if content_type not in _ALLOWED_CONTENT_TYPES:
            raise OpenAITranscriptionError(
                "unsupported audio content type",
                client_error=True,
            )

        filename = self._safe_filename(audio.filename)
        language = self._language(audio.language)
        started = perf_counter()
        try:
            async with asyncio.timeout(self.settings.request_timeout_seconds):
                async with self._semaphore:
                    form_data = {
                        "model": self.settings.model,
                        "language": language,
                        "response_format": "json",
                    }
                    prompt = self._prompt(language)
                    if prompt:
                        form_data["prompt"] = prompt
                    response = await self._client.post(
                        "/v1/audio/transcriptions",
                        headers=self._authorization_headers(),
                        files={"file": (filename, audio.data, content_type)},
                        data=form_data,
                    )
        except OpenAITranscriptionError:
            raise
        except (httpx.HTTPError, TimeoutError) as exc:
            raise OpenAITranscriptionError(
                "OpenAI transcription could not be reached"
            ) from exc

        if not response.is_success:
            raise _provider_error(response)
        try:
            payload: Any = response.json()
            raw_text = payload["text"]
            if not isinstance(raw_text, str):
                raise TypeError("text must be a string")
            text = raw_text.strip()
        except (KeyError, TypeError, ValueError) as exc:
            raise OpenAITranscriptionError(
                "OpenAI transcription returned an invalid response"
            ) from exc
        return TranscriptionResult(
            text=text,
            language=language,
            duration_ms=max(0, round((perf_counter() - started) * 1_000)),
            model=self.settings.model,
        )

    async def health(self) -> STTHealth:
        if not self.settings.configured:
            return STTHealth(
                status="unavailable",
                model=self.settings.model,
                detail="OPENAI_API_KEY is not configured.",
            )
        try:
            response = await self._client.get(
                f"/v1/models/{self.settings.model}",
                headers=self._authorization_headers(),
            )
        except (httpx.HTTPError, OpenAITranscriptionError):
            return STTHealth(
                status="unavailable",
                model=self.settings.model,
                detail="OpenAI transcription could not be reached.",
            )
        if response.is_success:
            return STTHealth(
                status="available",
                model=self.settings.model,
                detail="OpenAI cloud transcription is available.",
            )
        return STTHealth(
            status="unavailable",
            model=self.settings.model,
            detail=str(_provider_error(response)),
        )
