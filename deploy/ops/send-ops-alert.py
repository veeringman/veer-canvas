#!/usr/bin/env python3
"""Send a short ops alert via site data/smtp.env (Gmail App Password).

Usage:
  send-ops-alert.py --site-root /var/www/... --subject "..." --body "..."
"""

from __future__ import annotations

import argparse
import smtplib
import sys
from email.message import EmailMessage
from pathlib import Path


def load_env(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip("'").strip('"')
        if key:
            out[key] = val
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--site-root", required=True)
    ap.add_argument("--subject", required=True)
    ap.add_argument("--body", required=True)
    args = ap.parse_args()
    root = Path(args.site_root)
    env = load_env(root / "data" / "smtp.env")
    host = env.get("RWA_SMTP_HOST") or "smtp.gmail.com"
    port = int(env.get("RWA_SMTP_PORT") or "587")
    user = env.get("RWA_SMTP_USER") or ""
    password = env.get("RWA_SMTP_PASS") or ""
    sender = env.get("RWA_SMTP_FROM") or user
    to = env.get("BACKUP_ALERT_TO") or env.get("RWA_OPS_ALERT_TO") or sender
    if not user or not password or not to:
        print("ops alert skipped: SMTP not configured", file=sys.stderr)
        return 2
    msg = EmailMessage()
    msg["Subject"] = args.subject
    msg["From"] = sender
    msg["To"] = to
    msg.set_content(args.body)
    with smtplib.SMTP(host, port, timeout=25) as smtp:
        smtp.ehlo()
        smtp.starttls()
        smtp.ehlo()
        smtp.login(user, password)
        smtp.send_message(msg)
    print(f"ops alert sent to {to}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
