"""Provider-neutral ports for language and speech inference."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Generic, Literal, Protocol, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AIMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["system", "user", "assistant", "tool"]
    content: str
    tool_name: str | None = Field(default=None, min_length=1, max_length=128)

    @model_validator(mode="after")
    def validate_tool_name(self) -> "AIMessage":
        if self.role == "tool" and self.tool_name is None:
            raise ValueError("tool messages require tool_name")
        if self.role != "tool" and self.tool_name is not None:
            raise ValueError("tool_name is only valid for tool messages")
        return self


class AITool(BaseModel):
    """JSON-Schema function exposed to a language model."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=128)
    description: str = Field(min_length=1, max_length=1_000)
    parameters: dict[str, Any]

    def as_ollama(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class AIToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str | None = None
    name: str = Field(min_length=1, max_length=128)
    arguments: dict[str, Any]


class AIChatResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = ""
    tool_calls: list[AIToolCall] = Field(default_factory=list)


class MissionIntentDraft(BaseModel):
    """Safe, deliberately incomplete result of transcript interpretation.

    Relative time remains text.  The deterministic application layer must
    resolve it using the user's timezone and current clock.
    """

    model_config = ConfigDict(extra="forbid")

    goal: str = Field(min_length=1, max_length=160)
    title: str = Field(min_length=1, max_length=160)
    participants: int | None = Field(default=None, ge=1, le=10_000)
    budget: float | None = Field(default=None, ge=0, le=10_000_000)
    currency: Literal["PLN", "EUR", "USD"] = "PLN"
    categories: list[str] = Field(default_factory=list, max_length=32)
    hard_constraints: list[str] = Field(default_factory=list, max_length=64)
    soft_preferences: list[str] = Field(default_factory=list, max_length=64)
    deadline_text: str | None = Field(default=None, max_length=160)
    confidence: float = Field(ge=0, le=1)


class AIHealth(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["available", "degraded", "unavailable"]
    provider: Literal["ollama"] = "ollama"
    version: str | None = None
    model: str
    model_available: bool = False
    model_loaded: bool = False
    detail: str | None = None


ResultT = TypeVar("ResultT", bound=BaseModel)


@dataclass(frozen=True, slots=True)
class AIResult(Generic[ResultT]):
    value: ResultT
    provider: Literal["ollama", "fallback"]
    model: str | None
    fallback_reason: str | None = None

    @property
    def used_fallback(self) -> bool:
        return self.provider == "fallback"


class StructuredAIPort(Protocol):
    async def generate_structured(
        self,
        *,
        messages: Sequence[AIMessage],
        response_model: type[ResultT],
        fallback: Callable[[], ResultT],
    ) -> AIResult[ResultT]: ...

    async def extract_mission(
        self,
        transcript: str,
        *,
        locale: str,
        timezone: str,
        now: datetime,
    ) -> AIResult[MissionIntentDraft]: ...

    async def chat_with_tools(
        self,
        *,
        messages: Sequence[AIMessage],
        tools: Sequence[AITool],
        fallback: Callable[[], AIChatResponse],
    ) -> AIResult[AIChatResponse]: ...

    async def health(self) -> AIHealth: ...


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
    audio_duration_seconds: float | None = Field(default=None, ge=0)
    model: str
    segments: int = Field(default=0, ge=0)


class STTHealth(BaseModel):
    model_config = ConfigDict(extra="ignore")

    status: Literal["available", "degraded", "unavailable"]
    model: str
    model_cached: bool = False
    model_loaded: bool = False
    ffmpeg: bool = False
    detail: str | None = None


class SpeechToTextPort(Protocol):
    async def transcribe(self, audio: AudioPayload) -> TranscriptionResult: ...

    async def health(self) -> STTHealth: ...
