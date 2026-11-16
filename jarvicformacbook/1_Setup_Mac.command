#!/bin/bash
# Jarvis for MacBook - step 1: verify Docker and download the local models.
set -euo pipefail

cd "$(dirname "$0")"
PACKAGE_DIR="$PWD"

pause() {
  echo
  read -r -p "Press Enter to close this window..." _ || true
}

trap 'status=$?; if [ "$status" -ne 0 ]; then echo; echo "Setup failed (exit $status). Read the message above."; pause; fi' EXIT

echo "=============================================="
echo "  Jarvis for MacBook - First-time setup"
echo "=============================================="
echo

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker Desktop is not installed."
  echo "Install it from https://www.docker.com/products/docker-desktop/ and run this again."
  open "https://www.docker.com/products/docker-desktop/" 2>/dev/null || true
  exit 1
fi

if ! docker compose version >/dev/null 2>&1; then
  echo "Docker Compose v2 is required. Update Docker Desktop and run this again."
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  echo "Starting Docker Desktop..."
  open -a Docker 2>/dev/null || true
  echo "Waiting for Docker to be ready (this can take a minute)..."
  for _ in $(seq 1 90); do
    if docker info >/dev/null 2>&1; then break; fi
    sleep 2
  done
fi

if ! docker info >/dev/null 2>&1; then
  echo "Docker did not start. Open Docker Desktop manually, wait for the whale icon,"
  echo "then double-click 1_Setup_Mac.command again."
  exit 1
fi

echo "Preparing data folders..."
mkdir -p "$PACKAGE_DIR/data/ollama" \
         "$PACKAGE_DIR/data/voice" \
         "$PACKAGE_DIR/data/audit" \
         "$PACKAGE_DIR/data/sandbox"
# Docker Desktop for Mac maps host files through a VM; world-writable data folders
# avoid UID mismatches with the containers' non-root user (UID 10001).
chmod -R u+rwX,go+rwX "$PACKAGE_DIR/data" 2>/dev/null || true
# Secrets are mounted read-only; make sure the container user can read them.
chmod 644 "$PACKAGE_DIR"/secrets/* 2>/dev/null || true

cd "$PACKAGE_DIR/jarvis-docker"

echo
echo "Building the Jarvis images..."
echo "The first build compiles Whisper for voice; expect 15-30 minutes on a MacBook."
docker compose --profile app build

echo
echo "Starting Ollama..."
docker compose up -d ollama

echo
echo "Downloading the local models (qwen2.5:7b, llama3.2:3b, nomic-embed-text)..."
echo "This is a ~9 GB download and can take a while on a slow connection."
docker compose --profile setup run --rm ollama-pull

echo
echo "=============================================="
echo "  Setup complete."
echo "  Next: double-click 2_Start_Jarvis.command"
echo "=============================================="
pause
