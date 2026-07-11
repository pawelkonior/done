"""Local AI provider adapters."""

from .ollama import OllamaAdapter, deterministic_mission_fallback
from .whisper import WhisperSidecarAdapter

__all__ = ["OllamaAdapter", "WhisperSidecarAdapter", "deterministic_mission_fallback"]
