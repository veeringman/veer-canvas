#!/usr/bin/env python3
"""One-time OAuth for personal Gmail Drive backups.

Service accounts cannot write into a normal Gmail folder (no storage quota).
This script signs in as housingcolonysanyard@gmail.com and saves a refresh token.

Usage (on your Mac, with a browser):
  python3 authorize-drive.py \\
    --client ~/Downloads/client_secret_….json \\
    --out ./drive-token.json

Then copy drive-token.json to the server as data/drive-token.json (chmod 600).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

SCOPES = ["https://www.googleapis.com/auth/drive.file"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--client", required=True, help="OAuth Desktop client JSON from Google Cloud")
    ap.add_argument("--out", required=True, help="Where to write the user token JSON")
    args = ap.parse_args()
    client = Path(args.client).expanduser()
    out = Path(args.out).expanduser()
    if not client.is_file():
        raise SystemExit(f"Missing client JSON: {client}")

    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_secrets_file(str(client), SCOPES)
    print(
        "Sign in as housingcolonysanyard@gmail.com and click Allow.",
        flush=True,
    )
    creds = flow.run_local_server(
        port=8765,
        prompt="consent",
        access_type="offline",
        authorization_prompt_message="Open this URL in your browser:\n{url}\n",
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(creds.to_json(), encoding="utf-8")
    try:
        out.chmod(0o600)
    except OSError:
        pass
    print(f"Wrote {out}")
    print("Copy this file to the server as data/drive-token.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
