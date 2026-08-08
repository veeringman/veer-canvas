"""No Objection Certificate requests: resident request → issuer issue → resident download."""

from __future__ import annotations

import pathlib
import re
import secrets
import sqlite3
from typing import Any

from init_rwa_db import ensure_no_objection_requests_table, utc_now
import rwa_reports

STATUS_LABELS = {
    "requested": "Requested",
    "issued": "Issued",
    "rejected": "Rejected",
}

DEFAULT_PURPOSE = "Property transfer / sale / mortgage / official purposes"


def normalize_purpose(raw: str | None) -> str:
    text = (raw or "").strip()[:400]
    return text or DEFAULT_PURPOSE


def no_objection_root(site_root: pathlib.Path) -> pathlib.Path:
    path = pathlib.Path(site_root) / "data" / "no-objection"
    path.mkdir(parents=True, exist_ok=True)
    return path


def certificate_path(site_root: pathlib.Path, house_id: str, request_id: str, filename: str) -> pathlib.Path:
    safe_house = re.sub(r"[^A-Za-z0-9_-]", "_", (house_id or "").strip()) or "_"
    safe_id = re.sub(r"[^A-Za-z0-9_-]", "_", (request_id or "").strip()) or "_"
    safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", (filename or "").strip()) or "certificate.pdf"
    if ".." in safe_name or "/" in safe_name or "\\" in safe_name:
        raise ValueError("Invalid filename")
    base = (no_objection_root(site_root) / safe_house / safe_id).resolve()
    path = (base / safe_name).resolve()
    if not str(path).startswith(str(base)):
        raise ValueError("Invalid path")
    return path


def house_plot_finance(
    conn: sqlite3.Connection,
    house_id: str,
    *,
    enrich_payment_row=None,
) -> dict:
    """Dues + ledger treasury snapshot for the plot (issuer context on a NOC request)."""
    import rwa_treasury

    hid = (house_id or "").strip()
    empty = {
        "houseId": hid,
        "outstanding": None,
        "pendingReceipts": 0,
        "duesClear": None,
        "ledgerTreasuryStatus": "pending",
        "ledgerTreasuryStatusLabel": "Treasury pending",
        "asOf": "",
        "summary": "No ledger row for this plot yet",
    }
    if not hid:
        return empty
    if enrich_payment_row is None:
        try:
            from rwa_portal import enrich_payment_row as enrich_payment_row  # type: ignore
        except ImportError:
            return empty
    try:
        info = rwa_reports.no_dues_eligibility(conn, hid, enrich_payment_row=enrich_payment_row)
    except ValueError as exc:
        empty["summary"] = str(exc)
        return empty
    payment = info.get("payment") or {}
    ledger_t = rwa_treasury.treasury_fields_from_row(payment)
    outstanding = int(info.get("outstanding") or 0)
    pending_receipts = int(info.get("pendingReceipts") or 0)
    dues_clear = bool(info.get("eligible"))
    if dues_clear:
        summary = "Dues clear"
    elif outstanding > 0:
        summary = f"Outstanding dues ₹{outstanding}"
    else:
        summary = f"{pending_receipts} payment receipt(s) awaiting EC verification"
    lst = ledger_t.get("treasuryStatus") or "pending"
    return {
        "houseId": hid,
        "plotNo": info.get("plotNo") or hid,
        "outstanding": outstanding,
        "pendingReceipts": pending_receipts,
        "duesClear": dues_clear,
        "ledgerTreasuryStatus": lst,
        "ledgerTreasuryStatusLabel": ledger_t.get("treasuryStatusLabel")
        or rwa_treasury.TREASURY_STATUS_LABELS.get(lst, lst),
        "asOf": payment.get("asOf") or payment.get("as_of") or "",
        "summary": summary,
    }


def public_request(
    _conn: sqlite3.Connection,
    row: Any,
    *,
    plot_finance: dict | None = None,
) -> dict:
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
        "purpose": normalize_purpose(data.get("purpose")),
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
            f"/api/rwa/no-objection-requests/{rid}/download" if can_download else None
        ),
        "downloadLocked": bool(st == "issued" and rid and not can_download),
    }
    out["sentBack"] = bool(
        st == "requested" and (out["reviewedAt"] or out["reviewNote"])
    )
    out["canEditPurpose"] = bool(out["sentBack"])
    out.update(treasury)
    if plot_finance is not None:
        out["plotFinance"] = plot_finance
    return out


def update_purpose(
    conn: sqlite3.Connection,
    request_id: str,
    *,
    actor: dict,
    purpose: str | None,
) -> dict:
    """Requester may change purpose only when the request was sent back."""
    ensure_no_objection_requests_table(conn)
    item = get_request(conn, request_id)
    if not item:
        raise ValueError("Request not found")
    own = (actor.get("houseId") or actor.get("house_id") or "") == (item.get("houseId") or "")
    if not own and not actor.get("superAdmin"):
        raise PermissionError("Only the requester can update purpose")
    if not item.get("canEditPurpose"):
        raise PermissionError(
            "Purpose is locked after request. You can change it only if the issuer sends it back."
        )
    now = utc_now()
    conn.execute(
        """
        UPDATE no_objection_requests
        SET purpose = ?, updated_at = ?
        WHERE id = ?
        """,
        (normalize_purpose(purpose), now, request_id),
    )
    conn.commit()
    out = get_request(conn, request_id)
    if not out:
        raise ValueError("Request not found after update")
    return out


def get_request(
    conn: sqlite3.Connection,
    request_id: str,
    *,
    include_plot_finance: bool = False,
    enrich_payment_row=None,
) -> dict | None:
    ensure_no_objection_requests_table(conn)
    rid = (request_id or "").strip()
    if not rid:
        return None
    row = conn.execute(
        """
        SELECT nr.*, r.plot_no, r.name
        FROM no_objection_requests nr
        LEFT JOIN residents r ON r.house_id = nr.house_id
        WHERE nr.id = ?
        """,
        (rid,),
    ).fetchone()
    if not row:
        return None
    finance = None
    if include_plot_finance:
        finance = house_plot_finance(
            conn, row["house_id"], enrich_payment_row=enrich_payment_row
        )
    return public_request(conn, row, plot_finance=finance)


def list_requests(
    conn: sqlite3.Connection,
    *,
    house_id: str | None = None,
    status: str | None = None,
    limit: int = 100,
    include_plot_finance: bool = False,
    enrich_payment_row=None,
) -> list[dict]:
    ensure_no_objection_requests_table(conn)
    clauses: list[str] = []
    params: list[Any] = []
    if house_id:
        clauses.append("nr.house_id = ?")
        params.append(house_id.strip())
    if status and status != "all":
        clauses.append("nr.status = ?")
        params.append(status.strip())
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    lim = max(1, min(int(limit or 100), 500))
    rows = conn.execute(
        f"""
        SELECT nr.*, r.plot_no, r.name
        FROM no_objection_requests nr
        LEFT JOIN residents r ON r.house_id = nr.house_id
        {where}
        ORDER BY
          CASE nr.status WHEN 'requested' THEN 0 WHEN 'issued' THEN 1 ELSE 2 END,
          nr.created_at DESC
        LIMIT ?
        """,
        (*params, lim),
    ).fetchall()
    cache: dict[str, dict] = {}
    out: list[dict] = []
    for r in rows:
        finance = None
        if include_plot_finance:
            hid = r["house_id"]
            if hid not in cache:
                cache[hid] = house_plot_finance(
                    conn, hid, enrich_payment_row=enrich_payment_row
                )
            finance = cache[hid]
        out.append(public_request(conn, r, plot_finance=finance))
    return out


def create_request(
    conn: sqlite3.Connection,
    *,
    house_id: str,
    actor: dict,
    note: str | None = None,
    purpose: str | None = None,
) -> dict:
    ensure_no_objection_requests_table(conn)
    hid = (house_id or "").strip()
    if not hid:
        raise ValueError("Plot required")
    info = rwa_reports.no_objection_eligibility(conn, hid)
    if not info.get("eligible"):
        raise ValueError(info.get("reason") or "Plot is not eligible for a No Objection Certificate")

    open_row = conn.execute(
        """
        SELECT id FROM no_objection_requests
        WHERE house_id = ? AND status = 'requested'
        LIMIT 1
        """,
        (hid,),
    ).fetchone()
    if open_row:
        raise ValueError("A No Objection Certificate request is already pending for this plot")

    rid = f"noc_{secrets.token_hex(8)}"
    now = utc_now()
    purpose_text = normalize_purpose(purpose)
    conn.execute(
        """
        INSERT INTO no_objection_requests(
          id, house_id, status, request_note, purpose,
          requested_by_house_id, requested_by_member_id,
          created_at, updated_at
        ) VALUES (?, ?, 'requested', ?, ?, ?, ?, ?, ?)
        """,
        (
            rid,
            hid,
            (note or "").strip()[:500] or None,
            purpose_text,
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
    ensure_no_objection_requests_table(conn)
    import rwa_treasury

    note = rwa_treasury.require_rejection_reason(review_note)
    row = conn.execute("SELECT * FROM no_objection_requests WHERE id = ?", (request_id,)).fetchone()
    if not row:
        raise ValueError("Request not found")
    if row["status"] != "requested":
        raise ValueError("Only pending requests can be rejected")
    now = utc_now()
    conn.execute(
        """
        UPDATE no_objection_requests
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
            note,
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
    review_note: str | None = None,
    public_base: str | None = None,
) -> dict:
    """Generate PDF, store on disk, mark request issued."""
    ensure_no_objection_requests_table(conn)
    row = conn.execute("SELECT * FROM no_objection_requests WHERE id = ?", (request_id,)).fetchone()
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
    pdf_bytes, download_name = rwa_reports.build_no_objection_certificate_pdf(
        conn,
        site_root=site_root,
        house_id=row["house_id"],
        issued_by=issuer_name,
        purpose=normalize_purpose(row["purpose"] if row["purpose"] is not None else ""),
        letterhead=True,
        attestation_id=att_id,
        verify_url=verify_url,
    )
    filename = f"no-objection-{secrets.token_hex(4)}.pdf"
    dest = certificate_path(site_root, row["house_id"], request_id, filename)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(pdf_bytes)
    stored_rel = rwa_attest.safe_rel_path(site_root, dest)

    import rwa_treasury

    treas_sql, treas_vals = rwa_treasury.certificate_issue_treasury_sql(
        conn, row["house_id"], actor=actor, now=now
    )
    conn.execute(
        f"""
        UPDATE no_objection_requests
        SET status = 'issued',
            reviewed_by_house_id = ?,
            reviewed_at = ?,
            review_note = ?,
            issued_at = ?,
            filename = ?,
            original_name = ?,
            {treas_sql}
        WHERE id = ?
        """,
        (
            issuer_house,
            now,
            (review_note or "").strip()[:500] or None,
            now,
            filename,
            download_name,
            *treas_vals,
            request_id,
        ),
    )
    rwa_attest.record_attestation(
        conn,
        site_root,
        attestation_id=att_id,
        artifact_type="no_objection",
        artifact_id=request_id,
        house_id=row["house_id"],
        issuer_house_id=issuer_house,
        issued_at=now,
        pdf_bytes=pdf_bytes,
        stored_path=stored_rel,
        filename=download_name,
        commit=True,
    )
    try:
        import rwa_vault

        rwa_vault.index_no_objection_certificate(
            conn,
            site_root,
            house_id=row["house_id"],
            request_id=request_id,
            filename=filename,
            original_name=download_name,
            attestation_id=att_id,
            uploaded_by_house_id=issuer_house,
            commit=True,
        )
    except Exception:
        pass
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
    note: str | None = None,
    public_base: str | None = None,
) -> dict:
    """Issuer: issue pending request for plot, or create+issue when none pending."""
    hid = (house_id or "").strip()
    if not hid:
        raise ValueError("Plot required")
    pending = conn.execute(
        """
        SELECT id FROM no_objection_requests
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
            review_note=note,
            public_base=public_base,
        )

    ensure_no_objection_requests_table(conn)
    info = rwa_reports.no_objection_eligibility(conn, hid)
    if not info.get("eligible"):
        raise ValueError(info.get("reason") or "Plot is not eligible")
    rid = f"noc_{secrets.token_hex(8)}"
    now = utc_now()
    conn.execute(
        """
        INSERT INTO no_objection_requests(
          id, house_id, status, request_note, purpose,
          requested_by_house_id, requested_by_member_id,
          created_at, updated_at
        ) VALUES (?, ?, 'requested', ?, ?, ?, ?, ?, ?)
        """,
        (
            rid,
            hid,
            (note or "").strip()[:500] or "Issued by No Objection Issuer",
            DEFAULT_PURPOSE,
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
        review_note=note,
        public_base=public_base,
    )


def build_download_pdf(
    conn: sqlite3.Connection,
    site_root: pathlib.Path,
    request_id: str,
    *,
    variant: str = "digital",
    public_base: str | None = None,
) -> tuple[bytes, str]:
    """Return PDF bytes for download. digital = stored file; print = no letterhead, wider margins."""
    item = get_request(conn, request_id)
    if not item:
        raise ValueError("Request not found")
    if item["status"] != "issued" or not item.get("filename"):
        raise ValueError("Certificate not issued yet")
    if item.get("treasuryStatus") != "confirmed":
        raise PermissionError("Treasury confirmation required before download")

    kind = (variant or "digital").strip().lower()
    if kind in ("digital", "letterhead", "with_letterhead"):
        path = certificate_path(site_root, item["houseId"], item["id"], item["filename"])
        if not path.is_file():
            raise FileNotFoundError("Certificate file missing")
        name = item.get("originalName") or f"no-objection-{item.get('plotNo') or item['houseId']}.pdf"
        return path.read_bytes(), name

    if kind not in ("print", "paper", "no_letterhead", "blank"):
        raise ValueError("Invalid download variant (use digital or print)")

    row = conn.execute(
        "SELECT * FROM no_objection_requests WHERE id = ?",
        (request_id,),
    ).fetchone()
    issuer_name = None
    issuer_house = (row["reviewed_by_house_id"] if row else None) or ""
    if issuer_house:
        r = conn.execute(
            "SELECT name FROM residents WHERE house_id = ?",
            (issuer_house,),
        ).fetchone()
        if r and r["name"]:
            issuer_name = r["name"]

    att_id = None
    verify_url = None
    try:
        import rwa_attest

        att = conn.execute(
            """
            SELECT id FROM document_attestations
            WHERE artifact_type = 'no_objection' AND artifact_id = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (request_id,),
        ).fetchone()
        if att:
            att_id = att["id"]
            verify_url = rwa_attest.verify_url_for(site_root, att_id, public_base=public_base)
    except Exception:
        pass

    pdf_bytes, download_name = rwa_reports.build_no_objection_certificate_pdf(
        conn,
        site_root=site_root,
        house_id=item["houseId"],
        issued_by=issuer_name,
        purpose=item.get("purpose") or DEFAULT_PURPOSE,
        letterhead=False,
        require_eligible=False,
        attestation_id=att_id,
        verify_url=verify_url,
    )
    base = download_name.rsplit(".", 1)[0]
    return pdf_bytes, f"{base}-print.pdf"


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
    ensure_no_objection_requests_table(conn)
    row = conn.execute("SELECT * FROM no_objection_requests WHERE id = ?", (request_id,)).fetchone()
    if not row:
        raise ValueError("Request not found")
    if row["status"] != "requested":
        raise ValueError("Only pending requests can be cancelled")
    own = (actor.get("houseId") or actor.get("house_id") or "") == (row["house_id"] or "")
    if not own and not can_issue and not actor.get("superAdmin"):
        raise ValueError("Not allowed to cancel this request")
    conn.execute("DELETE FROM no_objection_requests WHERE id = ?", (request_id,))
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
    ensure_no_objection_requests_table(conn)
    row = conn.execute("SELECT * FROM no_objection_requests WHERE id = ?", (request_id,)).fetchone()
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
        UPDATE no_objection_requests
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
