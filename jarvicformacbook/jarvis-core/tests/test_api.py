"""Tests for the FastAPI endpoints."""

import re
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

import app.main as main_module
from app.crew_factory import CrewBusyError, CrewError
from app.jobs import JobStore
from app.main import app


TOKEN = "test-token-123"


@pytest.fixture
def client() -> TestClient:
    """Client without credentials."""
    return TestClient(app)


@pytest.fixture
def secrets_dir(tmp_path, monkeypatch):
    """Point the app at a temp SECRETS_DIR holding a known core_api_token."""
    (tmp_path / "core_api_token").write_text(TOKEN + "\n", encoding="utf-8")
    monkeypatch.setenv("SECRETS_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture
def authed_client(secrets_dir) -> TestClient:
    """Client that sends a valid bearer token on every request."""
    return TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"})


def _payload(**overrides) -> dict:
    deadline = (datetime.now(UTC) + timedelta(days=30)).isoformat()
    body = {
        "opportunity_id": "T-100",
        "title": "Network upgrade",
        "buyer": "City Council",
        "submission_deadline": deadline,
        "requirements": [
            {
                "requirement_id": "R1",
                "description": "ISO 27001 certified",
                "gate_result": "pass",
                "confidence": 0.95,
                "evidence": [{"document_id": "tender.pdf", "page": 3}],
            }
        ],
    }
    body.update(overrides)
    return body


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["service"] == "jarvis-core"


class TestEvaluateTender:
    # Every test here runs with a valid token; auth itself is covered in TestEvaluateTenderAuth.
    @pytest.fixture
    def client(self, authed_client) -> TestClient:
        return authed_client

    def test_eligible(self, client):
        resp = client.post("/evaluate-tender", json=_payload())
        assert resp.status_code == 200
        data = resp.json()
        assert data["decision_status"] == "eligible_for_scoring"
        assert data["opportunity_id"] == "T-100"
        assert data["decision_reasons"]
        assert data["evaluated_at"]

    def test_reject_on_confident_fail(self, client):
        reqs = [
            {
                "requirement_id": "R1",
                "description": "Turnover > 1M",
                "gate_result": "fail",
                "confidence": 0.9,
                "evidence": [{"document_id": "financials.pdf"}],
            }
        ]
        resp = client.post("/evaluate-tender", json=_payload(requirements=reqs))
        assert resp.json()["decision_status"] == "reject"

    def test_investigate_on_unknown(self, client):
        reqs = [{"requirement_id": "R1", "description": "Security clearance"}]
        resp = client.post("/evaluate-tender", json=_payload(requirements=reqs))
        assert resp.json()["decision_status"] == "investigate"

    def test_human_review_when_no_requirements(self, client):
        resp = client.post("/evaluate-tender", json=_payload(requirements=[]))
        assert resp.json()["decision_status"] == "human_review"

    def test_past_deadline_rejects(self, client):
        past = (datetime.now(UTC) - timedelta(days=1)).isoformat()
        resp = client.post("/evaluate-tender", json=_payload(submission_deadline=past))
        assert resp.json()["decision_status"] == "reject"

    def test_no_deadline_is_allowed(self, client):
        resp = client.post("/evaluate-tender", json=_payload(submission_deadline=None))
        assert resp.status_code == 200
        assert resp.json()["decision_status"] == "eligible_for_scoring"

    @pytest.mark.parametrize(
        "overrides",
        [
            {"submission_deadline": "2026-12-01T12:00:00"},  # naive datetime
            {"opportunity_id": ""},  # blank required field
            {"unexpected_field": "x"},  # extra fields forbidden
            {"requirements": [{"requirement_id": "R1", "description": "d", "confidence": 2}]},
        ],
    )
    def test_invalid_payloads_return_422(self, client, overrides):
        resp = client.post("/evaluate-tender", json=_payload(**overrides))
        assert resp.status_code == 422

    def test_duplicate_requirement_ids_return_422(self, client):
        body = _payload()
        body["requirements"] = body["requirements"] * 2
        assert client.post("/evaluate-tender", json=body).status_code == 422

    def test_client_cannot_set_decision(self, client):
        # decision_status is output-only; supplying it is rejected, not trusted.
        resp = client.post("/evaluate-tender", json=_payload(decision_status="eligible_for_scoring"))
        assert resp.status_code == 422


class TestEvaluateTenderAuth:
    def test_missing_token_is_401(self, client, secrets_dir):
        resp = client.post("/evaluate-tender", json=_payload())
        assert resp.status_code == 401
        assert resp.headers["www-authenticate"] == "Bearer"

    def test_wrong_token_is_401(self, client, secrets_dir):
        resp = client.post("/evaluate-tender", json=_payload(),
                           headers={"Authorization": "Bearer wrong"})
        assert resp.status_code == 401

    def test_missing_secret_fails_closed(self, client, tmp_path, monkeypatch):
        monkeypatch.setenv("SECRETS_DIR", str(tmp_path))  # no token file
        resp = client.post("/evaluate-tender", json=_payload(),
                           headers={"Authorization": f"Bearer {TOKEN}"})
        assert resp.status_code == 503

    def test_invalid_payload_without_token_is_401_not_422(self, client, secrets_dir):
        # Auth runs before body validation, so anonymous callers learn nothing about the schema.
        resp = client.post("/evaluate-tender", json={"bogus": True})
        assert resp.status_code == 401


class TestRouteProtection:
    def test_health_needs_no_token(self, client, tmp_path, monkeypatch):
        # Docker's healthcheck calls /health without credentials, even if the secret is missing.
        monkeypatch.setenv("SECRETS_DIR", str(tmp_path))
        assert client.get("/health").status_code == 200

    @pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
    def test_api_docs_are_disabled(self, client, path):
        assert client.get(path).status_code == 404

    def test_every_route_except_health_requires_token(self, client, secrets_dir):
        # Guards against a future endpoint being registered on `app` instead of `protected`.
        for route in app.routes:
            if not isinstance(route, APIRoute) or route.path == "/health":
                continue
            for method in route.methods:
                resp = client.request(method, route.path.replace("{", "x").replace("}", ""))
                assert resp.status_code == 401, f"{method} {route.path} is not protected"


class TestChat:
    TOKEN = TOKEN

    @pytest.fixture(autouse=True)
    def fake_crew(self, monkeypatch):
        """Replace the real crew (Ollama, minutes on CPU) with a recorder, and give each test a
        fresh job store that runs jobs inline so results are ready on the next request."""
        calls: list[str] = []

        def _run(message: str) -> str:
            calls.append(message)
            return "Hello CEO"

        monkeypatch.setattr(main_module, "run_crew", _run)
        monkeypatch.setattr(main_module, "jobs", JobStore(
            describe_error=main_module._describe_job_error, spawn=lambda target: target()))
        return calls

    @pytest.fixture
    def deferred_jobs(self, monkeypatch):
        """Job store whose jobs stay 'running' until the test calls the captured targets."""
        pending: list = []
        monkeypatch.setattr(main_module, "jobs", JobStore(
            describe_error=main_module._describe_job_error, spawn=pending.append))
        return pending

    def _start(self, client, **overrides) -> dict:
        resp = client.post("/chat", json=self._body(**overrides), headers=self._auth())
        assert resp.status_code == 202, resp.text
        return resp.json()

    def _poll(self, client, job_id: str):
        return client.get(f"/jobs/{job_id}", headers=self._auth())

    def test_chat_returns_job_then_reply(self, client, secrets_dir, fake_crew):
        started = self._start(client, message="  What's new?  ")
        assert re.fullmatch(r"[0-9a-f]{32}", started["job_id"])
        resp = self._poll(client, started["job_id"])
        assert resp.status_code == 200
        assert resp.json() == {"job_id": started["job_id"], "status": "done",
                               "reply": "Hello CEO", "error": None}
        assert fake_crew == ["What's new?"]  # schema strips whitespace before the crew sees it

    def test_job_reports_running_until_finished(self, client, secrets_dir, deferred_jobs):
        started = self._start(client)
        assert started["status"] == "running" and started["reply"] is None
        assert self._poll(client, started["job_id"]).json()["status"] == "running"
        deferred_jobs.pop()()  # the background work completes
        assert self._poll(client, started["job_id"]).json()["status"] == "done"

    def test_second_chat_while_running_is_503(self, client, secrets_dir, deferred_jobs):
        self._start(client)
        resp = client.post("/chat", json=self._body(), headers=self._auth())
        assert resp.status_code == 503
        assert resp.headers["retry-after"] == "30"
        deferred_jobs.pop()()
        assert self._start(client)["status"] == "running"  # free again once the first is done

    def test_crew_not_called_without_token(self, client, secrets_dir, fake_crew):
        client.post("/chat", json=self._body())
        assert fake_crew == []

    def test_crew_failure_is_error_job_without_details(self, client, secrets_dir, monkeypatch):
        def _fail(message: str) -> str:
            raise CrewError("ollama exploded at http://ollama:11434")

        monkeypatch.setattr(main_module, "run_crew", _fail)
        data = self._poll(client, self._start(client)["job_id"]).json()
        assert data["status"] == "error" and data["reply"] is None
        assert data["error"] == "The AI model failed to respond. Please try again."
        assert "ollama" not in str(data)

    def test_crew_busy_inside_job_is_explained(self, client, secrets_dir, monkeypatch):
        def _busy(message: str) -> str:
            raise CrewBusyError("busy")

        monkeypatch.setattr(main_module, "run_crew", _busy)
        data = self._poll(client, self._start(client)["job_id"]).json()
        assert data["status"] == "error" and "earlier request" in data["error"]

    def test_unknown_job_is_404(self, client, secrets_dir):
        assert self._poll(client, "0" * 32).status_code == 404

    @pytest.mark.parametrize("job_id", ["abc", "G" * 32, "0" * 33, "..%2F..%2Fhealth"])
    def test_malformed_job_id_is_rejected(self, client, secrets_dir, job_id):
        assert self._poll(client, job_id).status_code in (404, 422)

    def test_jobs_endpoint_requires_token(self, client, secrets_dir, fake_crew):
        job_id = self._start(client)["job_id"]
        resp = client.get(f"/jobs/{job_id}")
        assert resp.status_code == 401

    @staticmethod
    def _body(**overrides) -> dict:
        body = {"message": "Hello Jarvis", "conversation_id": "a" * 32}
        body.update(overrides)
        return body

    def _auth(self, token: str | None = None) -> dict:
        return {"Authorization": f"Bearer {token or self.TOKEN}"}

    def test_missing_token_is_401(self, client, secrets_dir):
        resp = client.post("/chat", json=self._body())
        assert resp.status_code == 401
        assert resp.headers["www-authenticate"] == "Bearer"

    def test_wrong_token_is_401(self, client, secrets_dir):
        resp = client.post("/chat", json=self._body(), headers=self._auth("nope"))
        assert resp.status_code == 401

    def test_non_bearer_scheme_is_401(self, client, secrets_dir):
        resp = client.post("/chat", json=self._body(), headers={"Authorization": f"Basic {self.TOKEN}"})
        assert resp.status_code == 401

    def test_missing_secret_fails_closed(self, client, tmp_path, monkeypatch):
        monkeypatch.setenv("SECRETS_DIR", str(tmp_path))  # no token file
        resp = client.post("/chat", json=self._body(), headers=self._auth())
        assert resp.status_code == 503

    def test_empty_secret_fails_closed(self, client, tmp_path, monkeypatch):
        (tmp_path / "core_api_token").write_text("  \n", encoding="utf-8")
        monkeypatch.setenv("SECRETS_DIR", str(tmp_path))
        resp = client.post("/chat", json=self._body(), headers={"Authorization": "Bearer "})
        assert resp.status_code == 503

    @pytest.mark.parametrize(
        "overrides",
        [
            {"message": ""},
            {"message": "   "},
            {"message": "x" * 4001},
            {"conversation_id": "bad id!"},
            {"conversation_id": "a" * 65},
            {"extra": "field"},
        ],
    )
    def test_invalid_body_is_422(self, client, secrets_dir, overrides):
        resp = client.post("/chat", json=self._body(**overrides), headers=self._auth())
        assert resp.status_code == 422


class TestVoiceProxy:
    @pytest.fixture
    def fake_voice(self, monkeypatch):
        """Replace httpx.post so the tests never need a running voice container."""
        state = {
            "calls": [],
            "status": 200,
            "payload": {"text": "Hello Jarvis"},
            "content": b"RIFFfake",
        }

        class FakeResponse:
            def json(self):
                if state["payload"] is None:
                    raise ValueError("no json")
                return state["payload"]

        def fake_post(url, **kwargs):
            state["calls"].append((url, kwargs))
            return type(
                "Response",
                (),
                {"status_code": state["status"], "content": state["content"], "json": FakeResponse.json},
            )()

        monkeypatch.setattr(main_module.httpx, "post", fake_post)
        return state

    def test_transcribe_proxies_to_stt_and_returns_text(self, authed_client, fake_voice):
        resp = authed_client.post(
            "/api/voice/transcribe",
            files={"file": ("clip.wav", b"audio-bytes", "audio/wav")},
        )
        assert resp.status_code == 200
        assert resp.json() == {"text": "Hello Jarvis"}
        url, kwargs = fake_voice["calls"][0]
        assert url == "http://voice:8000/stt"
        assert kwargs["trust_env"] is False
        assert kwargs["files"]["file"][0] == "clip.wav"
        assert kwargs["files"]["file"][1] == b"audio-bytes"

    def test_synthesize_proxies_to_tts_and_returns_wav(self, authed_client, fake_voice):
        resp = authed_client.post("/api/voice/synthesize", json={"text": "Good morning"})
        assert resp.status_code == 200
        assert resp.content == b"RIFFfake"
        assert resp.headers["content-type"].startswith("audio/wav")
        url, kwargs = fake_voice["calls"][0]
        assert url == "http://voice:8000/tts"
        assert kwargs["json"] == {"text": "Good morning"}

    def test_transcribe_upstream_failure_is_502(self, authed_client, fake_voice):
        fake_voice["status"] = 500
        resp = authed_client.post(
            "/api/voice/transcribe", files={"file": ("clip.wav", b"x", "audio/wav")}
        )
        assert resp.status_code == 502

    def test_synthesize_rejects_empty_text(self, authed_client, fake_voice):
        assert authed_client.post("/api/voice/synthesize", json={"text": ""}).status_code == 422

    def test_voice_endpoints_require_token(self, client, secrets_dir, fake_voice):
        assert client.post(
            "/api/voice/transcribe", files={"file": ("clip.wav", b"x", "audio/wav")}
        ).status_code == 401
        assert client.post("/api/voice/synthesize", json={"text": "x"}).status_code == 401
