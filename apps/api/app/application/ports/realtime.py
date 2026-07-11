"""Provider-neutral application port for live voice session provisioning."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol


@dataclass(frozen=True, slots=True)
class RealtimeClientSecret:
    value: str = field(repr=False)
    expires_at: int
    model: str
    voice: str


@dataclass(frozen=True, slots=True)
class RealtimeHealth:
    status: Literal["available", "degraded", "unavailable"]
    provider: Literal["openai"] = "openai"
    model: str = "gpt-realtime-2"
    detail: str | None = None


class RealtimeSessionPort(Protocol):
    async def create_client_secret(
        self,
        *,
        language: str,
        safety_identifier: str,
    ) -> RealtimeClientSecret: ...

    async def health(self) -> RealtimeHealth: ...

    async def aclose(self) -> None: ...
