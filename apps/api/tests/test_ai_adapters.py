from __future__ import annotations

import asyncio
from datetime import datetime
import json
from zoneinfo import ZoneInfo

import httpx

from app.application.ports.ai import (
    AIChatResponse,
    AIMessage,
    AITool,
    AudioPayload,
    MissionIntentDraft,
)
from app.config import AISettings, TranscriptionSettings
from app.infrastructure.ai.ollama import OllamaAdapter
from app.infrastructure.ai.openai_transcription import (
    OpenAITranscriptionAdapter,
    OpenAITranscriptionError,
)
from app.infrastructure.ai.whisper import WhisperSidecarAdapter


def settings() -> AISettings:
    return AISettings(
        ollama_base_url="http://ollama.test",
        whisper_base_url="http://stt.test",
    )


def transcription_settings() -> TranscriptionSettings:
    return TranscriptionSettings(
        api_key="standard-server-key",
        base_url="https://api.openai.test",
        model="gpt-4o-transcribe",
    )


def test_ollama_structured_output_uses_schema_and_validates() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/chat"
        payload = json.loads(request.content)
        assert payload["format"] == MissionIntentDraft.model_json_schema()
        assert payload["options"]["num_ctx"] == 4_096
        content = MissionIntentDraft(
            goal="prepare_birthday_party",
            title="Przyjęcie urodzinowe",
            participants=10,
            budget=300,
            currency="PLN",
            categories=["snacks", "drinks", "decorations"],
            hard_constraints=["nut_free"],
            deadline_text="przed 16:00",
            confidence=0.94,
        ).model_dump_json()
        return httpx.Response(
            200,
            json={"message": {"role": "assistant", "content": content}, "done": True},
        )

    async def scenario() -> None:
        async with httpx.AsyncClient(
            base_url="http://ollama.test",
            transport=httpx.MockTransport(handler),
        ) as client:
            adapter = OllamaAdapter(settings(), client=client)
            result = await adapter.extract_mission(
                "Urodziny dla 10 dzieci do 300 PLN, bez orzechów, przed 16:00.",
                locale="pl-PL",
                timezone="Europe/Warsaw",
                now=datetime(2026, 7, 11, tzinfo=ZoneInfo("Europe/Warsaw")),
            )
            assert result.used_fallback is False
            assert result.value.participants == 10
            assert result.value.deadline_text == "przed 16:00"

    asyncio.run(scenario())


def test_ollama_invalid_json_uses_deterministic_fallback() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"message": {"role": "assistant", "content": "not-json"}, "done": True},
        )

    async def scenario() -> None:
        async with httpx.AsyncClient(
            base_url="http://ollama.test",
            transport=httpx.MockTransport(handler),
        ) as client:
            adapter = OllamaAdapter(settings(), client=client)
            result = await adapter.extract_mission(
                "Jutro urodziny dla 10 dzieci. Jedzenie i napoje do 300 PLN, "
                "bez orzechów, z dostawą przed 16:00.",
                locale="pl-PL",
                timezone="Europe/Warsaw",
                now=datetime(2026, 7, 11, tzinfo=ZoneInfo("Europe/Warsaw")),
            )
            assert result.used_fallback is True
            assert result.value.participants == 10
            assert result.value.budget == 300
            assert result.value.hard_constraints == ["nut_free"]
            assert "ValidationError" in (result.fallback_reason or "")

    asyncio.run(scenario())


def test_ollama_semantic_omissions_use_deterministic_fallback() -> None:
    incomplete = MissionIntentDraft(
        goal="prepare_birthday_party",
        title="Urodziny",
        budget=300,
        currency="PLN",
        deadline_text="2026-07-12T16:00:00+02:00",
        confidence=1,
    )

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "message": {"role": "assistant", "content": incomplete.model_dump_json()},
                "done": True,
            },
        )

    async def scenario() -> None:
        async with httpx.AsyncClient(
            base_url="http://ollama.test",
            transport=httpx.MockTransport(handler),
        ) as client:
            adapter = OllamaAdapter(settings(), client=client)
            result = await adapter.extract_mission(
                "Jutro urodziny dla 10 dzieci. Jedzenie i napoje do 300 PLN, "
                "bez orzechów, z dostawą przed 16:00.",
                locale="pl-PL",
                timezone="Europe/Warsaw",
                now=datetime(2026, 7, 11, tzinfo=ZoneInfo("Europe/Warsaw")),
            )
            assert result.used_fallback is True
            assert result.value.participants == 10
            assert result.value.categories == ["snacks", "drinks"]
            assert result.value.hard_constraints == ["nut_free"]
            assert result.value.deadline_text == "Jutro; z dostawą przed 16:00"
            assert "semantic validation" in (result.fallback_reason or "")

    asyncio.run(scenario())


def test_ollama_tool_calls_are_allowlisted() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["tools"][0]["function"]["name"] == "search_products"
        return httpx.Response(
            200,
            json={
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call-1",
                            "function": {
                                "name": "search_products",
                                "arguments": {
                                    "query": "przekąski",
                                    "max_price": 50,
                                    "nut_free": True,
                                },
                            },
                        }
                    ],
                },
                "done": True,
            },
        )

    tool = AITool(
        name="search_products",
        description="Search the local catalog",
        parameters={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    )

    async def scenario() -> None:
        async with httpx.AsyncClient(
            base_url="http://ollama.test",
            transport=httpx.MockTransport(handler),
        ) as client:
            adapter = OllamaAdapter(settings(), client=client)
            result = await adapter.chat_with_tools(
                messages=(AIMessage(role="user", content="Znajdź przekąski"),),
                tools=(tool,),
                fallback=lambda: AIChatResponse(content="fallback"),
            )
            assert result.used_fallback is False
            assert result.value.tool_calls[0].name == "search_products"

    asyncio.run(scenario())


def test_ollama_health_checks_installed_and_loaded_model() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/version":
            return httpx.Response(200, json={"version": "0.31.2"})
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "qwen2.5:7b"}]})
        if request.url.path == "/api/ps":
            return httpx.Response(200, json={"models": [{"name": "qwen2.5:7b"}]})
        return httpx.Response(404)

    async def scenario() -> None:
        async with httpx.AsyncClient(
            base_url="http://ollama.test",
            transport=httpx.MockTransport(handler),
        ) as client:
            health = await OllamaAdapter(settings(), client=client).health()
            assert health.status == "available"
            assert health.version == "0.31.2"
            assert health.model_loaded is True

    asyncio.run(scenario())


def test_whisper_sidecar_adapter_uses_multipart_and_validates_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/audio/transcriptions"
        assert request.headers["content-type"].startswith("multipart/form-data;")
        return httpx.Response(
            200,
            json={
                "text": "Kup napoje bez orzechów.",
                "language": "pl",
                "duration_ms": 410,
                "audio_duration_seconds": 2.5,
                "model": "turbo",
                "segments": 1,
            },
        )

    async def scenario() -> None:
        async with httpx.AsyncClient(
            base_url="http://stt.test",
            transport=httpx.MockTransport(handler),
        ) as client:
            adapter = WhisperSidecarAdapter(settings(), client=client)
            result = await adapter.transcribe(
                AudioPayload(
                    data=b"fake-m4a",
                    filename="voice.m4a",
                    content_type="audio/mp4",
                    language="pl",
                )
            )
            assert result.model == "turbo"
            assert result.text == "Kup napoje bez orzechów."

    asyncio.run(scenario())


def test_openai_transcription_uses_high_accuracy_model_and_multipart() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/audio/transcriptions"
        assert request.headers["authorization"] == "Bearer standard-server-key"
        assert request.headers["content-type"].startswith("multipart/form-data;")
        body = request.content
        assert b'gpt-4o-transcribe' in body
        assert b'name="language"' in body
        assert b'\r\n\r\npl\r\n' in body
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
