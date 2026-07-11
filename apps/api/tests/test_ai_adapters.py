from __future__ import annotations

import asyncio

import httpx

from app.application.ports.ai import AudioPayload
from app.config import TranscriptionSettings
from app.infrastructure.ai.openai_transcription import (
    OpenAITranscriptionAdapter,
    OpenAITranscriptionError,
)


def transcription_settings() -> TranscriptionSettings:
    return TranscriptionSettings(
        api_key="standard-server-key",
        base_url="https://api.openai.test",
        model="gpt-4o-transcribe",
    )


def test_openai_transcription_uses_high_accuracy_model_and_multipart() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/audio/transcriptions"
        assert request.headers["authorization"] == "Bearer standard-server-key"
        assert request.headers["content-type"].startswith("multipart/form-data;")
        body = request.content
        assert b"gpt-4o-transcribe" in body
        assert b'name="language"' in body
        assert b"\r\n\r\npl\r\n" in body
        assert b'name="prompt"' in body
        return httpx.Response(200, json={"text": "Kup napoje bez orzechów."})

    async def scenario() -> None:
        async with httpx.AsyncClient(
            base_url="https://api.openai.test",
            transport=httpx.MockTransport(handler),
        ) as client:
            adapter = OpenAITranscriptionAdapter(
                transcription_settings(),
                client=client,
            )
            result = await adapter.transcribe(
                AudioPayload(
                    data=b"fake-m4a",
                    filename="voice.m4a",
                    content_type="audio/mp4",
                    language="pl-PL",
                )
            )
            assert result.model == "gpt-4o-transcribe"
            assert result.language == "pl"
            assert result.text == "Kup napoje bez orzechów."
            assert "standard-server-key" not in repr(adapter.settings)

    asyncio.run(scenario())


def test_openai_transcription_redacts_provider_error_body() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            headers={"x-request-id": "req_safe"},
            json={"error": {"message": "standard-server-key was invalid"}},
        )

    async def scenario() -> None:
        async with httpx.AsyncClient(
            base_url="https://api.openai.test",
            transport=httpx.MockTransport(handler),
        ) as client:
            adapter = OpenAITranscriptionAdapter(
                transcription_settings(),
                client=client,
            )
            try:
                await adapter.transcribe(
                    AudioPayload(
                        data=b"fake-m4a",
                        filename="voice.m4a",
                        content_type="audio/mp4",
                        language="pl",
                    )
                )
            except OpenAITranscriptionError as exc:
                message = str(exc)
            else:  # pragma: no cover - protects redaction
                raise AssertionError("expected OpenAITranscriptionError")
            assert "standard-server-key" not in message
            assert "req_safe" in message

    asyncio.run(scenario())
