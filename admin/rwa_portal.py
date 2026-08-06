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
    ensure_otp_pending_columns,
    ensure_resident_profile_columns,
    ensure_superadmin_account,
    hash_otp,
    normalize_house_id,
    utc_now,
    verify_password,
)

OTP_TTL_SECONDS = int(os.environ.get("RWA_OTP_TTL", "600"))
SESSION_TTL_SECONDS = int(os.environ.get("RWA_SESSION_TTL", str(7 * 24 * 3600)))
HOUSE_RE = re.compile(r"^[A-Za-z0-9/()_-]{1,20}$")
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

    new_pass = str(smtp.get("password") or payload.get("smtpPassword") or "").strip()
    if new_pass:
        mapping["RWA_SMTP_PASS"] = new_pass
    elif "RWA_SMTP_PASS" in existing:
        mapping["RWA_SMTP_PASS"] = existing["RWA_SMTP_PASS"]

    # Preserve unrelated keys
    for key, value in existing.items():
        if key not in mapping and key.startswith("RWA_"):
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
    for key, value in sorted(mapping.items()):
        if key in _SETTINGS_KEYS or key == "RWA_SMTP_PASS":
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
        ensure_grievances_table(conn)
        ensure_superadmin_account(conn)
    return conn


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
        msg["Subject"] = f"HBC Sanyard login code for plot {house_id}"
        msg["From"] = f"HBC Sanyard RWA <{cfg['from']}>"
        msg["To"] = email
        msg["Reply-To"] = cfg["from"]
        msg.set_content(
            f"Your one-time login code for plot {house_id} is: {code}\n\n"
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
    pending_email: str | None = None,
    pending_phone: str | None = None,
) -> dict:
    ensure_otp_pending_columns(conn)
    code = f"{secrets.randbelow(1_000_000):06d}"
    now = datetime.now(timezone.utc)
    expires = (now + timedelta(seconds=OTP_TTL_SECONDS)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    delivery_email = (pending_email or email or "").strip().lower() or None
    conn.execute(
        """
        INSERT INTO otp_challenges(
          house_id, code_hash, email_masked, expires_at, attempts, consumed, created_at,
          pending_email, pending_phone
        )
        VALUES (?, ?, ?, ?, 0, 0, ?, ?, ?)
        """,
        (
            house_id,
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


def verify_otp(conn: sqlite3.Connection, house_id: str, code: str) -> dict | None:
    ensure_otp_pending_columns(conn)
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

    contact_updated = False
    if pending_email or pending_phone:
        try:
            apply_login_contacts(
                conn,
                hid,
                email=pending_email,
                phone=pending_phone,
            )
            contact_updated = True
        except ValueError:
            # Do not block login if contact apply fails after a valid code;
            # resident can fix details in Profile.
            contact_updated = False

    resident = find_resident(conn, hid)
    if not resident:
        return None
    sess = create_session_for_resident(conn, resident)
    if contact_updated:
        sess["contactUpdated"] = True
    return sess


def session_from_token(conn: sqlite3.Connection, token: str | None) -> dict | None:
    if not token:
        return None
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
    return {
        "token": token,
        "expiresAt": row["expires_at"],
        "resident": public_resident(resident),
    }


def destroy_session(conn: sqlite3.Connection, token: str | None) -> None:
    if not token:
        return
    conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
    conn.commit()


def public_resident(r: dict) -> dict:
    super_admin = str(r.get("house_id") or "") == SUPERADMIN_HOUSE_ID
    return {
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
    }


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
    if include_contacts:
        rows = conn.execute(
            """
            SELECT house_id, plot_no, section, name, title, profession, employment_status, official_title, role, email, phone, notes, status
            FROM residents
            WHERE house_id != ?
            ORDER BY section,
              CASE WHEN plot_no GLOB '[0-9]*' THEN CAST(plot_no AS INTEGER) ELSE 9999 END,
              plot_no
            """,
            (SUPERADMIN_HOUSE_ID,),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT house_id, plot_no, section, name, title, profession, employment_status, official_title, role, email, phone, notes, status
            FROM residents
            WHERE status = 'active' AND house_id != ?
            ORDER BY section,
              CASE WHEN plot_no GLOB '[0-9]*' THEN CAST(plot_no AS INTEGER) ELSE 9999 END,
              plot_no
            """,
            (SUPERADMIN_HOUSE_ID,),
        ).fetchall()
    out = []
    for r in rows:
        item = {
            "houseId": r["house_id"],
            "plotNo": r["plot_no"],
            "section": r["section"],
            "name": r["name"],
            "role": r["role"],
            "officialTitle": r["official_title"] or "",
        }
        if include_contacts:
            item["title"] = r["title"] or ""
            item["profession"] = r["profession"] or ""
            item["employmentStatus"] = r["employment_status"] or "unknown"
            item["officialTitle"] = r["official_title"] or ""
            item["email"] = r["email"] or ""
            item["phone"] = r["phone"] or ""
            item["notes"] = r["notes"] or ""
            item["status"] = r["status"] or "active"
            item["hasPhone"] = bool(r["phone"])
            item["hasEmail"] = bool(r["email"])
        out.append(item)
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

    return {
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
            remarks = ?
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


def _grievance_public(row: sqlite3.Row | dict, *, include_contacts: bool = False) -> dict:
    if hasattr(row, "keys"):
        data = {k: row[k] for k in row.keys()}
    else:
        data = dict(row)
    item = {
        "id": data.get("id"),
        "houseId": data.get("house_id") or data.get("houseId"),
        "category": data.get("category") or "other",
        "categoryLabel": GRIEVANCE_CATEGORIES.get(data.get("category") or "other", "Other"),
        "subject": data.get("subject") or "",
        "body": data.get("body") or "",
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
    }
    if include_contacts:
        item["phone"] = data.get("phone") or ""
        item["email"] = data.get("email") or ""
    return item


def _list_grievance_messages(conn: sqlite3.Connection, grievance_id: str) -> list[dict]:
    rows = conn.execute(
        """
        SELECT * FROM grievance_messages
        WHERE grievance_id = ?
        ORDER BY created_at ASC, rowid ASC
        """,
        (grievance_id,),
    ).fetchall()
    return [
        {
            "id": r["id"],
            "grievanceId": r["grievance_id"],
            "authorHouseId": r["author_house_id"] or "",
            "authorName": r["author_name"] or "",
            "authorRole": r["author_role"] or "resident",
            "body": r["body"] or "",
            "createdAt": r["created_at"],
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
    item = _grievance_public(joined, include_contacts=include_contacts)
    item["messages"] = _list_grievance_messages(conn, grievance_id)
    return item


def create_grievance(conn: sqlite3.Connection, house_id: str, payload: dict) -> dict:
    ensure_grievances_table(conn)
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
          id, house_id, category, subject, body, status, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, 'open', ?, ?)
        """,
        (gid, resident["house_id"], category, subject, body, now, now),
    )
    conn.execute(
        """
        INSERT INTO grievance_messages(
          id, grievance_id, author_house_id, author_name, author_role, body, created_at
        ) VALUES (?, ?, ?, ?, 'resident', ?, ?)
        """,
        (mid, gid, resident["house_id"], resident.get("name") or resident["house_id"], body, now),
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
    items = []
    for r in rows:
        item = _grievance_public(r, include_contacts=include_contacts)
        item["messages"] = _list_grievance_messages(conn, r["id"])
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

    is_ec = (actor.get("role") == "admin") or bool(actor.get("superAdmin"))
    author_role = "ec" if is_ec else "resident"
    author_house = actor.get("houseId") or actor.get("house_id") or ""
    author_name = actor.get("name") or actor.get("officialTitle") or ("EC" if is_ec else author_house)
    now = utc_now()
    mid = f"gm_{secrets.token_hex(6)}"
    conn.execute(
        """
        INSERT INTO grievance_messages(
          id, grievance_id, author_house_id, author_name, author_role, body, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (mid, gid, author_house, author_name, author_role, body, now),
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
            {"body": response, "status": status or None},
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


def list_notices(conn: sqlite3.Connection, *, include_drafts: bool = False) -> list[dict]:
    ensure_notice_pin_order(conn)
    order_sql = "ORDER BY pinned DESC, pin_order ASC, published_at DESC"
    if include_drafts:
        rows = conn.execute(f"SELECT * FROM notices {order_sql}").fetchall()
    else:
        rows = conn.execute(
            f"SELECT * FROM notices WHERE status = 'published' {order_sql}"
        ).fetchall()
    return [_notice_public(r) for r in rows]


def _notice_public(r: sqlite3.Row | dict) -> dict:
    if hasattr(r, "keys"):
        data = {k: r[k] for k in r.keys()}
    else:
        data = dict(r)
    return {
        "id": data.get("id"),
        "title": data.get("title") or "",
        "body": data.get("body") or "",
        "category": data.get("category") or "general",
        "pinned": bool(data.get("pinned")),
        "pinOrder": int(data.get("pin_order") or data.get("pinOrder") or 0),
        "publishedAt": data.get("published_at") or data.get("publishedAt"),
        "publishedBy": data.get("published_by") or data.get("publishedBy"),
        "status": data.get("status") or "published",
    }


def get_notice(conn: sqlite3.Connection, notice_id: str) -> dict | None:
    ensure_notice_pin_order(conn)
    row = conn.execute("SELECT * FROM notices WHERE id = ?", (notice_id,)).fetchone()
    return _notice_public(row) if row else None


def _next_pin_order(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT COALESCE(MAX(pin_order), -1) FROM notices WHERE pinned = 1"
    ).fetchone()
    return int(row[0] if row else -1) + 1


def _reindex_pinned(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        "SELECT id FROM notices WHERE pinned = 1 ORDER BY pin_order ASC, published_at DESC, id ASC"
    ).fetchall()
    for idx, row in enumerate(rows):
        conn.execute("UPDATE notices SET pin_order = ? WHERE id = ?", (idx, row["id"]))


def move_pinned_notice(conn: sqlite3.Connection, notice_id: str, direction: str) -> dict:
    """Swap a pinned notice with its neighbor (up = toward top of board)."""
    ensure_notice_pin_order(conn)
    nid = (notice_id or "").strip()
    direction = (direction or "").strip().lower()
    if direction not in {"up", "down"}:
        raise ValueError("move must be 'up' or 'down'")
    row = conn.execute("SELECT * FROM notices WHERE id = ?", (nid,)).fetchone()
    if not row:
        raise ValueError("Notice not found")
    if not int(row["pinned"] or 0):
        raise ValueError("Only pinned notices can be reordered")

    pinned = conn.execute(
        "SELECT id FROM notices WHERE pinned = 1 ORDER BY pin_order ASC, published_at DESC, id ASC"
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
    for order, item_id in enumerate(ids):
        conn.execute("UPDATE notices SET pin_order = ? WHERE id = ?", (order, item_id))
    conn.commit()
    return get_notice(conn, nid) or {"id": nid}


def upsert_notice(conn: sqlite3.Connection, payload: dict, publisher: str | None) -> dict:
    ensure_notice_pin_order(conn)
    notice_id = (payload.get("id") or f"n_{secrets.token_hex(6)}").strip()
    existing = conn.execute("SELECT * FROM notices WHERE id = ?", (notice_id,)).fetchone()
    title = (payload.get("title") or (existing["title"] if existing else "") or "").strip()
    body = (payload.get("body") or (existing["body"] if existing else "") or "").strip()
    if len(title) < 3 or len(body) < 3:
        raise ValueError("title and body required")

    was_pinned = bool(existing and int(existing["pinned"] or 0))
    if "pinned" in payload:
        pinned = 1 if payload.get("pinned") else 0
    elif existing:
        pinned = int(existing["pinned"] or 0)
    else:
        pinned = 0

    if pinned:
        if "pinOrder" in payload or "pin_order" in payload:
            pin_order = int(payload.get("pinOrder", payload.get("pin_order")) or 0)
        elif was_pinned and existing is not None:
            pin_order = int(existing["pin_order"] or 0)
        else:
            pin_order = _next_pin_order(conn)
    else:
        pin_order = 0

    category = (payload.get("category") or (existing["category"] if existing else None) or "general").strip()[:40]
    status = (payload.get("status") or (existing["status"] if existing else None) or "published").strip()
    if status not in {"draft", "published", "archived"}:
        raise ValueError("Invalid notice status")

    published_at = payload.get("publishedAt") or (existing["published_at"] if existing else None) or utc_now()
    published_by = publisher or (existing["published_by"] if existing else None)

    conn.execute(
        """
        INSERT INTO notices(id, title, body, category, pinned, pin_order, published_at, published_by, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
          title=excluded.title,
          body=excluded.body,
          category=excluded.category,
          pinned=excluded.pinned,
          pin_order=excluded.pin_order,
          published_at=excluded.published_at,
          published_by=excluded.published_by,
          status=excluded.status
        """,
        (notice_id, title, body, category, pinned, pin_order, published_at, published_by, status),
    )
    if was_pinned and not pinned:
        _reindex_pinned(conn)
    conn.commit()
    return get_notice(conn, notice_id) or {"id": notice_id}


def delete_notice(conn: sqlite3.Connection, notice_id: str) -> None:
    ensure_notice_pin_order(conn)
    nid = (notice_id or "").strip()
    if not nid:
        raise ValueError("notice id required")
    row = conn.execute("SELECT pinned FROM notices WHERE id = ?", (nid,)).fetchone()
    cur = conn.execute("DELETE FROM notices WHERE id = ?", (nid,))
    if cur.rowcount < 1:
        conn.commit()
        raise ValueError("Notice not found")
    if row and int(row["pinned"] or 0):
        _reindex_pinned(conn)
    conn.commit()


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

    role = resident.get("role")
    if "role" in payload and payload.get("role") in {"admin", "resident"}:
        new_role = payload["role"]
        if new_role != role:
            if not actor_is_super:
                raise ValueError("Only super admin can assign or remove EC admin role")
            role = new_role
            if role == "resident":
                # Leaving EC: keep official_title for history unless cleared explicitly
                pass

    notes = resident.get("notes")
    if as_admin and "notes" in payload:
        notes = str(payload.get("notes") or "").strip()[:500] or None

    status = resident.get("status") or "active"
    if "status" in payload and payload.get("status") in {"active", "inactive"}:
        new_status = payload["status"]
        if new_status != status:
            # Suspend / reinstate EC admins is super-admin only
            if (resident.get("role") == "admin" or role == "admin") and not actor_is_super:
                raise ValueError("Only super admin can suspend or reinstate EC admins")
            if not as_admin and not actor_is_super:
                raise ValueError("Admin access required to change status")
            status = new_status

    if role != "admin":
        # Official title is EC-facing; optional clear when demoted unless payload keeps it
        if "officialTitle" not in payload and "official_title" not in payload and role == "resident":
            pass

    conn.execute(
        """
        UPDATE residents SET
          email=?, phone=?, name=?, title=?, profession=?, employment_status=?,
          official_title=?, role=?, notes=?, status=?, updated_at=?
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
            role,
            notes,
            status,
            utc_now(),
            resident["house_id"],
        ),
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
        "official_title": official_title, "role": role, "notes": notes, "status": status,
    }}
    return public_resident(refreshed)


def create_session_for_resident(conn: sqlite3.Connection, resident: dict) -> dict:
    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    expires_at = (now + timedelta(seconds=SESSION_TTL_SECONDS)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    conn.execute(
        "INSERT INTO sessions(token, house_id, role, created_at, expires_at) VALUES (?, ?, ?, ?, ?)",
        (token, resident["house_id"], resident["role"], utc_now(), expires_at),
    )
    conn.commit()
    return {
        "token": token,
        "expiresAt": expires_at,
        "resident": public_resident(resident),
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
