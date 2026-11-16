"""
Jarvis Core API.
 
Run from the ``jarvis-core`` directory:
 
    uvicorn app.main:app --host 127.0.0.1 --port 8000
 
Endpoints:
    GET  /health           Liveness probe for Docker/nginx. The only unauthenticated route.
    POST /evaluate-tender  Run the deterministic mandatory-gate engine on a
                           tender whose requirements were assessed by agents.
    POST /chat             Start a chat job for the CrewAI chat crew; returns a job id (202).
    GET  /jobs/{job_id}    Poll a chat or pitch job: running | done (with reply) | error.
    GET  /global-tenders   Global tender feed (SAMPLE DATA for now, ``mode="mock"``). Also served
                           as /api/global-tenders, see the note on that route.
    POST /global-tenders/{tender_id}/pitch
                           Start a pitch job (Global Matchmaker + Bid Writer); returns a job id
                           (202). The finished job's ``reply`` is a JSON document.
    POST /api/voice/transcribe
                           Proxy a recorded clip to the voice container's Whisper STT; returns
                           ``{"text": "..."}``.
    POST /api/voice/synthesize
                           Proxy text to the voice container's Piper TTS; returns audio/wav bytes.
    POST /api/host/type    Type text on the Windows laptop (via the native host bridge).
    POST /api/host/hotkey  Press a key combination on the laptop.
    POST /api/host/open_app
                           Launch an application on the laptop.
    GET  /api/host/screenshot
                           Capture the laptop screen; returns base64 PNG JSON.
    GET  /api/host/stats   CPU, RAM and battery readings from the laptop.
    POST /api/host/whatsapp
                           Send a WhatsApp message from the laptop (WhatsApp Web / pywhatkit).
    GET  /api/briefing/latest
                           Latest stored morning briefing (``available=false`` until the first run).
    POST /api/briefing/generate
                           Generate a briefing now; returns a job id (202). The scheduler runs the
                           same job daily at 08:00 (``BRIEFING_*`` env vars).
 
Every route except /health requires ``Authorization: Bearer <core_api_token>``. Protected
routes are registered on the ``protected`` router, so new endpoints are secured by default.
The interactive docs (/docs, /redoc, /openapi.json) are disabled: they would publish the API
surface without authentication.
"""
 
from __future__ import annotations
 
import hmac
import json
import logging
import os
import threading
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, FastAPI, File, HTTPException, UploadFile, status
from fastapi import Path as PathParam
from fastapi.responses import Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import Field, field_validator
 
from .crew_factory import (
    MAX_REPLY_CHARS,
    CrewBusyError,
    CrewError,
    ProfileNotReadyError,
    run_crew,
    run_pitch_crew,
)
from .gate_engine import evaluate_mandatory_gates_detailed
from .global_tenders import (
    MOCK_NOTICE,
    TENDER_ID_PATTERN,
    GlobalTender,
    GlobalTenderList,
    PitchRequest,
    get_tender,
    list_tenders,
)
from .jobs import Job, JobsBusyError, JobStore
from .schemas import (
    JOB_ID_PATTERN,
    ChatJobResponse,
    ChatRequest,
    JobState,
    OpportunityAssessment,
    StrictModel,
    TenderEvaluationRequest,
)

APP_VERSION = "0.1.0"

# Cloud deployment (Railway): there is no Windows laptop and no host bridge, so the
# /api/host/* routes are not registered at all and the agent loses the host tools.
IS_CLOUD = os.environ.get("IS_CLOUD", "false").strip().lower() == "true"

# Voice service (compose service ``voice``; backend network only). The proxy keeps the
# browser from needing a second token and gives the UI one consistent API surface.
VOICE_URL = os.environ.get("VOICE_URL", "http://voice:8000").rstrip("/")
VOICE_TIMEOUT_S = 120.0
MAX_AUDIO_BYTES = 25 * 1024 * 1024
MAX_SPEECH_CHARS = 4_000
 
logger = logging.getLogger("jarvis.core")
 
# Secret file name under SECRETS_DIR (not a secret value).
API_TOKEN_SECRET = "core_api_token"  # noqa: S105
 
_bearer = HTTPBearer(auto_error=False)
 
 
def _secrets_dir() -> Path:
    return Path(os.environ.get("SECRETS_DIR", "/run/secrets"))
 
 
def _load_api_token() -> str | None:
    """Read the API token on each call so a rotated secret takes effect without a restart.

    Local Docker mounts ``/run/secrets/core_api_token``. On a cloud platform (Railway) there
    are no secret files, so ``CORE_API_TOKEN`` from the environment is the fallback. The file
    wins when both exist.
    """
    try:
        token = (_secrets_dir() / API_TOKEN_SECRET).read_text(encoding="utf-8-sig").strip()
    except OSError:
        token = ""
    return token or (os.environ.get("CORE_API_TOKEN") or "").strip() or None
 
 
def require_api_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> None:
    """Reject requests without a valid ``Authorization: Bearer <core_api_token>`` header."""
    expected = _load_api_token()
    if expected is None:
        # Fail closed: a missing secret must never mean "no auth".
        logger.error("core_api_token secret is missing or empty; refusing authenticated calls")
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="Authentication not configured")
    supplied = credentials.credentials if credentials and credentials.scheme.lower() == "bearer" else ""
    # Constant-time compare so response timing doesn't leak how much of the token matched.
    if not hmac.compare_digest(supplied.encode("utf-8"), expected.encode("utf-8")):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API token",
            headers={"WWW-Authenticate": "Bearer"},
        )
 
# --- Morning briefing ---------------------------------------------------------------------------
# APScheduler runs one job a day. The briefing is produced by the same chat crew as everything
# else (run_crew), stored on the /data volume and served to the dashboard. The requested prompt
# is kept verbatim; a grounding block is appended because a small local model will otherwise
# invent an inbox. Core has no email or approvals connector, and saying so is the honest answer.
BRIEFING_SCHEDULER_ENABLED = os.environ.get(
    "BRIEFING_SCHEDULER_ENABLED", "true"
).strip().lower() not in {"0", "false", "no", "off"}
BRIEFING_TIMEZONE = os.environ.get("BRIEFING_TIMEZONE", "UTC").strip() or "UTC"
BRIEFING_HOUR = max(0, min(int(os.environ.get("BRIEFING_HOUR", "8")), 23))
BRIEFING_MINUTE = max(0, min(int(os.environ.get("BRIEFING_MINUTE", "0")), 59))
BRIEFING_STORE_PATH = Path(os.environ.get("BRIEFING_STORE_PATH", "/data/briefing.json"))
BRIEFING_PROMPT = (
    "Generate a concise morning briefing for the CEO: summarize unread emails, "
    "new tenders, and pending approvals."
)
BRIEFING_NOTICE = (
    "No briefing has been generated yet. The scheduler runs every day at "
    f"{BRIEFING_HOUR:02d}:{BRIEFING_MINUTE:02d} {BRIEFING_TIMEZONE}."
)
MAX_BRIEFING_CHARS = 12_000

_briefing_lock = threading.Lock()
_briefing_cache: dict[str, Any] | None = None
_briefing_loaded = False
_briefing_scheduler: Any = None


class BriefingResponse(StrictModel):
    """The latest stored briefing. ``available=false`` until the first run has finished."""

    available: bool
    generated_at: str | None = None
    source: str | None = None
    text: str = ""
    tender_count: int = 0
    tender_mode: str = "none"
    notice: str = ""
    scheduled: bool = False
    next_run_at: str | None = None


def _briefing_context() -> str:
    """Grounding facts appended to the requested prompt."""
    tenders = list_tenders()
    lines = [
        "",
        "---",
        "GROUNDING CONTEXT (use only this; do not go beyond it):",
        f"Global tender feed: mode=mock (sample data, not live notices), {len(tenders)} item(s).",
    ]
    for tender in tenders[:8]:
        deadline = tender.submission_deadline.isoformat(timespec="minutes")
        lines.append(f"- {tender.id} | {tender.title} | {tender.country} | deadline {deadline}")
    lines += [
        "Connected data sources: the global tender feed above and the local operations "
        "database (you may call `finance_summary` for recorded expenses and invoices).",
        "NOT connected: the CEO's email inbox and any approvals system. You cannot read unread "
        "emails or pending approvals. For those two sections, say plainly that no data source is "
        "connected and that the CEO must check them manually. Never invent emails, senders, "
        "counts, approval items or deadlines.",
        "Format: three short sections (Tenders, Email, Approvals) plus one next action. "
        "Under 250 words.",
    ]
    return "\n".join(lines)


def _briefing_store_load() -> dict[str, Any] | None:
    """Read the stored briefing once, then serve it from memory (and after each new run)."""
    global _briefing_cache, _briefing_loaded
    with _briefing_lock:
        if not _briefing_loaded:
            try:
                raw = BRIEFING_STORE_PATH.read_text(encoding="utf-8")
                payload = json.loads(raw)
                _briefing_cache = payload if isinstance(payload, dict) else None
            except (OSError, ValueError):
                _briefing_cache = None
            _briefing_loaded = True
        return _briefing_cache


def _briefing_store_save(payload: dict[str, Any]) -> None:
    """Persist atomically: a crash mid-write must never leave a truncated briefing."""
    global _briefing_cache
    text = json.dumps(payload, ensure_ascii=False)
    try:
        BRIEFING_STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = BRIEFING_STORE_PATH.with_name(BRIEFING_STORE_PATH.name + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(BRIEFING_STORE_PATH)
        with _briefing_lock:
            _briefing_cache = payload
    except OSError as exc:
        # The in-memory copy still serves the UI for this process lifetime.
        logger.error("Could not persist the briefing: %s", exc.__class__.__name__)
        with _briefing_lock:
            _briefing_cache = payload


def _generate_briefing_job(source: str) -> str:
    """Body of a briefing job: run the crew, persist the text, index it in briefing memory."""
    started = datetime.now(UTC)
    tenders = list_tenders()
    reply = run_crew(BRIEFING_PROMPT + "\n" + _briefing_context()).strip()
    if not reply:
        raise CrewError("The briefing was empty")
    payload = {
        "generated_at": started.isoformat(timespec="seconds"),
        "source": source,
        "text": reply[:MAX_BRIEFING_CHARS],
        "tender_count": len(tenders),
        "tender_mode": "mock",
    }
    _briefing_store_save(payload)
    try:
        from . import rag_setup

        rag_setup.remember(
            "briefing_memory",
            [reply[:1800]],
            metadatas=[{"source": source, "generated_at": payload["generated_at"]}],
            source=source,
        )
    except Exception as exc:  # noqa: BLE001 - memory is best-effort, never fatal
        logger.warning("Briefing memory write skipped: %s", exc.__class__.__name__)
    logger.info("Briefing generated (source=%s, %d chars)", source, len(payload["text"]))
    return payload["text"]


def _scheduled_briefing() -> None:
    """APScheduler entry point: hand the briefing to the shared job store."""
    if not BRIEFING_SCHEDULER_ENABLED:
        return
    try:
        job = jobs.submit(lambda: _generate_briefing_job("scheduled"))
    except JobsBusyError:
        logger.warning("Scheduled briefing skipped: another job is running")
        return
    except Exception as exc:  # noqa: BLE001 - never let the scheduler thread die
        logger.error("Scheduled briefing could not start: %s", exc.__class__.__name__)
        return
    logger.info("Scheduled briefing job %s started", job.id)


def _scheduler_status() -> tuple[bool, str | None]:
    """(running, next run ISO) for the briefing job; (False, None) when disabled."""
    scheduler = _briefing_scheduler
    if scheduler is None or not getattr(scheduler, "running", False):
        return False, None
    job = scheduler.get_job("morning-briefing")
    next_run = getattr(job, "next_run_time", None)
    return True, next_run.isoformat(timespec="seconds") if next_run else None


def _start_briefing_scheduler() -> Any:
    """Start APScheduler, or return None when disabled/unavailable (core keeps serving)."""
    global _briefing_scheduler
    if not BRIEFING_SCHEDULER_ENABLED:
        logger.info("Morning briefing scheduler disabled (BRIEFING_SCHEDULER_ENABLED)")
        return None
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger

        scheduler = BackgroundScheduler(timezone=BRIEFING_TIMEZONE, daemon=True)
        scheduler.add_job(
            _scheduled_briefing,
            CronTrigger(hour=BRIEFING_HOUR, minute=BRIEFING_MINUTE,
                        timezone=BRIEFING_TIMEZONE),
            id="morning-briefing",
            replace_existing=True,
            coalesce=True,
            misfire_grace_time=3600,
            max_instances=1,
        )
        scheduler.start()
    except Exception as exc:  # noqa: BLE001 - a bad timezone must not stop the API
        logger.error("Briefing scheduler not started: %s", exc.__class__.__name__)
        return None
    _briefing_scheduler = scheduler
    logger.info("Morning briefing scheduled for %02d:%02d %s",
                BRIEFING_HOUR, BRIEFING_MINUTE, BRIEFING_TIMEZONE)
    return scheduler


@asynccontextmanager
async def lifespan(_: FastAPI):
    global _briefing_scheduler
    scheduler = _start_briefing_scheduler()
    try:
        yield
    finally:
        if scheduler is not None:
            scheduler.shutdown(wait=False)
        _briefing_scheduler = None


app = FastAPI(
    title="Jarvis Core API",
    version=APP_VERSION,
    description="Tender evaluation service for the Jarvis multi-agent system.",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=lifespan,
)
 
 
@app.get("/health", tags=["ops"])
def health() -> dict[str, str]:
    """Lightweight liveness check. Deliberately touches no dependencies so it
    stays fast and only reports whether the process is serving requests."""
    return {
        "status": "ok",
        "service": "jarvis-core",
        "version": APP_VERSION,
        "timestamp": datetime.now(UTC).isoformat(),
    }
 
 
# All routes on this router require the API token. Only /health is registered on `app`.
protected = APIRouter(dependencies=[Depends(require_api_token)])
 
 
@protected.post(
    "/evaluate-tender",
    response_model=OpportunityAssessment,
    status_code=status.HTTP_200_OK,
    tags=["evaluation"],
)
def evaluate_tender(payload: TenderEvaluationRequest) -> OpportunityAssessment:
    """Apply the mandatory gates to a tender and return the full assessment.
 
    Input validation (types, sizes, unique requirement IDs, timezone-aware
    deadline) is enforced by the Pydantic schema; invalid payloads get a 422
    automatically before this function runs.
    """
    evaluated_at = datetime.now(UTC)
    try:
        # Use one timestamp for both the deadline check and the record, so
        # the stored assessment is consistent with the decision it contains.
        result = evaluate_mandatory_gates_detailed(
            payload.requirements,
            submission_deadline=payload.submission_deadline,
            now=evaluated_at,
        )
    except ValueError as exc:
        # Engine-level validation errors are client errors, not server faults.
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
 
    logger.info(
        "Evaluated opportunity %s -> %s", payload.opportunity_id, result.decision.value
    )
 
    return OpportunityAssessment(
        **payload.model_dump(),
        decision_status=result.decision,
        decision_reasons=result.reasons,
        evaluated_at=evaluated_at,
    )
 
 
def _describe_job_error(exc: Exception) -> str:
    """User-facing job error. Never includes exception text (may hold prompts or URLs)."""
    if isinstance(exc, CrewBusyError):
        # Only when a timed-out run is still holding the model.
        return "Jarvis is still finishing an earlier request. Please try again shortly."
    if isinstance(exc, ProfileNotReadyError):
        return ("The CEO profile is not indexed yet. Check that boss_cv.txt is in app/knowledge "
                "and that the embedding model is pulled in Ollama, then try again.")
    return "The AI model failed to respond. Please try again."
 
 
# Process-wide: one chat job at a time, because Ollama serves one request at a time on CPU.
jobs = JobStore(max_running=1, timeout_s=900.0, describe_error=_describe_job_error)
 
 
def _job_response(job: Job) -> ChatJobResponse:
    return ChatJobResponse(
        job_id=job.id, status=JobState(job.status.value), reply=job.reply, error=job.error
    )
 
 
@protected.post(
    "/chat",
    response_model=ChatJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["chat"],
)
def chat(payload: ChatRequest) -> ChatJobResponse:
    """Start answering a dashboard chat message in the background; poll ``GET /jobs/{id}``.
 
    CPU inference with tool use can take several minutes, so the reply is not awaited here.
    Only one chat job runs at a time; a second one gets 503 straight away.
    Each message is answered on its own; conversation history is not sent to the model yet.
    Message text is never logged; only ids, sizes and timings.
    """
    message = payload.message
    try:
        job = jobs.submit(lambda: run_crew(message))
    except JobsBusyError as exc:
        logger.info("Chat rejected, a job is running (conversation=%s)", payload.conversation_id)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Jarvis is busy with another request. Try again shortly.",
            headers={"Retry-After": "30"},
        ) from exc
    logger.info("Chat job %s started (conversation=%s, chars=%d)",
                job.id, payload.conversation_id, len(message))
    return _job_response(job)
 
 
@protected.get("/jobs/{job_id}", response_model=ChatJobResponse, tags=["chat"])
def get_job(job_id: str = PathParam(pattern=JOB_ID_PATTERN)) -> ChatJobResponse:
    """Return a chat job's status, and its reply once done.
 
    404 if the id is unknown: never issued, expired (1 h after finishing), or lost when core
    restarted (jobs are kept in memory only).
    """
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Job not found")
    return _job_response(job)


# --- Briefing API --------------------------------------------------------------------------------
@protected.get("/api/briefing/latest", response_model=BriefingResponse, tags=["briefing"])
def briefing_latest() -> BriefingResponse:
    """Return the latest stored morning briefing.

    200 with ``available=false`` before the first run (so the widget can explain itself
    instead of showing an error). The text is the crew's own output; the UI renders it as
    plain text.
    """
    payload = _briefing_store_load()
    scheduled, next_run_at = _scheduler_status()
    if not payload:
        return BriefingResponse(
            available=False, notice=BRIEFING_NOTICE,
            scheduled=scheduled, next_run_at=next_run_at,
        )
    text = payload.get("text")
    if not isinstance(text, str) or not text.strip():
        return BriefingResponse(
            available=False, notice=BRIEFING_NOTICE,
            scheduled=scheduled, next_run_at=next_run_at,
        )
    try:
        tender_count = int(payload.get("tender_count") or 0)
    except (TypeError, ValueError):
        tender_count = 0
    return BriefingResponse(
        available=True,
        generated_at=str(payload.get("generated_at") or "") or None,
        source=str(payload.get("source") or "") or None,
        text=text[:MAX_BRIEFING_CHARS],
        tender_count=tender_count,
        tender_mode=str(payload.get("tender_mode") or "mock"),
        scheduled=scheduled,
        next_run_at=next_run_at,
    )


@protected.post(
    "/api/briefing/generate",
    response_model=ChatJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["briefing"],
)
def generate_briefing() -> ChatJobResponse:
    """Generate a briefing now. Returns 202 with a job id; poll ``GET /jobs/{id}``.

    The job's ``reply`` is the briefing text, and ``GET /api/briefing/latest`` returns it
    once stored. Shares the single job slot with chat and pitches (503 while busy).
    """
    try:
        job = jobs.submit(lambda: _generate_briefing_job("manual"))
    except JobsBusyError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Jarvis is busy with another request. Try again shortly.",
            headers={"Retry-After": "30"},
        ) from exc
    logger.info("Briefing job %s started", job.id)
    return _job_response(job)


# --- Voice proxy ---------------------------------------------------------------------------------
class VoiceSynthesizeRequest(StrictModel):
    """Text to speak. Bounded because TTS on CPU is slow and replies are capped anyway."""

    text: str = Field(min_length=1, max_length=MAX_SPEECH_CHARS)


def _voice_post(path: str, **kwargs: Any) -> httpx.Response:
    """POST to the voice container, bypassing the egress proxy (voice is internal-only).

    ``trust_env=False`` matters here: core has HTTP(S)_PROXY set for its scrapers, and a
    request to ``voice:8000`` must never be handed to Squid.
    """
    return httpx.post(
        f"{VOICE_URL}{path}",
        timeout=VOICE_TIMEOUT_S,
        trust_env=False,
        **kwargs,
    )


@protected.post("/api/voice/transcribe", tags=["voice"])
def transcribe_audio(file: Annotated[UploadFile, File()]) -> dict[str, str]:
    """Proxy a recorded clip to ``voice:8000/stt`` and return ``{"text": "..."}``.

    The clip is held in memory only. Nothing from the audio or the transcript is logged.
    """
    audio = file.file.read()
    if not audio:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Empty audio upload")
    if len(audio) > MAX_AUDIO_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Audio clip is too large"
        )
    try:
        response = _voice_post(
            "/stt",
            files={
                "file": (
                    file.filename or "speech.wav",
                    audio,
                    file.content_type or "audio/wav",
                )
            },
        )
    except httpx.TimeoutException as exc:
        raise HTTPException(
            status.HTTP_504_GATEWAY_TIMEOUT, detail="Speech-to-text timed out"
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, detail="Voice service is unavailable"
        ) from exc

    if response.status_code >= 400:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            detail="Voice service could not transcribe the clip",
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, detail="Voice service returned an invalid response"
        ) from exc
    text = payload.get("text") if isinstance(payload, dict) else None
    if not isinstance(text, str):
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, detail="Voice service returned an invalid response"
        )
    return {"text": text.strip()[:MAX_SPEECH_CHARS]}


@protected.post("/api/voice/synthesize", tags=["voice"])
def synthesize_speech(payload: VoiceSynthesizeRequest) -> Response:
    """Proxy text to ``voice:8000/tts`` and stream the WAV bytes back to the dashboard."""
    try:
        response = _voice_post("/tts", json={"text": payload.text})
    except httpx.TimeoutException as exc:
        raise HTTPException(
            status.HTTP_504_GATEWAY_TIMEOUT, detail="Speech synthesis timed out"
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, detail="Voice service is unavailable"
        ) from exc

    if response.status_code >= 400 or not response.content:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, detail="Voice service could not synthesize speech"
        )
    return Response(content=response.content, media_type="audio/wav")


# --- Host control proxy (Windows bridge) ---------------------------------------------------------
# The bridge (host_bridge.py) runs natively on the laptop: a container cannot drive the desktop.
# Docker Desktop publishes the host as host.docker.internal, and compose attaches core to a
# non-internal network (hostlink) so this route exists at all.
HOST_BRIDGE_URL = os.environ.get(
    "HOST_BRIDGE_URL", "http://host.docker.internal:9090"
).rstrip("/")
HOST_BRIDGE_TIMEOUT_S = float(os.environ.get("HOST_BRIDGE_TIMEOUT_SECONDS", "30"))
# Compose mounts the secret as /run/secrets/host_token; a direct run may use the .txt file.
HOST_TOKEN_FILENAMES = ("host_token", "host_token.txt")
HOTKEY_KEY_PATTERN = r"^[A-Za-z0-9_]{1,16}$"
# Letters, digits, spaces and the characters a Windows app name or path can contain.
APP_NAME_PATTERN = r"^[A-Za-z0-9 ._\-:/\\]{1,260}$"
MAX_HOST_TYPE_CHARS = 4_000
MAX_HOST_HOTKEY_KEYS = 5


class HostTypeRequest(StrictModel):
    """Text to type into the focused window on the laptop."""

    text: str = Field(min_length=1, max_length=MAX_HOST_TYPE_CHARS)


class HostHotkeyRequest(StrictModel):
    """A key combination such as ``ctrl+c`` or ``win+d``."""

    keys: list[Annotated[str, Field(pattern=HOTKEY_KEY_PATTERN)]] = Field(
        min_length=1, max_length=MAX_HOST_HOTKEY_KEYS
    )


class HostOpenAppRequest(StrictModel):
    """Application name (``code``, ``chrome``) or an absolute path to launch."""

    app_name: str = Field(min_length=1, max_length=260, pattern=APP_NAME_PATTERN)


class HostWhatsAppRequest(StrictModel):
    """A WhatsApp message to send from the laptop. Phone includes the country code."""

    phone: str = Field(min_length=8, max_length=32)
    message: str = Field(min_length=1, max_length=1000)

    @field_validator("phone")
    @classmethod
    def _normalise_phone(cls, phone: str) -> str:
        raw = phone.strip()
        digits = "".join(ch for ch in raw if ch.isdigit())
        if raw.startswith("00"):
            digits = digits[2:]
        if not 8 <= len(digits) <= 15:
            raise ValueError("phone must have 8-15 digits including the country code")
        return f"+{digits}"

    @field_validator("message")
    @classmethod
    def _printable(cls, message: str) -> str:
        if not message.strip():
            raise ValueError("message must not be blank")
        if any((ord(ch) < 32 and ch not in "\n\t") or ord(ch) == 127 for ch in message):
            raise ValueError("message contains unsupported control characters")
        return message


def _load_host_token() -> str | None:
    """Read the bridge token on each call so a rotated secret needs no restart.

    Compose mounts the secret as ``/run/secrets/host_token`` (the secret name); running the
    stack without compose may leave the source file name, ``host_token.txt``. Accept both.
    ``HOST_TOKEN`` from the environment is the last fallback (cloud deployments have no secret
    files, although host routes are disabled there).
    """
    for filename in HOST_TOKEN_FILENAMES:
        try:
            token = (_secrets_dir() / filename).read_text(encoding="utf-8-sig").strip()
        except OSError:
            continue
        if token:
            return token
    return (os.environ.get("HOST_TOKEN") or "").strip() or None


def _bridge_detail(response: httpx.Response) -> str | None:
    """Extract the bridge's own message (our code generated it) without trusting anything else."""
    try:
        body = response.json()
    except ValueError:
        return None
    detail = body.get("detail") if isinstance(body, dict) else None
    return detail[:300] if isinstance(detail, str) and detail else None


def _host_request(
    method: str,
    path: str,
    timeout: float | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Call the Windows bridge and return its JSON body, mapping failures to clear errors.

    ``trust_env=False`` matters: core sets HTTP(S)_PROXY for its scrapers, and a request to
    the host must never be handed to Squid.
    """
    token = _load_host_token()
    if token is None:
        # Fail closed: without the shared token the bridge would reject us anyway.
        logger.error("host_token secret is missing; refusing host control calls")
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Host control is not configured (host_token is missing).",
        )
    try:
        response = httpx.request(
            method,
            f"{HOST_BRIDGE_URL}{path}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=timeout if timeout is not None else HOST_BRIDGE_TIMEOUT_S,
            trust_env=False,
            **kwargs,
        )
    except httpx.TimeoutException as exc:
        raise HTTPException(
            status.HTTP_504_GATEWAY_TIMEOUT, detail="The laptop did not answer in time."
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            detail="Host bridge is unreachable. Is host_bridge.py running on the laptop?",
        ) from exc

    if response.status_code in (401, 403):
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, detail="The host bridge rejected the core token."
        )
    if response.status_code >= 500:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, detail="The host bridge failed to complete the action."
        )
    if response.status_code >= 400:
        # Keep the bridge's own explanation (e.g. "Application 'x' was not found") when present.
        detail = _bridge_detail(response) or "The host bridge rejected the request."
        mapped = {
            404: status.HTTP_404_NOT_FOUND,
            409: status.HTTP_409_CONFLICT,
        }.get(response.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)
        raise HTTPException(mapped, detail=detail)

    try:
        payload = response.json()
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, detail="The host bridge returned an invalid response."
        ) from exc
    if not isinstance(payload, dict):
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, detail="The host bridge returned an invalid response."
        )
    return payload


# Host routes live on their own router so cloud mode (IS_CLOUD=true) can omit them entirely
# instead of merely failing at call time. They are still bearer-protected when mounted.
host_protected = APIRouter(dependencies=[Depends(require_api_token)])


@host_protected.post("/api/host/whatsapp", tags=["host"])
def host_whatsapp(payload: HostWhatsAppRequest) -> dict[str, Any]:
    """Send a WhatsApp message from the laptop through the host bridge.

    ``dispatched=true`` means pywhatkit submitted the text to WhatsApp Web; it is not a
    delivery receipt. When pywhatkit is unavailable the bridge answers ``dispatched=false``
    with the reason, so the UI can show the truth. The message body is never logged.
    """
    logger.info("Host WhatsApp request (%d chars)", len(payload.message))
    return _host_request(
        "POST",
        "/action/whatsapp",
        json={"phone": payload.phone, "message": payload.message},
        timeout=max(HOST_BRIDGE_TIMEOUT_S, 90.0),
    )


@host_protected.post("/api/host/type", tags=["host"])
def host_type(payload: HostTypeRequest) -> dict[str, Any]:
    """Type text into whichever window has focus on the laptop. The text is never logged."""
    logger.info("Host type request (%d chars)", len(payload.text))
    return _host_request("POST", "/action/type", json={"text": payload.text})


@host_protected.post("/api/host/hotkey", tags=["host"])
def host_hotkey(payload: HostHotkeyRequest) -> dict[str, Any]:
    """Press a key combination on the laptop, e.g. ``{"keys": ["win", "d"]}``."""
    logger.info("Host hotkey request (%d keys)", len(payload.keys))
    return _host_request("POST", "/action/hotkey", json={"keys": payload.keys})


@host_protected.post("/api/host/open_app", tags=["host"])
def host_open_app(payload: HostOpenAppRequest) -> dict[str, Any]:
    """Launch an application on the laptop, e.g. ``{"app_name": "code"}``."""
    logger.info("Host open_app request (%s)", payload.app_name)
    return _host_request("POST", "/action/open_app", json={"app_name": payload.app_name})


@host_protected.get("/api/host/screenshot", tags=["host"])
def host_screenshot() -> dict[str, Any]:
    """Capture the laptop's main monitor. Returns ``image_base64`` (PNG) plus its size."""
    return _host_request("GET", "/screenshot", params={"monitor": 1})


@host_protected.get("/api/host/stats", tags=["host"])
def host_stats() -> dict[str, Any]:
    """CPU, RAM and battery readings from the laptop."""
    return _host_request("GET", "/system_stats")


# Mounted only for local runs: cloud has no laptop and no host bridge (see IS_CLOUD).
if not IS_CLOUD:
    protected.include_router(host_protected)
else:
    logger.info("Cloud mode: /api/host/* routes are disabled")


# --- Global tenders + VIP pitch ------------------------------------------------------------------
# Pitches drafted since core started, keyed by tender id. A pitch takes minutes on CPU, so a
# second click returns the stored one (marked "cached") unless the caller asks to regenerate.
# In memory only, like jobs: lost on restart. Holds at most one entry per listed tender.
_pitch_cache: dict[str, dict[str, Any]] = {}
_pitch_cache_lock = threading.Lock()
 
 
def _encode_pitch(result: dict[str, Any], *, cached: bool) -> str:
    """Serialise a pitch result for the job's ``reply`` string.
 
    The job store carries one string per job, so the structured result travels as JSON and
    the UI parses it. Kept under ``ChatJobResponse.reply``'s limit: the evidence excerpts are
    the first thing dropped if it would not fit.
    """
    payload = {**result, "cached": cached}
    text = json.dumps(payload, ensure_ascii=False)
    if len(text) > MAX_REPLY_CHARS:
        text = json.dumps({**payload, "evidence": []}, ensure_ascii=False)
    return text
 
 
def _pitch_job(tender: GlobalTender, regenerate: bool) -> str:
    """Body of a pitch job: reuse the stored pitch or run the matchmaker + pitch crew."""
    if not regenerate:
        with _pitch_cache_lock:
            stored = _pitch_cache.get(tender.id)
        if stored is not None:
            return _encode_pitch(stored, cached=True)
    result = run_pitch_crew(tender.brief())
    result["tender_id"] = tender.id
    result["generated_at"] = datetime.now(UTC).isoformat(timespec="seconds")
    with _pitch_cache_lock:
        _pitch_cache[tender.id] = result
    return _encode_pitch(result, cached=False)
 
 
# Two paths, one handler. Core's own convention is un-prefixed routes (/chat, /jobs): the UI
# calls core directly, and the edge exposes core under /api/. The /api/global-tenders alias
# makes the documented URL work whether or not nginx strips the /api/ prefix.
@protected.get("/global-tenders", response_model=GlobalTenderList, tags=["tenders"])
@protected.get("/api/global-tenders", response_model=GlobalTenderList, tags=["tenders"])
def global_tenders() -> GlobalTenderList:
    """List global AI / IoT / cloud tenders. SAMPLE DATA until the live connectors exist;
    the response says so (``mode="mock"``) and every item has ``is_mock=true``."""
    return GlobalTenderList(items=list_tenders(), mode="mock", notice=MOCK_NOTICE)
 
 
@protected.post(
    "/global-tenders/{tender_id}/pitch",
    response_model=ChatJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["tenders"],
)
def draft_pitch(
    tender_id: str = PathParam(pattern=TENDER_ID_PATTERN),
    payload: PitchRequest | None = None,
) -> ChatJobResponse:
    """Start drafting a VIP pitch for a tender in the background; poll ``GET /jobs/{id}``.
 
    The job's ``reply`` is JSON: matched_project, match_source, match_rationale, pitch,
    warnings, evidence, tender_id, generated_at, cached. Shares the single job slot with
    chat, so it returns 503 while another job runs. A pitch is a draft for human review; it
    is not an eligibility decision (that stays with the gate engine).
    """
    tender = get_tender(tender_id)
    if tender is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Tender not found")
    regenerate = bool(payload and payload.regenerate)
    try:
        job = jobs.submit(lambda: _pitch_job(tender, regenerate))
    except JobsBusyError as exc:
        logger.info("Pitch rejected, a job is running (tender=%s)", tender_id)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Jarvis is busy with another request. Try again shortly.",
            headers={"Retry-After": "30"},
        ) from exc
    logger.info("Pitch job %s started (tender=%s, regenerate=%s)", job.id, tender_id, regenerate)
    return _job_response(job)
 
 
# Register after all protected routes are defined (include_router copies routes at call time).
app.include_router(protected)
