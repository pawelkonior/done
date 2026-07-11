# Done local STT sidecar

Private FastAPI service wrapping the already cached OpenAI Whisper
`large-v3-turbo` checkpoint. It normalizes uploads with `ffmpeg`, runs one CPU
inference at a time, and deletes each temporary input before returning.

## Endpoints

- `GET /health` checks the package, checkpoint and ffmpeg without loading the model.
- `POST /v1/audio/transcriptions` accepts multipart `file` and optional `language`.

Example:

```bash
curl -F 'file=@recording.m4a;type=audio/mp4' \
  -F 'language=pl' \
  http://127.0.0.1:8002/v1/audio/transcriptions
```

```json
{
  "text": "Kup napoje bez orzechów.",
  "language": "pl",
  "duration_ms": 1585,
  "audio_duration_seconds": 9.505,
  "model": "turbo",
  "segments": 2
}
```

## Use the existing host installation

The host already has Whisper and both checkpoints under `~/.cache/whisper`.
Create a lightweight environment which can see those system packages; this
does not download the model again:

```bash
cd apps/stt
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3.13 \
  -m venv --system-site-packages .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/uvicorn stt_service.main:app --host 127.0.0.1 --port 8002 --workers 1
```

For Docker, mount the existing checkpoint cache. The image installs inference
code but intentionally does not bake or download a model:

```bash
docker build -t done-stt apps/stt
docker run --rm -p 127.0.0.1:8002:8002 \
  -v "$HOME/.cache/whisper:/models:ro" done-stt
```

The Done API should be the only consumer. A phone connects to the API on port
8001, never directly to this service.

## Configuration

| Variable | Default |
| --- | --- |
| `STT_MODEL` | `turbo` |
| `STT_MODEL_DIR` | `~/.cache/whisper` |
| `STT_DEVICE` | `cpu` |
| `STT_DEFAULT_LANGUAGE` | `pl` |
| `STT_ALLOW_MODEL_DOWNLOAD` | `false` |
| `STT_MAX_UPLOAD_BYTES` | `15728640` |
| `STT_MAX_AUDIO_SECONDS` | `90` |
| `STT_MAX_CONCURRENCY` | `1` |
| `STT_FFMPEG_TIMEOUT_SECONDS` | `30` |

MPS is deliberately disabled: the installed PyTorch/Whisper combination fails
on a sparse tensor operation. On the local M4 Pro, CPU turbo transcription of
a 9.5-second Polish sample took approximately 1.6 seconds after model load.
