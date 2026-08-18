"""Housing Colony Sanyard / RWA portal API helpers (SQLite-backed)."""

from __future__ import annotations

import hashlib
import html
import json
import mimetypes
import os
import pathlib
import re
import secrets
import smtplib
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from typing import Any
from urllib.parse import quote, urlparse
# When imported from admin/, resolve site scripts via SITE_ROOT / VEERCANVAS tree.
_ADMIN_DIR = pathlib.Path(__file__).resolve().parent
_ROOT = _ADMIN_DIR.parent
_SITE_ID = os.environ.get("VEERCANVAS_SITE_ID", "hbcsanyard")
_SITE_ROOT = pathlib.Path(
    os.environ.get("VEERCANVAS_SITE_ROOT")
    or os.environ.get("VEER_SITE_ROOT")
    or str(_ROOT / "sites" / _SITE_ID)
)
_SCRIPT_CANDIDATES = [
    _SITE_ROOT / "scripts",
    _ROOT / "sites" / _SITE_ID / "scripts",
    _ROOT.parent / "sites" / _SITE_ID / "scripts",  # local monorepo: veercanvas/../sites
    pathlib.Path(__file__).resolve().parents[1] / "sites" / "hbcsanyard" / "scripts",
]
for _scripts in _SCRIPT_CANDIDATES:
    # Skip empty dirs created by deploy scaffolding (e.g. canvas has no RWA scripts).
    if (_scripts / "init_rwa_db.py").is_file() and str(_scripts) not in sys.path:
        sys.path.insert(0, str(_scripts))
        break
else:
    # Still insert default so ImportError message is clear
    sys.path.insert(0, str(_SCRIPT_CANDIDATES[0]))

from init_rwa_db import (  # noqa: E402
    SUPERADMIN_HOUSE_ID,
    ADHOC_GATE_HOUSE_ID,
    SYSTEM_HOUSE_IDS,
    system_house_exclude_sql,
    connect,
    ensure_bank_account_columns,
    ensure_db,
    ensure_grievances_table,
    ensure_notice_pin_order,
    ensure_notice_audience,
    ensure_notice_image_column,
    ensure_notice_shares_table,
    ensure_notice_engagement_tables,
    ensure_household_members_table,
    ensure_household_tenants_table,
    ensure_parking_passes_table,
    ensure_access_events_table,
    ensure_info_documents_table,
    ensure_colony_works_table,
    ensure_work_quote_tables,
    ensure_colony_campaigns_tables,
    ensure_meeting_proceedings_table,
    ensure_resolution_votes_tables,
    migrate_roman_plot_ids,
    ensure_otp_pending_columns,
    ensure_resident_profile_columns,
    ensure_superadmin_account,
    ensure_entitlements_schema,
    ensure_report_templates_table,
    ensure_bilingual_content_columns,
    ensure_payment_records_tables,
    ensure_no_dues_requests_table,
    ensure_no_objection_requests_table,
    ensure_document_attestations_table,
    ensure_treasury_columns,
    ensure_messages_and_push_tables,
    ensure_msg_likes_and_ai,
    hash_otp,
    normalize_house_id,
    section_plot_sort_key,
    utc_now,
    verify_password,
)

import rwa_household as household  # noqa: E402
import rwa_entitlements as entitlements  # noqa: E402
import rwa_media  # noqa: E402

OTP_TTL_SECONDS = int(os.environ.get("RWA_OTP_TTL", "600"))
# Persist until Sign out (default ~10 years). Override with RWA_SESSION_TTL seconds.
SESSION_TTL_SECONDS = int(os.environ.get("RWA_SESSION_TTL", str(3650 * 24 * 3600)))
WELCOME_NOTICE_ID = "n_welcome"
HOUSE_RE = re.compile(r"^[A-Za-z0-9/_()-]{1,20}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _load_env_file(path: pathlib.Path) -> None:
    """Load KEY=VALUE lines into os.environ if not already set."""
    if not path.is_file():
        return
    try:
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip("'").strip('"')
            if key and key not in os.environ:
                os.environ[key] = value
    except OSError:
        pass


def load_smtp_config(site_root: pathlib.Path | None = None) -> dict:
    """Gmail-ready SMTP settings. Prefer env / data/smtp.env (never commit secrets)."""
    if site_root is not None:
        _load_env_file(site_root / "data" / "smtp.env")
        _load_env_file(site_root / "smtp.env")

    sender = (
        os.environ.get("RWA_SMTP_FROM")
        or os.environ.get("RWA_SMTP_USER")
        or "housingcolonysanyard@gmail.com"
    ).strip()
    user = (os.environ.get("RWA_SMTP_USER") or sender).strip()
    password = (os.environ.get("RWA_SMTP_PASS") or os.environ.get("RWA_SMTP_APP_PASSWORD") or "").strip()
    # Treat example placeholders as unset
    _placeholder = password.lower().replace(" ", "") in {
        "",
        "your-16-char-app-password-here",
        "xxxxxxxxxxxxxxxx",
        "changeme",
        "app-password-here",
    } or "password-here" in password.lower() or password.lower().startswith("xxxx")
    if _placeholder:
        password = ""
    provider = (os.environ.get("RWA_SMTP_PROVIDER") or "").strip().lower()
    if not provider and sender.lower().endswith("@gmail.com"):
        provider = "gmail"

    if provider == "gmail":
        host = (os.environ.get("RWA_SMTP_HOST") or "smtp.gmail.com").strip()
        port = int(os.environ.get("RWA_SMTP_PORT") or "587")
    else:
        host = (os.environ.get("RWA_SMTP_HOST") or "").strip()
        port = int(os.environ.get("RWA_SMTP_PORT") or "587")

    return {
        "provider": provider or "custom",
        "host": host,
        "port": port,
        "user": user,
        "password": password,
        "from": sender,
        "configured": bool(host and user and password),
    }


def smtp_status(site_root: pathlib.Path) -> dict:
    cfg = load_smtp_config(site_root)
    return {
        "provider": cfg["provider"],
        "host": cfg["host"],
        "port": cfg["port"],
        "from": cfg["from"],
        "user": cfg["user"],
        "configured": cfg["configured"],
        "envFile": str(site_root / "data" / "smtp.env"),
        "passwordSet": bool(cfg["password"]),
        "otpTtl": int(os.environ.get("RWA_OTP_TTL", str(OTP_TTL_SECONDS))),
    }


_SETTINGS_KEYS = (
    "RWA_SMTP_PROVIDER",
    "RWA_SMTP_HOST",
    "RWA_SMTP_PORT",
    "RWA_SMTP_USER",
    "RWA_SMTP_FROM",
    "RWA_SMTP_PASS",
    "RWA_OTP_TTL",
    "RWA_SUPERADMIN_USER",
    "RWA_INFO_CENTRE_PROTECT",
)

_OPS_ENV_KEYS = (
    "BACKUP_ALERT_TO",
    "OPS_VITALS_ENABLED",
    "BACKUP_RETAIN_DAYS",
    "DISK_MIN_PCT",
    "ACCESS_EVENTS_DAYS",
    "DISK_WARN_PCT",
    "DISK_CRIT_PCT",
    "MEM_WARN_PCT",
    "MEM_CRIT_PCT",
    "LOAD_WARN_RATIO",
    "LOAD_CRIT_RATIO",
    "BACKUP_MAX_AGE_H",
    "ALERT_COOLDOWN_WARN",
    "ALERT_COOLDOWN_CRIT",
    "DRIVE_ENABLED",
    "DRIVE_FOLDER_ID",
    "DRIVE_RETAIN_DAYS",
)

_OPS_DEFAULTS: dict[str, object] = {
    "alertTo": "",
    "vitalsEnabled": True,
    "backupRetainDays": 7,
    "backupDiskMinPct": 15,
    "accessEventsDays": 90,
    "diskWarnPct": 20,
    "diskCritPct": 10,
    "memWarnPct": 15,
    "memCritPct": 8,
    "loadWarnRatio": 1.5,
    "loadCritRatio": 2.5,
    "backupMaxAgeHours": 28,
    "alertCooldownWarnHours": 6,
    "alertCooldownCritHours": 1,
    "driveEnabled": False,
    "driveFolderId": "",
    "driveRetainDays": 14,
    "driveSaConfigured": False,
}


def _read_env_map(path: pathlib.Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        out[key.strip()] = value.strip().strip("'").strip('"')
    return out


def _env_truthy(val: str | None) -> bool:
    return str(val or "").strip().lower() in {"1", "true", "yes", "on"}


def read_ops_settings(site_root: pathlib.Path) -> dict:
    env = _read_env_map(_smtp_env_path(site_root))
    drive_env = _read_env_map(site_root / "data" / "drive.env")
    env = {**env, **drive_env}
    smtp_from = env.get("RWA_SMTP_FROM") or env.get("RWA_SMTP_USER") or ""
    alert_to = env.get("BACKUP_ALERT_TO") or env.get("RWA_OPS_ALERT_TO") or smtp_from
    sa_path = site_root / "data" / "drive-sa.json"
    return {
        "alertTo": alert_to,
        "vitalsEnabled": _env_truthy(env.get("OPS_VITALS_ENABLED", "1")),
        "backupRetainDays": int(env.get("BACKUP_RETAIN_DAYS") or _OPS_DEFAULTS["backupRetainDays"]),
        "backupDiskMinPct": int(env.get("DISK_MIN_PCT") or _OPS_DEFAULTS["backupDiskMinPct"]),
        "accessEventsDays": int(env.get("ACCESS_EVENTS_DAYS") or _OPS_DEFAULTS["accessEventsDays"]),
        "diskWarnPct": int(env.get("DISK_WARN_PCT") or _OPS_DEFAULTS["diskWarnPct"]),
        "diskCritPct": int(env.get("DISK_CRIT_PCT") or _OPS_DEFAULTS["diskCritPct"]),
        "memWarnPct": int(env.get("MEM_WARN_PCT") or _OPS_DEFAULTS["memWarnPct"]),
        "memCritPct": int(env.get("MEM_CRIT_PCT") or _OPS_DEFAULTS["memCritPct"]),
        "loadWarnRatio": float(env.get("LOAD_WARN_RATIO") or _OPS_DEFAULTS["loadWarnRatio"]),
        "loadCritRatio": float(env.get("LOAD_CRIT_RATIO") or _OPS_DEFAULTS["loadCritRatio"]),
        "backupMaxAgeHours": int(env.get("BACKUP_MAX_AGE_H") or _OPS_DEFAULTS["backupMaxAgeHours"]),
        "alertCooldownWarnHours": int(
            (int(env.get("ALERT_COOLDOWN_WARN") or 21600)) / 3600
        ),
        "alertCooldownCritHours": int(
            (int(env.get("ALERT_COOLDOWN_CRIT") or 3600)) / 3600
        ),
        "driveEnabled": _env_truthy(env.get("DRIVE_ENABLED", "0")),
        "driveFolderId": (env.get("DRIVE_FOLDER_ID") or "").strip(),
        "driveRetainDays": int(env.get("DRIVE_RETAIN_DAYS") or _OPS_DEFAULTS["driveRetainDays"]),
        "driveSaConfigured": sa_path.is_file(),
    }


def _ops_settings_to_env(ops: dict) -> dict[str, str]:
    def _int(key: str, default: int) -> str:
        try:
            return str(int(ops.get(key, default)))
        except (TypeError, ValueError):
            return str(default)

    def _float(key: str, default: float) -> str:
        try:
            return str(float(ops.get(key, default)))
        except (TypeError, ValueError):
            return str(default)

    warn_h = int(ops.get("alertCooldownWarnHours") or _OPS_DEFAULTS["alertCooldownWarnHours"])
    crit_h = int(ops.get("alertCooldownCritHours") or _OPS_DEFAULTS["alertCooldownCritHours"])
    enabled = ops.get("vitalsEnabled", True)
    return {
        "BACKUP_ALERT_TO": str(ops.get("alertTo") or "").strip(),
        "OPS_VITALS_ENABLED": "1" if enabled else "0",
        "BACKUP_RETAIN_DAYS": _int("backupRetainDays", 7),
        "DISK_MIN_PCT": _int("backupDiskMinPct", 15),
        "ACCESS_EVENTS_DAYS": _int("accessEventsDays", 90),
        "DISK_WARN_PCT": _int("diskWarnPct", 20),
        "DISK_CRIT_PCT": _int("diskCritPct", 10),
        "MEM_WARN_PCT": _int("memWarnPct", 15),
        "MEM_CRIT_PCT": _int("memCritPct", 8),
        "LOAD_WARN_RATIO": _float("loadWarnRatio", 1.5),
        "LOAD_CRIT_RATIO": _float("loadCritRatio", 2.5),
        "BACKUP_MAX_AGE_H": _int("backupMaxAgeHours", 28),
        "ALERT_COOLDOWN_WARN": str(max(1, warn_h) * 3600),
        "ALERT_COOLDOWN_CRIT": str(max(1, crit_h) * 3600),
        "DRIVE_ENABLED": "1" if ops.get("driveEnabled") else "0",
        "DRIVE_FOLDER_ID": str(ops.get("driveFolderId") or "").strip(),
        "DRIVE_RETAIN_DAYS": _int("driveRetainDays", 14),
    }


def send_ops_alert(site_root: pathlib.Path, subject: str, body: str) -> dict:
    """Send an ops email using site SMTP settings."""
    load_smtp_config(site_root)
    ops = read_ops_settings(site_root)
    cfg = load_smtp_config(site_root)
    to = (ops.get("alertTo") or cfg.get("from") or cfg.get("user") or "").strip()
    if not cfg.get("configured") or not to:
        raise ValueError("SMTP or alert recipient not configured")
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = cfg["from"]
    msg["To"] = to
    msg.set_content(body)
    with smtplib.SMTP(cfg["host"], cfg["port"], timeout=25) as smtp:
        smtp.ehlo()
        smtp.starttls()
        smtp.ehlo()
        smtp.login(cfg["user"], cfg["password"])
        smtp.send_message(msg)
    return {"sent": True, "to": to}


def read_ops_status(site_root: pathlib.Path, *, site_id: str | None = None) -> dict:
    """Snapshot for super-admin console (live + last cron writes)."""
    import shutil

    sid = (site_id or os.environ.get("VEERCANVAS_SITE_ID") or site_root.name.split(".")[0] or "site").strip()
    status_path = site_root / "data" / "ops-status.json"
    stored: dict = {}
    if status_path.is_file():
        try:
            stored = json.loads(status_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            stored = {}

    disk = shutil.disk_usage(site_root)
    disk_free_pct = round((disk.free / disk.total) * 100) if disk.total else 0

    mem_available_pct = None
    load_ratio = None
    mem_path = pathlib.Path("/proc/meminfo")
    if mem_path.is_file():
        info = {}
        for raw in mem_path.read_text(encoding="utf-8").splitlines():
            parts = raw.split(":")
            if len(parts) == 2:
                info[parts[0].strip()] = int(parts[1].strip().split()[0])
        total = info.get("MemTotal") or 0
        avail = info.get("MemAvailable") or info.get("MemFree") or 0
        if total:
            mem_available_pct = round((avail / total) * 100)
    load_path = pathlib.Path("/proc/loadavg")
    if load_path.is_file():
        load1 = float(load_path.read_text().split()[0])
        cpus = os.cpu_count() or 1
        load_ratio = round(load1 / max(1, cpus), 2)

    service_name = os.environ.get("VEERCANVAS_SERVICE_NAME") or ""
    cfg_path = site_root / "veercanvas" / "sites" / sid / "site.config.json"
    if not service_name and cfg_path.is_file():
        try:
            service_name = ((json.loads(cfg_path.read_text(encoding="utf-8")).get("admin") or {}).get("serviceName") or "")
        except json.JSONDecodeError:
            service_name = ""

    def _service_active(name: str) -> bool | None:
        if not name:
            return None
        try:
            import subprocess

            res = subprocess.run(
                ["systemctl", "is-active", name],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            return res.stdout.strip() == "active"
        except OSError:
            return None

    ops = read_ops_settings(site_root)
    return {
        "siteId": sid,
        "ops": ops,
        "live": {
            "diskFreePct": disk_free_pct,
            "memAvailablePct": mem_available_pct,
            "loadRatio": load_ratio,
            "adminServiceActive": _service_active(f"{service_name}.service" if service_name and not service_name.endswith(".service") else service_name),
            "nginxActive": _service_active("nginx"),
        },
        "lastBackup": stored.get("lastBackup"),
        "lastVitals": stored.get("lastVitals"),
        "lastDriveSync": stored.get("lastDriveSync"),
        "statusFile": str(status_path),
    }


def _smtp_env_path(site_root: pathlib.Path) -> pathlib.Path:
    return site_root / "data" / "smtp.env"


def info_centre_protect_enabled(site_root: pathlib.Path | None = None) -> bool:
    """Master-admin flag: enforce view-only / watermark deterrents for Information Centre."""
    if site_root is not None:
        _load_env_file(_smtp_env_path(site_root))
    raw = (os.environ.get("RWA_INFO_CENTRE_PROTECT") or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def read_platform_settings(site_root: pathlib.Path) -> dict:
    """Return editable platform settings (never include raw SMTP password)."""
    _load_env_file(_smtp_env_path(site_root))
    status = smtp_status(site_root)
    return {
        "smtp": {
            "provider": status["provider"] or "gmail",
            "host": status["host"] or "smtp.gmail.com",
            "port": status["port"] or 587,
            "user": status["user"] or "housingcolonysanyard@gmail.com",
            "from": status["from"] or "housingcolonysanyard@gmail.com",
            "passwordSet": status["passwordSet"],
            "configured": status["configured"],
        },
        "otpTtl": status["otpTtl"],
        "superadminUser": (os.environ.get("RWA_SUPERADMIN_USER") or "admin").strip() or "admin",
        "envFile": status["envFile"],
        "ops": read_ops_settings(site_root),
        "infoCentreProtect": info_centre_protect_enabled(site_root),
    }


def save_platform_settings(site_root: pathlib.Path, payload: dict, conn: sqlite3.Connection | None = None) -> dict:
    """Write selected keys to data/smtp.env and apply to process env."""
    data_dir = site_root / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    path = _smtp_env_path(site_root)

    existing: dict[str, str] = {}
    if path.is_file():
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            existing[key.strip()] = value.strip().strip("'").strip('"')

    smtp = payload.get("smtp") if isinstance(payload.get("smtp"), dict) else {}
    mapping = {
        "RWA_SMTP_PROVIDER": str(smtp.get("provider") or payload.get("provider") or existing.get("RWA_SMTP_PROVIDER") or "gmail").strip(),
        "RWA_SMTP_HOST": str(smtp.get("host") or payload.get("host") or existing.get("RWA_SMTP_HOST") or "smtp.gmail.com").strip(),
        "RWA_SMTP_PORT": str(smtp.get("port") or payload.get("port") or existing.get("RWA_SMTP_PORT") or "587").strip(),
        "RWA_SMTP_USER": str(smtp.get("user") or payload.get("user") or existing.get("RWA_SMTP_USER") or "housingcolonysanyard@gmail.com").strip(),
        "RWA_SMTP_FROM": str(smtp.get("from") or payload.get("from") or existing.get("RWA_SMTP_FROM") or "housingcolonysanyard@gmail.com").strip(),
        "RWA_OTP_TTL": str(payload.get("otpTtl") or existing.get("RWA_OTP_TTL") or "600").strip(),
    }
    if payload.get("superadminUser"):
        mapping["RWA_SUPERADMIN_USER"] = str(payload["superadminUser"]).strip().lower()

    if "infoCentreProtect" in payload:
        flag = str(payload.get("infoCentreProtect") or "").strip().lower()
        mapping["RWA_INFO_CENTRE_PROTECT"] = (
            "1" if flag in {"1", "true", "yes", "on"} else "0"
        )

    ops_payload = payload.get("ops") if isinstance(payload.get("ops"), dict) else {}
    if ops_payload:
        mapping.update(_ops_settings_to_env(ops_payload))

    new_pass = str(smtp.get("password") or payload.get("smtpPassword") or "").strip()
    if new_pass:
        mapping["RWA_SMTP_PASS"] = new_pass
    elif "RWA_SMTP_PASS" in existing:
        mapping["RWA_SMTP_PASS"] = existing["RWA_SMTP_PASS"]

    # Preserve unrelated keys
    for key, value in existing.items():
        if key not in mapping and (key.startswith("RWA_") or key in _OPS_ENV_KEYS):
            mapping[key] = value

    # Drive keys live in data/drive.env (keeps SA path out of smtp noise).
    _DRIVE_KEYS = ("DRIVE_ENABLED", "DRIVE_FOLDER_ID", "DRIVE_RETAIN_DAYS", "GOOGLE_APPLICATION_CREDENTIALS")
    drive_path = data_dir / "drive.env"
    drive_existing = _read_env_map(drive_path)
    drive_map = {
        "DRIVE_ENABLED": mapping.pop("DRIVE_ENABLED", drive_existing.get("DRIVE_ENABLED", "0")),
        "DRIVE_FOLDER_ID": mapping.pop("DRIVE_FOLDER_ID", drive_existing.get("DRIVE_FOLDER_ID", "")),
        "DRIVE_RETAIN_DAYS": mapping.pop("DRIVE_RETAIN_DAYS", drive_existing.get("DRIVE_RETAIN_DAYS", "14")),
        "GOOGLE_APPLICATION_CREDENTIALS": drive_existing.get(
            "GOOGLE_APPLICATION_CREDENTIALS",
            str(data_dir / "drive-sa.json"),
        ),
    }
    if ops_payload:
        if "driveEnabled" in ops_payload:
            drive_map["DRIVE_ENABLED"] = "1" if ops_payload.get("driveEnabled") else "0"
        if "driveFolderId" in ops_payload:
            drive_map["DRIVE_FOLDER_ID"] = str(ops_payload.get("driveFolderId") or "").strip()
        if "driveRetainDays" in ops_payload:
            try:
                drive_map["DRIVE_RETAIN_DAYS"] = str(int(ops_payload.get("driveRetainDays") or 14))
            except (TypeError, ValueError):
                drive_map["DRIVE_RETAIN_DAYS"] = "14"

    lines = [
        "# Housing Colony Sanyard portal settings (managed via Super admin → Settings).",
        "# Do not commit this file with real secrets.",
        "",
    ]
    for key in _SETTINGS_KEYS:
        if key in mapping and key != "RWA_SMTP_PASS":
            lines.append(f"{key}={mapping[key]}")
    if mapping.get("RWA_SMTP_PASS"):
        lines.append(f"RWA_SMTP_PASS={mapping['RWA_SMTP_PASS']}")
    lines.append("")
    lines.append("# Ops: backups, vitals alerts (managed via Super admin → Settings)")
    for key in _OPS_ENV_KEYS:
        if key in _DRIVE_KEYS:
            continue
        if key in mapping:
            lines.append(f"{key}={mapping[key]}")
    for key, value in sorted(mapping.items()):
        if key in _SETTINGS_KEYS or key in _OPS_ENV_KEYS or key == "RWA_SMTP_PASS" or key in _DRIVE_KEYS:
            continue
        lines.append(f"{key}={value}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass

    drive_lines = [
        "# Google Drive off-box backup (managed via Super admin → Settings).",
        "# Place service account JSON at data/drive-sa.json (chmod 600).",
        "",
    ]
    for key in _DRIVE_KEYS:
        drive_lines.append(f"{key}={drive_map.get(key, '')}")
    drive_path.write_text("\n".join(drive_lines) + "\n", encoding="utf-8")
    try:
        drive_path.chmod(0o600)
    except OSError:
        pass

    for key, value in mapping.items():
        os.environ[key] = value
    for key, value in drive_map.items():
        os.environ[key] = value

    # Optional super-admin password rotate
    sa_pass = str(payload.get("superadminPassword") or "").strip()
    if sa_pass and conn is not None:
        from init_rwa_db import hash_password

        username = mapping.get("RWA_SUPERADMIN_USER") or "admin"
        now = utc_now()
        row = conn.execute("SELECT username FROM portal_accounts WHERE username = ?", (username,)).fetchone()
        if row:
            conn.execute(
                "UPDATE portal_accounts SET password_hash=?, updated_at=? WHERE username=?",
                (hash_password(sa_pass), now, username),
            )
        else:
            conn.execute(
                """
                INSERT INTO portal_accounts(username, password_hash, house_id, is_superadmin, created_at, updated_at)
                VALUES (?, ?, ?, 1, ?, ?)
                """,
                (username, hash_password(sa_pass), SUPERADMIN_HOUSE_ID, now, now),
            )
        conn.commit()

    return read_platform_settings(site_root)

def rwa_db_path(site_root: pathlib.Path) -> pathlib.Path:
    return site_root / "data" / "rwa.db"


def open_rwa(site_root: pathlib.Path) -> sqlite3.Connection:
    path = rwa_db_path(site_root)
    ensure_db(path, seed=True)
    # Load data/smtp.env + vapid.env early so secrets / Web Push keys are available.
    try:
        _load_env_file(pathlib.Path(site_root) / "data" / "smtp.env")
        _load_env_file(pathlib.Path(site_root) / "data" / "vapid.env")
        _load_env_file(pathlib.Path(site_root) / "data" / "ai.env")
        _load_env_file(pathlib.Path(site_root) / "data" / "apple-wallet.env")
        _load_env_file(pathlib.Path(site_root) / "data" / "google-wallet.env")
    except Exception:
        pass
    try:
        import rwa_push as _rwa_push

        _rwa_push.ensure_vapid_keys(pathlib.Path(site_root))
    except Exception:
        pass
    conn = connect(path)
    # Migrate-safe: ensure portal_accounts + revisions + superadmin exist on older DBs
    try:
        conn.execute("SELECT 1 FROM portal_accounts LIMIT 1")
    except sqlite3.OperationalError:
        from init_rwa_db import init_schema

        init_schema(conn)
    else:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS resident_revisions (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              house_id TEXT NOT NULL,
              changed_at TEXT NOT NULL,
              changed_by_house_id TEXT,
              changed_by_name TEXT,
              change_source TEXT NOT NULL DEFAULT 'profile',
              snapshot_before TEXT NOT NULL,
              snapshot_after TEXT NOT NULL,
              changed_fields TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_revisions_house ON resident_revisions(house_id, id DESC)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_revisions_changed ON resident_revisions(changed_at DESC)"
        )
        conn.commit()
        ensure_resident_profile_columns(conn)
        ensure_bank_account_columns(conn)
        ensure_otp_pending_columns(conn)
        ensure_notice_pin_order(conn)
        ensure_notice_shares_table(conn)
        ensure_notice_engagement_tables(conn)
        ensure_household_members_table(conn)
        ensure_access_events_table(conn)
        ensure_grievances_table(conn)
        ensure_info_documents_table(conn)
        ensure_colony_works_table(conn)
        ensure_work_quote_tables(conn)
        ensure_colony_campaigns_tables(conn)
        ensure_meeting_proceedings_table(conn)
        ensure_resolution_votes_tables(conn)
        ensure_entitlements_schema(conn)
        ensure_report_templates_table(conn)
        ensure_bilingual_content_columns(conn)
        ensure_payment_records_tables(conn)
        ensure_no_dues_requests_table(conn)
        ensure_no_objection_requests_table(conn)
        ensure_document_attestations_table(conn)
        ensure_treasury_columns(conn)
        ensure_messages_and_push_tables(conn)
        ensure_msg_likes_and_ai(conn)
        try:
            import rwa_vault as _rwa_vault

            _rwa_vault.ensure_vault_tables(conn)
            _rwa_vault.backfill_from_existing(conn, site_root)
            _rwa_vault.dedupe_catalog(conn)
        except Exception:
            pass
        try:
            import rwa_payments as _rwa_payments

            _rwa_payments.reconcile_orphan_receipts(conn, site_root)
        except Exception:
            pass
        try:
            repair_missing_info_files(conn, site_root)
        except Exception:
            pass
        try:
            import rwa_colony_services as _rwa_colony_services

            _rwa_colony_services.ensure_colony_services_seed(conn)
        except Exception:
            pass
        migrate_roman_plot_ids(conn)
        ensure_superadmin_account(conn)
        try:
            ensure_persistent_sessions_once(conn)
        except Exception:
            pass
    return conn


def ensure_persistent_sessions_once(conn: sqlite3.Connection) -> None:
    """One-time: extend active sessions to the long-lived 'until Sign out' TTL."""
    flagged = conn.execute(
        "SELECT value FROM meta WHERE key = 'sessions_persistent_v1'"
    ).fetchone()
    if flagged:
        return
    now = datetime.now(timezone.utc)
    new_expires = _session_expiry_iso(now)
    conn.execute(
        """
        UPDATE sessions
        SET expires_at = ?
        WHERE expires_at > ?
        """,
        (new_expires, now.replace(microsecond=0).isoformat().replace("+00:00", "Z")),
    )
    conn.execute(
        "INSERT OR REPLACE INTO meta(key, value) VALUES ('sessions_persistent_v1', ?)",
        (utc_now(),),
    )
    conn.commit()


def ensure_household_ready(conn: sqlite3.Connection) -> None:
    ensure_household_members_table(conn)
    household.ensure_household_codes(conn)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS rwa_schema_flags (
          key TEXT PRIMARY KEY,
          applied_at TEXT NOT NULL
        )
        """
    )
    flag = conn.execute(
        "SELECT 1 FROM rwa_schema_flags WHERE key = 'sync_primary_from_residents_v1'"
    ).fetchone()
    if not flag:
        household.backfill_primary_from_residents(conn)
        conn.execute(
            "INSERT OR REPLACE INTO rwa_schema_flags(key, applied_at) VALUES (?, ?)",
            ("sync_primary_from_residents_v1", utc_now()),
        )
        conn.commit()


def is_superadmin_resident(r: dict | None) -> bool:
    if not r:
        return False
    return str(r.get("house_id") or "") == SUPERADMIN_HOUSE_ID or bool(r.get("superAdmin"))


def mask_email(email: str | None) -> str:
    if not email or "@" not in email:
        return ""
    local, _, domain = email.partition("@")
    if len(local) <= 2:
        shown = local[:1] + "*"
    else:
        shown = local[:2] + "*" * max(1, len(local) - 2)
    return f"{shown}@{domain}"


def row_to_dict(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    return {k: row[k] for k in row.keys()}


def find_resident(conn: sqlite3.Connection, house_id: str, *, include_inactive: bool = False) -> dict | None:
    hid = normalize_house_id(house_id)
    status_clause = "" if include_inactive else " AND status = 'active'"
    row = conn.execute(
        f"SELECT * FROM residents WHERE house_id = ? COLLATE NOCASE{status_clause}",
        (hid,),
    ).fetchone()
    if row:
        return row_to_dict(row)
    # Accept legacy slash form (33/34) when DB has hyphen form (33-34)
    legacy = (house_id or "").strip().upper().replace(" ", "")
    if "/" in legacy:
        alt = normalize_house_id(legacy)
        if alt != hid:
            row = conn.execute(
                f"SELECT * FROM residents WHERE house_id = ? COLLATE NOCASE{status_clause}",
                (alt,),
            ).fetchone()
            if row:
                return row_to_dict(row)
    # Accept legacy roman suffix 12B(i) if somehow still present in DB
    if "(" in legacy and ")" in legacy:
        row = conn.execute(
            f"SELECT * FROM residents WHERE house_id = ? COLLATE NOCASE{status_clause}",
            (legacy,),
        ).fetchone()
        if row:
            return row_to_dict(row)
        # lowercase roman variant historically stored
        lower_roman = re.sub(
            r"\(([IVX]+)\)",
            lambda m: f"({m.group(1).lower()})",
            legacy,
            flags=re.I,
        )
        if lower_roman != legacy:
            row = conn.execute(
                f"SELECT * FROM residents WHERE house_id = ? COLLATE NOCASE{status_clause}",
                (lower_roman,),
            ).fetchone()
            if row:
                return row_to_dict(row)
    row = conn.execute(
        f"SELECT * FROM residents WHERE plot_no = ? COLLATE NOCASE{status_clause}",
        (house_id.strip(),),
    ).fetchone()
    return row_to_dict(row)


def _resident_snapshot(r: dict) -> dict:
    return {
        "houseId": r.get("house_id") or r.get("houseId"),
        "plotNo": r.get("plot_no") or r.get("plotNo"),
        "section": r.get("section"),
        "name": r.get("name") or "",
        "title": r.get("title") or "",
        "profession": r.get("profession") or "",
        "employmentStatus": r.get("employment_status") or r.get("employmentStatus") or "unknown",
        "officialTitle": r.get("official_title") or r.get("officialTitle") or "",
        "email": r.get("email") or "",
        "phone": r.get("phone") or "",
        "role": r.get("role") or "resident",
        "status": r.get("status") or "active",
        "notes": r.get("notes") or "",
    }


def record_resident_revision(
    conn: sqlite3.Connection,
    *,
    house_id: str,
    before: dict,
    after: dict,
    actor: dict | None = None,
    change_source: str = "profile",
) -> list[str]:
    fields = []
    for key in ("name", "title", "profession", "employmentStatus", "officialTitle", "email", "phone", "role", "status", "notes", "section", "plotNo"):
        if (before.get(key) or "") != (after.get(key) or ""):
            fields.append(key)
    if not fields:
        return []
    actor = actor or {}
    conn.execute(
        """
        INSERT INTO resident_revisions(
          house_id, changed_at, changed_by_house_id, changed_by_name,
          change_source, snapshot_before, snapshot_after, changed_fields
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            house_id,
            utc_now(),
            actor.get("houseId") or actor.get("house_id"),
            actor.get("name") or actor.get("houseId") or "system",
            change_source,
            json.dumps(before, ensure_ascii=False),
            json.dumps(after, ensure_ascii=False),
            json.dumps(fields),
        ),
    )
    return fields


def list_resident_revisions(
    conn: sqlite3.Connection,
    *,
    house_id: str | None = None,
    limit: int = 100,
) -> list[dict]:
    limit = max(1, min(int(limit or 100), 500))
    if house_id:
        hid = normalize_house_id(house_id)
        rows = conn.execute(
            """
            SELECT * FROM resident_revisions
            WHERE house_id = ? COLLATE NOCASE
            ORDER BY id DESC LIMIT ?
            """,
            (hid, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT * FROM resident_revisions
            WHERE house_id != ?
            ORDER BY id DESC LIMIT ?
            """,
            (SUPERADMIN_HOUSE_ID, limit),
        ).fetchall()
    out = []
    for r in rows:
        try:
            before = json.loads(r["snapshot_before"] or "{}")
            after = json.loads(r["snapshot_after"] or "{}")
            fields = json.loads(r["changed_fields"] or "[]")
        except json.JSONDecodeError:
            before, after, fields = {}, {}, []
        out.append(
            {
                "id": r["id"],
                "houseId": r["house_id"],
                "changedAt": r["changed_at"],
                "changedByHouseId": r["changed_by_house_id"] or "",
                "changedByName": r["changed_by_name"] or "",
                "source": r["change_source"],
                "fields": fields,
                "before": before,
                "after": after,
            }
        )
    return out


def send_otp_email(email: str | None, code: str, house_id: str, site_root: pathlib.Path | None = None) -> dict:
    cfg = load_smtp_config(site_root)
    if not email:
        return {"channel": "dev", "devCode": True, "reason": "no_email"}
    if not cfg["configured"]:
        return {
            "channel": "dev",
            "devCode": True,
            "reason": "smtp_not_configured",
            "hint": "Set RWA_SMTP_PASS (Gmail App Password) in data/smtp.env",
        }
    try:
        msg = EmailMessage()
        msg["Subject"] = "Housing Colony Sanyard — code for resident login"
        msg["From"] = f"Housing Colony Sanyard RWA <{cfg['from']}>"
        msg["To"] = email
        msg["Reply-To"] = cfg["from"]
        msg.set_content(
            f"Your one-time code for resident login is: {code}\n\n"
            f"Plot: {house_id}\n"
            f"It expires in {OTP_TTL_SECONDS // 60} minutes.\n"
            "If you did not request this, ignore this email.\n\n"
            "— Residents Welfare Association\n"
            "  Housing Colony Sanyard, Mandi\n"
        )
        with smtplib.SMTP(cfg["host"], cfg["port"], timeout=25) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.ehlo()
            smtp.login(cfg["user"], cfg["password"])
            smtp.send_message(msg)
        return {"channel": "email", "from": cfg["from"]}
    except Exception as exc:  # noqa: BLE001
        return {"channel": "dev", "devCode": True, "error": str(exc)}


def create_otp(
    conn: sqlite3.Connection,
    house_id: str,
    email: str | None,
    site_root: pathlib.Path | None = None,
    *,
    member_id: str | None = None,
    pending_email: str | None = None,
    pending_phone: str | None = None,
) -> dict:
    ensure_otp_pending_columns(conn)
    ensure_household_members_table(conn)
    code = f"{secrets.randbelow(1_000_000):06d}"
    now = datetime.now(timezone.utc)
    expires = (now + timedelta(seconds=OTP_TTL_SECONDS)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    delivery_email = (pending_email or email or "").strip().lower() or None
    conn.execute(
        """
        INSERT INTO otp_challenges(
          house_id, member_id, code_hash, email_masked, expires_at, attempts, consumed, created_at,
          pending_email, pending_phone
        )
        VALUES (?, ?, ?, ?, ?, 0, 0, ?, ?, ?)
        """,
        (
            house_id,
            member_id,
            hash_otp(code),
            mask_email(delivery_email),
            expires,
            utc_now(),
            pending_email,
            pending_phone,
        ),
    )
    conn.commit()
    delivery = send_otp_email(delivery_email, code, house_id, site_root=site_root)
    result = {
        "houseId": house_id,
        "memberId": member_id,
        "emailMasked": mask_email(delivery_email),
        "expiresAt": expires,
        "ttlSeconds": OTP_TTL_SECONDS,
        "delivery": delivery["channel"],
        "pendingContact": bool(pending_email or pending_phone),
    }
    if delivery.get("devCode"):
        result["devCode"] = code
        result["hint"] = delivery.get("hint") or delivery.get("error") or "SMTP not configured — use devCode"
    return result


def verify_otp(
    conn: sqlite3.Connection,
    house_id: str,
    code: str,
    *,
    member_id: str | None = None,
) -> dict | None:
    ensure_otp_pending_columns(conn)
    ensure_household_members_table(conn)
    hid = normalize_house_id(house_id)
    row = conn.execute(
        """
        SELECT * FROM otp_challenges
        WHERE house_id = ? AND consumed = 0
        ORDER BY id DESC LIMIT 1
        """,
        (hid,),
    ).fetchone()
    if not row:
        return None
    expires = datetime.fromisoformat(str(row["expires_at"]).replace("Z", "+00:00"))
    if expires < datetime.now(timezone.utc):
        return None
    if int(row["attempts"] or 0) >= 5:
        return None
    conn.execute("UPDATE otp_challenges SET attempts = attempts + 1 WHERE id = ?", (row["id"],))
    if hash_otp(code.strip()) != row["code_hash"]:
        conn.commit()
        return None
    conn.execute("UPDATE otp_challenges SET consumed = 1 WHERE id = ?", (row["id"],))
    conn.commit()

    pending_email = None
    pending_phone = None
    try:
        pending_email = (row["pending_email"] or "").strip() or None
        pending_phone = (row["pending_phone"] or "").strip() or None
    except (KeyError, IndexError, TypeError):
        pass

    otp_member_id = None
    try:
        otp_member_id = (row["member_id"] or "").strip() or None
    except (KeyError, IndexError, TypeError):
        pass
    mid = (member_id or otp_member_id or "").strip() or None

    contact_updated = False
    if mid and (pending_email or pending_phone):
        try:
            household.apply_member_contacts(
                conn, mid, email=pending_email, phone=pending_phone
            )
            contact_updated = True
        except ValueError:
            contact_updated = False
    elif pending_email or pending_phone:
        try:
            apply_login_contacts(
                conn,
                hid,
                email=pending_email,
                phone=pending_phone,
            )
            contact_updated = True
        except ValueError:
            contact_updated = False

    resident = find_resident(conn, hid)
    if not resident:
        return None
    member = household.get_member(conn, mid) if mid else household.primary_member(conn, hid)
    if mid and (not member or member.get("house_id") != hid):
        return None
    if member and (member.get("status") or "active") != "active":
        return None
    sess = create_session_for_resident(conn, resident, member=member)
    if contact_updated:
        sess["contactUpdated"] = True
    return sess


def _session_expiry_iso(from_dt: datetime | None = None) -> str:
    base = from_dt or datetime.now(timezone.utc)
    return (base + timedelta(seconds=SESSION_TTL_SECONDS)).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def touch_session(conn: sqlite3.Connection, token: str, *, current_expires: str | None = None) -> str:
    """Sliding expiry: keep the session alive while the user keeps using the portal."""
    now = datetime.now(timezone.utc)
    new_expires = _session_expiry_iso(now)
    should_extend = True
    if current_expires:
        try:
            expires = datetime.fromisoformat(str(current_expires).replace("Z", "+00:00"))
            remaining = (expires - now).total_seconds()
            # Only rewrite when less than half the TTL remains (avoids a write on every request).
            should_extend = remaining < (SESSION_TTL_SECONDS * 0.5)
        except ValueError:
            should_extend = True
    if should_extend:
        conn.execute(
            "UPDATE sessions SET expires_at = ? WHERE token = ?",
            (new_expires, token),
        )
        conn.commit()
        return new_expires
    return current_expires or new_expires


def session_from_token(conn: sqlite3.Connection, token: str | None) -> dict | None:
    if not token:
        return None
    ensure_household_members_table(conn)
    row = conn.execute("SELECT * FROM sessions WHERE token = ?", (token,)).fetchone()
    if not row:
        return None
    expires = datetime.fromisoformat(str(row["expires_at"]).replace("Z", "+00:00"))
    if expires < datetime.now(timezone.utc):
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
        conn.commit()
        return None
    resident = find_resident(conn, row["house_id"])
    if not resident:
        return None
    member = None
    try:
        mid = (row["member_id"] or "").strip() or None
    except (KeyError, IndexError, TypeError):
        mid = None
    if mid:
        member = household.get_member(conn, mid)
        if member and (member.get("status") or "active") != "active":
            return None
    if not member and resident.get("house_id") != SUPERADMIN_HOUSE_ID:
        member = household.primary_member(conn, row["house_id"])
    expires_at = touch_session(conn, token, current_expires=row["expires_at"])
    return {
        "token": token,
        "expiresAt": expires_at,
        "resident": public_actor(conn, resident, member=member),
    }


def destroy_session(conn: sqlite3.Connection, token: str | None) -> None:
    if not token:
        return
    conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
    conn.commit()


def public_resident(r: dict, member: dict | None = None) -> dict:
    super_admin = str(r.get("house_id") or "") == SUPERADMIN_HOUSE_ID
    household_name = r.get("name") or ""
    is_ob = bool(int(r.get("is_office_bearer") or 0)) or bool(str(r.get("official_title") or "").strip()) or (
        (r.get("role") or "") == "admin"
    ) or super_admin
    is_mem = bool(int(r.get("is_ec_member") or 0)) or is_ob or super_admin
    ec_member_id = str(r.get("ec_member_id") or "").strip() or None
    out = {
        "houseId": r.get("house_id"),
        "plotNo": r.get("plot_no"),
        "section": r.get("section"),
        "name": r.get("name"),
        "title": r.get("title") or "",
        "profession": r.get("profession") or "",
        "employmentStatus": r.get("employment_status") or "unknown",
        "officialTitle": r.get("official_title") or "",
        "email": r.get("email") or "",
        "phone": r.get("phone") or "",
        "role": r.get("role") or "resident",
        "status": r.get("status") or "active",
        "notes": r.get("notes") or "",
        "superAdmin": super_admin,
        "householdName": household_name,
        "memberId": None,
        "relation": "owner" if not super_admin else "",
        "relationLabel": "Owner" if not super_admin else "",
        "isPrimary": True,
        "isPrimaryDelegate": False,
        "canManageHousehold": True,
        "viewOnly": False,
        "isEcMember": is_mem,
        "isOfficeBearer": is_ob,
        "isEcAdmin": (r.get("role") or "") == "admin" or super_admin,
        "ecMemberId": ec_member_id,
        "holdsEcSeat": True if super_admin else False,
        "entitlements": [],
        "hasPhoto": False,
        "photoUrl": "",
        "authbuddyLinked": False,
        "authbuddyUsername": None,
    }
    if member and not super_admin:
        pub = household.public_member(member, include_contacts=True)
        out["memberId"] = pub.get("id")
        out["name"] = pub.get("name") or out["name"]
        out["title"] = pub.get("title") or ""
        out["email"] = pub.get("email") or ""
        out["phone"] = pub.get("phone") or ""
        out["relation"] = pub.get("relation") or "other"
        out["relationLabel"] = pub.get("relationLabel") or ""
        out["identityLabel"] = pub.get("identityLabel") or ""
        out["isPrimary"] = bool(pub.get("isPrimary"))
        out["isPrimaryDelegate"] = bool(pub.get("isPrimaryDelegate"))
        out["canManageHousehold"] = bool(pub.get("canManage") or pub.get("isPrimary")) and not bool(pub.get("viewOnly"))
        out["viewOnly"] = bool(pub.get("viewOnly"))
        out["hasPhoto"] = bool(pub.get("hasPhoto"))
        out["photoUrl"] = pub.get("photoUrl") or ""
        out["authbuddyLinked"] = bool(pub.get("authbuddyLinked"))
        out["authbuddyUsername"] = pub.get("authbuddyUsername")
        plot_is_ec = is_mem
        out["plotIsEc"] = plot_is_ec
        mid = str(out["memberId"] or "").strip()
        seat = ec_member_id or ""
        if plot_is_ec:
            if seat:
                out["holdsEcSeat"] = bool(mid) and mid == seat and not out["viewOnly"]
            else:
                out["holdsEcSeat"] = bool(out["isPrimary"]) and not out["viewOnly"]
        else:
            out["holdsEcSeat"] = False
        # Strip plot-level EC from logins that do not hold the seat.
        if not out["holdsEcSeat"]:
            out["role"] = "resident"
            out["isEcAdmin"] = False
            out["isOfficeBearer"] = False
            out["isEcMember"] = False
            out["officialTitle"] = ""
        if out["viewOnly"]:
            out["role"] = "resident"
            out["isEcAdmin"] = False
            out["canManageHousehold"] = False
            out["officialTitle"] = ""
            out["holdsEcSeat"] = False
    elif super_admin:
        out["holdsEcSeat"] = True
    return out


def public_actor(conn: sqlite3.Connection, r: dict, member: dict | None = None) -> dict:
    """public_resident plus effective entitlements."""
    return entitlements.enrich_actor(conn, public_resident(r, member=member))


def normalize_phone(raw: str | None) -> str | None:
    """Normalize Indian mobiles to digits; store as 10-digit local or +91…."""
    if raw is None:
        return None
    digits = re.sub(r"\D", "", str(raw).strip())
    if not digits:
        return None
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    if len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    if len(digits) != 10:
        # Keep international / other formats lightly cleaned
        cleaned = re.sub(r"[^\d+]", "", str(raw).strip())
        return cleaned[:20] or None
    return digits


def validate_email(raw: str | None) -> str:
    email = str(raw or "").strip().lower()
    if not email or not EMAIL_RE.match(email):
        raise ValueError("Enter a valid email address")
    return email


def contact_gaps(resident: dict | None) -> dict:
    r = resident or {}
    missing_email = not str(r.get("email") or "").strip()
    missing_phone = not str(r.get("phone") or "").strip()
    return {
        "missingEmail": missing_email,
        "missingPhone": missing_phone,
        "needsContact": missing_email or missing_phone,
    }


def prepare_pending_contacts(
    resident: dict,
    *,
    email: str | None = None,
    phone: str | None = None,
) -> dict:
    """Validate login-gate contact fields without writing the resident row.

    Returns pending values to attach to the OTP challenge. Contacts are applied
    only after the one-time code is verified.
    """
    gaps = contact_gaps(resident)
    pending_email = None
    pending_phone = None

    if gaps["missingEmail"]:
        pending_email = validate_email(email)
    if gaps["missingPhone"]:
        if not phone:
            raise ValueError("Mobile number is required for the colony register")
        normalized = normalize_phone(phone)
        if not normalized or len(re.sub(r"\D", "", normalized)) < 10:
            raise ValueError("Enter a valid 10-digit mobile number")
        pending_phone = normalized

    delivery_email = pending_email or (str(resident.get("email") or "").strip().lower() or None)
    if not delivery_email:
        raise ValueError("Email is required so we can send your login code")

    return {
        "pendingEmail": pending_email,
        "pendingPhone": pending_phone,
        "deliveryEmail": delivery_email,
        "missingEmail": gaps["missingEmail"],
        "missingPhone": gaps["missingPhone"],
    }


def apply_login_contacts(
    conn: sqlite3.Connection,
    house_id: str,
    *,
    email: str | None = None,
    phone: str | None = None,
) -> dict:
    """Fill empty email/phone from the login gate. Never overwrites existing values."""
    resident = find_resident(conn, house_id, include_inactive=False)
    if not resident:
        raise ValueError("Plot not found in colony register")
    if resident.get("house_id") == SUPERADMIN_HOUSE_ID:
        raise ValueError("Use Super admin password login")

    gaps = contact_gaps(resident)
    before = _resident_snapshot(resident)
    new_email = resident.get("email")
    new_phone = resident.get("phone")
    changed = []

    if gaps["missingEmail"]:
        if not email:
            raise ValueError("Email is required so we can send your login code")
        new_email = validate_email(email)
        changed.append("email")
    elif email and str(email).strip():
        # Ignore attempts to change an existing email at login
        pass

    if gaps["missingPhone"]:
        if not phone:
            raise ValueError("Mobile number is required for the colony register")
        normalized = normalize_phone(phone)
        if not normalized or len(re.sub(r"\D", "", normalized)) < 10:
            raise ValueError("Enter a valid 10-digit mobile number")
        new_phone = normalized
        changed.append("phone")

    if not changed:
        return resident

    now = utc_now()
    conn.execute(
        """
        UPDATE residents
        SET email = ?, phone = ?, updated_at = ?
        WHERE house_id = ?
        """,
        (new_email, new_phone, now, resident["house_id"]),
    )
    after_row = find_resident(conn, resident["house_id"], include_inactive=False) or {}
    after = _resident_snapshot(after_row)
    try:
        conn.execute(
            """
            INSERT INTO resident_revisions(
              house_id, changed_at, changed_by_house_id, changed_by_name,
              change_source, snapshot_before, snapshot_after, changed_fields
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                resident["house_id"],
                now,
                resident["house_id"],
                resident.get("name") or "",
                "login_gate",
                json.dumps(before, ensure_ascii=False),
                json.dumps(after, ensure_ascii=False),
                json.dumps(changed),
            ),
        )
    except sqlite3.Error:
        # Revisions table may be missing on very old DBs; contact update still counts.
        pass
    conn.commit()
    return after_row


def mask_phone(phone: str | None) -> str:
    digits = re.sub(r"\D", "", phone or "")
    if len(digits) < 4:
        return ""
    return f"{'*' * max(0, len(digits) - 4)}{digits[-4:]}"


def _directory_delegates(
    conn: sqlite3.Connection, house_ids: list[str]
) -> dict[str, list[dict]]:
    """Active household members (owner + delegates) for directory cards (batch)."""
    delegates_by: dict[str, list[dict]] = {}
    ids = [str(h).strip() for h in house_ids if str(h).strip()]
    if not ids:
        return delegates_by
    placeholders = ",".join("?" for _ in ids)
    try:
        ensure_household_members_table(conn)
        rows = conn.execute(
            f"""
            SELECT *
            FROM household_members
            WHERE status = 'active' AND house_id IN ({placeholders})
            ORDER BY is_primary DESC, is_primary_delegate DESC, can_manage DESC,
              CASE relation
                WHEN 'owner' THEN 0 WHEN 'spouse' THEN 1 WHEN 'parent' THEN 2
                WHEN 'child' THEN 3 ELSE 4 END,
              name COLLATE NOCASE
            """,
            ids,
        ).fetchall()
        for row in rows:
            pub = household.public_member(row, include_contacts=True)
            hid = (pub.get("houseId") or "").strip()
            name = (pub.get("name") or "").strip()
            if not hid or not name:
                continue
            delegates_by.setdefault(hid, []).append({
                "name": name,
                "identityLabel": pub.get("identityLabel") or pub.get("relationLabel") or "Delegate",
                "phone": (pub.get("phone") or "").strip(),
                "isPrimary": bool(pub.get("isPrimary")),
                "isPrimaryDelegate": bool(pub.get("isPrimaryDelegate")),
            })
    except sqlite3.OperationalError:
        pass
    return delegates_by


def _directory_household_extras(
    conn: sqlite3.Connection, house_ids: list[str]
) -> tuple[dict[str, list[dict]], dict[str, list[dict]]]:
    """Active tenants and registered vehicles for directory cards (batch)."""
    tenants_by: dict[str, list[dict]] = {}
    vehicles_by: dict[str, list[dict]] = {}
    ids = [str(h).strip() for h in house_ids if str(h).strip()]
    if not ids:
        return tenants_by, vehicles_by
    placeholders = ",".join("?" for _ in ids)
    try:
        ensure_household_tenants_table(conn)
        rows = conn.execute(
            f"""
            SELECT house_id, name
            FROM household_tenants
            WHERE status = 'active' AND house_id IN ({placeholders})
            ORDER BY name COLLATE NOCASE
            """,
            ids,
        ).fetchall()
        for row in rows:
            hid = row["house_id"] or ""
            name = (row["name"] or "").strip()
            if not hid or not name:
                continue
            tenants_by.setdefault(hid, []).append({"name": name})
    except sqlite3.OperationalError:
        pass
    try:
        import rwa_parking
        ensure_parking_passes_table(conn)
        kind_labels = getattr(rwa_parking, "KIND_LABELS", {}) or {}
        type_labels = getattr(rwa_parking, "VEHICLE_LABELS", {}) or {}
        rows = conn.execute(
            f"""
            SELECT house_id, plate_display, plate, kind, vehicle_type, status
            FROM parking_passes
            WHERE status = 'active'
              AND COALESCE(kind, 'visitor') IN ('member', 'tenant')
              AND house_id IN ({placeholders})
            ORDER BY
              CASE COALESCE(kind, 'visitor') WHEN 'member' THEN 0 ELSE 1 END,
              COALESCE(plate_display, plate) COLLATE NOCASE
            """,
            ids,
        ).fetchall()
        for row in rows:
            hid = row["house_id"] or ""
            plate = (row["plate_display"] or row["plate"] or "").strip()
            if not hid or not plate:
                continue
            kind = (row["kind"] or "member").strip().lower()
            vtype = (row["vehicle_type"] or "car").strip().lower()
            vehicles_by.setdefault(hid, []).append({
                "plate": plate,
                "kind": kind,
                "kindLabel": kind_labels.get(kind) or kind.title(),
                "vehicleType": vtype,
                "vehicleTypeLabel": type_labels.get(vtype) or vtype.replace("_", " ").title(),
            })
    except (sqlite3.OperationalError, ImportError):
        pass
    return tenants_by, vehicles_by


def directory(
    conn: sqlite3.Connection,
    *,
    include_contacts: bool = False,
    include_occupancy: bool = False,
) -> list[dict]:
    entitlements.ensure_ready(conn)
    household.ensure_household_codes(conn)
    exclude_sql, exclude_ids = system_house_exclude_sql("house_id")
    if include_contacts:
        rows = conn.execute(
            f"""
            SELECT house_id, plot_no, section, name, title, profession, employment_status,
                   official_title, is_ec_member, is_office_bearer, role, email, phone, notes, status,
                   ec_member_id, household_code
            FROM residents
            WHERE {exclude_sql}
            """,
            exclude_ids,
        ).fetchall()
    else:
        rows = conn.execute(
            f"""
            SELECT house_id, plot_no, section, name, title, profession, employment_status,
                   official_title, is_ec_member, is_office_bearer, role, email, phone, notes, status,
                   ec_member_id, household_code
            FROM residents
            WHERE status = 'active' AND {exclude_sql}
            """,
            exclude_ids,
        ).fetchall()
    photos = primary_member_photo_map(conn)
    out = []
    for r in rows:
        if (r["house_id"] or "") in SYSTEM_HOUSE_IDS:
            continue
        is_ec = (r["role"] or "") == "admin"
        is_ob = bool(int(r["is_office_bearer"] or 0)) or bool(r["official_title"] or "") or is_ec
        is_mem = bool(int(r["is_ec_member"] or 0)) or is_ob or is_ec
        photo = photos.get(r["house_id"]) or photo_fields_for_member(None, None)
        owner = household.primary_member(conn, r["house_id"])
        delegate = household.primary_delegate_member(conn, r["house_id"])
        # Master personal name: primary member, falling back to residents (dues/roster).
        owner_name = (owner or {}).get("name") or r["name"] or ""
        delegate_name = ((delegate or {}).get("name") or "").strip()
        display_name = f"{owner_name} / {delegate_name}" if delegate_name else owner_name
        seat_id = (r["ec_member_id"] or "").strip() or ((owner or {}).get("id") or "")
        seat = household.get_member(conn, seat_id) if seat_id else None
        seat_name = (seat or {}).get("name") or ""
        # Prefer primary member contacts when present; else residents (shared master).
        email = ((owner or {}).get("email") or r["email"] or "").strip()
        phone = ((owner or {}).get("phone") or r["phone"] or "").strip()
        item = {
            "houseId": r["house_id"],
            "plotNo": r["plot_no"],
            "section": r["section"],
            "name": owner_name,
            "ownerName": owner_name,
            "primaryDelegateName": delegate_name,
            "displayName": display_name,
            "householdCode": (r["household_code"] or "").strip(),
            "role": r["role"],
            "officialTitle": r["official_title"] or "",
            "isEcMember": is_mem,
            "isOfficeBearer": is_ob,
            "isEcAdmin": is_ec,
            "ecMemberId": seat_id or None,
            "ecSeatHolderName": seat_name if is_mem else "",
            "email": email,
            "phone": phone,
            "hasPhone": bool(phone),
            "hasEmail": bool(email),
            "hasPhoto": photo["hasPhoto"],
            "photoUrl": photo["photoUrl"],
            "primaryMemberId": photo.get("memberId"),
        }
        if include_contacts:
            item["title"] = (owner or {}).get("title") or r["title"] or ""
            item["profession"] = r["profession"] or ""
            item["employmentStatus"] = r["employment_status"] or "unknown"
            item["notes"] = r["notes"] or ""
            item["status"] = r["status"] or "active"
            item["entitlements"] = (
                sorted(entitlements.EC_ADMIN_ENTITLEMENTS)
                if is_ec
                else (entitlements.load_grants(conn, r["house_id"]) if is_mem else [])
            )
        out.append(item)
    house_ids = [row["houseId"] for row in out]
    delegates_by = _directory_delegates(conn, house_ids)
    tenants_by: dict[str, list[dict]] = {}
    vehicles_by: dict[str, list[dict]] = {}
    if include_occupancy:
        tenants_by, vehicles_by = _directory_household_extras(conn, house_ids)
    for item in out:
        hid = item.get("houseId") or ""
        item["delegates"] = delegates_by.get(hid) or []
        if include_occupancy:
            item["tenants"] = tenants_by.get(hid) or []
            item["vehicles"] = vehicles_by.get(hid) or []
    out.sort(
        key=lambda row: section_plot_sort_key(
            row.get("section"),
            row.get("plotNo") or row.get("houseId"),
            row.get("houseId"),
        )
    )
    return out


def roster_stats(conn: sqlite3.Connection) -> dict:
    exclude_sql, exclude_ids = system_house_exclude_sql("house_id")
    row = conn.execute(
        f"""
        SELECT
          COUNT(*) AS total,
          SUM(CASE WHEN phone IS NOT NULL AND TRIM(phone) != '' THEN 1 ELSE 0 END) AS with_phone,
          SUM(CASE WHEN email IS NOT NULL AND TRIM(email) != '' THEN 1 ELSE 0 END) AS with_email
        FROM residents WHERE status = 'active' AND {exclude_sql}
        """,
        exclude_ids,
    ).fetchone()
    total = int(row["total"] or 0) if row else 0
    with_phone = int(row["with_phone"] or 0) if row else 0
    with_email = int(row["with_email"] or 0) if row else 0
    return {
        "total": total,
        "withPhone": with_phone,
        "withEmail": with_email,
        "missingPhone": max(0, total - with_phone),
        "missingEmail": max(0, total - with_email),
    }


def enrich_payment_row(row: sqlite3.Row | dict) -> dict:
    """Derive previous/current paid & pending from ledger columns.

    Ledger: balance_prev (prior dues), fee_amount (current year), amount_received (paid),
    total_due, balance_outstanding. Payments are applied to previous dues first.
    """
    if hasattr(row, "keys"):
        data = {k: row[k] for k in row.keys()}
    else:
        data = dict(row)
    prev_total = int(data.get("balance_prev") or 0)
    year_total = int(data.get("fee_amount") or 0)
    received = int(data.get("amount_received") or 0)
    total_due = int(data.get("total_due") or (prev_total + year_total))
    outstanding = int(data.get("balance_outstanding") if data.get("balance_outstanding") is not None else (total_due - received))

    prev_paid = min(max(received, 0), max(prev_total, 0)) if prev_total > 0 else 0
    if prev_total < 0:
        # Credit balance from previous period
        prev_paid = 0
    prev_pending = max(0, prev_total - prev_paid)
    paid_toward_year = max(0, received - prev_paid)
    year_pending = max(0, year_total - paid_toward_year)

    import rwa_treasury

    out = {
        "houseId": data.get("house_id") or data.get("houseId"),
        "balancePrev": prev_total,
        "previousTotal": prev_total,
        "previousPaid": prev_paid,
        "previousPending": prev_pending,
        "feeYear": data.get("fee_year") or data.get("feeYear") or 2026,
        "feeAmount": year_total,
        "currentYearTotal": year_total,
        "currentYearPaid": paid_toward_year,
        "currentYearPending": year_pending,
        "totalDue": total_due,
        "amountReceived": received,
        "balanceOutstanding": outstanding,
        "pendingDues": outstanding,
        "remarks": data.get("remarks") or "",
        "asOf": data.get("as_of") or data.get("asOf"),
        "source": data.get("source"),
    }
    out.update(rwa_treasury.treasury_fields_from_row(data))
    return out


def latest_payment_for(conn: sqlite3.Connection, house_id: str) -> dict | None:
    row = conn.execute(
        """
        SELECT pr.*, pl.as_of, pl.source
        FROM payment_rows pr
        JOIN payment_ledgers pl ON pl.id = pr.ledger_id
        WHERE pr.house_id = ?
        ORDER BY pl.as_of DESC, pr.id DESC
        LIMIT 1
        """,
        (house_id,),
    ).fetchone()
    if not row:
        return None
    return enrich_payment_row(row)


def payments_summary(conn: sqlite3.Connection) -> dict:
    row = conn.execute(
        """
        SELECT
          COUNT(*) AS households,
          COALESCE(SUM(total_due),0) AS total_due,
          COALESCE(SUM(amount_received),0) AS total_received,
          COALESCE(SUM(balance_outstanding),0) AS total_outstanding
        FROM payment_rows
        WHERE ledger_id = (SELECT id FROM payment_ledgers ORDER BY as_of DESC, id DESC LIMIT 1)
        """
    ).fetchone()
    return {
        "households": row["households"] if row else 0,
        "totalDue": row["total_due"] if row else 0,
        "totalReceived": row["total_received"] if row else 0,
        "totalOutstanding": row["total_outstanding"] if row else 0,
        "bank": get_primary_bank(conn),
    }


def get_primary_bank(conn: sqlite3.Connection) -> dict | None:
    ensure_bank_account_columns(conn)
    row = conn.execute(
        "SELECT * FROM bank_accounts WHERE is_primary = 1 ORDER BY id ASC LIMIT 1"
    ).fetchone()
    if not row:
        row = conn.execute("SELECT * FROM bank_accounts ORDER BY id ASC LIMIT 1").fetchone()
    if not row:
        return None
    qr_name = (row["qr_filename"] if "qr_filename" in row.keys() else None) or ""
    return {
        "id": row["id"],
        "label": row["label"] or "RWA collection",
        "bankName": row["bank_name"] or "",
        "accountNo": row["account_no"] or "",
        "ifsc": row["ifsc"] or "",
        "upiId": (row["upi_id"] if "upi_id" in row.keys() else None) or "",
        "upiName": (row["upi_name"] if "upi_name" in row.keys() else None) or "",
        "qrFilename": qr_name,
        "hasQr": bool(qr_name),
        "qrUrl": "/api/rwa/bank/qr" if qr_name else "",
        # snake_case aliases for older UI
        "bank_name": row["bank_name"] or "",
        "account_no": row["account_no"] or "",
    }


def update_primary_bank(conn: sqlite3.Connection, payload: dict) -> dict:
    """EC: create or update the primary collection account + UPI details."""
    ensure_bank_account_columns(conn)
    bank_name = str(payload.get("bankName") or payload.get("bank_name") or "").strip()
    account_no = str(payload.get("accountNo") or payload.get("account_no") or "").strip()
    ifsc = str(payload.get("ifsc") or "").strip().upper().replace(" ", "")
    label = str(payload.get("label") or "RWA collection").strip() or "RWA collection"
    upi_id = str(payload.get("upiId") or payload.get("upi_id") or "").strip()
    upi_name = str(payload.get("upiName") or payload.get("upi_name") or "").strip()

    if len(bank_name) < 2:
        raise ValueError("Bank name is required")
    if len(account_no) < 4:
        raise ValueError("Account number is required")
    if len(ifsc) < 4:
        raise ValueError("IFSC is required")
    if upi_id and "@" not in upi_id:
        raise ValueError("UPI ID should look like name@bank")

    existing = conn.execute(
        "SELECT id, qr_filename FROM bank_accounts WHERE is_primary = 1 ORDER BY id ASC LIMIT 1"
    ).fetchone()
    if existing:
        conn.execute(
            """
            UPDATE bank_accounts
            SET label = ?, bank_name = ?, account_no = ?, ifsc = ?, upi_id = ?, upi_name = ?
            WHERE id = ?
            """,
            (label, bank_name, account_no, ifsc, upi_id or None, upi_name or None, existing["id"]),
        )
    else:
        conn.execute(
            """
            INSERT INTO bank_accounts(label, bank_name, account_no, ifsc, is_primary, upi_id, upi_name)
            VALUES (?, ?, ?, ?, 1, ?, ?)
            """,
            (label, bank_name, account_no, ifsc, upi_id or None, upi_name or None),
        )
    conn.commit()
    return get_primary_bank(conn)


def bank_qr_dir(site_root: pathlib.Path) -> pathlib.Path:
    path = pathlib.Path(site_root) / "data" / "payments"
    path.mkdir(parents=True, exist_ok=True)
    return path


PROFILE_PHOTO_SIZE = 280
PROFILE_PHOTO_QUALITY = 72
PROFILE_PHOTO_MAX_UPLOAD = 8_000_000  # 8 MB pre-crop upload


def photo_fields_for_member(member_id: str | None, filename: str | None) -> dict:
    return household.photo_fields_for_member(member_id, filename)


def primary_member_photo_map(conn: sqlite3.Connection) -> dict[str, dict]:
    return household.primary_member_photo_map(conn)


def member_photo_map(conn: sqlite3.Connection, member_ids: list[str] | None = None) -> dict[str, dict]:
    return household.member_photo_map(conn, member_ids)


def profile_photo_dir(site_root: pathlib.Path) -> pathlib.Path:
    path = pathlib.Path(site_root) / "data" / "profile-photos"
    path.mkdir(parents=True, exist_ok=True)
    return path


def profile_photo_path(site_root: pathlib.Path, filename: str | None) -> pathlib.Path | None:
    if not filename:
        return None
    name = pathlib.Path(str(filename)).name
    if name != str(filename) or ".." in name or "/" in name or "\\" in name:
        return None
    if not re.fullmatch(r"photo_[A-Za-z0-9_-]+\.webp", name):
        return None
    path = profile_photo_dir(site_root) / name
    return path if path.is_file() else None


def _optimize_profile_photo_bytes(raw: bytes) -> bytes:
    """Square-ish crop already done client-side; re-encode light WebP for phones."""
    try:
        from PIL import Image
    except ImportError as exc:  # pragma: no cover
        raise ValueError("Image processing unavailable on server") from exc
    from io import BytesIO

    try:
        img = Image.open(BytesIO(raw))
        img.load()
    except Exception as exc:
        raise ValueError("Could not read image") from exc
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGBA") if "A" in img.getbands() else img.convert("RGB")
    # Center-crop to square then resize
    w, h = img.size
    if w <= 0 or h <= 0:
        raise ValueError("Invalid image size")
    side = min(w, h)
    left = (w - side) // 2
    top = (h - side) // 2
    img = img.crop((left, top, left + side, top + side))
    resample = Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS
    if side > PROFILE_PHOTO_SIZE:
        img = img.resize((PROFILE_PHOTO_SIZE, PROFILE_PHOTO_SIZE), resample)
    elif side < PROFILE_PHOTO_SIZE:
        img = img.resize((PROFILE_PHOTO_SIZE, PROFILE_PHOTO_SIZE), resample)
    if img.mode == "RGBA":
        background = Image.new("RGB", img.size, (246, 241, 230))
        background.paste(img, mask=img.split()[-1])
        img = background
    else:
        img = img.convert("RGB")
    out = BytesIO()
    img.save(out, format="WEBP", quality=PROFILE_PHOTO_QUALITY, method=6)
    data = out.getvalue()
    if len(data) > 120_000:
        # Second pass more aggressive
        out = BytesIO()
        img.save(out, format="WEBP", quality=58, method=6)
        data = out.getvalue()
    if not data:
        raise ValueError("Could not encode photo")
    return data


def save_member_photo(
    conn: sqlite3.Connection,
    site_root: pathlib.Path,
    member_id: str,
    *,
    file_storage,
    actor: dict | None = None,
) -> dict:
    ensure_household_members_table(conn)
    mid = (member_id or "").strip()
    member = household.get_member(conn, mid)
    if not member:
        raise ValueError("Member not found")
    actor = actor or {}
    actor_mid = actor.get("memberId") or actor.get("member_id")
    same_self = actor_mid and actor_mid == mid
    managing = household.can_actor_manage_household(actor, member.get("house_id") or "")
    if not same_self and not managing and not actor.get("superAdmin"):
        raise ValueError("Not allowed to update this photo")
    if household.actor_is_view_only(actor) and not same_self:
        raise ValueError("View-only access cannot change photos")
    if file_storage is None or not getattr(file_storage, "filename", None):
        raise ValueError("Photo file required")
    raw = file_storage.read()
    if not raw:
        raise ValueError("Empty upload")
    if len(raw) > PROFILE_PHOTO_MAX_UPLOAD:
        raise ValueError("Photo must be under 8 MB")
    optimized = _optimize_profile_photo_bytes(raw)
    safe_id = re.sub(r"[^a-zA-Z0-9_-]", "", mid)[:48] or secrets.token_hex(4)
    filename = f"photo_{safe_id}.webp"
    dest_dir = profile_photo_dir(site_root)
    dest = dest_dir / filename
    old_name = (member.get("photo_filename") or "").strip()
    dest.write_bytes(optimized)
    if old_name and old_name != filename:
        old_path = profile_photo_path(site_root, old_name)
        if old_path and old_path != dest:
            try:
                old_path.unlink()
            except OSError:
                pass
    now = utc_now()
    conn.execute(
        "UPDATE household_members SET photo_filename = ?, updated_at = ? WHERE id = ?",
        (filename, now, mid),
    )
    conn.commit()
    return household.public_member(household.get_member(conn, mid), include_contacts=True)


def clear_member_photo(
    conn: sqlite3.Connection,
    site_root: pathlib.Path,
    member_id: str,
    *,
    actor: dict | None = None,
) -> dict:
    ensure_household_members_table(conn)
    mid = (member_id or "").strip()
    member = household.get_member(conn, mid)
    if not member:
        raise ValueError("Member not found")
    actor = actor or {}
    actor_mid = actor.get("memberId") or actor.get("member_id")
    same_self = actor_mid and actor_mid == mid
    managing = household.can_actor_manage_household(actor, member.get("house_id") or "")
    if not same_self and not managing and not actor.get("superAdmin"):
        raise ValueError("Not allowed to remove this photo")
    old_name = (member.get("photo_filename") or "").strip()
    if old_name:
        path = profile_photo_path(site_root, old_name)
        if path:
            try:
                path.unlink()
            except OSError:
                pass
    now = utc_now()
    conn.execute(
        "UPDATE household_members SET photo_filename = NULL, updated_at = ? WHERE id = ?",
        (now, mid),
    )
    conn.commit()
    return household.public_member(household.get_member(conn, mid), include_contacts=True)


NOTICE_ALLOWED_IMAGE_TYPES = rwa_media.ALLOWED_IMAGE_TYPES


def notice_images_root(site_root: pathlib.Path) -> pathlib.Path:
    return pathlib.Path(site_root) / "data" / "notice-images"


def notice_image_url(notice_id: str | None, image_file: str | None) -> str | None:
    if not notice_id or not image_file:
        return None
    return f"/api/rwa/notices/{notice_id}/image"


def notice_image_path(
    site_root: pathlib.Path,
    notice_id: str,
    image_file: str | None,
) -> pathlib.Path | None:
    if not notice_id or not image_file:
        return None
    safe_id = re.sub(r"[^A-Za-z0-9_-]", "", str(notice_id))
    name = pathlib.Path(str(image_file)).name
    if name != str(image_file) or ".." in name:
        return None
    path = notice_images_root(site_root) / safe_id / name
    return path if path.is_file() else None


def _optimize_notice_image(raw: bytes) -> tuple[bytes, str]:
    return rwa_media.optimize_portal_card_image(raw)


def save_notice_image(
    conn: sqlite3.Connection,
    site_root: pathlib.Path,
    *,
    notice_id: str,
    data: bytes,
    filename: str,
    mime: str,
) -> str:
    ensure_notice_image_column(conn)
    if len(data) > rwa_media.UPLOAD_MAX_BYTES:
        raise ValueError("Image exceeds size limit (5 MB)")
    mime = mime or mimetypes.guess_type(filename)[0] or "application/octet-stream"
    if mime not in rwa_media.ALLOWED_IMAGE_TYPES:
        raise ValueError("Image must be JPEG, PNG, or WebP")
    data, _out_mime = _optimize_notice_image(data)
    safe_name = "photo.webp"
    safe_id = re.sub(r"[^A-Za-z0-9_-]", "", str(notice_id))
    dest_dir = notice_images_root(site_root) / safe_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    for old in dest_dir.glob("photo.*"):
        old.unlink(missing_ok=True)
    (dest_dir / safe_name).write_bytes(data)
    conn.execute("UPDATE notices SET image_file = ? WHERE id = ?", (safe_name, notice_id))
    conn.commit()
    return safe_name


def get_notice_image(
    conn: sqlite3.Connection,
    site_root: pathlib.Path,
    notice_id: str,
    *,
    public_only: bool = False,
    signed_in: bool = False,
) -> tuple[pathlib.Path, str] | None:
    ensure_notice_image_column(conn)
    row = conn.execute(
        "SELECT image_file, status, audience FROM notices WHERE id = ?",
        (notice_id,),
    ).fetchone()
    if not row or not row["image_file"]:
        return None
    if (row["status"] or "") != "published":
        return None
    if public_only and _notice_audience(row["audience"]) != "public":
        return None
    if not public_only and not signed_in and _notice_audience(row["audience"]) != "public":
        return None
    path = notice_image_path(site_root, notice_id, row["image_file"])
    if not path:
        return None
    mime = mimetypes.guess_type(path.name)[0] or "image/webp"
    return path, mime


def bank_qr_path(site_root: pathlib.Path, filename: str | None) -> pathlib.Path | None:
    if not filename:
        return None
    name = pathlib.Path(str(filename)).name
    if name != str(filename) or ".." in name:
        return None
    path = bank_qr_dir(site_root) / name
    return path if path.is_file() else None


def save_bank_qr(
    conn: sqlite3.Connection,
    site_root: pathlib.Path,
    *,
    file_storage,
) -> dict:
    """EC: store uploaded UPI QR image and link it to the primary bank row."""
    ensure_bank_account_columns(conn)
    if file_storage is None or not getattr(file_storage, "filename", None):
        raise ValueError("QR image file required")

    original = pathlib.Path(file_storage.filename).name.lower()
    ext = pathlib.Path(original).suffix
    allowed = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
    if ext not in allowed:
        raise ValueError("QR must be a PNG, JPG, or WebP image")

    # Read with size cap (~2.5 MB)
    data = file_storage.read()
    if not data:
        raise ValueError("Empty upload")
    if len(data) > 2_500_000:
        raise ValueError("QR image must be under 2.5 MB")
    # Basic magic-byte check
    if ext == ".png" and not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("File is not a valid PNG")
    if ext in {".jpg", ".jpeg"} and not data.startswith(b"\xff\xd8"):
        raise ValueError("File is not a valid JPEG")
    if ext == ".webp" and data[0:4] != b"RIFF":
        raise ValueError("File is not a valid WebP")

    filename = f"upi-qr{ext}"
    dest = bank_qr_dir(site_root) / filename
    # Remove older QR variants
    for old in bank_qr_dir(site_root).glob("upi-qr.*"):
        try:
            old.unlink()
        except OSError:
            pass
    dest.write_bytes(data)

    existing = conn.execute(
        "SELECT id FROM bank_accounts WHERE is_primary = 1 ORDER BY id ASC LIMIT 1"
    ).fetchone()
    if not existing:
        # Ensure a bank row exists so QR has somewhere to hang.
        conn.execute(
            """
            INSERT INTO bank_accounts(label, bank_name, account_no, ifsc, is_primary, qr_filename)
            VALUES ('RWA collection', 'Bank of Baroda — Mandi', '09640100004511', 'BARB0MANDIX', 1, ?)
            """,
            (filename,),
        )
    else:
        conn.execute(
            "UPDATE bank_accounts SET qr_filename = ? WHERE id = ?",
            (filename, existing["id"]),
        )
    conn.commit()
    return get_primary_bank(conn)


def clear_bank_qr(conn: sqlite3.Connection, site_root: pathlib.Path) -> dict:
    ensure_bank_account_columns(conn)
    row = conn.execute(
        "SELECT id, qr_filename FROM bank_accounts WHERE is_primary = 1 ORDER BY id ASC LIMIT 1"
    ).fetchone()
    if row and row["qr_filename"]:
        path = bank_qr_path(site_root, row["qr_filename"])
        if path and path.is_file():
            try:
                path.unlink()
            except OSError:
                pass
        conn.execute("UPDATE bank_accounts SET qr_filename = NULL WHERE id = ?", (row["id"],))
        conn.commit()
    for leftover in bank_qr_dir(site_root).glob("upi-qr.*"):
        try:
            leftover.unlink()
        except OSError:
            pass
    return get_primary_bank(conn)


# --- Information Centre -----------------------------------------------------

INFO_DOC_CATEGORIES = (
    ("bylaws", "Bylaws & rules"),
    ("circulars", "Circulars"),
    ("minutes", "Meeting minutes"),
    ("forms", "Forms"),
    ("policies", "Policies"),
    ("guidelines", "Guidelines"),
    ("financial", "Accounts & finance"),
    ("general", "General"),
)

INFO_DOC_MIME = {
    ".pdf": "application/pdf",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xls": "application/vnd.ms-excel",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".ppt": "application/vnd.ms-powerpoint",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".odt": "application/vnd.oasis.opendocument.text",
    ".ods": "application/vnd.oasis.opendocument.spreadsheet",
    ".txt": "text/plain",
    ".rtf": "application/rtf",
    ".csv": "text/csv",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".html": "text/html",
    ".htm": "text/html",
}

INFO_INLINE_EXTS = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".gif", ".html", ".htm", ".txt"}
INFO_MAX_BYTES = 15_000_000  # 15 MB
INFO_DOC_TYPES = frozenset({"file", "html", "link"})


def normalize_info_external_url(raw: str | None) -> str:
    """Accept http(s) URLs or same-site root-relative paths for link documents."""
    text = str(raw or "").strip()
    if not text:
        raise ValueError("Web link URL required")
    if len(text) > 2000:
        raise ValueError("Web link is too long")
    lower = text.lower()
    if lower.startswith(("javascript:", "data:", "vbscript:", "file:")):
        raise ValueError("Unsupported link type")
    # Same-site path: /documents/act.html
    if text.startswith("/") and not text.startswith("//"):
        if " " in text or "\\" in text or "/../" in f"{text}/":
            raise ValueError("Enter a valid site path or web link")
        return text
    # Allow paste without scheme
    if re.match(r"^[\w.-]+\.[a-zA-Z]{2,}(/.*)?$", text):
        text = "https://" + text
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Web link must start with http:// or https:// (or a /site/path)")
    if not parsed.netloc or " " in text:
        raise ValueError("Enter a valid web link (URL)")
    return text


def guess_info_link_mime(url: str) -> str:
    """Guess preview mime from the URL path (pdf / image / html page)."""
    path = (urlparse(url).path if "://" in url else url).lower()
    # root-relative
    if "://" not in url:
        path = url.split("?", 1)[0].split("#", 1)[0].lower()
    else:
        path = (urlparse(url).path or "").lower()
    ext = pathlib.Path(path).suffix
    if ext in INFO_DOC_MIME:
        return INFO_DOC_MIME[ext]
    return "text/html"


def info_centre_categories() -> list[dict]:
    return [{"id": cid, "label": label} for cid, label in INFO_DOC_CATEGORIES]


def _info_folder_public(
    row: sqlite3.Row | dict,
    *,
    doc_count: int | None = None,
    include_allowlist: bool = False,
) -> dict:
    if hasattr(row, "keys"):
        data = {k: row[k] for k in row.keys()}
    else:
        data = dict(row)
    parent_id = data.get("parent_id") or data.get("parentId") or ""
    audience = _info_audience(data.get("audience"))
    allowed = _parse_member_ids(
        data.get("allowed_member_ids")
        if "allowed_member_ids" in data
        else data.get("allowedMemberIds")
    )
    out = {
        "id": data.get("id"),
        "title": data.get("title") or "",
        "titleHi": data.get("title_hi") or data.get("titleHi") or "",
        "summary": data.get("summary") or "",
        "parentId": parent_id or None,
        "sortOrder": int(data.get("sort_order") or data.get("sortOrder") or 100),
        "audience": audience,
        "audienceLabel": _info_audience_label(audience),
        "createdAt": data.get("created_at") or data.get("createdAt") or "",
        "updatedAt": data.get("updated_at") or data.get("updatedAt") or "",
        "createdBy": data.get("created_by") or data.get("createdBy") or "",
    }
    if include_allowlist:
        out["allowedMemberIds"] = allowed
    if doc_count is not None:
        out["docCount"] = int(doc_count)
    return out


def _parse_member_ids(raw: Any) -> list[str]:
    """Normalize allowed_member_ids from JSON text, list, or comma-separated string."""
    if raw is None or raw == "":
        return []
    if isinstance(raw, (list, tuple, set)):
        items = list(raw)
    else:
        text = str(raw).strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                items = parsed
            else:
                items = [x.strip() for x in text.split(",") if x.strip()]
        except (json.JSONDecodeError, TypeError, ValueError):
            items = [x.strip() for x in text.split(",") if x.strip()]
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        mid = str(item or "").strip()
        if not mid or mid in seen:
            continue
        seen.add(mid)
        out.append(mid)
    return out


def _info_audience(raw: str | None) -> str:
    key = (raw or "all").strip().lower()
    return key if key in {"all", "ec", "restricted"} else "all"


def _info_audience_label(audience: str) -> str:
    if audience == "ec":
        return "EC only"
    if audience == "restricted":
        return "Restricted"
    return "All members"


def _validate_member_ids(conn: sqlite3.Connection, member_ids: list[str]) -> list[str]:
    """Keep only active household member ids; raise if any unknown."""
    ensure_household_members_table(conn)
    ids = _parse_member_ids(member_ids)
    if not ids:
        return []
    placeholders = ",".join("?" for _ in ids)
    rows = conn.execute(
        f"""
        SELECT id FROM household_members
        WHERE id IN ({placeholders}) AND status = 'active'
        """,
        ids,
    ).fetchall()
    found = {r["id"] for r in rows}
    missing = [mid for mid in ids if mid not in found]
    if missing:
        raise ValueError(f"Unknown or inactive member id(s): {', '.join(missing[:5])}")
    return [mid for mid in ids if mid in found]


def _resolve_info_audience_payload(
    conn: sqlite3.Connection,
    payload: dict,
    existing: sqlite3.Row | None,
    *,
    audience_key: str = "audience",
    members_key: str = "allowed_member_ids",
) -> tuple[str, str]:
    """Return (audience, allowed_member_ids_json) for upsert."""
    if "audience" in payload:
        audience = _info_audience(payload.get("audience"))
    elif existing and audience_key in existing.keys():
        audience = _info_audience(existing[audience_key])
    else:
        audience = "all"

    raw_ids = None
    if "allowedMemberIds" in payload or "allowed_member_ids" in payload:
        raw_ids = payload.get("allowedMemberIds", payload.get("allowed_member_ids"))
    elif existing and members_key in existing.keys():
        raw_ids = existing[members_key]

    if audience != "restricted":
        return audience, "[]"
    allowed = _validate_member_ids(conn, _parse_member_ids(raw_ids))
    return audience, json.dumps(allowed)


def actor_info_member_id(conn: sqlite3.Connection, actor: dict | None) -> str | None:
    """Resolve the member id used for Info Centre ACL grants."""
    if not actor:
        return None
    mid = (actor.get("memberId") or actor.get("member_id") or "").strip()
    if mid:
        return mid
    house_id = (actor.get("houseId") or actor.get("house_id") or "").strip()
    if not house_id or actor.get("superAdmin"):
        return None
    primary = household.primary_member(conn, house_id)
    if not primary:
        return None
    return str(primary.get("id") or "").strip() or None


def can_view_info_acl(
    conn: sqlite3.Connection,
    actor: dict | None,
    *,
    audience: str,
    allowed_member_ids: Any,
    manage_info: bool = False,
) -> bool:
    if manage_info or (actor and actor.get("superAdmin")):
        return True
    if not actor:
        return False
    aud = _info_audience(audience)
    if aud == "all":
        return True
    if aud == "ec":
        return entitlements.is_ec_member(actor)
    if aud == "restricted":
        mid = actor_info_member_id(conn, actor)
        if not mid:
            return False
        return mid in set(_parse_member_ids(allowed_member_ids))
    return False


def _folder_chain_ids(conn: sqlite3.Connection, folder_id: str | None) -> list[str]:
    """Folder id plus ancestors (child → … → root)."""
    fid = (folder_id or "").strip()
    if not fid:
        return []
    parents = _folder_parent_map(conn)
    chain: list[str] = []
    seen: set[str] = set()
    cur: str | None = fid
    while cur:
        if cur in seen:
            break
        seen.add(cur)
        chain.append(cur)
        cur = parents.get(cur)
    return chain


def can_view_info_folder(
    conn: sqlite3.Connection,
    actor: dict | None,
    folder_row: sqlite3.Row | dict | None,
    *,
    manage_info: bool = False,
    folders_by_id: dict[str, sqlite3.Row | dict] | None = None,
) -> bool:
    """True when actor may browse this folder (including ancestor ACLs)."""
    if manage_info or (actor and actor.get("superAdmin")):
        return True
    if not folder_row:
        return False
    if hasattr(folder_row, "keys"):
        data = {k: folder_row[k] for k in folder_row.keys()}
    else:
        data = dict(folder_row)
    folder_id = str(data.get("id") or "").strip()
    if not folder_id:
        return False

    by_id = folders_by_id
    if by_id is None:
        rows = conn.execute("SELECT * FROM info_folders").fetchall()
        by_id = {r["id"]: r for r in rows}

    for fid in _folder_chain_ids(conn, folder_id):
        row = by_id.get(fid)
        if row is None:
            return False
        if hasattr(row, "keys"):
            fdata = {k: row[k] for k in row.keys()}
        else:
            fdata = dict(row)
        if not can_view_info_acl(
            conn,
            actor,
            audience=fdata.get("audience") or "all",
            allowed_member_ids=fdata.get("allowed_member_ids") or "[]",
            manage_info=False,
        ):
            return False
    return True


def can_view_info_document(
    conn: sqlite3.Connection,
    actor: dict | None,
    doc_row: sqlite3.Row | dict,
    *,
    manage_info: bool = False,
    folders_by_id: dict[str, sqlite3.Row | dict] | None = None,
) -> bool:
    """True when actor may see this document (folder chain ∩ document ACL)."""
    if manage_info or (actor and actor.get("superAdmin")):
        return True
    if not actor:
        return False
    if hasattr(doc_row, "keys"):
        data = {k: doc_row[k] for k in doc_row.keys()}
    else:
        data = dict(doc_row)
    if (data.get("status") or "") != "published":
        return False
    folder_id = (data.get("folder_id") or data.get("folderId") or "").strip() or None
    if folder_id:
        by_id = folders_by_id
        if by_id is None:
            rows = conn.execute("SELECT * FROM info_folders").fetchall()
            by_id = {r["id"]: r for r in rows}
        folder_row = by_id.get(folder_id)
        if folder_row is None:
            return False
        if not can_view_info_folder(
            conn, actor, folder_row, manage_info=False, folders_by_id=by_id
        ):
            return False
    return can_view_info_acl(
        conn,
        actor,
        audience=data.get("audience") or "all",
        allowed_member_ids=(
            data.get("allowed_member_ids")
            if "allowed_member_ids" in data
            else data.get("allowedMemberIds")
        ),
        manage_info=False,
    )


def list_info_access_candidates(conn: sqlite3.Connection) -> list[dict]:
    """Active household members for the restricted-access picker."""
    ensure_household_members_table(conn)
    rows = conn.execute(
        """
        SELECT m.id, m.house_id, m.name, m.relation, m.is_primary
        FROM household_members m
        WHERE m.status = 'active'
          AND m.house_id != ?
        ORDER BY m.house_id COLLATE NOCASE,
          m.is_primary DESC,
          CASE m.relation
            WHEN 'owner' THEN 0 WHEN 'spouse' THEN 1 WHEN 'parent' THEN 2
            WHEN 'child' THEN 3 ELSE 4 END,
          m.name COLLATE NOCASE
        """,
        (SUPERADMIN_HOUSE_ID,),
    ).fetchall()
    out: list[dict] = []
    for r in rows:
        pub = household.public_member(r, include_contacts=False)
        out.append({
            "id": pub.get("id"),
            "houseId": pub.get("houseId"),
            "name": pub.get("name") or "",
            "relation": pub.get("relation") or "",
            "relationLabel": pub.get("relationLabel") or "",
            "isPrimary": bool(pub.get("isPrimary")),
            "label": f"{pub.get('houseId') or ''} — {pub.get('name') or ''} ({pub.get('relationLabel') or ''})".strip(" —"),
        })
    return out


def _ensure_info_folder_parent_column(conn: sqlite3.Connection) -> None:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(info_folders)").fetchall()}
    if "parent_id" not in cols:
        conn.execute("ALTER TABLE info_folders ADD COLUMN parent_id TEXT")
        conn.commit()
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_info_folders_parent
          ON info_folders(parent_id, sort_order, title COLLATE NOCASE)
        """
    )


def _folder_parent_map(conn: sqlite3.Connection) -> dict[str, str | None]:
    _ensure_info_folder_parent_column(conn)
    rows = conn.execute("SELECT id, parent_id FROM info_folders").fetchall()
    out: dict[str, str | None] = {}
    for r in rows:
        pid = (r["parent_id"] or "").strip() or None
        out[r["id"]] = pid
    return out


def _folder_subtree_ids(conn: sqlite3.Connection, folder_id: str) -> list[str]:
    """Return folder_id plus all descendant folder ids."""
    fid = (folder_id or "").strip()
    if not fid:
        return []
    parents = _folder_parent_map(conn)
    if fid not in parents:
        return [fid]
    children: dict[str | None, list[str]] = {}
    for child_id, parent_id in parents.items():
        children.setdefault(parent_id, []).append(child_id)
    out: list[str] = []
    stack = [fid]
    seen: set[str] = set()
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        out.append(cur)
        for kid in sorted(children.get(cur) or []):
            stack.append(kid)
    return out


def _folder_would_cycle(conn: sqlite3.Connection, folder_id: str, new_parent_id: str | None) -> bool:
    fid = (folder_id or "").strip()
    parent = (new_parent_id or "").strip() or None
    if not fid or not parent:
        return False
    if parent == fid:
        return True
    parents = _folder_parent_map(conn)
    seen: set[str] = set()
    cur: str | None = parent
    while cur:
        if cur == fid:
            return True
        if cur in seen:
            break
        seen.add(cur)
        cur = parents.get(cur)
    return False


def list_info_folders(
    conn: sqlite3.Connection,
    *,
    with_counts: bool = True,
    actor: dict | None = None,
    manage_info: bool = False,
    include_allowlist: bool = False,
) -> list[dict]:
    ensure_info_documents_table(conn)
    _ensure_info_folder_parent_column(conn)
    rows = conn.execute(
        """
        SELECT f.*,
               (SELECT COUNT(*) FROM info_documents d WHERE d.folder_id = f.id) AS doc_count
        FROM info_folders f
        ORDER BY f.sort_order ASC, f.title COLLATE NOCASE ASC
        """
    ).fetchall()
    folders_by_id = {r["id"]: r for r in rows}
    show_allowlist = include_allowlist or manage_info
    by_id: dict[str, dict] = {}
    for r in rows:
        if actor is not None and not manage_info:
            if not can_view_info_folder(
                conn, actor, r, manage_info=False, folders_by_id=folders_by_id
            ):
                continue
        count = int(r["doc_count"] or 0) if with_counts else None
        by_id[r["id"]] = _info_folder_public(
            r, doc_count=count, include_allowlist=show_allowlist
        )
    for folder in by_id.values():
        parts = [folder["title"]]
        cur = folder.get("parentId")
        guard = 0
        while cur and cur in by_id and guard < 40:
            parts.append(by_id[cur]["title"])
            cur = by_id[cur].get("parentId")
            guard += 1
        folder["pathLabel"] = " / ".join(reversed(parts))
        folder["depth"] = max(0, len(parts) - 1)
    return list(by_id.values())


def get_info_folder(
    conn: sqlite3.Connection,
    folder_id: str,
    *,
    actor: dict | None = None,
    manage_info: bool = False,
    include_allowlist: bool = False,
) -> dict | None:
    ensure_info_documents_table(conn)
    _ensure_info_folder_parent_column(conn)
    fid = (folder_id or "").strip()
    if not fid:
        return None
    row = conn.execute("SELECT * FROM info_folders WHERE id = ?", (fid,)).fetchone()
    if not row:
        return None
    if actor is not None and not manage_info:
        if not can_view_info_folder(conn, actor, row, manage_info=False):
            return None
    n = conn.execute(
        "SELECT COUNT(*) AS n FROM info_documents WHERE folder_id = ?",
        (fid,),
    ).fetchone()["n"]
    out = _info_folder_public(
        row,
        doc_count=int(n or 0),
        include_allowlist=include_allowlist or manage_info,
    )
    folders = {
        f["id"]: f
        for f in list_info_folders(
            conn,
            with_counts=False,
            actor=actor if not manage_info else None,
            manage_info=manage_info,
            include_allowlist=False,
        )
    }
    if fid in folders:
        out["pathLabel"] = folders[fid].get("pathLabel") or out["title"]
        out["depth"] = folders[fid].get("depth") or 0
        out["parentId"] = folders[fid].get("parentId")
    return out


def upsert_info_folder(
    conn: sqlite3.Connection,
    payload: dict,
    *,
    actor: dict | None = None,
) -> dict:
    ensure_info_documents_table(conn)
    _ensure_info_folder_parent_column(conn)
    folder_id = (payload.get("id") or "").strip() or f"folder_{secrets.token_hex(6)}"
    existing = conn.execute("SELECT * FROM info_folders WHERE id = ?", (folder_id,)).fetchone()
    title = payload.get("title") if "title" in payload else (existing["title"] if existing else None)
    title = str(title or "").strip()
    if len(title) < 2:
        raise ValueError("Folder title required")
    title_hi = (
        payload.get("titleHi")
        if "titleHi" in payload or "title_hi" in payload
        else (existing["title_hi"] if existing and "title_hi" in existing.keys() else "")
    )
    if "title_hi" in payload and "titleHi" not in payload:
        title_hi = payload.get("title_hi")
    title_hi = str(title_hi or "").strip()[:160]
    summary = payload.get("summary") if "summary" in payload else (existing["summary"] if existing else "")
    summary = str(summary or "").strip()[:400]
    sort_order = payload.get("sortOrder", payload.get("sort_order"))
    if sort_order is None:
        sort_order = existing["sort_order"] if existing else 100
    try:
        sort_order = int(sort_order)
    except (TypeError, ValueError):
        sort_order = 100

    parent_raw = None
    if "parentId" in payload or "parent_id" in payload:
        parent_raw = payload.get("parentId", payload.get("parent_id"))
    elif existing and "parent_id" in existing.keys():
        parent_raw = existing["parent_id"]
    parent_id = str(parent_raw or "").strip() or None
    if parent_id in {"", "none", "unfiled", "null", "root"}:
        parent_id = None
    if parent_id:
        parent_row = conn.execute("SELECT id FROM info_folders WHERE id = ?", (parent_id,)).fetchone()
        if not parent_row:
            raise ValueError("Parent folder not found")
        if _folder_would_cycle(conn, folder_id, parent_id):
            raise ValueError("Cannot move a folder into itself or its subfolder")

    audience, allowed_json = _resolve_info_audience_payload(conn, payload, existing)

    now = utc_now()
    created_at = existing["created_at"] if existing else now
    created_by = (
        (existing["created_by"] if existing and existing["created_by"] else None)
        or (actor or {}).get("houseId")
        or (actor or {}).get("house_id")
        or ""
    )
    conn.execute(
        """
        INSERT INTO info_folders(
          id, title, title_hi, summary, parent_id, sort_order,
          audience, allowed_member_ids, created_by, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
          title=excluded.title,
          title_hi=excluded.title_hi,
          summary=excluded.summary,
          parent_id=excluded.parent_id,
          sort_order=excluded.sort_order,
          audience=excluded.audience,
          allowed_member_ids=excluded.allowed_member_ids,
          updated_at=excluded.updated_at
        """,
        (
            folder_id,
            title,
            title_hi,
            summary,
            parent_id,
            sort_order,
            audience,
            allowed_json,
            created_by,
            created_at,
            now,
        ),
    )
    conn.commit()
    out = get_info_folder(conn, folder_id, manage_info=True, include_allowlist=True)
    if not out:
        raise ValueError("Folder not found after save")
    return out


def delete_info_folder(
    conn: sqlite3.Connection,
    folder_id: str,
    *,
    site_root: pathlib.Path | None = None,
) -> None:
    ensure_info_documents_table(conn)
    _ensure_info_folder_parent_column(conn)
    fid = (folder_id or "").strip()
    if not fid:
        raise ValueError("folder id required")
    row = conn.execute("SELECT id, parent_id FROM info_folders WHERE id = ?", (fid,)).fetchone()
    if not row:
        raise ValueError("Folder not found")
    parent_id = (row["parent_id"] or "").strip() or None
    # Re-home direct child folders under this folder's parent (or root).
    conn.execute(
        "UPDATE info_folders SET parent_id = ?, updated_at = ? WHERE parent_id = ?",
        (parent_id, utc_now(), fid),
    )
    # Move documents in this folder to the parent folder (or Unfiled).
    conn.execute(
        "UPDATE info_documents SET folder_id = ? WHERE folder_id = ?",
        (parent_id, fid),
    )
    conn.execute("DELETE FROM info_folders WHERE id = ?", (fid,))
    conn.commit()
    if site_root is not None:
        try:
            share = pathlib.Path(site_root) / info_share_static_relpath(folder_id=fid)
            if share.is_file():
                share.unlink()
        except Exception:
            pass


def _resolve_folder_id(conn: sqlite3.Connection, raw: str | None, *, allow_empty: bool = True) -> str | None:
    """Validate folder id; empty string clears the folder."""
    if raw is None:
        return None
    fid = str(raw).strip()
    if not fid or fid in {"", "none", "unfiled", "null"}:
        if allow_empty:
            return ""
        return None
    row = conn.execute("SELECT id FROM info_folders WHERE id = ?", (fid,)).fetchone()
    if not row:
        raise ValueError("Unknown folder")
    return fid


def info_centre_dir(site_root: pathlib.Path) -> pathlib.Path:
    path = pathlib.Path(site_root) / "data" / "info-centre"
    path.mkdir(parents=True, exist_ok=True)
    return path


def info_doc_dir(site_root: pathlib.Path, doc_id: str) -> pathlib.Path:
    safe = re.sub(r"[^a-zA-Z0-9_-]", "", (doc_id or "").strip())
    if not safe:
        raise ValueError("Invalid document id")
    path = info_centre_dir(site_root) / safe
    path.mkdir(parents=True, exist_ok=True)
    return path


def info_doc_file_path(site_root: pathlib.Path, doc_id: str, filename: str | None) -> pathlib.Path | None:
    if not filename:
        return None
    name = pathlib.Path(str(filename)).name
    if name != str(filename) or ".." in name or "/" in name or "\\" in name:
        return None
    try:
        path = info_doc_dir(site_root, doc_id) / name
    except ValueError:
        return None
    return path if path.is_file() else None


def _atomic_write_bytes(path: pathlib.Path, data: bytes) -> None:
    """Write via temp file then replace, so a crash cannot leave an empty target."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
    try:
        tmp.write_bytes(data)
        tmp.replace(path)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def _replace_dir_file(
    dest_dir: pathlib.Path,
    filename: str,
    data: bytes,
    *,
    keep_names: set[str] | None = None,
) -> pathlib.Path:
    """Write new file first, then remove other files (except keep_names)."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / filename
    _atomic_write_bytes(target, data)
    keep = set(keep_names or set()) | {filename}
    for old in list(dest_dir.iterdir()):
        if old.is_file() and old.name not in keep and not old.name.startswith("."):
            try:
                old.unlink()
            except OSError:
                pass
    if not target.is_file() or target.stat().st_size != len(data):
        raise ValueError("Failed to store document file on server")
    return target


def _info_category(raw: str | None) -> str:
    key = (raw or "general").strip().lower()
    allowed = {c[0] for c in INFO_DOC_CATEGORIES}
    return key if key in allowed else "general"


def _info_public(
    r: sqlite3.Row | dict,
    site_root: pathlib.Path | None = None,
    *,
    include_allowlist: bool = False,
) -> dict:
    if hasattr(r, "keys"):
        data = {k: r[k] for k in r.keys()}
    else:
        data = dict(r)
    cat = data.get("category") or "general"
    label = next((lbl for cid, lbl in INFO_DOC_CATEGORIES if cid == cat), cat)
    audience = _info_audience(data.get("audience"))
    allowed = _parse_member_ids(
        data.get("allowed_member_ids")
        if "allowed_member_ids" in data
        else data.get("allowedMemberIds")
    )
    filename = data.get("filename")
    file_missing = False
    has_file = bool(filename)
    if filename and site_root is not None:
        path = info_doc_file_path(site_root, str(data.get("id") or ""), filename)
        has_file = path is not None
        file_missing = path is None
    folder_id = (data.get("folder_id") or data.get("folderId") or "") or None
    folder_title = data.get("folder_title") or data.get("folderTitle") or ""
    folder_title_hi = data.get("folder_title_hi") or data.get("folderTitleHi") or ""
    doc_type = (data.get("doc_type") or "file").strip().lower() or "file"
    external_url = (data.get("external_url") or data.get("externalUrl") or "").strip()
    if doc_type == "link":
        has_file = bool(external_url)
        file_missing = not bool(external_url)
    out = {
        "id": data.get("id"),
        "title": data.get("title") or "",
        "titleHi": data.get("title_hi") or data.get("titleHi") or "",
        "summary": data.get("summary") or "",
        "summaryHi": data.get("summary_hi") or data.get("summaryHi") or "",
        "category": cat,
        "categoryLabel": label,
        "folderId": folder_id,
        "folderTitle": folder_title,
        "folderTitleHi": folder_title_hi,
        "docType": doc_type,
        "filename": filename,
        "originalName": data.get("original_name") or data.get("filename") or "",
        "mimeType": data.get("mime_type") or "",
        "sizeBytes": int(data.get("size_bytes") or 0),
        "externalUrl": external_url,
        "status": data.get("status") or "draft",
        "audience": audience,
        "audienceLabel": _info_audience_label(audience),
        "publishedAt": data.get("published_at"),
        "publishedBy": data.get("published_by"),
        "createdAt": data.get("created_at"),
        "updatedAt": data.get("updated_at"),
        "hasFile": has_file,
        "fileMissing": file_missing,
        "hasHtmlHi": bool(int(data.get("has_html_hi") or data.get("hasHtmlHi") or 0)),
    }
    if include_allowlist:
        out["allowedMemberIds"] = allowed
    return out


def list_info_documents(
    conn: sqlite3.Connection,
    *,
    status: str | None = "published",
    category: str | None = None,
    folder_id: str | None = None,
    as_admin: bool = False,
    actor: dict | None = None,
    site_root: pathlib.Path | None = None,
) -> list[dict]:
    ensure_info_documents_table(conn)
    status_key = (status or "published").strip().lower()
    clauses: list[str] = []
    params: list[Any] = []
    if status_key == "all":
        if not as_admin:
            clauses.append("d.status = 'published'")
    elif status_key in {"draft", "published", "archived"}:
        if status_key != "published" and not as_admin:
            raise ValueError("Admin access required for drafts")
        clauses.append("d.status = ?")
        params.append(status_key)
    else:
        raise ValueError("Invalid status filter")
    if category:
        clauses.append("d.category = ?")
        params.append(_info_category(category))
    if folder_id is not None:
        fid = str(folder_id).strip()
        if fid in {"", "unfiled", "none"}:
            clauses.append("(d.folder_id IS NULL OR d.folder_id = '')")
        else:
            subtree = _folder_subtree_ids(conn, fid)
            if len(subtree) == 1:
                clauses.append("d.folder_id = ?")
                params.append(subtree[0])
            else:
                placeholders = ",".join("?" for _ in subtree)
                clauses.append(f"d.folder_id IN ({placeholders})")
                params.extend(subtree)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = conn.execute(
        f"""
        SELECT d.*, f.title AS folder_title, f.title_hi AS folder_title_hi
        FROM info_documents d
        LEFT JOIN info_folders f ON f.id = d.folder_id
        {where}
        ORDER BY
          CASE WHEN d.folder_id IS NULL OR d.folder_id = '' THEN 1 ELSE 0 END,
          COALESCE(f.sort_order, 9999) ASC,
          COALESCE(f.title, '') COLLATE NOCASE ASC,
          CASE d.status WHEN 'published' THEN 0 WHEN 'draft' THEN 1 ELSE 2 END,
          COALESCE(d.published_at, d.updated_at) DESC,
          d.id DESC
        """,
        params,
    ).fetchall()
    folders_by_id = {r["id"]: r for r in conn.execute("SELECT * FROM info_folders").fetchall()}
    out: list[dict] = []
    for r in rows:
        if not as_admin:
            if not can_view_info_document(
                conn, actor, r, manage_info=False, folders_by_id=folders_by_id
            ):
                continue
        out.append(_info_public(r, site_root=site_root, include_allowlist=as_admin))
    return out


def get_info_document(
    conn: sqlite3.Connection,
    doc_id: str,
    *,
    as_admin: bool = False,
    actor: dict | None = None,
    site_root: pathlib.Path | None = None,
) -> dict | None:
    ensure_info_documents_table(conn)
    row = conn.execute(
        """
        SELECT d.*, f.title AS folder_title, f.title_hi AS folder_title_hi
        FROM info_documents d
        LEFT JOIN info_folders f ON f.id = d.folder_id
        WHERE d.id = ?
        """,
        (doc_id,),
    ).fetchone()
    if not row:
        return None
    if as_admin:
        return _info_public(row, site_root=site_root, include_allowlist=True)
    if not can_view_info_document(conn, actor, row, manage_info=False):
        return None
    return _info_public(row, site_root=site_root, include_allowlist=False)


def get_info_share_meta(
    conn: sqlite3.Connection,
    *,
    doc_id: str | None = None,
    folder_id: str | None = None,
    site_root: pathlib.Path | None = None,
) -> dict | None:
    """Public metadata for link previews (title/summary only; no file body).

    Published docs (including EC-only) get a titled card so WhatsApp/iMessage
    can unfurl. Drafts and unknown ids return a generic gated card.
    """
    ensure_info_documents_table(conn)
    if doc_id:
        did = (doc_id or "").strip()
        if not did:
            return None
        row = conn.execute(
            """
            SELECT d.*, f.title AS folder_title, f.title_hi AS folder_title_hi
            FROM info_documents d
            LEFT JOIN info_folders f ON f.id = d.folder_id
            WHERE d.id = ?
            """,
            (did,),
        ).fetchone()
        if not row or (row["status"] or "") != "published":
            return {
                "kind": "doc",
                "available": False,
                "id": did,
                "title": "Housing Colony Sanyard · Information Centre",
                "description": "Sign in to the residents portal to open this document.",
                "deepLink": f"/#info/doc/{did}" if did else "/#info",
                "badge": "Members only",
            }
        doc = _info_public(row, site_root=site_root)
        audience = doc.get("audience") or "all"
        # Do not leak titles of EC/restricted docs on public OG cards.
        if audience in {"ec", "restricted"}:
            return {
                "kind": "doc",
                "available": True,
                "id": doc["id"],
                "title": "Housing Colony Sanyard · Information Centre",
                "description": "Members-only document — sign in to the residents portal to open it.",
                "badge": "Members only",
                "category": "",
                "folderTitle": "",
                "docType": doc.get("docType") or "file",
                "deepLink": f"/#info/doc/{doc['id']}",
                "gated": True,
            }
        summary = (doc.get("summary") or "").strip()
        bits = [
            doc.get("folderTitle") or "",
            doc.get("categoryLabel") or "",
            doc.get("audienceLabel") or "",
            "Housing Colony Sanyard Information Centre",
        ]
        fallback = " · ".join(b for b in bits if b)
        return {
            "kind": "doc",
            "available": True,
            "id": doc["id"],
            "title": doc.get("title") or "Document",
            "description": summary or fallback,
            "badge": doc.get("audienceLabel") or "All members",
            "category": doc.get("categoryLabel") or "",
            "folderTitle": doc.get("folderTitle") or "",
            "docType": doc.get("docType") or "file",
            "deepLink": f"/#info/doc/{doc['id']}",
        }

    if folder_id:
        # Share meta must not require actor ACL — load raw folder for managers' cards.
        ensure_info_documents_table(conn)
        fid = (folder_id or "").strip()
        raw = conn.execute("SELECT * FROM info_folders WHERE id = ?", (fid,)).fetchone() if fid else None
        if not raw:
            return {
                "kind": "folder",
                "available": False,
                "id": fid,
                "title": "Housing Colony Sanyard · Information Centre",
                "description": "Sign in to the residents portal to open this folder.",
                "deepLink": "/#info",
                "badge": "Members only",
            }
        folder = _info_folder_public(raw, doc_count=None, include_allowlist=False)
        aud = folder.get("audience") or "all"
        if aud in {"ec", "restricted"}:
            return {
                "kind": "folder",
                "available": True,
                "id": folder["id"],
                "title": "Housing Colony Sanyard · Information Centre",
                "description": "Members-only folder — sign in to the residents portal to open it.",
                "badge": "Members only",
                "deepLink": f"/#info/folder/{folder['id']}",
                "gated": True,
            }
        folder_full = get_info_folder(conn, fid, manage_info=True)
        if not folder_full:
            folder_full = folder
        summary = (folder_full.get("summary") or "").strip()
        path_label = folder_full.get("pathLabel") or folder_full.get("title") or "Folder"
        count = int(folder_full.get("docCount") or 0)
        desc = summary or (
            f"{count} document{'s' if count != 1 else ''} in Information Centre · Housing Colony Sanyard"
        )
        return {
            "kind": "folder",
            "available": True,
            "id": folder_full["id"],
            "title": folder_full.get("title") or "Folder",
            "description": desc,
            "badge": path_label if path_label != folder_full.get("title") else "Folder",
            "deepLink": f"/#info/folder/{folder_full['id']}",
        }
    return None


def render_info_share_page(
    meta: dict,
    *,
    page_url: str,
    image_url: str,
    site_name: str = "Housing Colony Sanyard",
    image_width: int = 480,
    image_height: int = 480,
    auto_open_app: bool = True,
) -> str:
    """Self-contained HTML card with Open Graph / Twitter tags for crawlers."""
    title = (meta.get("title") or site_name).strip() or site_name
    description = (meta.get("description") or "Residents Welfare Association portal.").strip()
    # WhatsApp is picky about exotic punctuation in scraped titles.
    title = (
        title.replace("\u2014", "-")
        .replace("\u2013", "-")
        .replace("\u2018", "'")
        .replace("\u2019", "'")
        .replace("\u201c", '"')
        .replace("\u201d", '"')
        .replace("\u00a0", " ")
    )
    description = (
        description.replace("\u2014", "-")
        .replace("\u2013", "-")
        .replace("\u00a0", " ")
    )
    if len(title) > 70:
        title = title[:67].rstrip() + "..."
    if len(description) > 160:
        description = description[:157].rstrip() + "..."
    badge = (meta.get("badge") or "Members only").strip()
    deep = meta.get("deepLink") or "/?source=pwa#info"
    # Prefer absolute https app URL for PWA link capture (Android).
    if deep.startswith("/"):
        # Caller should pass absolute; keep relative as last resort.
        pass
    available = bool(meta.get("available"))
    kind = meta.get("kind") or "doc"
    eyebrow = "Information Centre document" if kind == "doc" else "Information Centre folder"
    if not available:
        eyebrow = "Members-only link"

    et = html.escape(title, quote=True)
    ed = html.escape(description, quote=True)
    eb = html.escape(badge)
    eu = html.escape(page_url, quote=True)
    ei = html.escape(image_url, quote=True)
    es = html.escape(site_name, quote=True)
    edeep = html.escape(deep, quote=True)
    eeyebrow = html.escape(eyebrow)
    cta = "Open in Housing Colony Sanyard app" if available else "Sign in to continue"
    deep_js = json.dumps(deep)
    # Android Intent — opens installed Chrome PWA when link handling is enabled.
    # Fragment cannot appear before #Intent, so deep link is carried in ?info=.
    intent_url = ""
    if deep.startswith("https://"):
        base = deep.split("#", 1)[0]
        without_scheme = base[len("https://") :]
        intent_url = (
            "intent://"
            + without_scheme
            + "#Intent;scheme=https;action=android.intent.action.VIEW;S.browser_fallback_url="
            + quote(deep, safe="")
            + ";end"
        )
    intent_js = json.dumps(intent_url)
    auto_script = ""
    if auto_open_app:
        auto_script = f"""
  <script>
    (function () {{
      var ua = navigator.userAgent || '';
      if (/bot|crawl|spider|slurp|whatsapp|facebook|facebot|telegram|twitter|linkedin|slack|discord|applebot|preview|embedly|pinterest|skype|meta-externalagent/i.test(ua)) return;
      location.replace({deep_js});
    }})();
  </script>"""

    open_script = f"""
  <script>
    (function () {{
      var appUrl = {deep_js};
      var intentUrl = {intent_js};
      function remember() {{
        try {{
          var m = String(appUrl).match(/[?&]info=((?:doc|folder)\\.[^&#]+)/i);
          if (!m) return;
          var parts = m[1].split('.');
          localStorage.setItem('hbc_pending_info', JSON.stringify({{
            type: parts[0].toLowerCase(),
            id: decodeURIComponent(parts.slice(1).join('.')),
            t: Date.now()
          }}));
        }} catch (e) {{}}
      }}
      function openApp(ev) {{
        remember();
        var ua = navigator.userAgent || '';
        if (intentUrl && /Android/i.test(ua)) {{
          if (ev) ev.preventDefault();
          location.href = intentUrl;
          setTimeout(function () {{ location.href = appUrl; }}, 900);
          return false;
        }}
        // iOS / desktop: same-origin https URL (may open installed PWA on some browsers)
        if (ev) ev.preventDefault();
        location.href = appUrl;
        return false;
      }}
      document.addEventListener('DOMContentLoaded', function () {{
        var btn = document.getElementById('openAppBtn');
        if (btn) btn.addEventListener('click', openApp);
        remember();
      }});
    }})();
  </script>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta property="og:title" content="{et}">
  <meta property="og:description" content="{ed}">
  <meta property="og:image" content="{ei}">
  <meta property="og:url" content="{eu}">
  <meta property="og:type" content="website">
  <meta property="og:site_name" content="{es}">
  <meta property="og:locale" content="en_IN">
  <meta property="og:image:secure_url" content="{ei}">
  <meta property="og:image:type" content="image/jpeg">
  <meta property="og:image:width" content="{int(image_width)}">
  <meta property="og:image:height" content="{int(image_height)}">
  <meta property="og:image:alt" content="{es}">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:title" content="{et}">
  <meta name="twitter:description" content="{ed}">
  <meta name="twitter:image" content="{ei}">
  <meta name="description" content="{ed}">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="robots" content="index,follow">
  <link rel="canonical" href="{eu}">
  <link rel="image_src" href="{ei}">
  <link rel="icon" href="/assets/favicon-192.png" type="image/png">
  <title>{et} · {es}</title>
  <style>
    :root {{
      --navy: #15233f;
      --ink: #1c2434;
      --muted: #5b6578;
      --line: rgba(21, 35, 63, 0.14);
      --cream: #f6f1e7;
      --card: #fffdf8;
      --green: #1f4d3a;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      min-height: 100vh;
      font-family: "Segoe UI", system-ui, -apple-system, sans-serif;
      color: var(--ink);
      background:
        radial-gradient(ellipse 80% 50% at 10% -10%, rgba(176, 138, 60, 0.18), transparent 55%),
        radial-gradient(ellipse 70% 45% at 100% 0%, rgba(31, 77, 58, 0.14), transparent 50%),
        linear-gradient(180deg, #eef2f7, var(--cream) 55%, #e8e2d4);
      display: grid;
      place-items: center;
      padding: 1.25rem;
    }}
    .card {{
      width: min(100%, 28rem);
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 18px;
      box-shadow: 0 18px 40px rgba(21, 35, 63, 0.12);
      overflow: hidden;
    }}
    .hero {{
      display: flex;
      gap: 0.9rem;
      align-items: center;
      padding: 1.15rem 1.2rem 0.95rem;
      background: linear-gradient(135deg, rgba(21, 35, 63, 0.96), rgba(31, 77, 58, 0.92));
      color: #f7f3ea;
    }}
    .hero img {{
      width: 64px;
      height: 64px;
      border-radius: 14px;
      object-fit: cover;
      background: #fff;
      flex: 0 0 auto;
    }}
    .hero .eyebrow {{
      margin: 0 0 0.2rem;
      font-size: 0.72rem;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      opacity: 0.78;
    }}
    .hero h1 {{
      margin: 0;
      font-size: 1.15rem;
      line-height: 1.3;
      font-weight: 700;
    }}
    .body {{ padding: 1rem 1.2rem 1.25rem; }}
    .badge {{
      display: inline-block;
      margin: 0 0 0.65rem;
      padding: 0.22rem 0.55rem;
      border-radius: 999px;
      font-size: 0.7rem;
      font-weight: 700;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      background: rgba(31, 77, 58, 0.12);
      color: var(--green);
    }}
    .desc {{
      margin: 0 0 1rem;
      color: var(--muted);
      font-size: 0.95rem;
      line-height: 1.45;
    }}
    .cta {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 100%;
      padding: 0.75rem 1rem;
      border-radius: 999px;
      background: var(--navy);
      color: #fff;
      text-decoration: none;
      font-weight: 650;
    }}
    .note {{
      margin: 0.75rem 0 0;
      font-size: 0.78rem;
      color: var(--muted);
      text-align: center;
    }}
  </style>
</head>
<body>
  <main class="card">
    <div class="hero">
      <img src="{ei}" width="64" height="64" alt="{es}">
      <div>
        <p class="eyebrow">{eeyebrow}</p>
        <h1>{et}</h1>
      </div>
    </div>
    <div class="body">
      <span class="badge">{eb}</span>
      <p class="desc">{ed}</p>
      <a class="cta" id="openAppBtn" href="{edeep}">{html.escape(cta)}</a>
      <p class="note">Android: tap the button — Chrome can open the installed Housing Colony Sanyard app.<br>
      iPhone: WhatsApp cannot open Home Screen apps directly; tap <b>··· → Open in Safari</b>, then the button, or open the app and sign in.</p>
      <p class="note">Residents must sign in with their house / plot number to open the full document.</p>
    </div>
  </main>
  {auto_script}
  {open_script}
</body>
</html>
"""


def info_share_static_relpath(*, doc_id: str | None = None, folder_id: str | None = None) -> str:
    if doc_id:
        safe = re.sub(r"[^a-zA-Z0-9_-]", "", str(doc_id)) or "doc"
        return f"share/doc/{safe}.html"
    if folder_id:
        safe = re.sub(r"[^a-zA-Z0-9_-]", "", str(folder_id)) or "folder"
        return f"share/folder/{safe}.html"
    return "share/index.html"


def write_info_share_static(
    site_root: pathlib.Path,
    meta: dict,
    *,
    page_url: str,
    image_url: str,
    image_width: int = 1200,
    image_height: int = 630,
) -> pathlib.Path:
    """Write a plain HTML share card under the site web root for nginx (no Flask)."""
    kind = meta.get("kind") or "doc"
    if kind == "folder":
        rel = info_share_static_relpath(folder_id=str(meta.get("id") or ""))
    else:
        rel = info_share_static_relpath(doc_id=str(meta.get("id") or ""))
    path = pathlib.Path(site_root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    html_page = render_info_share_page(
        meta,
        page_url=page_url,
        image_url=image_url,
        image_width=image_width,
        image_height=image_height,
        auto_open_app=False,
    )
    path.write_text(html_page, encoding="utf-8")
    return path


def rebuild_all_info_share_static(
    conn: sqlite3.Connection,
    site_root: pathlib.Path,
    *,
    origin: str,
) -> int:
    """Regenerate /share/doc/*.html and /share/folder/*.html for published items."""
    ensure_info_documents_table(conn)
    origin = (origin or "").rstrip("/")
    image_url = f"{origin}/assets/og-share-card.jpg?v=20260810-mhws"
    written = 0
    rows = conn.execute(
        "SELECT id FROM info_documents WHERE status = 'published'"
    ).fetchall()
    for row in rows:
        meta = get_info_share_meta(conn, doc_id=row["id"], site_root=site_root)
        if not meta or not meta.get("available"):
            continue
        page_url = f"{origin}/share/doc/{meta['id']}.html"
        meta = dict(meta)
        meta["deepLink"] = f"{origin}/?source=pwa&info=doc.{meta['id']}#info/doc/{meta['id']}"
        write_info_share_static(
            site_root,
            meta,
            page_url=page_url,
            image_url=image_url,
        )
        written += 1
    for folder in list_info_folders(conn, with_counts=True):
        meta = get_info_share_meta(conn, folder_id=folder["id"], site_root=site_root)
        if not meta:
            continue
        page_url = f"{origin}/share/folder/{meta['id']}.html"
        meta = dict(meta)
        meta["deepLink"] = f"{origin}/?source=pwa&info=folder.{meta['id']}#info/folder/{meta['id']}"
        write_info_share_static(
            site_root,
            meta,
            page_url=page_url,
            image_url=image_url,
        )
        written += 1
    return written


def repair_missing_info_files(conn: sqlite3.Connection, site_root: pathlib.Path) -> int:
    """If a doc's file is missing, copy from another doc with the same original name when unique."""
    ensure_info_documents_table(conn)
    rows = conn.execute(
        "SELECT id, filename, original_name, size_bytes FROM info_documents WHERE filename IS NOT NULL"
    ).fetchall()
    fixed = 0
    for row in rows:
        if info_doc_file_path(site_root, row["id"], row["filename"]):
            continue
        original = (row["original_name"] or "").strip()
        if not original:
            continue
        donors = [
            r for r in rows
            if r["id"] != row["id"]
            and (r["original_name"] or "").strip() == original
            and info_doc_file_path(site_root, r["id"], r["filename"])
        ]
        if len(donors) != 1:
            continue
        donor = donors[0]
        src = info_doc_file_path(site_root, donor["id"], donor["filename"])
        if not src:
            continue
        dest_dir = info_doc_dir(site_root, row["id"])
        dest = dest_dir / row["filename"]
        try:
            dest.write_bytes(src.read_bytes())
            if dest.is_file():
                fixed += 1
        except OSError:
            pass
    return fixed


def _sanitize_upload_name(name: str) -> str:
    base = pathlib.Path(name or "document").name
    base = re.sub(r"[^\w.\- ()]+", "_", base).strip("._ ")
    return (base or "document")[:120]


def _extract_html_body(raw: str) -> str:
    """Pull authored content from a full HTML document, or return fragment as-is."""
    text = (raw or "").strip()
    if not text:
        return ""
    # Prefer inner authored content from our Information Centre shell.
    m = re.search(
        r'<div class="content">\s*(.*?)\s*</div>\s*</article>',
        text,
        flags=re.I | re.S,
    )
    if m:
        return m.group(1).strip()
    m = re.search(r"<body\b[^>]*>(.*)</body>", text, flags=re.I | re.S)
    if m:
        return m.group(1).strip()
    m = re.search(r"<body\b[^>]*>(.*)$", text, flags=re.I | re.S)
    if m:
        inner = m.group(1).strip()
        return re.sub(r"</html>\s*$", "", inner, flags=re.I).strip()
    if re.search(r"<html\b", text, flags=re.I):
        cleaned = re.sub(r"<!DOCTYPE[^>]*>", "", text, flags=re.I)
        cleaned = re.sub(r"<head\b[^>]*>.*?</head>", "", cleaned, flags=re.I | re.S)
        cleaned = re.sub(r"</?html\b[^>]*>", "", cleaned, flags=re.I)
        return cleaned.strip()
    return text


def _normalize_authored_html(body_html: str) -> str:
    """Turn loose authored text into readable block HTML when needed."""
    text = (body_html or "").strip()
    if not text:
        return "<p></p>"
    # Already structured with block elements — keep as authored.
    if re.search(
        r"<(p|div|h[1-6]|ul|ol|li|table|section|article|header|blockquote|pre)\b",
        text,
        flags=re.I,
    ):
        return text
    # Drop a redundant leading <h1>…</h1> if wrap will add the title again.
    text = re.sub(r"^\s*<h1\b[^>]*>.*?</h1>\s*", "", text, count=1, flags=re.I | re.S)
    parts = re.split(r"\n\s*\n", text)
    paras: list[str] = []
    for part in parts:
        chunk = part.strip()
        if not chunk:
            continue
        # Preserve light inline markup; convert single newlines to breaks.
        chunk = re.sub(r"\n+", "<br>\n", chunk)
        paras.append(f"<p>{chunk}</p>")
    return "\n".join(paras) if paras else f"<p>{text}</p>"


def _wrap_html_document(title: str, body_html: str) -> str:
    """Readable document shell for Information Centre HTML pages."""
    safe_title = (title or "Document").replace("<", "&lt;").replace(">", "&gt;")
    extracted = _extract_html_body(body_html)
    # Drop a prior shell title so we don't double-render headings.
    if title:
        m = re.match(r"^\s*<h1\b[^>]*>(.*?)</h1>\s*", extracted, flags=re.I | re.S)
        if m:
            inner = re.sub(r"<[^>]+>", "", m.group(1)).strip()
            if not inner or inner.casefold() == title.strip().casefold():
                extracted = extracted[m.end() :]
    body = _normalize_authored_html(extracted)
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n<head>\n'
        '<meta charset="utf-8">\n'
        f"<title>{safe_title}</title>\n"
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "<style>\n"
        ":root{--ink:#162033;--muted:#5b6578;--navy:#0f2744;--paper:#f7f3ea;"
        "--rule:rgba(15,39,68,.12);--accent:#1f4d3a;}\n"
        "*{box-sizing:border-box;}\n"
        "html,body{margin:0;padding:0;background:linear-gradient(180deg,#e8eef5,#dfe7f0);}\n"
        "body{font-family:Georgia,'Iowan Old Style','Palatino Linotype',Palatino,serif;"
        "line-height:1.65;color:var(--ink);-webkit-font-smoothing:antialiased;}\n"
        ".sheet{max-width:46rem;margin:1.25rem auto 2.5rem;padding:0 1rem 2rem;}\n"
        "@media (min-width:720px){.sheet{margin-top:1.75rem;padding:0 1.25rem 2.5rem;}}\n"
        ".card{background:var(--paper);border:1px solid var(--rule);border-radius:18px;"
        "box-shadow:0 18px 40px rgba(15,39,68,.08);overflow:hidden;}\n"
        ".mast{padding:1.35rem 1.4rem 1.15rem;background:linear-gradient(135deg,#123054,#1a3f66);"
        "color:#f4f1ea;text-align:left;}\n"
        ".mast .eyebrow{margin:0 0 .35rem;font:600 .72rem/1.2 system-ui,-apple-system,sans-serif;"
        "letter-spacing:.08em;text-transform:uppercase;opacity:.78;text-align:left;}\n"
        ".mast h1{margin:0;font:700 1.55rem/1.25 'Segoe UI',system-ui,-apple-system,sans-serif;"
        "letter-spacing:-.01em;text-align:left;}\n"
        ".content{padding:1.35rem 1.4rem 1.75rem;text-align:left;}\n"
        "@media (min-width:720px){.mast,.content{padding-left:1.85rem;padding-right:1.85rem;}"
        ".mast h1{font-size:1.85rem;}}\n"
        ".content > :first-child{margin-top:0;}\n"
        ".content > :last-child{margin-bottom:0;}\n"
        "h2,h3,h4{font-family:'Segoe UI',system-ui,-apple-system,sans-serif;color:var(--navy);"
        "line-height:1.3;margin:1.45rem 0 .55rem;}\n"
        "h2{font-size:1.25rem;} h3{font-size:1.08rem;} h4{font-size:1rem;}\n"
        "p{margin:.7rem 0;}\n"
        "ul,ol{margin:.65rem 0 .9rem;padding-left:1.35rem;}\n"
        "li{margin:.28rem 0;}\n"
        "strong,b{font-weight:700;color:var(--navy);}\n"
        "a{color:#1d4ed8;} a:hover{color:#1e3a8a;}\n"
        "hr{border:0;border-top:1px solid var(--rule);margin:1.4rem 0;}\n"
        "blockquote{margin:1rem 0;padding:.55rem 0 .55rem 1rem;border-left:3px solid var(--accent);"
        "color:var(--muted);font-style:italic;}\n"
        "img{max-width:100%;height:auto;border-radius:10px;}\n"
        "table{border-collapse:collapse;width:100%;margin:1rem 0;font-size:.95rem;}\n"
        "th,td{border:1px solid var(--rule);padding:.45rem .6rem;text-align:left;vertical-align:top;}\n"
        "th{background:rgba(15,39,68,.06);font-family:'Segoe UI',system-ui,sans-serif;}\n"
        "code,pre{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:.9em;}\n"
        "pre{overflow:auto;padding:.85rem 1rem;background:rgba(15,39,68,.04);border-radius:10px;}\n"
        ".foot{margin:1rem auto 0;max-width:46rem;padding:0 1rem;text-align:center;"
        "font:500 .72rem/1.4 system-ui,sans-serif;color:#6b7385;}\n"
        "</style>\n</head>\n<body>\n"
        '<div class="sheet"><article class="card">\n'
        f'<header class="mast"><p class="eyebrow">Information Centre</p>'
        f"<h1>{safe_title}</h1></header>\n"
        f'<div class="content">\n{body}\n</div>\n'
        "</article>\n"
        '<p class="foot">Housing Colony Sanyard · Residents Welfare Association</p>\n'
        "</div>\n"
        "</body>\n</html>\n"
    )


def _is_complete_html_document(raw: str) -> bool:
    """True when stored HTML is already a full page (do not re-wrap / strip design)."""
    text = (raw or "").lstrip()
    if not text:
        return False
    head = text[:4000].lower()
    if not (head.startswith("<!doctype html") or head.startswith("<html")):
        return False
    has_head = "<head" in head
    has_body = "<body" in text[:12000].lower()
    if not (has_head and has_body):
        return False
    # Standalone designed pages (uploaded Act HTML, linked documents, etc.)
    if any(
        marker in head
        for marker in (
            "<style",
            'rel="stylesheet"',
            "fonts.googleapis",
            "font-face",
        )
    ):
        return True
    # Already using our Information Centre shell
    sample = text[:12000]
    if 'class="sheet"' in sample and 'class="mast"' in sample:
        return True
    if 'class="page"' in sample and ("chapter" in sample.lower() or "toc" in sample.lower()):
        return True
    return False


def render_info_html_for_view(title: str, raw_html: str) -> str:
    """Serve complete HTML pages as-is; beautify authored fragments for the viewer."""
    if _is_complete_html_document(raw_html):
        return raw_html
    return _wrap_html_document(title, raw_html)


def upsert_info_document(
    conn: sqlite3.Connection,
    site_root: pathlib.Path,
    payload: dict,
    *,
    publisher: str | None,
    file_storage=None,
) -> dict:
    ensure_info_documents_table(conn)
    ensure_bilingual_content_columns(conn)
    doc_id = (payload.get("id") or f"info_{secrets.token_hex(6)}").strip()
    existing = conn.execute("SELECT * FROM info_documents WHERE id = ?", (doc_id,)).fetchone()

    title = payload.get("title") if "title" in payload else (existing["title"] if existing else None)
    title = str(title or "").strip()
    if len(title) < 2:
        raise ValueError("Title required")

    summary = payload.get("summary") if "summary" in payload else (existing["summary"] if existing else "")
    summary = str(summary or "").strip()[:800]
    category = _info_category(
        payload.get("category") if "category" in payload else (existing["category"] if existing else "general")
    )

    folder_id_val: str | None
    if "folderId" in payload or "folder_id" in payload:
        raw_folder = payload.get("folderId", payload.get("folder_id"))
        resolved = _resolve_folder_id(conn, "" if raw_folder is None else str(raw_folder))
        folder_id_val = None if resolved == "" else resolved
    elif existing and "folder_id" in existing.keys():
        folder_id_val = existing["folder_id"] or None
    else:
        folder_id_val = None

    def _pick_hi(field: str, camel: str, *, max_len: int | None = None) -> str | None:
        if camel in payload or field in payload:
            raw = payload.get(camel, payload.get(field))
            text = str(raw or "").strip()
            if max_len is not None:
                text = text[:max_len]
            return text
        if existing and field in existing.keys():
            return existing[field] or ""
        return ""

    title_hi = _pick_hi("title_hi", "titleHi", max_len=160) or ""
    summary_hi = _pick_hi("summary_hi", "summaryHi", max_len=800) or ""
    has_html_hi = int(existing["has_html_hi"] or 0) if existing and "has_html_hi" in existing.keys() else 0

    status = (
        payload.get("status")
        if "status" in payload
        else (existing["status"] if existing else "draft")
    )
    status = str(status or "draft").strip().lower()
    if status not in {"draft", "published", "archived"}:
        raise ValueError("Invalid status")

    if "audience" in payload or "allowedMemberIds" in payload or "allowed_member_ids" in payload:
        audience, allowed_json = _resolve_info_audience_payload(conn, payload, existing)
    elif existing and "audience" in existing.keys():
        audience = _info_audience(existing["audience"])
        if "allowed_member_ids" in existing.keys():
            allowed_json = existing["allowed_member_ids"] or "[]"
            if audience != "restricted":
                allowed_json = "[]"
        else:
            allowed_json = "[]"
    else:
        audience = "all"
        allowed_json = "[]"

    doc_type = None
    if "docType" in payload or "doc_type" in payload:
        doc_type = payload.get("docType") or payload.get("doc_type")
    elif existing:
        doc_type = existing["doc_type"]
    html_body = payload.get("htmlBody") if "htmlBody" in payload else None
    if "html_body" in payload and html_body is None:
        html_body = payload.get("html_body")
    external_url_in = None
    if "externalUrl" in payload or "external_url" in payload:
        external_url_in = payload.get("externalUrl", payload.get("external_url"))
    if not doc_type:
        if html_body is not None:
            doc_type = "html"
        elif external_url_in is not None:
            doc_type = "link"
        else:
            doc_type = "file"
    doc_type = str(doc_type or "file").strip().lower()
    if doc_type not in INFO_DOC_TYPES:
        raise ValueError("docType must be file, html, or link")

    now = utc_now()
    filename = existing["filename"] if existing else None
    original_name = existing["original_name"] if existing else None
    mime_type = existing["mime_type"] if existing else None
    size_bytes = int(existing["size_bytes"] or 0) if existing else 0
    external_url = ""
    if existing and "external_url" in existing.keys() and existing["external_url"]:
        external_url = str(existing["external_url"]).strip()

    if doc_type == "link":
        if external_url_in is not None or not existing:
            external_url = normalize_info_external_url(
                external_url_in if external_url_in is not None else external_url
            )
        elif not external_url:
            raise ValueError("Web link URL required")
        else:
            external_url = normalize_info_external_url(external_url)
        mime_type = guess_info_link_mime(external_url)
        parsed = urlparse(external_url)
        path_name = pathlib.Path(parsed.path or "").name
        original_name = path_name or parsed.netloc or "web-link"
        filename = None
        size_bytes = 0
        has_html_hi = 0
        # Drop any previously stored upload/HTML files for this id.
        try:
            dest = info_doc_dir(site_root, doc_id)
            if dest.is_dir():
                for f in dest.iterdir():
                    try:
                        f.unlink()
                    except OSError:
                        pass
        except Exception:
            pass
    elif doc_type == "html" and html_body is not None:
        body = str(html_body).strip()
        if len(body) < 3:
            raise ValueError("HTML content required")
        if len(body.encode("utf-8")) > INFO_MAX_BYTES:
            raise ValueError("HTML content must be under 15 MB")
        wrapped = _wrap_html_document(title, body)
        data = wrapped.encode("utf-8")
        filename = "content.html"
        original_name = f"{_sanitize_upload_name(title)}.html"
        mime_type = "text/html"
        size_bytes = len(data)
        external_url = ""
        dest_dir = info_doc_dir(site_root, doc_id)
        _replace_dir_file(dest_dir, filename, data, keep_names={"content_hi.html"})

    html_body_hi = None
    if "htmlBodyHi" in payload or "html_body_hi" in payload:
        html_body_hi = payload.get("htmlBodyHi", payload.get("html_body_hi"))
    if doc_type == "html" and html_body_hi is not None:
        hi_text = str(html_body_hi).strip()
        dest_dir = info_doc_dir(site_root, doc_id)
        hi_path = dest_dir / "content_hi.html"
        if hi_text:
            if len(hi_text.encode("utf-8")) > INFO_MAX_BYTES:
                raise ValueError("Hindi HTML content must be under 15 MB")
            wrapped_hi = _wrap_html_document(title_hi or title, hi_text)
            _atomic_write_bytes(hi_path, wrapped_hi.encode("utf-8"))
            has_html_hi = 1
        else:
            try:
                if hi_path.is_file():
                    hi_path.unlink()
            except OSError:
                pass
            has_html_hi = 0
    elif doc_type == "html":
        # Preserve existing Hindi HTML file flag.
        dest_dir = info_doc_dir(site_root, doc_id)
        has_html_hi = 1 if (dest_dir / "content_hi.html").is_file() else has_html_hi
    elif doc_type != "html":
        has_html_hi = 0

    if doc_type != "link" and file_storage is not None and getattr(file_storage, "filename", None):
        original = _sanitize_upload_name(file_storage.filename)
        ext = pathlib.Path(original).suffix.lower()
        if ext not in INFO_DOC_MIME:
            raise ValueError(
                "Unsupported file type. Use PDF, Word, Excel, PowerPoint, images, CSV, TXT, or HTML."
            )
        data = file_storage.read()
        if not data:
            raise ValueError("Empty upload")
        if len(data) > INFO_MAX_BYTES:
            raise ValueError("File must be under 15 MB")
        filename = f"doc{ext}"
        original_name = original
        mime_type = INFO_DOC_MIME[ext]
        size_bytes = len(data)
        external_url = ""
        doc_type = "html" if ext in {".html", ".htm"} else "file"
        dest_dir = info_doc_dir(site_root, doc_id)
        _replace_dir_file(dest_dir, filename, data, keep_names=set())
        has_html_hi = 0
    elif doc_type != "link" and not existing and not filename:
        if doc_type == "html":
            raise ValueError("HTML content required")
        raise ValueError("Upload a document file, create HTML content, or paste a web link")

    if doc_type == "link":
        if not external_url:
            raise ValueError("Web link URL required")
    elif filename and not info_doc_file_path(site_root, doc_id, filename):
        raise ValueError("Document file missing on server — please re-upload the file")

    if status == "published":
        if doc_type == "link":
            if not external_url:
                raise ValueError("Add a web link before publishing")
        elif not filename:
            raise ValueError("Add a file, HTML content, or web link before publishing")

    was_pub = bool(existing and (existing["status"] or "") == "published")
    if status == "published" and (not was_pub or not existing):
        published_at = now
    else:
        published_at = existing["published_at"] if existing else None
        if status == "published" and not published_at:
            published_at = now
        if status != "published":
            published_at = published_at  # keep history if republishing later
    published_by = (existing["published_by"] if existing and existing["published_by"] else None) or publisher

    created_at = existing["created_at"] if existing else now
    # Ensure bilingual columns exist before insert (older DBs).
    ensure_bilingual_content_columns(conn)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(info_documents)").fetchall()}
    if "external_url" not in cols:
        conn.execute("ALTER TABLE info_documents ADD COLUMN external_url TEXT")
    conn.execute(
        """
        INSERT INTO info_documents(
          id, title, summary, category, folder_id, doc_type, filename, original_name, mime_type,
          size_bytes, external_url, status, audience, allowed_member_ids, published_at, published_by,
          created_at, updated_at, title_hi, summary_hi, has_html_hi
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
          title=excluded.title,
          summary=excluded.summary,
          category=excluded.category,
          folder_id=excluded.folder_id,
          doc_type=excluded.doc_type,
          filename=excluded.filename,
          original_name=excluded.original_name,
          mime_type=excluded.mime_type,
          size_bytes=excluded.size_bytes,
          external_url=excluded.external_url,
          status=excluded.status,
          audience=excluded.audience,
          allowed_member_ids=excluded.allowed_member_ids,
          published_at=excluded.published_at,
          published_by=excluded.published_by,
          updated_at=excluded.updated_at,
          title_hi=excluded.title_hi,
          summary_hi=excluded.summary_hi,
          has_html_hi=excluded.has_html_hi
        """,
        (
            doc_id,
            title,
            summary,
            category,
            folder_id_val,
            doc_type,
            filename,
            original_name,
            mime_type,
            size_bytes,
            external_url or None,
            status,
            audience,
            allowed_json,
            published_at,
            published_by,
            created_at,
            now,
            title_hi,
            summary_hi,
            has_html_hi,
        ),
    )
    conn.commit()
    doc = get_info_document(conn, doc_id, as_admin=True, site_root=site_root) or {"id": doc_id}
    try:
        _sync_info_share_card(conn, site_root, doc_id=doc_id)
    except Exception:
        pass
    return doc


def _public_origin_for_share(site_root: pathlib.Path | None = None) -> str:
    return (
        os.environ.get("VEERCANVAS_PUBLIC_ORIGIN")
        or os.environ.get("RWA_PUBLIC_ORIGIN")
        or "https://housingcolonysanyard.in"
    ).rstrip("/")


def branded_email_html(*, text_body: str, site_root: pathlib.Path | None = None) -> str:
    """HTML counterpart for colony emails — seal plus the same text as the plaintext part."""
    origin = _public_origin_for_share(site_root)
    logo = f"{origin}/assets/mhws-logo/mhws-logo-web-256.png"
    body_html = html.escape(text_body or "").replace("\n", "<br>\n")
    return (
        "<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"></head>"
        "<body style=\"margin:0;background:#f3f6fa;padding:16px;"
        "font-family:Georgia,'Times New Roman',serif;color:#1a2236;\">"
        "<div style=\"max-width:560px;margin:0 auto;background:#ffffff;"
        "border-radius:12px;padding:24px 20px;border:1px solid #e6e2d8;\">"
        "<div style=\"text-align:center;margin-bottom:18px;\">"
        f"<img src=\"{html.escape(logo)}\" alt=\"Mandi Housing Welfare Society\" "
        "width=\"72\" height=\"72\" style=\"display:block;margin:0 auto 8px;\">"
        "<p style=\"margin:0;font-size:13px;color:#64748b;font-family:system-ui,sans-serif;\">"
        "Housing Colony Sanyard · Mandi Housing Welfare Society</p></div>"
        f"<div style=\"font-size:15px;line-height:1.55;\">{body_html}</div>"
        "</div></body></html>"
    )


def add_branded_html_alternative(
    msg: EmailMessage,
    *,
    text_body: str,
    site_root: pathlib.Path | None = None,
) -> None:
    msg.add_alternative(branded_email_html(text_body=text_body, site_root=site_root), subtype="html")


def _sync_info_share_card(
    conn: sqlite3.Connection,
    site_root: pathlib.Path,
    *,
    doc_id: str | None = None,
    folder_id: str | None = None,
) -> None:
    """Write or refresh nginx-served /share/*.html for WhatsApp OG previews."""
    meta = get_info_share_meta(
        conn,
        doc_id=doc_id,
        folder_id=folder_id,
        site_root=site_root,
    )
    if not meta:
        return
    origin = _public_origin_for_share(site_root)
    meta = dict(meta)
    if doc_id:
        tid = str(meta.get("id") or doc_id)
        meta["id"] = tid
        page_url = f"{origin}/share/doc/{tid}.html"
        meta["deepLink"] = f"{origin}/?source=pwa&info=doc.{tid}#info/doc/{tid}"
    else:
        tid = str(meta.get("id") or folder_id or "")
        if not tid:
            return
        meta["id"] = tid
        page_url = f"{origin}/share/folder/{tid}.html"
        meta["deepLink"] = f"{origin}/?source=pwa&info=folder.{tid}#info/folder/{tid}"
    write_info_share_static(
        site_root,
        meta,
        page_url=page_url,
        image_url=f"{origin}/assets/og-share-card.jpg?v=20260810-mhws",
        image_width=1200,
        image_height=630,
    )


def delete_info_document(conn: sqlite3.Connection, site_root: pathlib.Path, doc_id: str) -> None:
    ensure_info_documents_table(conn)
    nid = (doc_id or "").strip()
    if not nid:
        raise ValueError("document id required")
    row = conn.execute("SELECT id FROM info_documents WHERE id = ?", (nid,)).fetchone()
    if not row:
        raise ValueError("Document not found")
    cur = conn.execute("DELETE FROM info_documents WHERE id = ?", (nid,))
    conn.commit()
    if cur.rowcount < 1:
        raise ValueError("Document not found")
    # Remove files
    try:
        dest = info_centre_dir(site_root) / re.sub(r"[^a-zA-Z0-9_-]", "", nid)
        if dest.is_dir():
            for f in dest.iterdir():
                try:
                    f.unlink()
                except OSError:
                    pass
            try:
                dest.rmdir()
            except OSError:
                pass
    except Exception:
        pass
    try:
        share = pathlib.Path(site_root) / info_share_static_relpath(doc_id=nid)
        if share.is_file():
            share.unlink()
    except Exception:
        pass


def info_doc_should_inline(mime_type: str | None, filename: str | None) -> bool:
    ext = pathlib.Path(filename or "").suffix.lower()
    if ext in INFO_INLINE_EXTS:
        return True
    mt = (mime_type or "").lower()
    return mt.startswith("image/") or mt in {"application/pdf", "text/html", "text/plain"}


# --- Works & Events ---------------------------------------------------------

WORK_KINDS = (
    ("maintenance", "Maintenance"),
    ("development", "Development project"),
    ("activity", "Activity"),
    ("event", "Event"),
)

WORK_CATEGORIES: dict[str, tuple[tuple[str, str], ...]] = {
    "maintenance": (
        ("water", "Water supply / tanks"),
        ("roads", "Roads & drains"),
        ("electrical", "Electrical / lighting"),
        ("sanitation", "Sanitation & garbage"),
        ("buildings", "Buildings & structures"),
        ("parks", "Parks & greenery"),
        ("security", "Security & gates"),
        ("other", "Other maintenance"),
    ),
    "development": (
        ("infrastructure", "Infrastructure"),
        ("amenities", "Amenities"),
        ("landscaping", "Landscaping"),
        ("digital", "IT / digital"),
        ("other", "Other development"),
    ),
    "activity": (
        ("cultural", "Cultural"),
        ("sports", "Sports"),
        ("welfare", "Welfare"),
        ("cleanliness", "Cleanliness drive"),
        ("awareness", "Awareness / training"),
        ("other", "Other activity"),
    ),
    "event": (
        ("meeting", "Meeting / AGM"),
        ("festival", "Festival / celebration"),
        ("sports_day", "Sports day"),
        ("workshop", "Workshop"),
        ("other", "Other event"),
    ),
}

WORK_STATUSES = (
    ("planned", "Planned"),
    ("approved", "Approved"),
    ("in_progress", "In progress"),
    ("on_hold", "On hold"),
    ("completed", "Completed"),
    ("closed", "Closed"),
    ("cancelled", "Cancelled"),
)

FUNDING_SOURCES = (
    ("rwa_fund", "RWA fund"),
    ("member_contribution", "Member contribution"),
    ("himuda", "HIMUDA / govt"),
    ("grant", "Grant"),
    ("donation", "Donation"),
    ("sponsor", "Sponsor"),
    ("other", "Other"),
)


def works_meta() -> dict:
    return {
        "kinds": [{"id": k, "label": lbl} for k, lbl in WORK_KINDS],
        "categories": {
            kind: [{"id": c, "label": lbl} for c, lbl in cats]
            for kind, cats in WORK_CATEGORIES.items()
        },
        "statuses": [{"id": s, "label": lbl} for s, lbl in WORK_STATUSES],
        "fundingSources": [{"id": s, "label": lbl} for s, lbl in FUNDING_SOURCES],
    }


def _work_kind(raw: str | None) -> str:
    key = (raw or "").strip().lower()
    allowed = {k for k, _ in WORK_KINDS}
    if key not in allowed:
        raise ValueError("kind must be maintenance, development, activity, or event")
    return key


def _work_category(kind: str, raw: str | None) -> str:
    key = (raw or "other").strip().lower() or "other"
    allowed = {c for c, _ in WORK_CATEGORIES.get(kind, ())}
    return key if key in allowed else "other"


def _work_status(raw: str | None) -> str:
    key = (raw or "planned").strip().lower()
    allowed = {s for s, _ in WORK_STATUSES}
    if key not in allowed:
        raise ValueError("Invalid status")
    return key


def _optional_rupees(value, *, field: str) -> int | None:
    if value is None or value == "":
        return None
    return _as_int_rupees(value, field=field, allow_negative=False)


def _parse_funding(raw) -> list[dict]:
    if raw is None or raw == "":
        return []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError("funding must be valid JSON") from exc
    if not isinstance(raw, list):
        raise ValueError("funding must be a list")
    source_ids = {s for s, _ in FUNDING_SOURCES}
    source_labels = dict(FUNDING_SOURCES)
    out: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        source = str(item.get("source") or item.get("sourceId") or "other").strip().lower()
        if source not in source_ids:
            source = "other"
        amount = item.get("amount")
        amount_i = _optional_rupees(amount, field="funding amount") if amount not in (None, "") else None
        notes = str(item.get("notes") or "").strip()[:240]
        label = str(item.get("label") or source_labels.get(source) or source)
        if amount_i is None and not notes and source == "other" and not item.get("label"):
            continue
        out.append({
            "source": source,
            "label": label[:80],
            "amount": amount_i,
            "notes": notes,
        })
    return out[:20]


def _parse_milestones(raw) -> list[dict]:
    if raw is None or raw == "":
        return []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError("milestones must be valid JSON") from exc
    if not isinstance(raw, list):
        raise ValueError("milestones must be a list")
    out: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or item.get("label") or "").strip()[:160]
        if not title:
            continue
        out.append({
            "date": str(item.get("date") or "").strip()[:20] or None,
            "title": title,
            "done": bool(item.get("done")),
        })
    return out[:30]


def _work_public(r: sqlite3.Row | dict) -> dict:
    if hasattr(r, "keys"):
        data = {k: r[k] for k in r.keys()}
    else:
        data = dict(r)
    kind = data.get("kind") or "maintenance"
    cat = data.get("category") or "other"
    status = data.get("status") or "planned"
    kind_label = next((lbl for k, lbl in WORK_KINDS if k == kind), kind)
    cat_label = next((lbl for c, lbl in WORK_CATEGORIES.get(kind, ()) if c == cat), cat)
    status_label = next((lbl for s, lbl in WORK_STATUSES if s == status), status)
    try:
        funding = _parse_funding(data.get("funding_json") or "[]")
    except ValueError:
        funding = []
    try:
        milestones = _parse_milestones(data.get("milestones_json") or "[]")
    except ValueError:
        milestones = []
    est = data.get("estimated_cost")
    act = data.get("actual_cost")
    funding_total = sum(int(f["amount"]) for f in funding if f.get("amount") is not None)
    return {
        "id": data.get("id"),
        "title": data.get("title") or "",
        "kind": kind,
        "kindLabel": kind_label,
        "category": cat,
        "categoryLabel": cat_label,
        "summary": data.get("summary") or "",
        "details": data.get("details") or "",
        "benefits": data.get("benefits") or "",
        "timelineNotes": data.get("timeline_notes") or "",
        "milestones": milestones,
        "status": status,
        "statusLabel": status_label,
        "visibility": data.get("visibility") or "published",
        "location": data.get("location") or "",
        "startDate": data.get("start_date") or "",
        "endDate": data.get("end_date") or "",
        "eventDate": data.get("event_date") or "",
        "estimatedCost": int(est) if est is not None else None,
        "actualCost": int(act) if act is not None else None,
        "costNotes": data.get("cost_notes") or "",
        "contractorName": data.get("contractor_name") or "",
        "contractorContact": data.get("contractor_contact") or "",
        "contractorDetails": data.get("contractor_details") or "",
        "funding": funding,
        "fundingTotal": funding_total,
        "assignedTo": data.get("assigned_to") or "",
        "createdBy": data.get("created_by") or "",
        "createdAt": data.get("created_at"),
        "updatedAt": data.get("updated_at"),
        "closedAt": data.get("closed_at"),
        "closedBy": data.get("closed_by") or "",
    }


def list_colony_works(
    conn: sqlite3.Connection,
    *,
    kind: str | None = None,
    status: str | None = None,
    visibility: str | None = None,
    as_admin: bool = False,
) -> list[dict]:
    ensure_colony_works_table(conn)
    clauses: list[str] = []
    params: list[Any] = []
    if not as_admin:
        clauses.append("visibility = 'published'")
        clauses.append("status != 'cancelled'")
    elif visibility in {"draft", "published"}:
        clauses.append("visibility = ?")
        params.append(visibility)
    if kind:
        clauses.append("kind = ?")
        params.append(_work_kind(kind))
    if status:
        if status == "active":
            clauses.append("status IN ('planned','approved','in_progress','on_hold')")
        elif status == "done":
            clauses.append("status IN ('completed','closed')")
        else:
            clauses.append("status = ?")
            params.append(_work_status(status))
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = conn.execute(
        f"""
        SELECT * FROM colony_works
        {where}
        ORDER BY
          CASE status
            WHEN 'in_progress' THEN 0
            WHEN 'approved' THEN 1
            WHEN 'planned' THEN 2
            WHEN 'on_hold' THEN 3
            WHEN 'completed' THEN 4
            WHEN 'closed' THEN 5
            ELSE 6
          END,
          COALESCE(event_date, start_date, updated_at) DESC,
          id DESC
        """,
        params,
    ).fetchall()
    return [_work_public(r) for r in rows]


def get_colony_work(
    conn: sqlite3.Connection,
    work_id: str,
    *,
    as_admin: bool = False,
) -> dict | None:
    ensure_colony_works_table(conn)
    row = conn.execute("SELECT * FROM colony_works WHERE id = ?", (work_id,)).fetchone()
    if not row:
        return None
    if not as_admin and (row["visibility"] or "") != "published":
        return None
    return _work_public(row)


def upsert_colony_work(
    conn: sqlite3.Connection,
    payload: dict,
    *,
    actor: dict | None = None,
) -> dict:
    ensure_colony_works_table(conn)
    work_id = (payload.get("id") or f"w_{secrets.token_hex(6)}").strip()
    existing = conn.execute("SELECT * FROM colony_works WHERE id = ?", (work_id,)).fetchone()

    title = payload.get("title") if "title" in payload else (existing["title"] if existing else "")
    title = str(title or "").strip()
    if len(title) < 2:
        raise ValueError("Title required")

    if "kind" in payload or not existing:
        kind = _work_kind(payload.get("kind") or (existing["kind"] if existing else None))
    else:
        kind = existing["kind"]

    category = _work_category(
        kind,
        payload.get("category") if "category" in payload else (existing["category"] if existing else "other"),
    )
    status = _work_status(
        payload.get("status") if "status" in payload else (existing["status"] if existing else "planned")
    )
    visibility = (
        payload.get("visibility")
        if "visibility" in payload
        else (existing["visibility"] if existing else "published")
    )
    visibility = str(visibility or "published").strip().lower()
    if visibility not in {"draft", "published"}:
        raise ValueError("visibility must be draft or published")

    def pick(field: str, col: str | None = None, default: str = "") -> str:
        col = col or field
        if field in payload or _snake(field) in payload:
            val = payload.get(field, payload.get(_snake(field)))
            return str(val or "").strip()
        if existing:
            return str(existing[col] or "")
        return default

    def _snake(name: str) -> str:
        out = []
        for ch in name:
            if ch.isupper():
                out.append("_")
                out.append(ch.lower())
            else:
                out.append(ch)
        return "".join(out)

    summary = pick("summary")[:800]
    details = pick("details")[:8000]
    benefits = pick("benefits")[:4000]
    timeline_notes = pick("timelineNotes", "timeline_notes")[:4000]
    location = pick("location")[:160]
    start_date = pick("startDate", "start_date")[:20]
    end_date = pick("endDate", "end_date")[:20]
    event_date = pick("eventDate", "event_date")[:20]
    cost_notes = pick("costNotes", "cost_notes")[:800]
    contractor_name = pick("contractorName", "contractor_name")[:160]
    contractor_contact = pick("contractorContact", "contractor_contact")[:160]
    contractor_details = pick("contractorDetails", "contractor_details")[:800]
    assigned_to = pick("assignedTo", "assigned_to")[:120]

    if "estimatedCost" in payload or "estimated_cost" in payload:
        estimated_cost = _optional_rupees(
            payload.get("estimatedCost", payload.get("estimated_cost")),
            field="estimatedCost",
        )
    else:
        estimated_cost = existing["estimated_cost"] if existing else None

    if "actualCost" in payload or "actual_cost" in payload:
        actual_cost = _optional_rupees(
            payload.get("actualCost", payload.get("actual_cost")),
            field="actualCost",
        )
    else:
        actual_cost = existing["actual_cost"] if existing else None

    if "funding" in payload or "funding_json" in payload:
        funding = _parse_funding(payload.get("funding", payload.get("funding_json")))
    elif existing and existing["funding_json"]:
        funding = _parse_funding(existing["funding_json"])
    else:
        funding = []

    if "milestones" in payload or "milestones_json" in payload:
        milestones = _parse_milestones(payload.get("milestones", payload.get("milestones_json")))
    elif existing and existing["milestones_json"]:
        milestones = _parse_milestones(existing["milestones_json"])
    else:
        milestones = []

    now = utc_now()
    actor_house = ""
    if actor:
        actor_house = str(actor.get("houseId") or actor.get("house_id") or "")
    created_by = (existing["created_by"] if existing and existing["created_by"] else None) or actor_house or None
    created_at = existing["created_at"] if existing else now

    was_closed = bool(existing and (existing["status"] or "") in {"closed", "completed"})
    closing_now = status in {"closed", "completed"} and not was_closed
    if closing_now:
        closed_at = now
        closed_by = actor_house or None
    elif status in {"closed", "completed"} and existing:
        closed_at = existing["closed_at"]
        closed_by = existing["closed_by"]
    else:
        closed_at = None
        closed_by = None

    conn.execute(
        """
        INSERT INTO colony_works(
          id, title, kind, category, summary, details, benefits, timeline_notes, milestones_json,
          status, visibility, location, start_date, end_date, event_date,
          estimated_cost, actual_cost, cost_notes,
          contractor_name, contractor_contact, contractor_details, funding_json,
          assigned_to, created_by, created_at, updated_at, closed_at, closed_by
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(id) DO UPDATE SET
          title=excluded.title,
          kind=excluded.kind,
          category=excluded.category,
          summary=excluded.summary,
          details=excluded.details,
          benefits=excluded.benefits,
          timeline_notes=excluded.timeline_notes,
          milestones_json=excluded.milestones_json,
          status=excluded.status,
          visibility=excluded.visibility,
          location=excluded.location,
          start_date=excluded.start_date,
          end_date=excluded.end_date,
          event_date=excluded.event_date,
          estimated_cost=excluded.estimated_cost,
          actual_cost=excluded.actual_cost,
          cost_notes=excluded.cost_notes,
          contractor_name=excluded.contractor_name,
          contractor_contact=excluded.contractor_contact,
          contractor_details=excluded.contractor_details,
          funding_json=excluded.funding_json,
          assigned_to=excluded.assigned_to,
          updated_at=excluded.updated_at,
          closed_at=excluded.closed_at,
          closed_by=excluded.closed_by
        """,
        (
            work_id,
            title,
            kind,
            category,
            summary,
            details,
            benefits,
            timeline_notes,
            json.dumps(milestones),
            status,
            visibility,
            location,
            start_date or None,
            end_date or None,
            event_date or None,
            estimated_cost,
            actual_cost,
            cost_notes,
            contractor_name,
            contractor_contact,
            contractor_details,
            json.dumps(funding),
            assigned_to,
            created_by,
            created_at,
            now,
            closed_at,
            closed_by,
        ),
    )
    conn.commit()
    return get_colony_work(conn, work_id, as_admin=True) or {"id": work_id}


def delete_colony_work(conn: sqlite3.Connection, work_id: str) -> None:
    ensure_colony_works_table(conn)
    ensure_work_quote_tables(conn)
    wid = (work_id or "").strip()
    if not wid:
        raise ValueError("work id required")
    conn.execute("DELETE FROM work_quote_responses WHERE work_id = ?", (wid,))
    conn.execute("DELETE FROM work_quote_invites WHERE work_id = ?", (wid,))
    cur = conn.execute("DELETE FROM colony_works WHERE id = ?", (wid,))
    conn.commit()
    if cur.rowcount < 1:
        raise ValueError("Work item not found")


def _parse_email_list(raw) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, list):
        parts = [str(x) for x in raw]
    else:
        parts = re.split(r"[\s,;]+", str(raw))
    out: list[str] = []
    seen: set[str] = set()
    for part in parts:
        email = part.strip().lower()
        if not email:
            continue
        if not EMAIL_RE.match(email):
            raise ValueError(f"Invalid email: {part.strip()}")
        if email in seen:
            continue
        seen.add(email)
        out.append(email)
    return out[:40]


def _quote_invite_public(row) -> dict:
    keys = row.keys() if hasattr(row, "keys") else row
    data = {k: row[k] for k in keys} if hasattr(row, "keys") else dict(row)
    return {
        "id": data.get("id"),
        "workId": data.get("work_id"),
        "vendorEmail": data.get("vendor_email") or "",
        "vendorName": data.get("vendor_name") or "",
        "status": data.get("status") or "sent",
        "message": data.get("message") or "",
        "invitedBy": data.get("invited_by") or "",
        "createdAt": data.get("created_at"),
        "expiresAt": data.get("expires_at"),
        "emailSentAt": data.get("email_sent_at"),
        "emailError": data.get("email_error") or "",
        "publicUrl": data.get("_public_url") or "",
    }


def _quote_response_public(row) -> dict:
    keys = row.keys() if hasattr(row, "keys") else row
    data = {k: row[k] for k in keys} if hasattr(row, "keys") else dict(row)
    amount = data.get("amount")
    return {
        "id": data.get("id"),
        "inviteId": data.get("invite_id"),
        "workId": data.get("work_id"),
        "vendorEmail": data.get("vendor_email") or "",
        "vendorName": data.get("vendor_name") or "",
        "vendorPhone": data.get("vendor_phone") or "",
        "amount": int(amount) if amount is not None else None,
        "notes": data.get("notes") or "",
        "timeline": data.get("timeline") or "",
        "status": data.get("status") or "submitted",
        "createdAt": data.get("created_at"),
        "updatedAt": data.get("updated_at"),
    }


def _work_quote_public_url(token: str, site_root: pathlib.Path | None = None) -> str:
    origin = _public_origin_for_share(site_root)
    return f"{origin}/quote.html?t={token}"


def send_quote_invite_email(
    *,
    to_email: str,
    work: dict,
    public_url: str,
    message: str = "",
    site_root: pathlib.Path | None = None,
) -> dict:
    cfg = load_smtp_config(site_root)
    if not cfg["configured"]:
        return {
            "ok": False,
            "channel": "dev",
            "reason": "smtp_not_configured",
            "hint": "Set RWA_SMTP_PASS in data/smtp.env",
            "publicUrl": public_url,
        }
    title = work.get("title") or "Colony work"
    summary = work.get("summary") or ""
    details = (work.get("details") or "")[:1200]
    location = work.get("location") or ""
    note = f"\nNote from colony:\n{message.strip()}\n" if message.strip() else ""
    body = (
        f"You are invited to submit a quote for a colony work requirement.\n\n"
        f"Work: {title}\n"
        f"{('Location: ' + location + chr(10)) if location else ''}"
        f"{('Summary: ' + summary + chr(10)) if summary else ''}"
        f"{('Details:\n' + details + '\n\n') if details else ''}"
        f"{note}"
        f"Please enter your quoted amount on the response form. The colony does not share an estimated budget.\n\n"
        f"Respond online (preferred):\n{public_url}\n\n"
        f"You may also reply to this email with your quote; responses are tracked in the colony mailbox "
        f"and in the project's Quotes section.\n\n"
        f"— Mandi Housing Welfare Society\n"
        f"  Housing Colony Sanyard, Mandi\n"
    )
    try:
        msg = EmailMessage()
        msg["Subject"] = f"Quote invite — {title[:80]}"
        msg["From"] = f"Housing Colony Sanyard RWA <{cfg['from']}>"
        msg["To"] = to_email
        msg["Reply-To"] = cfg["from"]
        msg.set_content(body)
        add_branded_html_alternative(msg, text_body=body, site_root=site_root)
        with smtplib.SMTP(cfg["host"], cfg["port"], timeout=25) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.ehlo()
            smtp.login(cfg["user"], cfg["password"])
            smtp.send_message(msg)
        return {"ok": True, "channel": "email", "from": cfg["from"], "publicUrl": public_url}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "channel": "dev", "error": str(exc), "publicUrl": public_url}


def send_quote_received_email(
    *,
    work: dict,
    response: dict,
    site_root: pathlib.Path | None = None,
) -> dict:
    """Notify the colony mailbox when a vendor submits a quote."""
    cfg = load_smtp_config(site_root)
    if not cfg["configured"]:
        return {"ok": False, "reason": "smtp_not_configured"}
    to_email = (
        os.environ.get("RWA_QUOTE_NOTIFY_EMAIL")
        or cfg.get("from")
        or ""
    ).strip()
    if not to_email:
        return {"ok": False, "reason": "no_notify_email"}
    title = work.get("title") or "Colony work"
    amount = response.get("amount")
    amount_line = f"Amount: ₹{amount:,}\n" if isinstance(amount, int) else "Amount: (not stated)\n"
    body = (
        f"A vendor submitted a quote for:\n\n"
        f"Work: {title}\n"
        f"Vendor: {response.get('vendorName') or '—'}\n"
        f"Email: {response.get('vendorEmail') or '—'}\n"
        f"Phone: {response.get('vendorPhone') or '—'}\n"
        f"{amount_line}"
        f"Timeline: {response.get('timeline') or '—'}\n"
        f"Notes:\n{response.get('notes') or '—'}\n\n"
        f"View all quotes in Works and Events → project → Quotes.\n\n"
        f"— Housing Colony Sanyard portal\n"
    )
    try:
        msg = EmailMessage()
        msg["Subject"] = f"Quote received — {title[:80]}"
        msg["From"] = f"Housing Colony Sanyard RWA <{cfg['from']}>"
        msg["To"] = to_email
        msg["Reply-To"] = response.get("vendorEmail") or cfg["from"]
        msg.set_content(body)
        with smtplib.SMTP(cfg["host"], cfg["port"], timeout=25) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.ehlo()
            smtp.login(cfg["user"], cfg["password"])
            smtp.send_message(msg)
        return {"ok": True, "channel": "email", "to": to_email}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


def invite_work_quotes(
    conn: sqlite3.Connection,
    work_id: str,
    payload: dict,
    *,
    actor: dict | None = None,
    site_root: pathlib.Path | None = None,
) -> dict:
    ensure_colony_works_table(conn)
    ensure_work_quote_tables(conn)
    work = get_colony_work(conn, work_id, as_admin=True)
    if not work:
        raise ValueError("Work item not found")
    emails = _parse_email_list(payload.get("emails") or payload.get("email") or "")
    if not emails:
        raise ValueError("Enter at least one vendor email")
    message = str(payload.get("message") or "").strip()[:800]
    invited_by = ""
    if actor:
        invited_by = str(actor.get("member_id") or actor.get("house_id") or actor.get("name") or "")[:80]
    now = utc_now()
    expires = None
    invites = []
    for email in emails:
        existing = conn.execute(
            """
            SELECT * FROM work_quote_invites
            WHERE work_id = ? AND lower(vendor_email) = ? AND status IN ('sent','opened')
            ORDER BY created_at DESC LIMIT 1
            """,
            (work_id, email),
        ).fetchone()
        if existing and not conn.execute(
            "SELECT id FROM work_quote_responses WHERE invite_id = ?",
            (existing["id"],),
        ).fetchone():
            token = existing["token"]
            invite_id = existing["id"]
            conn.execute(
                """
                UPDATE work_quote_invites
                SET message = ?, invited_by = ?, email_error = ''
                WHERE id = ?
                """,
                (message, invited_by, invite_id),
            )
        else:
            invite_id = "wqi_" + secrets.token_hex(8)
            token = secrets.token_urlsafe(24)
            conn.execute(
                """
                INSERT INTO work_quote_invites (
                  id, work_id, token, vendor_email, vendor_name, status, message,
                  invited_by, created_at, expires_at, email_sent_at, email_error
                ) VALUES (?, ?, ?, ?, '', 'sent', ?, ?, ?, ?, NULL, '')
                """,
                (invite_id, work_id, token, email, message, invited_by, now, expires),
            )
        public_url = _work_quote_public_url(token, site_root)
        delivery = send_quote_invite_email(
            to_email=email,
            work=work,
            public_url=public_url,
            message=message,
            site_root=site_root,
        )
        if delivery.get("ok"):
            conn.execute(
                "UPDATE work_quote_invites SET email_sent_at = ?, email_error = '' WHERE id = ?",
                (now, invite_id),
            )
        else:
            err = str(delivery.get("error") or delivery.get("reason") or "send_failed")[:240]
            conn.execute(
                "UPDATE work_quote_invites SET email_error = ? WHERE id = ?",
                (err, invite_id),
            )
        row = conn.execute("SELECT * FROM work_quote_invites WHERE id = ?", (invite_id,)).fetchone()
        item = _quote_invite_public(row)
        item["publicUrl"] = public_url
        item["emailDelivery"] = delivery
        invites.append(item)
    conn.commit()
    return {"workId": work_id, "invites": invites, "quotes": list_work_quotes(conn, work_id)}


def list_work_quotes(conn: sqlite3.Connection, work_id: str) -> dict:
    ensure_work_quote_tables(conn)
    wid = (work_id or "").strip()
    invites = conn.execute(
        """
        SELECT * FROM work_quote_invites
        WHERE work_id = ?
        ORDER BY created_at DESC
        """,
        (wid,),
    ).fetchall()
    responses = conn.execute(
        """
        SELECT * FROM work_quote_responses
        WHERE work_id = ?
        ORDER BY created_at DESC
        """,
        (wid,),
    ).fetchall()
    invite_list = []
    for row in invites:
        item = _quote_invite_public(row)
        item["publicUrl"] = _work_quote_public_url(row["token"])
        invite_list.append(item)
    return {
        "workId": wid,
        "invites": invite_list,
        "responses": [_quote_response_public(r) for r in responses],
        "counts": {
            "invited": len(invite_list),
            "responded": len(responses),
            "pending": sum(1 for i in invite_list if i["status"] in ("sent", "opened")),
        },
    }


def get_public_quote_invite(conn: sqlite3.Connection, token: str) -> dict | None:
    ensure_colony_works_table(conn)
    ensure_work_quote_tables(conn)
    tok = (token or "").strip()
    if not tok:
        return None
    invite = conn.execute(
        "SELECT * FROM work_quote_invites WHERE token = ?",
        (tok,),
    ).fetchone()
    if not invite:
        return None
    if invite["status"] == "cancelled":
        raise ValueError("This quote invite was cancelled")
    work = get_colony_work(conn, invite["work_id"], as_admin=True)
    if not work:
        raise ValueError("Work item not found")
    if invite["status"] == "sent":
        conn.execute(
            "UPDATE work_quote_invites SET status = 'opened' WHERE id = ? AND status = 'sent'",
            (invite["id"],),
        )
        conn.commit()
        invite = conn.execute("SELECT * FROM work_quote_invites WHERE id = ?", (invite["id"],)).fetchone()
    existing = conn.execute(
        "SELECT * FROM work_quote_responses WHERE invite_id = ?",
        (invite["id"],),
    ).fetchone()
    return {
        "invite": {
            "id": invite["id"],
            "vendorEmail": invite["vendor_email"],
            "status": invite["status"],
            "message": invite["message"] or "",
            "alreadyResponded": bool(existing),
        },
        "work": {
            "id": work["id"],
            "title": work["title"],
            "kind": work["kind"],
            "kindLabel": work.get("kindLabel") or work["kind"],
            "categoryLabel": work.get("categoryLabel") or "",
            "summary": work.get("summary") or "",
            "details": work.get("details") or "",
            "location": work.get("location") or "",
            "startDate": work.get("startDate") or "",
            "endDate": work.get("endDate") or "",
            "statusLabel": work.get("statusLabel") or work.get("status") or "",
        },
        "response": _quote_response_public(existing) if existing else None,
    }


def submit_public_quote(
    conn: sqlite3.Connection,
    token: str,
    payload: dict,
    *,
    site_root: pathlib.Path | None = None,
) -> dict:
    ensure_work_quote_tables(conn)
    tok = (token or "").strip()
    invite = conn.execute(
        "SELECT * FROM work_quote_invites WHERE token = ?",
        (tok,),
    ).fetchone()
    if not invite:
        raise ValueError("Invalid or expired quote link")
    if invite["status"] == "cancelled":
        raise ValueError("This quote invite was cancelled")
    existing = conn.execute(
        "SELECT * FROM work_quote_responses WHERE invite_id = ?",
        (invite["id"],),
    ).fetchone()
    if existing:
        raise ValueError("A quote was already submitted for this invite")
    work = get_colony_work(conn, invite["work_id"], as_admin=True)
    if not work:
        raise ValueError("Work item not found")
    name = str(payload.get("vendorName") or payload.get("name") or "").strip()[:120]
    phone = str(payload.get("vendorPhone") or payload.get("phone") or "").strip()[:40]
    notes = str(payload.get("notes") or payload.get("quote") or "").strip()[:4000]
    timeline = str(payload.get("timeline") or "").strip()[:400]
    amount_raw = payload.get("amount")
    amount = None
    if amount_raw not in (None, ""):
        amount = _as_int_rupees(amount_raw, field="quote amount", allow_negative=False)
    if not name:
        raise ValueError("Enter your name / firm name")
    if amount is None:
        raise ValueError("Enter your quote amount")
    if not notes:
        raise ValueError("Enter quote details")
    now = utc_now()
    rid = "wqr_" + secrets.token_hex(8)
    conn.execute(
        """
        INSERT INTO work_quote_responses (
          id, invite_id, work_id, vendor_email, vendor_name, vendor_phone,
          amount, notes, timeline, status, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'submitted', ?, ?)
        """,
        (
            rid,
            invite["id"],
            invite["work_id"],
            invite["vendor_email"],
            name,
            phone,
            amount,
            notes,
            timeline,
            now,
            now,
        ),
    )
    conn.execute(
        "UPDATE work_quote_invites SET status = 'responded' WHERE id = ?",
        (invite["id"],),
    )
    conn.commit()
    response = _quote_response_public(
        conn.execute("SELECT * FROM work_quote_responses WHERE id = ?", (rid,)).fetchone()
    )
    notify = send_quote_received_email(work=work, response=response, site_root=site_root)
    return {"ok": True, "response": response, "mailboxNotify": notify}


def _as_int_rupees(value, *, field: str, allow_negative: bool = True) -> int:
    if value is None or value == "":
        raise ValueError(f"{field} is required")
    try:
        # Accept "1,200" / "₹1200" style from curated forms
        cleaned = str(value).strip().replace(",", "").replace("₹", "").replace(" ", "")
        num = int(float(cleaned))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a whole-rupee amount") from exc
    if not allow_negative and num < 0:
        raise ValueError(f"{field} cannot be negative")
    return num


def update_payment_row(
    conn: sqlite3.Connection,
    house_id: str,
    payload: dict,
) -> dict:
    """EC: curate a household's row on the latest payment ledger."""
    hid = (house_id or "").strip()
    if not hid:
        raise ValueError("houseId required")

    ledger = conn.execute(
        "SELECT id, as_of, source FROM payment_ledgers ORDER BY as_of DESC, id DESC LIMIT 1"
    ).fetchone()
    if not ledger:
        raise ValueError("No payment ledger loaded yet")

    existing = conn.execute(
        """
        SELECT pr.*, r.name, r.section, r.plot_no
        FROM payment_rows pr
        JOIN residents r ON r.house_id = pr.house_id
        WHERE pr.ledger_id = ? AND pr.house_id = ?
        """,
        (ledger["id"], hid),
    ).fetchone()
    if not existing:
        raise ValueError(f"No ledger row for plot {hid}")

    # Start from current values; overlay provided keys.
    balance_prev = int(existing["balance_prev"] or 0)
    fee_year = int(existing["fee_year"] or 0)
    fee_amount = int(existing["fee_amount"] or 0)
    amount_received = int(existing["amount_received"] or 0)
    remarks = existing["remarks"] or ""

    if "balancePrev" in payload or "previousTotal" in payload:
        raw = payload["balancePrev"] if "balancePrev" in payload else payload["previousTotal"]
        balance_prev = _as_int_rupees(raw, field="previousTotal")
    if "feeYear" in payload:
        try:
            fee_year = int(payload["feeYear"])
        except (TypeError, ValueError) as exc:
            raise ValueError("feeYear must be a year number") from exc
        if fee_year < 2000 or fee_year > 2100:
            raise ValueError("feeYear out of range")
    if "feeAmount" in payload or "currentYearTotal" in payload:
        raw = payload["feeAmount"] if "feeAmount" in payload else payload["currentYearTotal"]
        fee_amount = _as_int_rupees(raw, field="currentYearTotal", allow_negative=False)
    if "amountReceived" in payload:
        amount_received = _as_int_rupees(payload["amountReceived"], field="amountReceived", allow_negative=False)
    if "remarks" in payload:
        remarks = str(payload.get("remarks") or "").strip()[:500]

    # Defaults: recompute totals unless explicitly overridden.
    if "totalDue" in payload:
        total_due = _as_int_rupees(payload["totalDue"], field="totalDue")
    else:
        total_due = balance_prev + fee_amount

    if "balanceOutstanding" in payload or "pendingDues" in payload:
        raw = payload["balanceOutstanding"] if "balanceOutstanding" in payload else payload["pendingDues"]
        balance_outstanding = _as_int_rupees(raw, field="pendingDues")
    else:
        balance_outstanding = total_due - amount_received

    conn.execute(
        """
        UPDATE payment_rows
        SET balance_prev = ?,
            fee_year = ?,
            fee_amount = ?,
            total_due = ?,
            amount_received = ?,
            balance_outstanding = ?,
            remarks = ?,
            treasury_status = 'pending',
            treasury_validated_by = NULL,
            treasury_validated_at = NULL,
            treasury_confirmed_by = NULL,
            treasury_confirmed_at = NULL,
            treasury_note = NULL
        WHERE ledger_id = ? AND house_id = ?
        """,
        (
            balance_prev,
            fee_year,
            fee_amount,
            total_due,
            amount_received,
            balance_outstanding,
            remarks,
            ledger["id"],
            hid,
        ),
    )
    conn.commit()

    row = conn.execute(
        """
        SELECT pr.*, r.name, r.section, r.plot_no, pl.as_of, pl.source
        FROM payment_rows pr
        JOIN residents r ON r.house_id = pr.house_id
        JOIN payment_ledgers pl ON pl.id = pr.ledger_id
        WHERE pr.ledger_id = ? AND pr.house_id = ?
        """,
        (ledger["id"], hid),
    ).fetchone()
    enriched = enrich_payment_row(row)
    enriched.update({
        "plotNo": row["plot_no"],
        "section": row["section"],
        "name": row["name"],
    })
    return enriched



GRIEVANCE_CATEGORIES = {
    "dues": "Dues & payments",
    "data": "Plot / resident data",
    "app": "Portal / app / login",
    "maintenance": "Maintenance & repairs",
    "water": "Water supply",
    "sanitation": "Cleanliness & garbage",
    "security": "Security, gates & parking",
    "amenities": "Common areas & amenities",
    "neighbour": "Neighbour / plot matters",
    "committee": "EC / RWA functioning",
    "other": "Other",
}

GRIEVANCE_STATUSES = ("open", "in_progress", "resolved", "closed")


def grievance_categories() -> list[dict]:
    return [{"id": k, "label": v} for k, v in GRIEVANCE_CATEGORIES.items()]


def _grievance_public(row: sqlite3.Row | dict, *, include_contacts: bool = False, photo: dict | None = None) -> dict:
    if hasattr(row, "keys"):
        data = {k: row[k] for k in row.keys()}
    else:
        data = dict(row)
    photo = photo or photo_fields_for_member(None, None)
    item = {
        "id": data.get("id"),
        "houseId": data.get("house_id") or data.get("houseId"),
        "category": data.get("category") or "other",
        "categoryLabel": GRIEVANCE_CATEGORIES.get(data.get("category") or "other", "Other"),
        "subject": data.get("subject") or "",
        "subjectHi": data.get("subject_hi") or data.get("subjectHi") or "",
        "body": data.get("body") or "",
        "bodyHi": data.get("body_hi") or data.get("bodyHi") or "",
        "status": data.get("status") or "open",
        "createdAt": data.get("created_at") or data.get("createdAt"),
        "updatedAt": data.get("updated_at") or data.get("updatedAt"),
        "response": data.get("response") or "",
        "respondedAt": data.get("responded_at") or data.get("respondedAt"),
        "respondedByName": data.get("responded_by_name") or data.get("respondedByName") or "",
        "respondedByHouseId": data.get("responded_by_house_id") or data.get("respondedByHouseId") or "",
        "name": data.get("name") or "",
        "section": data.get("section") or "",
        "plotNo": data.get("plot_no") or data.get("plotNo") or "",
        "messages": [],
        "hasPhoto": photo.get("hasPhoto", False),
        "photoUrl": photo.get("photoUrl") or "",
        "primaryMemberId": photo.get("memberId"),
    }
    if include_contacts:
        item["phone"] = data.get("phone") or ""
        item["email"] = data.get("email") or ""
    return item


def _list_grievance_messages(conn: sqlite3.Connection, grievance_id: str, *, photos: dict | None = None) -> list[dict]:
    rows = conn.execute(
        """
        SELECT * FROM grievance_messages
        WHERE grievance_id = ?
        ORDER BY created_at ASC, rowid ASC
        """,
        (grievance_id,),
    ).fetchall()
    photos = photos if photos is not None else primary_member_photo_map(conn)
    return [
        {
            "id": r["id"],
            "grievanceId": r["grievance_id"],
            "authorHouseId": r["author_house_id"] or "",
            "authorName": r["author_name"] or "",
            "authorRole": r["author_role"] or "resident",
            "body": r["body"] or "",
            "bodyHi": (r["body_hi"] if "body_hi" in r.keys() else "") or "",
            "createdAt": r["created_at"],
            **(photos.get(r["author_house_id"] or "") or photo_fields_for_member(None, None)),
        }
        for r in rows
    ]


def _fetch_grievance(conn: sqlite3.Connection, grievance_id: str, *, include_contacts: bool = False) -> dict:
    joined = conn.execute(
        """
        SELECT g.*, r.name, r.section, r.plot_no, r.phone, r.email
        FROM grievances g
        JOIN residents r ON r.house_id = g.house_id
        WHERE g.id = ?
        """,
        (grievance_id,),
    ).fetchone()
    if not joined:
        raise ValueError("Concern not found")
    photos = primary_member_photo_map(conn)
    item = _grievance_public(
        joined,
        include_contacts=include_contacts,
        photo=photos.get(joined["house_id"]),
    )
    item["messages"] = _list_grievance_messages(conn, grievance_id, photos=photos)
    return item


def create_grievance(conn: sqlite3.Connection, house_id: str, payload: dict) -> dict:
    ensure_grievances_table(conn)
    ensure_bilingual_content_columns(conn)
    hid = normalize_house_id(house_id)
    resident = find_resident(conn, hid)
    if not resident:
        raise ValueError("Resident not found")
    if resident.get("house_id") == SUPERADMIN_HOUSE_ID:
        raise ValueError("Super admin cannot file colony grievances under the system account")

    category = str(payload.get("category") or "").strip().lower()
    if category not in GRIEVANCE_CATEGORIES:
        raise ValueError("Choose a valid category")
    subject = str(payload.get("subject") or "").strip()
    body = str(payload.get("body") or payload.get("message") or "").strip()
    subject_hi = str(payload.get("subjectHi") or payload.get("subject_hi") or "").strip()[:160]
    body_hi = str(payload.get("bodyHi") or payload.get("body_hi") or "").strip()[:4000]
    if len(subject) < 4:
        raise ValueError("Subject is too short")
    if len(body) < 8:
        raise ValueError("Please describe the issue in a bit more detail")
    if len(subject) > 160:
        subject = subject[:160]
    if len(body) > 4000:
        body = body[:4000]

    gid = f"g_{secrets.token_hex(6)}"
    mid = f"gm_{secrets.token_hex(6)}"
    now = utc_now()
    conn.execute(
        """
        INSERT INTO grievances(
          id, house_id, category, subject, body, status, created_at, updated_at, subject_hi, body_hi
        ) VALUES (?, ?, ?, ?, ?, 'open', ?, ?, ?, ?)
        """,
        (gid, resident["house_id"], category, subject, body, now, now, subject_hi or None, body_hi or None),
    )
    conn.execute(
        """
        INSERT INTO grievance_messages(
          id, grievance_id, author_house_id, author_name, author_role, body, created_at, body_hi
        ) VALUES (?, ?, ?, ?, 'resident', ?, ?, ?)
        """,
        (mid, gid, resident["house_id"], resident.get("name") or resident["house_id"], body, now, body_hi or None),
    )
    conn.commit()
    return _fetch_grievance(conn, gid)


def list_grievances(
    conn: sqlite3.Connection,
    *,
    house_id: str | None = None,
    status: str | None = None,
    category: str | None = None,
    limit: int = 100,
    include_contacts: bool = False,
) -> list[dict]:
    ensure_grievances_table(conn)
    try:
        lim = max(1, min(int(limit), 300))
    except (TypeError, ValueError):
        lim = 100

    clauses = []
    args: list[Any] = []
    if house_id:
        clauses.append("g.house_id = ?")
        args.append(normalize_house_id(house_id))
    if status and status != "all":
        clauses.append("g.status = ?")
        args.append(status)
    if category and category != "all":
        clauses.append("g.category = ?")
        args.append(category)

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = conn.execute(
        f"""
        SELECT g.*, r.name, r.section, r.plot_no, r.phone, r.email
        FROM grievances g
        JOIN residents r ON r.house_id = g.house_id
        {where}
        ORDER BY g.updated_at DESC, g.created_at DESC
        LIMIT ?
        """,
        (*args, lim),
    ).fetchall()
    photos = primary_member_photo_map(conn)
    items = []
    for r in rows:
        item = _grievance_public(
            r,
            include_contacts=include_contacts,
            photo=photos.get(r["house_id"]),
        )
        item["messages"] = _list_grievance_messages(conn, r["id"], photos=photos)
        items.append(item)
    return items


def grievance_stats(conn: sqlite3.Connection) -> dict:
    ensure_grievances_table(conn)
    row = conn.execute(
        """
        SELECT
          COUNT(*) AS total,
          SUM(CASE WHEN status = 'open' THEN 1 ELSE 0 END) AS open_count,
          SUM(CASE WHEN status = 'in_progress' THEN 1 ELSE 0 END) AS in_progress_count,
          SUM(CASE WHEN status = 'resolved' THEN 1 ELSE 0 END) AS resolved_count,
          SUM(CASE WHEN status = 'closed' THEN 1 ELSE 0 END) AS closed_count
        FROM grievances
        """
    ).fetchone()
    return {
        "total": int(row["total"] or 0) if row else 0,
        "open": int(row["open_count"] or 0) if row else 0,
        "inProgress": int(row["in_progress_count"] or 0) if row else 0,
        "resolved": int(row["resolved_count"] or 0) if row else 0,
        "closed": int(row["closed_count"] or 0) if row else 0,
    }


def add_grievance_message(
    conn: sqlite3.Connection,
    grievance_id: str,
    payload: dict,
    actor: dict,
) -> dict:
    """Append a mailbox reply. Any signed-in resident/EC can post on the shared thread."""
    ensure_grievances_table(conn)
    ensure_bilingual_content_columns(conn)
    gid = str(grievance_id or "").strip()
    row = conn.execute("SELECT * FROM grievances WHERE id = ?", (gid,)).fetchone()
    if not row:
        raise ValueError("Concern not found")
    if row["status"] == "closed":
        raise ValueError("This concern is closed")

    body = str(payload.get("body") or payload.get("message") or payload.get("response") or "").strip()
    if len(body) < 2:
        raise ValueError("Message is too short")
    if len(body) > 4000:
        body = body[:4000]
    body_hi = str(payload.get("bodyHi") or payload.get("body_hi") or "").strip()[:4000] or None

    is_ec = (actor.get("role") == "admin") or bool(actor.get("superAdmin"))
    author_role = "ec" if is_ec else "resident"
    author_house = actor.get("houseId") or actor.get("house_id") or ""
    author_name = actor.get("name") or actor.get("officialTitle") or ("EC" if is_ec else author_house)
    now = utc_now()
    mid = f"gm_{secrets.token_hex(6)}"
    conn.execute(
        """
        INSERT INTO grievance_messages(
          id, grievance_id, author_house_id, author_name, author_role, body, created_at, body_hi
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (mid, gid, author_house, author_name, author_role, body, now, body_hi),
    )

    status = str(payload.get("status") or "").strip().lower()
    if is_ec and status in GRIEVANCE_STATUSES:
        new_status = status
    elif is_ec and row["status"] == "open":
        new_status = "in_progress"
    else:
        new_status = row["status"]

    updates = {
        "updated_at": now,
        "status": new_status,
    }
    if is_ec:
        updates["response"] = body
        updates["responded_at"] = now
        updates["responded_by_house_id"] = author_house
        updates["responded_by_name"] = author_name

    conn.execute(
        """
        UPDATE grievances
        SET response = COALESCE(?, response),
            status = ?,
            updated_at = ?,
            responded_at = COALESCE(?, responded_at),
            responded_by_house_id = COALESCE(?, responded_by_house_id),
            responded_by_name = COALESCE(?, responded_by_name)
        WHERE id = ?
        """,
        (
            updates.get("response"),
            updates["status"],
            updates["updated_at"],
            updates.get("responded_at"),
            updates.get("responded_by_house_id"),
            updates.get("responded_by_name"),
            gid,
        ),
    )
    conn.commit()
    return _fetch_grievance(conn, gid, include_contacts=is_ec)


def respond_grievance(
    conn: sqlite3.Connection,
    grievance_id: str,
    payload: dict,
    actor: dict,
) -> dict:
    """EC convenience: reply + optional status change on the shared mailbox thread."""
    ensure_grievances_table(conn)
    response = str(payload.get("response") or payload.get("reply") or payload.get("body") or "").strip()
    status = str(payload.get("status") or "").strip().lower()
    if response:
        return add_grievance_message(
            conn,
            grievance_id,
            {
                "body": response,
                "bodyHi": payload.get("bodyHi") or payload.get("body_hi") or payload.get("responseHi"),
                "status": status or None,
            },
            actor,
        )
    # Status-only update
    gid = str(grievance_id or "").strip()
    row = conn.execute("SELECT * FROM grievances WHERE id = ?", (gid,)).fetchone()
    if not row:
        raise ValueError("Concern not found")
    if status and status not in GRIEVANCE_STATUSES:
        raise ValueError("Invalid status")
    if not status:
        raise ValueError("Response or status required")
    now = utc_now()
    conn.execute(
        "UPDATE grievances SET status = ?, updated_at = ? WHERE id = ?",
        (status, now, gid),
    )
    conn.commit()
    return _fetch_grievance(conn, gid, include_contacts=True)


def list_ec_members(conn: sqlite3.Connection) -> list[dict]:
    """Active Executive Committee members (for draft sharing)."""
    rows = conn.execute(
        """
        SELECT house_id, plot_no, name, official_title, role
        FROM residents
        WHERE role = 'admin' AND status = 'active' AND house_id != ?
        ORDER BY
          CASE WHEN official_title IS NULL OR official_title = '' THEN 1 ELSE 0 END,
          official_title COLLATE NOCASE,
          name COLLATE NOCASE
        """,
        (SUPERADMIN_HOUSE_ID,),
    ).fetchall()
    photos = primary_member_photo_map(conn)
    return [
        {
            "houseId": r["house_id"],
            "plotNo": r["plot_no"],
            "name": r["name"] or r["house_id"],
            "officialTitle": r["official_title"] or "",
            "label": (
                f"{r['official_title']} · {r['name']}"
                if r["official_title"]
                else f"{r['name']} ({r['house_id']})"
            ),
            **(photos.get(r["house_id"]) or photo_fields_for_member(None, None)),
        }
        for r in rows
    ]


def _share_rows(conn: sqlite3.Connection, notice_id: str) -> list[sqlite3.Row]:
    ensure_notice_shares_table(conn)
    return conn.execute(
        """
        SELECT s.house_id, s.can_edit, s.shared_at, s.shared_by,
               r.name, r.official_title
        FROM notice_shares s
        LEFT JOIN residents r ON r.house_id = s.house_id
        WHERE s.notice_id = ?
        ORDER BY r.official_title COLLATE NOCASE, r.name COLLATE NOCASE, s.house_id
        """,
        (notice_id,),
    ).fetchall()


def _notice_shares_public(conn: sqlite3.Connection, notice_id: str) -> list[dict]:
    return [
        {
            "houseId": r["house_id"],
            "canEdit": bool(r["can_edit"]),
            "sharedAt": r["shared_at"],
            "sharedBy": r["shared_by"],
            "name": r["name"] or r["house_id"],
            "officialTitle": r["official_title"] or "",
            "label": (
                f"{r['official_title']} · {r['name']}"
                if r["official_title"]
                else (r["name"] or r["house_id"])
            ),
        }
        for r in _share_rows(conn, notice_id)
    ]


def _viewer_house(viewer: dict | None) -> str:
    if not viewer:
        return ""
    return str(viewer.get("houseId") or viewer.get("house_id") or "").strip()


def _is_notice_owner(notice_row: sqlite3.Row | dict, viewer: dict | None) -> bool:
    if not viewer:
        return False
    if bool(viewer.get("superAdmin")) or is_superadmin_resident(viewer):
        return True
    owner = ""
    if hasattr(notice_row, "keys"):
        owner = str(notice_row["published_by"] or "")
    else:
        owner = str(notice_row.get("published_by") or notice_row.get("publishedBy") or "")
    # Legacy drafts without an author: any EC may manage until ownership is set.
    if not owner:
        return viewer.get("role") == "admin"
    return owner == _viewer_house(viewer)


def _share_access(conn: sqlite3.Connection, notice_id: str, viewer: dict | None) -> dict | None:
    house = _viewer_house(viewer)
    if not house:
        return None
    ensure_notice_shares_table(conn)
    row = conn.execute(
        "SELECT can_edit FROM notice_shares WHERE notice_id = ? AND house_id = ?",
        (notice_id, house),
    ).fetchone()
    if not row:
        return None
    return {"canEdit": bool(row["can_edit"])}


def can_view_draft(conn: sqlite3.Connection, notice_row: sqlite3.Row | dict, viewer: dict | None) -> bool:
    if not viewer:
        return False
    if _is_notice_owner(notice_row, viewer):
        return True
    # Legacy drafts with no owner remain visible to all EC until claimed/shared.
    owner = ""
    if hasattr(notice_row, "keys"):
        owner = str(notice_row["published_by"] or "")
    else:
        owner = str(notice_row.get("published_by") or notice_row.get("publishedBy") or "")
    if not owner and viewer.get("role") == "admin":
        return True
    nid = notice_row["id"] if hasattr(notice_row, "keys") else notice_row.get("id")
    return _share_access(conn, nid, viewer) is not None


def can_edit_draft(conn: sqlite3.Connection, notice_row: sqlite3.Row | dict, viewer: dict | None) -> bool:
    """Owner, or a shared member with edit access, may edit/publish until live."""
    if not viewer:
        return False
    if _is_notice_owner(notice_row, viewer):
        return True
    nid = notice_row["id"] if hasattr(notice_row, "keys") else notice_row.get("id")
    access = _share_access(conn, nid, viewer)
    return bool(access and access.get("canEdit"))

def list_notices(
    conn: sqlite3.Connection,
    *,
    status: str | None = "published",
    viewer: dict | None = None,
) -> list[dict]:
    """List notices. status: published (default), draft, archived, or all."""
    ensure_notice_pin_order(conn)
    ensure_notice_audience(conn)
    ensure_notice_image_column(conn)
    ensure_notice_shares_table(conn)
    ensure_notice_engagement_tables(conn)
    # Welcome notice is always first among published; drafts sort by updated/published date.
    order_sql = (
        "ORDER BY CASE WHEN id = ? THEN 0 ELSE 1 END, "
        "pinned DESC, pin_order ASC, published_at DESC"
    )
    status_key = (status or "published").strip().lower()
    if status_key == "all":
        rows = conn.execute(f"SELECT * FROM notices {order_sql}", (WELCOME_NOTICE_ID,)).fetchall()
    elif status_key in {"draft", "published", "archived"}:
        rows = conn.execute(
            f"SELECT * FROM notices WHERE status = ? {order_sql}",
            (status_key, WELCOME_NOTICE_ID),
        ).fetchall()
    else:
        raise ValueError("Invalid notice status filter")

    out = []
    for r in rows:
        if (r["status"] or "") == "draft" and not can_view_draft(conn, r, viewer):
            continue
        out.append(_notice_public(conn, r, viewer=viewer))
    return out


def _notice_audience(raw: str | None) -> str:
    aud = (raw or "members").strip().lower()
    return aud if aud in ("members", "public") else "members"


def _office_bearer_sort_key(item: dict) -> tuple:
    """President → Vice President(s) → General Secretary → Treasurer → others."""
    title = re.sub(r"\s+", " ", (item.get("officialTitle") or "").strip().lower())
    if re.match(r"^vice[\s\-]*president", title) or title in ("vp", "vice president"):
        rank = 1
    elif re.match(r"^president\b", title):
        rank = 0
    elif "general secretary" in title or title in ("secretary", "gs"):
        rank = 2
    elif "treasurer" in title:
        rank = 3
    else:
        rank = 9
    return (rank, title, (item.get("name") or "").lower())


def _landing_published_ts(item: dict) -> str:
    return str(
        item.get("publishedAt")
        or item.get("published_at")
        or item.get("createdAt")
        or item.get("created_at")
        or ""
    )


def public_landing(conn: sqlite3.Connection, *, site_meta: dict | None = None) -> dict:
    """Unauthenticated colony home: greeting, public updates, office bearers."""
    ensure_notice_audience(conn)
    ensure_notice_image_column(conn)
    meta = site_meta or {}
    society = (meta.get("societyName") or "Mandi Housing Welfare Society").strip()
    colony = (
        meta.get("brandName")
        or meta.get("siteName")
        or meta.get("title")
        or "Himuda Housing Colony Sanyard"
    ).strip()
    greeting = (
        f"Unity · Harmony · Progress — {colony}'s public face for residents and the city of Mandi."
    )

    notices = list_notices(conn, status="published", viewer=None)
    updates = []
    notice_ads = []
    seen_news_titles: set[str] = set()
    for n in notices:
        if _notice_audience(n.get("audience")) != "public":
            continue
        body = (n.get("body") or "").strip()
        item = {
            "id": n.get("id"),
            "title": n.get("title") or "",
            "body": body,
            "publishedAt": n.get("publishedAt"),
            "pinned": bool(n.get("pinned")),
            "category": n.get("category") or "general",
            "imageUrl": n.get("imageUrl"),
        }
        cat = (n.get("category") or "").strip().lower()
        if cat in ("ad", "ads", "classified", "advert"):
            # Ads stay short on the landing cards.
            if len(body) > 280:
                item["body"] = body[:277].rstrip() + "…"
            notice_ads.append(item)
        else:
            title_key = " ".join((item["title"] or "").lower().split())
            if title_key and title_key in seen_news_titles:
                continue
            if title_key:
                seen_news_titles.add(title_key)
            updates.append(item)
    updates.sort(key=_landing_published_ts, reverse=True)
    notice_ads.sort(key=_landing_published_ts, reverse=True)
    updates = updates[:8]
    notice_ads = notice_ads[:6]

    office_bearers = []
    for m in entitlements.list_office_and_ec(conn):
        title = (m.get("officialTitle") or "").strip()
        # Public roster: titled seats only (skip untitled EC admin / members).
        if not title:
            continue
        office_bearers.append(
            {
                "officialTitle": title,
                "name": (m.get("ecSeatHolderName") or m.get("name") or "").strip(),
            }
        )
    office_bearers.sort(key=_office_bearer_sort_key)

    public_campaigns = []
    market = {"businesses": [], "ads": [], "serviceNeeds": []}
    try:
        import rwa_marketplace

        market = rwa_marketplace.landing_slices(conn, limit_each=8)
    except Exception:
        pass

    # Merge notice-based ads with marketplace ads, newest first.
    ads = list(market.get("ads") or [])
    for na in notice_ads:
        ads.append(
            {
                "id": na["id"],
                "kind": "ad",
                "kindLabel": "Ad",
                "category": na.get("category") or "ad",
                "categoryLabel": "Colony ad",
                "title": na.get("title") or "",
                "description": na.get("body") or "",
                "contactName": "",
                "phone": "",
                "publishedAt": na.get("publishedAt") or "",
                "imageUrl": na.get("imageUrl"),
                "source": "notice",
                "acceptsInterest": False,
            }
        )
    ads.sort(key=_landing_published_ts, reverse=True)
    ads = ads[:8]

    return {
        "ok": True,
        "societyName": society,
        "colonyName": colony,
        "greeting": greeting,
        "eyebrow": (meta.get("eyebrow") or f"{society} · RWA · Mandi").strip(),
        "updates": updates,
        "news": updates,
        "ads": ads,
        "businesses": market.get("businesses") or [],
        "serviceNeeds": market.get("serviceNeeds") or [],
        "campaigns": public_campaigns,
        "officeBearers": office_bearers,
        "connectUrl": "/gate-pass.html#needs",
    }


def _notice_engagement(conn: sqlite3.Connection, notice_id: str, viewer: dict | None) -> dict:
    ensure_notice_engagement_tables(conn)
    ensure_household_members_table(conn)
    like_count = conn.execute(
        "SELECT COUNT(*) FROM notice_likes WHERE notice_id = ?",
        (notice_id,),
    ).fetchone()[0]
    comment_count = conn.execute(
        """
        SELECT COUNT(*) FROM notice_comments
        WHERE notice_id = ? AND status = 'active'
        """,
        (notice_id,),
    ).fetchone()[0]
    liked_by_me = False
    member_id = (viewer or {}).get("memberId") or (viewer or {}).get("member_id") or ""
    house_id = (viewer or {}).get("houseId") or (viewer or {}).get("house_id") or ""
    if member_id:
        liked_by_me = bool(
            conn.execute(
                "SELECT 1 FROM notice_likes WHERE notice_id = ? AND member_id = ?",
                (notice_id, member_id),
            ).fetchone()
        )
    elif house_id:
        liked_by_me = bool(
            conn.execute(
                "SELECT 1 FROM notice_likes WHERE notice_id = ? AND house_id = ?",
                (notice_id, house_id),
            ).fetchone()
        )
    return {
        "likeCount": int(like_count or 0),
        "commentCount": int(comment_count or 0),
        "likedByMe": liked_by_me,
    }


def _notice_public(
    conn: sqlite3.Connection | None,
    r: sqlite3.Row | dict,
    *,
    viewer: dict | None = None,
) -> dict:
    if hasattr(r, "keys"):
        data = {k: r[k] for k in r.keys()}
    else:
        data = dict(r)
    notice_id = data.get("id")
    status = data.get("status") or "published"
    shares = (
        _notice_shares_public(conn, notice_id)
        if conn is not None and status == "draft"
        else []
    )
    is_owner = _is_notice_owner(data, viewer) if viewer else False
    share_access = (
        _share_access(conn, notice_id, viewer) if conn is not None and viewer else None
    )
    can_edit = (
        bool(is_owner or (share_access and share_access.get("canEdit")))
        if status == "draft"
        else True
    )
    engagement = (
        _notice_engagement(conn, notice_id, viewer)
        if conn is not None and notice_id
        else {"likeCount": 0, "commentCount": 0, "likedByMe": False}
    )
    return {
        "id": notice_id,
        "title": data.get("title") or "",
        "titleHi": data.get("title_hi") or data.get("titleHi") or "",
        "body": data.get("body") or "",
        "bodyHi": data.get("body_hi") or data.get("bodyHi") or "",
        "category": data.get("category") or "general",
        "audience": _notice_audience(data.get("audience")),
        "pinned": bool(data.get("pinned")),
        "pinOrder": int(data.get("pin_order") or data.get("pinOrder") or 0),
        "fixedTop": notice_id == WELCOME_NOTICE_ID,
        "publishedAt": data.get("published_at") or data.get("publishedAt"),
        "publishedBy": data.get("published_by") or data.get("publishedBy"),
        "status": status,
        "sharedWith": shares,
        "isOwner": is_owner,
        "canEdit": can_edit,
        "sharedWithMe": bool(share_access) and not is_owner,
        "likeCount": engagement["likeCount"],
        "commentCount": engagement["commentCount"],
        "likedByMe": engagement["likedByMe"],
        "imageUrl": notice_image_url(notice_id, data.get("image_file")),
    }


def list_notice_comments(conn: sqlite3.Connection, notice_id: str) -> list[dict]:
    ensure_notice_engagement_tables(conn)
    nid = (notice_id or "").strip()
    if not nid:
        raise ValueError("notice id required")
    exists = conn.execute("SELECT 1 FROM notices WHERE id = ?", (nid,)).fetchone()
    if not exists:
        raise ValueError("Notice not found")
    rows = conn.execute(
        """
        SELECT id, notice_id, house_id, member_id, author_name, body, created_at
        FROM notice_comments
        WHERE notice_id = ? AND status = 'active'
        ORDER BY created_at ASC, id ASC
        """,
        (nid,),
    ).fetchall()
    member_ids = [r["member_id"] for r in rows if r["member_id"]]
    photos_by_member = member_photo_map(conn, member_ids)
    photos_by_house = primary_member_photo_map(conn)
    out = []
    for r in rows:
        mid = r["member_id"] or ""
        photo = photos_by_member.get(mid) if mid else None
        if not photo or not photo.get("hasPhoto"):
            photo = photos_by_house.get(r["house_id"] or "") or photo_fields_for_member(mid, None)
        out.append({
            "id": r["id"],
            "noticeId": r["notice_id"],
            "houseId": r["house_id"],
            "memberId": mid or None,
            "authorName": r["author_name"] or r["house_id"],
            "body": r["body"] or "",
            "createdAt": r["created_at"],
            "hasPhoto": photo.get("hasPhoto", False),
            "photoUrl": photo.get("photoUrl") or "",
        })
    return out


def toggle_notice_like(
    conn: sqlite3.Connection,
    notice_id: str,
    actor: dict,
) -> dict:
    ensure_notice_engagement_tables(conn)
    ensure_household_members_table(conn)
    nid = (notice_id or "").strip()
    house_id = (actor or {}).get("houseId") or (actor or {}).get("house_id") or ""
    member_id = (actor or {}).get("memberId") or (actor or {}).get("member_id") or ""
    if not nid:
        raise ValueError("notice id required")
    if not house_id:
        raise ValueError("Sign in required")
    if household.actor_is_view_only(actor):
        raise ValueError("View-only access cannot like notices")
    if not member_id:
        primary = household.primary_member(conn, house_id)
        member_id = (primary or {}).get("id") or ""
    if not member_id:
        raise ValueError("Household member required")
    row = conn.execute("SELECT id, status FROM notices WHERE id = ?", (nid,)).fetchone()
    if not row:
        raise ValueError("Notice not found")
    if (row["status"] or "") != "published":
        raise ValueError("Only published notices can be liked")
    existing = conn.execute(
        "SELECT 1 FROM notice_likes WHERE notice_id = ? AND member_id = ?",
        (nid, member_id),
    ).fetchone()
    if existing:
        conn.execute(
            "DELETE FROM notice_likes WHERE notice_id = ? AND member_id = ?",
            (nid, member_id),
        )
        liked = False
    else:
        conn.execute(
            "INSERT INTO notice_likes(notice_id, member_id, house_id, created_at) VALUES (?, ?, ?, ?)",
            (nid, member_id, house_id, utc_now()),
        )
        liked = True
    conn.commit()
    engagement = _notice_engagement(conn, nid, actor)
    return {"liked": liked, **engagement}


def add_notice_comment(
    conn: sqlite3.Connection,
    notice_id: str,
    actor: dict,
    body: str,
) -> dict:
    ensure_notice_engagement_tables(conn)
    ensure_household_members_table(conn)
    nid = (notice_id or "").strip()
    house_id = (actor or {}).get("houseId") or (actor or {}).get("house_id") or ""
    member_id = (actor or {}).get("memberId") or (actor or {}).get("member_id") or ""
    text = (body or "").strip()
    if not nid:
        raise ValueError("notice id required")
    if not house_id:
        raise ValueError("Sign in required")
    if household.actor_is_view_only(actor):
        raise ValueError("View-only access cannot comment")
    if len(text) < 2:
        raise ValueError("Comment is too short")
    if len(text) > 1000:
        raise ValueError("Comment is too long (max 1000 characters)")
    row = conn.execute("SELECT id, status FROM notices WHERE id = ?", (nid,)).fetchone()
    if not row:
        raise ValueError("Notice not found")
    if (row["status"] or "") != "published":
        raise ValueError("Only published notices can be commented on")
    author = (actor or {}).get("name") or house_id
    relation = (actor or {}).get("relationLabel") or (actor or {}).get("relation") or ""
    if relation and relation.lower() not in {"owner", ""}:
        author = f"{author} ({relation})"
    if (actor or {}).get("superAdmin"):
        author = "Super admin"
    if not member_id:
        primary = household.primary_member(conn, house_id)
        member_id = (primary or {}).get("id")
    cid = f"nc_{secrets.token_hex(8)}"
    now = utc_now()
    conn.execute(
        """
        INSERT INTO notice_comments(id, notice_id, house_id, member_id, author_name, body, created_at, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'active')
        """,
        (cid, nid, house_id, member_id, author, text, now),
    )
    conn.commit()
    return {
        "id": cid,
        "noticeId": nid,
        "houseId": house_id,
        "memberId": member_id,
        "authorName": author,
        "body": text,
        "createdAt": now,
        **_notice_engagement(conn, nid, actor),
    }


def delete_notice_comment(
    conn: sqlite3.Connection,
    notice_id: str,
    comment_id: str,
    actor: dict,
) -> dict:
    ensure_notice_engagement_tables(conn)
    nid = (notice_id or "").strip()
    cid = (comment_id or "").strip()
    house_id = (actor or {}).get("houseId") or (actor or {}).get("house_id") or ""
    member_id = (actor or {}).get("memberId") or (actor or {}).get("member_id") or ""
    if not nid or not cid:
        raise ValueError("notice and comment id required")
    if household.actor_is_view_only(actor):
        raise ValueError("View-only access cannot remove comments")
    row = conn.execute(
        "SELECT * FROM notice_comments WHERE id = ? AND notice_id = ?",
        (cid, nid),
    ).fetchone()
    if not row or (row["status"] or "") != "active":
        raise ValueError("Comment not found")
    row_member = None
    try:
        row_member = row["member_id"]
    except (KeyError, IndexError, TypeError):
        row_member = None
    is_owner = (row_member and row_member == member_id) or (not row_member and row["house_id"] == house_id)
    is_admin = (actor or {}).get("role") == "admin" or (actor or {}).get("superAdmin")
    if not is_owner and not is_admin:
        raise ValueError("You can only remove your own comment")
    conn.execute(
        "UPDATE notice_comments SET status = 'deleted' WHERE id = ?",
        (cid,),
    )
    conn.commit()
    return {"deleted": cid, **_notice_engagement(conn, nid, actor)}


def get_notice(
    conn: sqlite3.Connection,
    notice_id: str,
    *,
    viewer: dict | None = None,
) -> dict | None:
    ensure_notice_pin_order(conn)
    ensure_notice_shares_table(conn)
    ensure_notice_engagement_tables(conn)
    row = conn.execute("SELECT * FROM notices WHERE id = ?", (notice_id,)).fetchone()
    if not row:
        return None
    if (row["status"] or "") == "draft" and viewer is not None and not can_view_draft(conn, row, viewer):
        return None
    return _notice_public(conn, row, viewer=viewer)


def set_notice_shares(
    conn: sqlite3.Connection,
    notice_id: str,
    shares: list,
    *,
    actor: dict | None = None,
) -> dict:
    """Replace draft share list. Each entry: houseId + canEdit (default True).

    Owner can change who is shared and each member's view/edit access anytime
    while the notice remains a draft.
    """
    ensure_notice_shares_table(conn)
    nid = (notice_id or "").strip()
    row = conn.execute("SELECT * FROM notices WHERE id = ?", (nid,)).fetchone()
    if not row:
        raise ValueError("Notice not found")
    if (row["status"] or "") != "draft":
        raise ValueError("Only drafts can be shared")
    if not _is_notice_owner(row, actor):
        raise ValueError("Only the draft owner can manage sharing")

    ec_ids = {m["houseId"] for m in list_ec_members(conn)}
    actor_house = _viewer_house(actor)
    cleaned: list[tuple[str, bool]] = []
    seen: set[str] = set()

    for raw in shares or []:
        if isinstance(raw, dict):
            hid = str(raw.get("houseId") or raw.get("house_id") or "").strip()
            can_edit = bool(raw.get("canEdit", raw.get("can_edit", True)))
        else:
            hid = str(raw or "").strip()
            can_edit = True
        if not hid:
            continue
        try:
            hid = normalize_house_id(hid)
        except ValueError:
            pass
        if hid == actor_house or hid in seen:
            continue
        if hid not in ec_ids:
            raise ValueError(f"Not an active EC member: {hid}")
        seen.add(hid)
        cleaned.append((hid, can_edit))

    now = utc_now()
    shared_by = actor_house or None
    conn.execute("DELETE FROM notice_shares WHERE notice_id = ?", (nid,))
    for hid, can_edit in cleaned:
        conn.execute(
            """
            INSERT INTO notice_shares(notice_id, house_id, can_edit, shared_at, shared_by)
            VALUES (?, ?, ?, ?, ?)
            """,
            (nid, hid, 1 if can_edit else 0, now, shared_by),
        )
    conn.commit()
    return get_notice(conn, nid, viewer=actor) or {"id": nid}

def _next_pin_order(conn: sqlite3.Connection) -> int:
    welcome = conn.execute(
        "SELECT 1 FROM notices WHERE id = ? AND pinned = 1",
        (WELCOME_NOTICE_ID,),
    ).fetchone()
    row = conn.execute(
        "SELECT COALESCE(MAX(pin_order), 0) FROM notices WHERE pinned = 1 AND id != ?",
        (WELCOME_NOTICE_ID,),
    ).fetchone()
    base = 0 if welcome else -1
    return max(int(row[0] if row else base), base) + 1


def _reindex_pinned(conn: sqlite3.Connection) -> None:
    welcome = conn.execute(
        "SELECT id FROM notices WHERE id = ? AND pinned = 1",
        (WELCOME_NOTICE_ID,),
    ).fetchone()
    others = conn.execute(
        """
        SELECT id FROM notices
        WHERE pinned = 1 AND id != ?
        ORDER BY pin_order ASC, published_at DESC, id ASC
        """,
        (WELCOME_NOTICE_ID,),
    ).fetchall()
    ids = ([welcome["id"]] if welcome else []) + [r["id"] for r in others]
    for idx, row_id in enumerate(ids):
        conn.execute("UPDATE notices SET pin_order = ? WHERE id = ?", (idx, row_id))


def move_pinned_notice(conn: sqlite3.Connection, notice_id: str, direction: str) -> dict:
    """Swap a pinned notice with its neighbor (up = toward top of board)."""
    ensure_notice_pin_order(conn)
    nid = (notice_id or "").strip()
    direction = (direction or "").strip().lower()
    if direction not in {"up", "down"}:
        raise ValueError("move must be 'up' or 'down'")
    if nid == WELCOME_NOTICE_ID:
        raise ValueError("Welcome notice stays fixed at the top")
    row = conn.execute("SELECT * FROM notices WHERE id = ?", (nid,)).fetchone()
    if not row:
        raise ValueError("Notice not found")
    if not int(row["pinned"] or 0):
        raise ValueError("Only pinned notices can be reordered")

    pinned = conn.execute(
        """
        SELECT id FROM notices
        WHERE pinned = 1 AND id != ?
        ORDER BY pin_order ASC, published_at DESC, id ASC
        """,
        (WELCOME_NOTICE_ID,),
    ).fetchall()
    ids = [r["id"] for r in pinned]
    try:
        idx = ids.index(nid)
    except ValueError as exc:
        raise ValueError("Notice not in pinned list") from exc
    swap_with = idx - 1 if direction == "up" else idx + 1
    if swap_with < 0 or swap_with >= len(ids):
        return get_notice(conn, nid) or {"id": nid}

    ids[idx], ids[swap_with] = ids[swap_with], ids[idx]
    start = 1 if conn.execute(
        "SELECT 1 FROM notices WHERE id = ? AND pinned = 1",
        (WELCOME_NOTICE_ID,),
    ).fetchone() else 0
    if start == 1:
        conn.execute(
            "UPDATE notices SET pin_order = 0 WHERE id = ?",
            (WELCOME_NOTICE_ID,),
        )
    for offset, item_id in enumerate(ids):
        conn.execute("UPDATE notices SET pin_order = ? WHERE id = ?", (start + offset, item_id))
    conn.commit()
    return get_notice(conn, nid) or {"id": nid}


def upsert_notice(
    conn: sqlite3.Connection,
    payload: dict,
    publisher: str | None,
    *,
    actor: dict | None = None,
) -> dict:
    ensure_notice_pin_order(conn)
    ensure_notice_audience(conn)
    ensure_notice_image_column(conn)
    ensure_notice_shares_table(conn)
    ensure_bilingual_content_columns(conn)
    notice_id = (payload.get("id") or f"n_{secrets.token_hex(6)}").strip()
    existing = conn.execute("SELECT * FROM notices WHERE id = ?", (notice_id,)).fetchone()

    if existing and (existing["status"] or "") == "draft":
        if not can_edit_draft(conn, existing, actor):
            raise ValueError("You do not have permission to edit this draft")
    elif existing is None and (payload.get("status") or "published") == "draft":
        # Creating a draft — any EC is fine (caller already checked admin).
        pass

    title = (payload.get("title") if "title" in payload else None)
    if title is None:
        title = (existing["title"] if existing else "") or ""
    title = str(title).strip()
    body = (payload.get("body") if "body" in payload else None)
    if body is None:
        body = (existing["body"] if existing else "") or ""
    body = str(body).strip()

    def _pick_notice_hi(snake: str, camel: str) -> str:
        if camel in payload or snake in payload:
            return str(payload.get(camel, payload.get(snake)) or "").strip()
        if existing and snake in existing.keys():
            return (existing[snake] or "")
        return ""

    title_hi = _pick_notice_hi("title_hi", "titleHi")
    body_hi = _pick_notice_hi("body_hi", "bodyHi")

    status = (payload.get("status") or (existing["status"] if existing else None) or "published").strip()
    if status not in {"draft", "published", "archived"}:
        raise ValueError("Invalid notice status")
    if notice_id == WELCOME_NOTICE_ID and status != "published":
        raise ValueError("Welcome notice must stay published")

    if status == "draft":
        if len(title) < 1:
            raise ValueError("Draft needs a title")
        # Incomplete drafts may have an empty body.
    elif len(title) < 3 or len(body) < 3:
        raise ValueError("title and body required to publish")

    was_pinned = bool(existing and int(existing["pinned"] or 0))
    was_draft = bool(existing and (existing["status"] or "") == "draft")
    if notice_id == WELCOME_NOTICE_ID:
        # Welcome notice stays pinned at the top of the colony board.
        pinned = 1
        pin_order = 0
    elif status == "draft":
        # Drafts stay off the public board pin list until published.
        pinned = 0
        pin_order = 0
    else:
        if "pinned" in payload:
            pinned = 1 if payload.get("pinned") else 0
        elif existing:
            pinned = int(existing["pinned"] or 0)
        else:
            pinned = 0

        if pinned:
            if "pinOrder" in payload or "pin_order" in payload:
                pin_order = int(payload.get("pinOrder", payload.get("pin_order")) or 0)
            elif was_pinned and existing is not None and not was_draft:
                pin_order = int(existing["pin_order"] or 0)
            else:
                pin_order = _next_pin_order(conn)
        else:
            pin_order = 0

    category = (payload.get("category") or (existing["category"] if existing else None) or "general").strip()[:40]
    if "audience" in payload:
        audience = _notice_audience(payload.get("audience"))
    elif existing and "audience" in existing.keys():
        audience = _notice_audience(existing["audience"])
    else:
        audience = "members"

    # Fresh publish timestamp when leaving draft (or creating published).
    if status == "published" and (was_draft or not existing):
        published_at = utc_now()
    else:
        published_at = payload.get("publishedAt") or (existing["published_at"] if existing else None) or utc_now()
    # Keep original author as owner (needed for draft sharing ACL).
    if existing and existing["published_by"]:
        published_by = existing["published_by"]
    else:
        published_by = publisher or None

    conn.execute(
        """
        INSERT INTO notices(id, title, body, category, pinned, pin_order, published_at, published_by, status, title_hi, body_hi, audience)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
          title=excluded.title,
          body=excluded.body,
          category=excluded.category,
          pinned=excluded.pinned,
          pin_order=excluded.pin_order,
          published_at=excluded.published_at,
          published_by=excluded.published_by,
          status=excluded.status,
          title_hi=excluded.title_hi,
          body_hi=excluded.body_hi,
          audience=excluded.audience
        """,
        (
            notice_id,
            title,
            body or "",
            category,
            pinned,
            pin_order,
            published_at,
            published_by,
            status,
            title_hi or None,
            body_hi or None,
            audience,
        ),
    )
    if status == "published" and was_draft:
        conn.execute("DELETE FROM notice_shares WHERE notice_id = ?", (notice_id,))
    if notice_id == WELCOME_NOTICE_ID or (was_pinned and not pinned) or (was_draft and status == "published" and pinned):
        _reindex_pinned(conn)
    conn.commit()
    return get_notice(conn, notice_id, viewer=actor) or {"id": notice_id}


def delete_notice(
    conn: sqlite3.Connection,
    notice_id: str,
    *,
    actor: dict | None = None,
) -> None:
    ensure_notice_pin_order(conn)
    ensure_notice_shares_table(conn)
    nid = (notice_id or "").strip()
    if not nid:
        raise ValueError("notice id required")
    if nid == WELCOME_NOTICE_ID:
        raise ValueError("Welcome notice cannot be deleted")
    row = conn.execute("SELECT * FROM notices WHERE id = ?", (nid,)).fetchone()
    if not row:
        raise ValueError("Notice not found")
    if (row["status"] or "") == "draft" and not _is_notice_owner(row, actor):
        raise ValueError("Only the draft owner can delete this draft")
    was_pinned = bool(int(row["pinned"] or 0))
    conn.execute("DELETE FROM notice_shares WHERE notice_id = ?", (nid,))
    conn.execute("DELETE FROM notice_likes WHERE notice_id = ?", (nid,))
    conn.execute("DELETE FROM notice_comments WHERE notice_id = ?", (nid,))
    cur = conn.execute("DELETE FROM notices WHERE id = ?", (nid,))
    if cur.rowcount < 1:
        conn.commit()
        raise ValueError("Notice not found")
    if was_pinned:
        _reindex_pinned(conn)
    import shutil

    img_dir = notice_images_root(_SITE_ROOT) / re.sub(r"[^A-Za-z0-9_-]", "", nid)
    if img_dir.is_dir():
        shutil.rmtree(img_dir, ignore_errors=True)
    conn.commit()


# --- Super-admin observability (access / function usage) --------------------

_ACCESS_ACTION_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^POST /api/rwa/login$"), "Super admin login"),
    (re.compile(r"^POST /api/rwa/logout$"), "Sign out"),
    (re.compile(r"^POST /api/rwa/otp/request$"), "Request OTP"),
    (re.compile(r"^POST /api/rwa/otp/verify$"), "Verify OTP / sign in"),
    (re.compile(r"^GET /api/rwa/session$"), "Session check"),
    (re.compile(r"^GET /api/rwa/colony-services$"), "View colony services"),
    (re.compile(r"^PUT /api/rwa/colony-services$"), "Update colony services"),
    (re.compile(r"^GET /api/rwa/notices$"), "View notices"),
    (re.compile(r"^POST /api/rwa/notices$"), "Create notice"),
    (re.compile(r"^PATCH /api/rwa/notices/[^/]+$"), "Update notice"),
    (re.compile(r"^DELETE /api/rwa/notices/[^/]+$"), "Delete notice"),
    (re.compile(r"^POST /api/rwa/notices/[^/]+/like$"), "Like / unlike notice"),
    (re.compile(r"^GET /api/rwa/notices/[^/]+/comments$"), "View notice comments"),
    (re.compile(r"^POST /api/rwa/notices/[^/]+/comments$"), "Comment on notice"),
    (re.compile(r"^DELETE /api/rwa/notices/[^/]+/comments/[^/]+$"), "Delete notice comment"),
    (re.compile(r"^GET /api/rwa/household/[^/]+/members$"), "View household members"),
    (re.compile(r"^POST /api/rwa/household/[^/]+/members$"), "Add household member"),
    (re.compile(r"^PATCH /api/rwa/household/[^/]+/members/[^/]+$"), "Update household member"),
    (re.compile(r"^DELETE /api/rwa/household/[^/]+/members/[^/]+$"), "Remove household member"),
    (re.compile(r"^PUT /api/rwa/notices/[^/]+/shares$"), "Share draft"),
    (re.compile(r"^GET /api/rwa/notices/[^/]+/shares$"), "View draft shares"),
    (re.compile(r"^GET /api/rwa/ec-members$"), "List EC members"),
    (re.compile(r"^GET /api/rwa/grievances"), "View concerns"),
    (re.compile(r"^POST /api/rwa/grievances$"), "Submit concern"),
    (re.compile(r"^POST /api/rwa/grievances/[^/]+/messages$"), "Reply to concern"),
    (re.compile(r"^PATCH /api/rwa/grievances/[^/]+$"), "Update concern status"),
    (re.compile(r"^GET /api/rwa/directory$"), "View directory"),
    (re.compile(r"^GET /api/rwa/residents/revisions$"), "View revision history"),
    (re.compile(r"^GET /api/rwa/residents$"), "View roster"),
    (re.compile(r"^PATCH /api/rwa/residents/[^/]+$"), "Update resident"),
    (re.compile(r"^POST /api/rwa/residents/[^/]+/promote$"), "Promote / demote EC"),
    (re.compile(r"^GET /api/rwa/payments/me$"), "View own dues"),
    (re.compile(r"^GET /api/rwa/payments$"), "View ledger"),
    (re.compile(r"^PATCH /api/rwa/payments/[^/]+$"), "Edit ledger row"),
    (re.compile(r"^GET /api/rwa/bank"), "View bank details"),
    (re.compile(r"^PUT /api/rwa/bank"), "Update bank details"),
    (re.compile(r"^POST /api/rwa/bank"), "Update bank / QR"),
    (re.compile(r"^PATCH /api/rwa/profile$"), "Update profile"),
    (re.compile(r"^GET /api/rwa/profile$"), "View profile"),
    (re.compile(r"^GET /api/rwa/smtp/status$"), "SMTP status"),
    (re.compile(r"^GET /api/rwa/settings$"), "View settings"),
    (re.compile(r"^(PUT|PATCH) /api/rwa/settings$"), "Save settings"),
    (re.compile(r"^POST /api/rwa/ledger/import$"), "Import ledger PDF"),
    (re.compile(r"^GET /api/rwa/info-centre$"), "Browse Information Centre"),
    (re.compile(r"^POST /api/rwa/info-centre$"), "Create Information Centre doc"),
    (re.compile(r"^PATCH /api/rwa/info-centre/[^/]+$"), "Update Information Centre doc"),
    (re.compile(r"^DELETE /api/rwa/info-centre/[^/]+$"), "Delete Information Centre doc"),
    (re.compile(r"^GET /api/rwa/info-centre/[^/]+/file$"), "Open Information Centre file"),
    (re.compile(r"^GET /api/rwa/templates$"), "Browse printable templates"),
    (re.compile(r"^POST /api/rwa/templates$"), "Create printable template"),
    (re.compile(r"^PATCH /api/rwa/templates/[^/]+$"), "Update printable template"),
    (re.compile(r"^DELETE /api/rwa/templates/[^/]+$"), "Delete printable template"),
    (re.compile(r"^GET /api/rwa/templates/[^/]+/file$"), "Open printable template"),
    (re.compile(r"^GET /api/rwa/works$"), "Browse Works & Events"),
    (re.compile(r"^POST /api/rwa/works$"), "Create Works & Events item"),
    (re.compile(r"^PATCH /api/rwa/works/[^/]+$"), "Update Works & Events item"),
    (re.compile(r"^DELETE /api/rwa/works/[^/]+$"), "Delete Works & Events item"),
    (re.compile(r"^GET /api/rwa/campaigns$"), "Browse campaigns"),
    (re.compile(r"^POST /api/rwa/campaigns$"), "Create campaign"),
    (re.compile(r"^PATCH /api/rwa/campaigns/[^/]+$"), "Update campaign"),
    (re.compile(r"^DELETE /api/rwa/campaigns/[^/]+$"), "Delete campaign"),
    (re.compile(r"^POST /api/rwa/campaigns/[^/]+/contributions$"), "Submit campaign contribution"),
    (re.compile(r"^PATCH /api/rwa/campaigns/[^/]+/contributions/[^/]+$"), "Review campaign contribution"),
    (re.compile(r"^DELETE /api/rwa/campaigns/[^/]+/contributions/[^/]+$"), "Remove campaign contribution"),
    (re.compile(r"^DELETE /api/rwa/campaigns/[^/]+/pledges/[^/]+$"), "Remove campaign pledge"),
    (re.compile(r"^GET /api/rwa/proceedings$"), "Browse Proceedings register"),
    (re.compile(r"^POST /api/rwa/proceedings$"), "Create Proceedings entry"),
    (re.compile(r"^PATCH /api/rwa/proceedings/[^/]+$"), "Update Proceedings entry"),
    (re.compile(r"^DELETE /api/rwa/proceedings/[^/]+$"), "Delete Proceedings entry"),
]

_PANEL_LABELS = {
    "home": "Open Home (colony board)",
    "dues": "Open Dues",
    "concerns": "Open Concerns",
    "directory": "Open Directory",
    "profile": "Open Profile",
    "admin": "Open EC desk",
    "info": "Open Information Centre",
    "works": "Open Works & Events",
    "observability": "Open Observability",
}

# High-frequency GETs we skip to keep the log useful.
_ACCESS_SKIP_GET_PATHS = {
    "/api/rwa/session",
    "/api/rwa/smtp/status",
}


def access_action_label(method: str, path: str, *, panel: str | None = None) -> str:
    if panel:
        return _PANEL_LABELS.get(panel, f"Open panel · {panel}")
    key = f"{(method or 'GET').upper()} {(path or '').split('?', 1)[0]}"
    for pattern, label in _ACCESS_ACTION_RULES:
        if pattern.match(key):
            return label
    short = (path or "").replace("/api/rwa/", "").strip("/") or "rwa"
    return f"{(method or 'GET').upper()} {short}"


def should_log_rwa_request(method: str, path: str) -> bool:
    path = (path or "").split("?", 1)[0]
    if not path.startswith("/api/rwa/"):
        return False
    if path.startswith("/api/rwa/observability"):
        return False
    method_u = (method or "GET").upper()
    if method_u == "GET" and path in _ACCESS_SKIP_GET_PATHS:
        return False
    return True


def record_access_event(
    conn: sqlite3.Connection,
    *,
    actor: dict | None = None,
    event_type: str = "api",
    method: str | None = None,
    path: str | None = None,
    action: str | None = None,
    status_code: int | None = None,
    panel: str | None = None,
    detail: str | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
) -> None:
    ensure_access_events_table(conn)
    house_id = None
    actor_name = None
    role = None
    is_sa = 0
    if actor:
        house_id = str(actor.get("houseId") or actor.get("house_id") or "") or None
        actor_name = str(actor.get("name") or "") or None
        role = str(actor.get("role") or "") or None
        is_sa = 1 if (actor.get("superAdmin") or is_superadmin_resident(actor)) else 0
    label = (action or "").strip() or access_action_label(method or "GET", path or "", panel=panel)
    conn.execute(
        """
        INSERT INTO access_events(
          created_at, house_id, actor_name, role, is_superadmin,
          event_type, method, path, action, status_code, panel, detail, ip, user_agent
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            utc_now(),
            house_id,
            actor_name,
            role,
            is_sa,
            (event_type or "api")[:40],
            (method or "")[:12] or None,
            (path or "")[:240] or None,
            label[:160],
            status_code,
            (panel or "")[:40] or None,
            (detail or "")[:500] or None,
            (ip or "")[:80] or None,
            (user_agent or "")[:240] or None,
        ),
    )
    # Soft retention: drop oldest beyond ~30k rows.
    count = conn.execute("SELECT COUNT(*) FROM access_events").fetchone()[0]
    if count and int(count) > 30000:
        conn.execute(
            """
            DELETE FROM access_events WHERE id IN (
              SELECT id FROM access_events ORDER BY id ASC LIMIT ?
            )
            """,
            (int(count) - 25000,),
        )
    conn.commit()


def observability_dashboard(
    conn: sqlite3.Connection,
    *,
    days: int = 7,
    limit: int = 200,
    house_id: str | None = None,
) -> dict:
    ensure_access_events_table(conn)
    days = max(1, min(int(days or 7), 90))
    limit = max(20, min(int(limit or 200), 500))
    since = (datetime.now(timezone.utc) - timedelta(days=days)).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    where = ["created_at >= ?"]
    params: list[Any] = [since]
    if house_id:
        where.append("house_id = ? COLLATE NOCASE")
        params.append(normalize_house_id(house_id) if house_id != SUPERADMIN_HOUSE_ID else house_id)
    where_sql = " AND ".join(where)

    total = conn.execute(f"SELECT COUNT(*) FROM access_events WHERE {where_sql}", params).fetchone()[0]
    unique_users = conn.execute(
        f"SELECT COUNT(DISTINCT house_id) FROM access_events WHERE {where_sql} AND house_id IS NOT NULL AND house_id != ''",
        params,
    ).fetchone()[0]
    logins = conn.execute(
        f"""
        SELECT COUNT(*) FROM access_events
        WHERE {where_sql} AND action IN ('Super admin login', 'Verify OTP / sign in')
        """,
        params,
    ).fetchone()[0]
    panel_views = conn.execute(
        f"SELECT COUNT(*) FROM access_events WHERE {where_sql} AND event_type = 'panel'",
        params,
    ).fetchone()[0]
    api_calls = conn.execute(
        f"SELECT COUNT(*) FROM access_events WHERE {where_sql} AND event_type = 'api'",
        params,
    ).fetchone()[0]

    top_actions = [
        {"action": r["action"], "count": r["c"]}
        for r in conn.execute(
            f"""
            SELECT action, COUNT(*) AS c FROM access_events
            WHERE {where_sql}
            GROUP BY action
            ORDER BY c DESC
            LIMIT 12
            """,
            params,
        ).fetchall()
    ]
    top_users = [
        {
            "houseId": r["house_id"],
            "name": r["actor_name"] or r["house_id"],
            "role": r["role"] or "",
            "count": r["c"],
        }
        for r in conn.execute(
            f"""
            SELECT house_id, MAX(actor_name) AS actor_name, MAX(role) AS role, COUNT(*) AS c
            FROM access_events
            WHERE {where_sql} AND house_id IS NOT NULL AND house_id != ''
            GROUP BY house_id
            ORDER BY c DESC
            LIMIT 12
            """,
            params,
        ).fetchall()
    ]
    recent = [
        {
            "id": r["id"],
            "createdAt": r["created_at"],
            "houseId": r["house_id"] or "",
            "name": r["actor_name"] or (r["house_id"] or "anonymous"),
            "role": r["role"] or "",
            "superAdmin": bool(r["is_superadmin"]),
            "eventType": r["event_type"],
            "method": r["method"] or "",
            "path": r["path"] or "",
            "action": r["action"],
            "statusCode": r["status_code"],
            "panel": r["panel"] or "",
            "ip": r["ip"] or "",
        }
        for r in conn.execute(
            f"""
            SELECT * FROM access_events
            WHERE {where_sql}
            ORDER BY id DESC
            LIMIT ?
            """,
            [*params, limit],
        ).fetchall()
    ]
    by_day = [
        {"day": r["d"], "count": r["c"]}
        for r in conn.execute(
            f"""
            SELECT substr(created_at, 1, 10) AS d, COUNT(*) AS c
            FROM access_events
            WHERE {where_sql}
            GROUP BY d
            ORDER BY d ASC
            """,
            params,
        ).fetchall()
    ]

    return {
        "days": days,
        "since": since,
        "summary": {
            "totalEvents": int(total or 0),
            "uniqueUsers": int(unique_users or 0),
            "logins": int(logins or 0),
            "panelViews": int(panel_views or 0),
            "apiCalls": int(api_calls or 0),
        },
        "topActions": top_actions,
        "topUsers": top_users,
        "byDay": by_day,
        "recent": recent,
    }


def update_profile(
    conn: sqlite3.Connection,
    house_id: str,
    payload: dict,
    *,
    as_admin: bool = False,
    actor: dict | None = None,
    change_source: str = "profile",
) -> dict:
    resident = find_resident(conn, house_id, include_inactive=as_admin)
    if not resident:
        raise ValueError("resident not found")

    before = _resident_snapshot(resident)
    actor = actor or {}
    actor_is_super = is_superadmin_resident(actor)

    if resident.get("house_id") == SUPERADMIN_HOUSE_ID:
        if payload.get("role") and payload.get("role") != "admin":
            raise ValueError("Cannot change super-admin role")
        if payload.get("status") and payload.get("status") != "active":
            raise ValueError("Cannot suspend super-admin")
        payload = {**payload, "role": "admin", "status": "active", "name": resident.get("name") or "Portal Super Admin"}

    if "email" in payload:
        email = str(payload.get("email") or "").strip().lower() or None
    else:
        email = resident.get("email")

    if "phone" in payload:
        phone = normalize_phone(payload.get("phone"))
    else:
        phone = resident.get("phone")

    if "name" in payload:
        name = str(payload.get("name") or "").strip()[:120]
        if not name:
            raise ValueError("name required")
    else:
        name = resident.get("name") or ""

    # Personal profile fields — resident can edit own; EC can edit any
    if "title" in payload:
        title = str(payload.get("title") or "").strip()[:40] or None
    else:
        title = resident.get("title")

    if "profession" in payload:
        profession = str(payload.get("profession") or "").strip()[:80] or None
    else:
        profession = resident.get("profession")

    employment = resident.get("employment_status") or "unknown"
    if "employmentStatus" in payload or "employment_status" in payload:
        raw_emp = payload.get("employmentStatus", payload.get("employment_status"))
        employment = str(raw_emp or "unknown").strip().lower()
        if employment not in {"working", "retired", "unknown"}:
            raise ValueError("employmentStatus must be working, retired, or unknown")

    official_title = resident.get("official_title")
    if "officialTitle" in payload or "official_title" in payload:
        if not as_admin and not actor_is_super:
            raise ValueError("Only EC / super admin can set official title")
        official_title = str(payload.get("officialTitle", payload.get("official_title")) or "").strip()[:80] or None

    can_manage_roles = actor_is_super or entitlements.actor_has(actor, "sensitive_ops") or entitlements.actor_has(actor, "manage_roles")
    is_office_bearer = bool(int(resident.get("is_office_bearer") or 0)) or bool(
        str(resident.get("official_title") or "").strip()
    ) or (resident.get("role") == "admin")
    is_ec_member = bool(int(resident.get("is_ec_member") or 0)) or is_office_bearer or (
        resident.get("role") == "admin"
    )

    if "isEcMember" in payload or "ecMember" in payload:
        if not can_manage_roles:
            raise ValueError("manage_roles entitlement required")
        want_mem = bool(payload.get("isEcMember", payload.get("ecMember")))
        if want_mem:
            is_ec_member = True
        else:
            # Removing EC membership also clears OB / admin (with guards)
            if (resident.get("role") == "admin" or payload.get("role") == "admin") and entitlements.count_ec_admins(conn) <= 1:
                raise ValueError("Cannot remove the last EC Admin from EC membership")
            is_ec_member = False
            is_office_bearer = False
            if "role" not in payload:
                payload = {**payload, "role": "resident"}
            if "isOfficeBearer" not in payload and "officeBearer" not in payload:
                payload = {**payload, "isOfficeBearer": False}

    # EC seat holder: owner or primary delegate only.
    ec_member_id = str(resident.get("ec_member_id") or "").strip() or None
    if "ecMemberId" in payload or "ec_member_id" in payload:
        if not can_manage_roles:
            raise ValueError("manage_roles entitlement required")
        raw_seat = payload.get("ecMemberId", payload.get("ec_member_id"))
        if raw_seat is None or str(raw_seat).strip() == "":
            ec_member_id = household.resolve_ec_member_id(conn, resident["house_id"])
        else:
            ec_member_id = household.resolve_ec_member_id(
                conn, resident["house_id"], ec_member_id=str(raw_seat).strip()
            )
    elif is_ec_member and not ec_member_id:
        ec_member_id = household.resolve_ec_member_id(conn, resident["house_id"])
    if is_ec_member and ec_member_id:
        # Re-validate whenever plot stays / becomes EC.
        ec_member_id = household.resolve_ec_member_id(
            conn, resident["house_id"], ec_member_id=ec_member_id
        )
    if not is_ec_member:
        ec_member_id = None

    if "isOfficeBearer" in payload or "officeBearer" in payload:
        if not can_manage_roles:
            raise ValueError("manage_roles entitlement required")
        want_ob = bool(payload.get("isOfficeBearer", payload.get("officeBearer")))
        if want_ob:
            if not official_title:
                raise ValueError("Official title is required for office bearers")
            is_office_bearer = True
            is_ec_member = True
        else:
            if (resident.get("role") == "admin" or payload.get("role") == "admin") and entitlements.count_ec_admins(conn) <= 1:
                raise ValueError("Cannot remove the last EC Admin from office bearer status")
            is_office_bearer = False
            if "role" not in payload:
                payload = {**payload, "role": "resident"}
            # Stay EC member unless explicitly cleared

    # Setting a title implies office bearer (+ EC member) when managed via roles
    if official_title and can_manage_roles and (
        "officialTitle" in payload or "official_title" in payload
    ):
        is_office_bearer = True
        is_ec_member = True

    role = resident.get("role")
    if "role" in payload and payload.get("role") in {"admin", "resident"}:
        new_role = payload["role"]
        if new_role != role:
            if not can_manage_roles:
                raise ValueError("manage_roles entitlement required to change EC Admin role")
            if new_role == "admin":
                if not is_office_bearer and not official_title:
                    raise ValueError("Only office bearers can be elevated to EC Admin")
                is_office_bearer = True
                is_ec_member = True
            else:
                if entitlements.count_ec_admins(conn) <= 1 and role == "admin":
                    raise ValueError("Cannot demote the last EC Admin")
            role = new_role

    if role == "admin":
        is_office_bearer = True
        is_ec_member = True
    if is_office_bearer:
        is_ec_member = True

    notes = resident.get("notes")
    if as_admin and "notes" in payload:
        notes = str(payload.get("notes") or "").strip()[:500] or None

    status = resident.get("status") or "active"
    if "status" in payload and payload.get("status") in {"active", "inactive"}:
        new_status = payload["status"]
        if new_status != status:
            if (resident.get("role") == "admin" or role == "admin") and not actor_is_super:
                raise ValueError("Only super admin can suspend or reinstate EC admins")
            if not as_admin and not actor_is_super:
                raise ValueError("Admin access required to change status")
            status = new_status

    entitlements.ensure_ready(conn)
    was_ec_member = bool(int(resident.get("is_ec_member") or 0)) or bool(
        int(resident.get("is_office_bearer") or 0)
    ) or bool(str(resident.get("official_title") or "").strip()) or (
        (resident.get("role") or "") == "admin"
    )
    conn.execute(
        """
        UPDATE residents SET
          email=?, phone=?, name=?, title=?, profession=?, employment_status=?,
          official_title=?, is_ec_member=?, is_office_bearer=?, role=?, notes=?, status=?,
          ec_member_id=?, updated_at=?
        WHERE house_id=?
        """,
        (
            email,
            phone,
            name,
            title,
            profession,
            employment,
            official_title,
            1 if is_ec_member else 0,
            1 if is_office_bearer else 0,
            role,
            notes,
            status,
            ec_member_id,
            utc_now(),
            resident["house_id"],
        ),
    )

    if role == "admin":
        # Drop redundant implicit grants; keep / refresh explicit grants via set_grants below.
        for key in entitlements.GRANTABLE_ENTITLEMENTS - entitlements.EXPLICIT_GRANT_ENTITLEMENTS:
            conn.execute(
                "DELETE FROM resident_entitlements WHERE house_id = ? AND entitlement = ?",
                (resident["house_id"], key),
            )
    elif not is_ec_member:
        conn.execute("DELETE FROM resident_entitlements WHERE house_id = ?", (resident["house_id"],))

    # One-off entitlement grants (EC members/bearers; EC Admins only store explicit grants)
    if "entitlements" in payload and isinstance(payload.get("entitlements"), list):
        if not can_manage_roles:
            raise ValueError("manage_roles entitlement required")
        entitlements.set_grants(
            conn,
            resident["house_id"],
            payload["entitlements"],
            granted_by=actor.get("houseId"),
            commit=False,
        )
    elif is_ec_member and not was_ec_member and role != "admin":
        # New EC members get Pass · manage / upgrade-staff by default (EC Admin can revoke later).
        entitlements.grant_pass_manage_if_needed(
            conn,
            resident["house_id"],
            granted_by=actor.get("houseId") or "system:ec_join",
            commit=False,
        )
        entitlements.grant_pass_upgrade_staff_if_needed(
            conn,
            resident["house_id"],
            granted_by=actor.get("houseId") or "system:ec_join",
            commit=False,
        )

    after = {
        "houseId": resident["house_id"],
        "plotNo": resident.get("plot_no"),
        "section": resident.get("section"),
        "name": name,
        "title": title or "",
        "profession": profession or "",
        "employmentStatus": employment,
        "officialTitle": official_title or "",
        "isEcMember": is_ec_member,
        "isOfficeBearer": is_office_bearer,
        "email": email or "",
        "phone": phone or "",
        "role": role,
        "status": status,
        "notes": notes or "",
    }
    record_resident_revision(
        conn,
        house_id=resident["house_id"],
        before=before,
        after=after,
        actor=actor,
        change_source=change_source,
    )
    # Keep Directory + Dues on the same master: roster/profile writes flow both ways.
    household.sync_resident_to_primary(conn, resident["house_id"])
    conn.commit()

    refreshed = find_resident(conn, house_id, include_inactive=True) or {**resident, **{
        "name": name, "email": email, "phone": phone, "title": title,
        "profession": profession, "employment_status": employment,
        "official_title": official_title,
        "is_ec_member": 1 if is_ec_member else 0,
        "is_office_bearer": 1 if is_office_bearer else 0,
        "role": role, "notes": notes, "status": status,
    }}
    return public_actor(conn, refreshed)


def create_session_for_resident(
    conn: sqlite3.Connection,
    resident: dict,
    *,
    member: dict | None = None,
) -> dict:
    ensure_household_members_table(conn)
    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    expires_at = _session_expiry_iso(now)
    mid = None
    if member:
        mid = member.get("id")
    elif resident.get("house_id") != SUPERADMIN_HOUSE_ID:
        primary = household.primary_member(conn, resident["house_id"])
        mid = primary.get("id") if primary else None
        member = primary
    conn.execute(
        "INSERT INTO sessions(token, house_id, member_id, role, created_at, expires_at) VALUES (?, ?, ?, ?, ?, ?)",
        (token, resident["house_id"], mid, resident["role"], utc_now(), expires_at),
    )
    conn.commit()
    return {
        "token": token,
        "expiresAt": expires_at,
        "resident": public_actor(conn, resident, member=member),
    }


def login_with_password(conn: sqlite3.Connection, username: str, password: str) -> dict | None:
    user = (username or "").strip().lower()
    if not user or not password:
        return None
    row = conn.execute(
        "SELECT * FROM portal_accounts WHERE username = ?",
        (user,),
    ).fetchone()
    if not row or not verify_password(password, row["password_hash"]):
        return None
    resident = find_resident(conn, row["house_id"])
    if not resident:
        return None
    # Force admin role for portal password accounts
    if resident.get("role") != "admin":
        conn.execute(
            "UPDATE residents SET role='admin', updated_at=? WHERE house_id=?",
            (utc_now(), resident["house_id"]),
        )
        conn.commit()
        resident = find_resident(conn, row["house_id"]) or resident
    return create_session_for_resident(conn, resident)
