from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any

from app.application.mission_service import (
    MissionApplicationService,
    MissionServiceSettings,
)
from app.application.ports.ai import (
    AIResult,
    AudioPayload,
    MissionIntentDraft,
    TranscriptionResult,
)
from app.database import Database
from app.workflow import MissionWorkflow


class FakeAI:
    async def extract_mission(
        self,
        transcript: str,
        *,
        locale: str,
        timezone: str,
        now: datetime,
    ) -> AIResult[MissionIntentDraft]:
        del transcript, locale, timezone, now
        return AIResult(
            value=MissionIntentDraft(
                goal="prepare_birthday_party",
                title="Przyjęcie dla dzieci",
                participants=999,
                budget=1,
                currency="USD",
                categories=["cake", "decorations"],
                hard_constraints=[],
                soft_preferences=["colorful"],
                deadline_text="in two years",
                confidence=0.91,
            ),
            provider="ollama",
            model="fake-model",
        )

    async def health(self) -> Any:
        raise NotImplementedError


class FakeSpeech:
    async def transcribe(self, audio: AudioPayload) -> TranscriptionResult:
        assert audio.data == b"audio"
        return TranscriptionResult(
            text=(
                "Jutro urodziny dla 10 dzieci, jedzenie i dekoracje do 300 PLN, "
                "bez orzechów, dostawa do 16:00."
            ),
            language="pl",
            duration_ms=42,
            model="fake-whisper",
        )

    async def health(self) -> Any:
        raise NotImplementedError


def service(tmp_path: Path, *, speech: bool = False) -> MissionApplicationService:
    database = Database(tmp_path / "mission-service.sqlite3")
    database.initialize()
    return MissionApplicationService(
        MissionWorkflow(database),
        ai=FakeAI(),  # type: ignore[arg-type]
        speech_to_text=FakeSpeech() if speech else None,  # type: ignore[arg-type]
        settings=MissionServiceSettings(
            ai_enabled=True,
            stt_enabled=speech,
            inject_demo_failures=False,
        ),
    )


def test_llm_can_label_but_cannot_override_contract_invariants(tmp_path: Path) -> None:
    application = service(tmp_path)
    detail = asyncio.run(
        application.create_from_text(
            transcript=(
                "Jutro urodziny dla 10 dzieci, jedzenie i dekoracje do 300 PLN, "
                "bez orzechów, dostawa do 16:00."
            ),
            locale="pl-PL",
            timezone="Europe/Warsaw",
        )
    )

    assert detail["mission"]["title"] == "Przyjęcie dla dzieci"
    assert detail["contract"]["participants"][0]["count"] == 10
    assert detail["contract"]["budget_limit"] == 300
    assert detail["contract"]["currency"] == "PLN"
    inference_event = next(
        event for event in detail["events"] if event["type"] == "intent.parsed"
    )
    assert inference_event["payload"]["inference_provider"] == "ollama"
    assert inference_event["payload"]["inference_model"] == "fake-model"


def test_audio_use_case_uses_transcript_and_marks_voice_input(tmp_path: Path) -> None:
    application = service(tmp_path, speech=True)
    detail = asyncio.run(
        application.create_from_audio(
            data=b"audio",
            filename="mission.m4a",
            content_type="audio/m4a",
            language="pl",
            locale="pl-PL",
            timezone="Europe/Warsaw",
        )
    )

    assert detail["mission"]["input_mode"] == "voice"
    assert detail["transcription"]["model"] == "fake-whisper"
    assert "urodziny" in detail["mission"]["raw_voice_transcript"].lower()
