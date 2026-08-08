#!/usr/bin/env python3
"""Upload latest backup + asset dirs to Google Drive (Phase 2).

Requires:
  pip: google-api-python-client google-auth
  env: GOOGLE_APPLICATION_CREDENTIALS, DRIVE_FOLDER_ID
"""

from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
import sys
from pathlib import Path


def _drive_service():
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload
    except ImportError as exc:
        raise SystemExit(
            "Install Drive deps: pip install google-api-python-client google-auth"
        ) from exc
    creds_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") or ""
    scopes = ["https://www.googleapis.com/auth/drive.file"]
    creds = service_account.Credentials.from_service_account_file(creds_path, scopes=scopes)
    return build("drive", "v3", credentials=creds, cache_discovery=False), MediaFileUpload


def _ensure_child_folder(service, parent_id: str, name: str) -> str:
    q = (
        f"name = '{name.replace(chr(39), chr(92) + chr(39))}' and "
        f"'{parent_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    )
    found = service.files().list(q=q, spaces="drive", fields="files(id,name)", pageSize=5).execute()
    files = found.get("files") or []
    if files:
        return files[0]["id"]
    meta = {
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [parent_id],
    }
    created = service.files().create(body=meta, fields="id").execute()
    return created["id"]


def _upload_file(service, MediaFileUpload, parent_id: str, path: Path, remote_name: str | None = None) -> str:
    name = remote_name or path.name
    mime = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
    # Replace existing same-name file in folder
    q = f"name = '{name.replace(chr(39), chr(92) + chr(39))}' and '{parent_id}' in parents and trashed = false"
    existing = service.files().list(q=q, spaces="drive", fields="files(id)", pageSize=5).execute().get("files") or []
    media = MediaFileUpload(str(path), mimetype=mime, resumable=True)
    if existing:
        fid = existing[0]["id"]
        service.files().update(fileId=fid, media_body=media).execute()
        return fid
    meta = {"name": name, "parents": [parent_id]}
    created = service.files().create(body=meta, media_body=media, fields="id").execute()
    return created["id"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--site-root", required=True)
    ap.add_argument("--folder-id", required=True)
    ap.add_argument("--site-id", default="site")
    args = ap.parse_args()
    root = Path(args.site_root)
    service, MediaFileUpload = _drive_service()

    backups_id = _ensure_child_folder(service, args.folder_id, "backups")
    assets_id = _ensure_child_folder(service, args.folder_id, "assets")
    site_assets = _ensure_child_folder(service, assets_id, args.site_id)

    backup_root = Path(f"/var/backups/veercanvas/{args.site_id}")
    latest_tg = backup_root / "latest.tgz"
    if latest_tg.is_file() or latest_tg.is_symlink():
        target = latest_tg.resolve() if latest_tg.exists() else None
        if target and target.is_file():
            print(f"upload backup {target.name}")
            _upload_file(service, MediaFileUpload, backups_id, target, remote_name=f"{args.site_id}-latest.tgz")

    for rel in ("receipts", "no-dues", "no-objection", "vault", "profile-photos", "info-centre", "payments", "messages"):
        local = root / "data" / rel
        if not local.is_dir():
            continue
        folder = _ensure_child_folder(service, site_assets, rel)
        # Tar small dirs for fewer API calls
        import tarfile
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=f"-{rel}.tgz", delete=False) as tmp:
            tar_path = Path(tmp.name)
        try:
            with tarfile.open(tar_path, "w:gz") as tar:
                tar.add(local, arcname=rel)
            print(f"upload assets/{rel}")
            _upload_file(service, MediaFileUpload, folder, tar_path, remote_name=f"{rel}.tgz")
        finally:
            tar_path.unlink(missing_ok=True)

    manifest = {
        "siteId": args.site_id,
        "webRoot": str(root),
    }
    print(json.dumps({"ok": True, **manifest}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
