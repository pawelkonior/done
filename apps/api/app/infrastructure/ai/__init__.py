"""Server-side OpenAI voice adapters."""

from .openai_realtime import OpenAIRealtimeAdapter
from .openai_transcription import OpenAITranscriptionAdapter

__all__ = ["OpenAIRealtimeAdapter", "OpenAITranscriptionAdapter"]
