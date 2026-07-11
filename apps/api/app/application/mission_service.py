"""Application use cases for creating missions from text or audio.

This module is the orchestration boundary between the mission domain workflow
and server-side speech transcription. Mission interpretation and safety rules
remain deterministic.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any

from ..domain.common import Money
from ..domain.mission.policies import MissionExecutionPolicy
from .ports.ai import AudioPayload, SpeechToTextPort
from .ports.mission import MissionWorkflowPort
from .user_service import UserApplicationService


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    normalized = raw.strip().casefold()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean")


@dataclass(frozen=True, slots=True)
class MissionServiceSettings:
    stt_enabled: bool = False
    inject_demo_failures: bool = False
    demo_endpoints_enabled: bool = False

    @classmethod
    def from_env(cls) -> "MissionServiceSettings":
        return cls(
            stt_enabled=_env_bool("DONE_STT_ENABLED", False),
            inject_demo_failures=_env_bool("DONE_DEMO_FAILURES_ENABLED", False),
            demo_endpoints_enabled=_env_bool("DONE_DEMO_ENDPOINTS_ENABLED", False),
        )


class SpeechInputUnavailableError(RuntimeError):
    """Audio was supplied, but the configured STT service is unavailable."""


class EmptyTranscriptionError(ValueError):
    """The speech recognizer could not extract a usable command."""


class MissionApplicationService:
    """Coordinates ports and delegates transactional work to the workflow."""

    def __init__(
        self,
        workflow: MissionWorkflowPort,
        *,
        speech_to_text: SpeechToTextPort | None = None,
        user_service: UserApplicationService | None = None,
        settings: MissionServiceSettings | None = None,
    ) -> None:
        self.workflow = workflow
        self.speech_to_text = speech_to_text
        self.user_service = user_service
        self.settings = settings or MissionServiceSettings.from_env()

    async def create_from_text(
        self,
        *,
        transcript: str,
        locale: str,
        timezone: str,
        input_mode: str = "text",
    ) -> dict[str, Any]:
        safe_transcript = transcript.strip()
        if len(safe_transcript) < 3:
            raise ValueError("A mission transcript must contain at least 3 characters")

        interpretation = self.workflow.interpret_transcript(
            safe_transcript, locale, timezone
        )

        execution_policy = MissionExecutionPolicy()
        if self.user_service is not None:
            user_settings = self.user_service.get_settings()
            profile = self.user_service.get_profile().profile
            approval_mode = user_settings.approval_policy.value
            threshold_minor = user_settings.approval_threshold.minor
            mission_currency = str(interpretation.get("currency", "PLN"))
            if (
                approval_mode == "above_threshold"
                and user_settings.approval_threshold.currency != mission_currency
            ):
                # Comparing money without an FX quote is unsafe. Until the
                # exchange-rate port exists, fail closed by requiring approval.
                approval_mode = "always"
                threshold_minor = 0
            execution_policy = MissionExecutionPolicy(
                approval_mode=approval_mode,
                approval_threshold=Money(threshold_minor, mission_currency),
                safe_recovery_enabled=user_settings.safe_recovery_enabled,
                preferred_merchant_ids=user_settings.preferred_merchant_ids,
                default_constraints=profile.default_constraints,
            )

        return self.workflow.create_mission(
            transcript=safe_transcript,
            locale=locale,
            timezone=timezone,
            input_mode=input_mode,
            interpretation=interpretation,
            inject_demo_failures=self.settings.inject_demo_failures,
            execution_policy=execution_policy,
        )

    async def create_from_audio(
        self,
        *,
        data: bytes,
        filename: str,
        content_type: str,
        language: str | None,
        locale: str,
        timezone: str,
    ) -> dict[str, Any]:
        if not self.settings.stt_enabled or self.speech_to_text is None:
            raise SpeechInputUnavailableError(
                "Voice recognition is disabled; configure OpenAI transcription or use text"
            )
        transcription = await self.speech_to_text.transcribe(
            AudioPayload(
                data=data,
                filename=filename,
                content_type=content_type,
                language=language,
            )
        )
        if len(transcription.text.strip()) < 3:
            raise EmptyTranscriptionError(
                "No usable speech was detected; record the command again"
            )
        detail = await self.create_from_text(
            transcript=transcription.text,
            locale=locale,
            timezone=timezone,
            input_mode="voice",
        )
        detail["transcription"] = transcription.model_dump()
        return detail

    async def capabilities(self) -> dict[str, Any]:
        stt_health: Any = {
            "status": "disabled",
            "detail": "Set DONE_STT_ENABLED=true to enable OpenAI speech recognition.",
        }

        if self.settings.stt_enabled and self.speech_to_text is not None:
            try:
                stt_health = (await self.speech_to_text.health()).model_dump()
            except Exception as exc:  # noqa: BLE001 - health must remain best-effort
                stt_health = {
                    "status": "unavailable",
                    "detail": f"{type(exc).__name__}: {exc}",
                }

        return {
            "speech_to_text": stt_health,
            "demo_failures": self.settings.inject_demo_failures,
            "demo_endpoints": self.settings.demo_endpoints_enabled,
        }

    async def aclose(self) -> None:
        closer = getattr(self.speech_to_text, "aclose", None)
        if closer is not None:
            await closer()
