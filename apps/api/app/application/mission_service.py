"""Application use cases for creating missions from text or audio.

This module is the orchestration boundary between the mission domain workflow
and optional inference adapters.  The LLM may improve descriptive metadata,
but it is deliberately not authoritative for money, dates or hard policies.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
import os
from typing import Any

from ..domain.common import Money
from ..domain.mission.policies import MissionExecutionPolicy
from .ports.ai import AudioPayload, SpeechToTextPort, StructuredAIPort
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
    ai_enabled: bool = False
    stt_enabled: bool = False
    inject_demo_failures: bool = True
    demo_endpoints_enabled: bool = True

    @classmethod
    def from_env(cls) -> "MissionServiceSettings":
        return cls(
            ai_enabled=_env_bool("DONE_AI_ENABLED", False),
            stt_enabled=_env_bool("DONE_STT_ENABLED", False),
            inject_demo_failures=_env_bool("DONE_DEMO_FAILURES_ENABLED", True),
            demo_endpoints_enabled=_env_bool("DONE_DEMO_ENDPOINTS_ENABLED", True),
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
        ai: StructuredAIPort | None = None,
        speech_to_text: SpeechToTextPort | None = None,
        user_service: UserApplicationService | None = None,
        settings: MissionServiceSettings | None = None,
    ) -> None:
        self.workflow = workflow
        self.ai = ai
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
        interpretation["inference_provider"] = "deterministic"

        if self.settings.ai_enabled and self.ai is not None:
            result = await self.ai.extract_mission(
                safe_transcript,
                locale=locale,
                timezone=timezone,
                now=datetime.now(UTC),
            )
            draft = result.value

            # A model can improve a label, never a safety-critical field.  The
            # deterministic interpreter remains authoritative for participant
            # count, budget, deadline, currency and all hard constraints.
            supported_categories = {
                "cake",
                "decorations",
                "drinks",
                "snacks",
                "tableware",
            }
            if set(draft.categories) & supported_categories and draft.title.strip():
                interpretation["title"] = draft.title.strip()
            interpretation["confidence"] = min(
                float(interpretation["confidence"]), float(draft.confidence)
            )
            interpretation["inference_provider"] = result.provider
            interpretation["inference_model"] = result.model
            interpretation["inference_fallback_reason"] = result.fallback_reason

        execution_policy = MissionExecutionPolicy()
        if self.user_service is not None:
            user_settings = self.user_service.get_settings()
            profile = self.user_service.get_profile().profile
            approval_mode = user_settings.approval_policy.value
            threshold_minor = user_settings.approval_threshold.minor
            if (
                approval_mode == "above_threshold"
                and user_settings.approval_threshold.currency != "PLN"
            ):
                # Comparing money without an FX quote is unsafe. Until the
                # exchange-rate port exists, fail closed by requiring approval.
                approval_mode = "always"
                threshold_minor = 0
            execution_policy = MissionExecutionPolicy(
                approval_mode=approval_mode,
                approval_threshold=Money(threshold_minor, "PLN"),
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
        ai_health: Any = {
            "status": "disabled",
            "provider": "ollama",
            "detail": "Set DONE_AI_ENABLED=true to enable local inference.",
        }
        stt_health: Any = {
            "status": "disabled",
            "detail": "Set DONE_STT_ENABLED=true to enable OpenAI speech recognition.",
        }

        tasks: list[tuple[str, Any]] = []
        if self.settings.ai_enabled and self.ai is not None:
            tasks.append(("ai", self.ai.health()))
        if self.settings.stt_enabled and self.speech_to_text is not None:
            tasks.append(("stt", self.speech_to_text.health()))
        if tasks:
            results = await asyncio.gather(
                *(task for _, task in tasks), return_exceptions=True
            )
            for (kind, _), result in zip(tasks, results, strict=True):
                if isinstance(result, Exception):
                    value: Any = {
                        "status": "unavailable",
                        "detail": f"{type(result).__name__}: {result}",
                    }
                else:
                    value = result.model_dump()
                if kind == "ai":
                    ai_health = value
                else:
                    stt_health = value

        return {
            "ai": ai_health,
            "speech_to_text": stt_health,
            "demo_failures": self.settings.inject_demo_failures,
            "demo_endpoints": self.settings.demo_endpoints_enabled,
        }

    async def aclose(self) -> None:
        for adapter in (self.ai, self.speech_to_text):
            closer = getattr(adapter, "aclose", None)
            if closer is not None:
                await closer()
