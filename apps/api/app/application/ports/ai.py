"""Provider-neutral port for server-side speech transcription."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field


@dataclass(frozen=True, slots=True)
class AudioPayload:
    data: bytes
    filename: str
    content_type: str
    language: str | None = None


class TranscriptionResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    text: str
    language: str
    duration_ms: int = Field(ge=0)
    model: str


class STTHealth(BaseModel):
    model_config = ConfigDict(extra="ignore")

    status: Literal["available", "degraded", "unavailable"]
    model: str
    detail: str | None = None


class SpeechToTextPort(Protocol):
    async def transcribe(self, audio: AudioPayload) -> TranscriptionResult: ...

    async def health(self) -> STTHealth: ...
