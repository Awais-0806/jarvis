#!/bin/bash
# Jarvis for MacBook - step 2: start the stack and open the dashboard.
set -euo pipefail

cd "$(dirname "$0")"
PACKAGE_DIR="$PWD"

pause() {
  echo
  read -r -p "Press Enter to close this window..." _ || true
}

trap 'status=$?; if [ "$status" -ne 0 ]; then echo; echo "Jarvis did not start (exit $status). Read the message above."; pause; fi' EXIT

if ! docker info >/dev/null 2>&1; then
  echo "Docker Desktop is not running. Starting it..."
  open -a Docker 2>/dev/null || true
  for _ in $(seq 1 90); do
    if docker info >/dev/null 2>&1; then break; fi
    sleep 2
  done
fi

if ! docker info >/dev/null 2>&1; then
  echo "Docker is not available. Run 1_Setup_Mac.command first."
  exit 1
fi

mkdir -p "$PACKAGE_DIR/data/ollama" \
         "$PACKAGE_DIR/data/voice" \
         "$PACKAGE_DIR/data/audit" \
         "$PACKAGE_DIR/data/sandbox"

cd "$PACKAGE_DIR/jarvis-docker"

echo "Starting Jarvis..."
docker compose --profile app up -d

echo "Waiting for the dashboard on http://localhost:8080 ..."
for _ in $(seq 1 90); do
  if curl -fsS http://127.0.0.1:8080/ >/dev/null 2>&1; then break; fi
  sleep 2
done

open http://localhost:8080 2>/dev/null || true

echo
echo "Jarvis is starting at http://localhost:8080"
echo "The first answer can take 1-3 minutes while the local model warms up."
pause
