"""Payment records + receipt vault for HBC Sanyard RWA."""

from __future__ import annotations

import pathlib
import re
import secrets
import shutil
import sqlite3
from datetime import datetime, timezone
from typing import Any

from init_rwa_db import SUPERADMIN_HOUSE_ID, ensure_payment_records_tables, utc_now

PAYMENT_KINDS = ("payment", "reimbursement")
PAYMENT_CATEGORIES = ("annual_dues", "special_levy", "other")
REIMBURSEMENT_CATEGORIES = ("colony_work", "supplies", "travel", "event", "other_expense")
ALL_CATEGORIES = PAYMENT_CATEGORIES + REIMBURSEMENT_CATEGORIES
PAYMENT_METHODS = ("upi", "bank", "cash", "other")
PAYMENT_STATUSES = ("submitted", "verified", "rejected", "reimbursed")

CATEGORY_LABELS = {
    "annual_dues": "Annual dues",
    "special_levy": "Special levy",
    "other": "Other payment",
    "colony_work": "Colony work / labour",
    "supplies": "Supplies / materials",
    "travel": "Travel / logistics",
    "event": "Event / function",
    "other_expense": "Other expense",
}
KIND_LABELS = {
    "payment": "Payment to RWA",
    "reimbursement": "Reimbursement claim",
}
METHOD_LABELS = {
    "upi": "UPI",
    "bank": "Bank transfer",
    "cash": "Cash",
    "other": "Other",
}

RECEIPT_MAX_FILES = 3
RECEIPT_MAX_BYTES = 5_000_000
RECEIPT_IMAGE_QUALITY = 72
RECEIPT_IMAGE_MAX_EDGE = 1600


def reconcile_orphan_receipts(conn: sqlite3.Connection, site_root: pathlib.Path) -> int:
    """Re-link receipt files on disk that lost their DB rows (e.g. after a cascade wipe)."""
    ensure_payment_records_tables(conn)
    root = receipts_root(site_root)
    if not root.is_dir():
        return 0
    fixed = 0
    now = utc_now()
    for house_dir in root.iterdir():
        if not house_dir.is_dir():
            continue
        for rec_dir in house_dir.iterdir():
            if not rec_dir.is_dir():
                continue
            rid = rec_dir.name
            if not conn.execute("SELECT 1 FROM payment_records WHERE id = ?", (rid,)).fetchone():
                continue
            for path in rec_dir.iterdir():
                if not path.is_file():
                    continue
                name = path.name
                if not re.fullmatch(r"rcpt_[A-Za-z0-9_-]+\.(webp|pdf)", name):
                    continue
                exists = conn.execute(
                    "SELECT 1 FROM payment_receipt_files WHERE record_id = ? AND filename = ?",
                    (rid, name),
                ).fetchone()
                if exists:
                    continue
                stem = path.stem
                fid = f"rf_{stem[5:]}" if stem.startswith("rcpt_") else f"rf_{secrets.token_hex(8)}"
                if conn.execute("SELECT 1 FROM payment_receipt_files WHERE id = ?", (fid,)).fetchone():
                    fid = f"rf_{secrets.token_hex(8)}"
                mime = "application/pdf" if name.endswith(".pdf") else "image/webp"
                width = height = None
                if mime.startswith("image/"):
                    try:
                        from PIL import Image
                        with Image.open(path) as img:
                            width, height = img.size
                    except Exception:  # noqa: BLE001
                        pass
                conn.execute(
                    """
                    INSERT INTO payment_receipt_files(
                      id, record_id, filename, original_name, mime, size_bytes, width, height, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        fid,
                        rid,
                        name,
                        name,
                        mime,
                        path.stat().st_size,
                        width,
                        height,
                        now,
                    ),
                )
                fixed += 1
    if fixed:
        conn.commit()
    return fixed


def _replace_receipt_files(
    conn: sqlite3.Connection,
    site_root: pathlib.Path,
    *,
    house_id: str,
    record_id: str,
    files: list[tuple[bytes, str, str]],
) -> None:
    if not files:
        raise ValueError("At least one receipt file is required")
    if len(files) > RECEIPT_MAX_FILES:
        raise ValueError(f"At most {RECEIPT_MAX_FILES} files per claim")

    old = conn.execute(
        "SELECT filename FROM payment_receipt_files WHERE record_id = ?",
        (record_id,),
    ).fetchall()
    conn.execute("DELETE FROM payment_receipt_files WHERE record_id = ?", (record_id,))

    dest_dir = receipts_root(site_root) / re.sub(r"[^A-Za-z0-9_-]", "_", house_id) / record_id
    if dest_dir.exists():
        shutil.rmtree(dest_dir, ignore_errors=True)
    dest_dir.mkdir(parents=True, exist_ok=True)
    now = utc_now()
    saved = 0
    try:
        for raw, content_type, original_name in files:
            data, mime, ext, width, height = _save_upload_bytes(raw, content_type, original_name)
            fid = f"rf_{secrets.token_hex(8)}"
            filename = f"rcpt_{fid[3:]}.{ext}"
            path = dest_dir / filename
            path.write_bytes(data)
            conn.execute(
                """
                INSERT INTO payment_receipt_files(
                  id, record_id, filename, original_name, mime, size_bytes, width, height, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    fid,
                    record_id,
                    filename,
                    (original_name or "")[:200] or None,
                    mime,
                    len(data),
                    width,
                    height,
                    now,
                ),
            )
            saved += 1
        if saved < 1:
            raise ValueError("At least one receipt file is required")
    except Exception:
        for f in old:
            # Best-effort: leave DB empty; caller rolls back transaction
            pass
        raise


def unapply_record_from_ledger(conn: sqlite3.Connection, record_id: str) -> None:
    """Reverse a previously applied verified payment on the latest ledger row."""
    row = conn.execute("SELECT * FROM payment_records WHERE id = ?", (record_id,)).fetchone()
    if not row:
        raise ValueError("Payment not found")
    if not int(row["ledger_applied"] or 0):
        return
    kind = (row["kind"] if "kind" in row.keys() else "payment") or "payment"
    if kind != "payment":
        conn.execute(
            "UPDATE payment_records SET ledger_applied = 0, updated_at = ? WHERE id = ?",
            (utc_now(), record_id),
        )
        return

    ledger = conn.execute(
        "SELECT id FROM payment_ledgers ORDER BY as_of DESC, id DESC LIMIT 1"
    ).fetchone()
    amount = int(row["amount"] or 0)
    if ledger and amount:
        existing = conn.execute(
            "SELECT * FROM payment_rows WHERE ledger_id = ? AND house_id = ?",
            (ledger["id"], row["house_id"]),
        ).fetchone()
        if existing:
            received = max(0, int(existing["amount_received"] or 0) - amount)
            balance_prev = int(existing["balance_prev"] or 0)
            fee_amount = int(existing["fee_amount"] or 0)
            total_due = int(existing["total_due"] or (balance_prev + fee_amount))
            outstanding = total_due - received
            remarks = (existing["remarks"] or "").strip()
            stamp = (row["paid_on"] or "")[:10]
            undo_bit = f"Reverted receipt {stamp} ₹{amount}"
            remarks = f"{remarks}; {undo_bit}".strip("; ").strip()[:500]
            conn.execute(
                """
                UPDATE payment_rows
                SET amount_received = ?, balance_outstanding = ?, remarks = ?
                WHERE id = ?
                """,
                (received, outstanding, remarks, existing["id"]),
            )
    conn.execute(
        "UPDATE payment_records SET ledger_applied = 0, updated_at = ? WHERE id = ?",
        (utc_now(), record_id),
    )


def update_record(
    conn: sqlite3.Connection,
    site_root: pathlib.Path,
    record_id: str,
    *,
    payload: dict,
    files: list[tuple[bytes, str, str]] | None = None,
    actor: dict,
) -> dict:
    """Edit a submitted/rejected payment or claim; optionally replace receipt files."""
    ensure_payment_records_tables(conn)
    row = conn.execute("SELECT * FROM payment_records WHERE id = ?", (record_id,)).fetchone()
    if not row:
        raise ValueError("Record not found")
    status = row["status"] or "submitted"
    if status not in ("submitted", "rejected"):
        raise ValueError("Only submitted or rejected items can be edited")

    kind = str(payload.get("kind") or row["kind"] or "payment").strip().lower()
    if kind not in PAYMENT_KINDS:
        raise ValueError("Invalid kind (payment or reimbursement)")
    allowed_cats = REIMBURSEMENT_CATEGORIES if kind == "reimbursement" else PAYMENT_CATEGORIES
    default_cat = "colony_work" if kind == "reimbursement" else "annual_dues"
    category = str(payload.get("category") or row["category"] or default_cat).strip().lower()
    if category not in allowed_cats:
        raise ValueError("Invalid category for this claim type")
    method = str(payload.get("method") or row["method"] or "upi").strip().lower()
    if method not in PAYMENT_METHODS:
        raise ValueError("Invalid payment method")
    amount = _as_amount(payload["amount"]) if "amount" in payload and payload.get("amount") not in (None, "") else int(row["amount"] or 0)
    fee_year = (
        _as_year(payload.get("feeYear") or payload.get("fee_year"))
        if ("feeYear" in payload or "fee_year" in payload)
        else int(row["fee_year"] or datetime.now(timezone.utc).year)
    )
    paid_on = (
        _as_paid_on(payload.get("paidOn") or payload.get("paid_on"))
        if ("paidOn" in payload or "paid_on" in payload)
        else (row["paid_on"] or "")
    )
    note = str(payload["note"]).strip()[:500] if "note" in payload else (row["note"] or "")

    now = utc_now()
    conn.execute(
        """
        UPDATE payment_records
        SET kind = ?, fee_year = ?, category = ?, amount = ?, paid_on = ?, method = ?, note = ?,
            status = 'submitted',
            reviewed_by_house_id = NULL,
            reviewed_at = NULL,
            review_note = NULL,
            updated_at = ?
        WHERE id = ?
        """,
        (
            kind,
            fee_year,
            category,
            amount,
            paid_on,
            method,
            note or None,
            now,
            record_id,
        ),
    )
    if files:
        _replace_receipt_files(
            conn,
            site_root,
            house_id=row["house_id"],
            record_id=record_id,
            files=files,
        )
    else:
        n = conn.execute(
            "SELECT COUNT(*) AS n FROM payment_receipt_files WHERE record_id = ?",
            (record_id,),
        ).fetchone()
        if int(n["n"] if hasattr(n, "keys") else n[0]) < 1:
            raise ValueError("This item has no receipt files — please re-upload at least one")

    conn.commit()
    out = get_record(conn, record_id)
    if not out:
        raise ValueError("Record not found after update")
    return out


def revert_record(
    conn: sqlite3.Connection,
    record_id: str,
    *,
    actor: dict,
    review_note: str | None = None,
) -> dict:
    """EC: send verified/rejected/reimbursed items back toward submitted for rework."""
    ensure_payment_records_tables(conn)
    row = conn.execute("SELECT * FROM payment_records WHERE id = ?", (record_id,)).fetchone()
    if not row:
        raise ValueError("Record not found")
    status = row["status"] or ""
    kind = (row["kind"] if "kind" in row.keys() else "payment") or "payment"
    now = utc_now()
    note = (review_note or "").strip()[:500] or None

    if status == "verified":
        unapply_record_from_ledger(conn, record_id)
        conn.execute(
            """
            UPDATE payment_records
            SET status = 'submitted',
                reviewed_by_house_id = ?,
                reviewed_at = ?,
                review_note = ?,
                treasury_status = 'pending',
                treasury_validated_by = NULL,
                treasury_validated_at = NULL,
                treasury_confirmed_by = NULL,
                treasury_confirmed_at = NULL,
                treasury_note = NULL,
                updated_at = ?
            WHERE id = ?
            """,
            (actor.get("houseId") or actor.get("house_id"), now, note or "Reverted to submitted", now, record_id),
        )
        import rwa_treasury

        rwa_treasury.mark_ledger_row_pending(conn, row["house_id"], commit=False)
    elif status == "rejected":
        conn.execute(
            """
            UPDATE payment_records
            SET status = 'submitted',
                reviewed_by_house_id = ?,
                reviewed_at = ?,
                review_note = ?,
                treasury_status = 'pending',
                treasury_validated_by = NULL,
                treasury_validated_at = NULL,
                treasury_confirmed_by = NULL,
                treasury_confirmed_at = NULL,
                treasury_note = NULL,
                updated_at = ?
            WHERE id = ?
            """,
            (actor.get("houseId") or actor.get("house_id"), now, note or "Reopened after rejection", now, record_id),
        )
    elif status == "reimbursed" and kind == "reimbursement":
        conn.execute(
            """
            UPDATE payment_records
            SET status = 'verified',
                reimbursed_at = NULL,
                reimbursed_by_house_id = NULL,
                reviewed_by_house_id = ?,
                reviewed_at = ?,
                review_note = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (actor.get("houseId") or actor.get("house_id"), now, note or "Reverted reimbursement", now, record_id),
        )
    else:
        raise ValueError("Only verified, rejected, or reimbursed items can be reverted")

    conn.commit()
    out = get_record(conn, record_id)
    if not out:
        raise ValueError("Record not found after revert")
    return out


def receipts_root(site_root: pathlib.Path) -> pathlib.Path:
    path = pathlib.Path(site_root) / "data" / "receipts"
    path.mkdir(parents=True, exist_ok=True)
    return path


def receipt_file_path(site_root: pathlib.Path, house_id: str, record_id: str, filename: str) -> pathlib.Path:
    safe_house = re.sub(r"[^A-Za-z0-9_-]", "_", (house_id or "").strip()) or "unknown"
    safe_rec = re.sub(r"[^A-Za-z0-9_-]", "_", (record_id or "").strip()) or "unknown"
    name = pathlib.Path(str(filename)).name
    if name != str(filename) or ".." in name:
        raise ValueError("Invalid receipt filename")
    if not re.fullmatch(r"rcpt_[A-Za-z0-9_-]+\.(webp|pdf)", name):
        raise ValueError("Invalid receipt filename")
    return receipts_root(site_root) / safe_house / safe_rec / name


def _as_amount(value) -> int:
    if value is None or value == "":
        raise ValueError("amount is required")
    try:
        cleaned = str(value).strip().replace(",", "").replace("₹", "").replace(" ", "")
        num = int(float(cleaned))
    except (TypeError, ValueError) as exc:
        raise ValueError("amount must be a whole-rupee amount") from exc
    if num < 1:
        raise ValueError("amount must be at least ₹1")
    if num > 10_000_000:
        raise ValueError("amount is too large")
    return num


def _as_year(value) -> int:
    try:
        year = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("feeYear must be a year number") from exc
    if year < 2000 or year > 2100:
        raise ValueError("feeYear out of range")
    return year


def _as_paid_on(value) -> str:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("paidOn date is required")
    # Accept YYYY-MM-DD
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        raise ValueError("paidOn must be YYYY-MM-DD")
    datetime.strptime(raw, "%Y-%m-%d")
    return raw


def _optimize_receipt_image(raw: bytes) -> tuple[bytes, str, int | None, int | None]:
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
    if edge > RECEIPT_IMAGE_MAX_EDGE:
        scale = RECEIPT_IMAGE_MAX_EDGE / edge
        resample = Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS
        img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))), resample)
    buf = BytesIO()
    img.save(buf, format="WEBP", quality=RECEIPT_IMAGE_QUALITY, method=4)
    data = buf.getvalue()
    if not data:
        raise ValueError("Could not encode receipt image")
    return data, "image/webp", img.size[0], img.size[1]


def _save_upload_bytes(raw: bytes, content_type: str, original_name: str) -> tuple[bytes, str, str, int | None, int | None]:
    """Return (bytes, mime, ext, width, height)."""
    ctype = (content_type or "").split(";")[0].strip().lower()
    name_l = (original_name or "").lower()
    is_pdf = ctype == "application/pdf" or name_l.endswith(".pdf")
    is_image = ctype.startswith("image/") or re.search(r"\.(jpe?g|png|webp|gif)$", name_l)
    if is_pdf:
        if len(raw) > RECEIPT_MAX_BYTES:
            raise ValueError("PDF must be under 5 MB")
        if not raw.startswith(b"%PDF"):
            raise ValueError("File does not look like a PDF")
        return raw, "application/pdf", "pdf", None, None
    if is_image:
        if len(raw) > RECEIPT_MAX_BYTES:
            raise ValueError("Image must be under 5 MB")
        data, mime, w, h = _optimize_receipt_image(raw)
        return data, mime, "webp", w, h
    raise ValueError("Receipts must be JPG, PNG, WebP, or PDF")


def _files_for_record(conn: sqlite3.Connection, record_id: str) -> list[dict]:
    rows = conn.execute(
        """
        SELECT id, record_id, filename, original_name, mime, size_bytes, width, height, created_at
        FROM payment_receipt_files
        WHERE record_id = ?
        ORDER BY created_at ASC
        """,
        (record_id,),
    ).fetchall()
    out = []
    for r in rows:
        out.append({
            "id": r["id"],
            "recordId": r["record_id"],
            "filename": r["filename"],
            "originalName": r["original_name"] or "",
            "mime": r["mime"],
            "sizeBytes": int(r["size_bytes"] or 0),
            "width": r["width"],
            "height": r["height"],
            "url": f"/api/rwa/payments/receipts/{r['id']}",
            "createdAt": r["created_at"],
        })
    return out


def public_record(conn: sqlite3.Connection, row: sqlite3.Row | dict) -> dict:
    if hasattr(row, "keys"):
        data = {k: row[k] for k in row.keys()}
    else:
        data = dict(row)
    cat = data.get("category") or "other"
    method = data.get("method") or "other"
    kind = data.get("kind") or "payment"
    import rwa_treasury

    out = {
        "id": data.get("id"),
        "houseId": data.get("house_id"),
        "kind": kind,
        "kindLabel": KIND_LABELS.get(kind, kind),
        "feeYear": int(data.get("fee_year") or 0),
        "category": cat,
        "categoryLabel": CATEGORY_LABELS.get(cat, cat),
        "amount": int(data.get("amount") or 0),
        "paidOn": data.get("paid_on") or "",
        "method": method,
        "methodLabel": METHOD_LABELS.get(method, method),
        "note": data.get("note") or "",
        "status": data.get("status") or "submitted",
        "uploadedByHouseId": data.get("uploaded_by_house_id") or "",
        "uploadedByMemberId": data.get("uploaded_by_member_id") or "",
        "uploadedByRole": data.get("uploaded_by_role") or "resident",
        "reviewedByHouseId": data.get("reviewed_by_house_id") or "",
        "reviewedAt": data.get("reviewed_at") or "",
        "reviewNote": data.get("review_note") or "",
        "ledgerApplied": bool(int(data.get("ledger_applied") or 0)),
        "reimbursedAt": data.get("reimbursed_at") or "",
        "reimbursedByHouseId": data.get("reimbursed_by_house_id") or "",
        "createdAt": data.get("created_at") or "",
        "updatedAt": data.get("updated_at") or "",
        "plotNo": data.get("plot_no") or data.get("house_id") or "",
        "residentName": data.get("name") or "",
        "files": _files_for_record(conn, str(data.get("id") or "")),
    }
    out.update(rwa_treasury.treasury_fields_from_row(data))
    return out


def get_record(conn: sqlite3.Connection, record_id: str) -> dict | None:
    ensure_payment_records_tables(conn)
    rid = (record_id or "").strip()
    if not rid:
        return None
    row = conn.execute(
        """
        SELECT pr.*, r.plot_no, r.name
        FROM payment_records pr
        LEFT JOIN residents r ON r.house_id = pr.house_id
        WHERE pr.id = ?
        """,
        (rid,),
    ).fetchone()
    return public_record(conn, row) if row else None


def list_records(
    conn: sqlite3.Connection,
    *,
    house_id: str | None = None,
    status: str | None = None,
    kind: str | None = None,
    limit: int = 100,
) -> list[dict]:
    ensure_payment_records_tables(conn)
    clauses: list[str] = []
    params: list[Any] = []
    if house_id:
        clauses.append("pr.house_id = ?")
        params.append(house_id.strip())
    if status and status != "all":
        clauses.append("pr.status = ?")
        params.append(status.strip())
    if kind and kind != "all":
        clauses.append("pr.kind = ?")
        params.append(kind.strip())
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    lim = max(1, min(int(limit or 100), 500))
    rows = conn.execute(
        f"""
        SELECT pr.*, r.plot_no, r.name
        FROM payment_records pr
        LEFT JOIN residents r ON r.house_id = pr.house_id
        {where}
        ORDER BY
          CASE pr.status
            WHEN 'submitted' THEN 0
            WHEN 'verified' THEN 1
            WHEN 'reimbursed' THEN 2
            ELSE 3 END,
          pr.created_at DESC
        LIMIT ?
        """,
        (*params, lim),
    ).fetchall()
    return [public_record(conn, r) for r in rows]


def create_record(
    conn: sqlite3.Connection,
    site_root: pathlib.Path,
    *,
    house_id: str,
    payload: dict,
    files: list[tuple[bytes, str, str]],
    actor: dict,
    uploaded_by_role: str = "resident",
) -> dict:
    ensure_payment_records_tables(conn)
    hid = (house_id or "").strip()
    if not hid or hid == SUPERADMIN_HOUSE_ID:
        raise ValueError("Valid plot is required")
    resident = conn.execute(
        "SELECT house_id FROM residents WHERE house_id = ?",
        (hid,),
    ).fetchone()
    if not resident:
        raise ValueError(f"Unknown plot {hid}")

    if not files:
        raise ValueError("At least one receipt file is required")
    if len(files) > RECEIPT_MAX_FILES:
        raise ValueError(f"At most {RECEIPT_MAX_FILES} files per claim")

    kind = str(payload.get("kind") or "payment").strip().lower()
    if kind not in PAYMENT_KINDS:
        raise ValueError("Invalid kind (payment or reimbursement)")
    allowed_cats = REIMBURSEMENT_CATEGORIES if kind == "reimbursement" else PAYMENT_CATEGORIES
    default_cat = "colony_work" if kind == "reimbursement" else "annual_dues"
    category = str(payload.get("category") or default_cat).strip().lower()
    if category not in allowed_cats:
        raise ValueError("Invalid category for this claim type")
    method = str(payload.get("method") or "upi").strip().lower()
    if method not in PAYMENT_METHODS:
        raise ValueError("Invalid payment method")
    amount = _as_amount(payload.get("amount"))
    fee_year = _as_year(payload.get("feeYear") or payload.get("fee_year") or datetime.now(timezone.utc).year)
    paid_on = _as_paid_on(payload.get("paidOn") or payload.get("paid_on"))
    note = str(payload.get("note") or "").strip()[:500]
    role = uploaded_by_role if uploaded_by_role in ("resident", "ec") else "resident"

    rid = f"pay_{secrets.token_hex(8)}"
    now = utc_now()
    conn.execute(
        """
        INSERT INTO payment_records(
          id, house_id, kind, fee_year, category, amount, paid_on, method, note, status,
          uploaded_by_house_id, uploaded_by_member_id, uploaded_by_role,
          ledger_applied, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'submitted', ?, ?, ?, 0, ?, ?)
        """,
        (
            rid,
            hid,
            kind,
            fee_year,
            category,
            amount,
            paid_on,
            method,
            note or None,
            actor.get("houseId") or actor.get("house_id"),
            actor.get("memberId") or actor.get("member_id"),
            role,
            now,
            now,
        ),
    )

    try:
        _replace_receipt_files(conn, site_root, house_id=hid, record_id=rid, files=files)
        conn.commit()
    except Exception:
        conn.rollback()
        dest_dir = receipts_root(site_root) / re.sub(r"[^A-Za-z0-9_-]", "_", hid) / rid
        shutil.rmtree(dest_dir, ignore_errors=True)
        raise

    out = get_record(conn, rid)
    if not out:
        raise ValueError("Could not load created payment")
    if not out.get("files"):
        raise ValueError("Receipt files failed to save — please try again")
    return out


def apply_record_to_ledger(conn: sqlite3.Connection, record_id: str) -> None:
    """Add verified payment amount into latest payment_rows for the plot."""
    row = conn.execute("SELECT * FROM payment_records WHERE id = ?", (record_id,)).fetchone()
    if not row:
        raise ValueError("Payment not found")
    if int(row["ledger_applied"] or 0):
        return
    kind = (row["kind"] if "kind" in row.keys() else "payment") or "payment"
    if kind != "payment":
        raise ValueError("Only payment receipts update the dues ledger")
    if row["status"] != "verified":
        raise ValueError("Only verified payments update the ledger")

    ledger = conn.execute(
        "SELECT id FROM payment_ledgers ORDER BY as_of DESC, id DESC LIMIT 1"
    ).fetchone()
    if not ledger:
        # No ledger yet — mark applied so we don't double-add later without a baseline.
        conn.execute(
            "UPDATE payment_records SET ledger_applied = 1, updated_at = ? WHERE id = ?",
            (utc_now(), record_id),
        )
        return

    existing = conn.execute(
        "SELECT * FROM payment_rows WHERE ledger_id = ? AND house_id = ?",
        (ledger["id"], row["house_id"]),
    ).fetchone()
    amount = int(row["amount"] or 0)
    stamp = (row["paid_on"] or "")[:10]
    note_bit = f"Verified receipt {stamp} ₹{amount}"
    if existing:
        received = int(existing["amount_received"] or 0) + amount
        balance_prev = int(existing["balance_prev"] or 0)
        fee_amount = int(existing["fee_amount"] or 0)
        total_due = int(existing["total_due"] or (balance_prev + fee_amount))
        outstanding = total_due - received
        remarks = (existing["remarks"] or "").strip()
        remarks = f"{remarks}; {note_bit}".strip("; ").strip()[:500]
        conn.execute(
            """
            UPDATE payment_rows
            SET amount_received = ?, balance_outstanding = ?, remarks = ?
            WHERE id = ?
            """,
            (received, outstanding, remarks, existing["id"]),
        )
        import rwa_treasury

        rwa_treasury.mark_ledger_row_pending(conn, row["house_id"], commit=False)
    else:
        # Create a sparse row if plot missing from latest ledger.
        conn.execute(
            """
            INSERT INTO payment_rows(
              ledger_id, house_id, balance_prev, fee_year, fee_amount,
              total_due, amount_received, balance_outstanding, remarks
            ) VALUES (?, ?, 0, ?, 0, 0, ?, ?, ?)
            """,
            (
                ledger["id"],
                row["house_id"],
                int(row["fee_year"] or 0),
                amount,
                -amount,
                note_bit,
            ),
        )
        import rwa_treasury

        rwa_treasury.mark_ledger_row_pending(conn, row["house_id"], commit=False)
    conn.execute(
        "UPDATE payment_records SET ledger_applied = 1, updated_at = ? WHERE id = ?",
        (utc_now(), record_id),
    )


def verify_record(
    conn: sqlite3.Connection,
    record_id: str,
    *,
    actor: dict,
    review_note: str | None = None,
) -> dict:
    ensure_payment_records_tables(conn)
    row = conn.execute("SELECT * FROM payment_records WHERE id = ?", (record_id,)).fetchone()
    if not row:
        raise ValueError("Record not found")
    if row["status"] != "submitted":
        raise ValueError("Only submitted items can be verified")
    now = utc_now()
    conn.execute(
        """
        UPDATE payment_records
        SET status = 'verified',
            reviewed_by_house_id = ?,
            reviewed_at = ?,
            review_note = ?,
            updated_at = ?
        WHERE id = ?
        """,
        (
            actor.get("houseId") or actor.get("house_id"),
            now,
            (review_note or "").strip()[:500] or None,
            now,
            record_id,
        ),
    )
    # Dues ledger only for payments to RWA — not reimbursement claims.
    kind = (row["kind"] if "kind" in row.keys() else "payment") or "payment"
    if kind == "payment":
        apply_record_to_ledger(conn, record_id)
    conn.commit()
    out = get_record(conn, record_id)
    if not out:
        raise ValueError("Record not found after verify")
    return out


def reject_record(
    conn: sqlite3.Connection,
    record_id: str,
    *,
    actor: dict,
    review_note: str | None = None,
) -> dict:
    ensure_payment_records_tables(conn)
    row = conn.execute("SELECT * FROM payment_records WHERE id = ?", (record_id,)).fetchone()
    if not row:
        raise ValueError("Record not found")
    if row["status"] != "submitted":
        raise ValueError("Only submitted items can be rejected")
    now = utc_now()
    conn.execute(
        """
        UPDATE payment_records
        SET status = 'rejected',
            reviewed_by_house_id = ?,
            reviewed_at = ?,
            review_note = ?,
            updated_at = ?
        WHERE id = ?
        """,
        (
            actor.get("houseId") or actor.get("house_id"),
            now,
            (review_note or "").strip()[:500] or None,
            now,
            record_id,
        ),
    )
    conn.commit()
    out = get_record(conn, record_id)
    if not out:
        raise ValueError("Record not found after reject")
    return out


def mark_reimbursed(
    conn: sqlite3.Connection,
    record_id: str,
    *,
    actor: dict,
    review_note: str | None = None,
) -> dict:
    """EC: mark an approved reimbursement claim as paid out to the resident."""
    ensure_payment_records_tables(conn)
    row = conn.execute("SELECT * FROM payment_records WHERE id = ?", (record_id,)).fetchone()
    if not row:
        raise ValueError("Claim not found")
    kind = (row["kind"] if "kind" in row.keys() else "payment") or "payment"
    if kind != "reimbursement":
        raise ValueError("Only reimbursement claims can be marked reimbursed")
    if row["status"] != "verified":
        raise ValueError("Approve the claim before marking it reimbursed")
    now = utc_now()
    note = (review_note or "").strip()[:500]
    existing_note = (row["review_note"] or "").strip()
    merged = f"{existing_note}; {note}".strip("; ").strip() if note else existing_note
    conn.execute(
        """
        UPDATE payment_records
        SET status = 'reimbursed',
            reimbursed_at = ?,
            reimbursed_by_house_id = ?,
            review_note = ?,
            updated_at = ?
        WHERE id = ?
        """,
        (
            now,
            actor.get("houseId") or actor.get("house_id"),
            merged or None,
            now,
            record_id,
        ),
    )
    conn.commit()
    out = get_record(conn, record_id)
    if not out:
        raise ValueError("Claim not found after update")
    return out


def delete_record(conn: sqlite3.Connection, site_root: pathlib.Path, record_id: str) -> None:
    ensure_payment_records_tables(conn)
    row = conn.execute("SELECT * FROM payment_records WHERE id = ?", (record_id,)).fetchone()
    if not row:
        raise ValueError("Record not found")
    if row["status"] == "verified" and int(row["ledger_applied"] or 0):
        raise ValueError("Verified payments that updated the ledger cannot be deleted")
    if row["status"] == "reimbursed":
        raise ValueError("Reimbursed claims cannot be deleted")
    files = conn.execute(
        "SELECT filename FROM payment_receipt_files WHERE record_id = ?",
        (record_id,),
    ).fetchall()
    house_id = row["house_id"]
    conn.execute("DELETE FROM payment_receipt_files WHERE record_id = ?", (record_id,))
    conn.execute("DELETE FROM payment_records WHERE id = ?", (record_id,))
    conn.commit()
    dest_dir = receipts_root(site_root) / re.sub(r"[^A-Za-z0-9_-]", "_", house_id) / record_id
    shutil.rmtree(dest_dir, ignore_errors=True)
    for f in files:
        try:
            p = receipt_file_path(site_root, house_id, record_id, f["filename"])
            if p.is_file():
                p.unlink()
        except ValueError:
            pass


def get_receipt_file(conn: sqlite3.Connection, file_id: str) -> dict | None:
    ensure_payment_records_tables(conn)
    fid = (file_id or "").strip()
    if not fid:
        return None
    row = conn.execute(
        """
        SELECT f.*, pr.house_id, pr.status AS record_status
        FROM payment_receipt_files f
        JOIN payment_records pr ON pr.id = f.record_id
        WHERE f.id = ?
        """,
        (fid,),
    ).fetchone()
    if not row:
        return None
    return {
        "id": row["id"],
        "recordId": row["record_id"],
        "houseId": row["house_id"],
        "filename": row["filename"],
        "mime": row["mime"],
        "originalName": row["original_name"] or "",
        "recordStatus": row["record_status"],
    }


def can_view_house_payments(actor: dict, house_id: str, *, can_manage_dues: bool) -> bool:
    if can_manage_dues or actor.get("superAdmin"):
        return True
    return (actor.get("houseId") or actor.get("house_id") or "") == house_id


def can_upload_for_house(actor: dict, house_id: str, *, can_manage_dues: bool) -> bool:
    if actor.get("viewOnly"):
        return False
    if can_manage_dues or actor.get("superAdmin"):
        return True
    return (actor.get("houseId") or actor.get("house_id") or "") == house_id
