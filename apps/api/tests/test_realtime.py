from __future__ import annotations

import asyncio
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from app.application.mission_service import MissionServiceSettings
from app.application.ports.realtime import RealtimeClientSecret, RealtimeHealth
from app.config import RealtimeSettings
from app.infrastructure.ai.openai_realtime import (
    OpenAIRealtimeAdapter,
    RealtimeUnavailableError,
)
from app.main import create_app


def realtime_settings(*, enabled: bool = True) -> RealtimeSettings:
    return RealtimeSettings(
        enabled=enabled,
        api_key="standard-server-key" if enabled else None,
        base_url="https://api.openai.test",
        model="gpt-realtime-1.5",
        voice="marin",
        transcription_model="gpt-realtime-whisper",
    )


def test_realtime_adapter_mints_scoped_ephemeral_secret() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/realtime/client_secrets"
        assert request.headers["authorization"] == "Bearer standard-server-key"
        assert request.headers["openai-safety-identifier"] == "hashed-user"
        payload = json.loads(request.content)
        session = payload["session"]
        assert session["type"] == "realtime"
        assert session["model"] == "gpt-realtime-1.5"
        assert session["audio"]["output"]["voice"] == "marin"
        assert session["audio"]["input"]["transcription"] == {
            "model": "gpt-realtime-whisper",
            "language": "pl",
        }
        assert session["tools"][0]["name"] == "submit_mission"
        assert "deterministic Done backend" in session["instructions"]
        return httpx.Response(
            200,
            json={"value": "ephemeral-client-secret", "expires_at": 1_900_000_000},
        )

    async def scenario() -> None:
        async with httpx.AsyncClient(
            base_url="https://api.openai.test",
            transport=httpx.MockTransport(handler),
        ) as client:
            adapter = OpenAIRealtimeAdapter(realtime_settings(), client=client)
            secret = await adapter.create_client_secret(
                language="pl-PL",
                safety_identifier="hashed-user",
            )
            assert secret.value == "ephemeral-client-secret"
            assert secret.model == "gpt-realtime-1.5"
            assert "ephemeral-client-secret" not in repr(secret)
            assert "standard-server-key" not in repr(adapter.settings)

    asyncio.run(scenario())


def test_realtime_adapter_redacts_provider_error_body() -> None:
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
            adapter = OpenAIRealtimeAdapter(realtime_settings(), client=client)
            try:
                await adapter.create_client_secret(
                    language="en-US",
                    safety_identifier="hashed-user",
                )
            except RealtimeUnavailableError as exc:
                message = str(exc)
            else:  # pragma: no cover - protects the redaction assertion
                raise AssertionError("expected RealtimeUnavailableError")
            assert "standard-server-key" not in message
            assert "req_safe" in message

    asyncio.run(scenario())


@dataclass
class FakeRealtime:
    closed: bool = False
    safety_identifier: str | None = None
    language: str | None = None

    async def create_client_secret(
        self,
        *,
        language: str,
        safety_identifier: str,
    ) -> RealtimeClientSecret:
        self.language = language
        self.safety_identifier = safety_identifier
        return RealtimeClientSecret(
            value="short-lived-secret",
            expires_at=1_900_000_000,
            model="gpt-realtime-1.5",
            voice="marin",
        )

    async def health(self) -> RealtimeHealth:
        return RealtimeHealth(status="available", model="gpt-realtime-1.5")

    async def aclose(self) -> None:
        self.closed = True


def test_realtime_endpoint_returns_only_ephemeral_credentials(tmp_path: Path) -> None:
    fake = FakeRealtime()
    application = create_app(
        tmp_path / "realtime.sqlite3",
        mission_settings=MissionServiceSettings(),
        realtime=fake,
        realtime_settings=realtime_settings(),
    )
    with TestClient(application) as client:
        response = client.post(
            "/v1/realtime/client-secret",
            json={"language": "pl-PL"},
        )
        capabilities = client.get("/v1/runtime/capabilities")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "value": "short-lived-secret",
        "expires_at": 1_900_000_000,
        "model": "gpt-realtime-1.5",
        "voice": "marin",
    }
    assert "standard-server-key" not in response.text
    assert fake.language == "pl-PL"
    assert fake.safety_identifier == sha256(b"done:demo-user").hexdigest()
    assert capabilities.json()["realtime"]["status"] == "available"
    assert fake.closed is True


def test_realtime_endpoint_fails_closed_when_disabled(tmp_path: Path) -> None:
    application = create_app(
        tmp_path / "disabled.sqlite3",
        mission_settings=MissionServiceSettings(),
        realtime_settings=realtime_settings(enabled=False),
    )
    with TestClient(application) as client:
        response = client.post(
            "/v1/realtime/client-secret",
            json={"language": "pl-PL"},
        )
        capabilities = client.get("/v1/runtime/capabilities")

    assert response.status_code == 503
    assert response.json()["error"] == "realtime_unavailable"
    assert capabilities.json()["realtime"]["status"] == "disabled"
