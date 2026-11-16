"""Tests for app.crew_factory. The real CrewAI/Ollama call (_kickoff) is always mocked."""

from __future__ import annotations

import threading

import pytest

from app import crew_factory
from app.crew_factory import CrewBusyError, CrewError, run_crew


DEMO_INTRO = (
    "I am Jarvis, your Chief of Staff. I was built to save your time and secure your business. "
    "I can find global tenders for you, draft highly personalized pitches based on your CV and "
    "45+ projects, analyze Etimad tenders, and manage your daily briefings. Most importantly, I "
    "operate 100% locally, ensuring absolute privacy. How can I assist you today, Boss?"
)


def test_demo_intro_is_exact():
    assert crew_factory.GREETING_REPLY == DEMO_INTRO


def test_returns_stripped_reply(monkeypatch):
    monkeypatch.setattr(crew_factory, "_kickoff", lambda message: "  Hi there \n")
    assert run_crew("hello") == "Hi there"


@pytest.mark.parametrize(
    "message",
    ["Hello Jarvis", "Hi", "hI!", "Are you there?", "Hello, Jarvis", "Good morning Jarvis"],
)
def test_greeting_returns_fixed_intro_without_running_crew(monkeypatch, message):
    def _unexpected(_message: str) -> str:
        raise AssertionError("a greeting must not reach the LLM")

    monkeypatch.setattr(crew_factory, "_kickoff", _unexpected)
    assert run_crew(message) == DEMO_INTRO


@pytest.mark.parametrize(
    "message",
    ["hello", "Hi Jarvis, find tenders for me", "Summarise today's tenders"],
)
def test_messages_that_are_not_only_greetings_reach_the_crew(monkeypatch, message):
    seen: list[str] = []
    monkeypatch.setattr(crew_factory, "_kickoff", lambda text: seen.append(text) or "ok")
    assert run_crew(message) == "ok"
    assert seen == [message]


def test_passes_message_through(monkeypatch):
    seen: list[str] = []
    monkeypatch.setattr(crew_factory, "_kickoff", lambda message: seen.append(message) or "ok")
    run_crew("Summarise {tender} please")
    assert seen == ["Summarise {tender} please"]


def test_reply_is_truncated_to_limit(monkeypatch):
    monkeypatch.setattr(crew_factory, "_kickoff", lambda message: "x" * 50_000)
    assert len(run_crew("hello")) == crew_factory.MAX_REPLY_CHARS


@pytest.mark.parametrize("output", ["", "   \n\t"])
def test_empty_reply_raises(monkeypatch, output):
    monkeypatch.setattr(crew_factory, "_kickoff", lambda message: output)
    with pytest.raises(CrewError):
        run_crew("hello")


def test_kickoff_failure_is_wrapped_and_lock_released(monkeypatch):
    def _boom(message: str) -> str:
        raise ConnectionError("ollama down")

    monkeypatch.setattr(crew_factory, "_kickoff", _boom)
    with pytest.raises(CrewError) as excinfo:
        run_crew("hello")
    assert not isinstance(excinfo.value, CrewBusyError)
    assert not crew_factory._crew_lock.locked()

    monkeypatch.setattr(crew_factory, "_kickoff", lambda message: "recovered")
    assert run_crew("hello") == "recovered"


def test_concurrent_call_is_rejected_as_busy(monkeypatch):
    started = threading.Event()
    release = threading.Event()

    def _slow(message: str) -> str:
        started.set()
        assert release.wait(5)
        return "first"

    monkeypatch.setattr(crew_factory, "_kickoff", _slow)
    results: list[str] = []
    worker = threading.Thread(target=lambda: results.append(run_crew("one")))
    worker.start()
    try:
        assert started.wait(5)
        with pytest.raises(CrewBusyError):
            run_crew("two")
    finally:
        release.set()
        worker.join(5)
    assert results == ["first"]
    assert not crew_factory._crew_lock.locked()


def test_kickoff_without_crewai_installed_fails_cleanly():
    # The host has no crewai: the lazy import must surface as CrewError, not ImportError.
    try:
        import crewai  # noqa: F401
    except ImportError:
        with pytest.raises(CrewError):
            run_crew("hello")
    else:
        pytest.skip("crewai installed; this test only covers the host environment")


class TestControlHostComputer:
    """The agent tool that drives the Windows laptop through the host bridge."""

    @pytest.fixture(autouse=True)
    def host_token(self, tmp_path, monkeypatch):
        token_file = tmp_path / "host_token.txt"
        token_file.write_text("host-secret\n", encoding="utf-8")
        monkeypatch.setenv("SECRETS_DIR", str(tmp_path))
        monkeypatch.setenv("HOST_BRIDGE_URL", "http://host.docker.internal:9090")
        return token_file

    @pytest.fixture
    def bridge(self, monkeypatch):
        state = {"calls": [], "status": 200, "payload": {"ok": True}, "error": None}

        class FakeResponse:
            def __init__(self) -> None:
                self.status_code = state["status"]

            def json(self):
                return state["payload"]

        def fake_request(method, url, **kwargs):
            state["calls"].append((method, url, kwargs))
            if state["error"] is not None:
                raise state["error"]
            return FakeResponse()

        monkeypatch.setattr(crew_factory.httpx, "request", fake_request)
        return state

    def test_open_app(self, bridge):
        result = crew_factory.control_host_computer("open_app", '{"app_name": "code"}')
        assert result == "Opened code on the laptop."
        method, url, kwargs = bridge["calls"][0]
        assert (method, url) == ("POST", "http://host.docker.internal:9090/action/open_app")
        assert kwargs["json"] == {"app_name": "code"}
        assert kwargs["headers"]["Authorization"] == "Bearer host-secret"
        assert kwargs["trust_env"] is False

    def test_hotkey_accepts_a_string_or_a_list(self, bridge):
        assert "Pressed win+d" in crew_factory.control_host_computer("hotkey", '{"keys": "win+d"}')
        assert bridge["calls"][0][2]["json"] == {"keys": ["win", "d"]}
        crew_factory.control_host_computer("press_hotkey", '{"keys": ["ctrl", "shift", "esc"]}')
        assert bridge["calls"][1][2]["json"] == {"keys": ["ctrl", "shift", "esc"]}

    def test_type_clips_long_text(self, bridge):
        long_text = "a" * (crew_factory.MAX_HOST_TYPE_CHARS + 50)
        result = crew_factory.control_host_computer(
            "type", '{"text": "' + long_text + '"}'
        )
        sent = bridge["calls"][0][2]["json"]["text"]
        assert len(sent) == crew_factory.MAX_HOST_TYPE_CHARS
        assert "truncated" in result

    def test_screenshot_reports_dimensions(self, bridge):
        bridge["payload"] = {"image_base64": "abc", "width": 1920, "height": 1080}
        result = crew_factory.control_host_computer("screenshot", "{}")
        assert "1920x1080" in result
        assert bridge["calls"][0][1].endswith("/screenshot?monitor=1")

    def test_stats_are_summarised_for_the_model(self, bridge):
        bridge["payload"] = {
            "cpu_percent": 12.5, "ram_percent": 40.0,
            "battery_percent": 88.0, "battery_plugged": True,
        }
        result = crew_factory.control_host_computer("stats", "{}")
        assert "CPU 12.5%" in result
        assert "RAM 40.0%" in result
        assert "charging" in result

    def test_unknown_action_does_not_call_the_bridge(self, bridge):
        result = crew_factory.control_host_computer("format_disk", "{}")
        assert "Unknown action" in result
        assert bridge["calls"] == []

    def test_invalid_params_json_is_explained(self, bridge):
        result = crew_factory.control_host_computer("open_app", "not json")
        assert "Invalid params" in result
        assert bridge["calls"] == []

    def test_unreachable_bridge_is_reported(self, bridge):
        bridge["error"] = crew_factory.httpx.ConnectError("no route")
        result = crew_factory.control_host_computer("stats", "{}")
        assert result.startswith("Host control failed:")
        assert "unreachable" in result

    def test_missing_token_is_reported(self, bridge, host_token):
        host_token.unlink()
        result = crew_factory.control_host_computer("stats", "{}")
        assert "not configured" in result
        assert bridge["calls"] == []

    def test_bridge_error_detail_is_passed_through(self, bridge):
        bridge["status"] = 404
        bridge["payload"] = {"detail": "Application 'nope' was not found."}
        result = crew_factory.control_host_computer("open_app", '{"app_name": "nope"}')
        assert "Application 'nope' was not found." in result
