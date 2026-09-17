"""EC-configured extra columns on the dues ledger.

Column definitions are colony-wide. Values are stored per plot (house_id) so they
survive ledger PDF re-imports. Money columns do not change pending/dues totals.
"""

from __future__ import annotations

import re
import secrets
import sqlite3
from typing import Any

from init_rwa_db import utc_now

MAX_COLUMNS = 8
LABEL_MAX = 40
TEXT_VALUE_MAX = 200
KINDS = ("money", "text")
ID_RE = re.compile(r"^lc_[a-z0-9]{8,16}$")


def ensure_ledger_custom_columns(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS ledger_custom_columns (
          id TEXT PRIMARY KEY,
          label TEXT NOT NULL,
          kind TEXT NOT NULL CHECK(kind IN ('money','text')),
          sort_order INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS ledger_custom_values (
          column_id TEXT NOT NULL REFERENCES ledger_custom_columns(id) ON DELETE CASCADE,
          house_id TEXT NOT NULL,
          value_text TEXT,
          value_num INTEGER,
          updated_at TEXT NOT NULL,
          PRIMARY KEY (column_id, house_id)
        );
        CREATE INDEX IF NOT EXISTS idx_ledger_custom_values_house
          ON ledger_custom_values(house_id);
        """
    )
    conn.commit()


def _new_column_id() -> str:
    return "lc_" + secrets.token_hex(4)


def _kind(raw: Any) -> str:
    k = str(raw or "text").strip().lower()
    return k if k in KINDS else "text"


def _label(raw: Any) -> str:
    return re.sub(r"\s+", " ", str(raw or "").strip())[:LABEL_MAX]


def list_columns(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    ensure_ledger_custom_columns(conn)
    rows = conn.execute(
        """
        SELECT id, label, kind, sort_order
        FROM ledger_custom_columns
        ORDER BY sort_order ASC, created_at ASC
        """
    ).fetchall()
    return [
        {
            "id": r["id"],
            "label": r["label"],
            "kind": r["kind"],
            "sortOrder": int(r["sort_order"] or 0),
        }
        for r in rows
    ]


def save_columns(conn: sqlite3.Connection, payload: list[Any] | None) -> list[dict[str, Any]]:
    """Replace the column set. Existing ids keep their values; dropped ids lose them."""
    ensure_ledger_custom_columns(conn)
    incoming = payload if isinstance(payload, list) else []
    existing = {c["id"]: c for c in list_columns(conn)}
    cleaned: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in incoming:
        if not isinstance(item, dict):
            continue
        label = _label(item.get("label"))
        if not label:
            continue
        kind = _kind(item.get("kind"))
        cid = str(item.get("id") or "").strip()
        if cid in existing and cid not in seen:
            pass
        elif ID_RE.fullmatch(cid) and cid not in seen:
            pass
        else:
            cid = _new_column_id()
            while cid in existing or cid in seen:
                cid = _new_column_id()
        if cid in seen:
            continue
        seen.add(cid)
        cleaned.append({"id": cid, "label": label, "kind": kind})
        if len(cleaned) >= MAX_COLUMNS:
            break

    now = utc_now()
    keep_ids = {c["id"] for c in cleaned}
    for old_id in existing:
        if old_id not in keep_ids:
            conn.execute("DELETE FROM ledger_custom_values WHERE column_id = ?", (old_id,))
            conn.execute("DELETE FROM ledger_custom_columns WHERE id = ?", (old_id,))

    for i, col in enumerate(cleaned):
        prev = existing.get(col["id"])
        if prev:
            conn.execute(
                """
                UPDATE ledger_custom_columns
                   SET label = ?, kind = ?, sort_order = ?, updated_at = ?
                 WHERE id = ?
                """,
                (col["label"], col["kind"], i, now, col["id"]),
            )
            if prev["kind"] != col["kind"]:
                conn.execute(
                    "DELETE FROM ledger_custom_values WHERE column_id = ?",
                    (col["id"],),
                )
        else:
            conn.execute(
                """
                INSERT INTO ledger_custom_columns(id, label, kind, sort_order, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (col["id"], col["label"], col["kind"], i, now, now),
            )
    conn.commit()
    return list_columns(conn)


def _parse_money(raw: Any) -> int | None:
    if raw is None:
        return None
    if isinstance(raw, str) and not raw.strip():
        return None
    cleaned = str(raw).strip().replace(",", "").replace("₹", "").replace(" ", "")
    if cleaned in {"", "-", "—"}:
        return None
    try:
        return int(float(cleaned))
    except (TypeError, ValueError) as exc:
        raise ValueError("Custom rupee columns need a whole-rupee amount") from exc


def values_for_houses(conn: sqlite3.Connection, house_ids: list[str]) -> dict[str, dict[str, Any]]:
    """house_id → { column_id → money int | text str }."""
    ensure_ledger_custom_columns(conn)
    columns = list_columns(conn)
    out: dict[str, dict[str, Any]] = {hid: {} for hid in house_ids}
    if not columns or not house_ids:
        return out
    by_id = {c["id"]: c for c in columns}
    placeholders = ", ".join("?" for _ in house_ids)
    col_placeholders = ", ".join("?" for _ in columns)
    rows = conn.execute(
        f"""
        SELECT column_id, house_id, value_text, value_num
          FROM ledger_custom_values
         WHERE house_id IN ({placeholders})
           AND column_id IN ({col_placeholders})
        """,
        tuple(house_ids) + tuple(c["id"] for c in columns),
    ).fetchall()
    for r in rows:
        hid = r["house_id"]
        cid = r["column_id"]
        col = by_id.get(cid)
        if not col or hid not in out:
            continue
        if col["kind"] == "money":
            if r["value_num"] is None:
                continue
            out[hid][cid] = int(r["value_num"])
        else:
            text = (r["value_text"] or "").strip()
            if text:
                out[hid][cid] = text
    return out


def values_for_house(conn: sqlite3.Connection, house_id: str) -> dict[str, Any]:
    return values_for_houses(conn, [house_id]).get(house_id) or {}


def set_values_for_house(
    conn: sqlite3.Connection,
    house_id: str,
    mapping: Any,
    *,
    commit: bool = True,
) -> dict[str, Any]:
    ensure_ledger_custom_columns(conn)
    hid = (house_id or "").strip()
    if not hid:
        raise ValueError("houseId required")
    if mapping is None:
        return values_for_house(conn, hid)
    if not isinstance(mapping, dict):
        raise ValueError("customValues must be an object")
    columns = {c["id"]: c for c in list_columns(conn)}
    now = utc_now()
    for cid, raw in mapping.items():
        col = columns.get(str(cid))
        if not col:
            continue
        if col["kind"] == "money":
            num = _parse_money(raw)
            if num is None:
                conn.execute(
                    "DELETE FROM ledger_custom_values WHERE column_id = ? AND house_id = ?",
                    (col["id"], hid),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO ledger_custom_values(column_id, house_id, value_text, value_num, updated_at)
                    VALUES (?, ?, NULL, ?, ?)
                    ON CONFLICT(column_id, house_id) DO UPDATE SET
                      value_text = NULL,
                      value_num = excluded.value_num,
                      updated_at = excluded.updated_at
                    """,
                    (col["id"], hid, num, now),
                )
        else:
            text = str(raw or "").strip()[:TEXT_VALUE_MAX]
            if not text:
                conn.execute(
                    "DELETE FROM ledger_custom_values WHERE column_id = ? AND house_id = ?",
                    (col["id"], hid),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO ledger_custom_values(column_id, house_id, value_text, value_num, updated_at)
                    VALUES (?, ?, ?, NULL, ?)
                    ON CONFLICT(column_id, house_id) DO UPDATE SET
                      value_text = excluded.value_text,
                      value_num = NULL,
                      updated_at = excluded.updated_at
                    """,
                    (col["id"], hid, text, now),
                )
    if commit:
        conn.commit()
    return values_for_house(conn, hid)


def attach_to_payment(
    payment: dict[str, Any] | None,
    columns: list[dict[str, Any]],
    values: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if payment is None:
        return None
    vals = values or {}
    payment["customColumns"] = columns
    payment["customValues"] = {c["id"]: vals.get(c["id"]) for c in columns if c["id"] in vals}
    for col in columns:
        payment[field_id(col["id"])] = vals.get(col["id"])
    return payment


def field_id(column_id: str) -> str:
    return f"custom:{column_id}"


def report_field_defs(conn: sqlite3.Connection | None) -> list[dict[str, Any]]:
    if conn is None:
        return []
    out = []
    for col in list_columns(conn):
        money = col["kind"] == "money"
        out.append({
            "id": field_id(col["id"]),
            "label": col["label"],
            "default": True,
            "align": "right" if money else "left",
            "width": 54 if money else 70,
            "kind": col["kind"],
            "custom": True,
        })
    return out


def money_field_ids(conn: sqlite3.Connection | None) -> set[str]:
    return {field_id(c["id"]) for c in list_columns(conn) if c["kind"] == "money"} if conn is not None else set()
