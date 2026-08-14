"""Parking passes — member, tenant, visitor, and gate ad-hoc (selfie) passes."""

from __future__ import annotations

import calendar
import base64
import html
import os
import pathlib
import re
import secrets
import smtplib
import sqlite3
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from io import BytesIO
from typing import Any
from zoneinfo import ZoneInfo

from init_rwa_db import SUPERADMIN_HOUSE_ID, ADHOC_GATE_HOUSE_ID, ensure_parking_passes_table, utc_now
import rwa_attest
import rwa_entitlements
import rwa_household

IST = ZoneInfo("Asia/Kolkata")

ALLOWED_HOURS = (4, 8, 12, 24)
DEFAULT_HOURS = 24
ALLOWED_MONTHS = (1, 3, 6, 12)
DEFAULT_MONTHS = 6
ALLOWED_ADHOC_HOURS = (1, 2, 3, 4, 5, 6, 7, 8, 9)
DEFAULT_ADHOC_HOURS = 4
ADHOC_HOUSE_ID = ADHOC_GATE_HOUSE_ID
ADHOC_CATEGORIES = {
    "hawker": "Hawker",
    "scrap": "Scrap collector",
    "labour": "Labourer",
    "delivery": "Delivery",
    "other": "Other",
}
ADHOC_PHOTO_MAX = 6_000_000
ADHOC_PHOTO_SIZE = 480
VEHICLE_TYPES = ("car", "suv", "van", "bike", "scooter", "other", "foot")
VEHICLE_LABELS = {
    "car": "Car",
    "suv": "SUV",
    "van": "Van",
    "bike": "Motorcycle",
    "scooter": "Scooter",
    "other": "Other",
    "foot": "On foot",
}
STATUS_LABELS = {
    "active": "Active",
    "expired": "Expired",
    "pending_renewal": "Awaiting EC",
    "revoked": "Revoked",
}
META_DEFAULT_HOURS = "parking_default_hours"
PERMANENT_EXPIRES = "9999-12-31T00:00:00Z"
KIND_MEMBER = "member"
KIND_VISITOR = "visitor"
KIND_TENANT = "tenant"
KIND_ADHOC = "adhoc"
KIND_LABELS = {
    KIND_MEMBER: "Member",
    KIND_VISITOR: "Visitor",
    KIND_TENANT: "Tenant",
    KIND_ADHOC: "Ad-hoc",
}


def parse_utc(value: str | None) -> datetime | None:
    raw = (value or "").strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_ist(value: str | None) -> str:
    dt = parse_utc(value)
    if not dt:
        return ""
    return dt.astimezone(IST).strftime("%d %b %Y, %I:%M %p IST")


def public_origin(site_root: pathlib.Path | None = None) -> str:
    return (
        os.environ.get("VEERCANVAS_PUBLIC_ORIGIN")
        or os.environ.get("RWA_PUBLIC_ORIGIN")
        or "https://housingcolonysanyard.in"
    ).rstrip("/")


def normalize_plate(raw: str | None) -> tuple[str, str]:
    display = re.sub(r"\s+", " ", (raw or "").strip().upper())
    key = re.sub(r"[^A-Z0-9]", "", display)
    if len(key) < 4:
        raise ValueError("Enter a valid vehicle number (at least 4 characters)")
    if len(key) > 14:
        raise ValueError("Vehicle number is too long")
    return key, display or key


def normalize_colour(raw: str | None) -> str:
    return re.sub(r"\s+", " ", (raw or "").strip())[:40]


def normalize_visitor(raw: str | None) -> str:
    return re.sub(r"\s+", " ", (raw or "").strip())[:80]


def normalize_vehicle_type(raw: str | None) -> str:
    key = (raw or "car").strip().lower()
    return key if key in VEHICLE_TYPES else "car"


def normalize_kind(raw: str | None) -> str:
    key = (raw or KIND_VISITOR).strip().lower()
    if key in ("member", "resident", "permanent", "own"):
        return KIND_MEMBER
    if key in ("tenant", "tenants", "renter", "lessee"):
        return KIND_TENANT
    if key in ("adhoc", "ad-hoc", "gate", "hawker", "labour", "labor"):
        return KIND_ADHOC
    return KIND_VISITOR


def normalize_adhoc_category(raw: str | None) -> str:
    key = (raw or "other").strip().lower()
    return key if key in ADHOC_CATEGORIES else "other"


def _adhoc_hours_from_payload(payload: dict | None) -> int:
    raw = (payload or {}).get("hours") or (payload or {}).get("leaseHours") or DEFAULT_ADHOC_HOURS
    try:
        n = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("Choose a duration between 1 and 9 hours") from exc
    if n not in ALLOWED_ADHOC_HOURS:
        raise ValueError("Ad-hoc pass duration must be between 1 and 9 hours")
    return n


def _meta_int(conn: sqlite3.Connection, key: str, default: int) -> int:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    if not row:
        return default
    try:
        n = int(str(row["value"] if isinstance(row, sqlite3.Row) else row[0]).strip())
    except (TypeError, ValueError):
        return default
    return n


def default_hours(conn: sqlite3.Connection) -> int:
    n = _meta_int(conn, META_DEFAULT_HOURS, DEFAULT_HOURS)
    return n if n in ALLOWED_HOURS else DEFAULT_HOURS


def set_default_hours(conn: sqlite3.Connection, hours: int, *, actor: dict) -> int:
    n = int(hours)
    if n not in ALLOWED_HOURS:
        raise ValueError("Lease duration must be 4, 8, 12, or 24 hours")
    conn.execute(
        "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
        (META_DEFAULT_HOURS, str(n)),
    )
    conn.commit()
    return n


def settings(conn: sqlite3.Connection) -> dict[str, Any]:
    ensure_parking_passes_table(conn)
    hours = default_hours(conn)
    return {
        "defaultHours": hours,
        "allowedHours": list(ALLOWED_HOURS),
        "defaultMonths": DEFAULT_MONTHS,
        "allowedMonths": list(ALLOWED_MONTHS),
        "adhocHours": list(ALLOWED_ADHOC_HOURS),
        "defaultAdhocHours": DEFAULT_ADHOC_HOURS,
        "adhocCategories": [{"id": k, "label": v} for k, v in ADHOC_CATEGORIES.items()],
        "gatePassUrl": gate_pass_public_url(),
        "vehicleTypes": [{"id": k, "label": VEHICLE_LABELS[k]} for k in VEHICLE_TYPES if k != "foot"],
        "walletEnabled": _wallet_configured(),
        "googleWalletEnabled": _google_wallet_configured(),
    }


def _wallet_configured() -> bool:
    try:
        import rwa_wallet
        return rwa_wallet.is_configured()
    except ImportError:
        return False


def _google_wallet_configured() -> bool:
    try:
        import rwa_wallet
        return rwa_wallet.is_google_configured()
    except ImportError:
        return False


def gate_pass_public_url(site_root: pathlib.Path | None = None) -> str:
    return f"{public_origin(site_root).rstrip('/')}/gate-pass.html#needs"


def gate_qr_png(site_root: pathlib.Path | None = None) -> bytes:
    return rwa_attest.qr_png_bytes(gate_pass_public_url(site_root), box_size=12, border=2) or b""


def adhoc_photo_dir(site_root: pathlib.Path) -> pathlib.Path:
    path = pathlib.Path(site_root) / "data" / "parking-adhoc"
    path.mkdir(parents=True, exist_ok=True)
    return path


def adhoc_photo_path(site_root: pathlib.Path, filename: str | None) -> pathlib.Path | None:
    if not filename:
        return None
    name = pathlib.Path(str(filename)).name
    if name != str(filename) or ".." in name or "/" in name or "\\" in name:
        return None
    if not re.fullmatch(r"adhoc_[A-Za-z0-9_-]+\.webp", name):
        return None
    path = adhoc_photo_dir(site_root) / name
    return path if path.is_file() else None


def _optimize_adhoc_photo(raw: bytes) -> bytes:
    try:
        from PIL import Image
    except ImportError as exc:  # pragma: no cover
        raise ValueError("Image processing unavailable on server") from exc
    try:
        img = Image.open(BytesIO(raw))
        img.load()
    except Exception as exc:
        raise ValueError("Could not read the selfie. Retake and try again.") from exc
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGBA") if "A" in img.getbands() else img.convert("RGB")
    w, h = img.size
    if w <= 0 or h <= 0:
        raise ValueError("Invalid selfie")
    side = min(w, h)
    left = (w - side) // 2
    top = (h - side) // 2
    img = img.crop((left, top, left + side, top + side))
    resample = Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS
    if side != ADHOC_PHOTO_SIZE:
        img = img.resize((ADHOC_PHOTO_SIZE, ADHOC_PHOTO_SIZE), resample)
    if img.mode == "RGBA":
        background = Image.new("RGB", img.size, (246, 241, 230))
        background.paste(img, mask=img.split()[-1])
        img = background
    else:
        img = img.convert("RGB")
    out = BytesIO()
    img.save(out, format="WEBP", quality=72, method=6)
    data = out.getvalue()
    if not data:
        raise ValueError("Could not save selfie")
    return data


def save_adhoc_photo(site_root: pathlib.Path, pass_id: str, raw: bytes) -> str:
    if not raw:
        raise ValueError("Selfie is required")
    if len(raw) > ADHOC_PHOTO_MAX:
        raise ValueError("Selfie is too large. Retake at a lower quality.")
    optimized = _optimize_adhoc_photo(raw)
    filename = f"adhoc_{pass_id.replace('pp_', '')}.webp"
    path = adhoc_photo_dir(site_root) / filename
    path.write_bytes(optimized)
    return filename


def _new_id() -> str:
    return "pp_" + secrets.token_hex(8)


def _new_code(conn: sqlite3.Connection, kind: str = KIND_VISITOR) -> str:
    prefix = {
        KIND_MEMBER: "MP-",
        KIND_TENANT: "TP-",
        KIND_ADHOC: "AP-",
    }.get(kind, "VP-")
    for _ in range(12):
        code = prefix + secrets.token_hex(3).upper()
        exists = conn.execute(
            "SELECT 1 FROM parking_passes WHERE public_code = ?",
            (code,),
        ).fetchone()
        if not exists:
            return code
    return prefix + secrets.token_hex(5).upper()


def expire_due_passes(conn: sqlite3.Connection) -> int:
    ensure_parking_passes_table(conn)
    now = utc_now()
    cur = conn.execute(
        """
        UPDATE parking_passes
        SET status = 'expired', updated_at = ?
        WHERE status = 'active'
          AND COALESCE(kind, 'visitor') != 'member'
          AND expires_at <= ?
          AND expires_at < '9000-01-01'
        """,
        (now, now),
    )
    if cur.rowcount:
        conn.commit()
    return int(cur.rowcount or 0)


def _add_event(
    conn: sqlite3.Connection,
    *,
    pass_id: str,
    action: str,
    actor: dict | None,
    note: str = "",
) -> None:
    conn.execute(
        """
        INSERT INTO parking_pass_events(
          id, pass_id, action, actor_house_id, actor_member_id, actor_name, note, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "pe_" + secrets.token_hex(8),
            pass_id,
            action,
            (actor or {}).get("houseId") or (actor or {}).get("house_id") or "",
            (actor or {}).get("memberId") or "",
            (actor or {}).get("name") or "",
            (note or "")[:400],
            utc_now(),
        ),
    )


def _row_pass(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if not row:
        return None
    data = dict(row)
    status = data.get("status") or "expired"
    kind = (data.get("kind") or KIND_VISITOR).strip().lower()
    if kind not in (KIND_MEMBER, KIND_VISITOR, KIND_TENANT, KIND_ADHOC):
        kind = KIND_VISITOR
    permanent = kind == KIND_MEMBER
    tenant = kind == KIND_TENANT
    adhoc = kind == KIND_ADHOC
    expires_at = data.get("expires_at") or ""
    lease_months = int(data.get("lease_months") or 0)
    category = ""
    category_label = ""
    if adhoc:
        category = normalize_adhoc_category(data.get("tenant_note") or data.get("vehicle_type"))
        # Prefer note field for category id; fall back
        note_cat = (data.get("tenant_note") or "").strip().lower()
        if note_cat in ADHOC_CATEGORIES:
            category = note_cat
        category_label = ADHOC_CATEGORIES.get(category, "Ad-hoc")
        status_label = f"{int(data.get('lease_hours') or DEFAULT_ADHOC_HOURS)}h ad-hoc" if status == "active" else STATUS_LABELS.get(status, status.replace("_", " ").title())
    elif permanent:
        status_label = "Permanent" if status == "active" else STATUS_LABELS.get(status, status.replace("_", " ").title())
    elif tenant and status == "active":
        status_label = f"{lease_months or DEFAULT_MONTHS} mo lease"
    else:
        status_label = STATUS_LABELS.get(status, status.replace("_", " ").title())
    photo_filename = data.get("photo_filename") or ""
    item = {
        "id": data.get("id"),
        "code": data.get("public_code") or "",
        "kind": kind,
        "kindLabel": KIND_LABELS.get(kind, "Visitor"),
        "permanent": permanent,
        "houseId": data.get("house_id") or "",
        "plotNo": "GATE" if adhoc else (data.get("plot_no") or data.get("house_id") or ""),
        "memberId": data.get("member_id") or "",
        "memberName": data.get("member_name") or "",
        "plate": data.get("plate") or "",
        "plateDisplay": data.get("plate_display") or data.get("plate") or "",
        "colour": data.get("colour") or "",
        "vehicleType": data.get("vehicle_type") or "car",
        "vehicleTypeLabel": VEHICLE_LABELS.get(data.get("vehicle_type") or "car", "Car"),
        "visitorName": data.get("visitor_name") or "",
        "tenantId": data.get("tenant_id") or "",
        "tenantName": (data.get("visitor_name") or "") if tenant else "",
        "tenantPhone": data.get("tenant_phone") or "",
        "tenantEmail": data.get("tenant_email") or "",
        "tenantNote": data.get("tenant_note") or "",
        "adhocCategory": category if adhoc else "",
        "adhocCategoryLabel": category_label if adhoc else "",
        "leaseHours": 0 if permanent or tenant else int(data.get("lease_hours") or (DEFAULT_ADHOC_HOURS if adhoc else DEFAULT_HOURS)),
        "leaseMonths": lease_months if tenant else 0,
        "photoFilename": photo_filename,
        "hasPhoto": bool(photo_filename),
        "photoUrl": f"/api/rwa/parking/passes/{data.get('id')}/photo" if photo_filename else "",
        "status": status,
        "statusLabel": status_label,
        "issuedAt": data.get("issued_at") or "",
        "issuedAtLabel": format_ist(data.get("issued_at")),
        "expiresAt": "" if permanent else expires_at,
        "expiresAtLabel": "Permanent" if permanent else format_ist(expires_at),
        "renewCount": int(data.get("renew_count") or 0),
        "lastRenewedAt": data.get("last_renewed_at") or "",
        "pendingRenewHours": int(data.get("pending_renew_hours") or 0),
        "pendingRenewAt": data.get("pending_renew_at") or "",
        "approvedByName": data.get("approved_by_name") or "",
        "revokedReason": data.get("revoked_reason") or "",
        "emailSent": bool(int(data.get("email_sent") or 0)),
        "createdAt": data.get("created_at") or "",
        "updatedAt": data.get("updated_at") or "",
        "canRenew": (not permanent) and (not adhoc) and status == "expired",
        "needsEcApproval": (not permanent) and (not adhoc) and status == "expired" and int(data.get("renew_count") or 0) >= 1,
        "canRemove": permanent and status == "active",
        "verifyUrl": "",
    }
    item.update(_wallet_public_fields(item))
    return item


def _wallet_public_fields(item: dict[str, Any]) -> dict[str, Any]:
    try:
        import rwa_wallet
    except ImportError:
        return {"walletEnabled": False, "walletUrl": "", "googleWalletEnabled": False, "googleWalletUrl": ""}
    return rwa_wallet.public_fields(item)


def can_download_wallet(
    item: dict[str, Any] | None,
    actor: dict | None,
    *,
    code: str = "",
    can_manage: bool = False,
    can_general: bool = False,
) -> bool:
    """Owner plot, pass staff, or possession of the public pass code."""
    if not item:
        return False
    if str(item.get("status") or "") not in ("active", "pending_renewal"):
        return False
    pub = str(item.get("code") or "").strip().upper()
    offered = (code or "").strip().upper()
    if pub and offered and pub == offered:
        return True
    if can_manage or can_general:
        return True
    actor_house = str((actor or {}).get("houseId") or (actor or {}).get("house_id") or "").strip()
    pass_house = str(item.get("houseId") or item.get("house_id") or "").strip()
    return bool(actor_house and pass_house and actor_house == pass_house)


def _attach_qr(item: dict[str, Any], site_root: pathlib.Path | None) -> dict[str, Any]:
    origin = public_origin(site_root)
    code = item.get("code") or ""
    url = f"{origin}/#parking?pass={code}" if code else origin
    item["verifyUrl"] = url
    png = rwa_attest.qr_png_bytes(url, box_size=5, border=2)
    if png:
        item["qrDataUrl"] = "data:image/png;base64," + base64.b64encode(png).decode("ascii")
    else:
        item["qrDataUrl"] = ""
    return item


def get_pass(
    conn: sqlite3.Connection,
    pass_id: str,
    *,
    site_root: pathlib.Path | None = None,
    with_qr: bool = False,
) -> dict[str, Any] | None:
    ensure_parking_passes_table(conn)
    expire_due_passes(conn)
    row = conn.execute(
        """
        SELECT p.*, r.plot_no
        FROM parking_passes p
        LEFT JOIN residents r ON r.house_id = p.house_id
        WHERE p.id = ? OR p.public_code = ?
        """,
        ((pass_id or "").strip(), (pass_id or "").strip()),
    ).fetchone()
    item = _row_pass(row)
    if item and with_qr:
        _attach_qr(item, site_root)
    return item


def list_passes(
    conn: sqlite3.Connection,
    *,
    house_id: str,
    site_root: pathlib.Path | None = None,
    limit: int = 40,
) -> list[dict[str, Any]]:
    ensure_parking_passes_table(conn)
    expire_due_passes(conn)
    hid = (house_id or "").strip()
    if not hid:
        return []
    lim = max(1, min(int(limit or 40), 100))
    rows = conn.execute(
        """
        SELECT p.*, r.plot_no
        FROM parking_passes p
        LEFT JOIN residents r ON r.house_id = p.house_id
        WHERE p.house_id = ?
        ORDER BY
          CASE
            WHEN COALESCE(p.kind, 'visitor') = 'member' AND p.status = 'active' THEN 0
            WHEN COALESCE(p.kind, 'visitor') = 'tenant' AND p.status = 'active' THEN 1
            WHEN p.status = 'active' THEN 2
            WHEN p.status = 'pending_renewal' THEN 3
            ELSE 4
          END,
          p.created_at DESC
        LIMIT ?
        """,
        (hid, lim),
    ).fetchall()
    out = []
    for row in rows:
        item = _row_pass(row)
        if item:
            _attach_qr(item, site_root)
            out.append(item)
    return out


def list_passes_for_report(
    conn: sqlite3.Connection,
    *,
    kinds: list[str] | None = None,
    status: str | None = None,
    house_ids: list[str] | None = None,
    exclude_foot: bool = False,
    limit: int = 3000,
) -> list[dict[str, Any]]:
    """Colony-wide pass rows for EC reports (no QR blobs)."""
    ensure_parking_passes_table(conn)
    expire_due_passes(conn)
    lim = max(1, min(int(limit or 3000), 5000))
    clauses: list[str] = []
    args: list[Any] = []
    if kinds:
        mapped: list[str] = []
        for raw in kinds:
            key = str(raw or "").strip().lower()
            if key in (KIND_MEMBER, KIND_VISITOR, KIND_TENANT, KIND_ADHOC):
                mapped.append(key)
            elif key in ("ad-hoc", "gate"):
                mapped.append(KIND_ADHOC)
        if mapped:
            clauses.append(f"COALESCE(p.kind, 'visitor') IN ({','.join('?' for _ in mapped)})")
            args.extend(mapped)
    st = (status or "all").strip().lower()
    if st and st != "all":
        clauses.append("p.status = ?")
        args.append(st)
    ids = [str(h).strip() for h in (house_ids or []) if str(h).strip()]
    if ids:
        clauses.append(f"p.house_id IN ({','.join('?' for _ in ids)})")
        args.extend(ids)
    if exclude_foot:
        clauses.append("COALESCE(p.vehicle_type, '') != 'foot'")
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    rows = conn.execute(
        f"""
        SELECT p.*,
               CASE WHEN p.house_id = ? THEN 'GATE' ELSE COALESCE(r.plot_no, p.house_id) END AS plot_no
        FROM parking_passes p
        LEFT JOIN residents r ON r.house_id = p.house_id
        {where}
        ORDER BY p.created_at DESC
        LIMIT ?
        """,
        (ADHOC_HOUSE_ID, *args, lim),
    ).fetchall()
    out = []
    for row in rows:
        item = _row_pass(row)
        if item:
            item.pop("qrDataUrl", None)
            item.pop("photoDataUrl", None)
            out.append(item)
    return out


def list_pending_renewals(
    conn: sqlite3.Connection,
    *,
    site_root: pathlib.Path | None = None,
    limit: int = 80,
) -> list[dict[str, Any]]:
    ensure_parking_passes_table(conn)
    expire_due_passes(conn)
    lim = max(1, min(int(limit or 80), 200))
    rows = conn.execute(
        """
        SELECT p.*, r.plot_no
        FROM parking_passes p
        LEFT JOIN residents r ON r.house_id = p.house_id
        WHERE p.status = 'pending_renewal'
        ORDER BY p.pending_renew_at ASC
        LIMIT ?
        """,
        (lim,),
    ).fetchall()
    out = []
    for row in rows:
        item = _row_pass(row)
        if item:
            _attach_qr(item, site_root)
            out.append(item)
    return out


def lookup_pass(
    conn: sqlite3.Connection,
    query: str,
    *,
    site_root: pathlib.Path | None = None,
) -> dict[str, Any] | None:
    ensure_parking_passes_table(conn)
    expire_due_passes(conn)
    raw = (query or "").strip()
    if not raw:
        raise ValueError("Enter a vehicle number or pass code")
    code = raw.upper()
    if (
        code.startswith("VP-")
        or code.startswith("MP-")
        or code.startswith("TP-")
        or code.startswith("AP-")
        or code.startswith("PP_")
    ):
        item = get_pass(conn, code, site_root=site_root, with_qr=True)
        if item:
            return item
    try:
        plate, _display = normalize_plate(raw)
    except ValueError:
        plate = re.sub(r"[^A-Z0-9]", "", raw.upper())
    if not plate:
        return None
    row = conn.execute(
        """
        SELECT p.*, r.plot_no
        FROM parking_passes p
        LEFT JOIN residents r ON r.house_id = p.house_id
        WHERE p.plate = ?
        ORDER BY
          CASE p.status
            WHEN 'active' THEN 0
            WHEN 'pending_renewal' THEN 1
            WHEN 'expired' THEN 2
            ELSE 3
          END,
          p.created_at DESC
        LIMIT 1
        """,
        (plate,),
    ).fetchone()
    item = _row_pass(row)
    if item:
        _attach_qr(item, site_root)
    return item


def general_lookup_view(item: dict[str, Any] | None) -> dict[str, Any] | None:
    """Type, validity, and code — for other plots when the actor has Pass · general."""
    if not item:
        return None
    status = (item.get("status") or "expired").strip().lower()
    valid = status in ("active", "pending_renewal")
    if valid:
        status_label = "Valid"
    elif status == "revoked":
        status_label = "Not valid (revoked)"
    elif status == "expired":
        status_label = "Not valid (expired)"
    else:
        status_label = "Not valid"
    return {
        "id": item.get("id") or "",
        "code": item.get("code") or item.get("id") or "",
        "kind": item.get("kind") or "",
        "kindLabel": item.get("kindLabel") or "Pass",
        "status": status,
        "statusLabel": status_label,
        "valid": valid,
        "expiresAtLabel": item.get("expiresAtLabel") or ("Permanent" if item.get("permanent") else ""),
        "detailLevel": "general",
    }


def manage_lookup_view(item: dict[str, Any] | None) -> dict[str, Any] | None:
    if not item:
        return None
    out = dict(item)
    out["detailLevel"] = "manage"
    status = (out.get("status") or "expired").strip().lower()
    out["valid"] = status in ("active", "pending_renewal")
    return out


def own_house_lookup_view(item: dict[str, Any] | None) -> dict[str, Any] | None:
    """Full vehicle details for a pass belonging to the viewer's own plot."""
    if not item:
        return None
    out = dict(item)
    out["detailLevel"] = "own"
    status = (out.get("status") or "expired").strip().lower()
    out["valid"] = status in ("active", "pending_renewal")
    return out


def lookup_view_for_actor(
    item: dict[str, Any] | None,
    actor: dict | None,
    *,
    can_manage: bool,
) -> dict[str, Any] | None:
    if not item:
        return None
    if can_manage:
        return manage_lookup_view(item)
    actor_house = str((actor or {}).get("houseId") or (actor or {}).get("house_id") or "").strip()
    pass_house = str(item.get("houseId") or item.get("house_id") or "").strip()
    if actor_house and pass_house and actor_house == pass_house:
        return own_house_lookup_view(item)
    return general_lookup_view(item)


def _active_for_plate(conn: sqlite3.Connection, plate: str) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT * FROM parking_passes
        WHERE plate = ? AND status IN ('active', 'pending_renewal')
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (plate,),
    ).fetchone()


def _latest_for_house_plate(
    conn: sqlite3.Connection, house_id: str, plate: str
) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT * FROM parking_passes
        WHERE house_id = ? AND plate = ?
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (house_id, plate),
    ).fetchone()


def actor_email(conn: sqlite3.Connection, actor: dict) -> str:
    mid = (actor.get("memberId") or "").strip()
    if mid:
        member = rwa_household.get_member(conn, mid)
        if member and str(member.get("email") or "").strip():
            return str(member.get("email") or "").strip().lower()
    return str(actor.get("email") or "").strip().lower()


def _actor_name(actor: dict) -> str:
    return (actor.get("name") or actor.get("houseId") or "Member").strip()


def _hours_from_payload(conn: sqlite3.Connection, payload: dict) -> int:
    raw = payload.get("hours") or payload.get("leaseHours") or payload.get("durationHours")
    if raw in (None, ""):
        return default_hours(conn)
    try:
        n = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("Choose a valid lease duration") from exc
    if n not in ALLOWED_HOURS:
        raise ValueError("Lease duration must be 4, 8, 12, or 24 hours")
    return n


def _months_from_payload(payload: dict, *, fallback: int = DEFAULT_MONTHS) -> int:
    raw = payload.get("months") or payload.get("leaseMonths") or payload.get("durationMonths")
    if raw in (None, ""):
        n = int(fallback or DEFAULT_MONTHS)
    else:
        try:
            n = int(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError("Choose a valid tenant lease (1, 3, 6, or 12 months)") from exc
    if n not in ALLOWED_MONTHS:
        raise ValueError("Tenant lease must be 1, 3, 6, or 12 months")
    return n


def _apply_window(hours: int) -> tuple[str, str]:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    end = now + timedelta(hours=int(hours))
    issued = now.isoformat().replace("+00:00", "Z")
    expires = end.isoformat().replace("+00:00", "Z")
    return issued, expires


def _apply_month_window(months: int) -> tuple[str, str]:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    month_index = now.month - 1 + int(months)
    year = now.year + month_index // 12
    month = month_index % 12 + 1
    day = min(now.day, calendar.monthrange(year, month)[1])
    end = now.replace(year=year, month=month, day=day)
    issued = now.isoformat().replace("+00:00", "Z")
    expires = end.isoformat().replace("+00:00", "Z")
    return issued, expires


def _tenant_fields(payload: dict) -> tuple[str, str, str, str]:
    name = normalize_visitor(
        payload.get("tenantName") or payload.get("visitorName") or payload.get("name")
    )
    if not name:
        raise ValueError("Tenant name is required")
    phone = rwa_household.normalize_phone(payload.get("tenantPhone") or payload.get("phone"))
    if not phone or len(re.sub(r"\D", "", phone)) < 10:
        raise ValueError("Tenant mobile number is required")
    email_raw = str(payload.get("tenantEmail") or payload.get("email") or "").strip().lower()
    email = ""
    if email_raw:
        email = rwa_household.validate_email(email_raw)
    note = re.sub(r"\s+", " ", str(payload.get("tenantNote") or payload.get("idNote") or "").strip())[:200]
    return name, phone, email, note


def _kind_of_row(row: sqlite3.Row | None) -> str:
    if not row:
        return KIND_VISITOR
    if "kind" in row.keys():
        return normalize_kind(row["kind"])
    return KIND_VISITOR


def issue_pass(
    conn: sqlite3.Connection,
    *,
    actor: dict,
    payload: dict,
    site_root: pathlib.Path,
) -> dict[str, Any]:
    ensure_parking_passes_table(conn)
    expire_due_passes(conn)
    if actor.get("viewOnly"):
        raise PermissionError("View-only access cannot request a parking pass")
    if actor.get("superAdmin"):
        raise PermissionError("Super admin cannot register a vehicle as a plot")
    house_id = (actor.get("houseId") or "").strip()
    if not house_id or house_id == SUPERADMIN_HOUSE_ID:
        raise ValueError("Sign in from your plot to request a pass")
    kind = normalize_kind(payload.get("kind") or payload.get("passKind"))
    if kind == KIND_ADHOC:
        raise ValueError("Ad-hoc gate passes are issued only at the main gate QR page")
    plate, plate_display = normalize_plate(payload.get("plate") or payload.get("vehicleNumber"))
    colour = normalize_colour(payload.get("colour") or payload.get("color"))
    vehicle_type = normalize_vehicle_type(payload.get("vehicleType") or payload.get("type"))
    visitor_name = normalize_visitor(
        payload.get("visitorName") or payload.get("visitor") or payload.get("driverName")
    )
    tenant_phone = ""
    tenant_email = ""
    tenant_note = ""
    tenant_id = ""
    lease_months = 0
    if kind == KIND_MEMBER and not visitor_name:
        visitor_name = _actor_name(actor)
    if kind == KIND_TENANT:
        import rwa_tenants

        tenant = rwa_tenants.get_tenant(conn, payload.get("tenantId") or payload.get("tenant_id") or "")
        if not tenant or tenant.get("houseId") != house_id:
            raise ValueError("Select a tenant already registered on this plot (Profile → Tenants).")
        if tenant.get("status") != "active":
            raise ValueError("That occupancy has ended. Register the current tenant first.")
        tenant_id = tenant["id"]
        visitor_name = tenant.get("name") or ""
        tenant_phone = tenant.get("phone") or ""
        tenant_email = tenant.get("email") or ""
        tenant_note = tenant.get("note") or ""

    existing = _active_for_plate(conn, plate)
    if existing:
        existing_kind = _kind_of_row(existing)
        label = KIND_LABELS.get(existing_kind, "visitor").lower()
        if existing["house_id"] == house_id:
            if existing_kind == KIND_MEMBER:
                raise ValueError("This vehicle is already registered for a permanent member pass.")
            raise ValueError(f"This vehicle already has an active or pending {label} pass. Renew it from Pass.")
        raise ValueError(f"This vehicle number already has an active {label} pass in the colony")

    if kind in (KIND_VISITOR, KIND_TENANT):
        latest = _latest_for_house_plate(conn, house_id, plate)
        latest_kind = _kind_of_row(latest)
        if latest and latest["status"] == "expired" and latest_kind == kind:
            extra = {"months": _months_from_payload(payload)} if kind == KIND_TENANT else {"hours": _hours_from_payload(conn, payload)}
            return renew_pass(
                conn,
                pass_id=latest["id"],
                actor=actor,
                payload=extra,
                site_root=site_root,
            )

    pid = _new_id()
    code = _new_code(conn, kind)
    now = utc_now()
    hours = 0
    if kind == KIND_MEMBER:
        issued_at = now
        expires_at = PERMANENT_EXPIRES
        note = "permanent member vehicle"
    elif kind == KIND_TENANT:
        lease_months = _months_from_payload(payload)
        issued_at, expires_at = _apply_month_window(lease_months)
        note = f"{lease_months} month tenant lease"
    else:
        hours = _hours_from_payload(conn, payload)
        issued_at, expires_at = _apply_window(hours)
        note = f"{hours}h visitor lease"
    conn.execute(
        """
        INSERT INTO parking_passes(
          id, public_code, house_id, member_id, member_name, kind, plate, plate_display,
          colour, vehicle_type, visitor_name, tenant_id, tenant_phone, tenant_email, tenant_note,
          lease_hours, lease_months, photo_filename, status, issued_at, expires_at,
          renew_count, last_renewed_at, pending_renew_hours, pending_renew_at,
          approved_by_house_id, approved_by_name, revoked_reason, email_sent,
          created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, 'active', ?, ?, 0, NULL, 0, NULL,
                  NULL, NULL, '', 0, ?, ?)
        """,
        (
            pid,
            code,
            house_id,
            actor.get("memberId") or "",
            _actor_name(actor),
            kind,
            plate,
            plate_display,
            colour,
            vehicle_type,
            visitor_name,
            tenant_id,
            tenant_phone,
            tenant_email,
            tenant_note,
            hours,
            lease_months,
            issued_at,
            expires_at,
            now,
            now,
        ),
    )
    _add_event(conn, pass_id=pid, action="issued", actor=actor, note=note)
    conn.commit()
    item = get_pass(conn, pid, site_root=site_root, with_qr=True)
    if not item:
        raise ValueError("Pass could not be loaded after issue")
    delivery = send_pass_email(conn, item, actor=actor, site_root=site_root, reason="issued")
    item["emailDelivery"] = delivery
    return item


def issue_adhoc_pass(
    conn: sqlite3.Connection,
    *,
    name: str,
    photo_bytes: bytes,
    hours: int | None = None,
    category: str | None = None,
    site_root: pathlib.Path,
) -> dict[str, Any]:
    """Public gate flow: selfie + name → short ad-hoc entry pass (1–9 hours)."""
    ensure_parking_passes_table(conn)
    expire_due_passes(conn)
    visitor_name = normalize_visitor(name)
    if len(visitor_name) < 2:
        raise ValueError("Enter your full name")
    cat = normalize_adhoc_category(category)
    lease_hours = int(hours) if hours is not None else DEFAULT_ADHOC_HOURS
    if lease_hours not in ALLOWED_ADHOC_HOURS:
        raise ValueError("Ad-hoc pass duration must be between 1 and 9 hours")
    if not photo_bytes:
        raise ValueError("Take a selfie to continue")

    pid = _new_id()
    code = _new_code(conn, KIND_ADHOC)
    # Synthetic plate key so schema stays unique / non-null without a vehicle.
    plate = f"ADHOC{pid.replace('pp_', '').upper()[:8]}"
    plate_display = "On foot / gate"
    issued_at, expires_at = _apply_window(lease_hours)
    now = utc_now()
    photo_filename = save_adhoc_photo(site_root, pid, photo_bytes)

    conn.execute(
        """
        INSERT INTO parking_passes(
          id, public_code, house_id, member_id, member_name, kind, plate, plate_display,
          colour, vehicle_type, visitor_name, tenant_id, tenant_phone, tenant_email, tenant_note,
          lease_hours, lease_months, photo_filename, status, issued_at, expires_at,
          renew_count, last_renewed_at, pending_renew_hours, pending_renew_at,
          approved_by_house_id, approved_by_name, revoked_reason, email_sent,
          created_at, updated_at
        ) VALUES (?, ?, ?, '', 'Main gate', ?, ?, ?, '', 'foot', ?, '', '', '', ?,
                  ?, 0, ?, 'active', ?, ?, 0, NULL, 0, NULL, NULL, NULL, '', 0, ?, ?)
        """,
        (
            pid,
            code,
            ADHOC_HOUSE_ID,
            KIND_ADHOC,
            plate,
            plate_display,
            visitor_name,
            cat,
            lease_hours,
            photo_filename,
            issued_at,
            expires_at,
            now,
            now,
        ),
    )
    _add_event(
        conn,
        pass_id=pid,
        action="issued",
        actor={"houseId": ADHOC_HOUSE_ID, "name": visitor_name},
        note=f"{lease_hours}h ad-hoc ({ADHOC_CATEGORIES.get(cat, cat)})",
    )
    conn.commit()
    item = get_pass(conn, pid, site_root=site_root, with_qr=True)
    if not item:
        raise ValueError("Pass could not be loaded after issue")
    # Embed selfie once for the public confirmation screen.
    path = adhoc_photo_path(site_root, photo_filename)
    if path and path.is_file():
        item["photoDataUrl"] = "data:image/webp;base64," + base64.b64encode(path.read_bytes()).decode("ascii")
    return item


def list_adhoc_passes(
    conn: sqlite3.Connection,
    *,
    site_root: pathlib.Path | None = None,
    limit: int = 40,
) -> list[dict[str, Any]]:
    ensure_parking_passes_table(conn)
    expire_due_passes(conn)
    rows = conn.execute(
        """
        SELECT p.*, 'GATE' AS plot_no
        FROM parking_passes p
        WHERE p.kind = ?
        ORDER BY p.created_at DESC
        LIMIT ?
        """,
        (KIND_ADHOC, max(1, min(int(limit or 40), 100))),
    ).fetchall()
    out = []
    for row in rows:
        item = _row_pass(row)
        if item:
            _attach_qr(item, site_root)
            out.append(item)
    return out


def renew_pass(
    conn: sqlite3.Connection,
    *,
    pass_id: str,
    actor: dict,
    payload: dict | None = None,
    site_root: pathlib.Path,
) -> dict[str, Any]:
    ensure_parking_passes_table(conn)
    expire_due_passes(conn)
    if actor.get("viewOnly"):
        raise PermissionError("View-only access cannot renew a parking pass")
    item = get_pass(conn, pass_id, site_root=site_root)
    if not item:
        raise ValueError("Pass not found")
    house_id = (actor.get("houseId") or "").strip()
    if item["houseId"] != house_id and not actor.get("superAdmin"):
        raise PermissionError("You can only renew passes for your plot")
    if item.get("permanent") or item.get("kind") == KIND_MEMBER:
        raise ValueError("Member vehicle passes are permanent and do not need renewal")
    if item.get("kind") == KIND_ADHOC:
        raise ValueError("Ad-hoc gate passes cannot be renewed. Scan the main gate QR for a new pass.")
    if item["status"] == "pending_renewal":
        raise ValueError("This renewal is already waiting for EC approval")
    if item["status"] == "revoked":
        raise ValueError("This pass was revoked. Request a new pass.")
    if item["status"] == "active":
        raise ValueError("This pass is still valid. Renew after it expires.")
    if item["status"] != "expired":
        raise ValueError("This pass cannot be renewed")

    payload = payload or {}
    now = utc_now()
    renew_count = int(item.get("renewCount") or 0)
    is_tenant = item.get("kind") == KIND_TENANT
    if is_tenant:
        duration = _months_from_payload(payload, fallback=item.get("leaseMonths") or DEFAULT_MONTHS)
        duration_note = f"{duration} month tenant lease"
        window_fn = _apply_month_window
    else:
        duration = _hours_from_payload(conn, payload)
        duration_note = f"{duration}h"
        window_fn = _apply_window

    if renew_count >= 1:
        conn.execute(
            """
            UPDATE parking_passes
            SET status = 'pending_renewal',
                pending_renew_hours = ?,
                pending_renew_at = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (duration, now, now, item["id"]),
        )
        _add_event(conn, pass_id=item["id"], action="renew_requested", actor=actor, note=duration_note)
        conn.commit()
        out = get_pass(conn, item["id"], site_root=site_root, with_qr=True)
        if not out:
            raise ValueError("Pass not found after renew request")
        out["renewKind"] = "pending_ec"
        return out

    issued_at, expires_at = window_fn(duration)
    if is_tenant:
        conn.execute(
            """
            UPDATE parking_passes
            SET status = 'active',
                lease_months = ?,
                issued_at = ?,
                expires_at = ?,
                renew_count = 1,
                last_renewed_at = ?,
                pending_renew_hours = 0,
                pending_renew_at = NULL,
                email_sent = 0,
                updated_at = ?
            WHERE id = ?
            """,
            (duration, issued_at, expires_at, now, now, item["id"]),
        )
    else:
        conn.execute(
            """
            UPDATE parking_passes
            SET status = 'active',
                lease_hours = ?,
                issued_at = ?,
                expires_at = ?,
                renew_count = 1,
                last_renewed_at = ?,
                pending_renew_hours = 0,
                pending_renew_at = NULL,
                email_sent = 0,
                updated_at = ?
            WHERE id = ?
            """,
            (duration, issued_at, expires_at, now, now, item["id"]),
        )
    _add_event(conn, pass_id=item["id"], action="renewed", actor=actor, note="1st renew (auto)")
    conn.commit()
    out = get_pass(conn, item["id"], site_root=site_root, with_qr=True)
    if not out:
        raise ValueError("Pass not found after renew")
    delivery = send_pass_email(conn, out, actor=actor, site_root=site_root, reason="renewed")
    out["emailDelivery"] = delivery
    out["renewKind"] = "auto_notify_ec"
    return out


def approve_renewal(
    conn: sqlite3.Connection,
    *,
    pass_id: str,
    actor: dict,
    site_root: pathlib.Path,
) -> dict[str, Any]:
    ensure_parking_passes_table(conn)
    item = get_pass(conn, pass_id, site_root=site_root)
    if not item:
        raise ValueError("Pass not found")
    if item["status"] != "pending_renewal":
        raise ValueError("This pass is not waiting for EC approval")
    now = utc_now()
    is_tenant = item.get("kind") == KIND_TENANT
    if is_tenant:
        months = int(item.get("pendingRenewHours") or item.get("leaseMonths") or DEFAULT_MONTHS)
        if months not in ALLOWED_MONTHS:
            months = DEFAULT_MONTHS
        issued_at, expires_at = _apply_month_window(months)
        conn.execute(
            """
            UPDATE parking_passes
            SET status = 'active',
                lease_months = ?,
                issued_at = ?,
                expires_at = ?,
                renew_count = renew_count + 1,
                last_renewed_at = ?,
                pending_renew_hours = 0,
                pending_renew_at = NULL,
                approved_by_house_id = ?,
                approved_by_name = ?,
                email_sent = 0,
                updated_at = ?
            WHERE id = ?
            """,
            (
                months,
                issued_at,
                expires_at,
                now,
                actor.get("houseId") or "",
                _actor_name(actor),
                now,
                item["id"],
            ),
        )
    else:
        hours = int(item.get("pendingRenewHours") or item.get("leaseHours") or default_hours(conn))
        if hours not in ALLOWED_HOURS:
            hours = default_hours(conn)
        issued_at, expires_at = _apply_window(hours)
        conn.execute(
            """
            UPDATE parking_passes
            SET status = 'active',
                lease_hours = ?,
                issued_at = ?,
                expires_at = ?,
                renew_count = renew_count + 1,
                last_renewed_at = ?,
                pending_renew_hours = 0,
                pending_renew_at = NULL,
                approved_by_house_id = ?,
                approved_by_name = ?,
                email_sent = 0,
                updated_at = ?
            WHERE id = ?
            """,
            (
                hours,
                issued_at,
                expires_at,
                now,
                actor.get("houseId") or "",
                _actor_name(actor),
                now,
                item["id"],
            ),
        )
    _add_event(conn, pass_id=item["id"], action="renew_approved", actor=actor)
    conn.commit()
    out = get_pass(conn, item["id"], site_root=site_root, with_qr=True)
    if not out:
        raise ValueError("Pass not found after approval")
    delivery = send_pass_email(conn, out, actor=None, site_root=site_root, reason="approved")
    out["emailDelivery"] = delivery
    return out


def reject_renewal(
    conn: sqlite3.Connection,
    *,
    pass_id: str,
    actor: dict,
    note: str = "",
) -> dict[str, Any]:
    ensure_parking_passes_table(conn)
    item = get_pass(conn, pass_id)
    if not item:
        raise ValueError("Pass not found")
    if item["status"] != "pending_renewal":
        raise ValueError("This pass is not waiting for EC approval")
    now = utc_now()
    reason = (note or "").strip()[:240]
    conn.execute(
        """
        UPDATE parking_passes
        SET status = 'expired',
            pending_renew_hours = 0,
            pending_renew_at = NULL,
            revoked_reason = ?,
            updated_at = ?
        WHERE id = ?
        """,
        (reason, now, item["id"]),
    )
    _add_event(conn, pass_id=item["id"], action="renew_rejected", actor=actor, note=reason)
    conn.commit()
    out = get_pass(conn, item["id"])
    if not out:
        raise ValueError("Pass not found after rejection")
    return out


def revoke_pass(
    conn: sqlite3.Connection,
    *,
    pass_id: str,
    actor: dict,
    note: str = "",
) -> dict[str, Any]:
    ensure_parking_passes_table(conn)
    item = get_pass(conn, pass_id)
    if not item:
        raise ValueError("Pass not found")
    if item["status"] == "revoked":
        return item
    now = utc_now()
    reason = (note or "").strip()[:240] or "Revoked by EC"
    conn.execute(
        """
        UPDATE parking_passes
        SET status = 'revoked',
            pending_renew_hours = 0,
            pending_renew_at = NULL,
            revoked_reason = ?,
            updated_at = ?
        WHERE id = ?
        """,
        (reason, now, item["id"]),
    )
    _add_event(conn, pass_id=item["id"], action="revoked", actor=actor, note=reason)
    conn.commit()
    out = get_pass(conn, item["id"])
    if not out:
        raise ValueError("Pass not found after revoke")
    return out


def remove_own_pass(
    conn: sqlite3.Connection,
    *,
    pass_id: str,
    actor: dict,
) -> dict[str, Any]:
    """Member may retire their own registered vehicle."""
    ensure_parking_passes_table(conn)
    item = get_pass(conn, pass_id)
    if not item:
        raise ValueError("Pass not found")
    house_id = (actor.get("houseId") or "").strip()
    if item["houseId"] != house_id and not actor.get("superAdmin"):
        raise PermissionError("You can only remove vehicles registered to your plot")
    if item.get("kind") != KIND_MEMBER:
        raise ValueError("Only a registered member vehicle can be removed this way")
    if item["status"] == "revoked":
        return item
    return revoke_pass(conn, pass_id=item["id"], actor=actor, note="Removed by member")


def ec_house_ids(conn: sqlite3.Connection) -> list[str]:
    ids: list[str] = []
    for row in rwa_entitlements.list_office_and_ec(conn):
        hid = (row.get("houseId") or "").strip()
        if hid and hid not in ids:
            ids.append(hid)
    return ids


def send_pass_email(
    conn: sqlite3.Connection,
    item: dict[str, Any],
    *,
    actor: dict | None,
    site_root: pathlib.Path,
    reason: str,
) -> dict[str, Any]:
    if item.get("kind") == KIND_ADHOC:
        return {"ok": False, "channel": "none", "reason": "adhoc"}
    to_email = ""
    if actor:
        to_email = actor_email(conn, actor)
    if not to_email:
        member = rwa_household.get_member(conn, item.get("memberId") or "")
        if member:
            to_email = str(member.get("email") or "").strip().lower()
    if not to_email:
        row = conn.execute(
            "SELECT email FROM residents WHERE house_id = ?",
            (item.get("houseId") or "",),
        ).fetchone()
        if row:
            to_email = str(row["email"] or "").strip().lower()
    tenant_email = str(item.get("tenantEmail") or "").strip().lower()
    recipients = []
    if to_email:
        recipients.append(to_email)
    if tenant_email and tenant_email not in recipients:
        recipients.append(tenant_email)
    if not recipients:
        return {"channel": "none", "reason": "no_email"}
    to_email = ", ".join(recipients)

    try:
        import rwa_portal
    except ImportError:
        return {"channel": "none", "reason": "mailer_unavailable"}

    cfg = rwa_portal.load_smtp_config(site_root)
    if not cfg.get("configured"):
        return {"channel": "dev", "reason": "smtp_not_configured"}

    origin = public_origin(site_root)
    pass_url = f"{origin}/#parking"
    plate = html.escape(item.get("plateDisplay") or item.get("plate") or "")
    code = html.escape(item.get("code") or "")
    visitor = html.escape(item.get("visitorName") or item.get("memberName") or "Member")
    colour = html.escape(item.get("colour") or "—")
    vtype = html.escape(item.get("vehicleTypeLabel") or "Car")
    hours = html.escape(str(item.get("leaseHours") or ""))
    expires = html.escape(item.get("expiresAtLabel") or "")
    plot = html.escape(item.get("plotNo") or item.get("houseId") or "")
    member = html.escape(item.get("memberName") or "")
    permanent = bool(item.get("permanent") or item.get("kind") == KIND_MEMBER)
    tenant = item.get("kind") == KIND_TENANT
    if permanent:
        card_title = "Member parking pass"
        validity = "Permanent member vehicle"
        subject_map = {"issued": "Member vehicle registered"}
        subject = f"HBC Sanyard — {subject_map.get(reason, 'Member parking pass')}"
        text_title = "Member vehicle parking pass"
        card_bg, accent, btn_bg, btn_fg, stripe = "#15233f", "#c4a15a", "#c4a15a", "#15233f", "#3a2e16"
    elif tenant:
        card_title = "Tenant parking pass"
        validity = f"Tenant lease {html.escape(str(item.get('leaseMonths') or ''))} months · Valid until {expires}"
        subject_map = {
            "issued": "Tenant parking pass issued",
            "renewed": "Tenant parking pass renewed",
            "approved": "Tenant parking pass approved",
        }
        subject = f"HBC Sanyard — {subject_map.get(reason, 'Tenant parking pass')}"
        text_title = "Tenant vehicle parking pass"
        card_bg, accent, btn_bg, btn_fg, stripe = "#143322", "#b7ddb8", "#4d8f57", "#f6f1e6", "#0b1f16"
    else:
        card_title = "Visitor parking pass"
        validity = f"Lease {hours} hours · Valid until {expires}"
        subject_map = {
            "issued": "Visitor parking pass issued",
            "renewed": "Visitor parking pass renewed",
            "approved": "Visitor parking pass approved",
        }
        subject = f"HBC Sanyard — {subject_map.get(reason, 'Visitor parking pass')}"
        text_title = "Visitor vehicle parking pass"
        card_bg, accent, btn_bg, btn_fg, stripe = "#3d1c18", "#f0c4a8", "#c46a3a", "#fff8f2", "#1c1010"
    text = (
        f"{text_title}\n\n"
        f"Pass: {item.get('code')}\n"
        f"Vehicle: {item.get('plateDisplay')}\n"
        f"Valid: {item.get('expiresAtLabel') or 'Permanent'}\n"
        f"Plot: {item.get('plotNo')}\n\n"
        f"Open your pass in the member area: {pass_url}\n\n"
        f"— Residents Welfare Association\n"
        f"  Housing Colony Sanyard, Mandi\n"
    )
    html_body = f"""<!DOCTYPE html>
<html><body style="margin:0;padding:24px;background:#f3eee3;font-family:Georgia,serif;color:#15233f;">
  <table width="100%" cellpadding="0" cellspacing="0" style="max-width:520px;margin:0 auto;background:{card_bg};border-radius:16px;overflow:hidden;">
    <tr><td style="height:18px;background:{stripe};"></td></tr>
    <tr><td style="padding:20px 24px 8px;color:{accent};letter-spacing:.18em;font-size:11px;text-transform:uppercase;">Himuda Housing Colony Sanyard</td></tr>
    <tr><td style="padding:0 24px 4px;color:#f6f1e6;font-size:22px;">{html.escape(card_title)}</td></tr>
    <tr><td style="padding:0 24px 16px;color:{accent};font-size:28px;letter-spacing:.12em;">{plate}</td></tr>
    <tr><td style="padding:0 24px 20px;color:#f6f1e6;font-size:14px;line-height:1.55;">
      Pass {code}<br>
      {vtype} · {colour} · {visitor}<br>
      Plot {plot} · {member}<br>
      {validity}
    </td></tr>
    <tr><td style="padding:0 24px 24px;">
      <a href="{html.escape(pass_url)}" style="display:inline-block;background:{btn_bg};color:{btn_fg};text-decoration:none;padding:10px 16px;border-radius:999px;font-family:system-ui,sans-serif;font-weight:600;">Open in Pass</a>
    </td></tr>
  </table>
  <p style="max-width:520px;margin:16px auto 0;font-size:12px;color:#5b6578;">Show this pass at the gate. Any EC member can verify the vehicle number.</p>
</body></html>"""
    try:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = f"HBC Sanyard RWA <{cfg['from']}>"
        msg["To"] = to_email
        msg["Reply-To"] = cfg["from"]
        msg.set_content(text)
        msg.add_alternative(html_body, subtype="html")
        with smtplib.SMTP(cfg["host"], cfg["port"], timeout=25) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.ehlo()
            smtp.login(cfg["user"], cfg["password"])
            smtp.send_message(msg)
        conn.execute(
            "UPDATE parking_passes SET email_sent = 1, updated_at = ? WHERE id = ?",
            (utc_now(), item["id"]),
        )
        conn.commit()
        return {"channel": "email", "to": to_email}
    except Exception as exc:  # noqa: BLE001
        return {"channel": "failed", "error": str(exc)}
