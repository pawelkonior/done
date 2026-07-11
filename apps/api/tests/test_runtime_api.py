from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.application.mission_service import MissionServiceSettings
from app.application.ports.ai import AudioPayload, STTHealth, TranscriptionResult
from app.main import create_app


class FakeSpeech:
    async def transcribe(self, audio: AudioPayload) -> TranscriptionResult:
        assert audio.filename == "command.m4a"
        assert audio.content_type == "audio/m4a"
        assert audio.language == "pl"
        return TranscriptionResult(
            text=(
                "Jutro urodziny dla 10 dzieci, jedzenie i dekoracje do 300 PLN, "
                "bez orzechów, dostawa przed 16:00."
            ),
            language="pl",
            duration_ms=25,
            audio_duration_seconds=2.4,
            model="fake-whisper",
            segments=1,
        )

    async def health(self) -> STTHealth:
        return STTHealth(
            status="available",
            model="fake-whisper",
            model_cached=True,
            model_loaded=True,
            ffmpeg=True,
        )


def runtime_client(tmp_path: Path) -> TestClient:
    return TestClient(
        create_app(
            tmp_path / "runtime.sqlite3",
            mission_settings=MissionServiceSettings(
                ai_enabled=False,
                stt_enabled=True,
                inject_demo_failures=False,
                demo_endpoints_enabled=False,
            ),
            speech_to_text=FakeSpeech(),
        )
    )


def test_voice_endpoint_transcribes_real_multipart(tmp_path: Path) -> None:
    with runtime_client(tmp_path) as client:
        response = client.post(
            "/v1/missions/voice",
            files={"file": ("command.m4a", b"audio bytes", "audio/m4a")},
            data={
                "locale": "pl-PL",
                "timezone": "Europe/Warsaw",
                "language": "pl-PL",
            },
        )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["mission"]["input_mode"] == "voice"
    assert body["transcription"]["text"].startswith("Jutro urodziny")
    assert body["transcription"]["model"] == "fake-whisper"
    assert response.headers["x-request-id"]


def test_capabilities_and_production_demo_gate(tmp_path: Path) -> None:
    with runtime_client(tmp_path) as client:
        capabilities = client.get("/v1/runtime/capabilities")
        reset = client.post("/v1/demo/reset")

    assert capabilities.status_code == 200
    assert capabilities.json()["ai"]["status"] == "disabled"
    assert capabilities.json()["speech_to_text"]["status"] == "available"
    assert capabilities.json()["demo_endpoints"] is False
    assert reset.status_code == 404


def test_voice_json_contract_remains_available_for_accessibility(
    tmp_path: Path,
) -> None:
    with runtime_client(tmp_path) as client:
        response = client.post(
            "/v1/missions/voice",
            json={
                "transcript": "Birthday for 10 children under 300 PLN before 16:00",
                "locale": "en-PL",
                "timezone": "Europe/Warsaw",
            },
        )

    assert response.status_code == 201, response.text
    assert response.json()["mission"]["input_mode"] == "voice"
