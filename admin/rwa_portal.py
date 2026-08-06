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
    ensure_access_events_table,
    ensure_info_documents_table,
    ensure_colony_works_table,
    migrate_roman_plot_ids,
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
        ensure_notice_shares_table(conn)
        ensure_access_events_table(conn)
        ensure_grievances_table(conn)
        ensure_info_documents_table(conn)
        ensure_colony_works_table(conn)
        migrate_roman_plot_ids(conn)
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
    path = info_doc_dir(site_root, doc_id) / name
    return path if path.is_file() else None


def _info_category(raw: str | None) -> str:
    key = (raw or "general").strip().lower()
    allowed = {c[0] for c in INFO_DOC_CATEGORIES}
    return key if key in allowed else "general"


def _info_audience(raw: str | None) -> str:
    key = (raw or "all").strip().lower()
    return key if key in {"all", "ec"} else "all"


def _info_public(r: sqlite3.Row | dict) -> dict:
    if hasattr(r, "keys"):
        data = {k: r[k] for k in r.keys()}
    else:
        data = dict(r)
    cat = data.get("category") or "general"
    label = next((lbl for cid, lbl in INFO_DOC_CATEGORIES if cid == cat), cat)
    audience = _info_audience(data.get("audience"))
    return {
        "id": data.get("id"),
        "title": data.get("title") or "",
        "summary": data.get("summary") or "",
        "category": cat,
        "categoryLabel": label,
        "docType": data.get("doc_type") or "file",
        "filename": data.get("filename"),
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
        "hasFile": bool(data.get("filename")),
    }


def list_info_documents(
    conn: sqlite3.Connection,
    *,
    status: str | None = "published",
    category: str | None = None,
    as_admin: bool = False,
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
    return [_info_public(r) for r in rows]


def get_info_document(
    conn: sqlite3.Connection,
    doc_id: str,
    *,
    as_admin: bool = False,
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
    return _info_public(row)


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
        for old in dest_dir.iterdir():
            if old.is_file():
                try:
                    old.unlink()
                except OSError:
                    pass
        (dest_dir / filename).write_bytes(data)
    elif file_storage is not None and getattr(file_storage, "filename", None):
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
        for old in dest_dir.iterdir():
            if old.is_file():
                try:
                    old.unlink()
                except OSError:
                    pass
        (dest_dir / filename).write_bytes(data)
    elif not existing:
        if doc_type == "html":
            raise ValueError("HTML content required")
        raise ValueError("Upload a document file, or create HTML content")

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
          size_bytes, status, audience, published_at, published_by, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
          updated_at=excluded.updated_at
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
        ),
    )
    conn.commit()
    return get_info_document(conn, doc_id, as_admin=True) or {"id": doc_id}


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
    return {
        "id": notice_id,
        "title": data.get("title") or "",
        "body": data.get("body") or "",
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
    }

def get_notice(
    conn: sqlite3.Connection,
    notice_id: str,
    *,
    viewer: dict | None = None,
) -> dict | None:
    ensure_notice_pin_order(conn)
    ensure_notice_shares_table(conn)
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
        (notice_id, title, body or "", category, pinned, pin_order, published_at, published_by, status),
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
