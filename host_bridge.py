#!/usr/bin/env python3
"""Jarvis Host Control Bridge - runs natively on the Windows laptop, not in Docker.

The Dockerised Jarvis core cannot touch the desktop, so it forwards every remote-control
request to this small FastAPI service over ``host.docker.internal:9090``.

Endpoints (all except /health require ``Authorization: Bearer <host_token>``)
    GET  /health            Liveness probe. The only unauthenticated route.
    POST /action/type       {"text": "..."}                Type on the focused window.
    POST /action/hotkey     {"keys": ["ctrl", "c"]}        Press a key combination.
    POST /action/open_app   {"app_name": "code"}           Launch an application.
    GET  /screenshot        Base64 PNG of the requested monitor.
    GET  /system_stats      CPU, RAM and battery percentages.
    POST /action/whatsapp   {"phone": "+447...", "message": "..."}  Send via WhatsApp Web.

Run it:
    python host_bridge.py                 # 127.0.0.1:9090
    python host_bridge.py --port 9091     # different port
    python host_bridge.py --host 0.0.0.0  # ONLY if Docker Desktop cannot reach loopback

Security notes
- Binds to 127.0.0.1 by default: nothing on the LAN can reach it. Docker Desktop forwards
  ``host.docker.internal`` to the host's loopback interface, so containers still connect.
- The bearer token lives in ``secrets/host_token.txt`` next to this script (override with
  ``HOST_TOKEN_FILE``). Missing or empty token = every call is refused (fail closed).
- Text is never logged: it may contain passwords. Only action names, sizes and durations.
- Windows UIPI: pyautogui cannot type into windows owned by an elevated (Administrator)
  process unless this bridge itself runs elevated. Run it normally first.
- Move the mouse to a screen corner to trigger pyautogui's failsafe; the call returns 409.
"""

from __future__ import annotations

import argparse
import base64
import hmac
import logging
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import mss
import mss.tools
import psutil
import uvicorn
from fastapi import APIRouter, Depends, FastAPI, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field, field_validator

APP_VERSION = "1.0.0"
SERVICE_NAME = "jarvis-host-bridge"

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9090
TOKEN_FILE_NAME = "host_token.txt"  # noqa: S105 - a file name, not a secret value

MAX_TEXT_CHARS = 4_000
MAX_KEYS = 5
MAX_APP_NAME_CHARS = 260
# Fast enough for 4 000 characters to finish inside the core's 30 s proxy timeout.
TYPING_INTERVAL_S = 0.002

# WhatsApp: pywhatkit drives WhatsApp Web in the user's default browser. It needs a logged-in
# WhatsApp Web session; the phone number must include the country code.
MAX_WHATSAPP_CHARS = 1_000
WHATSAPP_DEFAULT_COUNTRY = os.environ.get("WHATSAPP_DEFAULT_COUNTRY", "").strip()
WHATSAPP_WAIT_S = int(os.environ.get("WHATSAPP_WAIT_SECONDS", "20"))
_whatsapp_lock = threading.Lock()

KEY_PATTERN = re.compile(r"^[a-z0-9_]{1,16}$")
APP_NAME_PATTERN = re.compile(
    rf"^[A-Za-z0-9 ._\-:/\\]{{1,{MAX_APP_NAME_CHARS}}}$"
)

# pyautogui key names we accept for hotkeys. Anything else is rejected before it reaches
# the desktop, so a malformed request cannot wedge the keyboard.
ALLOWED_KEYS = frozenset(
    {
        "ctrl", "control", "alt", "shift", "win", "cmd", "command", "option",
        "esc", "escape", "tab", "enter", "return", "space", "backspace", "delete",
        "insert", "home", "end", "pageup", "pagedown", "up", "down", "left", "right",
        "capslock", "numlock", "scrolllock", "printscreen", "pause", "menu", "apps",
        "volumeup", "volumedown", "volumemute", "playpause", "nexttrack", "prevtrack",
        "sleep",
    }
    | {f"f{i}" for i in range(1, 25)}
    | {chr(c) for c in range(ord("a"), ord("z") + 1)}
    | {str(d) for d in range(10)}
)

# Friendly names -> executable that Windows can resolve on PATH.
APP_ALIASES = {
    "vscode": "code",
    "vs code": "code",
    "visual studio code": "code",
    "google chrome": "chrome",
    "chrome browser": "chrome",
    "microsoft edge": "msedge",
    "browser": "msedge",
    "files": "explorer",
    "file explorer": "explorer",
    "explorer": "explorer",
    "terminal": "wt",
    "windows terminal": "wt",
    "command prompt": "cmd",
    "cmd": "cmd",
    "powershell": "powershell",
    "notepad": "notepad",
    "calculator": "calc",
    "calc": "calc",
    "paint": "mspaint",
    "word": "winword",
    "excel": "excel",
    "powerpoint": "powerpnt",
    "outlook": "outlook",
    "task manager": "taskmgr",
    "taskmgr": "taskmgr",
    "settings": "ms-settings:",
    "spotify": "spotify",
    "whatsapp": "whatsapp",
    "telegram": "telegram",
}

# Install locations for apps that are usually NOT on PATH.
KNOWN_APP_PATHS = {
    "code": (
        r"%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe",
        r"%ProgramFiles%\Microsoft VS Code\Code.exe",
        r"%ProgramFiles(x86)%\Microsoft VS Code\Code.exe",
    ),
    "chrome": (
        r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
        r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
        r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe",
    ),
    "msedge": (
        r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
        r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe",
    ),
    "wt": (
        r"%LOCALAPPDATA%\Microsoft\WindowsApps\wt.exe",
    ),
    "spotify": (
        r"%APPDATA%\Spotify\Spotify.exe",
    ),
    "telegram": (
        r"%APPDATA%\Telegram Desktop\Telegram.exe",
    ),
}

logger = logging.getLogger("jarvis.hostbridge")

_bearer = HTTPBearer(auto_error=False)


# --- Authentication ------------------------------------------------------------------------------
def _token_path() -> Path:
    """Location of the shared bearer token. Read on every call so rotation needs no restart."""
    override = os.environ.get("HOST_TOKEN_FILE")
    if override:
        return Path(override).expanduser()
    return Path(__file__).resolve().parent / "secrets" / TOKEN_FILE_NAME


def _load_token() -> str | None:
    try:
        token = _token_path().read_text(encoding="utf-8-sig").strip()
    except OSError:
        return None
    return token or None


def require_bridge_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),  # noqa: B008
) -> None:
    """Reject anything without a valid ``Authorization: Bearer <host_token>`` header."""
    expected = _load_token()
    if expected is None:
        logger.error("host_token is missing or empty at %s; refusing every call", _token_path())
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, detail="Host bridge token is not configured"
        )
    supplied = (
        credentials.credentials
        if credentials and credentials.scheme.lower() == "bearer"
        else ""
    )
    if not hmac.compare_digest(supplied.encode("utf-8"), expected.encode("utf-8")):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing host token",
            headers={"WWW-Authenticate": "Bearer"},
        )


# --- Request models ------------------------------------------------------------------------------
class BridgeModel(BaseModel):
    """Strict payloads: no unknown fields, surrounding whitespace removed."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class TypeRequest(BridgeModel):
    text: str = Field(min_length=1, max_length=MAX_TEXT_CHARS)


class HotkeyRequest(BridgeModel):
    keys: list[str] = Field(min_length=1, max_length=MAX_KEYS)

    @field_validator("keys")
    @classmethod
    def _known_keys(cls, keys: list[str]) -> list[str]:
        normalised = [key.strip().lower() for key in keys]
        unknown = [
            key
            for key in normalised
            if not KEY_PATTERN.fullmatch(key) or key not in ALLOWED_KEYS
        ]
        if unknown:
            raise ValueError(f"Unsupported key(s): {', '.join(unknown[:5])}")
        return normalised


class OpenAppRequest(BridgeModel):
    app_name: str = Field(min_length=1, max_length=MAX_APP_NAME_CHARS)

    @field_validator("app_name")
    @classmethod
    def _safe_name(cls, name: str) -> str:
        if not APP_NAME_PATTERN.fullmatch(name):
            raise ValueError("app_name contains unsupported characters")
        if ".." in name:
            raise ValueError("app_name must not contain '..'")
        return name


class WhatsAppRequest(BridgeModel):
    phone: str = Field(min_length=8, max_length=32)
    message: str = Field(min_length=1, max_length=MAX_WHATSAPP_CHARS)

    @field_validator("phone")
    @classmethod
    def _normalise_phone(cls, phone: str) -> str:
        raw = phone.strip()
        digits = re.sub(r"[^0-9]", "", raw)
        if raw.startswith("00"):  # 0044... -> 44...
            digits = digits[2:]
        if len(digits) < 8 or len(digits) > 15:
            raise ValueError("phone must have 8-15 digits including the country code")
        # pywhatkit wants '+<country><number>' with no spaces.
        return f"+{digits}"

    @field_validator("message")
    @classmethod
    def _printable(cls, message: str) -> str:
        if not message.strip():
            raise ValueError("message must not be blank")
        if any((ord(ch) < 32 and ch not in "\n\t") or ord(ch) == 127 for ch in message):
            raise ValueError("message contains unsupported control characters")
        return message


app = FastAPI(
    title="Jarvis Host Control Bridge",
    version=APP_VERSION,
    description="Local desktop automation endpoint for the Jarvis core container.",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


@app.get("/health", tags=["ops"])
def health() -> dict[str, Any]:
    """Liveness probe. Touches no GUI API, so it stays fast and never blocks on a locked screen."""
    return {
        "status": "ok",
        "service": SERVICE_NAME,
        "version": APP_VERSION,
        "host": socket.gethostname(),
        "timestamp": datetime.now(UTC).isoformat(),
    }


# --- GUI helpers ---------------------------------------------------------------------------------
def _pyautogui() -> Any:
    """Import pyautogui lazily: /health keeps working even if the GUI stack cannot load."""
    try:
        import pyautogui
    except Exception as exc:  # noqa: BLE001 - any import failure is a service problem
        logger.error("pyautogui could not be loaded: %s", type(exc).__name__)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Desktop automation is unavailable on this host (pyautogui failed to load).",
        ) from exc
    pyautogui.FAILSAFE = True   # moving the mouse to a corner aborts the action
    pyautogui.PAUSE = 0.05      # small gap between events so Windows keeps up
    return pyautogui


def _gui_error(exc: Exception) -> HTTPException:
    """Translate a pyautogui failure into a status the UI can explain."""
    name = type(exc).__name__
    if name == "FailSafeException":
        return HTTPException(
            status.HTTP_409_CONFLICT,
            detail="Desktop action cancelled: the mouse was moved to the failsafe corner.",
        )
    logger.error("Desktop action failed: %s", name)
    return HTTPException(
        status.HTTP_500_INTERNAL_SERVER_ERROR, detail="The desktop action failed on the host."
    )


def _type_text(text: str) -> None:
    """Type into the focused window. Non-ASCII text goes through the clipboard."""
    pyautogui = _pyautogui()
    # pyautogui applies PAUSE before every public call, and write() calls press() per
    # character: with the default pause, 4 000 characters would take minutes and time out.
    previous_pause = pyautogui.PAUSE
    pyautogui.PAUSE = 0
    try:
        if text.isascii():
            pyautogui.write(text, interval=TYPING_INTERVAL_S)
            return
        # pyautogui.write() cannot emit non-ASCII characters. Pasting is the reliable path
        # for Arabic, accented names, emoji, etc.
        try:
            import pyperclip  # optional dependency; see requirements_host.txt
        except ImportError as exc:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Non-ASCII text needs pyperclip: pip install -r requirements_host.txt",
            ) from exc
        pyperclip.copy(text)
        pyautogui.hotkey("ctrl", "v")
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise _gui_error(exc) from exc
    finally:
        pyautogui.PAUSE = previous_pause


def _press_hotkey(keys: list[str]) -> None:
    pyautogui = _pyautogui()
    try:
        pyautogui.hotkey(*keys)
    except Exception as exc:  # noqa: BLE001
        raise _gui_error(exc) from exc


def _whatsapp_mode() -> str:
    """``auto`` (pywhatkit if installed) or ``mock`` (never touch WhatsApp, report honestly)."""
    mode = os.environ.get("WHATSAPP_MODE", "auto").strip().lower()
    return "mock" if mode == "mock" else "auto"


def _send_whatsapp(phone: str, message: str) -> dict[str, Any]:
    """Send one WhatsApp message through WhatsApp Web via pywhatkit.

    Returns the response body. ``dispatched`` means pywhatkit's call returned control after
    submitting the message to WhatsApp Web; it is NOT a delivery receipt, and this bridge never
    claims one. If pywhatkit is missing or cannot drive a browser, nothing is sent and the body
    says so (HTTP 200, ``dispatched: false``), so the core can relay an honest answer.
    """
    if _whatsapp_mode() == "mock":
        return {
            "ok": True, "action": "whatsapp", "mode": "mock", "dispatched": False,
            "delivered": False, "phone": phone,
            "detail": "WHATSAPP_MODE=mock: draft validated, nothing was sent.",
        }
    try:
        import pywhatkit  # imported lazily: the GUI stack keeps working without it
    except Exception as exc:  # noqa: BLE001 - ImportError or a broken optional dependency
        logger.warning("pywhatkit unavailable: %s", type(exc).__name__)
        return {
            "ok": True, "action": "whatsapp", "mode": "mock", "dispatched": False,
            "delivered": False, "phone": phone,
            "detail": "pywhatkit is not installed on the host; nothing was sent. "
                      "Run: pip install -r requirements_host.txt",
        }

    if not _whatsapp_lock.acquire(timeout=5):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="Another WhatsApp send is in progress; try again in a moment.",
        )
    try:
        # sendwhatmsg_instantly opens WhatsApp Web and submits after wait_time. It raises
        # when the browser cannot be driven or the page does not load.
        pywhatkit.sendwhatmsg_instantly(
            phone, message, wait_time=WHATSAPP_WAIT_S, tab_close=True, close_time=3
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("WhatsApp send failed: %s", type(exc).__name__)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            detail=("WhatsApp Web could not be driven by pywhatkit. Check that the default "
                    "browser is logged in to web.whatsapp.com and try again."),
        ) from exc
    finally:
        _whatsapp_lock.release()

    logger.info("WhatsApp message submitted for %s (%d chars)", phone[-4:].rjust(4, "*"),
                len(message))
    return {
        "ok": True, "action": "whatsapp", "mode": "pywhatkit", "dispatched": True,
        "delivered": False, "phone": phone,
        "detail": "Submitted through WhatsApp Web. Delivery is not confirmed by the bridge.",
    }


def _expand(path: str) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(path)))


def _resolve_app(app_name: str) -> str | None:
    """Return something launchable for ``app_name`` (an exe, a .cmd, a path or a URI)."""
    raw = app_name.strip()
    key = raw.lower()

    # 1. An existing file/folder path: open it with the shell association.
    candidate = _expand(raw)
    if candidate.exists():
        return str(candidate)

    # 2. Friendly name -> real executable name.
    target = APP_ALIASES.get(key, key)
    if target.startswith("ms-settings:"):
        return target

    found = shutil.which(target)
    if found:
        return found

    # 3. Well-known install folders.
    for path in KNOWN_APP_PATHS.get(target, ()):
        resolved = _expand(path)
        if resolved.exists():
            return str(resolved)

    # 4. Let Windows resolve it through PATH/PATHEXT as a last try.
    fallback = shutil.which(raw)
    return fallback


def _spawn(executable: str) -> None:
    """Start an app detached from the bridge so it survives this process."""
    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    kwargs: dict[str, Any] = {
        "shell": False,
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if creationflags:
        kwargs["creationflags"] = creationflags

    if executable.lower().endswith((".cmd", ".bat")):
        # cmd.exe is required: CreateProcess cannot run a batch file directly.
        # The target is resolved from an allowlisted name or an existing path; never a shell string.
        subprocess.Popen(["cmd", "/c", executable], **kwargs)  # noqa: S603,S606,S607
    elif executable.startswith(("ms-settings:", "shell:", "http:", "https:")):
        if os.name == "nt":
            os.startfile(executable)  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["xdg-open", executable], **kwargs)  # noqa: S603,S607
    else:
        subprocess.Popen([executable], **kwargs)  # noqa: S603


def _open_app(app_name: str) -> str:
    target = _resolve_app(app_name)
    if target is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail=(
                f"Application '{app_name}' was not found. Try a full path or a known name "
                "such as 'code', 'chrome', 'notepad', 'explorer', 'calc'."
            ),
        )
    try:
        _spawn(target)
    except OSError as exc:
        logger.error("Could not launch app (%s): %s", app_name, type(exc).__name__)
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Windows could not start '{app_name}'.",
        ) from exc
    return target


# --- Screenshot / stats --------------------------------------------------------------------------
def _capture_screen(monitor: int) -> dict[str, Any]:
    """Grab one monitor and return it as base64 PNG (index 0 = all monitors, 1 = primary)."""
    try:
        with mss.mss() as sct:
            monitors = sct.monitors
            index = monitor if 0 <= monitor < len(monitors) else 1
            shot = sct.grab(monitors[index])
            png = mss.tools.to_png(shot.rgb, shot.size)
    except Exception as exc:  # noqa: BLE001 - locked screen, RDP session, driver issue
        logger.error("Screenshot failed: %s", type(exc).__name__)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The screen could not be captured. Is the session unlocked?",
        ) from exc

    return {
        "image_base64": base64.b64encode(png).decode("ascii"),
        "mime_type": "image/png",
        "width": shot.width,
        "height": shot.height,
        "monitor": index,
        "captured_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }


def _system_stats() -> dict[str, Any]:
    memory = psutil.virtual_memory()
    battery_percent: float | None = None
    battery_plugged: bool | None = None
    try:
        battery = psutil.sensors_battery()
    except Exception:  # noqa: BLE001 - some Windows/VM setups raise here
        battery = None
    if battery is not None:
        battery_percent = round(float(battery.percent), 1)
        battery_plugged = bool(battery.power_plugged)

    return {
        "cpu_percent": round(float(psutil.cpu_percent(interval=0.3)), 1),
        "ram_percent": round(float(memory.percent), 1),
        "ram_used_gb": round(memory.used / (1024 ** 3), 2),
        "ram_total_gb": round(memory.total / (1024 ** 3), 2),
        "battery_percent": battery_percent,
        "battery_plugged": battery_plugged,
        "cpu_cores": psutil.cpu_count(logical=True),
        "hostname": socket.gethostname(),
        "platform": f"{platform.system()} {platform.release()}",
        "collected_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }


# --- Routes --------------------------------------------------------------------------------------
protected = APIRouter(dependencies=[Depends(require_bridge_token)])


@protected.post("/action/type", tags=["actions"])
def action_type(payload: TypeRequest) -> dict[str, Any]:
    """Type ``text`` into the window that currently has focus."""
    _type_text(payload.text)
    logger.info("Typed %d characters", len(payload.text))
    return {"ok": True, "action": "type", "characters": len(payload.text)}


@protected.post("/action/hotkey", tags=["actions"])
def action_hotkey(payload: HotkeyRequest) -> dict[str, Any]:
    """Press a key combination, e.g. ``{"keys": ["ctrl", "c"]}`` or ``{"keys": ["win", "d"]}``."""
    _press_hotkey(payload.keys)
    logger.info("Pressed hotkey with %d key(s)", len(payload.keys))
    return {"ok": True, "action": "hotkey", "keys": payload.keys}


@protected.post("/action/open_app", tags=["actions"])
def action_open_app(payload: OpenAppRequest) -> dict[str, Any]:
    """Launch an application (``code``, ``chrome``, ``notepad``, or an absolute path)."""
    resolved = _open_app(payload.app_name)
    logger.info("Opened app %s", payload.app_name)
    return {"ok": True, "action": "open_app", "app": payload.app_name, "resolved": resolved}


@protected.post("/action/whatsapp", tags=["actions"])
def action_whatsapp(payload: WhatsAppRequest) -> dict[str, Any]:
    """Send a WhatsApp message through WhatsApp Web (pywhatkit), or report that nothing was sent.

    Body: ``{"phone": "+447700900123", "message": "..."}``. ``delivered`` is always false:
    the bridge submits the message but does not receive a delivery receipt.
    """
    result = _send_whatsapp(payload.phone, payload.message)
    logger.info("WhatsApp request for %s: dispatched=%s mode=%s",
                payload.phone[-4:].rjust(4, "*"), result["dispatched"], result["mode"])
    return result


@protected.get("/screenshot", tags=["capture"])
def screenshot(monitor: int = 1) -> dict[str, Any]:
    """Capture a monitor and return ``{"image_base64": "...", "mime_type": "image/png", ...}``."""
    if not 0 <= monitor <= 9:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="monitor must be 0-9")
    return _capture_screen(monitor)


@protected.get("/system_stats", tags=["capture"])
def system_stats() -> dict[str, Any]:
    """CPU, RAM and battery usage of the laptop."""
    return _system_stats()


app.include_router(protected)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Jarvis host control bridge.")
    parser.add_argument("--host", default=os.environ.get("HOST_BRIDGE_HOST", DEFAULT_HOST))
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("HOST_BRIDGE_PORT", DEFAULT_PORT)),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    args = _parse_args(argv)

    if sys.platform != "win32":
        logger.warning("This bridge is written for Windows; desktop control may not work here.")

    logger.info("Jarvis host bridge %s on %s:%d", APP_VERSION, args.host, args.port)
    logger.info("Token file: %s", _token_path())
    if _load_token() is None:
        logger.error(
            "No host token found. Create %s before starting Docker (see README).", _token_path()
        )
    if args.host not in ("127.0.0.1", "localhost", "::1"):
        logger.warning(
            "Listening on %s exposes desktop control to your network. Firewall it carefully.",
            args.host,
        )

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
