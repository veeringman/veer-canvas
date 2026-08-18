"""Colony board: staff roster, utility contacts, and activity schedule (meta-backed JSON)."""

from __future__ import annotations

import json
import re
import secrets
import sqlite3
from datetime import datetime, timezone
from typing import Any

META_KEY = "colony_services_v1"

_STAFF_FIELDS = ("name", "role", "responsibility", "phone", "hours", "notes")
_CONTACT_FIELDS = (
    "department",
    "forIssues",
    "contactName",
    "phone",
    "altPhone",
    "hours",
    "notes",
)
_SCHEDULE_FIELDS = ("activity", "detail", "when", "where", "contact", "notes")


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(4)}"


def default_colony_services() -> dict[str, Any]:
    return {
        "staff": [
            {
                "id": "watchman",
                "name": "",
                "role": "Watchman / gate",
                "responsibility": "Gate entry, visitor logs, and night patrol",
                "phone": "",
                "hours": "As posted at the gate",
                "notes": "",
            },
            {
                "id": "gardener",
                "name": "",
                "role": "Gardener",
                "responsibility": "Common-area lawns, plants, and seasonal upkeep",
                "phone": "",
                "hours": "",
                "notes": "",
            },
            {
                "id": "sanitation",
                "name": "",
                "role": "Sanitation",
                "responsibility": "Street sweeping, drain clearing, and waste collection points",
                "phone": "",
                "hours": "",
                "notes": "",
            },
        ],
        "contacts": [
            {
                "id": "water",
                "department": "Water supply",
                "forIssues": "Low pressure, leakage, or tanker timing",
                "contactName": "Jal Shakti / local sub-division (ask EC for office number)",
                "phone": "",
                "altPhone": "",
                "hours": "",
                "notes": "Note your block/plot and the nearest valve or hydrant when reporting.",
            },
            {
                "id": "electricity",
                "department": "Electricity (HPSEBL)",
                "forIssues": "Power outage, meter fault, or street-light fault",
                "contactName": "HPSEBL customer care",
                "phone": "1912",
                "altPhone": "",
                "hours": "24×7",
                "notes": "Dial 112 for life-threatening electrical emergencies.",
            },
            {
                "id": "police",
                "department": "Police",
                "forIssues": "Theft, disturbance, or safety",
                "contactName": "Emergency",
                "phone": "100",
                "altPhone": "112",
                "hours": "24×7",
                "notes": "",
            },
            {
                "id": "ambulance",
                "department": "Medical emergency",
                "forIssues": "Ambulance",
                "contactName": "Emergency",
                "phone": "108",
                "altPhone": "112",
                "hours": "24×7",
                "notes": "",
            },
            {
                "id": "ec",
                "department": "Executive Committee",
                "forIssues": "Colony maintenance and society matters",
                "contactName": "See Directory or EC desk",
                "phone": "",
                "altPhone": "",
                "hours": "",
                "notes": "Use the Concerns mailbox in this portal for tracked requests.",
            },
        ],
        "schedule": [
            {
                "id": "water-supply",
                "activity": "Water tanker / supply window",
                "detail": "Typical supply days and times (EC to confirm)",
                "when": "To be announced",
                "where": "Community tanks / blocks",
                "contact": "EC / watchman",
                "notes": "",
            },
            {
                "id": "waste",
                "activity": "Waste collection",
                "detail": "Municipal or private pickup schedule",
                "when": "To be announced",
                "where": "Designated collection points",
                "contact": "",
                "notes": "",
            },
            {
                "id": "garden",
                "activity": "Garden / pruning",
                "detail": "Common-area maintenance",
                "when": "To be announced",
                "where": "Colony grounds",
                "contact": "Gardener",
                "notes": "",
            },
        ],
    }


def ensure_colony_services_seed(conn: sqlite3.Connection) -> None:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (META_KEY,)).fetchone()
    if row:
        return
    payload = default_colony_services()
    payload["updatedAt"] = utc_now()
    payload["updatedBy"] = "system"
    conn.execute(
        "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
        (META_KEY, json.dumps(payload, ensure_ascii=False)),
    )
    conn.commit()


def _clean_text(value: Any, *, max_len: int = 500) -> str:
    text = str(value or "").strip()
    if len(text) > max_len:
        text = text[:max_len]
    return text


def _clean_phone(value: Any) -> str:
    text = _clean_text(value, max_len=40)
    if not text:
        return ""
    # Allow digits, +, spaces, hyphens, commas, x for extensions.
    if not re.fullmatch(r"[0-9+\s\-,xX()]+", text):
        raise ValueError(f"Invalid phone number: {text}")
    return text


def _normalize_rows(
    items: Any,
    *,
    fields: tuple[str, ...],
    id_prefix: str,
    required_any: tuple[str, ...] | None = None,
    max_items: int = 40,
) -> list[dict[str, str]]:
    if not isinstance(items, list):
        raise ValueError("Expected a list")
    if len(items) > max_items:
        raise ValueError(f"Too many rows (max {max_items})")
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw in items:
        if not isinstance(raw, dict):
            raise ValueError("Each row must be an object")
        row_id = _clean_text(raw.get("id") or _new_id(id_prefix), max_len=64)
        if not row_id or row_id in seen:
            row_id = _new_id(id_prefix)
        seen.add(row_id)
        row: dict[str, str] = {"id": row_id}
        for field in fields:
            if field in {"phone", "altPhone"}:
                row[field] = _clean_phone(raw.get(field))
            else:
                row[field] = _clean_text(raw.get(field))
        if required_any and not any(row[k] for k in required_any):
            continue
        out.append(row)
    return out


def get_colony_services(conn: sqlite3.Connection) -> dict[str, Any]:
    ensure_colony_services_seed(conn)
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (META_KEY,)).fetchone()
    if not row:
        data = default_colony_services()
        data["updatedAt"] = utc_now()
        data["updatedBy"] = "system"
        return data
    try:
        data = json.loads(row["value"])
    except (TypeError, json.JSONDecodeError):
        data = default_colony_services()
    if not isinstance(data, dict):
        data = default_colony_services()
    base = default_colony_services()
    for key in ("staff", "contacts", "schedule"):
        if not isinstance(data.get(key), list):
            data[key] = base[key]
    data.setdefault("updatedAt", utc_now())
    data.setdefault("updatedBy", "")
    return data


def update_colony_services(
    conn: sqlite3.Connection,
    payload: dict,
    *,
    actor_house_id: str | None = None,
    actor_name: str | None = None,
) -> dict[str, Any]:
    ensure_colony_services_seed(conn)
    staff = _normalize_rows(
        payload.get("staff"),
        fields=_STAFF_FIELDS,
        id_prefix="staff",
        required_any=("name", "role", "responsibility", "phone"),
    )
    contacts = _normalize_rows(
        payload.get("contacts"),
        fields=_CONTACT_FIELDS,
        id_prefix="contact",
        required_any=("department", "forIssues", "contactName", "phone"),
    )
    schedule = _normalize_rows(
        payload.get("schedule"),
        fields=_SCHEDULE_FIELDS,
        id_prefix="sched",
        required_any=("activity", "detail", "when"),
    )
    if not staff:
        raise ValueError("Add at least one staff row with a name, role, responsibility, or phone")
    if not contacts:
        raise ValueError("Add at least one utility contact row")
    if not schedule:
        raise ValueError("Add at least one scheduled activity row")
    actor_bits = [b for b in (actor_name, actor_house_id and f"Plot {actor_house_id}") if b]
    updated_by = " · ".join(actor_bits) if actor_bits else "EC"
    data = {
        "staff": staff,
        "contacts": contacts,
        "schedule": schedule,
        "updatedAt": utc_now(),
        "updatedBy": updated_by,
    }
    conn.execute(
        "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
        (META_KEY, json.dumps(data, ensure_ascii=False)),
    )
    conn.commit()
    return data
