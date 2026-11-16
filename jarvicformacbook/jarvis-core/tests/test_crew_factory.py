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
