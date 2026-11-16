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
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any
 
import httpx
from fastapi import APIRouter, Depends, FastAPI, File, HTTPException, UploadFile, status
from fastapi import Path as PathParam
from fastapi.responses import Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import Field
 
from .crew_factory import (
    MAX_REPLY_CHARS,
    CrewBusyError,
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
    """Read the API token on each call so a rotated secret takes effect without a restart."""
    try:
        token = (_secrets_dir() / API_TOKEN_SECRET).read_text(encoding="utf-8-sig").strip()
    except OSError:
        return None
    return token or None
 
 
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
 
app = FastAPI(
    title="Jarvis Core API",
    version=APP_VERSION,
    description="Tender evaluation service for the Jarvis multi-agent system.",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
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
