"""No Dues Certificate requests: resident request → issuer issue → resident download."""

from __future__ import annotations

import pathlib
import re
import secrets
import sqlite3
from typing import Any, Callable

from init_rwa_db import ensure_no_dues_requests_table, utc_now
import rwa_reports

STATUS_LABELS = {
    "requested": "Requested",
    "issued": "Issued",
    "rejected": "Rejected",
}


def no_dues_root(site_root: pathlib.Path) -> pathlib.Path:
    path = pathlib.Path(site_root) / "data" / "no-dues"
    path.mkdir(parents=True, exist_ok=True)
    return path


def certificate_path(site_root: pathlib.Path, house_id: str, request_id: str, filename: str) -> pathlib.Path:
    safe_house = re.sub(r"[^A-Za-z0-9_-]", "_", (house_id or "").strip()) or "_"
    safe_id = re.sub(r"[^A-Za-z0-9_-]", "_", (request_id or "").strip()) or "_"
    safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", (filename or "").strip()) or "certificate.pdf"
    if ".." in safe_name or "/" in safe_name or "\\" in safe_name:
        raise ValueError("Invalid filename")
    base = (no_dues_root(site_root) / safe_house / safe_id).resolve()
    path = (base / safe_name).resolve()
    if not str(path).startswith(str(base)):
        raise ValueError("Invalid path")
    return path


def public_request(_conn: sqlite3.Connection, row: Any) -> dict:
    data = {k: row[k] for k in row.keys()}
    st = data.get("status") or "requested"
    rid = data.get("id")
    import rwa_treasury

    treasury = rwa_treasury.treasury_fields_from_row(data)
    can_download = (
        st == "issued"
        and rid
        and treasury.get("treasuryStatus") == "confirmed"
    )
    out = {
        "id": rid,
        "houseId": data.get("house_id"),
        "plotNo": data.get("plot_no") or data.get("house_id") or "",
        "residentName": data.get("name") or "",
        "status": st,
        "statusLabel": STATUS_LABELS.get(st, st),
        "requestNote": data.get("request_note") or "",
        "requestedByHouseId": data.get("requested_by_house_id") or "",
        "requestedByMemberId": data.get("requested_by_member_id") or "",
        "reviewedByHouseId": data.get("reviewed_by_house_id") or "",
        "reviewedAt": data.get("reviewed_at") or "",
        "reviewNote": data.get("review_note") or "",
        "issuedAt": data.get("issued_at") or "",
        "filename": data.get("filename") or "",
        "originalName": data.get("original_name") or "",
        "createdAt": data.get("created_at") or "",
        "updatedAt": data.get("updated_at") or "",
        "downloadUrl": (
            f"/api/rwa/payments/no-dues-requests/{rid}/download" if can_download else None
        ),
        "downloadLocked": bool(st == "issued" and rid and not can_download),
    }
    out.update(treasury)
    return out


def get_request(conn: sqlite3.Connection, request_id: str) -> dict | None:
    ensure_no_dues_requests_table(conn)
    rid = (request_id or "").strip()
    if not rid:
        return None
    row = conn.execute(
        """
        SELECT nd.*, r.plot_no, r.name
        FROM no_dues_requests nd
        LEFT JOIN residents r ON r.house_id = nd.house_id
        WHERE nd.id = ?
        """,
        (rid,),
    ).fetchone()
    return public_request(conn, row) if row else None


def list_requests(
    conn: sqlite3.Connection,
    *,
    house_id: str | None = None,
    status: str | None = None,
    limit: int = 100,
) -> list[dict]:
    ensure_no_dues_requests_table(conn)
    clauses: list[str] = []
    params: list[Any] = []
    if house_id:
        clauses.append("nd.house_id = ?")
        params.append(house_id.strip())
    if status and status != "all":
        clauses.append("nd.status = ?")
        params.append(status.strip())
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    lim = max(1, min(int(limit or 100), 500))
    rows = conn.execute(
        f"""
        SELECT nd.*, r.plot_no, r.name
        FROM no_dues_requests nd
        LEFT JOIN residents r ON r.house_id = nd.house_id
        {where}
        ORDER BY
          CASE nd.status WHEN 'requested' THEN 0 WHEN 'issued' THEN 1 ELSE 2 END,
          nd.created_at DESC
        LIMIT ?
        """,
        (*params, lim),
    ).fetchall()
    return [public_request(conn, r) for r in rows]


def create_request(
    conn: sqlite3.Connection,
    *,
    house_id: str,
    actor: dict,
    note: str | None = None,
    enrich_payment_row: Callable,
) -> dict:
    ensure_no_dues_requests_table(conn)
    hid = (house_id or "").strip()
    if not hid:
        raise ValueError("Plot required")
    info = rwa_reports.no_dues_eligibility(conn, hid, enrich_payment_row=enrich_payment_row)
    if not info.get("eligible"):
        raise ValueError(info.get("reason") or "Plot is not eligible for a No Dues Certificate")

    open_row = conn.execute(
        """
        SELECT id FROM no_dues_requests
        WHERE house_id = ? AND status = 'requested'
        LIMIT 1
        """,
        (hid,),
    ).fetchone()
    if open_row:
        raise ValueError("A No Dues Certificate request is already pending for this plot")

    rid = f"nd_{secrets.token_hex(8)}"
    now = utc_now()
    conn.execute(
        """
        INSERT INTO no_dues_requests(
          id, house_id, status, request_note,
          requested_by_house_id, requested_by_member_id,
          created_at, updated_at
        ) VALUES (?, ?, 'requested', ?, ?, ?, ?, ?)
        """,
        (
            rid,
            hid,
            (note or "").strip()[:500] or None,
            actor.get("houseId") or actor.get("house_id"),
            actor.get("memberId") or actor.get("member_id"),
            now,
            now,
        ),
    )
    conn.commit()
    out = get_request(conn, rid)
    if not out:
        raise ValueError("Request not found after create")
    return out


def reject_request(
    conn: sqlite3.Connection,
    request_id: str,
    *,
    actor: dict,
    review_note: str | None = None,
) -> dict:
    ensure_no_dues_requests_table(conn)
    row = conn.execute("SELECT * FROM no_dues_requests WHERE id = ?", (request_id,)).fetchone()
    if not row:
        raise ValueError("Request not found")
    if row["status"] != "requested":
        raise ValueError("Only pending requests can be rejected")
    now = utc_now()
    conn.execute(
        """
        UPDATE no_dues_requests
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
            request_id,
        ),
    )
    conn.commit()
    out = get_request(conn, request_id)
    if not out:
        raise ValueError("Request not found after reject")
    return out


def issue_request(
    conn: sqlite3.Connection,
    site_root: pathlib.Path,
    request_id: str,
    *,
    actor: dict,
    enrich_payment_row: Callable,
    review_note: str | None = None,
    public_base: str | None = None,
) -> dict:
    """Generate PDF, store on disk, mark request issued."""
    ensure_no_dues_requests_table(conn)
    row = conn.execute("SELECT * FROM no_dues_requests WHERE id = ?", (request_id,)).fetchone()
    if not row:
        raise ValueError("Request not found")
    if row["status"] != "requested":
        raise ValueError("Only pending requests can be issued")

    issuer_name = actor.get("name") or actor.get("houseId") or "RWA"
    issuer_house = actor.get("houseId") or actor.get("house_id") or ""
    now = utc_now()

    import rwa_attest

    att_id = rwa_attest.new_attestation_id()
    verify_url = rwa_attest.verify_url_for(site_root, att_id, public_base=public_base)
    pdf_bytes, download_name = rwa_reports.build_no_dues_certificate_pdf(
        conn,
        site_root=site_root,
        house_id=row["house_id"],
        enrich_payment_row=enrich_payment_row,
        issued_by=issuer_name,
        attestation_id=att_id,
        verify_url=verify_url,
    )
    filename = f"no-dues-{secrets.token_hex(4)}.pdf"
    dest = certificate_path(site_root, row["house_id"], request_id, filename)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(pdf_bytes)
    stored_rel = rwa_attest.safe_rel_path(site_root, dest)

    conn.execute(
        """
        UPDATE no_dues_requests
        SET status = 'issued',
            reviewed_by_house_id = ?,
            reviewed_at = ?,
            review_note = ?,
            issued_at = ?,
            filename = ?,
            original_name = ?,
            updated_at = ?
        WHERE id = ?
        """,
        (
            issuer_house,
            now,
            (review_note or "").strip()[:500] or None,
            now,
            filename,
            download_name,
            now,
            request_id,
        ),
    )
    rwa_attest.record_attestation(
        conn,
        site_root,
        attestation_id=att_id,
        artifact_type="no_dues",
        artifact_id=request_id,
        house_id=row["house_id"],
        issuer_house_id=issuer_house,
        issued_at=now,
        pdf_bytes=pdf_bytes,
        stored_path=stored_rel,
        filename=download_name,
        commit=True,
    )
    out = get_request(conn, request_id)
    if not out:
        raise ValueError("Request not found after issue")
    out["attestationId"] = att_id
    out["verifyUrl"] = verify_url
    return out


def issue_for_house(
    conn: sqlite3.Connection,
    site_root: pathlib.Path,
    *,
    house_id: str,
    actor: dict,
    enrich_payment_row: Callable,
    note: str | None = None,
    public_base: str | None = None,
) -> dict:
    """Issuer: issue pending request for plot, or create+issue when none pending."""
    hid = (house_id or "").strip()
    if not hid:
        raise ValueError("Plot required")
    pending = conn.execute(
        """
        SELECT id FROM no_dues_requests
        WHERE house_id = ? AND status = 'requested'
        ORDER BY created_at ASC
        LIMIT 1
        """,
        (hid,),
    ).fetchone()
    if pending:
        return issue_request(
            conn,
            site_root,
            pending["id"],
            actor=actor,
            enrich_payment_row=enrich_payment_row,
            review_note=note,
            public_base=public_base,
        )

    # Create a request attributed to the issuer, then issue immediately.
    ensure_no_dues_requests_table(conn)
    info = rwa_reports.no_dues_eligibility(conn, hid, enrich_payment_row=enrich_payment_row)
    if not info.get("eligible"):
        raise ValueError(info.get("reason") or "Plot is not eligible")
    rid = f"nd_{secrets.token_hex(8)}"
    now = utc_now()
    conn.execute(
        """
        INSERT INTO no_dues_requests(
          id, house_id, status, request_note,
          requested_by_house_id, requested_by_member_id,
          created_at, updated_at
        ) VALUES (?, ?, 'requested', ?, ?, ?, ?, ?)
        """,
        (
            rid,
            hid,
            (note or "").strip()[:500] or "Issued by No Dues Issuer",
            actor.get("houseId") or actor.get("house_id"),
            actor.get("memberId") or actor.get("member_id"),
            now,
            now,
        ),
    )
    conn.commit()
    return issue_request(
        conn,
        site_root,
        rid,
        actor=actor,
        enrich_payment_row=enrich_payment_row,
        review_note=note,
        public_base=public_base,
    )


def can_view_request(actor: dict, item: dict, *, can_issue: bool) -> bool:
    if can_issue or actor.get("superAdmin"):
        return True
    return (actor.get("houseId") or actor.get("house_id") or "") == (item.get("houseId") or "")


def cancel_request(
    conn: sqlite3.Connection,
    request_id: str,
    *,
    actor: dict,
    can_issue: bool = False,
) -> dict:
    """Resident or issuer: withdraw a pending request."""
    ensure_no_dues_requests_table(conn)
    row = conn.execute("SELECT * FROM no_dues_requests WHERE id = ?", (request_id,)).fetchone()
    if not row:
        raise ValueError("Request not found")
    if row["status"] != "requested":
        raise ValueError("Only pending requests can be cancelled")
    own = (actor.get("houseId") or actor.get("house_id") or "") == (row["house_id"] or "")
    if not own and not can_issue and not actor.get("superAdmin"):
        raise ValueError("Not allowed to cancel this request")
    conn.execute("DELETE FROM no_dues_requests WHERE id = ?", (request_id,))
    conn.commit()
    return {"id": request_id, "status": "cancelled"}


def revert_request(
    conn: sqlite3.Connection,
    site_root: pathlib.Path,
    request_id: str,
    *,
    actor: dict,
    review_note: str | None = None,
) -> dict:
    """Issuer: send issued/rejected request back to pending (delete stored PDF if any)."""
    ensure_no_dues_requests_table(conn)
    row = conn.execute("SELECT * FROM no_dues_requests WHERE id = ?", (request_id,)).fetchone()
    if not row:
        raise ValueError("Request not found")
    status = row["status"] or ""
    if status not in ("issued", "rejected"):
        raise ValueError("Only issued or rejected requests can be reverted")

    filename = row["filename"] or ""
    if filename:
        try:
            path = certificate_path(site_root, row["house_id"], request_id, filename)
            if path.is_file():
                path.unlink()
            parent = path.parent
            if parent.is_dir() and not any(parent.iterdir()):
                parent.rmdir()
        except ValueError:
            pass

    now = utc_now()
    conn.execute(
        """
        UPDATE no_dues_requests
        SET status = 'requested',
            reviewed_by_house_id = ?,
            reviewed_at = ?,
            review_note = ?,
            issued_at = NULL,
            filename = NULL,
            original_name = NULL,
            treasury_status = 'pending',
            treasury_validated_by = NULL,
            treasury_validated_at = NULL,
            treasury_confirmed_by = NULL,
            treasury_confirmed_at = NULL,
            treasury_note = NULL,
            updated_at = ?
        WHERE id = ?
        """,
        (
            actor.get("houseId") or actor.get("house_id"),
            now,
            (review_note or "").strip()[:500] or "Reverted to pending",
            now,
            request_id,
        ),
    )
    conn.commit()
    out = get_request(conn, request_id)
    if not out:
        raise ValueError("Request not found after revert")
    return out
