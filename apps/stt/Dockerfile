FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    STT_MODEL=turbo \
    STT_DEVICE=cpu \
    STT_MODEL_DIR=/models \
    STT_ALLOW_MODEL_DOWNLOAD=false

RUN apt-get update \
    && apt-get install --no-install-recommends -y ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /service

COPY pyproject.toml README.md ./
COPY stt_service ./stt_service

# Installs the runtime, never a model checkpoint. Mount the existing Whisper
# cache read-only at /models when the container starts.
RUN pip install --no-cache-dir '.[inference]'

EXPOSE 8002

CMD ["uvicorn", "stt_service.main:app", "--host", "0.0.0.0", "--port", "8002", "--workers", "1"]
