# Jarvis for MacBook - Boss's Quick Start

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
