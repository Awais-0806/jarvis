# syntax=docker/dockerfile:1
#
# Jarvis UI - Streamlit CEO dashboard.
# Designed to run under the compose "hardened" profile:
#   non-root (UID 10001), read-only root filesystem, all capabilities dropped.
# The only writable location at runtime is /tmp (tmpfs). The UI keeps no state on disk.

# Same digest as jarvis-core (verified build 2026-11-08), so both services share one base layer.
FROM python:3.11-slim@sha256:673719e071ecf27434fd2635bbd8d00f49f4fdd81f243143438a42ced8bedf60

# --- Python / pip behaviour ---------------------------------------------
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# --- Writable paths (root FS is read-only at runtime) --------------------
ENV HOME=/tmp \
    XDG_CACHE_HOME=/tmp/.cache \
    XDG_CONFIG_HOME=/tmp/.config

# --- Streamlit server config ---------------------------------------------
# GATHER_USAGE_STATS=false: Streamlit telemetry off (and ui has no internet anyway).
# FILE_WATCHER none / RUN_ON_SAVE false: no inotify watchers or hot reload in production.
# SHOW_ERROR_DETAILS none: never send Python tracebacks to the browser.
# TOOLBAR_MODE viewer: hides the developer menu (rerun/settings/deploy).
# MAX_UPLOAD_SIZE 10 (MB): room for a voice recording from st.audio_input; nginx's
# client_max_body_size is also 10m, so the two limits agree.
# XSRF protection stays on (Streamlit default); nginx in front is same-origin.
ENV STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_SERVER_ADDRESS=0.0.0.0 \
    STREAMLIT_SERVER_PORT=3000 \
    STREAMLIT_SERVER_FILE_WATCHER_TYPE=none \
    STREAMLIT_SERVER_RUN_ON_SAVE=false \
    STREAMLIT_SERVER_ENABLE_STATIC_SERVING=true \
    STREAMLIT_SERVER_ENABLE_XSRF_PROTECTION=true \
    STREAMLIT_SERVER_MAX_UPLOAD_SIZE=10 \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false \
    STREAMLIT_CLIENT_SHOW_ERROR_DETAILS=none \
    STREAMLIT_CLIENT_TOOLBAR_MODE=viewer \
    STREAMLIT_GLOBAL_DEVELOPMENT_MODE=false

WORKDIR /srv

# Dependencies first so this layer is cached when only app.py changes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy assets to static folder for Streamlit static file serving (/app/static/...)
COPY assets/ static/

# Copy all application files (including app.py and the assets folder)
COPY . .

# Non-root user with a fixed UID/GID matching compose `user: "10001:10001"`.
# No login shell, no home directory (HOME=/tmp above). App code is not writable.
RUN groupadd --system --gid 10001 jarvis \
 && useradd --system --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin jarvis \
 && chmod -R a-w /srv

USER 10001:10001

# Port 3000 is what nginx (edge) proxies "/" to (nginx.conf: ui:3000). Not published to the host.
EXPOSE 3000

# slim has no curl; use the stdlib against Streamlit's built-in health endpoint.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:3000/_stcore/health', timeout=4).status == 200 else 1)"]

# Exec form: streamlit runs as PID 1 and receives SIGTERM directly.
CMD ["streamlit", "run", "app.py"]