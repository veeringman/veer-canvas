"""Household tenants: occupancy records per plot, separate from household logins."""

from __future__ import annotations

import re
import secrets
import sqlite3
from typing import Any

from init_rwa_db import SUPERADMIN_HOUSE_ID, ensure_household_tenants_table, utc_now
import rwa_household

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def public_tenant(row: sqlite3.Row | dict | None) -> dict[str, Any]:
    if not row:
        return {}
    data = dict(row) if not isinstance(row, dict) else row
    if hasattr(row, "keys") and not isinstance(row, dict):
        data = {k: row[k] for k in row.keys()}
    start = data.get("occupancy_start") or ""
    end = data.get("occupancy_end") or ""
    return {
        "id": data.get("id"),
        "houseId": data.get("house_id") or "",
        "name": data.get("name") or "",
        "phone": data.get("phone") or "",
        "email": data.get("email") or "",
        "note": data.get("id_note") or "",
        "occupancyStart": start,
        "occupancyEnd": end,
        "status": data.get("status") or "active",
        "createdByName": data.get("created_by_name") or "",
        "createdAt": data.get("created_at") or "",
        "updatedAt": data.get("updated_at") or "",
    }


def get_tenant(conn: sqlite3.Connection, tenant_id: str) -> dict[str, Any] | None:
    ensure_household_tenants_table(conn)
    tid = (tenant_id or "").strip()
    if not tid:
        return None
    row = conn.execute("SELECT * FROM household_tenants WHERE id = ?", (tid,)).fetchone()
    return public_tenant(row) if row else None


def list_tenants(
    conn: sqlite3.Connection,
    house_id: str,
    *,
    include_ended: bool = False,
) -> list[dict[str, Any]]:
    ensure_household_tenants_table(conn)
    hid = (house_id or "").strip()
    if not hid:
        return []
    if include_ended:
        rows = conn.execute(
            """
            SELECT * FROM household_tenants
            WHERE house_id = ?
            ORDER BY CASE status WHEN 'active' THEN 0 ELSE 1 END, created_at DESC
            """,
            (hid,),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT * FROM household_tenants
            WHERE house_id = ? AND status = 'active'
            ORDER BY name COLLATE NOCASE
            """,
            (hid,),
        ).fetchall()
    return [public_tenant(r) for r in rows]


def list_tenants_for_report(
    conn: sqlite3.Connection,
    *,
    status: str | None = None,
    house_ids: list[str] | None = None,
    limit: int = 3000,
) -> list[dict[str, Any]]:
    """Colony-wide tenant occupancy rows for EC reports."""
    ensure_household_tenants_table(conn)
    lim = max(1, min(int(limit or 3000), 5000))
    clauses: list[str] = []
    args: list[Any] = []
    st = (status or "all").strip().lower()
    if st and st != "all":
        clauses.append("t.status = ?")
        args.append(st)
    ids = [str(h).strip() for h in (house_ids or []) if str(h).strip()]
    if ids:
        clauses.append(f"t.house_id IN ({','.join('?' for _ in ids)})")
        args.extend(ids)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    rows = conn.execute(
        f"""
        SELECT t.*, COALESCE(r.plot_no, t.house_id) AS plot_no
        FROM household_tenants t
        LEFT JOIN residents r ON r.house_id = t.house_id
        {where}
        ORDER BY
          CASE t.status WHEN 'active' THEN 0 ELSE 1 END,
          COALESCE(r.plot_no, t.house_id) COLLATE NOCASE,
          t.name COLLATE NOCASE
        LIMIT ?
        """,
        (*args, lim),
    ).fetchall()
    out = []
    for row in rows:
        item = public_tenant(row)
        data = dict(row)
        item["plotNo"] = data.get("plot_no") or item.get("houseId") or ""
        out.append(item)
    return out


def _require_manage(actor: dict | None, house_id: str) -> None:
    if not rwa_household.can_actor_manage_household(actor, house_id):
        raise PermissionError("Only the owner (or EC) can manage tenants for this plot")


def add_tenant(
    conn: sqlite3.Connection,
    house_id: str,
    payload: dict,
    *,
    actor: dict | None = None,
) -> dict[str, Any]:
    ensure_household_tenants_table(conn)
    hid = (house_id or "").strip()
    if not hid or hid == SUPERADMIN_HOUSE_ID:
        raise ValueError("Invalid plot")
    _require_manage(actor, hid)
    name = re.sub(r"\s+", " ", str(payload.get("name") or "").strip())[:120]
    if not name:
        raise ValueError("Tenant name is required")
    phone = rwa_household.normalize_phone(payload.get("phone") or payload.get("tenantPhone"))
    if not phone or len(re.sub(r"\D", "", phone)) < 10:
        raise ValueError("Tenant mobile number is required")
    email_raw = str(payload.get("email") or "").strip().lower()
    email = rwa_household.validate_email(email_raw) if email_raw else ""
    note = re.sub(r"\s+", " ", str(payload.get("note") or payload.get("idNote") or "").strip())[:240]
    start = str(payload.get("occupancyStart") or payload.get("from") or "").strip()[:10]
    end = str(payload.get("occupancyEnd") or payload.get("until") or "").strip()[:10]
    tid = "ht_" + secrets.token_hex(8)
    now = utc_now()
    conn.execute(
        """
        INSERT INTO household_tenants(
          id, house_id, name, phone, email, id_note, occupancy_start, occupancy_end,
          status, created_by_member_id, created_by_name, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?)
        """,
        (
            tid,
            hid,
            name,
            phone,
            email,
            note,
            start,
            end,
            (actor or {}).get("memberId") or "",
            (actor or {}).get("name") or "",
            now,
            now,
        ),
    )
    conn.commit()
    out = get_tenant(conn, tid)
    if not out:
        raise ValueError("Tenant could not be loaded after save")
    return out


def update_tenant(
    conn: sqlite3.Connection,
    house_id: str,
    tenant_id: str,
    payload: dict,
    *,
    actor: dict | None = None,
) -> dict[str, Any]:
    ensure_household_tenants_table(conn)
    hid = (house_id or "").strip()
    _require_manage(actor, hid)
    item = get_tenant(conn, tenant_id)
    if not item or item.get("houseId") != hid:
        raise ValueError("Tenant not found on this plot")
    name = item["name"]
    if "name" in payload:
        name = re.sub(r"\s+", " ", str(payload.get("name") or "").strip())[:120]
        if not name:
            raise ValueError("Tenant name is required")
    phone = item["phone"]
    if "phone" in payload:
        phone = rwa_household.normalize_phone(payload.get("phone")) or ""
        if not phone or len(re.sub(r"\D", "", phone)) < 10:
            raise ValueError("Tenant mobile number is required")
    email = item["email"]
    if "email" in payload:
        email_raw = str(payload.get("email") or "").strip().lower()
        email = rwa_household.validate_email(email_raw) if email_raw else ""
    note = item["note"]
    if "note" in payload or "idNote" in payload:
        note = re.sub(r"\s+", " ", str(payload.get("note") or payload.get("idNote") or "").strip())[:240]
    start = item["occupancyStart"]
    if "occupancyStart" in payload or "from" in payload:
        start = str(payload.get("occupancyStart") or payload.get("from") or "").strip()[:10]
    end = item["occupancyEnd"]
    if "occupancyEnd" in payload or "until" in payload:
        end = str(payload.get("occupancyEnd") or payload.get("until") or "").strip()[:10]
    status = item["status"]
    if payload.get("status") in ("active", "ended") or payload.get("endOccupancy"):
        status = "ended" if payload.get("endOccupancy") or payload.get("status") == "ended" else "active"
        if status == "ended" and not end:
            end = now_date()
    now = utc_now()
    conn.execute(
        """
        UPDATE household_tenants
        SET name = ?, phone = ?, email = ?, id_note = ?, occupancy_start = ?, occupancy_end = ?,
            status = ?, updated_at = ?
        WHERE id = ?
        """,
        (name, phone, email, note, start, end, status, now, tenant_id),
    )
    conn.commit()
    out = get_tenant(conn, tenant_id)
    if not out:
        raise ValueError("Tenant not found after update")
    return out


def now_date() -> str:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    return datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%Y-%m-%d")


def end_tenant(
    conn: sqlite3.Connection,
    house_id: str,
    tenant_id: str,
    *,
    actor: dict | None = None,
) -> dict[str, Any]:
    return update_tenant(
        conn,
        house_id,
        tenant_id,
        {"endOccupancy": True},
        actor=actor,
    )
