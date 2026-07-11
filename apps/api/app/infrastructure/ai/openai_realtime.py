"""OpenAI Realtime adapter.

Only this server-side adapter can access the standard OpenAI API key. Mobile
and web clients receive a short-lived client secret bound to a hashed user ID.
"""

from __future__ import annotations

from typing import Any

import httpx

from ...application.ports.realtime import RealtimeClientSecret, RealtimeHealth
from ...config import RealtimeSettings


class RealtimeUnavailableError(RuntimeError):
    """A live voice session could not be provisioned safely."""


def _safe_provider_message(response: httpx.Response) -> str:
    request_id = response.headers.get("x-request-id")
    suffix = f" (request {request_id})" if request_id else ""
    if response.status_code in {401, 403}:
        return f"OpenAI Realtime credentials were rejected{suffix}"
    if response.status_code == 429:
        return f"OpenAI Realtime is rate-limited or has no available quota{suffix}"
    return f"OpenAI Realtime returned HTTP {response.status_code}{suffix}"


class OpenAIRealtimeAdapter:
    def __init__(
        self,
        settings: RealtimeSettings,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.settings = settings
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=settings.base_url,
            timeout=httpx.Timeout(
                settings.request_timeout_seconds,
                connect=settings.connect_timeout_seconds,
            ),
            headers={"Content-Type": "application/json"},
        )

    def _authorization_headers(self, safety_identifier: str | None = None) -> dict[str, str]:
        if not self.settings.configured or self.settings.api_key is None:
            raise RealtimeUnavailableError(
                "Live voice is not configured on this server"
            )
        headers = {"Authorization": f"Bearer {self.settings.api_key}"}
        if safety_identifier:
            headers["OpenAI-Safety-Identifier"] = safety_identifier
        return headers

    def _session_payload(self, language: str) -> dict[str, Any]:
        language_name = "Polish" if language.casefold().startswith("pl") else "English"
        return {
            "session": {
                "type": "realtime",
                "model": self.settings.model,
                "output_modalities": ["audio"],
                "instructions": (
                    "You are Done's live voice intake assistant. "
                    f"Speak {language_name}, clearly and briefly. Gather one complete "
                    "shopping or errand mission, including quantities, budget, deadline, "
                    "participants, allergens and other hard constraints when relevant. "
                    "Ask concise follow-up questions for missing critical facts. When the "
                    "mission is complete, call submit_mission exactly once with a faithful "
                    "standalone transcript containing every confirmed fact. Never claim that "
                    "a purchase or external action was executed. The deterministic Done backend "
                    "validates money, deadlines, allergens, approvals and execution policy."
                ),
                "audio": {
                    "input": {
                        "transcription": {
                            "model": self.settings.transcription_model,
                            "language": language.split("-", 1)[0].casefold(),
                        },
                        "turn_detection": {"type": "semantic_vad"},
                    },
                    "output": {"voice": self.settings.voice},
                },
                "tools": [
                    {
                        "type": "function",
                        "name": "submit_mission",
                        "description": (
                            "Submit the complete, confirmed mission to Done for deterministic "
                            "validation and execution planning."
                        ),
                        "parameters": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "transcript": {
                                    "type": "string",
                                    "description": (
                                        "A faithful standalone mission statement containing all "
                                        "confirmed requirements and constraints."
                                    ),
                                }
                            },
                            "required": ["transcript"],
                        },
                    }
                ],
                "tool_choice": "auto",
            }
        }

    async def create_client_secret(
        self,
        *,
        language: str,
        safety_identifier: str,
    ) -> RealtimeClientSecret:
        try:
            response = await self._client.post(
                "/v1/realtime/client_secrets",
                headers=self._authorization_headers(safety_identifier),
                json=self._session_payload(language),
            )
        except httpx.HTTPError as exc:
            raise RealtimeUnavailableError(
                "OpenAI Realtime could not be reached"
            ) from exc
        if not response.is_success:
            raise RealtimeUnavailableError(_safe_provider_message(response))
        try:
            payload = response.json()
            value = str(payload["value"])
            expires_at = int(payload["expires_at"])
        except (KeyError, TypeError, ValueError) as exc:
            raise RealtimeUnavailableError(
                "OpenAI Realtime returned an invalid client secret"
            ) from exc
        if not value:
            raise RealtimeUnavailableError(
                "OpenAI Realtime returned an empty client secret"
            )
        return RealtimeClientSecret(
            value=value,
            expires_at=expires_at,
            model=self.settings.model,
            voice=self.settings.voice,
        )

    async def health(self) -> RealtimeHealth:
        if not self.settings.enabled:
            return RealtimeHealth(
                status="unavailable",
                model=self.settings.model,
                detail="Set DONE_REALTIME_ENABLED=true to enable live voice.",
            )
        if self.settings.api_key is None:
            return RealtimeHealth(
                status="unavailable",
                model=self.settings.model,
                detail="OPENAI_API_KEY is not configured.",
            )
        try:
            response = await self._client.get(
                f"/v1/models/{self.settings.model}",
                headers=self._authorization_headers(),
            )
        except httpx.HTTPError:
            return RealtimeHealth(
                status="unavailable",
                model=self.settings.model,
                detail="OpenAI Realtime could not be reached.",
            )
        if response.is_success:
            return RealtimeHealth(status="available", model=self.settings.model)
        return RealtimeHealth(
            status="unavailable",
            model=self.settings.model,
            detail=_safe_provider_message(response),
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()
