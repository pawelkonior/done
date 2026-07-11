from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from stt_service.audio import AudioRejected, validate_upload_metadata
from stt_service.config import STTSettings
from stt_service.engine import WhisperEngine


class FakeWhisperModel:
    def __init__(self) -> None:
        self.calls = 0

    def transcribe(self, audio: str, **options: object) -> dict:
        self.calls += 1
        assert audio.endswith(".wav")
        assert options["language"] == "pl"
        assert options["fp16"] is False
        return {
            "text": "  Kup napoje bez orzechów.  ",
            "language": "pl",
            "segments": [{"id": 0}],
        }


def test_lazy_engine_loads_model_once(tmp_path: Path) -> None:
    model = FakeWhisperModel()
    loads = 0

    def loader(_: STTSettings) -> FakeWhisperModel:
        nonlocal loads
        loads += 1
        return model

    engine = WhisperEngine(
        STTSettings(model_dir=tmp_path),
        loader=loader,
    )
    assert engine.loaded is False

    async def scenario() -> None:
        first = await engine.transcribe(tmp_path / "one.wav", language="pl")
        second = await engine.transcribe(tmp_path / "two.wav", language="pl")
        assert first.text == "Kup napoje bez orzechów."
        assert second.segments == 1

    asyncio.run(scenario())
    assert engine.loaded is True
    assert loads == 1
    assert model.calls == 2


def test_upload_metadata_is_allowlisted() -> None:
    assert validate_upload_metadata("voice.m4a", "audio/mp4") == ".m4a"
    with pytest.raises(AudioRejected) as unsupported:
        validate_upload_metadata("payload.txt", "text/plain")
    assert unsupported.value.status_code == 415
