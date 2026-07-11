"""Local speech-to-text service.

The FastAPI entrypoint intentionally is not imported here.  This keeps config
and engine modules usable in lightweight tests without loading multipart or
Whisper dependencies.
"""
