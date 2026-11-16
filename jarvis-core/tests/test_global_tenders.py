"""Tests for the global tender feed, the CV chunker, the match/pitch guards and the pitch API.
 
Self-contained (own fixtures): no Ollama, ChromaDB, crewai or network needed.
"""
 
from __future__ import annotations
 
import json
import time
from datetime import UTC, date, datetime
 
import pytest
from fastapi.testclient import TestClient
 
from app import crew_factory, main, rag_setup
from app.global_tenders import MAX_BRIEF_CHARS, get_tender, list_tenders
from app.rag_setup import Evidence
 
TOKEN = "test-token"  # noqa: S105
AUTH = {"Authorization": f"Bearer {TOKEN}"}
 
CV = """JANE DOE
Chief Architect | Cloud | AI
London | +44 1234 567890 | jane@example.com
 
PROFESSIONAL SUMMARY
Architect with many years of delivery across AI and cloud.
 
FLAGSHIP PROJECTS
Tower Smart Building Platform | Acme Estates | 2025 – Present
Innovation Lead | IoT Architect
• Architect IoT glass devices with edge ML inference.
• Lead the formal patent filing with IP attorneys.
Tech: MQTT, Kubernetes
 
Voice Agent Platform | example.ai | 2025
Lead Engineer
• Build a voice AI platform scaling to 500+ concurrent calls.
 
PROFESSIONAL EXPERIENCE
Big Bank | London, UK | Oct 2022 – Aug 2023
Cloud Consultant | Lead Engineer
• Built a RAG pipeline over the regulatory knowledge base.
Big Bank | UK | Oct 2016 – Jun 2019
Full Stack Engineer
• Delivered banking apps.
 
PATENTS
• Smart-building IoT architecture (Tower Smart Building Platform). Patent filed.
 
EDUCATION & CERTIFICATIONS
• MSc Applied AI
• Cloud Architect | Solutions Architect | Kubernetes (CKA)
"""
 
 
def _ev(title: str, kind: str = "project", score: float = 0.8, text: str = "facts") -> Evidence:
    return Evidence(title=title, section="Flagship Projects", kind=kind, text=text,
                    score=score, subject="Jane Doe")
 
 
@pytest.fixture
def client(tmp_path, monkeypatch):
    (tmp_path / "core_api_token").write_text(TOKEN, encoding="utf-8")
    monkeypatch.setenv("SECRETS_DIR", str(tmp_path))
    main._pitch_cache.clear()
    return TestClient(main.app)
 
 
def _wait(client: TestClient, job_id: str) -> dict:
    for _ in range(100):
        body = client.get(f"/jobs/{job_id}", headers=AUTH).json()
        if body["status"] != "running":
            return body
        time.sleep(0.02)
    raise AssertionError("job did not finish")
 
 
# --- Sample tenders ----------------------------------------------------------------------------
def test_sample_tenders_cover_three_regions_and_are_labelled_mock():
    tenders = list_tenders(today=date(2026, 11, 12))
    assert [t.region for t in tenders] == ["UK", "USA", "EU"]
    assert all(t.is_mock and t.reference.startswith("DEMO-") for t in tenders)
    assert len({t.id for t in tenders}) == 3
 
 
def test_sample_deadlines_are_in_the_future_and_briefs_are_bounded():
    now = datetime(2026, 11, 12, 23, 59, tzinfo=UTC)
    for tender in list_tenders(today=now.date()):
        assert tender.submission_deadline > now
        assert tender.submission_deadline.tzinfo is not None
        assert 0 < len(tender.brief()) <= MAX_BRIEF_CHARS
 
 
def test_get_tender_unknown_id_is_none():
    assert get_tender("nope") is None
    assert get_tender("demo-us-001").region == "USA"
 
 
# --- CV chunker ---------------------------------------------------------------------------------
def test_parse_profile_makes_one_chunk_per_project_and_skips_contact_details(monkeypatch):
    monkeypatch.delenv("CEO_NAME", raising=False)
    chunks = rag_setup.parse_profile(CV, "boss_cv.txt")
    titles = [c.title for c in chunks]
    assert "Tower Smart Building Platform" in titles
    assert "Voice Agent Platform" in titles
    assert {c.subject for c in chunks} == {"Jane Doe"}
    joined = "\n".join(c.text for c in chunks)
    assert "+44 1234" not in joined and "jane@example.com" not in joined
    tower = next(c for c in chunks if c.title == "Tower Smart Building Platform")
    assert tower.kind == "project" and "patent filing" in tower.text and "500+" not in tower.text
 
 
def test_parse_profile_disambiguates_repeat_employers_and_keeps_plain_sections():
    chunks = rag_setup.parse_profile(CV, "boss_cv.txt")
    titles = [c.title for c in chunks]
    assert "Big Bank (Oct 2022 – Aug 2023)" in titles
    assert "Big Bank (Oct 2016 – Jun 2019)" in titles
    by_title = {c.title: c for c in chunks}
    assert by_title["Patents"].kind == "section"
    # A bulleted line containing " | " is not a project header.
    assert by_title["Education & Certifications"].kind == "section"
    assert all(len(c.text) <= rag_setup.MAX_CHUNK_CHARS for c in chunks)
    assert len({c.id for c in chunks}) == len(chunks)
 
 
def test_parse_profile_without_headings_falls_back_to_paragraphs(monkeypatch):
    monkeypatch.delenv("CEO_NAME", raising=False)
    chunks = rag_setup.parse_profile("Some notes about a project.\n\nMore notes here.", "portfolio.txt")
    assert chunks and all(c.kind == "section" and c.title == "Portfolio" for c in chunks)
    assert chunks[0].subject == rag_setup.DEFAULT_SUBJECT
 
 
def test_ceo_name_env_overrides_the_cv_first_line(monkeypatch):
    monkeypatch.setenv("CEO_NAME", "Dr Jane Doe")
    assert rag_setup.parse_profile(CV, "boss_cv.txt")[0].subject == "Dr Jane Doe"
 
 
def test_select_evidence_puts_projects_before_keyword_dense_sections():
    ranked = [_ev("Technical Skills", "section", 0.9), _ev("Core Competencies", "section", 0.88),
              _ev("A"), _ev("B"), _ev("C"), _ev("D")]
    chosen = rag_setup.select_evidence(ranked, 4)
    assert [e.title for e in chosen] == ["A", "B", "C", "Technical Skills"]
 
 
# --- Deterministic guards around the agents -------------------------------------------------------
def test_resolve_match_takes_the_agents_pick_when_it_is_a_retrieved_project():
    evidence = [_ev("Voice Agent Platform"), _ev("Tower Smart Building Platform")]
    out = "MATCH: Tower Smart Building Platform\nWHY: Edge ML and IoT glass fit the brief."
    assert crew_factory.resolve_match(out, evidence) == (
        "Tower Smart Building Platform", "Edge ML and IoT glass fit the brief.", "agent")
 
 
def test_resolve_match_falls_back_to_top_ranked_project_when_agent_names_none():
    evidence = [_ev("Technical Skills", "section"), _ev("Voice Agent Platform"), _ev("Tower")]
    project, rationale, source = crew_factory.resolve_match("MATCH: Project Apollo", evidence)
    assert (project, rationale, source) == ("Voice Agent Platform", "", "retrieval_fallback")
 
 
def test_resolve_match_never_picks_a_non_project_section_when_projects_exist():
    evidence = [_ev("Patents", "section"), _ev("Tower")]
    assert crew_factory.resolve_match("MATCH: Patents", evidence)[0] == "Tower"
 
 
def test_pitch_warnings_flag_missing_project_and_patent_overclaim():
    evidence = "Lead the formal patent filing. Patent filed."
    good = "Our CEO, Jane Doe, who led the patent filing for the Tower Smart Building Platform, proposes X."
    assert crew_factory.pitch_warnings(good, "Tower Smart Building Platform", evidence) == []
    bad = "Our CEO, who patented smart glass, proposes X."
    warnings = crew_factory.pitch_warnings(bad, "Tower Smart Building Platform", evidence)
    assert len(warnings) == 2
 
 
def test_run_pitch_crew_wires_retrieval_match_and_pitch(monkeypatch):
    evidence = [_ev("Voice Agent Platform", text="500+ concurrent calls"),
                _ev("Tower Smart Building Platform", text="edge ML, patent filing")]
    seen: dict[str, str] = {}
    monkeypatch.setattr(rag_setup, "retrieve", lambda query, k=4: evidence)
    monkeypatch.setattr(crew_factory, "_kickoff_match",
                        lambda tender, candidates: "MATCH: Tower Smart Building Platform\nWHY: fits.")
 
    def fake_pitch(tender, ceo_name, project, rationale, ev_text):
        seen.update(ceo=ceo_name, project=project, evidence=ev_text)
        return f"Our CEO, {ceo_name}, who led {project}, proposes a pilot."
 
    monkeypatch.setattr(crew_factory, "_kickoff_pitch", fake_pitch)
    result = crew_factory.run_pitch_crew("Title: smart buildings")
    assert result["matched_project"] == "Tower Smart Building Platform"
    assert result["match_source"] == "agent" and result["warnings"] == []
    assert seen["ceo"] == "Jane Doe"
    # The matched project's excerpt leads the pitch prompt.
    assert seen["evidence"].startswith("PROJECT: Tower Smart Building Platform")
    assert [e["title"] for e in result["evidence"]] == [e.title for e in evidence]
 
 
def test_run_pitch_crew_reports_missing_profile(monkeypatch):
    def boom(query, k=4):
        raise rag_setup.ProfileStoreError("empty")
 
    monkeypatch.setattr(rag_setup, "retrieve", boom)
    with pytest.raises(crew_factory.ProfileNotReadyError):
        crew_factory.run_pitch_crew("anything")
    assert crew_factory._crew_lock.acquire(blocking=False)  # lock was released
    crew_factory._crew_lock.release()
 
 
# --- API ----------------------------------------------------------------------------------------
@pytest.mark.parametrize("path", ["/global-tenders", "/api/global-tenders"])
def test_global_tenders_requires_token_and_is_marked_mock(client, path):
    assert client.get(path).status_code == 401
    resp = client.get(path, headers=AUTH)
    assert resp.status_code == 200
    body = resp.json()
    assert body["mode"] == "mock" and len(body["items"]) == 3
    assert {i["region"] for i in body["items"]} == {"UK", "USA", "EU"}
 
 
def test_pitch_endpoint_auth_and_unknown_tender(client):
    assert client.post("/global-tenders/demo-uk-001/pitch").status_code == 401
    assert client.post("/global-tenders/unknown/pitch", headers=AUTH).status_code == 404
    assert client.post("/global-tenders/bad..id/pitch", headers=AUTH).status_code == 422
    resp = client.post("/global-tenders/demo-uk-001/pitch", headers=AUTH, json={"nope": 1})
    assert resp.status_code == 422
 
 
def test_pitch_job_returns_json_reply_then_serves_cache_until_regenerate(client, monkeypatch):
    calls: list[str] = []
 
    def fake_run(brief: str) -> dict:
        calls.append(brief)
        return {"matched_project": "P", "match_source": "agent", "match_rationale": "r",
                "pitch": f"pitch {len(calls)}", "warnings": [], "evidence": []}
 
    monkeypatch.setattr(main, "run_pitch_crew", fake_run)
 
    first = client.post("/global-tenders/demo-eu-001/pitch", headers=AUTH)
    assert first.status_code == 202
    reply = json.loads(_wait(client, first.json()["job_id"])["reply"])
    assert reply["pitch"] == "pitch 1" and reply["cached"] is False
    assert reply["tender_id"] == "demo-eu-001" and "generated_at" in reply
    assert "Regulatory" in calls[0]  # the brief of the right tender reached the crew
 
    second = client.post("/global-tenders/demo-eu-001/pitch", headers=AUTH)
    reply = json.loads(_wait(client, second.json()["job_id"])["reply"])
    assert reply["pitch"] == "pitch 1" and reply["cached"] is True and len(calls) == 1
 
    third = client.post("/global-tenders/demo-eu-001/pitch", headers=AUTH, json={"regenerate": True})
    reply = json.loads(_wait(client, third.json()["job_id"])["reply"])
    assert reply["pitch"] == "pitch 2" and reply["cached"] is False
 
 
def test_pitch_job_error_message_for_missing_profile(client, monkeypatch):
    def boom(brief: str) -> dict:
        raise crew_factory.ProfileNotReadyError("x")
 
    monkeypatch.setattr(main, "run_pitch_crew", boom)
    job = client.post("/global-tenders/demo-us-001/pitch", headers=AUTH).json()
    done = _wait(client, job["job_id"])
    assert done["status"] == "error" and "boss_cv.txt" in done["error"]