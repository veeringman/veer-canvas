"""HBC Sanyard / RWA portal API helpers (SQLite-backed)."""

from __future__ import annotations

import hashlib
import json
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
    if _scripts.is_dir() and str(_scripts) not in sys.path:
        sys.path.insert(0, str(_scripts))
        break
else:
    # Still insert default so ImportError message is clear
    sys.path.insert(0, str(_SCRIPT_CANDIDATES[0]))

from init_rwa_db import (  # noqa: E402
    SUPERADMIN_HOUSE_ID,
    connect,
    ensure_bank_account_columns,
    ensure_db,
    ensure_grievances_table,
    ensure_notice_pin_order,
    ensure_notice_shares_table,
    ensure_notice_engagement_tables,
    ensure_household_members_table,
    ensure_access_events_table,
    ensure_info_documents_table,
    ensure_colony_works_table,
    migrate_roman_plot_ids,
    ensure_otp_pending_columns,
    ensure_resident_profile_columns,
    ensure_superadmin_account,
    ensure_entitlements_schema,
    ensure_report_templates_table,
    ensure_bilingual_content_columns,
    ensure_payment_records_tables,
    ensure_no_dues_requests_table,
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
        or "vij.ksh@gmail.com"
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
)

_OPS_DEFAULTS: dict[str, object] = {
    "alertTo": "",
    "vitalsEnabled": True,
    "backupRetainDays": 14,
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
    smtp_from = env.get("RWA_SMTP_FROM") or env.get("RWA_SMTP_USER") or ""
    alert_to = env.get("BACKUP_ALERT_TO") or env.get("RWA_OPS_ALERT_TO") or smtp_from
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
        "BACKUP_RETAIN_DAYS": _int("backupRetainDays", 14),
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
        "statusFile": str(status_path),
    }


def _smtp_env_path(site_root: pathlib.Path) -> pathlib.Path:
    return site_root / "data" / "smtp.env"


def read_platform_settings(site_root: pathlib.Path) -> dict:
    """Return editable platform settings (never include raw SMTP password)."""
    _load_env_file(_smtp_env_path(site_root))
    status = smtp_status(site_root)
    return {
        "smtp": {
            "provider": status["provider"] or "gmail",
            "host": status["host"] or "smtp.gmail.com",
            "port": status["port"] or 587,
            "user": status["user"] or "vij.ksh@gmail.com",
            "from": status["from"] or "vij.ksh@gmail.com",
            "passwordSet": status["passwordSet"],
            "configured": status["configured"],
        },
        "otpTtl": status["otpTtl"],
        "superadminUser": (os.environ.get("RWA_SUPERADMIN_USER") or "admin").strip() or "admin",
        "envFile": status["envFile"],
        "ops": read_ops_settings(site_root),
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
        "RWA_SMTP_USER": str(smtp.get("user") or payload.get("user") or existing.get("RWA_SMTP_USER") or "vij.ksh@gmail.com").strip(),
        "RWA_SMTP_FROM": str(smtp.get("from") or payload.get("from") or existing.get("RWA_SMTP_FROM") or "vij.ksh@gmail.com").strip(),
        "RWA_OTP_TTL": str(payload.get("otpTtl") or existing.get("RWA_OTP_TTL") or "600").strip(),
    }
    if payload.get("superadminUser"):
        mapping["RWA_SUPERADMIN_USER"] = str(payload["superadminUser"]).strip().lower()

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

    lines = [
        "# HBC Sanyard portal settings (managed via Super admin → Settings).",
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
        if key in mapping:
            lines.append(f"{key}={mapping[key]}")
    for key, value in sorted(mapping.items()):
        if key in _SETTINGS_KEYS or key in _OPS_ENV_KEYS or key == "RWA_SMTP_PASS":
            continue
        lines.append(f"{key}={value}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass

    for key, value in mapping.items():
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
        ensure_entitlements_schema(conn)
        ensure_report_templates_table(conn)
        ensure_bilingual_content_columns(conn)
        ensure_payment_records_tables(conn)
        ensure_no_dues_requests_table(conn)
        ensure_document_attestations_table(conn)
        ensure_treasury_columns(conn)
        ensure_messages_and_push_tables(conn)
        ensure_msg_likes_and_ai(conn)
        try:
            import rwa_payments as _rwa_payments

            _rwa_payments.reconcile_orphan_receipts(conn, site_root)
        except Exception:
            pass
        try:
            repair_missing_info_files(conn, site_root)
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
        msg["Subject"] = "HBC Sanyard — code for resident login"
        msg["From"] = f"HBC Sanyard RWA <{cfg['from']}>"
        msg["To"] = email
        msg["Reply-To"] = cfg["from"]
        msg.set_content(
            f"Your one-time code for resident login is: {code}\n\n"
            f"Plot: {house_id}\n"
            f"It expires in {OTP_TTL_SECONDS // 60} minutes.\n"
            "If you did not request this, ignore this email.\n\n"
            "— Residents Welfare Association\n"
            "  Housing Board Colony Sanyard, Mandi\n"
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
        "canManageHousehold": True,
        "viewOnly": False,
        "isEcMember": is_mem,
        "isOfficeBearer": is_ob,
        "isEcAdmin": (r.get("role") or "") == "admin" or super_admin,
        "entitlements": [],
        "hasPhoto": False,
        "photoUrl": "",
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
        out["isPrimary"] = bool(pub.get("isPrimary"))
        out["canManageHousehold"] = bool(pub.get("canManage") or pub.get("isPrimary")) and not bool(pub.get("viewOnly"))
        out["viewOnly"] = bool(pub.get("viewOnly"))
        out["hasPhoto"] = bool(pub.get("hasPhoto"))
        out["photoUrl"] = pub.get("photoUrl") or ""
        plot_is_ec = (r.get("role") or "") == "admin"
        out["plotIsEc"] = plot_is_ec
        if not out["isPrimary"] and out["role"] == "admin":
            out["role"] = "resident"
            out["isEcAdmin"] = False
        if out["viewOnly"]:
            out["role"] = "resident"
            out["isEcAdmin"] = False
            out["canManageHousehold"] = False
            out["officialTitle"] = ""
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


def directory(conn: sqlite3.Connection, *, include_contacts: bool = False) -> list[dict]:
    entitlements.ensure_ready(conn)
    if include_contacts:
        rows = conn.execute(
            """
            SELECT house_id, plot_no, section, name, title, profession, employment_status,
                   official_title, is_ec_member, is_office_bearer, role, email, phone, notes, status
            FROM residents
            WHERE house_id != ?
            """,
            (SUPERADMIN_HOUSE_ID,),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT house_id, plot_no, section, name, title, profession, employment_status,
                   official_title, is_ec_member, is_office_bearer, role, email, phone, notes, status
            FROM residents
            WHERE status = 'active' AND house_id != ?
            """,
            (SUPERADMIN_HOUSE_ID,),
        ).fetchall()
    photos = primary_member_photo_map(conn)
    out = []
    for r in rows:
        is_ec = (r["role"] or "") == "admin"
        is_ob = bool(int(r["is_office_bearer"] or 0)) or bool(r["official_title"] or "") or is_ec
        is_mem = bool(int(r["is_ec_member"] or 0)) or is_ob or is_ec
        photo = photos.get(r["house_id"]) or photo_fields_for_member(None, None)
        item = {
            "houseId": r["house_id"],
            "plotNo": r["plot_no"],
            "section": r["section"],
            "name": r["name"],
            "role": r["role"],
            "officialTitle": r["official_title"] or "",
            "isEcMember": is_mem,
            "isOfficeBearer": is_ob,
            "isEcAdmin": is_ec,
            "email": r["email"] or "",
            "phone": r["phone"] or "",
            "hasPhone": bool(r["phone"]),
            "hasEmail": bool(r["email"]),
            "hasPhoto": photo["hasPhoto"],
            "photoUrl": photo["photoUrl"],
            "primaryMemberId": photo.get("memberId"),
        }
        if include_contacts:
            item["title"] = r["title"] or ""
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
    out.sort(
        key=lambda row: section_plot_sort_key(
            row.get("section"),
            row.get("plotNo") or row.get("houseId"),
            row.get("houseId"),
        )
    )
    return out


def roster_stats(conn: sqlite3.Connection) -> dict:
    row = conn.execute(
        """
        SELECT
          COUNT(*) AS total,
          SUM(CASE WHEN phone IS NOT NULL AND TRIM(phone) != '' THEN 1 ELSE 0 END) AS with_phone,
          SUM(CASE WHEN email IS NOT NULL AND TRIM(email) != '' THEN 1 ELSE 0 END) AS with_email
        FROM residents WHERE status = 'active' AND house_id != ?
        """,
        (SUPERADMIN_HOUSE_ID,),
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


def info_centre_categories() -> list[dict]:
    return [{"id": cid, "label": label} for cid, label in INFO_DOC_CATEGORIES]


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


def _info_audience(raw: str | None) -> str:
    key = (raw or "all").strip().lower()
    return key if key in {"all", "ec"} else "all"


def _info_public(r: sqlite3.Row | dict, site_root: pathlib.Path | None = None) -> dict:
    if hasattr(r, "keys"):
        data = {k: r[k] for k in r.keys()}
    else:
        data = dict(r)
    cat = data.get("category") or "general"
    label = next((lbl for cid, lbl in INFO_DOC_CATEGORIES if cid == cat), cat)
    audience = _info_audience(data.get("audience"))
    filename = data.get("filename")
    file_missing = False
    has_file = bool(filename)
    if filename and site_root is not None:
        path = info_doc_file_path(site_root, str(data.get("id") or ""), filename)
        has_file = path is not None
        file_missing = path is None
    return {
        "id": data.get("id"),
        "title": data.get("title") or "",
        "titleHi": data.get("title_hi") or data.get("titleHi") or "",
        "summary": data.get("summary") or "",
        "summaryHi": data.get("summary_hi") or data.get("summaryHi") or "",
        "category": cat,
        "categoryLabel": label,
        "docType": data.get("doc_type") or "file",
        "filename": filename,
        "originalName": data.get("original_name") or data.get("filename") or "",
        "mimeType": data.get("mime_type") or "",
        "sizeBytes": int(data.get("size_bytes") or 0),
        "status": data.get("status") or "draft",
        "audience": audience,
        "audienceLabel": "EC only" if audience == "ec" else "All members",
        "publishedAt": data.get("published_at"),
        "publishedBy": data.get("published_by"),
        "createdAt": data.get("created_at"),
        "updatedAt": data.get("updated_at"),
        "hasFile": has_file,
        "fileMissing": file_missing,
        "hasHtmlHi": bool(int(data.get("has_html_hi") or data.get("hasHtmlHi") or 0)),
    }


def list_info_documents(
    conn: sqlite3.Connection,
    *,
    status: str | None = "published",
    category: str | None = None,
    as_admin: bool = False,
    site_root: pathlib.Path | None = None,
) -> list[dict]:
    ensure_info_documents_table(conn)
    status_key = (status or "published").strip().lower()
    clauses: list[str] = []
    params: list[Any] = []
    if status_key == "all":
        if not as_admin:
            clauses.append("status = 'published'")
    elif status_key in {"draft", "published", "archived"}:
        if status_key != "published" and not as_admin:
            raise ValueError("Admin access required for drafts")
        clauses.append("status = ?")
        params.append(status_key)
    else:
        raise ValueError("Invalid status filter")
    if not as_admin:
        # Residents only see colony-wide published docs (not EC-only).
        clauses.append("(audience IS NULL OR audience = 'all' OR audience = '')")
    if category:
        clauses.append("category = ?")
        params.append(_info_category(category))
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = conn.execute(
        f"""
        SELECT * FROM info_documents
        {where}
        ORDER BY
          CASE status WHEN 'published' THEN 0 WHEN 'draft' THEN 1 ELSE 2 END,
          COALESCE(published_at, updated_at) DESC,
          id DESC
        """,
        params,
    ).fetchall()
    return [_info_public(r, site_root=site_root) for r in rows]


def get_info_document(
    conn: sqlite3.Connection,
    doc_id: str,
    *,
    as_admin: bool = False,
    site_root: pathlib.Path | None = None,
) -> dict | None:
    ensure_info_documents_table(conn)
    row = conn.execute("SELECT * FROM info_documents WHERE id = ?", (doc_id,)).fetchone()
    if not row:
        return None
    if (row["status"] or "") != "published" and not as_admin:
        return None
    audience = _info_audience(row["audience"] if "audience" in row.keys() else "all")
    if audience == "ec" and not as_admin:
        return None
    return _info_public(row, site_root=site_root)


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


def _wrap_html_document(title: str, body_html: str) -> str:
    safe_title = (title or "Document").replace("<", "&lt;").replace(">", "&gt;")
    # Allow simple authored HTML; wrap in a readable page shell.
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n<head>\n'
        '<meta charset="utf-8">\n'
        f"<title>{safe_title}</title>\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        "<style>\n"
        "body{font-family:Georgia,'Times New Roman',serif;line-height:1.55;max-width:42rem;"
        "margin:2rem auto;padding:0 1.25rem;color:#1a2332;background:#f7f4ef;}\n"
        "h1,h2,h3{font-family:'Segoe UI',system-ui,sans-serif;color:#0f2744;}\n"
        "img{max-width:100%;height:auto;} a{color:#1d4ed8;}\n"
        "table{border-collapse:collapse;width:100%;} th,td{border:1px solid #ccc;padding:.4rem .55rem;}\n"
        "</style>\n</head>\n<body>\n"
        f"<h1>{safe_title}</h1>\n"
        f"{body_html}\n"
        "</body>\n</html>\n"
    )


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

    if "audience" in payload:
        audience = _info_audience(payload.get("audience"))
    elif existing and "audience" in existing.keys():
        audience = _info_audience(existing["audience"])
    else:
        audience = "all"

    doc_type = None
    if "docType" in payload or "doc_type" in payload:
        doc_type = payload.get("docType") or payload.get("doc_type")
    elif existing:
        doc_type = existing["doc_type"]
    html_body = payload.get("htmlBody") if "htmlBody" in payload else None
    if "html_body" in payload and html_body is None:
        html_body = payload.get("html_body")
    if not doc_type:
        doc_type = "html" if html_body is not None else "file"
    doc_type = str(doc_type or "file").strip().lower()
    if doc_type not in {"file", "html"}:
        raise ValueError("docType must be file or html")

    now = utc_now()
    filename = existing["filename"] if existing else None
    original_name = existing["original_name"] if existing else None
    mime_type = existing["mime_type"] if existing else None
    size_bytes = int(existing["size_bytes"] or 0) if existing else 0

    if doc_type == "html" and html_body is not None:
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

    if file_storage is not None and getattr(file_storage, "filename", None):
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
        doc_type = "html" if ext in {".html", ".htm"} else "file"
        dest_dir = info_doc_dir(site_root, doc_id)
        _replace_dir_file(dest_dir, filename, data, keep_names=set())
        has_html_hi = 0
    elif not existing and not filename:
        if doc_type == "html":
            raise ValueError("HTML content required")
        raise ValueError("Upload a document file, or create HTML content")

    if filename and not info_doc_file_path(site_root, doc_id, filename):
        raise ValueError("Document file missing on server — please re-upload the file")

    if status == "published" and not filename:
        raise ValueError("Add a file or HTML content before publishing")

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
    conn.execute(
        """
        INSERT INTO info_documents(
          id, title, summary, category, doc_type, filename, original_name, mime_type,
          size_bytes, status, audience, published_at, published_by, created_at, updated_at,
          title_hi, summary_hi, has_html_hi
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
          title=excluded.title,
          summary=excluded.summary,
          category=excluded.category,
          doc_type=excluded.doc_type,
          filename=excluded.filename,
          original_name=excluded.original_name,
          mime_type=excluded.mime_type,
          size_bytes=excluded.size_bytes,
          status=excluded.status,
          audience=excluded.audience,
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
            doc_type,
            filename,
            original_name,
            mime_type,
            size_bytes,
            status,
            audience,
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
    return get_info_document(conn, doc_id, as_admin=True, site_root=site_root) or {"id": doc_id}


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
    wid = (work_id or "").strip()
    if not wid:
        raise ValueError("work id required")
    cur = conn.execute("DELETE FROM colony_works WHERE id = ?", (wid,))
    conn.commit()
    if cur.rowcount < 1:
        raise ValueError("Work item not found")


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
        INSERT INTO notices(id, title, body, category, pinned, pin_order, published_at, published_by, status, title_hi, body_hi)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
          body_hi=excluded.body_hi
        """,
        (notice_id, title, body or "", category, pinned, pin_order, published_at, published_by, status, title_hi or None, body_hi or None),
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
    conn.commit()


# --- Super-admin observability (access / function usage) --------------------

_ACCESS_ACTION_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^POST /api/rwa/login$"), "Super admin login"),
    (re.compile(r"^POST /api/rwa/logout$"), "Sign out"),
    (re.compile(r"^POST /api/rwa/otp/request$"), "Request OTP"),
    (re.compile(r"^POST /api/rwa/otp/verify$"), "Verify OTP / sign in"),
    (re.compile(r"^GET /api/rwa/session$"), "Session check"),
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
    (re.compile(r"^GET /api/rwa/works$"), "Browse Works & Events"),
    (re.compile(r"^POST /api/rwa/works$"), "Create Works & Events item"),
    (re.compile(r"^PATCH /api/rwa/works/[^/]+$"), "Update Works & Events item"),
    (re.compile(r"^DELETE /api/rwa/works/[^/]+$"), "Delete Works & Events item"),
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
    conn.execute(
        """
        UPDATE residents SET
          email=?, phone=?, name=?, title=?, profession=?, employment_status=?,
          official_title=?, is_ec_member=?, is_office_bearer=?, role=?, notes=?, status=?, updated_at=?
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
