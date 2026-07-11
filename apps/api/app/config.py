"""Runtime configuration for server-side OpenAI voice services."""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
import os
from urllib.parse import urlparse


def _env_int(name: str, default: int, *, minimum: int = 1) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if value < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    return value


def _env_float(name: str, default: float, *, minimum: float = 0.0) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number") from exc
    if value < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    return value


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


def _http_url(name: str, value: str) -> str:
    normalized = value.rstrip("/")
    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{name} must be an absolute HTTP(S) URL")
    return normalized


@dataclass(frozen=True, slots=True)
class TranscriptionSettings:
    """Server-only configuration for OpenAI file transcription."""

    api_key: str | None = field(default=None, repr=False)
    base_url: str = "https://api.openai.com"
    model: str = "gpt-4o-transcribe"
    connect_timeout_seconds: float = 5.0
    request_timeout_seconds: float = 120.0
    max_concurrency: int = 2
    max_upload_bytes: int = 25 * 1024 * 1024
    default_language: str = "pl"

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "base_url",
            _http_url("DONE_TRANSCRIPTION_BASE_URL", self.base_url),
        )
        normalized_key = (self.api_key or "").strip() or None
        object.__setattr__(self, "api_key", normalized_key)
        if not self.model.strip():
            raise ValueError("DONE_TRANSCRIPTION_MODEL cannot be empty")
        if not self.default_language.strip():
            raise ValueError("DONE_TRANSCRIPTION_DEFAULT_LANGUAGE cannot be empty")

    @property
    def configured(self) -> bool:
        return self.api_key is not None

    @classmethod
    def from_env(cls) -> "TranscriptionSettings":
        return cls(
            api_key=os.getenv("OPENAI_API_KEY"),
            base_url=os.getenv(
                "DONE_TRANSCRIPTION_BASE_URL",
                os.getenv("OPENAI_BASE_URL", "https://api.openai.com"),
            ),
            model=os.getenv("DONE_TRANSCRIPTION_MODEL", "gpt-4o-transcribe"),
            connect_timeout_seconds=_env_float(
                "DONE_TRANSCRIPTION_CONNECT_TIMEOUT_SECONDS", 5.0
            ),
            request_timeout_seconds=_env_float(
                "DONE_TRANSCRIPTION_REQUEST_TIMEOUT_SECONDS", 120.0
            ),
            max_concurrency=_env_int("DONE_TRANSCRIPTION_MAX_CONCURRENCY", 2),
            max_upload_bytes=_env_int(
                "DONE_TRANSCRIPTION_MAX_UPLOAD_BYTES", 25 * 1024 * 1024
            ),
            default_language=os.getenv("DONE_TRANSCRIPTION_DEFAULT_LANGUAGE", "pl"),
        )


@lru_cache(maxsize=1)
def get_transcription_settings() -> TranscriptionSettings:
    """Return one immutable OpenAI transcription configuration snapshot."""

    return TranscriptionSettings.from_env()


@dataclass(frozen=True, slots=True)
class RealtimeSettings:
    """Server-only configuration for OpenAI Realtime voice sessions.

    ``api_key`` is deliberately excluded from repr output. The standard key
    never crosses the HTTP boundary; clients only receive short-lived secrets.
    """

    enabled: bool = False
    api_key: str | None = field(default=None, repr=False)
    base_url: str = "https://api.openai.com"
    model: str = "gpt-realtime-2"
    voice: str = "marin"
    transcription_model: str = "gpt-realtime-whisper"
    connect_timeout_seconds: float = 5.0
    request_timeout_seconds: float = 20.0

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "base_url",
            _http_url("DONE_REALTIME_BASE_URL", self.base_url),
        )
        normalized_key = (self.api_key or "").strip() or None
        object.__setattr__(self, "api_key", normalized_key)
        for env_name, value in (
            ("DONE_REALTIME_MODEL", self.model),
            ("DONE_REALTIME_VOICE", self.voice),
            ("DONE_REALTIME_TRANSCRIPTION_MODEL", self.transcription_model),
        ):
            if not value.strip():
                raise ValueError(f"{env_name} cannot be empty")

    @property
    def configured(self) -> bool:
        return self.enabled and self.api_key is not None

    @classmethod
    def from_env(cls) -> "RealtimeSettings":
        return cls(
            enabled=_env_bool("DONE_REALTIME_ENABLED", False),
            api_key=os.getenv("OPENAI_API_KEY"),
            base_url=os.getenv("DONE_REALTIME_BASE_URL", "https://api.openai.com"),
            model=os.getenv("DONE_REALTIME_MODEL", "gpt-realtime-2"),
            voice=os.getenv("DONE_REALTIME_VOICE", "marin"),
            transcription_model=os.getenv(
                "DONE_REALTIME_TRANSCRIPTION_MODEL", "gpt-realtime-whisper"
            ),
            connect_timeout_seconds=_env_float(
                "DONE_REALTIME_CONNECT_TIMEOUT_SECONDS", 5.0
            ),
            request_timeout_seconds=_env_float(
                "DONE_REALTIME_REQUEST_TIMEOUT_SECONDS", 20.0
            ),
        )


@lru_cache(maxsize=1)
def get_realtime_settings() -> RealtimeSettings:
    """Return one immutable Realtime configuration snapshot per process."""

    return RealtimeSettings.from_env()


@dataclass(frozen=True, slots=True)
class PortfolioShadowSettings:
    """Safe rollout controls for portfolio shadow evaluation.

    Shadow mode records a full planner run but never grants checkout authority.
    Autonomous execution remains explicitly disabled unless a separate, manual
    rollout decision enables it.
    """

    enabled: bool = False
    autonomy_enabled: bool = False
    min_shadow_runs: int = 100
    max_recommendation_diff_rate: float = 0.01
    max_price_delta_rate: float = 0.02

    def __post_init__(self) -> None:
        if self.min_shadow_runs < 1:
            raise ValueError("DONE_PORTFOLIO_SHADOW_MIN_RUNS must be >= 1")
        for name, value in (
            ("DONE_PORTFOLIO_SHADOW_MAX_RECOMMENDATION_DIFF_RATE", self.max_recommendation_diff_rate),
            ("DONE_PORTFOLIO_SHADOW_MAX_PRICE_DELTA_RATE", self.max_price_delta_rate),
        ):
            if not 0 <= value <= 1:
                raise ValueError(f"{name} must be between 0 and 1")

    @classmethod
    def from_env(cls) -> "PortfolioShadowSettings":
        return cls(
            enabled=_env_bool("DONE_PORTFOLIO_SHADOW_MODE", False),
            autonomy_enabled=_env_bool("DONE_PORTFOLIO_AUTONOMY_ENABLED", False),
            min_shadow_runs=_env_int("DONE_PORTFOLIO_SHADOW_MIN_RUNS", 100),
            max_recommendation_diff_rate=_env_float(
                "DONE_PORTFOLIO_SHADOW_MAX_RECOMMENDATION_DIFF_RATE", 0.01
            ),
            max_price_delta_rate=_env_float(
                "DONE_PORTFOLIO_SHADOW_MAX_PRICE_DELTA_RATE", 0.02
            ),
        )

    @property
    def promotion_gate(self) -> dict[str, object]:
        return {
            "minimum_shadow_runs": self.min_shadow_runs,
            "maximum_recommendation_diff_rate": self.max_recommendation_diff_rate,
            "maximum_price_delta_rate": self.max_price_delta_rate,
            "requires_manual_approval": True,
            "automatic_purchases_default": False,
        }


@lru_cache(maxsize=1)
def get_portfolio_shadow_settings() -> PortfolioShadowSettings:
    """Return one immutable portfolio rollout configuration snapshot."""

    return PortfolioShadowSettings.from_env()
