# CLAUDE.md — Jarvis Project Memory

Read this first in every session. It records what Jarvis is, how the repo is laid out,
the rules the code follows, and how to test and build safely. Keep it current: when a
decision changes, update this file in the same change.

---

## 1. Project overview

**Jarvis** is a privacy-first, self-hosted AI assistant built as a **6-agent CrewAI system**
running entirely on a **16 GB, CPU-only Windows machine** via Docker. Its first business
capability is **public-tender evaluation**: find tenders (SAM.gov, TED/EU, Etimad/Saudi),
extract requirements, check mandatory eligibility gates, score opportunities, and export
results for human review. Email (Gmail), contract tools, a file sandbox, voice and a web UI
are planned around this core.

- **Owner:** Awais (Backend & Infrastructure Engineer).
- **Core principle:** LLM agents *propose*; deterministic code *decides*. Bid/no-bid routing
  is made by the rule-based gate engine (`jarvis-core/app/gate_engine.py`), never by an LLM.
- **Security posture:** local models only (Ollama), no cloud LLM calls, internet only through
  an allowlisting proxy, non-root read-only containers, secrets as Docker secrets.
- **Development is in "loops":** Loop 1 (Ollama + secrets + compose hardening) is tested.
  Loop 2 (in progress) = `jarvis-core` FastAPI service, schemas, gate engine, CSV export,
  Dockerfile. Later loops: CrewAI agents, tools, UI, voice.

> **TODO (ask Awais):** names/roles of the 6 agents, scoring criteria after gates, target
> tender portals per region, and who consumes the CSV exports. Record answers here.

---

## 2. Repository layout (`D:\Jarvis`)

```
jarvis-core/            FastAPI service — the brain (Loop 2)
  app/
    schemas.py          Pydantic v2 contracts (GateResult, DecisionStatus, EvidenceRef,
                        Requirement, TenderEvaluationRequest, OpportunityAssessment, GateEvaluation)
    gate_engine.py      Deterministic mandatory-gate rules
    output_manager.py   CSV export with formula-injection protection, atomic writes
    main.py             FastAPI app: GET /health, POST /evaluate-tender, POST /chat (202 + job_id), GET /jobs/{id},
                        POST /api/voice/transcribe|synthesize (proxy to the voice container),
                        POST /api/host/type|hotkey|open_app and GET /api/host/screenshot|stats
                        (proxy to the native Windows host bridge); all but /health need the bearer token
    jobs.py             In-memory JobStore: background threads, 1 running job, 900 s timeout, 1 h TTL, 200 max
    crew_factory.py     run_crew(): single-agent CrewAI chat crew ("Chief of Staff") on MANAGER_MODEL via Ollama
                        (one run at a time); tools: Etimad listings + control_host_computer. Greetings return
                        the fixed demo intro in code, without an LLM call
    etimad_tool.py      CrewAI tools on scrapers/etimad.py: etimad_tender_listings (live, via proxy) and
                        etimad_sample_listings (@tool, parses app/test/etimad_sample.html → compact JSON)
    scrapers/           Ekremah's Etimad listing scraper (bs4); its own tests sit in scrapers/, outside tests/
  tests/                pytest suite (conftest + 7 test modules, 159 tests)
  scripts/setup_secrets.py   Stdlib-only secrets bootstrap (never overwrites existing files)
  Dockerfile, .dockerignore, requirements.txt, requirements-dev.txt
jarvis-docker/          docker-compose.yml, nginx.conf (edge), squid.conf (egress allowlist), .env
jarvis-tools/           email / contracts / files tool services (not built yet)
jarvis-ui/              Streamlit CEO dashboard (app.py, Dockerfile, requirements.txt). Listens on
                        3000 (internal; edge proxies "/" → ui:3000). Browser: http://127.0.0.1:8080.
                        Login (ui_password secret), chat → core /chat then polls /jobs/{id} every 3 s (job id kept
                        in session_state["chat_pending"], input disabled meanwhile), approvals → core /approvals,
                        leads → core /leads. A recording from st.audio_input goes to core's /api/voice/transcribe,
                        the transcript goes through /chat, and the reply is spoken via /api/voice/synthesize.
jarvis-voice/           local STT/TTS service: /health, /stt (whisper.cpp) and /tts (Piper) on voice:8000;
                        CPU only, one job at a time, models baked into the image
host_bridge.py          Native Windows FastAPI bridge (NOT in Docker) on 127.0.0.1:9090: /action/type,
                        /action/hotkey, /action/open_app, /screenshot, /system_stats. Bearer token from
                        secrets/host_token.txt; pyautogui + mss + psutil. requirements_host.txt installs it.
package_for_mac.py      Builds jarvicformacbook/ (relative-path compose, macOS .command launchers)
jarvicformacbook/       Generated Mac package. Contains a copy of secrets/ — never commit or share it.
data/                   host bind-mount data: ollama/ (models), audit/, core/ (unused), voice/
secrets/                Docker secret files — NEVER read, print, copy or commit (except the explicit Mac package)
logs/
.claude/                commands/check.md (/check), agents/python-reviewer.md,
                        skills/docker-deploy/SKILL.md (build/run/Ollama checklist)
```

Lint with `py -m ruff check app tests` from `jarvis-core` (config in `jarvis-core/ruff.toml`;
ruff is in `requirements-dev.txt`).

`jarvis-docker/.env` sets `JARVIS_HOME=C:/Users/awais/Desktop/Jarvis` and
`SANDBOX=C:/Users/awais/Desktop/Jarvis_Sandbox`.

---

## 3. Tech stack

| Layer | Choice | Notes |
|---|---|---|
| Language | Python 3.11 in containers (host has 3.12 via `py`) | Code must run on 3.11 |
| API | FastAPI + uvicorn[standard] | Exec-form CMD, uvicorn is PID 1 |
| Validation | Pydantic v2 | `extra="forbid"`, bounded sizes, `AwareDatetime` |
| Agents | CrewAI | Uses LiteLLM under the hood for Ollama |
| Vector store | ChromaDB (embedded, persistent at `/data/chroma`) | Embeddings via Ollama, not the default ONNX model |
| LLM runtime | Ollama (`ollama/ollama`), CPU only | Manager `qwen2.5:7b`, worker `llama3.2:3b`, embed `nomic-embed-text` |
| Edge | nginx 1.27-alpine on `127.0.0.1:8080` | `/api/`, `/ws/` → core:8000; `/` → ui:3000 (Streamlit) |
| UI | Streamlit (+ httpx, pandas) | CEO dashboard; talks to core over `backend` only |
| Egress | Squid exact-domain HTTPS allowlist | Google APIs, SAM.gov, TED, Etimad only |
| Tests | pytest + httpx (FastAPI TestClient) | Dev-only deps |

Third-party libraries in app code: only what is in `requirements.txt`. Ask before adding any.

---

## 4. Architecture & runtime topology

- **Networks:** `backend` is `internal: true` (no internet). `egress` is used only by `proxy`
  (runtime) and `ollama-pull` (setup profile). `frontend` faces the host via `edge`.
  `hostlink` is a plain bridge used only by `core`, so it can reach `host.docker.internal`
  (host_bridge.py on the laptop). Docker internal networks cannot resolve or route to the host.
- **Internet access** for app services happens only via `HTTP(S)_PROXY=http://proxy:3128`
  (`x-proxy-env` anchor). `NO_PROXY` covers all internal service names, including `ollama`.
  `tool-files`, `voice` and `ui` get no proxy at all.
- **Profiles:** `ollama` runs by default. Everything else is `profiles: ["app"]`.
  The model puller is `profiles: ["setup"]`.
- **`x-hardened` anchor (apply to every service):** `user: "10001:10001"`, `read_only: true`,
  `cap_drop: [ALL]`, `no-new-privileges:true`, `restart: unless-stopped`. Writable paths are
  only volumes and `tmpfs` mounts.
- **core service:** builds `../jarvis-core` → image `jarvis-core:local`; `mem_limit: 2g`,
  `memswap_limit: 2g`; named volume `jarvis_data:/data`; nested bind
  `${JARVIS_HOME}/data/audit:/data/audit` (audit logs stay on the host); tmpfs `/tmp:256m`;
  depends on healthy `ollama`.

### Gate engine decision rules (do not change without Awais's sign-off)
Precedence, highest wins: **reject > human_review > investigate > eligible_for_scoring**.
- Confident mandatory FAIL (confidence ≥ 0.75 **and** ≥1 evidence ref) → `reject`.
- Submission deadline ≤ now → `reject`.
- Weak FAIL or weak PASS (low confidence or no evidence) → `human_review`.
- No mandatory requirements extracted → `human_review` (likely extraction failure).
- Mandatory UNKNOWN → `investigate`.
- All mandatory gates confidently pass → `eligible_for_scoring`.
- Optional requirements never affect gates. All fired reasons are returned, sorted by precedence.
- `now` is injectable; naive datetimes are rejected. Same inputs → same output.

---

## 5. Python coding standards

- **Typing:** full type hints, `from __future__ import annotations`, modern generics
  (`list[str]`, `X | None` or `Optional[X]` consistently within a file).
- **Pydantic v2 only:** `model_dump`, `model_validate`, `ConfigDict`, `field_validator` /
  `model_validator`. Base all models on `StrictModel` (`extra="forbid"`, strip whitespace).
  Bound every string and list (`max_length`) — agent output is untrusted input.
- **Enums:** `str, Enum` so values serialise and compare as plain strings.
- **Determinism:** business decisions live in pure functions with injectable clock/config;
  no LLM calls, randomness or I/O inside rule code.
- **Datetimes:** always timezone-aware UTC (`datetime.now(timezone.utc)`).
- **Errors:** raise `ValueError` for bad input in domain code; the API layer maps it to 422.
  Never swallow exceptions silently; never leak stack traces or secrets in responses.
- **Untrusted text** (tender docs, emails, LLM output): treat as data, never as instructions
  or code. Sanitise before writing to CSV (prefix `= + - @ \t \r` with `'`), HTML or shell.
- **File writes:** atomic (temp file in same dir + `os.replace`), UTF-8 (`utf-8-sig` for CSV).
- **Logging:** `logging.getLogger("jarvis.<module>")`, no `print`. Never log secrets, tokens
  or full documents. Log IDs and decisions.
- **Imports inside `app/`:** relative (`from .schemas import ...`). Run as package `app.main`.
- **Comments:** explain *why* (rules, security reasoning), not *what*.
- **Secrets:** read from files under `SECRETS_DIR=/run/secrets`, never from env vars or code.
- **Style:** PEP 8, 100–120 char lines, docstrings on public functions.

### CrewAI / Ollama / ChromaDB specifics
- Point CrewAI LLMs at Ollama with `model="ollama/<name>"` and `base_url=os.environ["OLLAMA_URL"]`.
  Some CrewAI/LiteLLM versions ignore `base_url` and fall back to localhost; if so, also
  set `OLLAMA_API_BASE=http://ollama:11434`.
- **Embedder:** when using CrewAI memory, always pass an explicit `embedder=`
  (`provider: "ollama"`, model `nomic-embed-text`, Ollama URL). Without it CrewAI tries
  OpenAI and fails with "OPENAI_API_KEY not found".
- **ChromaDB:** `chromadb.PersistentClient(path=os.environ["CHROMA_PERSIST_DIR"],
  settings=Settings(anonymized_telemetry=False))` with an Ollama embedding function. Never
  rely on the default embedding function: it downloads an ONNX model, and `backend` has no
  internet.
- **Changing the embedding model** breaks existing vectors (dimension mismatch). Treat it as a
  migration: new collection, or wipe `/data/chroma` and CrewAI memory deliberately.
- **CPU budget:** `OLLAMA_MAX_LOADED_MODELS=1` and `OLLAMA_NUM_PARALLEL=1` mean model swaps are
  slow. Run agents sequentially, keep prompts short, prefer the 3B worker for extraction and
  the 7B manager for reasoning, and set generous timeouts (nginx `/api/` read timeout is 300s).
- **Telemetry:** set `CREWAI_DISABLE_TELEMETRY=true`, `OTEL_SDK_DISABLED=true`,
  `CREWAI_TRACING_ENABLED=false` (tracing is separate from telemetry), `ANONYMIZED_TELEMETRY=False`.
  Set them as real environment variables (Dockerfile/compose), not just in a `.env` read by the app.

---

## 6. Docker best practices (project rules)

- **Base image:** `python:3.11-slim`, pinned by digest in `jarvis-core/Dockerfile`. When you bump
  it, rebuild and re-test before changing the digest.
- **Layer order:** copy deps file → `pip install` → copy `app/`. The core image installs
  `requirements.lock` (exact freeze), never `requirements-dev.txt`. Tests are not copied in.
  To upgrade deps: edit `requirements.txt` ranges, build once from it, run the tests, then
  regenerate the lock with `docker run --rm --entrypoint pip jarvis-core:local freeze`.
- **Non-root:** UID/GID 10001, no shell, no home (`HOME=/tmp`). `/data` is pre-created and
  chowned to 10001 so new named volumes inherit the right owner.
- **Read-only rootfs:** anything that writes must target `/data` (volume) or `/tmp` (tmpfs).
  XDG cache/config → `/tmp`, XDG data → `/data/xdg`, `CREWAI_STORAGE_DIR=/data/crewai`,
  `CHROMA_PERSIST_DIR=/data/chroma`, `PYTHONDONTWRITEBYTECODE=1`.
- **Memory budget (16 GB host):** every service has `mem_limit` = `memswap_limit` (no swap):
  ollama 6g, core 2g, voice 1g (placeholder), ui 512m, tool-* 256m each, proxy 128m, edge 64m,
  ollama-pull 1g. The app-profile ceiling totals ~10.4 GiB. tmpfs mounts count against a
  container's limit. New services must get an explicit limit.
- **WSL2 VM size:** with no `C:\Users\awais\.wslconfig`, Docker Desktop gets ~50% of RAM (~8 GB).
  That's enough for ollama + core, but not the full app profile. Recommended `.wslconfig`:
  `[wsl2]` `memory=12GB` `swap=4GB` (Awais applies it himself, then runs `wsl --shutdown`).
- **Environment variables:** non-secret config via compose `environment:` with defaults
  (`${MANAGER_MODEL:-qwen2.5:7b}`). Secrets only via `secrets:`. Never bake secrets or `.env`
  into images (`.dockerignore` excludes `.env`, `*.key`, `scripts/`).
- **Health checks:** every long-running service has one. slim images have no curl, so use
  `python -c "urllib.request..."`.
- **Build context paths:** relative to the compose file (`../jarvis-core`).
- **Networking:** new services join `backend` only, unless they truly need egress, in which
  case add `x-proxy-env` and the domain to `squid.conf` (exact host, HTTPS only).
- **Image tags:** avoid `:latest` in production. `ollama/ollama:latest` is flagged to pin;
  `ubuntu/squid` is pinned by digest.

---

## 7. How to work in this repo (behaviour for future sessions)

### Environment quirks
- Windows 11. Use `py` (Python 3.12), **not** `python` (that hits the Microsoft Store stub).
- Shell tools: Git Bash and PowerShell. Give the user commands in **Windows CMD** form when they
  will run them, e.g. `cd /d D:\Jarvis\jarvis-docker`.
- Not a git repo yet. Don't run `git init` or commit unless asked.

### Running tests (always after changing `jarvis-core/app`)
```
cd D:\Jarvis\jarvis-core
py -m pytest tests -q
```
- Expect all tests to pass. Report failures with output; never delete or weaken a test to
  make it pass.
- Deprecation warnings from httpx about the `app` shortcut come from FastAPI 0.110 on the
  host. They are harmless.
- New logic needs tests: gate rules (including precedence), schema limits, CSV injection
  cases, API status codes. Use `conftest.py` fixtures (`make_req`, fixed `now`).
- The host lacks `crewai`/`chromadb`. Tests for agent code must mock Ollama/LLM calls and
  must not need network access.

### Validating Docker config (safe, no side effects)
```
cd D:\Jarvis\jarvis-docker
docker compose --profile app config
```

### Building images: ask first
- **Do not run `docker build`, `docker compose build/up/run/pull`, or `ollama pull` without
  Awais's explicit go-ahead.** He reviews files before builds. Give him the command instead:
  ```
  cd /d D:\Jarvis\jarvis-docker
  docker compose --profile app build --progress=plain core
  ```
- Never run `docker compose down -v`, `docker volume rm`, or delete `data/` (models, audit
  logs, ChromaDB). Confirm before any destructive action.
- Never use the `setup` profile (internet-connected puller) unless asked.

### Secrets and safety
- Never read, print, copy or modify files in `D:\Jarvis\secrets\`. Refer to them by name only.
- `setup_secrets.py` must never overwrite existing files. `--rotate` touches generated secrets
  only.
- Don't widen the Squid allowlist, publish new host ports, or remove hardening settings
  without stating the security trade-off and getting approval.

### Change discipline
- Do what was asked. Propose extras instead of silently adding them, and flag any deviation
  from the request in the summary.
- When compose, Dockerfile or the architecture changes, update this file.
- Keep summaries short: what changed, what was verified, what needs Awais's decision.

---

## 8. Open items / known TODOs
- Fill in the 6 agents' roles (section 1).
- `/chat` is asynchronous since 2026-11-09: returns 202 + job_id, UI polls `GET /jobs/{id}` (gives up after
  `CHAT_MAX_WAIT_SECONDS`=960). One CrewAI agent, `MANAGER_MODEL` at `OLLAMA_URL`, Etimad tools, no memory,
  stateless per message (no conversation history yet). Crew budget: 300 s per LLM call, 840 s per run, job
  timeout 900 s. A second chat while one runs gets 503 + Retry-After. Jobs are in memory: lost on core restart
  (UI shows "lost track… send it again"); a timed-out run's thread can't be killed and keeps the model busy.
  `WORKER_MODEL`/`EMBED_MODEL` are still unused.
- Done 2026-11-09: `jarvis-core/requirements.lock` (138 pkgs; crewai 1.15.37, chromadb 1.5.9,
  fastapi 0.162.2) is installed by the core Dockerfile, and the base image is pinned by digest.
  jarvis-ui has no lock yet; freeze one after its first verified build.
- Pin `ollama/ollama` tag. `ubuntu/squid` is pinned by digest in compose since 2026-11-09 (Squid 6.13).
- Proxy running since 2026-11-09. squid.conf fixes for Squid 6 in a hardened container:
  `max_filedescriptors 1024` (Docker's ~1M nofile limit made Squid OOM at 128 MB, exit 137),
  removed obsolete `dns_v4_first`, `pinger_enable off` (no CAP_NET_RAW). Verified: Etimad CONNECT
  allowed, example.com → 403.
- Etimad public listing (`tenders.etimad.sa`, added to the allowlist 2026-11-09) is behind F5 BIG-IP
  bot protection (TSPD JS challenge + CAPTCHA), so the live tool gets no tender cards. Do NOT try to
  bypass it. Legitimate route: Etimad's official API (`apiportal.etimad.sa`, already allowlisted;
  `etimad_api_key` secret is still a placeholder). Meanwhile use the offline sample tool.
  `etimad_tool.is_bot_challenge()` spots the interstitial by its visible text (not `/TSPD/`, which F5
  also injects into real pages), and the tool then reports "Etimad blocked automated access".
- `beautifulsoup4==4.15.0` + `soupsieve==2.8.4` were appended to requirements.lock by hand (not a full
  re-resolve); the image's `pip freeze` was verified identical to the lock and `pip check` passed.
- Chat agent hallucinated context it doesn't have (e.g. invented "yesterday's meeting notes"). Added
  "If you don't know the answer, say so rather than guessing." to the backstory 2026-11-09; re-check.
- `app/scrapers/test_scraper_etimad.py` is in `app/` (shipped in the image, not run by `pytest tests`).
  Move it to `tests/`.
- API auth (2026-11-09): every core route except `GET /health` requires
  `Authorization: Bearer <core_api_token>` (constant-time compare; 503 if the secret is missing).
  Register new endpoints on the `protected` router in `main.py`, never on `app`; a test fails
  otherwise. `/docs`, `/redoc` and `/openapi.json` are disabled.
- UI wiring done 2026-11-09: Streamlit listens on 3000 (matches nginx); compose secret
  `ui_password` → `secrets/ui_password.txt`, created by hand (setup_secrets.py doesn't generate
  it). CSP left strict: Streamlit 1.67 only has one harmless inline script (prerender hint).
- Voice done 2026-11-14: `voice` implements `/stt` (whisper.cpp base.en + ffmpeg) and `/tts`
  (Piper en_US-lessac-medium), serialised with a non-blocking lock. Core proxies them as
  `/api/voice/*` with the bearer token. UI upload limit raised to 10 MB to match nginx. The
  voice reply is stored on the newest chat message only, so session state does not accumulate WAV.
- Greeting done 2026-11-14: `crew_factory.is_greeting()` returns the fixed CEO-demo intro in code
  for "Hello Jarvis", "Hi", "Are you there?" and similar; a greeting carrying a request still
  reaches the crew.
- Mac package 2026-11-14: `package_for_mac.py` generates `jarvicformacbook/` with relative compose
  paths, `data/` folders, three `.command` launchers and `README_FOR_BOSS.md`. It copies `secrets/`
  on purpose for the demo — treat the package as sensitive and rotate credentials if it leaks.
- Host control done 2026-11-14: `host_bridge.py` runs natively on Windows (pyautogui/mss/psutil,
  token `secrets/host_token.txt`), core proxies it as `/api/host/*`, the chat crew has
  `control_host_computer`, and the UI has a "Remote Control" tab. `core` joins the `hostlink`
  network because `backend` (internal) cannot resolve or reach `host.docker.internal`.
  The bridge cannot type into elevated (Administrator) windows unless it runs elevated.
- Core endpoints still missing: `GET /approvals`, `POST /approvals/{id}/approve|reject`,
  `GET /leads`.
- `jarvis-core/app/test/etimad_sample.html` must stay in `app/` while the offline sample tool exists
  (it ships in the image; a test pins the path). Its 3.5 MB `etimad_sample_files/` (saved browser
  assets) is excluded via `.dockerignore`.
- Upgrade host FastAPI (0.110) to match the container version and clear test warnings.
