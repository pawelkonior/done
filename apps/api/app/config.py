"""Runtime configuration for optional AI services.

The deterministic workflow does not depend on these settings.  They are kept
in a separate module so local Ollama and OpenAI speech services can be enabled
without coupling the core application to a particular inference runtime.
"""

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
class AISettings:
    """Configuration for the optional local Ollama and legacy STT adapters."""

    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen2.5:7b"
    ollama_connect_timeout_seconds: float = 2.0
    ollama_request_timeout_seconds: float = 60.0
    ollama_max_concurrency: int = 1
    ollama_num_ctx: int = 4_096
    ollama_num_predict: int = 256
    ollama_temperature: float = 0.0
    ollama_seed: int = 42
    ollama_keep_alive: str = "15m"
    ollama_max_tool_rounds: int = 4

    whisper_base_url: str = "http://127.0.0.1:8002"
    whisper_model: str = "turbo"
    whisper_connect_timeout_seconds: float = 2.0
    whisper_request_timeout_seconds: float = 120.0
    whisper_max_concurrency: int = 1
    whisper_max_upload_bytes: int = 15 * 1024 * 1024
    whisper_default_language: str = "pl"

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "ollama_base_url",
            _http_url("DONE_OLLAMA_BASE_URL", self.ollama_base_url),
        )
        object.__setattr__(
            self,
            "whisper_base_url",
            _http_url("DONE_WHISPER_BASE_URL", self.whisper_base_url),
        )
        if not self.ollama_model.strip():
            raise ValueError("DONE_OLLAMA_MODEL cannot be empty")
        if not self.ollama_keep_alive.strip():
            raise ValueError("DONE_OLLAMA_KEEP_ALIVE cannot be empty")
        if not self.whisper_default_language.strip():
            raise ValueError("DONE_WHISPER_DEFAULT_LANGUAGE cannot be empty")
        if not self.whisper_model.strip():
            raise ValueError("DONE_WHISPER_MODEL cannot be empty")

    @classmethod
    def from_env(cls) -> "AISettings":
        return cls(
            ollama_base_url=os.getenv("DONE_OLLAMA_BASE_URL", "http://127.0.0.1:11434"),
            ollama_model=os.getenv("DONE_OLLAMA_MODEL", "qwen2.5:7b"),
            ollama_connect_timeout_seconds=_env_float("DONE_OLLAMA_CONNECT_TIMEOUT_SECONDS", 2.0),
            ollama_request_timeout_seconds=_env_float("DONE_OLLAMA_REQUEST_TIMEOUT_SECONDS", 60.0),
            ollama_max_concurrency=_env_int("DONE_OLLAMA_MAX_CONCURRENCY", 1),
            ollama_num_ctx=_env_int("DONE_OLLAMA_NUM_CTX", 4_096),
            ollama_num_predict=_env_int("DONE_OLLAMA_NUM_PREDICT", 256),
            ollama_temperature=_env_float("DONE_OLLAMA_TEMPERATURE", 0.0),
            ollama_seed=_env_int("DONE_OLLAMA_SEED", 42, minimum=0),
            ollama_keep_alive=os.getenv("DONE_OLLAMA_KEEP_ALIVE", "15m"),
            ollama_max_tool_rounds=_env_int("DONE_OLLAMA_MAX_TOOL_ROUNDS", 4),
            whisper_base_url=os.getenv("DONE_WHISPER_BASE_URL", "http://127.0.0.1:8002"),
            whisper_model=os.getenv("DONE_WHISPER_MODEL", "turbo"),
            whisper_connect_timeout_seconds=_env_float("DONE_WHISPER_CONNECT_TIMEOUT_SECONDS", 2.0),
            whisper_request_timeout_seconds=_env_float(
                "DONE_WHISPER_REQUEST_TIMEOUT_SECONDS", 120.0
            ),
            whisper_max_concurrency=_env_int("DONE_WHISPER_MAX_CONCURRENCY", 1),
            whisper_max_upload_bytes=_env_int("DONE_WHISPER_MAX_UPLOAD_BYTES", 15 * 1024 * 1024),
            whisper_default_language=os.getenv("DONE_WHISPER_DEFAULT_LANGUAGE", "pl"),
        )


@lru_cache(maxsize=1)
def get_ai_settings() -> AISettings:
    """Return one immutable environment snapshot per API process."""

    return AISettings.from_env()


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
