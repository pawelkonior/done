from __future__ import annotations

import pytest

from app.access import AccessConfigurationError, ApiAccessSettings


def test_demo_auth_is_optional(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DONE_API_AUTH_ENABLED", raising=False)
    monkeypatch.delenv("DONE_API_AUTH_TOKEN", raising=False)

    settings = ApiAccessSettings.from_env(commerce_mode="demo")

    assert settings.enabled is False
    assert settings.accepts(None) is True


def test_live_mode_refuses_to_start_without_a_strong_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DONE_API_AUTH_ENABLED", raising=False)
    monkeypatch.delenv("DONE_API_AUTH_TOKEN", raising=False)

    with pytest.raises(AccessConfigurationError, match="at least 32"):
        ApiAccessSettings.from_env(commerce_mode="live")


def test_enabled_access_uses_an_exact_bearer_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = "test-token-with-more-than-32-characters"
    monkeypatch.setenv("DONE_API_AUTH_ENABLED", "true")
    monkeypatch.setenv("DONE_API_AUTH_TOKEN", token)
    settings = ApiAccessSettings.from_env(commerce_mode="sandbox")

    assert settings.accepts(f"Bearer {token}") is True
    assert settings.accepts(f"bearer {token}") is True
    assert settings.accepts("Bearer wrong-token") is False
    assert settings.accepts(None) is False
