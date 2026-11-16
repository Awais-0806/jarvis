#!/bin/bash
# Jarvis for MacBook - step 3: stop the stack without deleting models or data.
set -euo pipefail

cd "$(dirname "$0")/jarvis-docker"

pause() {
  echo
  read -r -p "Press Enter to close this window..." _ || true
}

trap 'status=$?; if [ "$status" -ne 0 ]; then echo; echo "Stop failed (exit $status)."; pause; fi' EXIT

echo "Stopping Jarvis..."
docker compose --profile app down

echo
echo "Jarvis stopped. Models and data are still in ../data - nothing was deleted."
pause
