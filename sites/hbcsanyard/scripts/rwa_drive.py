"""Upload a single file to the society's Google Drive folder."""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import tempfile
from typing import Any


def _drive_python(site_root: pathlib.Path) -> pathlib.Path | None:
    candidates = [
        os.environ.get("DRIVE_PYTHON") or "",
        "/var/lib/veercanvas/drive-venv/bin/python",
        str(pathlib.Path(site_root) / "data" / "drive-venv" / "bin" / "python"),
    ]
    for raw in candidates:
        if not raw:
            continue
        path = pathlib.Path(raw)
        if path.is_file() and os.access(path, os.X_OK):
            return path
    return None


def _sync_script(site_root: pathlib.Path) -> pathlib.Path | None:
    root = pathlib.Path(site_root).resolve()
    candidates = [
        os.environ.get("VEERCANVAS_ROOT") or "",
        str(root.parent.parent),
        str(root.parent),
    ]
    for raw in candidates:
        if not raw:
            continue
        path = pathlib.Path(raw) / "deploy" / "ops" / "sync-to-drive.py"
        if path.is_file():
            return path
    return None


def _run_drive(site_root: pathlib.Path, extra: list[str], *, timeout: int = 90) -> dict[str, Any]:
    import rwa_portal

    ops = rwa_portal.read_ops_settings(site_root)
    if not ops.get("driveEnabled"):
        raise ValueError("Google Drive is not enabled. Super admin can turn it on under Backups.")
    folder_id = str(ops.get("driveFolderId") or "").strip()
    if not folder_id:
        raise ValueError("Google Drive folder is not set.")
    py = _drive_python(site_root)
    script = _sync_script(site_root)
    if py is None or script is None:
        raise ValueError("Google Drive tools are not installed on this server.")

    env = os.environ.copy()
    env["WEB_ROOT"] = str(pathlib.Path(site_root).resolve())
    env["DRIVE_FOLDER_ID"] = folder_id
    sa = pathlib.Path(site_root) / "data" / "drive-sa.json"
    token = pathlib.Path(site_root) / "data" / "drive-token.json"
    if sa.is_file():
        env["GOOGLE_APPLICATION_CREDENTIALS"] = str(sa)
    if token.is_file():
        env["DRIVE_TOKEN_JSON"] = str(token)

    cmd = [
        str(py),
        str(script),
        "--site-root",
        str(pathlib.Path(site_root).resolve()),
        "--folder-id",
        folder_id,
        *extra,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip() or "Drive request failed"
        raise ValueError(err.splitlines()[-1][:240])
    payload: dict[str, Any] = {}
    for line in reversed((proc.stdout or "").splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            break
    if not payload.get("ok"):
        raise ValueError(str(payload.get("error") or "Drive request failed"))
    return payload


def upload_bytes(
    site_root: pathlib.Path,
    data: bytes,
    filename: str,
    *,
    mime: str | None = None,
    subfolder: str = "Composer",
) -> dict[str, Any]:
    suffix = pathlib.Path(filename).suffix or ".bin"
    with tempfile.NamedTemporaryFile(prefix="mhws-compose-", suffix=suffix, delete=False) as tmp:
        tmp.write(data)
        tmp_path = pathlib.Path(tmp.name)
    try:
        payload = _run_drive(
            site_root,
            [
                "--upload-file",
                str(tmp_path),
                "--upload-name",
                filename,
                "--subfolder",
                subfolder,
            ],
        )
    finally:
        try:
            tmp_path.unlink()
        except OSError:
            pass
    return {
        "id": payload.get("id") or "",
        "name": payload.get("name") or filename,
        "url": payload.get("url") or "",
        "mime": mime or "",
    }


def list_importable_files(site_root: pathlib.Path) -> list[dict[str, Any]]:
    payload = _run_drive(site_root, ["--list-import"])
    files = payload.get("files") if isinstance(payload.get("files"), list) else []
    return files


def download_file(site_root: pathlib.Path, file_id: str) -> tuple[bytes, str, str]:
    fid = str(file_id or "").strip()
    if not fid or len(fid) > 128 or not re_file_id(fid):
        raise ValueError("Choose a Google Drive file.")
    with tempfile.NamedTemporaryFile(prefix="mhws-drive-", suffix=".bin", delete=False) as tmp:
        tmp_path = pathlib.Path(tmp.name)
    try:
        payload = _run_drive(
            site_root,
            ["--download-id", fid, "--download-out", str(tmp_path)],
            timeout=90,
        )
        data = tmp_path.read_bytes()
    finally:
        try:
            tmp_path.unlink()
        except OSError:
            pass
    name = str(payload.get("name") or "document")
    mime = str(payload.get("mime") or "application/octet-stream")
    return data, name, mime


def re_file_id(value: str) -> bool:
    return bool(value) and all(ch.isalnum() or ch in "_-" for ch in value)
