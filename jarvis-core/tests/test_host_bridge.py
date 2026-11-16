"""Tests for the standalone Windows host bridge (``host_bridge.py``).

The bridge normally runs on the laptop with pyautogui/mss/psutil installed. Here those
packages are replaced with small fakes so the routing, authentication and payload handling
can be tested in the container without a desktop.
"""

from __future__ import annotations

import base64
import importlib.util
import sys
import types
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

HOST_BRIDGE_PATH = Path(__file__).resolve().parents[2] / "host_bridge.py"
TOKEN = "bridge-secret-123"  # noqa: S105 - a test fixture value, not a real credential
FAKE_PNG = b"\x89PNG\r\n\x1a\nfake-image-data"


def _install_fake_dependencies(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub the desktop-only packages before host_bridge.py is imported."""
    # --- pyautogui ---
    gui = types.ModuleType("pyautogui")
    gui.writes: list[tuple[str, float]] = []
    gui.hotkeys: list[tuple[str, ...]] = []

    class FailsafeError(Exception):
        pass

    gui.FAILSAFE = True
    gui.PAUSE = 0.0
    gui.FailSafeException = FailsafeError
    gui.write = lambda text, interval=0.0: gui.writes.append((text, interval))
    gui.hotkey = lambda *keys: gui.hotkeys.append(keys)

    # --- mss / mss.tools ---
    mss_module = types.ModuleType("mss")
    tools_module = types.ModuleType("mss.tools")

    class FakeShot:
        rgb = b"\x00\x00\x00"
        size = types.SimpleNamespace(width=1280, height=720)
        width = 1280
        height = 720

    class FakeSct:
        monitors = [
            {"left": 0, "top": 0, "width": 1280, "height": 720},
            {"left": 0, "top": 0, "width": 1280, "height": 720},
        ]

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

        def grab(self, _monitor):
            return FakeShot()

    mss_module.mss = FakeSct
    mss_module.tools = tools_module
    tools_module.to_png = lambda rgb, size, **_kwargs: FAKE_PNG

    # --- psutil ---
    psutil_module = types.ModuleType("psutil")

    class FakeMemory:
        percent = 40.0
        used = 8 * 1024 ** 3
        total = 16 * 1024 ** 3

    psutil_module.cpu_percent = lambda interval=None: 12.5
    psutil_module.virtual_memory = lambda: FakeMemory()
    psutil_module.sensors_battery = lambda: None
    psutil_module.cpu_count = lambda logical=True: 8

    monkeypatch.setitem(sys.modules, "pyautogui", gui)
    monkeypatch.setitem(sys.modules, "mss", mss_module)
    monkeypatch.setitem(sys.modules, "mss.tools", tools_module)
    monkeypatch.setitem(sys.modules, "psutil", psutil_module)


@pytest.fixture(scope="module")
def bridge():
    if not HOST_BRIDGE_PATH.is_file():
        pytest.skip("host_bridge.py is not present (core-only checkout)")

    # The desktop packages must be stubbed before host_bridge.py imports them.
    fake_env = pytest.MonkeyPatch()
    _install_fake_dependencies(fake_env)

    spec = importlib.util.spec_from_file_location("jarvis_host_bridge", HOST_BRIDGE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["jarvis_host_bridge"] = module
    spec.loader.exec_module(module)
    yield module
    fake_env.undo()


@pytest.fixture
def bridge_client(bridge, tmp_path, monkeypatch):
    """Point the bridge at a temp token file, as a real deployment would."""
    token_file = tmp_path / "host_token.txt"
    token_file.write_text(TOKEN + "\n", encoding="utf-8")
    monkeypatch.setenv("HOST_TOKEN_FILE", str(token_file))
    return TestClient(bridge.app, headers={"Authorization": f"Bearer {TOKEN}"})


@pytest.fixture
def fake_gui(bridge):
    gui = sys.modules["pyautogui"]
    gui.writes.clear()
    gui.hotkeys.clear()
    return gui


@pytest.fixture
def base_client(bridge):
    return TestClient(bridge.app)


def test_health_needs_no_token(base_client):
    resp = base_client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["service"] == "jarvis-host-bridge"


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("post", "/action/type", {"text": "hi"}),
        ("post", "/action/hotkey", {"keys": ["ctrl", "c"]}),
        ("post", "/action/open_app", {"app_name": "code"}),
        ("get", "/screenshot", None),
        ("get", "/system_stats", None),
    ],
)
def test_every_action_requires_the_token(base_client, method, path, body):
    call = getattr(base_client, method)
    resp = call(path, json=body) if body is not None else call(path)
    assert resp.status_code == 401


def test_missing_token_file_fails_closed(bridge, tmp_path, monkeypatch):
    monkeypatch.setenv("HOST_TOKEN_FILE", str(tmp_path / "absent.txt"))
    client = TestClient(bridge.app, headers={"Authorization": f"Bearer {TOKEN}"})
    assert client.get("/system_stats").status_code == 503


def test_type_writes_on_the_focused_window(bridge_client, fake_gui):
    resp = bridge_client.post("/action/type", json={"text": "Hello Boss"})
    assert resp.status_code == 200
    module = sys.modules["jarvis_host_bridge"]
    assert fake_gui.writes == [("Hello Boss", module.TYPING_INTERVAL_S)]


def test_type_uses_the_clipboard_for_non_ascii(bridge_client, fake_gui, monkeypatch):
    clipboard = types.ModuleType("pyperclip")
    clipboard.copied: list[str] = []
    clipboard.copy = clipboard.copied.append
    monkeypatch.setitem(sys.modules, "pyperclip", clipboard)

    resp = bridge_client.post("/action/type", json={"text": "مرحبا Boss"})
    assert resp.status_code == 200
    assert clipboard.copied == ["مرحبا Boss"]
    assert fake_gui.hotkeys == [("ctrl", "v")]


def test_hotkey_presses_the_combination(bridge_client, fake_gui):
    resp = bridge_client.post("/action/hotkey", json={"keys": ["win", "d"]})
    assert resp.status_code == 200
    assert fake_gui.hotkeys == [("win", "d")]


@pytest.mark.parametrize(
    "keys",
    [["ctrl", "del"], ["ctrl", "rm -rf"], [], ["ctrl", "alt", "shift", "win", "del", "x"]],
)
def test_hotkey_rejects_unknown_or_oversized_keys(bridge_client, fake_gui, keys):
    assert bridge_client.post("/action/hotkey", json={"keys": keys}).status_code == 422


def test_open_app_uses_the_resolver(bridge_client, monkeypatch):
    spawned: list[str] = []
    module = sys.modules["jarvis_host_bridge"]
    monkeypatch.setattr(module, "_resolve_app", lambda name: r"C:\Apps\Code.exe")
    monkeypatch.setattr(module, "_spawn", spawned.append)

    resp = bridge_client.post("/action/open_app", json={"app_name": "code"})
    assert resp.status_code == 200
    assert spawned == [r"C:\Apps\Code.exe"]
    assert resp.json()["app"] == "code"


def test_open_app_reports_unknown_apps(bridge_client, monkeypatch):
    module = sys.modules["jarvis_host_bridge"]
    monkeypatch.setattr(module, "_resolve_app", lambda name: None)
    resp = bridge_client.post("/action/open_app", json={"app_name": "doesnotexist"})
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


def test_screenshot_returns_base64_png(bridge_client):
    resp = bridge_client.get("/screenshot")
    assert resp.status_code == 200
    data = resp.json()
    assert data["mime_type"] == "image/png"
    assert base64.b64decode(data["image_base64"]) == FAKE_PNG
    assert (data["width"], data["height"]) == (1280, 720)


def test_system_stats_reports_cpu_ram_and_battery(bridge_client):
    resp = bridge_client.get("/system_stats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["cpu_percent"] == 12.5
    assert data["ram_percent"] == 40.0
    assert data["battery_percent"] is None
    assert data["cpu_cores"] == 8


@pytest.mark.parametrize(
    "body",
    [
        {"text": ""},
        {"text": "x" * 4001},
        {"text": "hi", "extra": 1},
        {"app_name": "code\nrm -rf /"},
        {"app_name": "..\\..\\windows\\system32\\cmd.exe"},
    ],
)
def test_invalid_payloads_are_rejected(bridge_client, body):
    if "app_name" in body:
        path = "/action/open_app"
    else:
        path = "/action/type"
    assert bridge_client.post(path, json=body).status_code == 422
