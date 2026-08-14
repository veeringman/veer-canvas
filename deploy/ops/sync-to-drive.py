#!/usr/bin/env python3
"""Upload latest backup + asset dirs to Google Drive (Phase 2).

Auth (first match wins):
  1. OAuth user token  — data/drive-token.json  (personal Gmail; recommended)
  2. Service account   — data/drive-sa.json     (Shared Drives only)

Requires:
  pip: google-api-python-client google-auth google-auth-oauthlib
  env: DRIVE_FOLDER_ID
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sys
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path

SCOPES = ["https://www.googleapis.com/auth/drive.file"]
_DRIVE_KW = {
    "supportsAllDrives": True,
}


def _site_root_from_env() -> Path | None:
    raw = os.environ.get("WEB_ROOT") or os.environ.get("VEERCANVAS_SITE_ROOT") or ""
    return Path(raw) if raw else None


def _drive_service():
    try:
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload
    except ImportError as exc:
        raise SystemExit(
            "Install Drive deps: pip install google-api-python-client google-auth google-auth-oauthlib"
        ) from exc
    creds = _credentials()
    return build("drive", "v3", credentials=creds, cache_discovery=False), MediaFileUpload


def _credentials():
    token_path = os.environ.get("DRIVE_TOKEN_JSON") or ""
    client_path = os.environ.get("DRIVE_OAUTH_CLIENT") or ""
    sa_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") or ""
    root = _site_root_from_env()
    if root:
        token_path = token_path or str(root / "data" / "drive-token.json")
        client_path = client_path or str(root / "data" / "drive-oauth-client.json")
        sa_path = sa_path or str(root / "data" / "drive-sa.json")

    if token_path and Path(token_path).is_file():
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials

        creds = Credentials.from_authorized_user_file(token_path, SCOPES)
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            Path(token_path).write_text(creds.to_json(), encoding="utf-8")
            try:
                Path(token_path).chmod(0o600)
            except OSError:
                pass
        if creds and creds.valid:
            print("auth: oauth user token")
            return creds
        raise SystemExit(f"OAuth token at {token_path} is invalid — re-run authorize-drive.py")

    if sa_path and Path(sa_path).is_file():
        from google.oauth2 import service_account

        print("auth: service account (Shared Drive required)")
        return service_account.Credentials.from_service_account_file(sa_path, scopes=SCOPES)

    raise SystemExit(
        "No Drive credentials. Put data/drive-token.json (OAuth) or data/drive-sa.json (Shared Drive)."
    )


def _ensure_child_folder(service, parent_id: str, name: str) -> str:
    safe = name.replace("'", "\\'")
    q = (
        f"name = '{safe}' and "
        f"'{parent_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    )
    found = service.files().list(
        q=q,
        spaces="drive",
        fields="files(id,name)",
        pageSize=5,
        includeItemsFromAllDrives=True,
        **_DRIVE_KW,
    ).execute()
    files = found.get("files") or []
    if files:
        return files[0]["id"]
    meta = {
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [parent_id],
    }
    created = service.files().create(body=meta, fields="id", **_DRIVE_KW).execute()
    return created["id"]


def _upload_file(service, MediaFileUpload, parent_id: str, path: Path, remote_name: str | None = None) -> str:
    name = remote_name or path.name
    mime = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
    safe = name.replace("'", "\\'")
    q = f"name = '{safe}' and '{parent_id}' in parents and trashed = false"
    existing = (
        service.files()
        .list(
            q=q,
            spaces="drive",
            fields="files(id)",
            pageSize=5,
            includeItemsFromAllDrives=True,
            **_DRIVE_KW,
        )
        .execute()
        .get("files")
        or []
    )
    media = MediaFileUpload(str(path), mimetype=mime, resumable=True)
    if existing:
        fid = existing[0]["id"]
        service.files().update(fileId=fid, media_body=media, **_DRIVE_KW).execute()
        return fid
    meta = {"name": name, "parents": [parent_id]}
    created = service.files().create(body=meta, media_body=media, fields="id", **_DRIVE_KW).execute()
    return created["id"]


def _prune_dated_backups(service, folder_id: str, site_id: str, retain_days: int) -> int:
    """Trash dated <site>-YYYYMMDD*.tgz older than retain_days; keep *-latest.tgz."""
    if retain_days <= 0:
        return 0
    prefix = f"{site_id}-"
    safe_site = site_id.replace("'", "\\'")
    q = (
        f"'{folder_id}' in parents and trashed = false and "
        f"name contains '{safe_site}-' and not name contains '-latest'"
    )
    cutoff = datetime.now(timezone.utc).timestamp() - (retain_days * 86400)
    deleted = 0
    page_token = None
    while True:
        resp = (
            service.files()
            .list(
                q=q,
                spaces="drive",
                fields="nextPageToken, files(id,name,createdTime)",
                pageSize=100,
                pageToken=page_token,
                includeItemsFromAllDrives=True,
                **_DRIVE_KW,
            )
            .execute()
        )
        for f in resp.get("files") or []:
            name = f.get("name") or ""
            if not name.startswith(prefix) or not name.endswith(".tgz"):
                continue
            if name.endswith("-latest.tgz"):
                continue
            created = f.get("createdTime") or ""
            try:
                ts = datetime.fromisoformat(created.replace("Z", "+00:00")).timestamp()
            except ValueError:
                continue
            if ts < cutoff:
                service.files().update(fileId=f["id"], body={"trashed": True}, **_DRIVE_KW).execute()
                deleted += 1
                print(f"prune drive {name}")
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return deleted


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--site-root", required=True)
    ap.add_argument("--folder-id", required=True)
    ap.add_argument("--site-id", default="site")
    ap.add_argument("--retain-days", type=int, default=int(os.environ.get("DRIVE_RETAIN_DAYS") or 14))
    args = ap.parse_args()
    os.environ["WEB_ROOT"] = str(Path(args.site_root))
    root = Path(args.site_root)
    service, MediaFileUpload = _drive_service()

    backups_id = _ensure_child_folder(service, args.folder_id, "backups")
    assets_id = _ensure_child_folder(service, args.folder_id, "assets")
    site_assets = _ensure_child_folder(service, assets_id, args.site_id)

    uploaded: list[str] = []
    backup_root = Path(f"/var/backups/veercanvas/{args.site_id}")
    latest_tg = backup_root / "latest.tgz"
    if latest_tg.exists():
        target = latest_tg.resolve()
        if target.is_file():
            stamp = target.name.replace(f"{args.site_id}-", "").replace(".tgz", "")
            print(f"upload backup latest + dated {stamp}")
            _upload_file(
                service,
                MediaFileUpload,
                backups_id,
                target,
                remote_name=f"{args.site_id}-latest.tgz",
            )
            _upload_file(
                service,
                MediaFileUpload,
                backups_id,
                target,
                remote_name=f"{args.site_id}-{stamp}.tgz",
            )
            uploaded.append(f"backups/{args.site_id}-latest.tgz")

    for rel in (
        "receipts",
        "no-dues",
        "no-objection",
        "vault",
        "profile-photos",
        "info-centre",
        "payments",
        "messages",
        "parking-adhoc",
        "campaign-images",
        "notice-images",
        "marketplace-images",
    ):
        local = root / "data" / rel
        if not local.is_dir():
            continue
        if not any(local.iterdir()):
            continue
        folder = _ensure_child_folder(service, site_assets, rel)
        with tempfile.NamedTemporaryFile(suffix=f"-{rel}.tgz", delete=False) as tmp:
            tar_path = Path(tmp.name)
        try:
            with tarfile.open(tar_path, "w:gz") as tar:
                tar.add(local, arcname=rel)
            print(f"upload assets/{rel}")
            _upload_file(service, MediaFileUpload, folder, tar_path, remote_name=f"{rel}.tgz")
            uploaded.append(f"assets/{args.site_id}/{rel}.tgz")
        finally:
            tar_path.unlink(missing_ok=True)

    pruned = _prune_dated_backups(service, backups_id, args.site_id, args.retain_days)
    result = {
        "ok": True,
        "siteId": args.site_id,
        "webRoot": str(root),
        "uploaded": uploaded,
        "pruned": pruned,
        "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
