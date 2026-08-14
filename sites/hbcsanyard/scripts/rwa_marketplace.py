"""Colony marketplace — businesses, service needs, and ads (city QR + homepage)."""

from __future__ import annotations

import hashlib
import mimetypes
import pathlib
import re
import secrets
import shutil
import sqlite3
from datetime import datetime, timezone
from typing import Any

from init_rwa_db import SUPERADMIN_HOUSE_ID, utc_now
import rwa_entitlements
import rwa_household

KINDS = ("business", "service_need", "ad")
STATUSES = ("pending", "published", "rejected", "archived")

BUSINESS_CATEGORIES: dict[str, str] = {
    "auto_hire": "Auto for hire",
    "cab_rent": "Car / cab for rent",
    "taxi": "Taxi / driver",
    "electrician": "Electrician",
    "plumber": "Plumber",
    "carpenter": "Carpenter",
    "grocery": "Grocery / kirana",
    "laundry": "Laundry / dry clean",
    "tuition": "Tuition / coaching",
    "medical": "Medical / pharmacy",
    "food": "Food / tiffin",
    "maid": "Maid / domestic help",
    "cook": "Cook",
    "hardware": "Hardware / repair",
    "other": "Other",
}

NEED_CATEGORIES: dict[str, str] = {
    "auto_hire": "Need auto / taxi",
    "cab_rent": "Need car / cab",
    "electrician": "Need electrician",
    "plumber": "Need plumber",
    "carpenter": "Need carpenter",
    "labour": "Need labour / help",
    "maid": "Need maid / domestic help",
    "cook": "Need cook",
    "tuition": "Need tutor",
    "medical": "Need medical help",
    "other": "Other need",
}

AD_CATEGORIES: dict[str, str] = {
    "colony": "Colony announcement",
    "event": "Event",
    "sale": "Sale / offer",
    "lost_found": "Lost & found",
    "other": "Other",
}

PHONE_RE = re.compile(r"\D+")
WEBSITE_RE = re.compile(r"^https?://[^\s/$.?#][^\s]*$", re.I)
import rwa_media


def categories_meta() -> dict[str, list[dict[str, str]]]:
    return {
        "business": [{"id": k, "label": v} for k, v in BUSINESS_CATEGORIES.items()],
        "service_need": [{"id": k, "label": v} for k, v in NEED_CATEGORIES.items()],
        "ad": [{"id": k, "label": v} for k, v in AD_CATEGORIES.items()],
    }


def ensure_marketplace_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS colony_marketplace (
          id TEXT PRIMARY KEY,
          kind TEXT NOT NULL
            CHECK(kind IN ('business','service_need','ad')),
          category TEXT NOT NULL DEFAULT 'other',
          title TEXT NOT NULL,
          description TEXT,
          contact_name TEXT NOT NULL,
          phone TEXT NOT NULL,
          email TEXT,
          area TEXT,
          house_id TEXT,
          member_id TEXT,
          status TEXT NOT NULL DEFAULT 'pending'
            CHECK(status IN ('pending','published','rejected','archived')),
          source TEXT NOT NULL DEFAULT 'public',
          reviewed_by_name TEXT,
          review_note TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          published_at TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_marketplace_kind_status
          ON colony_marketplace(kind, status, updated_at DESC)
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS colony_marketplace_interest (
          id TEXT PRIMARY KEY,
          listing_id TEXT NOT NULL,
          contact_name TEXT NOT NULL,
          phone TEXT,
          email TEXT,
          note TEXT,
          created_at TEXT NOT NULL,
          FOREIGN KEY(listing_id) REFERENCES colony_marketplace(id)
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_marketplace_interest_listing
          ON colony_marketplace_interest(listing_id, created_at DESC)
        """
    )
    cols = {row[1] for row in conn.execute("PRAGMA table_info(colony_marketplace)").fetchall()}
    if cols:
        if "image_file" not in cols:
            conn.execute("ALTER TABLE colony_marketplace ADD COLUMN image_file TEXT")
        if "website" not in cols:
            conn.execute("ALTER TABLE colony_marketplace ADD COLUMN website TEXT")
        if "reg_no" not in cols:
            conn.execute("ALTER TABLE colony_marketplace ADD COLUMN reg_no TEXT")
        if "manage_pin_hash" not in cols:
            conn.execute("ALTER TABLE colony_marketplace ADD COLUMN manage_pin_hash TEXT")
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_marketplace_reg_no
          ON colony_marketplace(reg_no)
          WHERE reg_no IS NOT NULL AND trim(reg_no) != ''
        """
    )
    conn.commit()
    _backfill_business_reg_nos(conn)


def normalize_kind(raw: str | None) -> str:
    key = (raw or "").strip().lower().replace("-", "_")
    if key in ("business", "biz", "service"):
        return "business"
    if key in ("service_need", "need", "needs", "request"):
        return "service_need"
    if key in ("ad", "ads", "advert", "classified"):
        return "ad"
    raise ValueError("Invalid listing kind")


def normalize_category(kind: str, raw: str | None) -> str:
    catalogs = {
        "business": BUSINESS_CATEGORIES,
        "service_need": NEED_CATEGORIES,
        "ad": AD_CATEGORIES,
    }
    catalog = catalogs.get(kind) or BUSINESS_CATEGORIES
    key = (raw or "other").strip().lower().replace(" ", "_").replace("-", "_")
    return key if key in catalog else "other"


def category_label(kind: str, category: str) -> str:
    catalogs = {
        "business": BUSINESS_CATEGORIES,
        "service_need": NEED_CATEGORIES,
        "ad": AD_CATEGORIES,
    }
    return (catalogs.get(kind) or {}).get(category) or category.replace("_", " ").title()


def normalize_phone(raw: str | None) -> str:
    digits = PHONE_RE.sub("", str(raw or ""))
    if len(digits) < 10:
        raise ValueError("Valid 10-digit mobile number is required")
    if len(digits) > 12:
        digits = digits[-12:]
    return digits


def normalize_website(raw: str | None) -> str:
    s = str(raw or "").strip()
    if not s:
        return ""
    if not re.match(r"^https?://", s, re.I):
        s = f"https://{s}"
    if len(s) > 200:
        raise ValueError("Website URL is too long")
    if not WEBSITE_RE.match(s):
        raise ValueError("Enter a valid website URL")
    return s


def normalize_listing_status(raw: str | None) -> str:
    key = (raw or "").strip().lower().replace("-", "_")
    aliases = {
        "suspend": "archived",
        "suspended": "archived",
        "disabled": "archived",
        "disable": "archived",
        "enable": "published",
        "enabled": "published",
        "live": "published",
        "active": "published",
        "remove": "archived",
    }
    key = aliases.get(key, key)
    if key not in STATUSES:
        raise ValueError("Invalid status")
    return key


def normalize_reg_no(raw: str | None) -> str:
    return re.sub(r"[\s]+", "", str(raw or "")).upper()


def _hash_manage_pin(item_id: str, pin: str) -> str:
    return hashlib.sha256(f"{item_id}:{str(pin or '').strip()}".encode("utf-8")).hexdigest()


def issue_manage_pin() -> str:
    return f"{secrets.randbelow(900000) + 100000}"


def next_business_reg_no(conn: sqlite3.Connection) -> str:
    year = datetime.now(timezone.utc).year
    prefix = f"MHWS-B-{year}-"
    row = conn.execute(
        "SELECT reg_no FROM colony_marketplace WHERE reg_no LIKE ? ORDER BY reg_no DESC LIMIT 1",
        (f"{prefix}%",),
    ).fetchone()
    seq = 1
    if row and row["reg_no"]:
        tail = str(row["reg_no"]).rsplit("-", 1)[-1]
        if tail.isdigit():
            seq = int(tail) + 1
    return f"{prefix}{seq:04d}"


def _backfill_business_reg_nos(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        """
        SELECT id FROM colony_marketplace
        WHERE kind = 'business' AND (reg_no IS NULL OR trim(reg_no) = '')
        ORDER BY created_at ASC, id ASC
        """
    ).fetchall()
    if not rows:
        return
    for row in rows:
        conn.execute(
            "UPDATE colony_marketplace SET reg_no = ? WHERE id = ?",
            (next_business_reg_no(conn), row["id"]),
        )
    conn.commit()


def get_item_by_reg_no(conn: sqlite3.Connection, reg_no: str) -> dict[str, Any] | None:
    ensure_marketplace_table(conn)
    key = normalize_reg_no(reg_no)
    if not key:
        return None
    row = conn.execute(
        "SELECT * FROM colony_marketplace WHERE replace(upper(coalesce(reg_no,'')), ' ', '') = ?",
        (key,),
    ).fetchone()
    return public_item(row) if row else None


def actor_can_manage_listing(
    conn: sqlite3.Connection,
    item: dict[str, Any] | None,
    *,
    actor: dict | None = None,
    pin: str | None = None,
) -> bool:
    if not item:
        return False
    if actor and rwa_entitlements.actor_has(actor, "manage_notices"):
        return True
    house_id = str((actor or {}).get("houseId") or "")
    if house_id and house_id != SUPERADMIN_HOUSE_ID and house_id == str(item.get("houseId") or ""):
        return True
    pin_s = str(pin or "").strip()
    if not pin_s:
        return False
    row = conn.execute(
        "SELECT manage_pin_hash FROM colony_marketplace WHERE id = ?",
        (item.get("id"),),
    ).fetchone()
    stored = (row["manage_pin_hash"] if row else "") or ""
    if not stored:
        return False
    return secrets.compare_digest(stored, _hash_manage_pin(str(item.get("id") or ""), pin_s))


def require_listing_access(
    conn: sqlite3.Connection,
    item: dict[str, Any] | None,
    *,
    actor: dict | None = None,
    pin: str | None = None,
) -> None:
    if not item:
        raise PermissionError("Listing not found")
    if actor and rwa_entitlements.actor_has(actor, "manage_notices"):
        return
    house_id = str((actor or {}).get("houseId") or "")
    if house_id and house_id != SUPERADMIN_HOUSE_ID and house_id == str(item.get("houseId") or ""):
        return
    pin_s = str(pin or "").strip()
    row = conn.execute(
        "SELECT manage_pin_hash FROM colony_marketplace WHERE id = ?",
        (item.get("id"),),
    ).fetchone()
    stored = (row["manage_pin_hash"] if row else "") or ""
    if pin_s and not stored:
        raise PermissionError("This listing has no manage PIN. Ask EC to edit, suspend, or remove it")
    if pin_s and stored and secrets.compare_digest(stored, _hash_manage_pin(str(item.get("id") or ""), pin_s)):
        return
    if pin_s:
        raise PermissionError("Incorrect PIN")
    raise PermissionError("Enter the registration number and PIN, or sign in as EC")


def listing_images_root(site_root: pathlib.Path) -> pathlib.Path:
    return site_root / "data" / "marketplace-images"


def listing_image_url(item_id: str | None, image_file: str | None) -> str | None:
    if not item_id or not image_file:
        return None
    return f"/api/rwa/public/marketplace/{item_id}/image"


def listing_image_path(
    site_root: pathlib.Path,
    item_id: str,
    image_file: str | None,
) -> pathlib.Path | None:
    if not item_id or not image_file:
        return None
    safe_id = re.sub(r"[^A-Za-z0-9_-]", "", str(item_id))
    name = pathlib.Path(str(image_file)).name
    if name != str(image_file) or ".." in name:
        return None
    path = listing_images_root(site_root) / safe_id / name
    return path if path.is_file() else None


def _optimize_listing_image(raw: bytes) -> tuple[bytes, str]:
    return rwa_media.optimize_portal_card_image(raw)


def save_listing_image(
    conn: sqlite3.Connection,
    site_root: pathlib.Path,
    *,
    item_id: str,
    data: bytes,
    filename: str,
    mime: str,
) -> str:
    ensure_marketplace_table(conn)
    if len(data) > rwa_media.UPLOAD_MAX_BYTES:
        raise ValueError("Image exceeds size limit (5 MB)")
    mime = mime or mimetypes.guess_type(filename)[0] or "application/octet-stream"
    if mime not in rwa_media.ALLOWED_IMAGE_TYPES:
        raise ValueError("Image must be JPEG, PNG, or WebP")
    data, _out_mime = _optimize_listing_image(data)
    safe_name = "photo.webp"
    safe_id = re.sub(r"[^A-Za-z0-9_-]", "", str(item_id))
    dest_dir = listing_images_root(site_root) / safe_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    for old in dest_dir.glob("photo.*"):
        old.unlink(missing_ok=True)
    (dest_dir / safe_name).write_bytes(data)
    now = utc_now()
    conn.execute(
        "UPDATE colony_marketplace SET image_file = ?, updated_at = ? WHERE id = ?",
        (safe_name, now, item_id),
    )
    conn.commit()
    return safe_name


def get_listing_image(
    conn: sqlite3.Connection,
    site_root: pathlib.Path,
    item_id: str,
    *,
    status: str | None = "published",
) -> tuple[pathlib.Path, str] | None:
    ensure_marketplace_table(conn)
    row = conn.execute(
        "SELECT image_file, status FROM colony_marketplace WHERE id = ?",
        (item_id,),
    ).fetchone()
    if not row or not row["image_file"]:
        return None
    if status and (row["status"] or "") != status:
        return None
    path = listing_image_path(site_root, item_id, row["image_file"])
    if not path:
        return None
    mime = mimetypes.guess_type(path.name)[0] or "image/webp"
    return path, mime


def public_item(
    row: sqlite3.Row | dict | None,
    *,
    reveal_contact: bool = True,
) -> dict[str, Any]:
    if not row:
        return {}
    data = {k: row[k] for k in row.keys()} if hasattr(row, "keys") and not isinstance(row, dict) else dict(row)
    kind = data.get("kind") or "business"
    category = data.get("category") or "other"
    hide_contact = (not reveal_contact) and kind in ("ad", "service_need")
    return {
        "id": data.get("id"),
        "kind": kind,
        "kindLabel": {
            "business": "Business",
            "service_need": "Service need",
            "ad": "Ad",
        }.get(kind, kind),
        "category": category,
        "categoryLabel": category_label(kind, category),
        "title": data.get("title") or "",
        "description": data.get("description") or "",
        "contactName": "" if hide_contact else (data.get("contact_name") or ""),
        "phone": "" if hide_contact else (data.get("phone") or ""),
        "email": "" if hide_contact else (data.get("email") or ""),
        "website": "" if hide_contact else (data.get("website") or ""),
        "area": data.get("area") or "",
        "imageUrl": listing_image_url(data.get("id"), data.get("image_file")),
        "houseId": (data.get("house_id") or "") if reveal_contact else "",
        "status": data.get("status") or "pending",
        "source": data.get("source") or "public",
        "reviewedByName": data.get("reviewed_by_name") or "",
        "reviewNote": data.get("review_note") or "",
        "createdAt": data.get("created_at") or "",
        "updatedAt": data.get("updated_at") or "",
        "publishedAt": data.get("published_at") or "",
        "regNo": data.get("reg_no") or "",
        "hasManagePin": bool(data.get("manage_pin_hash")),
        "acceptsInterest": kind in ("service_need", "ad"),
        "contactHidden": hide_contact,
    }


def get_item(conn: sqlite3.Connection, item_id: str) -> dict[str, Any] | None:
    ensure_marketplace_table(conn)
    tid = (item_id or "").strip()
    if not tid:
        return None
    row = conn.execute("SELECT * FROM colony_marketplace WHERE id = ?", (tid,)).fetchone()
    return public_item(row) if row else None


def list_items(
    conn: sqlite3.Connection,
    *,
    kind: str | None = None,
    status: str | None = "published",
    limit: int = 100,
    reveal_contact: bool = True,
) -> list[dict[str, Any]]:
    ensure_marketplace_table(conn)
    lim = max(1, min(int(limit or 100), 500))
    clauses: list[str] = []
    args: list[Any] = []
    if kind:
        clauses.append("kind = ?")
        args.append(normalize_kind(kind))
    st = (status or "published").strip().lower()
    if st and st != "all":
        if st not in STATUSES:
            raise ValueError("Invalid status filter")
        clauses.append("status = ?")
        args.append(st)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    rows = conn.execute(
        f"""
        SELECT * FROM colony_marketplace
        {where}
        ORDER BY
          CASE status WHEN 'pending' THEN 0 WHEN 'published' THEN 1 ELSE 2 END,
          COALESCE(published_at, updated_at) DESC
        LIMIT ?
        """,
        (*args, lim),
    ).fetchall()
    return [public_item(r, reveal_contact=reveal_contact) for r in rows]


def _clean_text(raw: Any, *, max_len: int) -> str:
    return re.sub(r"\s+", " ", str(raw or "").strip())[:max_len]


def create_item(
    conn: sqlite3.Connection,
    payload: dict,
    *,
    actor: dict | None = None,
    auto_publish: bool = False,
    source: str = "public",
) -> dict[str, Any]:
    ensure_marketplace_table(conn)
    kind = normalize_kind(payload.get("kind") or "business")
    category = normalize_category(kind, payload.get("category"))
    title = _clean_text(payload.get("title"), max_len=120)
    if not title:
        raise ValueError("Title is required")
    description = str(payload.get("description") or "").strip()[:800]
    contact_name = _clean_text(payload.get("contactName") or payload.get("name"), max_len=80)
    if not contact_name:
        raise ValueError("Contact name is required")
    phone = normalize_phone(payload.get("phone"))
    email_raw = str(payload.get("email") or "").strip().lower()
    email = ""
    if email_raw:
        email = rwa_household.validate_email(email_raw)
    website = normalize_website(payload.get("website"))
    area = _clean_text(payload.get("area"), max_len=80)
    house_id = ""
    member_id = ""
    if actor:
        house_id = str(actor.get("houseId") or "")[:40]
        member_id = str(actor.get("memberId") or "")[:40]
        if house_id == SUPERADMIN_HOUSE_ID:
            house_id = ""
    if kind == "service_need" and not actor and not auto_publish:
        # Public can still post a need from the city QR; stays pending for EC.
        source = source or "public"
    status = "published" if auto_publish else "pending"
    now = utc_now()
    item_id = "mk_" + secrets.token_hex(8)
    reg_no = next_business_reg_no(conn) if kind == "business" else ""
    manage_pin = issue_manage_pin() if kind == "business" else ""
    pin_hash = _hash_manage_pin(item_id, manage_pin) if manage_pin else ""
    conn.execute(
        """
        INSERT INTO colony_marketplace(
          id, kind, category, title, description, contact_name, phone, email, website, area,
          house_id, member_id, status, source, created_at, updated_at, published_at,
          reg_no, manage_pin_hash
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            item_id,
            kind,
            category,
            title,
            description,
            contact_name,
            phone,
            email,
            website,
            area,
            house_id,
            member_id,
            status,
            (source or "public")[:40],
            now,
            now,
            now if status == "published" else None,
            reg_no,
            pin_hash,
        ),
    )
    conn.commit()
    out = get_item(conn, item_id)
    if not out:
        raise ValueError("Listing could not be loaded after save")
    if manage_pin:
        out["managePin"] = manage_pin
    return out


def update_status(
    conn: sqlite3.Connection,
    item_id: str,
    *,
    status: str,
    actor: dict | None = None,
    pin: str | None = None,
    note: str = "",
) -> dict[str, Any]:
    ensure_marketplace_table(conn)
    st = normalize_listing_status(status)
    item = get_item(conn, item_id)
    if not item:
        raise ValueError("Listing not found")
    require_listing_access(conn, item, actor=actor, pin=pin)
    is_ec = bool(actor and rwa_entitlements.actor_has(actor, "manage_notices"))
    if not is_ec:
        if st == "rejected":
            raise PermissionError("Only EC can reject a listing")
        if st == "published":
            if item.get("status") == "archived" and item.get("publishedAt"):
                st = "published"
            elif item.get("status") in {"pending", "archived"} and not item.get("publishedAt"):
                st = "pending"
            elif item.get("status") != "published":
                raise PermissionError("EC must publish this listing before it can go live")
    now = utc_now()
    published_at = item.get("publishedAt") or None
    if st == "published":
        published_at = published_at or now
    conn.execute(
        """
        UPDATE colony_marketplace
        SET status = ?, reviewed_by_name = ?, review_note = ?, updated_at = ?, published_at = ?
        WHERE id = ?
        """,
        (
            st,
            (actor or {}).get("name") or "",
            _clean_text(note, max_len=200),
            now,
            published_at,
            item_id,
        ),
    )
    conn.commit()
    out = get_item(conn, item_id)
    if not out:
        raise ValueError("Listing not found after update")
    return out


def update_listing(
    conn: sqlite3.Connection,
    item_id: str,
    payload: dict,
    *,
    actor: dict | None = None,
    pin: str | None = None,
) -> dict[str, Any]:
    ensure_marketplace_table(conn)
    item = get_item(conn, item_id)
    if not item:
        raise ValueError("Listing not found")
    require_listing_access(conn, item, actor=actor, pin=pin or payload.get("pin"))
    kind = item.get("kind") or "ad"
    title = item.get("title") or ""
    if "title" in payload:
        title = _clean_text(payload.get("title"), max_len=120)
        if not title:
            raise ValueError("Title is required")
    category = item.get("category") or "other"
    if "category" in payload:
        category = normalize_category(kind, payload.get("category"))
    description = item.get("description") or ""
    if "description" in payload:
        description = str(payload.get("description") or "").strip()[:800]
    contact_name = item.get("contactName") or ""
    if "contactName" in payload or "name" in payload:
        contact_name = _clean_text(payload.get("contactName") or payload.get("name"), max_len=80)
        if not contact_name:
            raise ValueError("Contact name is required")
    phone = item.get("phone") or ""
    if "phone" in payload:
        phone = normalize_phone(payload.get("phone"))
    email = item.get("email") or ""
    if "email" in payload:
        email_raw = str(payload.get("email") or "").strip().lower()
        email = rwa_household.validate_email(email_raw) if email_raw else ""
    website = item.get("website") or ""
    if "website" in payload:
        website = normalize_website(payload.get("website"))
    area = item.get("area") or ""
    if "area" in payload:
        area = _clean_text(payload.get("area"), max_len=80)
    now = utc_now()
    conn.execute(
        """
        UPDATE colony_marketplace
        SET category = ?, title = ?, description = ?, contact_name = ?, phone = ?,
            email = ?, website = ?, area = ?, updated_at = ?
        WHERE id = ?
        """,
        (category, title, description, contact_name, phone, email, website, area, now, item_id),
    )
    conn.commit()
    out = get_item(conn, item_id)
    if not out:
        raise ValueError("Listing not found after update")
    return out


def delete_listing(
    conn: sqlite3.Connection,
    site_root: pathlib.Path,
    item_id: str,
    *,
    actor: dict | None = None,
    pin: str | None = None,
) -> dict[str, Any]:
    ensure_marketplace_table(conn)
    item = get_item(conn, item_id)
    if not item:
        raise ValueError("Listing not found")
    require_listing_access(conn, item, actor=actor, pin=pin)
    tid = (item_id or "").strip()
    conn.execute("DELETE FROM colony_marketplace_interest WHERE listing_id = ?", (tid,))
    conn.execute("DELETE FROM colony_marketplace WHERE id = ?", (tid,))
    conn.commit()
    safe_id = re.sub(r"[^A-Za-z0-9_-]", "", tid)
    if safe_id:
        dest_dir = listing_images_root(site_root) / safe_id
        if dest_dir.is_dir():
            shutil.rmtree(dest_dir, ignore_errors=True)
    return item


def create_listing(
    conn: sqlite3.Connection,
    payload: dict,
    *,
    actor: dict | None = None,
    source: str = "public",
) -> dict[str, Any]:
    """Public/member create with sensible publish defaults.

    - City QR / anonymous: businesses & needs stay pending for EC.
    - Signed-in residents: can publish a service they offer OR request a need (live at once).
    - Ads: EC Notices entitlement only.
    """
    kind = normalize_kind(payload.get("kind") or "business")
    auto = False
    src = source or "public"
    if kind == "ad":
        require_manage(actor)
        auto = True
        src = "ec"
    elif actor:
        # Verified residents may publish a service or request one.
        auto = True
        src = "resident"
        if kind == "business" and rwa_entitlements.actor_has(actor, "manage_notices"):
            auto = True
    return create_item(
        conn,
        payload,
        actor=actor,
        auto_publish=auto,
        source=src,
    )


def require_manage(actor: dict | None) -> None:
    if not actor:
        raise PermissionError("Sign in required")
    if not rwa_entitlements.actor_has(actor, "manage_notices"):
        raise PermissionError("Notices entitlement required to moderate listings")


def landing_slices(conn: sqlite3.Connection, *, limit_each: int = 6) -> dict[str, list[dict]]:
    """Published slices for the public homepage."""
    return {
        "businesses": list_items(
            conn, kind="business", status="published", limit=limit_each, reveal_contact=False
        ),
        "ads": list_items(
            conn, kind="ad", status="published", limit=limit_each, reveal_contact=False
        ),
        "serviceNeeds": list_items(
            conn, kind="service_need", status="published", limit=limit_each, reveal_contact=False
        ),
    }


def _interest_public(row: sqlite3.Row | dict | None) -> dict[str, Any]:
    if not row:
        return {}
    data = {k: row[k] for k in row.keys()} if hasattr(row, "keys") and not isinstance(row, dict) else dict(row)
    return {
        "id": data.get("id"),
        "listingId": data.get("listing_id") or "",
        "contactName": data.get("contact_name") or "",
        "phone": data.get("phone") or "",
        "email": data.get("email") or "",
        "note": data.get("note") or "",
        "createdAt": data.get("created_at") or "",
    }


def add_interest(
    conn: sqlite3.Connection,
    listing_id: str,
    payload: dict,
) -> dict[str, Any]:
    """Public: respond to a service need or ad with contact details."""
    ensure_marketplace_table(conn)
    item = get_item(conn, listing_id)
    if not item or item.get("status") != "published":
        raise ValueError("Listing not found")
    if item.get("kind") not in ("service_need", "ad"):
        raise ValueError("Interest can only be sent for service needs or ads")
    name = _clean_text(payload.get("contactName") or payload.get("name"), max_len=80)
    if not name:
        raise ValueError("Your name is required")
    phone_raw = str(payload.get("phone") or "").strip()
    email_raw = str(payload.get("email") or "").strip().lower()
    phone = ""
    email = ""
    if phone_raw:
        phone = normalize_phone(phone_raw)
    if email_raw:
        email = rwa_household.validate_email(email_raw)
    if not phone and not email:
        raise ValueError("Provide a mobile number or email so the resident can connect")
    note = str(payload.get("note") or "").strip()[:400]
    now = utc_now()
    iid = "mi_" + secrets.token_hex(8)
    conn.execute(
        """
        INSERT INTO colony_marketplace_interest(
          id, listing_id, contact_name, phone, email, note, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (iid, item["id"], name, phone, email, note, now),
    )
    conn.commit()
    row = conn.execute(
        "SELECT * FROM colony_marketplace_interest WHERE id = ?", (iid,)
    ).fetchone()
    out = _interest_public(row)
    # Prefer raw DB fields so notify works even when public_item hides houseId.
    raw = conn.execute(
        "SELECT house_id, member_id, kind, title FROM colony_marketplace WHERE id = ?",
        (item["id"],),
    ).fetchone()
    out["listing"] = {
        "id": item.get("id"),
        "kind": (raw["kind"] if raw else None) or item.get("kind"),
        "title": (raw["title"] if raw else None) or item.get("title") or "",
        "houseId": (raw["house_id"] if raw else None) or item.get("houseId") or "",
        "memberId": (raw["member_id"] if raw else None) or "",
    }
    return out


def notify_interest(
    conn: sqlite3.Connection,
    site_root,
    interest: dict[str, Any],
    *,
    notify_fn,
) -> None:
    """Push the listing owner (or EC for desk ads) when someone shows interest."""
    listing = interest.get("listing") or {}
    title = (listing.get("title") or "Your listing").strip()
    kind = listing.get("kind") or "service_need"
    name = (interest.get("contactName") or "Someone").strip()
    contact_bits = [x for x in (interest.get("phone"), interest.get("email")) if x]
    contact = " · ".join(contact_bits) if contact_bits else "new contact"
    label = "Service need" if kind == "service_need" else "Ad"
    body = f"{name} responded to “{title[:60]}” · {contact}"
    house_id = (listing.get("houseId") or "").strip()
    member_id = (listing.get("memberId") or "").strip()
    url = "/#home"
    if house_id:
        notify_fn(
            conn,
            event_type="notice",
            audience={"type": "houses", "houseIds": [house_id]},
            title=f"{label}: new interest",
            body=body[:240],
            url=url,
        )
    elif member_id:
        notify_fn(
            conn,
            event_type="notice",
            audience={"type": "members", "memberIds": [member_id]},
            title=f"{label}: new interest",
            body=body[:240],
            url=url,
        )
    else:
        notify_fn(
            conn,
            event_type="notice",
            audience={"type": "entitlement", "key": "manage_notices"},
            title=f"{label}: new interest",
            body=body[:240],
            url=url,
        )


def list_interests(
    conn: sqlite3.Connection,
    listing_id: str,
    *,
    actor: dict | None = None,
) -> list[dict[str, Any]]:
    ensure_marketplace_table(conn)
    item = get_item(conn, listing_id)
    if not item:
        raise ValueError("Listing not found")
    house_id = str((actor or {}).get("houseId") or "")
    is_owner = bool(house_id and house_id == (item.get("houseId") or ""))
    is_ec = bool(actor and rwa_entitlements.actor_has(actor, "manage_notices"))
    if not is_owner and not is_ec:
        raise PermissionError("Only the listing owner or EC can view interest")
    rows = conn.execute(
        """
        SELECT * FROM colony_marketplace_interest
        WHERE listing_id = ?
        ORDER BY created_at DESC
        LIMIT 80
        """,
        (listing_id,),
    ).fetchall()
    return [_interest_public(r) for r in rows]


def list_interests_for_house(
    conn: sqlite3.Connection,
    house_id: str,
) -> dict[str, list[dict[str, Any]]]:
    """Interests grouped by listing for a resident's published needs."""
    ensure_marketplace_table(conn)
    hid = (house_id or "").strip()
    if not hid:
        return {}
    rows = conn.execute(
        """
        SELECT i.*
        FROM colony_marketplace_interest i
        JOIN colony_marketplace m ON m.id = i.listing_id
        WHERE m.house_id = ?
        ORDER BY i.created_at DESC
        LIMIT 200
        """,
        (hid,),
    ).fetchall()
    out: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        item = _interest_public(row)
        out.setdefault(item["listingId"], []).append(item)
    return out
