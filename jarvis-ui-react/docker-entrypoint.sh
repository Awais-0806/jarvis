#!/bin/sh
# Renders the nginx config with the core bearer token, then runs nginx in the foreground.
#
# Why a template: nginx cannot read a header value from a file, and the token must not be
# baked into the image or exposed to the browser. envsubst runs here, in the container only.
set -eu

TOKEN_FILE="${CORE_TOKEN_FILE:-/run/secrets/core_api_token}"
TEMPLATE="/etc/nginx/templates/jarvis.conf.template"
OUT="/tmp/nginx.conf"

# Local Docker mounts the token file; cloud platforms (Railway) inject CORE_API_TOKEN as an
# environment variable instead. The file wins when both exist.
ENV_TOKEN="${CORE_API_TOKEN:-}"
CORE_API_TOKEN=""
if [ -r "$TOKEN_FILE" ]; then
    # Strip CR/LF (the secret is often edited on Windows) and one layer of surrounding quotes
    # (a value pasted as "token" would otherwise close nginx's own quoted string and break the
    # config). Core only .strip()s the same file, so a quoted secret must not reach this proxy.
    CORE_API_TOKEN="$(tr -d '\r\n' < "$TOKEN_FILE" | sed -e 's/^"\(.*\)"$/\1/')"
elif [ -n "$ENV_TOKEN" ]; then
    CORE_API_TOKEN="$(printf '%s' "$ENV_TOKEN" | tr -d '\r\n' | sed -e 's/^"\(.*\)"$/\1/')"
fi

if [ -z "$CORE_API_TOKEN" ]; then
    echo "[jarvis-ui] FATAL: no API token. Mount $TOKEN_FILE or set CORE_API_TOKEN." >&2
    exit 1
fi

# Anything nginx could mis-parse inside a quoted header (spaces, quotes, backslashes, $, ;)
# is rejected here with a clear message rather than as an "unexpected ..." syntax error.
if ! printf '%s' "$CORE_API_TOKEN" | grep -Eq '^[A-Za-z0-9._~-]+$'; then
    echo "[jarvis-ui] FATAL: the API token contains characters that are unsafe in nginx.conf" >&2
    echo "[jarvis-ui]        Allowed: A-Z a-z 0-9 . _ ~ - (no quotes, spaces, CR/LF or \$)" >&2
    exit 1
fi

export CORE_API_TOKEN
# Only ${CORE_API_TOKEN} is substituted; nginx variables such as $host are left untouched.
envsubst '${CORE_API_TOKEN}' < "$TEMPLATE" > "$OUT"
chmod 0600 "$OUT"

nginx -t -c "$OUT"
echo "[jarvis-ui] starting nginx on :8080 (API proxy -> core:8000)" >&2
exec nginx -c "$OUT" -g 'daemon off;'
