"""Jarvis voice service: local speech-to-text (whisper.cpp) and text-to-speech (Piper).

Runs entirely offline on CPU. The Dockerfile already installs everything this module
uses:

- ``/whisper/build/bin/whisper-cli`` + ``/whisper/models/ggml-base.en.bin``
- Piper (``python -m piper``) + ``/voices/en_US-lessac-medium.onnx``
- ``ffmpeg`` for decoding the browser's WAV/WebM recording

Endpoints:
    GET  /health   Liveness probe (also reports whether the model files are present).
    POST /stt      Multipart ``file`` -> ``{"text": "..."}``.
    POST /tts      JSON ``{"text": "..."}`` -> audio/wav bytes.

Everything is written under ``/tmp`` (tmpfs) because the container root filesystem is
read-only. Audio and transcripts are never logged.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, File, HTTPException, UploadFile, status
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger("jarvis.voice")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

WHISPER_BIN = os.environ.get("WHISPER_BIN", "/whisper/build/bin/whisper-cli")
WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "/whisper/models/ggml-base.en.bin")
PIPER_MODEL = os.environ.get("PIPER_MODEL", "/voices/en_US-lessac-medium.onnx")
PIPER_CONFIG = os.environ.get("PIPER_CONFIG", f"{PIPER_MODEL}.json")

MAX_AUDIO_BYTES = 25 * 1024 * 1024
MAX_SPEECH_CHARS = 4_000
PROCESS_TIMEOUT_S = 300

# Whisper and Piper each saturate the CPU. One job at a time keeps latency predictable
# and mirrors what the rest of Jarvis already does for Ollama.
_voice_lock = threading.Lock()


class SynthesizeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    text: str = Field(min_length=1, max_length=MAX_SPEECH_CHARS)


app = FastAPI(title="Jarvis Voice", version="0.1.0", docs_url=None, redoc_url=None, openapi_url=None)


def _missing_tools() -> list[str]:
    missing: list[str] = []
    if not Path(WHISPER_BIN).is_file():
        missing.append("whisper-cli")
    if not Path(WHISPER_MODEL).is_file():
        missing.append("whisper model")
    if not Path(PIPER_MODEL).is_file():
        missing.append("piper voice")
    if not Path(PIPER_CONFIG).is_file():
        missing.append("piper config")
    if shutil.which("ffmpeg") is None:
        missing.append("ffmpeg")
    return missing


@app.get("/health")
def health() -> dict[str, object]:
    """Liveness plus a quick check that the local models shipped with the image."""
    missing = _missing_tools()
    return {
        "status": "ok" if not missing else "degraded",
        "service": "voice",
        "missing": missing,
    }


def _run(command: list[str], *, stdin: bytes | None = None) -> subprocess.CompletedProcess[bytes]:
    """Run a local tool with a hard timeout. The caller never sees its stderr."""
    return subprocess.run(
        command,
        input=stdin,
        capture_output=True,
        timeout=PROCESS_TIMEOUT_S,
        check=False,
    )


@app.post("/stt")
def speech_to_text(file: Annotated[UploadFile, File()]) -> dict[str, str]:
    """Transcribe one recorded clip with whisper.cpp."""
    audio = file.file.read()
    if not audio:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Empty audio upload")
    if len(audio) > MAX_AUDIO_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Audio clip is too large")
    if _missing_tools():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="Voice models are not installed")

    if not _voice_lock.acquire(blocking=False):
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="Voice service is busy")

    try:
        with tempfile.TemporaryDirectory(dir="/tmp", prefix="jarvis-stt-") as work:
            source = Path(work) / "input"
            source.write_bytes(audio)
            wav = Path(work) / "audio.wav"
            converted = _run(
                ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
                 "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(wav)]
            )
            if converted.returncode != 0 or not wav.is_file():
                logger.error("STT decode failed (ffmpeg rc=%s)", converted.returncode)
                raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Could not decode the recording")

            prefix = Path(work) / "transcript"
            result = _run(
                [WHISPER_BIN, "-m", WHISPER_MODEL, "-f", str(wav), "-l", "en",
                 "-nt", "-otxt", "-of", str(prefix)]
            )
            if result.returncode != 0:
                logger.error("STT inference failed (whisper rc=%s)", result.returncode)
                raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Transcription failed")

            text_file = prefix.with_suffix(".txt")
            if not text_file.is_file():
                logger.error("STT produced no transcript file")
                raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Transcription failed")
            text = text_file.read_text(encoding="utf-8", errors="replace").strip()
    except subprocess.TimeoutExpired as exc:
        logger.error("STT timed out")
        raise HTTPException(status.HTTP_504_GATEWAY_TIMEOUT, detail="Transcription timed out") from exc
    finally:
        _voice_lock.release()

    return {"text": text[:MAX_SPEECH_CHARS]}


def _piper_command(output_file: Path) -> list[str]:
    """Piper's CLI moved between releases; prefer the current ``python -m piper`` form."""
    return [
        sys.executable, "-m", "piper",
        "--model", PIPER_MODEL,
        "--config", PIPER_CONFIG,
        "--output_file", str(output_file),
    ]


@app.post("/tts")
def text_to_speech(payload: SynthesizeRequest) -> Response:
    """Synthesize ``payload.text`` to a WAV clip with Piper."""
    if _missing_tools():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="Voice models are not installed")
    if not _voice_lock.acquire(blocking=False):
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="Voice service is busy")

    try:
        with tempfile.TemporaryDirectory(dir="/tmp", prefix="jarvis-tts-") as work:
            output = Path(work) / "reply.wav"
            commands = [_piper_command(output)]
            # Piper's console script is the fallback for releases whose CLI is not a module.
            if piper_exe := shutil.which("piper"):
                commands.append(
                    [piper_exe, "--model", PIPER_MODEL, "--config", PIPER_CONFIG,
                     "--output_file", str(output)]
                )
            result = None
            for command in commands:
                result = _run(command, stdin=payload.text.encode("utf-8"))
                if result.returncode == 0 and output.is_file():
                    break
            if result is None or result.returncode != 0 or not output.is_file():
                logger.error("TTS failed (piper rc=%s)", result.returncode if result else "none")
                raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Speech synthesis failed")
            audio = output.read_bytes()
    except subprocess.TimeoutExpired as exc:
        logger.error("TTS timed out")
        raise HTTPException(status.HTTP_504_GATEWAY_TIMEOUT, detail="Speech synthesis timed out") from exc
    finally:
        _voice_lock.release()

    return Response(content=audio, media_type="audio/wav")
