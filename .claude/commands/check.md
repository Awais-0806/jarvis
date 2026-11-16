---
description: Run Jarvis quality checks — pytest, docker-compose config validation, and ruff lint
allowed-tools: Bash(py -m pytest:*), Bash(py -m ruff:*), Bash(docker compose:*), Bash(cd:*), Read, Grep, Glob
---

Run the Jarvis quality gate and report results. These checks are **read-only**. Do NOT build,
pull, start or stop any containers, and do NOT auto-fix code unless I say so after seeing the report.

Run these three checks (they are independent, so run them in parallel):

1. **Unit tests**
   ```
   cd D:/Jarvis/jarvis-core && py -m pytest tests -q -p no:cacheprovider
   ```

2. **Docker Compose config validation.** This parses and interpolates only. Nothing is built or started.
   ```
   cd D:/Jarvis/jarvis-docker && docker compose --profile app --profile setup config --quiet
   ```
   If it passes, also confirm these invariants by reading `docker compose --profile app config`:
   - every service except the one-shot `ollama-pull` has `read_only: true`, `cap_drop: [ALL]`,
     `user: "10001:10001"`, `no-new-privileges:true`
   - `core` has `mem_limit` set and mounts `jarvis_data` at `/data`
   - no service publishes a port other than `edge` on `127.0.0.1:8080`
   - the `backend` network is `internal: true`

3. **Lint**
   ```
   cd D:/Jarvis/jarvis-core && py -m ruff check app tests
   ```
   If ruff is not installed, don't install it yourself. Report it and suggest:
   `py -m pip install -r requirements-dev.txt`

Then print a compact summary table:

| Check | Result | Details |
|---|---|---|
| pytest | ✅/❌ | passed/failed counts |
| compose config | ✅/❌ | errors or invariant violations |
| ruff | ✅/❌/⚠️ not installed | issue count by rule |

For each failure, show the relevant output lines and a one-line suggested fix with `file:line`.
Ignore the known httpx "app shortcut" DeprecationWarning (it comes from FastAPI 0.110 on the host).
$ARGUMENTS
