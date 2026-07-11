from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.access import AccessConfigurationError
from app.main import create_app


def test_enabled_api_access_protects_user_and_mission_routes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = "private-test-token-with-at-least-32-characters"
    monkeypatch.setenv("DONE_API_AUTH_ENABLED", "true")
    monkeypatch.setenv("DONE_API_AUTH_TOKEN", token)
    with TestClient(create_app(tmp_path / "auth.sqlite3")) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/v1/missions").status_code == 401
        assert client.get(
            "/v1/missions",
            headers={"Authorization": f"Bearer {token}"},
        ).status_code == 200
        assert client.get("/v1/users/me").status_code == 401
        preflight = client.options(
            "/v1/missions",
            headers={
                "Origin": "http://localhost:8081",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "authorization",
            },
        )
        assert preflight.status_code == 200
        assert "authorization" in preflight.headers[
            "access-control-allow-headers"
        ].casefold()


def test_live_api_refuses_an_unauthenticated_configuration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DONE_COMMERCE_MODE", "live")
    monkeypatch.delenv("DONE_API_AUTH_ENABLED", raising=False)
    monkeypatch.delenv("DONE_API_AUTH_TOKEN", raising=False)

    with pytest.raises(AccessConfigurationError):
        create_app(tmp_path / "live.sqlite3")
