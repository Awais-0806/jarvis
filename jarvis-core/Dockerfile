# syntax=docker/dockerfile:1
#
# Jarvis Core - FastAPI + CrewAI service.
# Designed to run under the compose "hardened" profile:
#   non-root (UID 10001), read-only root filesystem, all capabilities dropped.
# Writable locations at runtime are ONLY /data (volume) and /tmp (tmpfs).

# Pinned by digest (verified build 2026-11-08) so rebuilds can't silently pick up a new
# upstream image. To update: pull python:3.11-slim, rebuild, re-run tests, then replace the digest.
FROM python:3.11-slim@sha256:673719e071ecf27434fd2635bbd8d00f49f4fdd81f243143438a42ced8bedf60

# --- Python / pip behaviour ---------------------------------------------
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# --- Telemetry OFF (CrewAI, OpenTelemetry, ChromaDB, HF, generic) --------
ENV CREWAI_DISABLE_TELEMETRY=true \
    CREWAI_DISABLE_TRACKING=true \
    CREWAI_TRACING_ENABLED=false \
    OTEL_SDK_DISABLED=true \
    ANONYMIZED_TELEMETRY=False \
    HF_HUB_DISABLE_TELEMETRY=1 \
    HF_HUB_OFFLINE=1 \
    DO_NOT_TRACK=1

# --- Writable paths (root FS is read-only at runtime) --------------------
# CREWAI_STORAGE_DIR: CrewAI memory/SQLite storage. An absolute path makes
#   CrewAI write here instead of ~/.local/share/<cwd-name>.
# HOME/XDG_*: libraries that write caches/config under $HOME land in /tmp
#   (tmpfs) or /data instead of failing on the read-only root FS.
ENV CREWAI_STORAGE_DIR=/data/crewai \
    CHROMA_PERSIST_DIR=/data/chroma \
    HOME=/tmp \
    XDG_CACHE_HOME=/tmp/.cache \
    XDG_CONFIG_HOME=/tmp/.config \
    XDG_DATA_HOME=/data/xdg

WORKDIR /srv

# Install PRODUCTION dependencies only (no pytest/httpx; see
# requirements-dev.txt). Copied first so this layer is cached when only
# code changes.
# requirements.lock = exact `pip freeze` of the last verified image, so rebuilds are
# reproducible. requirements.txt stays the human-edited source of ranges; to upgrade,
# edit it, build from it once, re-test, then regenerate the lock (see CLAUDE.md).
COPY requirements.lock .
RUN pip install --no-cache-dir -r requirements.lock

# Copy application code only; tests run outside the production image.
COPY app ./app

# Non-root user with a fixed UID/GID matching compose `user: "10001:10001"`.
# No login shell, no home directory (HOME=/tmp above).
# /data is created and owned by this user so a fresh named volume mounted
# there inherits the correct ownership on first use.
RUN groupadd --system --gid 10001 jarvis \
 && useradd --system --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin jarvis \
 && mkdir -p /data/crewai /data/chroma /data/xdg \
 && chown -R 10001:10001 /data \
 && chmod -R a-w /srv

USER 10001:10001

EXPOSE 8000

# slim has no curl; use the stdlib for the health probe.
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"]

# Exec form: uvicorn runs as PID 1 and receives SIGTERM directly
# (same effect as `exec uvicorn ...` in a shell, without needing a shell).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
