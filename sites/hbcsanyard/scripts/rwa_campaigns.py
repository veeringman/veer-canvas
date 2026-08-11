"""Colony campaigns and funding drives — plantation drives, member contributions."""

from __future__ import annotations

import json
import mimetypes
import pathlib
import re
import secrets
import shutil
import sqlite3
from typing import Any

from init_rwa_db import ensure_colony_campaigns_tables, utc_now

CAMPAIGN_KINDS: tuple[tuple[str, str], ...] = (
    ("plantation", "Plantation / greenery"),
    ("maintenance", "Maintenance fund"),
    ("development", "Development project"),
    ("welfare", "Welfare / community"),
    ("event", "Event / celebration"),
    ("general", "General fund"),
)

CAMPAIGN_STATUSES: tuple[tuple[str, str], ...] = (
    ("draft", "Draft (EC only)"),
    ("active", "Active — accepting contributions"),
    ("paused", "Paused"),
    ("completed", "Completed"),
    ("cancelled", "Cancelled"),
)

CAMPAIGN_AUDIENCES: tuple[tuple[str, str], ...] = (
    ("members", "Colony members only"),
    ("public", "Public — also on landing page"),
)

CAMPAIGN_MODES: tuple[tuple[str, str], ...] = (
    ("pledge", "Pledge only"),
    ("funding", "Accept funding"),
    ("both", "Pledges + funding"),
)

PLEDGE_AMOUNT_TYPES: tuple[tuple[str, str], ...] = (
    ("fixed", "Fixed amount per member"),
    ("discretionary", "Member chooses amount"),
)

CONTRIBUTION_METHODS: tuple[tuple[str, str], ...] = (
    ("upi", "UPI"),
    ("cash", "Cash"),
    ("bank_transfer", "Bank transfer"),
    ("cheque", "Cheque"),
    ("other", "Other"),
)

RECEIPT_MAX_FILES = 3
RECEIPT_MAX_BYTES = 8 * 1024 * 1024
IMAGE_MAX_BYTES = 4 * 1024 * 1024
CAMPAIGN_IMAGE_MAX_EDGE = 960
CAMPAIGN_IMAGE_QUALITY = 78
ALLOWED_RECEIPT_TYPES = frozenset(
    {"image/jpeg", "image/png", "image/webp", "application/pdf"}
)
ALLOWED_IMAGE_TYPES = frozenset({"image/jpeg", "image/png", "image/webp"})


def campaigns_meta() -> dict:
    return {
        "kinds": [{"id": k, "label": lbl} for k, lbl in CAMPAIGN_KINDS],
        "statuses": [{"id": s, "label": lbl} for s, lbl in CAMPAIGN_STATUSES],
        "audiences": [{"id": a, "label": lbl} for a, lbl in CAMPAIGN_AUDIENCES],
        "modes": [{"id": m, "label": lbl} for m, lbl in CAMPAIGN_MODES],
        "pledgeAmountTypes": [{"id": t, "label": lbl} for t, lbl in PLEDGE_AMOUNT_TYPES],
        "contributionMethods": [{"id": m, "label": lbl} for m, lbl in CONTRIBUTION_METHODS],
    }


def receipts_root(site_root: pathlib.Path) -> pathlib.Path:
    return site_root / "data" / "campaign-receipts"


def images_root(site_root: pathlib.Path) -> pathlib.Path:
    return site_root / "data" / "campaign-images"


def _kind(raw: str | None) -> str:
    key = (raw or "general").strip().lower()
    allowed = {k for k, _ in CAMPAIGN_KINDS}
    return key if key in allowed else "general"


def _status(raw: str | None) -> str:
    key = (raw or "draft").strip().lower()
    allowed = {s for s, _ in CAMPAIGN_STATUSES}
    if key not in allowed:
        raise ValueError("Invalid campaign status")
    return key


def _audience(raw: str | None) -> str:
    key = (raw or "members").strip().lower()
    if key not in {"members", "public"}:
        raise ValueError("audience must be members or public")
    return key


def _mode(raw: str | None) -> str:
    key = (raw or "both").strip().lower()
    allowed = {m for m, _ in CAMPAIGN_MODES}
    if key not in allowed:
        raise ValueError("mode must be pledge, funding, or both")
    return key


def _pledge_amount_type(raw: str | None) -> str:
    key = (raw or "discretionary").strip().lower()
    if key not in {"fixed", "discretionary"}:
        raise ValueError("pledgeAmountType must be fixed or discretionary")
    return key


def _method(raw: str | None) -> str:
    key = (raw or "upi").strip().lower()
    allowed = {m for m, _ in CONTRIBUTION_METHODS}
    return key if key in allowed else "upi"


def _as_amount(value) -> int:
    if value is None or value == "":
        raise ValueError("Amount is required")
    try:
        amt = int(float(value))
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid amount") from exc
    if amt <= 0:
        raise ValueError("Amount must be greater than zero")
    return amt


def _optional_target(value) -> int | None:
    if value is None or value == "":
        return None
    try:
        amt = int(float(value))
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid target amount") from exc
    if amt < 0:
        raise ValueError("Target amount cannot be negative")
    return amt or None


def _raised_for_campaign(conn: sqlite3.Connection, campaign_id: str) -> int:
    row = conn.execute(
        """
        SELECT COALESCE(SUM(amount), 0) AS total
        FROM campaign_contributions
        WHERE campaign_id = ? AND status = 'verified'
        """,
        (campaign_id,),
    ).fetchone()
    return int(row["total"] or 0)


def _pledged_for_campaign(conn: sqlite3.Connection, campaign_id: str) -> int:
    row = conn.execute(
        """
        SELECT COALESCE(SUM(amount), 0) AS total
        FROM campaign_pledges
        WHERE campaign_id = ?
        """,
        (campaign_id,),
    ).fetchone()
    return int(row["total"] or 0)


def _contributor_count(conn: sqlite3.Connection, campaign_id: str) -> int:
    row = conn.execute(
        """
        SELECT COUNT(DISTINCT house_id) AS n
        FROM campaign_contributions
        WHERE campaign_id = ? AND status = 'verified'
        """,
        (campaign_id,),
    ).fetchone()
    return int(row["n"] or 0)


def _pledger_count(conn: sqlite3.Connection, campaign_id: str) -> int:
    row = conn.execute(
        """
        SELECT COUNT(DISTINCT house_id) AS n
        FROM campaign_pledges
        WHERE campaign_id = ?
        """,
        (campaign_id,),
    ).fetchone()
    return int(row["n"] or 0)


def _suggestion_count(conn: sqlite3.Connection, campaign_id: str) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM campaign_suggestions WHERE campaign_id = ?",
        (campaign_id,),
    ).fetchone()
    return int(row["n"] or 0)


def _pending_count(conn: sqlite3.Connection, campaign_id: str) -> int:
    row = conn.execute(
        """
        SELECT COUNT(*) AS n
        FROM campaign_contributions
        WHERE campaign_id = ? AND status = 'pending'
        """,
        (campaign_id,),
    ).fetchone()
    return int(row["n"] or 0)


def _label_map(pairs: tuple[tuple[str, str], ...]) -> dict[str, str]:
    return dict(pairs)


_KIND_LABELS = _label_map(CAMPAIGN_KINDS)
_STATUS_LABELS = _label_map(CAMPAIGN_STATUSES)
_AUDIENCE_LABELS = _label_map(CAMPAIGN_AUDIENCES)
_MODE_LABELS = _label_map(CAMPAIGN_MODES)
_PLEDGE_AMOUNT_LABELS = _label_map(PLEDGE_AMOUNT_TYPES)
_METHOD_LABELS = _label_map(CONTRIBUTION_METHODS)


def campaign_cover_url(campaign_id: str, image_file: str | None) -> str | None:
    if not image_file:
        return None
    return f"/api/rwa/campaigns/{campaign_id}/cover"


def campaign_cover_path(site_root: pathlib.Path, campaign_id: str, image_file: str) -> pathlib.Path:
    return images_root(site_root) / campaign_id / image_file


def _campaign_public(conn: sqlite3.Connection, row: sqlite3.Row | dict, *, include_admin: bool = False) -> dict:
    if hasattr(row, "keys"):
        data = {k: row[k] for k in row.keys()}
    else:
        data = dict(row)
    cid = data.get("id") or ""
    kind = data.get("kind") or "general"
    status = data.get("status") or "draft"
    audience = data.get("audience") or "members"
    target = data.get("target_amount")
    mode = data.get("mode") or "both"
    pledge_amount_type = data.get("pledge_amount_type") or "discretionary"
    fixed_pledge = data.get("fixed_pledge_amount")
    image_file = data.get("image_file") or ""
    raised = _raised_for_campaign(conn, cid)
    pledged = _pledged_for_campaign(conn, cid)
    contributors = _contributor_count(conn, cid)
    pledgers = _pledger_count(conn, cid)
    suggestions = _suggestion_count(conn, cid)
    pending = _pending_count(conn, cid) if include_admin else 0
    progress_pct = None
    if target and int(target) > 0:
        # Progress against target uses raised + pledged depending on mode
        combined = raised
        if mode in {"pledge", "both"}:
            combined = pledged if mode == "pledge" else max(raised, pledged)
        if mode == "both":
            combined = raised + pledged
        progress_pct = min(100, round(100 * combined / int(target)))
    active = status == "active"
    out = {
        "id": cid,
        "title": data.get("title") or "",
        "kind": kind,
        "kindLabel": _KIND_LABELS.get(kind, kind),
        "summary": data.get("summary") or "",
        "details": data.get("details") or "",
        "status": status,
        "statusLabel": _STATUS_LABELS.get(status, status),
        "audience": audience,
        "audienceLabel": _AUDIENCE_LABELS.get(audience, audience),
        "mode": mode,
        "modeLabel": _MODE_LABELS.get(mode, mode),
        "pledgeAmountType": pledge_amount_type,
        "pledgeAmountTypeLabel": _PLEDGE_AMOUNT_LABELS.get(pledge_amount_type, pledge_amount_type),
        "fixedPledgeAmount": int(fixed_pledge) if fixed_pledge is not None else None,
        "targetAmount": int(target) if target is not None else None,
        "raisedAmount": raised,
        "pledgedAmount": pledged,
        "contributorCount": contributors,
        "pledgerCount": pledgers,
        "suggestionCount": suggestions,
        "progressPercent": progress_pct,
        "deadline": data.get("deadline") or "",
        "eventDate": data.get("event_date") or "",
        "location": data.get("location") or "",
        "paymentInstructions": data.get("payment_instructions") or "",
        "workId": data.get("work_id") or "",
        "imageUrl": campaign_cover_url(cid, image_file),
        "createdBy": data.get("created_by") or "",
        "createdAt": data.get("created_at"),
        "updatedAt": data.get("updated_at"),
        "canPledge": active and mode in {"pledge", "both"},
        "canContribute": active and mode in {"funding", "both"},
        "canSuggest": active,
    }
    if include_admin:
        out["pendingContributions"] = pending
    return out


def _can_view_campaign(campaign: dict, *, as_admin: bool, signed_in: bool) -> bool:
    if as_admin:
        return True
    status = campaign.get("status") or "draft"
    if status == "draft":
        return False
    if not signed_in:
        return (campaign.get("audience") or "") == "public" and status != "cancelled"
    return status != "cancelled"


def list_campaigns(
    conn: sqlite3.Connection,
    *,
    kind: str | None = None,
    status: str | None = None,
    audience: str | None = None,
    as_admin: bool = False,
    public_only: bool = False,
) -> list[dict]:
    ensure_colony_campaigns_tables(conn)
    clauses: list[str] = []
    params: list[Any] = []
    if public_only:
        clauses.append("audience = 'public'")
        clauses.append("status = 'active'")
    elif not as_admin:
        clauses.append("status != 'draft'")
        clauses.append("status != 'cancelled'")
    if kind:
        clauses.append("kind = ?")
        params.append(_kind(kind))
    if status:
        if status == "active":
            clauses.append("status IN ('active','paused')")
        else:
            clauses.append("status = ?")
            params.append(_status(status))
    if audience in {"members", "public"} and as_admin:
        clauses.append("audience = ?")
        params.append(audience)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = conn.execute(
        f"""
        SELECT * FROM colony_campaigns
        {where}
        ORDER BY
          CASE status
            WHEN 'active' THEN 0
            WHEN 'paused' THEN 1
            WHEN 'draft' THEN 2
            WHEN 'completed' THEN 3
            ELSE 4
          END,
          COALESCE(deadline, event_date, updated_at) DESC,
          id DESC
        """,
        params,
    ).fetchall()
    out = []
    for row in rows:
        item = _campaign_public(conn, row, include_admin=as_admin)
        if public_only or _can_view_campaign(item, as_admin=as_admin, signed_in=True):
            out.append(item)
    return out


def get_campaign(
    conn: sqlite3.Connection,
    campaign_id: str,
    *,
    as_admin: bool = False,
    signed_in: bool = True,
) -> dict | None:
    ensure_colony_campaigns_tables(conn)
    row = conn.execute("SELECT * FROM colony_campaigns WHERE id = ?", (campaign_id,)).fetchone()
    if not row:
        return None
    item = _campaign_public(conn, row, include_admin=as_admin)
    if not _can_view_campaign(item, as_admin=as_admin, signed_in=signed_in):
        return None
    return item


def upsert_campaign(
    conn: sqlite3.Connection,
    payload: dict,
    *,
    actor: dict | None = None,
) -> dict:
    ensure_colony_campaigns_tables(conn)
    campaign_id = (payload.get("id") or f"cmp_{secrets.token_hex(6)}").strip()
    existing = conn.execute("SELECT * FROM colony_campaigns WHERE id = ?", (campaign_id,)).fetchone()

    title = payload.get("title") if "title" in payload else (existing["title"] if existing else "")
    title = str(title or "").strip()
    if len(title) < 2:
        raise ValueError("Title required")

    kind = _kind(payload.get("kind") if "kind" in payload else (existing["kind"] if existing else None))
    status = _status(
        payload.get("status") if "status" in payload else (existing["status"] if existing else "draft")
    )
    audience = _audience(
        payload.get("audience") if "audience" in payload else (existing["audience"] if existing else "members")
    )
    mode = _mode(payload.get("mode") if "mode" in payload else (existing["mode"] if existing else "both"))
    pledge_amount_type = _pledge_amount_type(
        payload.get("pledgeAmountType")
        if "pledgeAmountType" in payload
        else payload.get("pledge_amount_type")
        if "pledge_amount_type" in payload
        else (existing["pledge_amount_type"] if existing else "discretionary")
    )

    def pick(field: str, col: str | None = None, default: str = "") -> str:
        col = col or field
        snake = re.sub(r"(?<!^)(?=[A-Z])", "_", field).lower()
        if field in payload or snake in payload:
            val = payload.get(field, payload.get(snake))
            return str(val or "").strip()
        if existing:
            return str(existing[col] or "")
        return default

    summary = pick("summary")[:800]
    details = pick("details")[:8000]
    deadline = pick("deadline")[:20]
    event_date = pick("eventDate", "event_date")[:20]
    location = pick("location")[:160]
    payment_instructions = pick("paymentInstructions", "payment_instructions")[:2000]
    work_id = pick("workId", "work_id")[:40] or None

    if "targetAmount" in payload or "target_amount" in payload:
        target_amount = _optional_target(payload.get("targetAmount", payload.get("target_amount")))
    else:
        target_amount = existing["target_amount"] if existing else None

    if mode == "funding":
        pledge_amount_type = "discretionary"
        fixed_pledge_amount = None
    elif "fixedPledgeAmount" in payload or "fixed_pledge_amount" in payload:
        fixed_pledge_amount = _optional_target(
            payload.get("fixedPledgeAmount", payload.get("fixed_pledge_amount"))
        )
    else:
        fixed_pledge_amount = existing["fixed_pledge_amount"] if existing else None

    if pledge_amount_type == "fixed" and not fixed_pledge_amount:
        raise ValueError("Fixed pledge amount is required when pledge amount type is fixed")

    image_file = existing["image_file"] if existing else None

    now = utc_now()
    actor_house = str((actor or {}).get("houseId") or (actor or {}).get("house_id") or "")
    created_by = (existing["created_by"] if existing and existing["created_by"] else None) or actor_house or None
    created_at = existing["created_at"] if existing else now

    conn.execute(
        """
        INSERT INTO colony_campaigns(
          id, title, kind, summary, details, status, audience, target_amount,
          deadline, event_date, location, payment_instructions, work_id,
          mode, pledge_amount_type, fixed_pledge_amount, image_file,
          created_by, created_at, updated_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(id) DO UPDATE SET
          title=excluded.title,
          kind=excluded.kind,
          summary=excluded.summary,
          details=excluded.details,
          status=excluded.status,
          audience=excluded.audience,
          target_amount=excluded.target_amount,
          deadline=excluded.deadline,
          event_date=excluded.event_date,
          location=excluded.location,
          payment_instructions=excluded.payment_instructions,
          work_id=excluded.work_id,
          mode=excluded.mode,
          pledge_amount_type=excluded.pledge_amount_type,
          fixed_pledge_amount=excluded.fixed_pledge_amount,
          updated_at=excluded.updated_at
        """,
        (
            campaign_id,
            title,
            kind,
            summary or None,
            details or None,
            status,
            audience,
            target_amount,
            deadline or None,
            event_date or None,
            location or None,
            payment_instructions or None,
            work_id,
            mode,
            pledge_amount_type,
            fixed_pledge_amount,
            image_file,
            created_by,
            created_at,
            now,
        ),
    )
    conn.commit()
    out = get_campaign(conn, campaign_id, as_admin=True, signed_in=True)
    if not out:
        raise ValueError("Could not load saved campaign")
    return out


def _optimize_campaign_cover_image(raw: bytes) -> tuple[bytes, str]:
    """Resize and compress campaign illustration for fast public-page loading."""
    try:
        from PIL import Image
    except ImportError as exc:  # pragma: no cover
        raise ValueError("Image processing unavailable on server") from exc
    from io import BytesIO

    try:
        img = Image.open(BytesIO(raw))
        img.load()
    except Exception as exc:  # noqa: BLE001
        raise ValueError("Could not read image") from exc
    if img.mode not in ("RGB", "L"):
        if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
            rgba = img.convert("RGBA")
            background = Image.new("RGB", rgba.size, (255, 255, 255))
            background.paste(rgba, mask=rgba.split()[-1])
            img = background
        else:
            img = img.convert("RGB")
    elif img.mode == "L":
        img = img.convert("RGB")
    w, h = img.size
    edge = max(w, h)
    if edge > CAMPAIGN_IMAGE_MAX_EDGE:
        scale = CAMPAIGN_IMAGE_MAX_EDGE / edge
        resample = Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS
        img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))), resample)
    buf = BytesIO()
    img.save(buf, format="WEBP", quality=CAMPAIGN_IMAGE_QUALITY, method=4)
    data = buf.getvalue()
    if not data:
        raise ValueError("Could not encode campaign image")
    return data, "image/webp"


def save_campaign_image(
    conn: sqlite3.Connection,
    site_root: pathlib.Path,
    *,
    campaign_id: str,
    data: bytes,
    filename: str,
    mime: str,
) -> str:
    ensure_colony_campaigns_tables(conn)
    if len(data) > IMAGE_MAX_BYTES:
        raise ValueError("Image exceeds size limit (4 MB)")
    mime = mime or mimetypes.guess_type(filename)[0] or "application/octet-stream"
    if mime not in ALLOWED_IMAGE_TYPES:
        raise ValueError("Image must be JPEG, PNG, or WebP")
    data, _out_mime = _optimize_campaign_cover_image(data)
    ext = ".webp"
    safe_name = f"cover{ext}"
    dest_dir = images_root(site_root) / campaign_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    for old in dest_dir.glob("cover.*"):
        old.unlink(missing_ok=True)
    (dest_dir / safe_name).write_bytes(data)
    now = utc_now()
    conn.execute(
        "UPDATE colony_campaigns SET image_file = ?, updated_at = ? WHERE id = ?",
        (safe_name, now, campaign_id),
    )
    conn.commit()
    return safe_name


def get_campaign_cover(
    conn: sqlite3.Connection,
    site_root: pathlib.Path,
    campaign_id: str,
    *,
    as_admin: bool = False,
    signed_in: bool = True,
) -> tuple[pathlib.Path, str] | None:
    campaign = get_campaign(conn, campaign_id, as_admin=as_admin, signed_in=signed_in)
    if not campaign:
        return None
    image_file = conn.execute(
        "SELECT image_file FROM colony_campaigns WHERE id = ?",
        (campaign_id,),
    ).fetchone()
    if not image_file or not image_file["image_file"]:
        return None
    path = campaign_cover_path(site_root, campaign_id, image_file["image_file"])
    if not path.is_file():
        return None
    mime = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    return path, mime


def delete_campaign(conn: sqlite3.Connection, campaign_id: str, *, site_root: pathlib.Path | None = None) -> None:
    ensure_colony_campaigns_tables(conn)
    cid = (campaign_id or "").strip()
    if not cid:
        raise ValueError("Campaign id required")
    if site_root:
        shutil.rmtree(receipts_root(site_root) / cid, ignore_errors=True)
        shutil.rmtree(images_root(site_root) / cid, ignore_errors=True)
    conn.execute("DELETE FROM campaign_pledges WHERE campaign_id = ?", (cid,))
    conn.execute("DELETE FROM campaign_contributions WHERE campaign_id = ?", (cid,))
    cur = conn.execute("DELETE FROM colony_campaigns WHERE id = ?", (cid,))
    if cur.rowcount < 1:
        raise ValueError("Campaign not found")
    conn.commit()


def _parse_files_json(raw) -> list[dict]:
    if not raw:
        return []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return []
    if not isinstance(raw, list):
        return []
    out = []
    for item in raw:
        if isinstance(item, dict) and item.get("name"):
            out.append({"name": str(item["name"]), "mime": str(item.get("mime") or "")})
    return out


def _contribution_public(conn: sqlite3.Connection, row: sqlite3.Row, *, mask_house: bool = False) -> dict:
    method = row["method"] or "upi"
    house_id = row["house_id"] or ""
    resident = None
    if house_id:
        resident = conn.execute(
            "SELECT name FROM residents WHERE house_id = ?",
            (house_id,),
        ).fetchone()
    display_name = (row["contributor_name"] or "").strip()
    if not display_name and resident:
        display_name = str(resident["name"] or "").strip()
    return {
        "id": row["id"],
        "campaignId": row["campaign_id"],
        "houseId": "" if mask_house else house_id,
        "contributorName": display_name,
        "amount": int(row["amount"] or 0),
        "method": method,
        "methodLabel": _METHOD_LABELS.get(method, method),
        "paidOn": row["paid_on"] or "",
        "note": row["note"] or "",
        "status": row["status"] or "pending",
        "files": _parse_files_json(row["files_json"]),
        "verifiedAt": row["verified_at"] or "",
        "rejectedReason": row["rejected_reason"] or "",
        "createdAt": row["created_at"],
    }


def _pledge_public(conn: sqlite3.Connection, row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "campaignId": row["campaign_id"],
        "houseId": row["house_id"] or "",
        "contributorName": row["contributor_name"] or "",
        "amount": int(row["amount"] or 0),
        "note": row["note"] or "",
        "createdAt": row["created_at"],
    }


def list_pledges(conn: sqlite3.Connection, campaign_id: str) -> list[dict]:
    ensure_colony_campaigns_tables(conn)
    rows = conn.execute(
        """
        SELECT * FROM campaign_pledges
        WHERE campaign_id = ?
        ORDER BY created_at DESC
        """,
        (campaign_id,),
    ).fetchall()
    return [_pledge_public(conn, r) for r in rows]


def create_pledge(
    conn: sqlite3.Connection,
    *,
    campaign_id: str,
    payload: dict,
    actor: dict,
) -> dict:
    ensure_colony_campaigns_tables(conn)
    campaign = get_campaign(conn, campaign_id, as_admin=False, signed_in=True)
    if not campaign:
        raise ValueError("Campaign not found")
    if not campaign.get("canPledge"):
        raise ValueError("This campaign is not accepting pledges")

    house_id = str(
        payload.get("houseId")
        or payload.get("house_id")
        or actor.get("houseId")
        or actor.get("house_id")
        or ""
    ).strip()
    if not house_id:
        raise ValueError("House / plot number is required")
    resident = conn.execute(
        "SELECT house_id, name FROM residents WHERE house_id = ?",
        (house_id,),
    ).fetchone()
    if not resident:
        raise ValueError(f"Unknown plot {house_id}")

    contributor_name = str(
        payload.get("contributorName") or payload.get("contributor_name") or ""
    ).strip()[:120]
    if not contributor_name:
        contributor_name = str(resident["name"] or "").strip()
    if not contributor_name:
        raise ValueError("Name is required")

    if campaign.get("pledgeAmountType") == "fixed" and campaign.get("fixedPledgeAmount"):
        amount = int(campaign["fixedPledgeAmount"])
    else:
        amount = _as_amount(payload.get("amount"))

    note = str(payload.get("note") or "").strip()[:500]
    pid = f"pl_{secrets.token_hex(8)}"
    now = utc_now()
    conn.execute(
        """
        INSERT INTO campaign_pledges(
          id, campaign_id, house_id, member_id, contributor_name, amount, note, created_at, updated_at
        ) VALUES (?,?,?,?,?,?,?,?,?)
        """,
        (
            pid,
            campaign_id,
            house_id,
            str(actor.get("memberId") or actor.get("member_id") or "") or None,
            contributor_name,
            amount,
            note or None,
            now,
            now,
        ),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM campaign_pledges WHERE id = ?", (pid,)).fetchone()
    if not row:
        raise ValueError("Could not load pledge")
    return _pledge_public(conn, row)


def list_contributions(
    conn: sqlite3.Connection,
    campaign_id: str,
    *,
    as_admin: bool = False,
    viewer_house: str | None = None,
    status: str | None = None,
) -> list[dict]:
    ensure_colony_campaigns_tables(conn)
    clauses = ["campaign_id = ?"]
    params: list[Any] = [campaign_id]
    if status in {"pending", "verified", "rejected"}:
        clauses.append("status = ?")
        params.append(status)
    if not as_admin and viewer_house:
        clauses.append("(status = 'verified' OR house_id = ?)")
        params.append(viewer_house)
    where = " AND ".join(clauses)
    rows = conn.execute(
        f"""
        SELECT * FROM campaign_contributions
        WHERE {where}
        ORDER BY
          CASE status WHEN 'pending' THEN 0 WHEN 'verified' THEN 1 ELSE 2 END,
          created_at DESC
        """,
        params,
    ).fetchall()
    out = []
    for row in rows:
        mask = not as_admin and row["house_id"] != viewer_house and row["status"] == "verified"
        out.append(_contribution_public(conn, row, mask_house=mask))
    return out


def _save_receipt_files(
    site_root: pathlib.Path,
    *,
    campaign_id: str,
    contribution_id: str,
    files: list[tuple[bytes, str, str]],
) -> list[dict]:
    if not files:
        return []
    dest_dir = receipts_root(site_root) / campaign_id / contribution_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    saved: list[dict] = []
    for i, (data, filename, mime) in enumerate(files[:RECEIPT_MAX_FILES]):
        if len(data) > RECEIPT_MAX_BYTES:
            raise ValueError(f"File {filename} exceeds size limit")
        mime = mime or mimetypes.guess_type(filename)[0] or "application/octet-stream"
        if mime not in ALLOWED_RECEIPT_TYPES:
            raise ValueError(f"Unsupported file type: {filename}")
        safe = re.sub(r"[^A-Za-z0-9._-]+", "_", filename)[:80] or f"receipt_{i + 1}"
        path = dest_dir / safe
        path.write_bytes(data)
        saved.append({"name": safe, "mime": mime})
    return saved


def create_contribution(
    conn: sqlite3.Connection,
    site_root: pathlib.Path,
    *,
    campaign_id: str,
    payload: dict,
    files: list[tuple[bytes, str, str]],
    actor: dict,
) -> dict:
    ensure_colony_campaigns_tables(conn)
    campaign = get_campaign(conn, campaign_id, as_admin=False, signed_in=True)
    if not campaign:
        raise ValueError("Campaign not found")
    if not campaign.get("canContribute"):
        raise ValueError("This campaign is not accepting contributions")

    house_id = str(
        payload.get("houseId")
        or payload.get("house_id")
        or actor.get("houseId")
        or actor.get("house_id")
        or ""
    ).strip()
    if not house_id:
        raise ValueError("Plot is required")
    resident = conn.execute("SELECT house_id, name FROM residents WHERE house_id = ?", (house_id,)).fetchone()
    if not resident:
        raise ValueError(f"Unknown plot {house_id}")

    amount = _as_amount(payload.get("amount"))
    method = _method(payload.get("method"))
    paid_on = str(payload.get("paidOn") or payload.get("paid_on") or "")[:20] or None
    note = str(payload.get("note") or "").strip()[:500]
    contributor_name = str(payload.get("contributorName") or payload.get("contributor_name") or "").strip()[:120]
    if not contributor_name:
        contributor_name = str(resident["name"] or "").strip()
    if not contributor_name:
        raise ValueError("Name is required")

    cid = f"cc_{secrets.token_hex(8)}"
    now = utc_now()
    file_meta: list[dict] = []
    if files:
        file_meta = _save_receipt_files(
            site_root,
            campaign_id=campaign_id,
            contribution_id=cid,
            files=files,
        )

    conn.execute(
        """
        INSERT INTO campaign_contributions(
          id, campaign_id, house_id, member_id, contributor_name, amount, method,
          paid_on, note, status, files_json, created_at, updated_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            cid,
            campaign_id,
            house_id,
            str(actor.get("memberId") or actor.get("member_id") or "") or None,
            contributor_name or None,
            amount,
            method,
            paid_on,
            note or None,
            "pending",
            json.dumps(file_meta) if file_meta else None,
            now,
            now,
        ),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM campaign_contributions WHERE id = ?", (cid,)).fetchone()
    if not row:
        raise ValueError("Could not load contribution")
    return _contribution_public(conn, row)


def verify_contribution(
    conn: sqlite3.Connection,
    *,
    campaign_id: str,
    contribution_id: str,
    actor: dict,
) -> dict:
    ensure_colony_campaigns_tables(conn)
    row = conn.execute(
        "SELECT * FROM campaign_contributions WHERE id = ? AND campaign_id = ?",
        (contribution_id, campaign_id),
    ).fetchone()
    if not row:
        raise ValueError("Contribution not found")
    if row["status"] != "pending":
        raise ValueError("Contribution is not pending")
    now = utc_now()
    verifier = str(actor.get("houseId") or actor.get("house_id") or "")
    conn.execute(
        """
        UPDATE campaign_contributions
        SET status = 'verified', verified_by = ?, verified_at = ?, updated_at = ?
        WHERE id = ?
        """,
        (verifier or None, now, now, contribution_id),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM campaign_contributions WHERE id = ?", (contribution_id,)).fetchone()
    return _contribution_public(conn, row)


def reject_contribution(
    conn: sqlite3.Connection,
    *,
    campaign_id: str,
    contribution_id: str,
    reason: str,
    actor: dict,
) -> dict:
    ensure_colony_campaigns_tables(conn)
    row = conn.execute(
        "SELECT * FROM campaign_contributions WHERE id = ? AND campaign_id = ?",
        (contribution_id, campaign_id),
    ).fetchone()
    if not row:
        raise ValueError("Contribution not found")
    if row["status"] != "pending":
        raise ValueError("Contribution is not pending")
    now = utc_now()
    conn.execute(
        """
        UPDATE campaign_contributions
        SET status = 'rejected', rejected_reason = ?, updated_at = ?
        WHERE id = ?
        """,
        (str(reason or "").strip()[:500] or None, now, contribution_id),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM campaign_contributions WHERE id = ?", (contribution_id,)).fetchone()
    return _contribution_public(conn, row)


def public_campaign_cards(conn: sqlite3.Connection, *, limit: int = 6) -> list[dict]:
    items = list_campaigns(conn, public_only=True)[:limit]
    cards = []
    for c in items:
        summary = (c.get("summary") or "").strip()
        if len(summary) > 200:
            summary = summary[:197].rstrip() + "…"
        cards.append({
            "id": c.get("id"),
            "title": c.get("title") or "",
            "summary": summary,
            "kindLabel": c.get("kindLabel") or "",
            "mode": c.get("mode") or "both",
            "modeLabel": c.get("modeLabel") or "",
            "targetAmount": c.get("targetAmount"),
            "raisedAmount": c.get("raisedAmount"),
            "pledgedAmount": c.get("pledgedAmount"),
            "progressPercent": c.get("progressPercent"),
            "deadline": c.get("deadline") or "",
            "contributorCount": c.get("contributorCount") or 0,
            "pledgerCount": c.get("pledgerCount") or 0,
            "imageUrl": c.get("imageUrl"),
        })
    return cards


def delete_pledge(
    conn: sqlite3.Connection,
    *,
    campaign_id: str,
    pledge_id: str,
) -> None:
    ensure_colony_campaigns_tables(conn)
    row = conn.execute(
        "SELECT id FROM campaign_pledges WHERE id = ? AND campaign_id = ?",
        (pledge_id, campaign_id),
    ).fetchone()
    if not row:
        raise ValueError("Pledge not found")
    conn.execute("DELETE FROM campaign_pledges WHERE id = ?", (pledge_id,))
    conn.commit()


def delete_contribution(
    conn: sqlite3.Connection,
    *,
    campaign_id: str,
    contribution_id: str,
) -> None:
    ensure_colony_campaigns_tables(conn)
    row = conn.execute(
        "SELECT id FROM campaign_contributions WHERE id = ? AND campaign_id = ?",
        (contribution_id, campaign_id),
    ).fetchone()
    if not row:
        raise ValueError("Contribution not found")
    conn.execute("DELETE FROM campaign_contributions WHERE id = ?", (contribution_id,))
    conn.commit()


def public_create_pledge(
    conn: sqlite3.Connection,
    *,
    campaign_id: str,
    house_id: str,
    contributor_name: str,
    amount: int,
    note: str = "",
) -> dict:
    """Create a pledge from the public page (no auth)."""
    ensure_colony_campaigns_tables(conn)
    pid = f"pl_{secrets.token_hex(8)}"
    now = utc_now()
    conn.execute(
        """INSERT INTO campaign_pledges(
            id, campaign_id, house_id, member_id, contributor_name, amount, note, created_at, updated_at
        ) VALUES (?,?,?,?,?,?,?,?,?)""",
        (pid, campaign_id, house_id, None, contributor_name, amount, note or None, now, now),
    )
    conn.commit()
    return {"id": pid, "contributorName": contributor_name, "amount": amount, "houseId": house_id}


def public_create_contribution(
    conn: sqlite3.Connection,
    *,
    campaign_id: str,
    house_id: str,
    contributor_name: str,
    amount: int,
    note: str = "",
) -> dict:
    """Create a contribution from the public page (no auth, pending review)."""
    ensure_colony_campaigns_tables(conn)
    cid = f"cc_{secrets.token_hex(8)}"
    now = utc_now()
    conn.execute(
        """INSERT INTO campaign_contributions(
            id, campaign_id, house_id, member_id, contributor_name, amount, status, note, created_at, updated_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (cid, campaign_id, house_id, None, contributor_name, amount, "pending", note or None, now, now),
    )
    conn.commit()
    return {"id": cid, "contributorName": contributor_name, "amount": amount, "houseId": house_id}


def _suggestion_public(row: sqlite3.Row | dict) -> dict:
    if hasattr(row, "keys"):
        data = {k: row[k] for k in row.keys()}
    else:
        data = dict(row)
    return {
        "id": data.get("id") or "",
        "contributorName": data.get("contributor_name") or "",
        "houseId": data.get("house_id") or "",
        "text": data.get("text") or "",
        "createdAt": data.get("created_at"),
    }


def list_suggestions(conn: sqlite3.Connection, campaign_id: str) -> list[dict]:
    ensure_colony_campaigns_tables(conn)
    rows = conn.execute(
        """
        SELECT * FROM campaign_suggestions
        WHERE campaign_id = ?
        ORDER BY created_at DESC
        """,
        (campaign_id,),
    ).fetchall()
    return [_suggestion_public(r) for r in rows]


def public_create_suggestion(
    conn: sqlite3.Connection,
    *,
    campaign_id: str,
    house_id: str,
    contributor_name: str,
    text: str,
) -> dict:
    ensure_colony_campaigns_tables(conn)
    body = str(text or "").strip()[:1000]
    if not body:
        raise ValueError("Suggestion text is required")
    sid = f"cs_{secrets.token_hex(8)}"
    now = utc_now()
    conn.execute(
        """INSERT INTO campaign_suggestions(
            id, campaign_id, house_id, member_id, contributor_name, text, created_at, updated_at
        ) VALUES (?,?,?,?,?,?,?,?)""",
        (sid, campaign_id, house_id, None, contributor_name, body, now, now),
    )
    conn.commit()
    return {"id": sid, "contributorName": contributor_name, "houseId": house_id, "text": body}


def create_suggestion(
    conn: sqlite3.Connection,
    *,
    campaign_id: str,
    payload: dict,
    actor: dict,
) -> dict:
    ensure_colony_campaigns_tables(conn)
    campaign = get_campaign(conn, campaign_id, as_admin=False, signed_in=True)
    if not campaign:
        raise ValueError("Campaign not found")
    if not campaign.get("canSuggest"):
        raise ValueError("This campaign is not accepting suggestions")
    house_id = str(
        payload.get("houseId") or payload.get("house_id") or payload.get("house")
        or actor.get("houseId") or actor.get("house_id") or ""
    ).strip()
    if not house_id:
        raise ValueError("House / plot number is required")
    contributor_name = str(
        payload.get("contributorName") or payload.get("contributor_name") or payload.get("name") or ""
    ).strip()[:120]
    if not contributor_name:
        contributor_name = str(actor.get("name") or "").strip()
    if not contributor_name:
        raise ValueError("Name is required")
    text = str(payload.get("text") or payload.get("suggestion") or "").strip()[:1000]
    if not text:
        raise ValueError("Suggestion text is required")
    sid = f"cs_{secrets.token_hex(8)}"
    now = utc_now()
    conn.execute(
        """INSERT INTO campaign_suggestions(
            id, campaign_id, house_id, member_id, contributor_name, text, created_at, updated_at
        ) VALUES (?,?,?,?,?,?,?,?)""",
        (
            sid,
            campaign_id,
            house_id,
            str(actor.get("memberId") or actor.get("member_id") or "") or None,
            contributor_name,
            text,
            now,
            now,
        ),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM campaign_suggestions WHERE id = ?", (sid,)).fetchone()
    return _suggestion_public(row)


def delete_suggestion(
    conn: sqlite3.Connection,
    *,
    campaign_id: str,
    suggestion_id: str,
) -> None:
    ensure_colony_campaigns_tables(conn)
    row = conn.execute(
        "SELECT id FROM campaign_suggestions WHERE id = ? AND campaign_id = ?",
        (suggestion_id, campaign_id),
    ).fetchone()
    if not row:
        raise ValueError("Suggestion not found")
    conn.execute("DELETE FROM campaign_suggestions WHERE id = ?", (suggestion_id,))
    conn.commit()
