#!/usr/bin/env python3
"""Merge a patch into site data/ops-status.json (for admin console display)."""

from __future__ import annotations

import argparse
import json
import os
import pwd
import sys
import time
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--site-root", required=True)
    ap.add_argument("--section", required=True, help="e.g. lastBackup or lastVitals")
    ap.add_argument("--json", required=True, help="JSON object string")
    ap.add_argument("--owner", default="ubuntu")
    args = ap.parse_args()
    root = Path(args.site_root)
    path = root / "data" / "ops-status.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    existing: dict = {}
    if path.is_file():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            existing = {}
    try:
        patch = json.loads(args.json)
    except json.JSONDecodeError as exc:
        print(f"invalid json: {exc}", file=sys.stderr)
        return 1
    if not isinstance(patch, dict):
        print("patch must be a JSON object", file=sys.stderr)
        return 1
    patch.setdefault("at", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    existing[args.section] = patch
    path.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")
    try:
        pw = pwd.getpwnam(args.owner)
        os.chown(path, pw.pw_uid, pw.pw_gid)
        os.chmod(path, 0o640)
    except (KeyError, OSError):
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
