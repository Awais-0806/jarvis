#!/usr/bin/env python3
"""Build ``jarvicformacbook/`` - a self-contained, Mac-ready copy of Jarvis.

Run from the repository root:

    python package_for_mac.py
    python package_for_mac.py --force      # replace an existing package

What it does
------------
1. Copies the services, docker config and secrets into ``jarvicformacbook/``.
2. Rewrites ``jarvis-docker/docker-compose.yml`` so every host path is relative
   (``../data/...``, ``../secrets/...``) instead of using Windows drive letters.
3. Creates the writable ``data/`` folders the Mac compose file mounts.
4. Writes the three macOS launchers and ``README_FOR_BOSS.md``.

The script never prints or inspects the contents of ``secrets/``.
"""

import argparse
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEFAULT_DEST = ROOT / "jarvicformacbook"

SERVICE_DIRS = (
    "jarvis-core",
    "jarvis-ui",
    "jarvis-voice",
    "jarvis-tools",
    "jarvis-docker",
    "secrets",
)

# Build artefacts and editor/OS noise that must not travel to the Mac.
IGNORED = shutil.ignore_patterns(
    "__pycache__",
    "*.pyc",
    "*.pyo",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    ".git",
    ".idea",
    ".vscode",
    ".DS_Store",
    "*.log",
)

# Order matters: the specific paths must be replaced before the generic fallback.
COMPOSE_REPLACEMENTS = (
    ("${JARVIS_HOME}/data", "../data"),
    ("${JARVIS_HOME}/secrets", "../secrets"),
    ("${JARVIS_HOME}/jarvis-tools", "../jarvis-tools"),
    ("${JARVIS_HOME}/jarvis-voice", "../jarvis-voice"),
    ("${JARVIS_HOME}/jarvis-ui", "../jarvis-ui"),
    ("${JARVIS_HOME}/jarvis-core", "../jarvis-core"),
    ("${SANDBOX}", "../data/sandbox"),
    ("${JARVIS_HOME}", ".."),
)

MAC_ENV = """# Jarvis for MacBook - Docker Compose environment.
#
# Every host path in docker-compose.yml is relative to this jarvis-docker/
# directory, which is what makes the package work on any Mac without editing.
JARVIS_HOME=..
SANDBOX=../data/sandbox
"""

SETUP_SCRIPT = r"""#!/bin/bash
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
"""

START_SCRIPT = r"""#!/bin/bash
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
"""

STOP_SCRIPT = r"""#!/bin/bash
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
"""

README = """# Jarvis for MacBook - Boss's Quick Start

This folder is a complete, self-contained copy of Jarvis, prepared for macOS.
Everything runs locally in Docker; no cloud AI service is used.

## What is in this folder

| Folder / file | Purpose |
|---|---|
| `1_Setup_Mac.command` | One-time setup: checks Docker, builds images, downloads the local models |
| `2_Start_Jarvis.command` | Starts Jarvis and opens the dashboard in your browser |
| `3_Stop_Jarvis.command` | Stops Jarvis; models and data are kept |
| `jarvis-core/` | The FastAPI "brain", agents and tender logic |
| `jarvis-ui/` | The Streamlit CEO dashboard |
| `jarvis-voice/` | Local speech-to-text and text-to-speech |
| `jarvis-tools/` | Email, contracts and file tools |
| `jarvis-docker/` | Docker Compose, nginx and proxy configuration |
| `secrets/` | Passwords and API keys (see the security note below) |
| `data/` | Local models, voice cache and audit logs - created on setup |

## Before you start

- macOS 12 or newer, on Apple Silicon or Intel.
- **Docker Desktop for Mac** installed: <https://www.docker.com/products/docker-desktop/>
- At least **16 GB of RAM** and **25 GB of free disk space**.
- Internet access for the one-time setup (the models are about 9 GB).

## First-time setup (do this once)

1. Move this whole `jarvicformacbook` folder somewhere permanent, for example
   your Desktop or Documents folder. Do not run it from a read-only location.
2. Open **Terminal**, go to the folder, and make the launchers executable:

   ```bash
   cd ~/Desktop/jarvicformacbook
   chmod +x *.command
   ```

3. Double-click **`1_Setup_Mac.command`** and leave the Terminal window open.
   The first run builds the images and downloads the models; it can take
   30-60 minutes depending on your connection.

   If macOS blocks the file ("cannot be opened because it is from an
   unidentified developer"), right-click it, choose **Open**, then **Open** again.

## Every time you want to use Jarvis

1. Double-click **`2_Start_Jarvis.command`**.
2. The dashboard opens automatically at <http://localhost:8080>.
3. Sign in with the CEO password. It is stored in `secrets/ui_password.txt`
   (open that file with TextEdit; do not share it).
4. The first answer can take 1-3 minutes while the local model warms up.
   Later answers are faster.

## To stop Jarvis

Double-click **`3_Stop_Jarvis.command`** (or run `docker compose --profile app down`
inside `jarvis-docker/`). Models and data are kept.

## Troubleshooting

- **"Docker is not available"**: open Docker Desktop, wait until the whale icon
  stops animating, then run the `.command` file again.
- **A `.command` file opens in a text editor**: run `chmod +x *.command` in
  Terminal, or right-click the file and choose **Open With > Terminal**.
- **Port 8080 is already in use**: stop the other application (often another
  container) or edit the `ports:` line in `jarvis-docker/docker-compose.yml`.
- **The dashboard loads but chat says the model is missing**: re-run
  `1_Setup_Mac.command`; the model download was interrupted.
- **Voice says the service is unavailable**: the voice image may still be
  building. Wait for `docker compose ps` to show `voice` as healthy, then retry.
- **Everything is broken and I want a clean start**: double-click
  `3_Stop_Jarvis.command`, then delete `data/ollama` only if you are happy to
  download the models again. Never delete `secrets/`.

## Security note - please read

This folder contains the **real** `secrets/` directory (passwords, API keys and
the encryption key). Treat the folder like a password:

- Do not email it, upload it to cloud storage, or commit it to Git.
- Keep it on the MacBook only for as long as the demo needs it.
- If the folder is lost or shared by accident, rotate the credentials and keys
  before using Jarvis again.

Jarvis itself stays private: models run on this Mac, and internet access is only
used by the explicitly allowlisted tender connectors.
"""


def write_text(path: Path, content: str) -> None:
    """Write UTF-8 text with LF line endings (macOS shell scripts need LF)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(content)


def copy_services(dest: Path) -> None:
    for name in SERVICE_DIRS:
        source = ROOT / name
        if not source.is_dir():
            raise SystemExit("Missing source folder: {}".format(source))
        shutil.copytree(source, dest / name, ignore=IGNORED)
        print("  copied {}".format(name))


def patch_compose(dest: Path) -> None:
    """Turn ${JARVIS_HOME}/... and Windows paths into Mac-safe relative paths."""
    compose = dest / "jarvis-docker" / "docker-compose.yml"
    text = compose.read_text(encoding="utf-8")

    for old, new in COMPOSE_REPLACEMENTS:
        text = text.replace(old, new)

    for forbidden in ("${JARVIS_HOME}", "${SANDBOX}", "C:/", "C:\\"):
        if forbidden in text:
            raise SystemExit(
                "Refusing to package: docker-compose.yml still contains {!r}".format(forbidden)
            )

    write_text(compose, text)
    write_text(dest / "jarvis-docker" / ".env", MAC_ENV)
    print("  rewrote jarvis-docker/docker-compose.yml and .env with relative paths")


def create_data_dirs(dest: Path) -> None:
    for name in ("ollama", "voice", "audit", "sandbox"):
        folder = dest / "data" / name
        folder.mkdir(parents=True, exist_ok=True)
        write_text(folder / ".gitkeep", "")
    print("  created data/ollama, data/voice, data/audit, data/sandbox")


def create_launchers(dest: Path) -> None:
    scripts = {
        "1_Setup_Mac.command": SETUP_SCRIPT,
        "2_Start_Jarvis.command": START_SCRIPT,
        "3_Stop_Jarvis.command": STOP_SCRIPT,
    }
    for filename, content in scripts.items():
        path = dest / filename
        write_text(path, content)
        try:
            os.chmod(path, 0o755)
        except OSError:
            # Windows cannot store POSIX modes; the README covers `chmod +x` on macOS.
            pass
    print("  wrote the three .command launchers")


def build(dest: Path) -> None:
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)

    print("Building {} ...".format(dest))
    copy_services(dest)
    patch_compose(dest)
    create_data_dirs(dest)
    create_launchers(dest)
    write_text(dest / "README_FOR_BOSS.md", README)
    print("  wrote README_FOR_BOSS.md")

    try:
        secret_count = sum(1 for item in (dest / "secrets").iterdir() if item.is_file())
    except OSError:
        secret_count = 0
    print()
    print("Done. {} service folders and {} secret files packaged.".format(
        len(SERVICE_DIRS), secret_count))
    print("Next: copy the whole '{}' folder to the Mac.".format(dest.name))
    print("On the Mac, run: chmod +x *.command   then double-click 1_Setup_Mac.command")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the MacBook package for Jarvis.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="replace jarvicformacbook/ if it already exists",
    )
    parser.add_argument(
        "--dest",
        type=Path,
        default=DEFAULT_DEST,
        help="output folder (default: ./jarvicformacbook)",
    )
    args = parser.parse_args()

    dest = args.dest.resolve()
    if dest.exists() and not args.force:
        print("{} already exists.".format(dest))
        print("Re-run with --force to replace it.")
        return 1

    try:
        build(dest)
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 - a packaging tool should explain, not traceback
        print("Packaging failed: {}".format(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
