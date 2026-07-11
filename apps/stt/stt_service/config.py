"""Configuration for the isolated Whisper process."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import os
from pathlib import Path


_MODEL_FILENAMES = {
    "tiny": "tiny.pt",
    "base": "base.pt",
    "small": "small.pt",
    "medium": "medium.pt",
    "large-v3": "large-v3.pt",
    "turbo": "large-v3-turbo.pt",
    "large-v3-turbo": "large-v3-turbo.pt",
}


def _integer(name: str, default: int, minimum: int = 1) -> int:
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


def _floating(name: str, default: float, minimum: float = 0.0) -> float:
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


def _boolean(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    normalized = raw.strip().casefold()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean")


@dataclass(frozen=True, slots=True)
class STTSettings:
    model: str = "turbo"
    model_dir: Path = Path.home() / ".cache" / "whisper"
    device: str = "cpu"
    default_language: str = "pl"
    allow_model_download: bool = False
    max_upload_bytes: int = 15 * 1024 * 1024
    max_audio_seconds: float = 90.0
    max_concurrency: int = 1
    ffmpeg_binary: str = "ffmpeg"
    ffmpeg_timeout_seconds: float = 30.0
    upload_chunk_bytes: int = 64 * 1024

    def __post_init__(self) -> None:
        object.__setattr__(self, "model_dir", Path(self.model_dir).expanduser())
        if self.device != "cpu":
            raise ValueError("STT_DEVICE must be cpu for the supported local runtime")
        if not self.default_language.strip():
            raise ValueError("STT_DEFAULT_LANGUAGE cannot be empty")
        if not self.ffmpeg_binary.strip():
            raise ValueError("STT_FFMPEG_BINARY cannot be empty")

    @property
    def model_path(self) -> Path:
        filename = _MODEL_FILENAMES.get(self.model, f"{self.model}.pt")
        return self.model_dir / filename

    @classmethod
    def from_env(cls) -> "STTSettings":
        return cls(
            model=os.getenv("STT_MODEL", "turbo"),
            model_dir=Path(os.getenv("STT_MODEL_DIR", str(Path.home() / ".cache" / "whisper"))),
            device=os.getenv("STT_DEVICE", "cpu"),
            default_language=os.getenv("STT_DEFAULT_LANGUAGE", "pl"),
            allow_model_download=_boolean("STT_ALLOW_MODEL_DOWNLOAD", False),
            max_upload_bytes=_integer("STT_MAX_UPLOAD_BYTES", 15 * 1024 * 1024),
            max_audio_seconds=_floating("STT_MAX_AUDIO_SECONDS", 90.0),
            max_concurrency=_integer("STT_MAX_CONCURRENCY", 1),
            ffmpeg_binary=os.getenv("STT_FFMPEG_BINARY", "ffmpeg"),
            ffmpeg_timeout_seconds=_floating("STT_FFMPEG_TIMEOUT_SECONDS", 30.0),
            upload_chunk_bytes=_integer("STT_UPLOAD_CHUNK_BYTES", 64 * 1024),
        )


@lru_cache(maxsize=1)
def get_settings() -> STTSettings:
    return STTSettings.from_env()
