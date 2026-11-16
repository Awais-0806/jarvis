"""
Jarvis CEO Dashboard (Streamlit) - Cinematic DeepSeek & Glassmorphism Edition.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
import pandas as pd
import streamlit as st

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("jarvis.ui")

# --- Configuration ---
SECRETS_DIR = Path(os.environ.get("SECRETS_DIR", "/run/secrets"))
CORE_URL = os.environ.get("CORE_URL", "http://core:8000").rstrip("/")

PASSWORD_SECRET = "ui_password"
TOKEN_SECRET = "core_api_token"

API_TIMEOUT_S = 15.0
CHAT_POLL_S = float(os.environ.get("CHAT_POLL_SECONDS", "3"))
CHAT_MAX_WAIT_S = float(os.environ.get("CHAT_MAX_WAIT_SECONDS", "960"))
VOICE_TIMEOUT_S = float(os.environ.get("VOICE_TIMEOUT_SECONDS", "180"))
APPROVALS_POLL_S = int(os.environ.get("APPROVALS_POLL_SECONDS", "30"))
LEADS_CACHE_S = 300
TENDERS_CACHE_S = 300
SESSION_IDLE_TIMEOUT_S = int(os.environ.get("SESSION_IDLE_TIMEOUT_SECONDS", "1800"))

MAX_LOGIN_FAILURES = 5
LOCKOUT_S = 300
MAX_MESSAGE_CHARS = 4000
MAX_CHAT_HISTORY = 50
MAX_REASON_CHARS = 500

APPROVAL_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
JOB_ID_RE = re.compile(r"^[0-9a-f]{32}$")
TENDER_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

FORMULA_TRIGGERS: tuple[str, ...] = ("=", "+", "-", "@", "\t", "\r")
_MD_SPECIAL_RE = re.compile(r"([\\`*_{}\[\]()#+\-.!|<>~:$])")
REGION_BADGES = {"UK": "blue", "USA": "violet", "EU": "green"}

# --- DeepSeek Glassmorphism & High-Contrast Dark Theme CSS ---
THEME_CSS = """
/* =====================================================================
   1. Hide Streamlit Branding / Chrome
   ===================================================================== */
#MainMenu { visibility: hidden !important; display: none !important; }
header { visibility: hidden !important; display: none !important; }
footer { visibility: hidden !important; display: none !important; }
[data-testid="stHeader"] { display: none !important; visibility: hidden !important; }
[data-testid="stToolbar"] { display: none !important; visibility: hidden !important; }
[data-testid="stDecoration"] { display: none !important; visibility: hidden !important; }
[data-testid="stStatusWidget"] { display: none !important; visibility: hidden !important; }
#manage-app-button { display: none !important; visibility: hidden !important; }

/* =====================================================================
   2. Base Background: Deep Dark Gradient
   ===================================================================== */
html, body, .stApp, [data-testid="stAppViewContainer"], [data-testid="stApp"] {
  background: linear-gradient(135deg, #0A0F1C 0%, #111827 100%) !important;
  background-color: #0A0F1C !important;
  color: #FFFFFF !important;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif !important;
}

[data-testid="stSidebar"] {
  background: #080D1A !important;
  border-right: 1px solid rgba(255, 255, 255, 0.08) !important;
}

[data-testid="stMainBlockContainer"] {
  max-width: 1200px !important;
  padding-top: 1.5rem !important;
  padding-bottom: 3rem !important;
}

/* Custom Scrollbars */
::-webkit-scrollbar {
  width: 8px;
  height: 8px;
}
::-webkit-scrollbar-track {
  background: rgba(10, 15, 28, 0.8);
}
::-webkit-scrollbar-thumb {
  background: rgba(255, 255, 255, 0.15);
  border-radius: 4px;
}
::-webkit-scrollbar-thumb:hover {
  background: rgba(0, 240, 255, 0.5);
}

/* =====================================================================
   3. Fix Invisible Chat Text (Critical Force Dark Glass & White Text)
   ===================================================================== */
[data-testid="stBottom"],
[data-testid="stBottom"] > div,
[data-testid="stBottomBlockContainer"] {
  background: transparent !important;
}

[data-testid="stChatInput"],
.stChatInput {
  background: rgba(15, 23, 42, 0.85) !important;
  backdrop-filter: blur(20px) !important;
  -webkit-backdrop-filter: blur(20px) !important;
  border: 1px solid rgba(0, 240, 255, 0.3) !important;
  border-radius: 16px !important;
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.6), 0 0 15px rgba(0, 240, 255, 0.12) !important;
  padding: 4px 8px !important;
}

[data-testid="stChatInput"]:focus-within,
.stChatInput:focus-within {
  border-color: #00F0FF !important;
  box-shadow: 0 10px 40px rgba(0, 0, 0, 0.8), 0 0 25px rgba(0, 240, 255, 0.35) !important;
}

/* Force dark background and white/cyan text on all nested input layers */
[data-testid="stChatInput"] div,
[data-testid="stChatInput"] [data-baseweb="base-input"],
[data-testid="stChatInput"] [data-baseweb="textarea"],
[data-testid="stChatInput"] textarea,
.stChatInput div,
.stChatInput [data-baseweb="base-input"],
.stChatInput [data-baseweb="textarea"],
.stChatInput textarea,
.stChatInput input,
textarea,
input {
  background-color: rgba(15, 23, 42, 0.8) !important;
  background: rgba(15, 23, 42, 0.8) !important;
  color: #FFFFFF !important;
  -webkit-text-fill-color: #FFFFFF !important;
  caret-color: #64FFDA !important;
}

/* Force placeholder to be clearly visible */
[data-testid="stChatInput"] textarea::placeholder,
.stChatInput textarea::placeholder,
textarea::placeholder,
input::placeholder {
  color: #94A3B8 !important;
  -webkit-text-fill-color: #94A3B8 !important;
  opacity: 1 !important;
}

/* Chat Input Send Button */
[data-testid="stChatInput"] button,
.stChatInput button {
  background: linear-gradient(90deg, #00F0FF, #0055FF) !important;
  color: #000000 !important;
  border-radius: 10px !important;
  border: none !important;
  transition: all 0.25s ease !important;
}

[data-testid="stChatInput"] button:hover,
.stChatInput button:hover {
  box-shadow: 0 0 15px rgba(0, 240, 255, 0.6) !important;
  transform: scale(1.05) !important;
}

[data-testid="stChatInput"] button svg,
.stChatInput button svg {
  fill: #000000 !important;
  color: #000000 !important;
}

/* =====================================================================
   4. Minimalistic Sleek Tabs & Glowing Active Cyan Tab
   ===================================================================== */
[data-testid="stTabs"] {
  border: none !important;
}

[data-testid="stTabs"] [data-baseweb="tab-list"],
[data-testid="stTabs"] [role="tablist"] {
  background: transparent !important;
  border-bottom: 1px solid rgba(255, 255, 255, 0.1) !important;
  gap: 0.5rem !important;
  padding-bottom: 0.5rem !important;
}

[data-testid="stTabs"] [data-baseweb="tab"],
[data-testid="stTabs"] [role="tab"] {
  background: rgba(255, 255, 255, 0.02) !important;
  border: 1px solid rgba(255, 255, 255, 0.06) !important;
  border-radius: 10px !important;
  padding: 0.6rem 1.4rem !important;
  color: #94A3B8 !important;
  font-weight: 500 !important;
  font-size: 0.95rem !important;
  transition: all 0.25s ease !important;
}

[data-testid="stTabs"] [data-baseweb="tab"]:hover,
[data-testid="stTabs"] [role="tab"]:hover {
  background: rgba(255, 255, 255, 0.06) !important;
  color: #FFFFFF !important;
  border-color: rgba(0, 240, 255, 0.3) !important;
}

/* Glowing cyan active tab as specified */
[data-testid="stTabs"] [aria-selected="true"],
[data-testid="stTabs"] [data-baseweb="tab"][aria-selected="true"],
[data-testid="stTabs"] button[role="tab"][aria-selected="true"] {
  background: rgba(0, 240, 255, 0.1) !important;
  color: #00F0FF !important;
  border-bottom: 2px solid #00F0FF !important;
  border-color: rgba(0, 240, 255, 0.4) !important;
  font-weight: 600 !important;
  box-shadow: 0 0 15px rgba(0, 240, 255, 0.3) !important;
}

[data-testid="stTabs"] [data-baseweb="tab-highlight"],
[data-testid="stTabs"] [data-baseweb="tab-border"] {
  display: none !important;
  background-color: transparent !important;
}

/* =====================================================================
   5. Glassmorphic Tender Cards & Pitch Result
   ===================================================================== */
[class*="st-key-tender_"] {
  background: rgba(255, 255, 255, 0.03) !important;
  backdrop-filter: blur(20px) !important;
  -webkit-backdrop-filter: blur(20px) !important;
  border: 1px solid rgba(255, 255, 255, 0.1) !important;
  border-radius: 16px !important;
  padding: 1.75rem !important;
  margin-bottom: 1.75rem !important;
  box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.45) !important;
  transition: transform 0.3s ease, border-color 0.3s ease, box-shadow 0.3s ease !important;
}

[class*="st-key-tender_"]:hover {
  transform: translateY(-4px) !important;
  border-color: rgba(0, 240, 255, 0.5) !important;
  box-shadow: 0 16px 45px rgba(0, 0, 0, 0.6), 0 0 25px rgba(0, 240, 255, 0.25) !important;
}

[class*="st-key-tender_"] [data-testid="stMarkdownContainer"] strong {
  font-size: 1.25rem !important;
  color: #FFFFFF !important;
}

/* Pitch Result Box (DeepSeek Glass Card) */
[class*="st-key-pitchbox_"]:has([data-testid="stMarkdownContainer"]),
[class*="st-key-pitchbox_"] {
  background: rgba(10, 15, 28, 0.85) !important;
  backdrop-filter: blur(20px) !important;
  -webkit-backdrop-filter: blur(20px) !important;
  border: 1px solid rgba(0, 240, 255, 0.25) !important;
  border-left: 4px solid #00F0FF !important;
  border-radius: 14px !important;
  padding: 1.5rem !important;
  margin-top: 1rem !important;
  box-shadow: inset 0 0 25px rgba(0, 0, 0, 0.7), 0 8px 30px rgba(0, 0, 0, 0.4) !important;
}

/* Visible Pitch Box Text & Evidence Expander Text (Fix for Dark Grey on Dark) */
[class*="st-key-pitchbox_"] p,
[class*="st-key-pitchbox_"] span,
[class*="st-key-pitchbox_"] [data-testid="stText"],
[class*="st-key-pitchbox_"] pre,
[class*="st-key-pitchbox_"] code,
[data-testid="stExpander"] p,
[data-testid="stExpander"] span,
[data-testid="stExpander"] [data-testid="stText"],
[data-testid="stExpander"] pre,
[data-testid="stExpander"] code,
[data-testid="stCaptionContainer"] {
  color: #E2E8F0 !important;
  -webkit-text-fill-color: #E2E8F0 !important;
}

[class*="st-key-pitchbox_"] [data-testid="stText"] pre,
[data-testid="stExpander"] [data-testid="stText"] pre {
  color: #E2E8F0 !important;
  -webkit-text-fill-color: #E2E8F0 !important;
  background: rgba(255, 255, 255, 0.04) !important;
  border: 1px solid rgba(255, 255, 255, 0.08) !important;
  border-radius: 8px !important;
  padding: 10px !important;
  font-family: inherit !important;
  white-space: pre-wrap !important;
  word-break: break-word !important;
}

[class*="st-key-pitchbox_"] strong {
  color: #00F0FF !important;
  -webkit-text-fill-color: #00F0FF !important;
}

/* =====================================================================
   6. Primary "Draft VIP Pitch" DeepSeek Gradient Button
   ===================================================================== */
[class*="st-key-pitch_"] button,
[class*="st-key-repitch_"] button,
button[kind="primary"] {
  background: linear-gradient(90deg, #00F0FF, #0055FF) !important;
  color: #000000 !important;
  font-weight: bold !important;
  border: none !important;
  border-radius: 12px !important;
  box-shadow: 0 0 15px rgba(0, 240, 255, 0.4) !important;
  transition: all 0.3s ease !important;
}

[class*="st-key-pitch_"] button p,
[class*="st-key-repitch_"] button p,
button[kind="primary"] p {
  color: #000000 !important;
  font-weight: bold !important;
}

[class*="st-key-pitch_"] button:hover:not(:disabled),
[class*="st-key-repitch_"] button:hover:not(:disabled),
button[kind="primary"]:hover:not(:disabled) {
  transform: translateY(-2px) !important;
  box-shadow: 0 0 25px rgba(0, 240, 255, 0.75), 0 4px 15px rgba(0, 85, 255, 0.5) !important;
}

/* Secondary Button Styling */
.stButton > button:not([kind="primary"]) {
  background: rgba(255, 255, 255, 0.04) !important;
  color: #E2E8F0 !important;
  border: 1px solid rgba(255, 255, 255, 0.12) !important;
  border-radius: 10px !important;
  backdrop-filter: blur(10px) !important;
  transition: all 0.25s ease !important;
}

.stButton > button:not([kind="primary"]):hover:not(:disabled) {
  background: rgba(255, 255, 255, 0.08) !important;
  border-color: rgba(0, 240, 255, 0.4) !important;
  color: #00F0FF !important;
}

/* =====================================================================
   7. Supporting Elements: Chat Messages, Metrics & Containers
   ===================================================================== */
[data-testid="stChatMessage"] {
  background: rgba(255, 255, 255, 0.03) !important;
  backdrop-filter: blur(14px) !important;
  -webkit-backdrop-filter: blur(14px) !important;
  border: 1px solid rgba(255, 255, 255, 0.08) !important;
  border-radius: 14px !important;
  padding: 1rem 1.25rem !important;
  margin-bottom: 0.75rem !important;
  color: #FFFFFF !important;
}

[data-testid="stChatMessage"] p,
[data-testid="stChatMessage"] div {
  color: #FFFFFF !important;
}

[data-testid="stMetric"] {
  background: rgba(255, 255, 255, 0.03) !important;
  backdrop-filter: blur(14px) !important;
  -webkit-backdrop-filter: blur(14px) !important;
  border: 1px solid rgba(255, 255, 255, 0.1) !important;
  border-radius: 14px !important;
  padding: 1rem 1.25rem !important;
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.3) !important;
}

[data-testid="stMetric"] label {
  color: #94A3B8 !important;
  font-weight: 600 !important;
}

[data-testid="stMetric"] [data-testid="stMetricValue"] {
  color: #00F0FF !important;
  font-weight: 800 !important;
  text-shadow: 0 0 15px rgba(0, 240, 255, 0.4) !important;
}

[data-testid="stDataFrame"] {
  border: 1px solid rgba(255, 255, 255, 0.08) !important;
  border-radius: 14px !important;
  overflow: hidden !important;
}

[data-testid="stExpander"] {
  background: rgba(255, 255, 255, 0.02) !important;
  border: 1px solid rgba(255, 255, 255, 0.08) !important;
  border-radius: 12px !important;
}

[data-testid="stVerticalBlockBorderWrapper"] {
  border-color: rgba(255, 255, 255, 0.08) !important;
  background: rgba(255, 255, 255, 0.02) !important;
  backdrop-filter: blur(12px) !important;
  -webkit-backdrop-filter: blur(12px) !important;
  border-radius: 16px !important;
}
"""

DECISION_ORDER = ["eligible_for_scoring", "human_review", "investigate", "reject"]
LEAD_SUMMARY_COLUMNS = [
    "opportunity_id", "title", "buyer", "submission_deadline",
    "decision_status", "decision_reasons", "evaluated_at",
]

def render_hero() -> None:
    """Render the cinematic DeepSeek hero section with direct static video serving."""
    hero_html = """
    <div style="position: relative; width: 100%; height: 350px; border-radius: 20px; overflow: hidden; margin-bottom: 2rem;">
        <video src="/app/static/jarvis_hero.mp4" autoplay loop muted playsinline style="width: 100%; height: 350px; object-fit: cover; border-radius: 20px; border: 1px solid rgba(0, 240, 255, 0.3); box-shadow: 0 0 30px rgba(0, 240, 255, 0.1); display: block;"></video>
        <div style="position: absolute; top: 0; left: 0; width: 100%; height: 100%; border-radius: 20px; background: linear-gradient(180deg, rgba(10, 15, 28, 0.25) 0%, rgba(10, 15, 28, 0.8) 100%); display: flex; flex-direction: column; align-items: center; justify-content: center; pointer-events: none;">
            <div style="display: inline-flex; align-items: center; gap: 8px; padding: 4px 14px; background: rgba(0, 240, 255, 0.1); border: 1px solid rgba(0, 240, 255, 0.3); border-radius: 9999px; color: #38BDF8; font-size: 0.75rem; font-weight: 700; letter-spacing: 0.2em; text-transform: uppercase; margin-bottom: 0.5rem;">
                <span style="width: 7px; height: 7px; background: #00F0FF; border-radius: 50%; box-shadow: 0 0 8px #00F0FF;"></span> SOVEREIGN INTELLIGENCE
            </div>
            <h1 style="font-size: 4rem; font-weight: 900; margin: 0; color: #FFFFFF; text-shadow: 0 0 20px #00F0FF; letter-spacing: 0.15em; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.1;">JARVIS</h1>
            <p style="font-size: 1.15rem; color: #94A3B8; margin-top: 8px; letter-spacing: 0.25em; text-transform: uppercase; font-weight: 600; text-shadow: 0 2px 10px rgba(0,0,0,0.8);">Global Tender Intelligence</p>
        </div>
    </div>
    """
    st.markdown(hero_html, unsafe_allow_html=True)

# --- Pure helpers ---
def read_secret(name: str) -> str | None:
    try:
        value = (SECRETS_DIR / name).read_text(encoding="utf-8-sig").strip()
    except FileNotFoundError:
        logger.error("Secret %s is not mounted", name)
        return None
    except OSError:
        return None
    return value or None

def check_password(candidate: str, expected: str) -> bool:
    return hmac.compare_digest(candidate.encode("utf-8"), expected.encode("utf-8"))

def md_escape(text: Any) -> str:
    flat = " ".join(str(text).split())
    return _MD_SPECIAL_RE.sub(r"\\\1", flat)

def sanitize_csv_field(value: Any) -> Any:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    if isinstance(value, (bool, int, float)):
        return value
    text = str(value)
    return "'" + text if text.startswith(FORMULA_TRIGGERS) else text

def to_safe_csv(df: pd.DataFrame) -> bytes:
    return df.map(sanitize_csv_field).to_csv(index=False).encode("utf-8-sig")

def valid_approval_id(raw: Any) -> str | None:
    if isinstance(raw, bool) or not isinstance(raw, (str, int)):
        return None
    item_id = str(raw)
    return item_id if APPROVAL_ID_RE.fullmatch(item_id) else None

def valid_tender_id(raw: Any) -> str | None:
    return raw if isinstance(raw, str) and TENDER_ID_RE.fullmatch(raw) else None

def parse_pitch_reply(raw: Any) -> dict[str, Any] | None:
    try:
        data = json.loads(raw) if isinstance(raw, str) else None
    except ValueError:
        return None
    if not isinstance(data, dict) or not isinstance(data.get("pitch"), str) or not data["pitch"]:
        return None
    evidence = []
    for item in data.get("evidence") or []:
        if isinstance(item, dict):
            score = item.get("score")
            evidence.append({
                "title": str(item.get("title") or "")[:200],
                "section": str(item.get("section") or "")[:100],
                "score": float(score) if isinstance(score, (int, float)) else None,
                "text": str(item.get("text") or "")[:1500],
            })
    return {
        "pitch": data["pitch"][:8000],
        "matched_project": str(data.get("matched_project") or "")[:200],
        "match_source": str(data.get("match_source") or ""),
        "match_rationale": str(data.get("match_rationale") or "")[:1500],
        "warnings": [str(w)[:300] for w in (data.get("warnings") or []) if isinstance(w, str)][:5],
        "evidence": evidence[:8],
        "generated_at": str(data.get("generated_at") or "")[:40],
        "cached": data.get("cached") is True,
    }

def inject_theme() -> None:
    st.markdown(f"<style>{THEME_CSS}</style>", unsafe_allow_html=True)

# --- Core API client ---
class CoreError(Exception):
    pass

@st.cache_resource
def _http_client() -> httpx.Client:
    return httpx.Client(base_url=CORE_URL, timeout=API_TIMEOUT_S, trust_env=False, follow_redirects=False)

def core_request(method: str, path: str, *, json: Any = None, timeout: float = API_TIMEOUT_S, not_found_message: str | None = None) -> Any:
    token = read_secret(TOKEN_SECRET)
    if not token:
        raise CoreError("The core API token is not configured.")
    try:
        resp = _http_client().request(method, path, json=json, timeout=timeout, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
    except httpx.TimeoutException:
        raise CoreError("Jarvis core did not respond in time. Please try again.") from None
    except httpx.HTTPError:
        raise CoreError("Cannot reach Jarvis core.") from None

    if resp.status_code in (401, 403):
        raise CoreError("Jarvis core rejected the dashboard's credentials.")
    if resp.status_code == 404:
        raise CoreError(not_found_message or "Not found: Jarvis core doesn't provide this feature yet.")
    if resp.status_code == 503:
        raise CoreError("Jarvis is busy with another request. Please try again shortly.")
    if resp.status_code >= 400:
        raise CoreError(f"Jarvis core returned an error (HTTP {resp.status_code}).")
    if resp.status_code == 204 or not resp.content:
        return None
    try:
        return resp.json()
    except ValueError:
        raise CoreError("Jarvis core returned an invalid response.") from None

def _voice_headers() -> dict[str, str]:
    token = read_secret(TOKEN_SECRET)
    if not token:
        raise CoreError("The core API token is not configured.")
    return {"Authorization": f"Bearer {token}", "Accept": "application/json"}


def _voice_error(status_code: int, action: str) -> CoreError:
    if status_code in (401, 403):
        return CoreError("Jarvis core rejected the dashboard's credentials.")
    if status_code == 404:
        return CoreError("The voice service is not available yet.")
    if status_code == 413:
        return CoreError("That recording is too long. Please keep it under 30 seconds.")
    if status_code == 503:
        return CoreError("Jarvis is busy with another request. Please try again shortly.")
    return CoreError(f"Jarvis could not {action}. Please try again.")


def transcribe_audio(audio_bytes: bytes, mime_type: str) -> str:
    """Send a recording to core's voice proxy and return the transcript."""
    try:
        resp = _http_client().post(
            "/api/voice/transcribe",
            files={"file": ("speech.wav", audio_bytes, mime_type or "audio/wav")},
            headers=_voice_headers(),
            timeout=VOICE_TIMEOUT_S,
        )
    except httpx.TimeoutException:
        raise CoreError("Speech recognition took too long. Please try again.") from None
    except httpx.HTTPError:
        raise CoreError("Cannot reach Jarvis voice service.") from None

    if resp.status_code >= 400:
        raise _voice_error(resp.status_code, "transcribe that recording")
    try:
        data = resp.json()
    except ValueError:
        raise CoreError("Jarvis returned an invalid transcription response.") from None
    text = data.get("text") if isinstance(data, dict) else None
    if not isinstance(text, str) or not text.strip():
        raise CoreError("Jarvis could not make out any words. Please try again.")
    return text.strip()[:MAX_MESSAGE_CHARS]


def synthesize_speech(text: str) -> bytes | None:
    """Ask core's voice proxy for WAV audio of ``text``; return None if TTS is unavailable."""
    try:
        resp = _http_client().post(
            "/api/voice/synthesize",
            json={"text": text[:MAX_MESSAGE_CHARS]},
            headers=_voice_headers(),
            timeout=VOICE_TIMEOUT_S,
        )
    except httpx.TimeoutException:
        raise CoreError("Speech synthesis took too long.") from None
    except httpx.HTTPError:
        raise CoreError("Cannot reach Jarvis voice service.") from None

    if resp.status_code >= 400 or not resp.content:
        raise _voice_error(resp.status_code, "speak that reply")
    return resp.content


def _items(payload: Any) -> list[dict[str, Any]]:
    items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        raise CoreError("Unexpected response format from Jarvis core.")
    return [item for item in items if isinstance(item, dict)]

@st.cache_data(ttl=30, show_spinner=False)
def _core_online() -> bool:
    try:
        core_request("GET", "/health", timeout=5)
    except CoreError:
        return False
    return True

# --- Authentication & session ---
@dataclass
class LoginThrottle:
    lock: threading.Lock = field(default_factory=threading.Lock)
    failures: int = 0
    locked_until: float = 0.0

@st.cache_resource
def _login_throttle() -> LoginThrottle:
    return LoginThrottle()

def _start_session() -> None:
    st.session_state.clear()
    st.session_state["authenticated"] = True
    st.session_state["last_activity"] = time.monotonic()
    st.session_state["conversation_id"] = uuid.uuid4().hex
    st.session_state["chat"] = []

def _logout(reason: str) -> None:
    st.session_state.clear()
    if reason == "idle":
        st.session_state["login_notice"] = "You were signed out after a period of inactivity."

def _idle_expired() -> bool:
    return time.monotonic() - st.session_state.get("last_activity", 0.0) > SESSION_IDLE_TIMEOUT_S

def _touch() -> None:
    st.session_state["last_activity"] = time.monotonic()

def _session_valid() -> bool:
    if not st.session_state.get("authenticated"):
        return False
    if _idle_expired():
        _logout("idle")
        return False
    _touch()
    return True

def render_login() -> None:
    _, mid, _ = st.columns([1, 2, 1])
    with mid:
        st.markdown(
            """
            <div style="text-align: center; margin-bottom: 2rem; margin-top: 2rem;">
                <h1 style="font-size: 3.5rem; font-weight: 900; letter-spacing: 0.1em; margin: 0;
                           background: linear-gradient(135deg, #FFFFFF 15%, #38BDF8 70%, #00F0FF 100%);
                           -webkit-background-clip: text; -webkit-text-fill-color: transparent;
                           filter: drop-shadow(0 0 25px rgba(0, 240, 255, 0.5));">JARVIS</h1>
                <p style="color: #94A3B8; letter-spacing: 0.25em; text-transform: uppercase; font-size: 0.85rem; margin-top: 0.5rem; font-weight: 600;">CEO Dashboard · Authentication</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if notice := st.session_state.pop("login_notice", None):
            st.info(notice)

        throttle = _login_throttle()
        with throttle.lock:
            remaining = throttle.locked_until - time.monotonic()
        if remaining > 0:
            st.error(f"Too many failed attempts. Try again in {int(remaining // 60) + 1} min.")
            return

        expected = read_secret(PASSWORD_SECRET)
        if not expected:
            st.error("Sign-in is not configured. Contact the administrator.")
            return

        with st.form("login", clear_on_submit=True):
            password = st.text_input("Password", type="password", max_chars=256)
            submitted = st.form_submit_button("Sign in", type="primary", width="stretch")

        if not submitted:
            return
        if password and check_password(password, expected):
            with throttle.lock:
                throttle.failures = 0
            _start_session()
            st.rerun()

        with throttle.lock:
            throttle.failures += 1
            if throttle.failures >= MAX_LOGIN_FAILURES:
                throttle.locked_until = time.monotonic() + LOCKOUT_S
                throttle.failures = 0
        time.sleep(1)
        st.error("Incorrect password.")

# --- Sidebar ---
def render_sidebar() -> None:
    with st.sidebar:
        st.subheader("Jarvis")
        if _core_online():
            st.success("Core online", icon=":material/check_circle:")
        else:
            st.error("Core unreachable", icon=":material/error:")
        st.caption(f"Signed out automatically after {SESSION_IDLE_TIMEOUT_S // 60} min idle.")
        if st.button("Sign out", width="stretch"):
            _logout("user")
            st.rerun()

# --- Tab: Command Jarvis ---
def _render_message(msg: dict[str, Any]) -> None:
    with st.chat_message(msg["role"]):
        if msg.get("error"):
            st.error(msg["content"])
        else:
            st.text(msg["content"])
            if msg.get("audio"):
                st.audio(msg["audio"], format="audio/wav")
            elif msg.get("tts_error"):
                st.caption(f"Voice reply unavailable: {md_escape(msg['tts_error'])}")

def valid_job_id(raw: Any) -> str | None:
    return raw if isinstance(raw, str) and JOB_ID_RE.fullmatch(raw) else None

def _error_answer(text: str) -> dict[str, Any]:
    return {"role": "assistant", "content": text, "error": True}

def _start_chat_job(prompt: str) -> str:
    data = core_request("POST", "/chat", json={"message": prompt, "conversation_id": st.session_state["conversation_id"]})
    job_id = valid_job_id(data.get("job_id") if isinstance(data, dict) else None)
    if job_id is None:
        raise CoreError("Unexpected response format from Jarvis core.")
    return job_id

def _wait_for_job(pending: dict[str, Any], spinner_text: str = "Jarvis is thinking…") -> dict[str, Any]:
    job_id = pending["job_id"]
    deadline = pending["started"] + CHAT_MAX_WAIT_S
    with st.spinner(spinner_text):
        while True:
            try:
                data = core_request("GET", f"/jobs/{job_id}", not_found_message="Jarvis lost track of this request.")
            except CoreError as exc:
                return _error_answer(str(exc))
            job_status = data.get("status") if isinstance(data, dict) else None
            if job_status == "done":
                reply = data.get("reply")
                if not isinstance(reply, str):
                    return _error_answer("Unexpected response format from Jarvis core.")
                return {"role": "assistant", "content": reply}
            if job_status == "error":
                error = data.get("error")
                return _error_answer(error if isinstance(error, str) and error else "Jarvis could not answer.")
            if job_status != "running":
                return _error_answer("Unexpected response format from Jarvis core.")
            if time.monotonic() >= deadline:
                return _error_answer("Jarvis is taking too long to answer.")
            time.sleep(CHAT_POLL_S)

def _run_voice_turn(audio_val: Any, history: list[dict[str, Any]], box: Any) -> None:
    """Transcribe a recording, send it to the chat crew, then speak the reply."""
    audio_bytes = audio_val.getvalue()
    if not audio_bytes:
        return
    digest = hashlib.sha256(audio_bytes).hexdigest()
    if st.session_state.get("voice_last_audio") == digest:
        # The widget keeps its value across reruns; never transcribe the same clip twice.
        return
    st.session_state["voice_last_audio"] = digest

    try:
        with st.spinner("Jarvis is listening..."):
            prompt = transcribe_audio(
                audio_bytes, getattr(audio_val, "type", "") or "audio/wav"
            )
    except CoreError as exc:
        history.append(_error_answer(str(exc)))
        del history[:-MAX_CHAT_HISTORY]
        st.rerun()
        return

    user_msg = {"role": "user", "content": prompt}
    history.append(user_msg)
    with box:
        _render_message(user_msg)

    try:
        job_id = _start_chat_job(prompt)
    except CoreError as exc:
        history.append(_error_answer(str(exc)))
        del history[:-MAX_CHAT_HISTORY]
        st.rerun()
        return

    with box:
        answer = _wait_for_job({"job_id": job_id, "started": time.monotonic()})
        if not answer.get("error"):
            try:
                with st.spinner("Jarvis is speaking..."):
                    audio = synthesize_speech(answer["content"])
            except CoreError as exc:
                answer["tts_error"] = str(exc)
            else:
                if audio:
                    answer["audio"] = audio

    # Keep only the newest spoken reply: WAV audio accumulates quickly in session state.
    for old in history:
        old.pop("audio", None)
    history.append(answer)
    del history[:-MAX_CHAT_HISTORY]
    st.rerun()


def render_chat() -> None:
    history: list[dict[str, Any]] = st.session_state.setdefault("chat", [])
    pending: dict[str, Any] | None = st.session_state.get("chat_pending")
    box = st.container(height=480, border=True)
    with box:
        if not history:
            st.caption("Ask Jarvis anything, e.g. “Summarise today's eligible tenders.”")
        for msg in history:
            _render_message(msg)

    pitch_busy = (st.session_state.get("pitch_pending") is not None or st.session_state.get("pitch_request") is not None)
    busy = pending is not None or pitch_busy
    placeholder = ("Jarvis is answering…" if pending else "Jarvis is drafting a pitch…" if pitch_busy else "Command Jarvis…")
    prompt = st.chat_input(placeholder, max_chars=MAX_MESSAGE_CHARS, disabled=busy)
    audio_val = st.audio_input("Or press to speak", key="voice_input", disabled=busy)
    if pending is None and prompt and prompt.strip():
        prompt = prompt.strip()
        user_msg = {"role": "user", "content": prompt}
        history.append(user_msg)
        with box:
            _render_message(user_msg)
        try:
            job_id = _start_chat_job(prompt)
        except CoreError as exc:
            history.append(_error_answer(str(exc)))
            del history[:-MAX_CHAT_HISTORY]
            st.rerun()
        pending = {"job_id": job_id, "started": time.monotonic()}
        st.session_state["chat_pending"] = pending
    elif pending is None and audio_val is not None:
        _run_voice_turn(audio_val, history, box)

    if pending is not None:
        with box:
            answer = _wait_for_job(pending)
        st.session_state.pop("chat_pending", None)
        history.append(answer)
        del history[:-MAX_CHAT_HISTORY]
        st.rerun()

# --- Tab: Pending Approvals ---
def _set_confirm(key: str, state: str | None) -> None:
    _touch()
    confirm: dict[str, str] = st.session_state.setdefault("approval_confirm", {})
    if state is None:
        confirm.pop(key, None)
    else:
        confirm[key] = state

def _submit_approval(key: str, item_id: str, action: str) -> None:
    _touch()
    reason = str(st.session_state.get(f"reason_{key}", "")).strip()[:MAX_REASON_CHARS]
    body = {"reason": reason} if action == "reject" else None
    try:
        core_request("POST", f"/approvals/{item_id}/{action}", json=body)
    except CoreError as exc:
        st.session_state["approvals_error"] = str(exc)
        return
    st.session_state.setdefault("approval_confirm", {}).pop(key, None)
    st.session_state["approvals_flash"] = ("Approved: Jarvis may now send the email." if action == "approve" else "Draft rejected.")

def _render_approval(item: dict[str, Any]) -> None:
    item_id = valid_approval_id(item.get("id"))
    if item_id is None:
        st.warning("An approval item with an invalid id was skipped.")
        return

    key = hashlib.sha256(item_id.encode()).hexdigest()[:16]
    state = st.session_state.get("approval_confirm", {}).get(key)

    with st.container(border=True):
        st.markdown(f"**{md_escape(item.get('subject') or '(no subject)')}**")
        meta = [f"To: {md_escape(item.get('to') or '?')}"]
        if item.get("created_at"):
            meta.append(f"Drafted: {md_escape(item['created_at'])}")
        if item.get("context"):
            meta.append(f"Re: {md_escape(item['context'])}")
        st.caption(" · ".join(meta))
        with st.container(height=220, border=False):
            st.text(str(item.get("body") or ""))

        c1, c2, _ = st.columns([1, 1, 4])
        if state is None:
            c1.button("Approve", key=f"approve_{key}", type="primary", width="stretch", on_click=_set_confirm, args=(key, "approve"))
            c2.button("Reject", key=f"reject_{key}", width="stretch", on_click=_set_confirm, args=(key, "reject"))
            return

        if state == "approve":
            st.warning("Approve this draft? Jarvis will be allowed to send it.")
        else:
            st.text_input("Reason for rejecting (optional)", key=f"reason_{key}", max_chars=MAX_REASON_CHARS)
        c1, c2, _ = st.columns([1, 1, 4])
        c1.button("Confirm approve" if state == "approve" else "Confirm reject", key=f"confirm_{key}", type="primary", width="stretch", on_click=_submit_approval, args=(key, item_id, state))
        c2.button("Cancel", key=f"cancel_{key}", width="stretch", on_click=_set_confirm, args=(key, None))

@st.fragment(run_every=APPROVALS_POLL_S)
def render_approvals() -> None:
    if not st.session_state.get("authenticated"):
        return
    if _idle_expired():
        _logout("idle")
        st.rerun()

    head, refresh = st.columns([5, 1])
    refresh.button("Refresh", key="approvals_refresh", width="stretch", on_click=_touch)
    if flash := st.session_state.pop("approvals_flash", None):
        st.success(flash)
    if error := st.session_state.pop("approvals_error", None):
        st.error(error)

    try:
        items = _items(core_request("GET", "/approvals"))
    except CoreError as exc:
        head.caption(f"Auto-refreshes every {APPROVALS_POLL_S}s")
        st.warning(str(exc))
        return

    head.caption(f"{len(items)} pending · auto-refreshes every {APPROVALS_POLL_S}s")
    if not items:
        st.success("Nothing is waiting for your approval.")
        return
    for item in items:
        _render_approval(item)

# --- Tab: Daily Drafts ---
def _load_leads(force: bool) -> list[dict[str, Any]]:
    cached = st.session_state.get("leads_cache")
    if not force and cached and time.monotonic() - cached[0] < LEADS_CACHE_S:
        return cached[1]
    rows = _items(core_request("GET", "/leads"))
    st.session_state["leads_cache"] = (time.monotonic(), rows)
    return rows

@st.fragment
def render_leads() -> None:
    head, refresh_col = st.columns([5, 1])
    refresh = refresh_col.button("Refresh", key="leads_refresh", width="stretch")
    if refresh:
        _touch()
    try:
        rows = _load_leads(force=refresh)
    except CoreError as exc:
        st.warning(str(exc))
        return
    if not rows:
        st.info("No assessed opportunities yet.")
        return

    df = pd.DataFrame(rows)
    known = [c for c in LEAD_SUMMARY_COLUMNS if c in df.columns]
    head.caption(f"{len(df)} rows from Jarvis core")

    if "decision_status" in df.columns:
        per_opp = df.drop_duplicates("opportunity_id") if "opportunity_id" in df.columns else df
        counts = per_opp["decision_status"].value_counts()
        cols = st.columns(len(DECISION_ORDER))
        for col, status in zip(cols, DECISION_ORDER, strict=True):
            col.metric(status.replace("_", " ").title(), int(counts.get(status, 0)))

        statuses = [s for s in DECISION_ORDER if s in set(df["decision_status"])]
        statuses += sorted(set(df["decision_status"].astype(str)) - set(statuses))
        default = [s for s in statuses if s != "reject"]
        chosen = st.multiselect("Decision status", statuses, default=default, key="leads_status_filter")
        df = df[df["decision_status"].isin(chosen)]

    summary = df.drop_duplicates("opportunity_id") if "opportunity_id" in df.columns else df
    st.subheader(f"Opportunities ({len(summary)})")
    st.dataframe(summary[known] if known else summary, hide_index=True, width="stretch")

    with st.expander("Requirement-level detail"):
        st.dataframe(df, hide_index=True, width="stretch")

    st.download_button("Download CSV", data=to_safe_csv(df), file_name=f"jarvis_leads_{datetime.now():%Y%m%d}.csv", mime="text/csv", on_click="ignore")

# --- Tab: Global Tenders ---
def _load_tenders(force: bool) -> dict[str, Any]:
    cached = st.session_state.get("tenders_cache")
    if not force and cached and time.monotonic() - cached[0] < TENDERS_CACHE_S:
        return cached[1]
    payload = core_request("GET", "/global-tenders")
    data = {"items": _items(payload), "mode": str(payload.get("mode") or "")}
    st.session_state["tenders_cache"] = (time.monotonic(), data)
    return data

def _request_pitch(tender_id: str, regenerate: bool) -> None:
    _touch()
    st.session_state["pitch_request"] = {"tender_id": tender_id, "regenerate": regenerate}

def _start_pitch_job(tender_id: str, regenerate: bool) -> str:
    data = core_request("POST", f"/global-tenders/{tender_id}/pitch", json={"regenerate": regenerate}, not_found_message="This tender is no longer listed. Refresh the list.")
    job_id = valid_job_id(data.get("job_id") if isinstance(data, dict) else None)
    if job_id is None:
        raise CoreError("Unexpected response format from Jarvis core.")
    return job_id

def _render_pitch(result: dict[str, Any]) -> None:
    st.markdown(f"**Matched project:** {md_escape(result['matched_project'] or '(none)')}")
    how = ("chosen by the Global Matchmaker agent" if result["match_source"] == "agent" else "top retrieval hit")
    when = f" · drafted {md_escape(result['generated_at'])}" if result["generated_at"] else ""
    st.caption(f"{how}{when}{' · stored draft, not regenerated' if result['cached'] else ''}")
    if result["match_rationale"]:
        st.text(result["match_rationale"])
    for warning in result["warnings"]:
        st.warning(md_escape(warning))
    st.markdown("**VIP pitch (draft for review)**")
    st.text(result["pitch"])
    if result["evidence"]:
        with st.expander("Evidence retrieved from the CEO profile (RAG)"):
            for item in result["evidence"]:
                score = f" · similarity {item['score']:.2f}" if item["score"] is not None else ""
                st.caption(f"{md_escape(item['title'])} · {md_escape(item['section'])}{score}")
                st.text(item["text"])

def _render_tender(row: dict[str, Any], busy: bool) -> Any:
    tender_id = valid_tender_id(row.get("id"))
    if tender_id is None:
        return None
    result = st.session_state.get("pitches", {}).get(tender_id)
    with st.container(key=f"tender_{tender_id}"):
        region = str(row.get("region") or "")
        badges = (f":{REGION_BADGES[region]}-badge[{region}]" if region in REGION_BADGES else md_escape(region or "?"))
        if row.get("is_mock"):
            badges += " :orange-badge[SAMPLE]"
        st.markdown(badges)
        st.markdown(f"**{md_escape(row.get('title') or '(untitled)')}**")
        st.caption(" · ".join(md_escape(row.get(k) or "?") for k in ("buyer", "source_portal", "reference")))
        left, mid, right = st.columns([2, 2, 3])
        left.caption(f"Deadline: {md_escape(str(row.get('submission_deadline') or '?')[:10])}")
        mid.caption(f"Value: {md_escape(row.get('estimated_value') or '?')}")
        right.caption(f"Procedure: {md_escape(row.get('procedure') or '?')}")
        st.text(str(row.get("summary") or ""))
        for label, key in (("Needs", "required_capabilities"), ("Mandatory", "mandatory_requirements")):
            values = row.get(key)
            if isinstance(values, list) and values:
                st.caption(f"{label}: " + " · ".join(md_escape(v) for v in values[:8]))

        c1, c2, _ = st.columns([2, 2, 5])
        if result is None:
            c1.button("Draft VIP Pitch", key=f"pitch_{tender_id}", type="primary", width="stretch", disabled=busy, on_click=_request_pitch, args=(tender_id, False))
        else:
            c1.button("Regenerate pitch", key=f"repitch_{tender_id}", width="stretch", disabled=busy, on_click=_request_pitch, args=(tender_id, True))
        if error := st.session_state.get("pitch_errors", {}).get(tender_id):
            st.error(error)
        slot = st.container(key=f"pitchbox_{tender_id}")
        if result is not None:
            with slot:
                _render_pitch(result)
        return slot

def render_global_tenders() -> None:
    head, refresh_col = st.columns([5, 1])
    refresh = refresh_col.button("Refresh", key="tenders_refresh", width="stretch")
    if refresh:
        _touch()
    try:
        feed = _load_tenders(force=refresh)
    except CoreError as exc:
        st.warning(str(exc))
        return
    rows = feed["items"]
    head.caption(f"{len(rows)} tenders · UK Find a Tender · US SAM.gov · EU TED")
    if feed["mode"] != "live":
        st.info("Sample data: these three tenders are demonstration records. Matching and pitch drafting below run for real on the local models.")
    if not rows:
        st.info("No tenders listed.")
        return

    pitches: dict[str, Any] = st.session_state.setdefault("pitches", {})
    errors: dict[str, str] = st.session_state.setdefault("pitch_errors", {})
    pending: dict[str, Any] | None = st.session_state.get("pitch_pending")

    request = st.session_state.pop("pitch_request", None)
    if request and pending is None:
        tender_id = valid_tender_id(request.get("tender_id"))
        if tender_id is not None:
            errors.pop(tender_id, None)
            try:
                job_id = _start_pitch_job(tender_id, bool(request.get("regenerate")))
            except CoreError as exc:
                errors[tender_id] = str(exc)
            else:
                pending = {"job_id": job_id, "tender_id": tender_id, "started": time.monotonic()}
                st.session_state["pitch_pending"] = pending

    busy = pending is not None or st.session_state.get("chat_pending") is not None
    slots = {row.get("id"): _render_tender(row, busy) for row in rows}

    if pending is not None:
        tender_id = pending["tender_id"]
        slot = slots.get(tender_id) or st.container()
        with slot:
            answer = _wait_for_job(pending, "Matching this tender to the CEO's track record and drafting the pitch…")
        st.session_state.pop("pitch_pending", None)
        result = None if answer.get("error") else parse_pitch_reply(answer["content"])
        if result is not None:
            pitches[tender_id] = result
        else:
            errors[tender_id] = (answer["content"] if answer.get("error") else "Unexpected response format from Jarvis core.")
        st.rerun()

# --- App Entrypoint ---
def main() -> None:
    st.set_page_config(
        page_title="Jarvis · CEO Dashboard",
        page_icon="⚡",
        layout="wide",
        initial_sidebar_state="collapsed",
        menu_items={"Get help": None, "Report a bug": None, "About": None},
    )
    inject_theme()

    if not _session_valid():
        render_login()
        return

    render_sidebar()

    # Cinematic Hero Section MUST be rendered BEFORE st.tabs()
    render_hero()

    # Minimalistic tabs with cyan glow
    chat_tab, tenders_tab, approvals_tab, leads_tab = st.tabs([
        "Command Jarvis",
        "Global Tenders",
        "Pending Approvals",
        "Daily Drafts",
    ])
    with chat_tab:
        render_chat()
    with tenders_tab:
        render_global_tenders()
    with approvals_tab:
        render_approvals()
    with leads_tab:
        render_leads()

if __name__ == "__main__":
    main()
