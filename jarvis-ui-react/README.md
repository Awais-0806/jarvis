# J.A.R.V.I.S. — React Command Center

Replacement for the Streamlit dashboard: a local-first React + Vite SPA that talks to the existing
FastAPI core **only** through same-origin `/api/...` paths. A server-side proxy injects the bearer
token, so the token never exists in the bundle, in `localStorage`, or in `sessionStorage`.

The Streamlit app in `../jarvis-ui` is untouched and remains the rollback path.

---

## Project structure

```
jarvis-ui-react/
├── Dockerfile                  # node:20-alpine build → nginx:1.27-alpine runtime
├── docker-entrypoint.sh        # renders nginx.conf with the bearer token, then runs nginx
├── nginx.conf.template         # SPA hosting + /api proxy + path rewrites
├── vite.config.js              # dev/preview proxy with the same rewrites and token injection
├── index.html
├── package.json
├── .env.example                # placeholder only
├── .gitignore / .dockerignore
├── README.md
└── src/
    ├── main.jsx
    ├── App.jsx
    ├── index.css               # design tokens, HUD components, responsive rules, reduced motion
    ├── api/                    # client.js chat.js tenders.js approvals.js voice.js host.js
    ├── components/             # TopBar Sidebar JarvisCore ChatInterface CommandBar VoiceRecorder
    │                           # AudioWaveform SystemPanel TenderCard TenderPanel PitchResult
    │                           # ApprovalCard ApprovalPanel RemoteControl StatusIndicator ErrorBoundary
    ├── context/JarvisContext.jsx
    ├── hooks/                  # useChat useJobPolling useVoiceRecorder useBackendHealth useHostControl
    ├── pages/                  # CommandCenter Conversation Voice Tenders Approvals
    │                           # RemoteControlPage Settings
    ├── config/constants.js
    └── utils/                  # conversation.js formatters.js
```

---

## Prerequisites

- Node.js 20+ and npm 10+ (built with Node 22.23.5 / npm 10.9.9)
- Docker Desktop with Compose v2 for the container path
- The existing `jarvis` stack (core + Ollama) reachable at `http://localhost:8080`
- `secrets/core_api_token.txt` (the value the core expects as `Authorization: Bearer …`)

## Local development

```bash
cd jarvis-ui-react
npm install
copy .env.example .env.local     # PowerShell; use cp on other shells
```

Edit `.env.local`:

```env
JARVIS_API_TOKEN=<the value from secrets/core_api_token.txt>
# Optional, defaults to the running stack behind the edge:
# JARVIS_BACKEND_URL=http://localhost:8080
```

Then:

```bash
npm run dev      # http://127.0.0.1:5173
npm run build    # production bundle in dist/
npm run preview  # serves dist/ on 4173 with the same proxy
```

> Never rename the variable to `VITE_JARVIS_API_TOKEN`. Only variables without the `VITE_` prefix
> are read by the Node-side config and kept out of the browser bundle.

### How the dev proxy works

`vite.config.js` loads env vars with `loadEnv(mode, cwd, '')` inside the Node process, then:

- proxies `/api` to `JARVIS_BACKEND_URL`,
- sets `Authorization: Bearer <JARVIS_API_TOKEN>` on `proxyReq`,
- rewrites the paths the core does not expose under `/api` (see the table below).

`rewriteApiPath` is exported and asserted by a unit check (see “Tests executed”).

---

## Path mapping (why the UI calls `/api/...`)

| Browser request | Core route | Handled by |
|---|---|---|
| `POST /api/chat` | `POST /chat` | rewrite |
| `GET /api/jobs/{id}` | `GET /jobs/{id}` | rewrite |
| `POST /api/global-tenders/{id}/pitch` | `POST /global-tenders/{id}/pitch` | rewrite |
| `GET /api/global-tenders` | same | passthrough (core has an `/api` alias) |
| `POST /api/voice/transcribe` | same | passthrough |
| `GET /api/host/screenshot` | same | passthrough |
| `GET /api/host/stats` | same | passthrough |
| `POST /api/host/open_app` | same | passthrough |
| `GET /api/approvals` | **does not exist** | returns 404 → UI shows “backend integration required” |

The identical mapping exists twice on purpose: `vite.config.js` for development and
`nginx.conf.template` for the container. If core changes its prefixes, change both.

---

## Container build and run

```bash
docker build -t jarvis-ui-react:local .
```

Run standalone against a core that is reachable as `core:8000` (normally Compose does this):

```bash
docker run --rm -p 18080:8080 \
  --user 10001:10001 --read-only --tmpfs /tmp:size=128m \
  --mount type=bind,source=../secrets/core_api_token.txt,target=/run/secrets/core_api_token,readonly \
  jarvis-ui-react:local
```

Compose wiring (`jarvis-docker/docker-compose.yml`):

- `ui.build.context: ../jarvis-ui-react`, image `jarvis-ui-react:local`
- listens on **8080** (see “non-root” below), healthcheck `GET /healthz`
- mounts only the `core_api_token` secret; no `ui_session_secret`/`ui_password` any more
- `edge` proxies `/` to `ui:8080` and keeps `/ws/` on core; the edge’s old unauthenticated
  `/api/` → core block was removed so API traffic goes through the token-injecting UI container

### Why 8080 and not 80

The stack’s shared hardening anchor runs everything as UID 10001 with a read-only rootfs and all
capabilities dropped. Binding port 80 requires `NET_BIND_SERVICE` or root, so the image listens on
8080, with `pid`, temp paths and the rendered config under `/tmp`. This is intentional; every other
service follows the same rule.

### How the token gets in

nginx cannot read a header value from a file, so `docker-entrypoint.sh`:

1. reads `/run/secrets/core_api_token` (fails fast if missing/empty),
2. `envsubst '${CORE_API_TOKEN}'` renders the template to `/tmp/nginx.conf` (mode 0600),
3. `nginx -t` then `exec nginx -c /tmp/nginx.conf`.

Only `${CORE_API_TOKEN}` is substituted; nginx variables such as `$host` are untouched.

---

## Backend integration status

| Feature | Endpoint(s) | State |
|---|---|---|
| Chat | `POST /api/chat` → poll `GET /api/jobs/{id}` | Real. Job statuses are `running`/`done`/`error`; timeout 16 min (core keeps jobs 900 s). |
| Global tenders | `GET /api/global-tenders` | Real. The core currently answers `mode="mock"` with `is_mock=true`; the UI labels this as sample data using the core’s own `notice`. |
| VIP pitch | `POST /api/global-tenders/{id}/pitch` → poll jobs | Real. `reply` is JSON and is parsed into pitch / matched project / rationale / warnings / evidence. “Regenerate” sends `{"regenerate":true}`. |
| Voice | `POST /api/voice/transcribe` | Real. MediaRecorder → FormData → transcript → chat. The multipart field name is isolated as `VOICE_UPLOAD_FIELD = 'file'` in `src/config/constants.js` (matches core’s `file: UploadFile`). |
| Remote control | `GET /api/host/screenshot`, `POST /api/host/open_app`, `GET /api/host/stats` | Real, proxied by core to `host_bridge.py` on the Windows host. |
| Approvals | `GET /api/approvals` | **Not implemented by core (404).** Panel explains this and stays read-only. |

Deliberately not implemented: approve/reject/send actions, TTS playback (`SPEAKING` exists in the
core-state enum but is never emitted, because nothing in the UI plays audio), and any metric the
backend does not supply.

## Security summary

- No cloud AI calls, analytics, external fonts, or third-party scripts.
- Bearer token exists only in the proxy process (Vite in dev, entrypoint+nginx in the container).
- Centralised `apiRequest` client: timeouts, abort support, response validation, no token logging.
- Markdown is rendered without raw HTML and with an `http`/`https`/`mailto` URL allowlist.
- Screenshot base64 becomes a `data:` URL inside `<img>`; it is never injected as HTML.
- CSP (container and edge): `default-src 'self'; connect-src 'self' ws: wss:; img-src 'self' data:;
  style-src 'self' 'unsafe-inline'; script-src 'self'; frame-ancestors 'none'`.
- Microphone audio is only uploaded when the user stops a recording, and empty/unrecognised audio is
  never forwarded to chat.

## Browser requirements

`navigator.mediaDevices.getUserMedia()` requires a secure context: `localhost`/`127.0.0.1` works over
plain HTTP, any other host needs HTTPS. The edge currently binds `127.0.0.1:8080`, so this is fine
locally.

---

## Tests executed (on this machine)

| Check | Result |
|---|---|
| `npm install` | 149 packages, no errors |
| `npm run build` | success: 2,127 modules, `dist/assets/*.js` 471 kB (146 kB gzip) |
| Rewrite assertions (`rewriteApiPath`) | 7/7 paths map as documented |
| `docker build -t jarvis-ui-react:local .` | success, 74.3 MB image |
| Container as UID 10001, read-only rootfs, tmpfs `/tmp` | starts; `nginx -t` OK |
| `GET /healthz` | `200 text/plain` |
| `GET /` and `GET /remote-control` | `200 text/html` (SPA fallback works) |
| Hashed asset request | `200 application/javascript` |
| Security headers | CSP, `X-Frame-Options`, `Permissions-Policy` present |
| Token rendered into `/tmp/nginx.conf` | exactly one `Authorization` header, matches the secret, file mode 0600 |
| Token in `dist/` | 0 occurrences of the token value |
| Proxy against a stand-in core | `/api/chat`→`/chat`, `/api/jobs/{id}`→`/jobs/{id}`, pitch→`/global-tenders/{id}/pitch`, `/api/host/stats` and `/api/global-tenders` passthrough; `Authorization` present on all |
| Core down | `/api/global-tenders` → `502` from nginx; UI shows the offline banner |
| `docker compose --profile app config` | valid |
| Edge `nginx -t` | valid |

Not tested here: live chat/pitch/voice against a running core + Ollama (needs model pulls and a CPU
job), the Windows host bridge itself, and a real browser session (no browser automation was used).

## Rollback

Change `edge`'s `/` upstream back to `ui:3000`, restore the Streamlit `ui` service block from version
control, and run `docker compose --profile app up -d --build ui edge`. The Streamlit files were not
modified.
