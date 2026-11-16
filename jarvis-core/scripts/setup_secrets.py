#!/usr/bin/env python3
"""
Jarvis - Loop 1 - secrets bootstrap.

Standard library ONLY (argparse, base64, os, pathlib, secrets, sys).
No third-party imports (no `cryptography`), so it runs in a bare
python:3.11-slim container.

Generates:
  * fernet.key                 - 32 random bytes, urlsafe-base64 (valid Fernet key)
  * *_token.txt / session secret - random URL-safe tokens
  * placeholder files          - contain REPLACE_ME, for you to fill in by hand

Behaviour:
  * Existing files are NEVER overwritten by default.
  * --rotate regenerates GENERATED secrets only.
  * Placeholder files are NEVER touched once they exist, even with --rotate,
    so your real API keys can't be wiped by accident.
  * Secret values are never printed.
"""

import argparse
import base64
import os
import secrets
import sys
from pathlib import Path

PLACEHOLDER = b"REPLACE_ME"

# Generated secrets: (filename, kind)
GENERATED = [
    ("fernet.key", "fernet"),
    ("core_api_token.txt", "token"),
    ("tool_email_token.txt", "token"),
    ("tool_contracts_token.txt", "token"),
    ("tool_files_token.txt", "token"),
    ("voice_token.txt", "token"),
    ("ui_session_secret.txt", "token"),
]

# Placeholders you fill in manually
PLACEHOLDERS = [
    "gmail_client_id.txt",
    "gmail_client_secret.txt",
    "sam_gov_api_key.txt",
    "ted_api_key.txt",
    "etimad_api_key.txt",
]


def make_fernet_key() -> bytes:
    """A Fernet key is 32 random bytes encoded as urlsafe base64 (44 chars)."""
    key = base64.urlsafe_b64encode(secrets.token_bytes(32))
    assert len(base64.urlsafe_b64decode(key)) == 32
    return key


def make_token() -> bytes:
    return secrets.token_urlsafe(48).encode("ascii")


def write_secret(path: Path, data: bytes) -> None:
    """Atomic write (temp file in same dir, then replace). No trailing newline."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    try:
        os.chmod(tmp, 0o600)  # best effort; mostly meaningless on Windows mounts
    except OSError:
        pass
    os.replace(tmp, path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate Jarvis secrets.")
    parser.add_argument("--out", default="/secrets",
                        help="Output directory (default: /secrets)")
    parser.add_argument("--rotate", action="store_true",
                        help="Regenerate generated secrets even if they exist "
                             "(placeholders are never touched)")
    args = parser.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    print(f"Secrets directory: {out}")
    print("-" * 56)

    for name, kind in GENERATED:
        path = out / name
        if path.exists() and not args.rotate:
            print(f"[KEPT     ] {name}")
            continue
        data = make_fernet_key() if kind == "fernet" else make_token()
        existed = path.exists()
        write_secret(path, data)
        print(f"[{'ROTATED  ' if existed else 'CREATED  '}] {name}")

    for name in PLACEHOLDERS:
        path = out / name
        if path.exists():
            print(f"[KEPT     ] {name}  (placeholder, untouched)")
            continue
        write_secret(path, PLACEHOLDER)
        print(f"[PLACEHLDR] {name}  -> edit and replace REPLACE_ME")

    print("-" * 56)
    print("Done. Values were NOT printed. Never commit this directory.")
    print("Apps must .strip() secret values when reading them.")
    return 0


if __name__ == "__main__":
    sys.exit(main())