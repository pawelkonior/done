from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from app.application.mission_service import (
    MissionApplicationService,
    MissionServiceSettings,
)
from app.application.ports.ai import AudioPayload, TranscriptionResult
from app.database import Database
from app.workflow import MissionWorkflow


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
            model="fake-transcription",
        )

    async def health(self) -> Any:
        raise NotImplementedError


def service(tmp_path: Path, *, speech: bool = False) -> MissionApplicationService:
    database = Database(tmp_path / "mission-service.sqlite3")
    database.initialize()
    return MissionApplicationService(
        MissionWorkflow(database),
        speech_to_text=FakeSpeech() if speech else None,  # type: ignore[arg-type]
        settings=MissionServiceSettings(
            stt_enabled=speech,
            inject_demo_failures=False,
        ),
    )


def test_text_use_case_uses_deterministic_contract_interpretation(tmp_path: Path) -> None:
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

    assert detail["mission"]["title"] == "Birthday party for 10 children"
    assert detail["contract"]["participants"][0]["count"] == 10
    assert detail["contract"]["budget_limit"] == 300
    assert detail["contract"]["currency"] == "PLN"
    inference_event = next(
        event for event in detail["events"] if event["type"] == "intent.parsed"
    )
    assert inference_event["payload"] == {
        "goal": "prepare_birthday_party",
        "confidence": 0.97,
        "missing_information": [],
    }


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
    assert detail["transcription"]["model"] == "fake-transcription"
    assert "urodziny" in detail["mission"]["raw_voice_transcript"].lower()
