---
name: docker-deploy
description: Checklist for building the Jarvis core Docker image, running it locally with Ollama, and verifying the Ollama connection and models. Use when asked to build, deploy, start, or smoke-test jarvis-core in Docker, or to debug core↔Ollama connectivity.
---

# Jarvis docker-deploy checklist

Follow the phases in order. Tick each item and stop at the first failure: report it with the
exact output and a suggested fix.

**Hard rules (from CLAUDE.md):**
- Get Awais's **explicit go-ahead before each phase that has side effects** (build, up, pull,
  down). Phases 0–1 are read-only and can run without asking.
- Never run `docker compose down -v`, `docker volume rm`, or `docker system prune`, and never
  delete `D:\Jarvis\data\`. They destroy models, ChromaDB data and audit logs.
- Never use the `setup` profile (internet-connected `ollama-pull`) unless Awais asks.
- Never print the contents of `D:\Jarvis\secrets\`.
- All commands run from `D:\Jarvis\jarvis-docker`. When giving commands to Awais, use Windows
  CMD form (`cd /d D:\Jarvis\jarvis-docker`).

---

## Phase 0: Pre-flight (read-only)
- [ ] Docker Desktop is running: `docker info --format "{{.ServerVersion}} mem={{.MemTotal}}"`.
      Docker's memory should be ≥ 10 GB (Ollama 7B uses ~6 GB, core 2 GB).
- [ ] Unit tests pass: `cd ../jarvis-core && py -m pytest tests -q`
- [ ] Compose file is valid: `docker compose --profile app config --quiet`
- [ ] Every file the build needs exists: `jarvis-core/Dockerfile`, `requirements.txt`,
      `.dockerignore`, `app/`.
- [ ] All secret files referenced in compose exist (check names only, not contents):
      `ls D:/Jarvis/secrets`. If any are missing, Awais runs `py jarvis-core/scripts/setup_secrets.py`.
- [ ] Models are already present on the host: `D:\Jarvis\data\ollama\manifests` contains
      `qwen2.5`, `llama3.2` and `nomic-embed-text` entries.

## Phase 1: Static review of the build inputs (read-only)
- [ ] The Dockerfile still has: `python:3.11-slim`, `USER 10001:10001`, exec-form CMD, HEALTHCHECK,
      telemetry env vars, and installs only `requirements.txt` (not `-dev`).
- [ ] `.dockerignore` excludes `.env`, `*.key`, `scripts/`, `__pycache__`.
- [ ] `core` in compose: `<<: *hardened`, `mem_limit: 2g`, `memswap_limit: 2g`,
      `jarvis_data:/data`, `networks: [backend]`, `depends_on: ollama (service_healthy)`.

## Phase 2: Build (ASK FIRST)
```
docker compose --profile app build --progress=plain core
```
- [ ] Build succeeds. On failure, quote the first `ERROR` block. Common causes:
  - pip resolver conflict → loosen or align the ranges in `requirements.txt`
  - a missing wheel needing a compiler → report it; don't add build-essential without approval
- [ ] Image size is reasonable: `docker image ls jarvis-core:local` (expect ~1.5–3 GB with crewai/chromadb).
- [ ] Runs as non-root: `docker run --rm --entrypoint id jarvis-core:local` → `uid=10001`.
- [ ] After the first good build, suggest freezing a lock:
      `docker run --rm --entrypoint pip jarvis-core:local freeze > ../jarvis-core/requirements.lock`

## Phase 3: Run locally (ASK FIRST)
Start only Ollama and core. `edge`, `proxy` and `ui` are not needed for a smoke test:
```
docker compose --profile app up -d ollama core
```
- [ ] Both are running and healthy: `docker compose --profile app ps`
      (core's healthcheck has a 30s start period; Ollama's up to ~3 min).
- [ ] No crash loop: `docker compose logs --tail=50 core`
- [ ] Memory is within budget: `docker stats --no-stream` (core < 2 GiB, total RAM headroom left).
- [ ] Health endpoint from inside the container (core publishes no host port; only `edge` does):
      ```
      docker compose exec core python -c "import urllib.request;print(urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=5).read().decode())"
      ```
- [ ] The read-only rootfs holds: `docker compose exec core sh -c "touch /srv/x"` should **fail**,
      and `touch /data/x && rm /data/x` should **succeed**.

## Phase 4: Check the Ollama connection
Run from inside core so the test uses the real network path (`backend`, `NO_PROXY` includes `ollama`):
- [ ] Ollama is reachable and models are listed:
      ```
      docker compose exec core python -c "import json,os,urllib.request;u=os.environ['OLLAMA_URL'];d=json.load(urllib.request.urlopen(u+'/api/tags',timeout=10));print(sorted(m['name'] for m in d['models']))"
      ```
      Expect it to include `MANAGER_MODEL`, `WORKER_MODEL` and `EMBED_MODEL`
      (`qwen2.5:7b`, `llama3.2:3b`, `nomic-embed-text:latest`).
- [ ] Embeddings work (small, fast call):
      ```
      docker compose exec core python -c "import json,os,urllib.request;u=os.environ['OLLAMA_URL'];r=urllib.request.Request(u+'/api/embed',data=json.dumps({'model':os.environ['EMBED_MODEL'],'input':'ping'}).encode(),headers={'Content-Type':'application/json'});print(len(json.load(urllib.request.urlopen(r,timeout=120))['embeddings'][0]),'dims')"
      ```
- [ ] Optional (slow on CPU, ~30–90s the first time; ask first): a one-token generation with the
      worker model via `/api/generate` with `"stream": false, "options": {"num_predict": 1}`.
- [ ] Network isolation: core **cannot** reach the internet directly. This should fail or time out:
      `docker compose exec core python -c "import urllib.request;urllib.request.urlopen('https://example.com',timeout=5)"`

### Troubleshooting
| Symptom | Likely cause / fix |
|---|---|
| `Connection refused` to ollama | Ollama still starting. Wait for `healthy`, or check `docker compose logs ollama` |
| Request goes to `proxy:3128` and fails | `ollama` missing from `NO_PROXY`, or the client ignores it. Check `env` in core |
| `model not found` | The model isn't in `data/ollama`. Awais runs the setup puller (needs his approval) |
| CrewAI calls `localhost:11434` | Set `OLLAMA_API_BASE=http://ollama:11434` (LiteLLM ignores `base_url` in some versions) |
| `OPENAI_API_KEY not found` | CrewAI memory has no explicit Ollama `embedder=` |
| core OOM-killed (exit 137) | Exceeded `mem_limit: 2g`. Profile it; don't raise the limit without approval |
| `Read-only file system` | Code writes outside `/data` or `/tmp`. Fix the path, don't drop `read_only` |

## Phase 5: Report and stop
- [ ] Summarise: build result, image size, health, memory, Ollama models and embedding check.
- [ ] Leave the containers running unless Awais asks to stop them. To stop without deleting data:
      `docker compose --profile app stop core ollama` (never `down -v`).
