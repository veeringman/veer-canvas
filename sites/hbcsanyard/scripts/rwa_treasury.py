"""Treasury validation and confirmation for financial artifacts.

Status flow: pending → validated → confirmed (final).
Ledger amounts may already reflect EC-verified payments; treasury status is the
audit seal. No Dues PDF download requires confirmed.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from init_rwa_db import ensure_treasury_columns, utc_now
import rwa_entitlements
import rwa_no_dues
import rwa_payments

TREASURY_STATUSES = ("pending", "validated", "confirmed")
TREASURY_STATUS_LABELS = {
    "pending": "Pending Treasury",
    "validated": "Treasury validated",
    "confirmed": "Treasury confirmed",
}

KINDS = ("payment", "ledger", "no_dues")


def _actor_house(actor: dict | None) -> str:
    if not actor:
        return ""
    return str(actor.get("houseId") or actor.get("house_id") or "")


def require_treasury(actor: dict | None) -> None:
    if not rwa_entitlements.actor_has(actor, "treasury"):
        raise PermissionError("Treasury entitlement required")


def treasury_fields_from_row(data: dict | sqlite3.Row | None) -> dict:
    if not data:
        return {
            "treasuryStatus": "pending",
            "treasuryStatusLabel": TREASURY_STATUS_LABELS["pending"],
            "treasuryValidatedBy": "",
            "treasuryValidatedAt": "",
            "treasuryConfirmedBy": "",
            "treasuryConfirmedAt": "",
            "treasuryNote": "",
        }
    if hasattr(data, "keys") and not isinstance(data, dict):
        raw = {k: data[k] for k in data.keys()}
    else:
        raw = dict(data)
    st = (raw.get("treasury_status") or raw.get("treasuryStatus") or "pending").strip()
    if st not in TREASURY_STATUSES:
        st = "pending"
    return {
        "treasuryStatus": st,
        "treasuryStatusLabel": TREASURY_STATUS_LABELS.get(st, st),
        "treasuryValidatedBy": raw.get("treasury_validated_by") or raw.get("treasuryValidatedBy") or "",
        "treasuryValidatedAt": raw.get("treasury_validated_at") or raw.get("treasuryValidatedAt") or "",
        "treasuryConfirmedBy": raw.get("treasury_confirmed_by") or raw.get("treasuryConfirmedBy") or "",
        "treasuryConfirmedAt": raw.get("treasury_confirmed_at") or raw.get("treasuryConfirmedAt") or "",
        "treasuryNote": raw.get("treasury_note") or raw.get("treasuryNote") or "",
    }


def reset_treasury_sql_fragment() -> str:
    """SET clause fragment to clear treasury stamps back to pending."""
    return """
        treasury_status = 'pending',
        treasury_validated_by = NULL,
        treasury_validated_at = NULL,
        treasury_confirmed_by = NULL,
        treasury_confirmed_at = NULL
    """


def mark_ledger_row_pending(conn: sqlite3.Connection, house_id: str, *, commit: bool = False) -> None:
    """After EC verify or manual edit — ledger shows amounts but needs treasury again."""
    ensure_treasury_columns(conn)
    hid = (house_id or "").strip()
    if not hid:
        return
    ledger = conn.execute(
        "SELECT id FROM payment_ledgers ORDER BY as_of DESC, id DESC LIMIT 1"
    ).fetchone()
    if not ledger:
        return
    conn.execute(
        f"""
        UPDATE payment_rows
        SET {reset_treasury_sql_fragment()},
            treasury_note = NULL
        WHERE ledger_id = ? AND house_id = ?
        """,
        (ledger["id"], hid),
    )
    if commit:
        conn.commit()


def _load_target(conn: sqlite3.Connection, kind: str, target_id: str) -> tuple[str, str, dict]:
    """Return (table, id_for_where, public_dict)."""
    ensure_treasury_columns(conn)
    kid = (kind or "").strip()
    tid = (target_id or "").strip()
    if kid not in KINDS:
        raise ValueError("Invalid treasury kind")
    if not tid:
        raise ValueError("Target id required")

    if kid == "payment":
        row = conn.execute("SELECT * FROM payment_records WHERE id = ?", (tid,)).fetchone()
        if not row:
            raise ValueError("Payment record not found")
        pub = rwa_payments.get_record(conn, tid) or {}
        return "payment_records", tid, pub

    if kid == "ledger":
        ledger = conn.execute(
            "SELECT id FROM payment_ledgers ORDER BY as_of DESC, id DESC LIMIT 1"
        ).fetchone()
        if not ledger:
            raise ValueError("No payment ledger loaded yet")
        row = conn.execute(
            "SELECT * FROM payment_rows WHERE ledger_id = ? AND house_id = ?",
            (ledger["id"], tid),
        ).fetchone()
        if not row:
            raise ValueError(f"No ledger row for plot {tid}")
        pub = {
            "houseId": tid,
            "kind": "ledger",
            **treasury_fields_from_row(row),
        }
        return "payment_rows", tid, pub

    row = conn.execute("SELECT * FROM no_dues_requests WHERE id = ?", (tid,)).fetchone()
    if not row:
        raise ValueError("No Dues request not found")
    if (row["status"] or "") != "issued":
        raise ValueError("Only issued No Dues certificates can be treasury-reviewed")
    pub = rwa_no_dues.get_request(conn, tid) or {}
    return "no_dues_requests", tid, pub


def _current_status(conn: sqlite3.Connection, table: str, tid: str) -> str:
    if table == "payment_rows":
        ledger = conn.execute(
            "SELECT id FROM payment_ledgers ORDER BY as_of DESC, id DESC LIMIT 1"
        ).fetchone()
        row = conn.execute(
            "SELECT treasury_status FROM payment_rows WHERE ledger_id = ? AND house_id = ?",
            (ledger["id"], tid),
        ).fetchone()
    else:
        row = conn.execute(
            f"SELECT treasury_status FROM {table} WHERE id = ?",
            (tid,),
        ).fetchone()
    if not row:
        return "pending"
    st = (row["treasury_status"] if hasattr(row, "keys") else row[0]) or "pending"
    return st if st in TREASURY_STATUSES else "pending"


def _reload_public(conn: sqlite3.Connection, kind: str, tid: str) -> dict:
    if kind == "payment":
        out = rwa_payments.get_record(conn, tid)
        if not out:
            raise ValueError("Payment record not found after update")
        return out
    if kind == "no_dues":
        out = rwa_no_dues.get_request(conn, tid)
        if not out:
            raise ValueError("No Dues request not found after update")
        return out
    ledger = conn.execute(
        "SELECT id FROM payment_ledgers ORDER BY as_of DESC, id DESC LIMIT 1"
    ).fetchone()
    row = conn.execute(
        """
        SELECT pr.*, r.name, r.section, r.plot_no, pl.as_of, pl.source
        FROM payment_rows pr
        JOIN residents r ON r.house_id = pr.house_id
        JOIN payment_ledgers pl ON pl.id = pr.ledger_id
        WHERE pr.ledger_id = ? AND pr.house_id = ?
        """,
        (ledger["id"], tid),
    ).fetchone()
    if not row:
        raise ValueError("Ledger row not found after update")
    try:
        import rwa_portal  # type: ignore

        base = rwa_portal.enrich_payment_row(row)
    except Exception:
        base = {"houseId": tid}
    base.update(treasury_fields_from_row(row))
    base["name"] = row["name"] if "name" in row.keys() else ""
    base["section"] = row["section"] if "section" in row.keys() else ""
    base["plotNo"] = row["plot_no"] if "plot_no" in row.keys() else tid
    return base


def _apply(
    conn: sqlite3.Connection,
    *,
    table: str,
    kind: str,
    tid: str,
    actor: dict,
    note: str | None,
    action: str,
) -> dict:
    ensure_treasury_columns(conn)
    house = _actor_house(actor)
    now = utc_now()
    note_clean = (note or "").strip()[:500] or None

    if table == "payment_rows":
        ledger = conn.execute(
            "SELECT id FROM payment_ledgers ORDER BY as_of DESC, id DESC LIMIT 1"
        ).fetchone()
        where = "ledger_id = ? AND house_id = ?"
        where_params: tuple[Any, ...] = (ledger["id"], tid)
    else:
        where = "id = ?"
        where_params = (tid,)

    if action == "validate":
        sets = """
            treasury_status = 'validated',
            treasury_validated_by = ?,
            treasury_validated_at = ?,
            treasury_confirmed_by = NULL,
            treasury_confirmed_at = NULL,
            treasury_note = COALESCE(?, treasury_note)
        """
        params: list[Any] = [house, now, note_clean]
    elif action == "confirm":
        sets = """
            treasury_status = 'confirmed',
            treasury_confirmed_by = ?,
            treasury_confirmed_at = ?,
            treasury_note = COALESCE(?, treasury_note)
        """
        params = [house, now, note_clean]
    else:
        sets = f"""
            {reset_treasury_sql_fragment()},
            treasury_note = ?
        """
        params = [note_clean or "Reverted by Treasury"]

    if table != "payment_rows":
        sets = sets + ", updated_at = ?"
        params.append(now)

    conn.execute(
        f"UPDATE {table} SET {sets} WHERE {where}",
        (*params, *where_params),
    )
    conn.commit()
    return _reload_public(conn, kind, tid)


def validate(
    conn: sqlite3.Connection,
    kind: str,
    target_id: str,
    *,
    actor: dict,
    note: str | None = None,
) -> dict:
    require_treasury(actor)
    table, tid, _ = _load_target(conn, kind, target_id)
    st = _current_status(conn, table, tid)
    if st != "pending":
        raise ValueError("Only pending items can be validated")
    return _apply(conn, table=table, kind=kind, tid=tid, actor=actor, note=note, action="validate")


def confirm(
    conn: sqlite3.Connection,
    kind: str,
    target_id: str,
    *,
    actor: dict,
    note: str | None = None,
) -> dict:
    require_treasury(actor)
    table, tid, _ = _load_target(conn, kind, target_id)
    st = _current_status(conn, table, tid)
    if st != "validated":
        raise ValueError("Validate before confirming")
    return _apply(conn, table=table, kind=kind, tid=tid, actor=actor, note=note, action="confirm")


def revert(
    conn: sqlite3.Connection,
    kind: str,
    target_id: str,
    *,
    actor: dict,
    note: str | None = None,
) -> dict:
    require_treasury(actor)
    table, tid, _ = _load_target(conn, kind, target_id)
    st = _current_status(conn, table, tid)
    if st not in ("validated", "confirmed"):
        raise ValueError("Only validated or confirmed items can be reverted")
    return _apply(conn, table=table, kind=kind, tid=tid, actor=actor, note=note, action="revert")


def list_queue(
    conn: sqlite3.Connection,
    *,
    kind: str | None = None,
    status: str | None = None,
    limit: int = 100,
) -> dict[str, list[dict]]:
    """Items needing treasury attention (and optionally confirmed for review)."""
    ensure_treasury_columns(conn)
    lim = max(1, min(int(limit or 100), 300))
    st_filter = (status or "attention").strip()
    kind_filter = (kind or "all").strip()

    def status_clause(alias: str = "") -> tuple[str, list[Any]]:
        col = f"{alias}treasury_status" if alias else "treasury_status"
        if st_filter in ("pending", "validated", "confirmed"):
            return f"{col} = ?", [st_filter]
        if st_filter == "attention":
            return f"{col} IN ('pending','validated')", []
        return "1=1", []

    out: dict[str, list[dict]] = {"payments": [], "ledger": [], "noDues": []}

    if kind_filter in ("all", "payment", "payments"):
        clause, params = status_clause("pr.")
        rows = conn.execute(
            f"""
            SELECT pr.*, r.plot_no, r.name
            FROM payment_records pr
            LEFT JOIN residents r ON r.house_id = pr.house_id
            WHERE pr.status IN ('verified','reimbursed')
              AND {clause}
            ORDER BY
              CASE pr.treasury_status WHEN 'pending' THEN 0 WHEN 'validated' THEN 1 ELSE 2 END,
              pr.updated_at DESC
            LIMIT ?
            """,
            (*params, lim),
        ).fetchall()
        out["payments"] = [rwa_payments.public_record(conn, r) for r in rows]

    if kind_filter in ("all", "ledger"):
        clause, params = status_clause("pr.")
        ledger = conn.execute(
            "SELECT id FROM payment_ledgers ORDER BY as_of DESC, id DESC LIMIT 1"
        ).fetchone()
        if ledger:
            rows = conn.execute(
                f"""
                SELECT pr.*, r.name, r.section, r.plot_no, pl.as_of, pl.source
                FROM payment_rows pr
                JOIN residents r ON r.house_id = pr.house_id
                JOIN payment_ledgers pl ON pl.id = pr.ledger_id
                WHERE pr.ledger_id = ?
                  AND {clause}
                ORDER BY
                  CASE pr.treasury_status WHEN 'pending' THEN 0 WHEN 'validated' THEN 1 ELSE 2 END,
                  r.section,
                  r.plot_no
                LIMIT ?
                """,
                (ledger["id"], *params, lim),
            ).fetchall()
            try:
                import rwa_portal  # type: ignore
                from init_rwa_db import section_plot_sort_key

                items = []
                for r in rows:
                    item = rwa_portal.enrich_payment_row(r)
                    item.update(treasury_fields_from_row(r))
                    item["name"] = r["name"] or ""
                    item["section"] = r["section"] or ""
                    item["plotNo"] = r["plot_no"] or item.get("houseId")
                    items.append(item)
                items.sort(
                    key=lambda row: (
                        {"pending": 0, "validated": 1, "confirmed": 2}.get(
                            row.get("treasuryStatus") or "pending", 9
                        ),
                        *section_plot_sort_key(
                            row.get("section"),
                            row.get("plotNo") or row.get("houseId"),
                            row.get("houseId"),
                        ),
                    )
                )
                out["ledger"] = items
            except Exception:
                out["ledger"] = [
                    {"houseId": r["house_id"], **treasury_fields_from_row(r)} for r in rows
                ]

    if kind_filter in ("all", "no_dues", "noDues"):
        clause, params = status_clause("nd.")
        rows = conn.execute(
            f"""
            SELECT nd.*, r.plot_no, r.name
            FROM no_dues_requests nd
            LEFT JOIN residents r ON r.house_id = nd.house_id
            WHERE nd.status = 'issued'
              AND {clause}
            ORDER BY
              CASE nd.treasury_status WHEN 'pending' THEN 0 WHEN 'validated' THEN 1 ELSE 2 END,
              nd.issued_at DESC
            LIMIT ?
            """,
            (*params, lim),
        ).fetchall()
        out["noDues"] = [rwa_no_dues.public_request(conn, r) for r in rows]

    return out
