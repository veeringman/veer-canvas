"""Meeting proceedings / MOM register — General House and Executive Committee."""

from __future__ import annotations

import json
import re
import secrets
import hashlib
import sqlite3
from typing import Any

from init_rwa_db import utc_now

MEETING_TYPES: list[tuple[str, str]] = (
    ("gh", "General House Meeting"),
    ("ec", "Executive Committee Meeting"),
)

GH_SUBTYPES: list[tuple[str, str]] = (
    ("regular", "Regular General Body"),
    ("annual", "Annual General Meeting"),
    ("special", "Special General Body"),
    ("emergency", "Emergency General Body"),
)

EC_SUBTYPES: list[tuple[str, str]] = (
    ("regular", "Regular EC Meeting"),
    ("special", "Special EC Meeting"),
    ("emergency", "Emergency EC Meeting"),
)

PROCEEDING_STATUSES: list[tuple[str, str]] = (
    ("draft", "Draft"),
    ("published", "Published"),
    ("archived", "Archived"),
)


def proceedings_meta() -> dict:
    return {
        "meetingTypes": [{"id": k, "label": lbl} for k, lbl in MEETING_TYPES],
        "subtypes": {
            "gh": [{"id": s, "label": lbl} for s, lbl in GH_SUBTYPES],
            "ec": [{"id": s, "label": lbl} for s, lbl in EC_SUBTYPES],
        },
        "statuses": [{"id": s, "label": lbl} for s, lbl in PROCEEDING_STATUSES],
    }


def _meeting_type(raw: str | None) -> str:
    key = (raw or "").strip().lower()
    allowed = {k for k, _ in MEETING_TYPES}
    if key not in allowed:
        raise ValueError("meetingType must be gh (General House) or ec (Executive Committee)")
    return key


def _subtype(meeting_type: str, raw: str | None) -> str:
    key = (raw or "regular").strip().lower() or "regular"
    pool = GH_SUBTYPES if meeting_type == "gh" else EC_SUBTYPES
    allowed = {s for s, _ in pool}
    return key if key in allowed else "regular"


def _status(raw: str | None) -> str:
    key = (raw or "draft").strip().lower()
    allowed = {s for s, _ in PROCEEDING_STATUSES}
    if key not in allowed:
        raise ValueError("Invalid status")
    return key


def _parse_resolutions(raw) -> list[dict]:
    if raw is None or raw == "":
        return []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError("resolutions must be valid JSON") from exc
    if not isinstance(raw, list):
        raise ValueError("resolutions must be a list")
    out: list[dict] = []
    for i, item in enumerate(raw, 1):
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or item.get("resolution") or "").strip()[:2000]
        if not text:
            continue
        no = str(item.get("no") or item.get("number") or i).strip()[:12]
        rid = str(item.get("id") or "").strip()[:40]
        if not rid or not re.match(r"^res_[a-zA-Z0-9]+$", rid):
            rid = "res_" + hashlib.sha256(f"{no}:{text}".encode("utf-8")).hexdigest()[:10]
        out.append({
            "id": rid,
            "no": no,
            "text": text,
            "passed": bool(item.get("passed", True)),
            "votesFor": _optional_int(item.get("votesFor")),
            "votesAgainst": _optional_int(item.get("votesAgainst")),
            "abstain": _optional_int(item.get("abstain")),
        })
    return out[:50]


def _parse_action_items(raw) -> list[dict]:
    if raw is None or raw == "":
        return []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError("actionItems must be valid JSON") from exc
    if not isinstance(raw, list):
        raise ValueError("actionItems must be a list")
    out: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        text = str(item.get("item") or item.get("text") or "").strip()[:800]
        if not text:
            continue
        out.append({
            "item": text,
            "owner": str(item.get("owner") or "").strip()[:120],
            "dueDate": str(item.get("dueDate") or item.get("due_date") or "").strip()[:20],
            "done": bool(item.get("done")),
        })
    return out[:40]


def _optional_int(value) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _year_from_date(meeting_date: str) -> str:
    m = re.match(r"(\d{4})", str(meeting_date or ""))
    return m.group(1) if m else utc_now()[:4]


def _next_register_no(conn: sqlite3.Connection, meeting_type: str, meeting_date: str) -> int:
    year = _year_from_date(meeting_date)
    row = conn.execute(
        """
        SELECT COALESCE(MAX(register_no), 0) AS mx
        FROM meeting_proceedings
        WHERE meeting_type = ? AND substr(meeting_date, 1, 4) = ?
        """,
        (meeting_type, year),
    ).fetchone()
    return int(row["mx"] or 0) + 1


def _proceeding_public(r: sqlite3.Row | dict) -> dict:
    if hasattr(r, "keys"):
        data = {k: r[k] for k in r.keys()}
    else:
        data = dict(r)
    meeting_type = data.get("meeting_type") or "gh"
    subtype = data.get("meeting_subtype") or "regular"
    status = data.get("status") or "draft"
    type_label = next((lbl for k, lbl in MEETING_TYPES if k == meeting_type), meeting_type)
    subtype_pool = GH_SUBTYPES if meeting_type == "gh" else EC_SUBTYPES
    subtype_label = next((lbl for s, lbl in subtype_pool if s == subtype), subtype)
    status_label = next((lbl for s, lbl in PROCEEDING_STATUSES if s == status), status)
    year = _year_from_date(data.get("meeting_date") or "")
    register_no = int(data.get("register_no") or 0)
    register_label = f"{register_no}/{year}" if register_no else ""
    try:
        resolutions = _parse_resolutions(data.get("resolutions_json") or "[]")
    except ValueError:
        resolutions = []
    try:
        action_items = _parse_action_items(data.get("action_items_json") or "[]")
    except ValueError:
        action_items = []
    quorum = data.get("quorum_met")
    return {
        "id": data.get("id"),
        "registerNo": register_no,
        "registerYear": year,
        "registerLabel": register_label,
        "meetingType": meeting_type,
        "meetingTypeLabel": type_label,
        "meetingSubtype": subtype,
        "meetingSubtypeLabel": subtype_label,
        "title": data.get("title") or "",
        "meetingDate": data.get("meeting_date") or "",
        "meetingTime": data.get("meeting_time") or "",
        "venue": data.get("venue") or "",
        "chairPerson": data.get("chair_person") or "",
        "membersPresent": data.get("members_present") or "",
        "membersAbsent": data.get("members_absent") or "",
        "quorumMet": bool(quorum) if quorum is not None else None,
        "agenda": data.get("agenda") or "",
        "proceedingsBody": data.get("proceedings_body") or "",
        "resolutions": resolutions,
        "actionItems": action_items,
        "nextMeetingDate": data.get("next_meeting_date") or "",
        "signedBy": data.get("signed_by") or "",
        "approvedAt": data.get("approved_at") or "",
        "status": status,
        "statusLabel": status_label,
        "visibility": data.get("visibility") or "published",
        "publishedAt": data.get("published_at") or "",
        "publishedBy": data.get("published_by") or "",
        "createdBy": data.get("created_by") or "",
        "createdAt": data.get("created_at"),
        "updatedAt": data.get("updated_at"),
    }


def list_meeting_proceedings(
    conn: sqlite3.Connection,
    *,
    meeting_type: str | None = None,
    year: str | None = None,
    status: str | None = None,
    search: str | None = None,
    as_admin: bool = False,
) -> list[dict]:
    from init_rwa_db import ensure_meeting_proceedings_table

    ensure_meeting_proceedings_table(conn)
    clauses: list[str] = []
    params: list[Any] = []
    if not as_admin:
        clauses.append("status = 'published'")
    elif status:
        clauses.append("status = ?")
        params.append(_status(status))
    if meeting_type:
        clauses.append("meeting_type = ?")
        params.append(_meeting_type(meeting_type))
    if year:
        clauses.append("substr(meeting_date, 1, 4) = ?")
        params.append(str(year).strip()[:4])
    if search:
        q = f"%{search.strip()}%"
        clauses.append(
            "(title LIKE ? OR agenda LIKE ? OR proceedings_body LIKE ? OR chair_person LIKE ?)"
        )
        params.extend([q, q, q, q])
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = conn.execute(
        f"""
        SELECT * FROM meeting_proceedings
        {where}
        ORDER BY meeting_date DESC, register_no DESC, updated_at DESC
        """,
        params,
    ).fetchall()
    out = [_proceeding_public(r) for r in rows]
    try:
        import rwa_resolution_votes as _votes

        _votes.attach_votes(conn, out)
    except Exception:
        pass
    return out


def get_meeting_proceeding(
    conn: sqlite3.Connection,
    proceeding_id: str,
    *,
    as_admin: bool = False,
) -> dict | None:
    from init_rwa_db import ensure_meeting_proceedings_table

    ensure_meeting_proceedings_table(conn)
    pid = (proceeding_id or "").strip()
    if not pid:
        return None
    row = conn.execute("SELECT * FROM meeting_proceedings WHERE id = ?", (pid,)).fetchone()
    if not row:
        return None
    if not as_admin and (row["status"] or "") != "published":
        return None
    proceeding = _proceeding_public(row)
    try:
        import rwa_resolution_votes as _votes

        _votes.attach_votes(conn, [proceeding])
    except Exception:
        pass
    return proceeding


def upsert_meeting_proceeding(
    conn: sqlite3.Connection,
    payload: dict,
    *,
    actor: dict | None = None,
) -> dict:
    from init_rwa_db import ensure_meeting_proceedings_table

    ensure_meeting_proceedings_table(conn)
    pid = str(payload.get("id") or payload.get("proceedingId") or "").strip()
    existing = None
    if pid:
        existing = conn.execute("SELECT * FROM meeting_proceedings WHERE id = ?", (pid,)).fetchone()
    if not pid:
        pid = f"mp_{secrets.token_hex(5)}"

    meeting_type = _meeting_type(payload.get("meetingType") or (existing["meeting_type"] if existing else None))
    meeting_date = str(payload.get("meetingDate") or (existing["meeting_date"] if existing else "") or "").strip()
    if not meeting_date:
        raise ValueError("meetingDate is required")
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", meeting_date):
        raise ValueError("meetingDate must be YYYY-MM-DD")

    title = str(payload.get("title") or (existing["title"] if existing else "") or "").strip()
    if not title:
        raise ValueError("title is required")

    subtype = _subtype(
        meeting_type,
        payload.get("meetingSubtype") if "meetingSubtype" in payload else (existing["meeting_subtype"] if existing else None),
    )
    status = _status(payload.get("status") if "status" in payload else (existing["status"] if existing else "draft"))
    visibility = str(
        payload.get("visibility") if "visibility" in payload else (existing["visibility"] if existing else "published")
    ).strip().lower()
    if visibility not in {"draft", "published"}:
        visibility = "published"

    register_no = int(existing["register_no"]) if existing else _next_register_no(conn, meeting_type, meeting_date)
    if existing and "registerNo" in payload and payload.get("registerNo") not in (None, ""):
        register_no = int(payload["registerNo"])

    resolutions = _parse_resolutions(
        payload.get("resolutions") if "resolutions" in payload else (existing["resolutions_json"] if existing else [])
    )
    action_items = _parse_action_items(
        payload.get("actionItems") if "actionItems" in payload else (existing["action_items_json"] if existing else [])
    )

    now = utc_now()
    actor_house = (actor or {}).get("houseId") or (actor or {}).get("house_id") or ""
    created_by = (existing["created_by"] if existing else actor_house) or ""
    published_at = existing["published_at"] if existing else None
    published_by = existing["published_by"] if existing else None
    if status == "published" and (not existing or (existing["status"] or "") != "published"):
        published_at = now
        published_by = actor_house

    quorum_raw = payload.get("quorumMet") if "quorumMet" in payload else (existing["quorum_met"] if existing else None)
    quorum_met = None if quorum_raw is None or quorum_raw == "" else (1 if bool(quorum_raw) else 0)

    fields = {
        "register_no": register_no,
        "meeting_type": meeting_type,
        "meeting_subtype": subtype,
        "title": title[:200],
        "meeting_date": meeting_date,
        "meeting_time": str(payload.get("meetingTime") if "meetingTime" in payload else (existing["meeting_time"] if existing else "") or "").strip()[:40],
        "venue": str(payload.get("venue") if "venue" in payload else (existing["venue"] if existing else "") or "").strip()[:200],
        "chair_person": str(payload.get("chairPerson") if "chairPerson" in payload else (existing["chair_person"] if existing else "") or "").strip()[:120],
        "members_present": str(payload.get("membersPresent") if "membersPresent" in payload else (existing["members_present"] if existing else "") or "").strip()[:4000],
        "members_absent": str(payload.get("membersAbsent") if "membersAbsent" in payload else (existing["members_absent"] if existing else "") or "").strip()[:4000],
        "quorum_met": quorum_met,
        "agenda": str(payload.get("agenda") if "agenda" in payload else (existing["agenda"] if existing else "") or "").strip()[:12000],
        "proceedings_body": str(payload.get("proceedingsBody") if "proceedingsBody" in payload else (existing["proceedings_body"] if existing else "") or "").strip()[:50000],
        "resolutions_json": json.dumps(resolutions, ensure_ascii=False),
        "action_items_json": json.dumps(action_items, ensure_ascii=False),
        "next_meeting_date": str(payload.get("nextMeetingDate") if "nextMeetingDate" in payload else (existing["next_meeting_date"] if existing else "") or "").strip()[:20],
        "signed_by": str(payload.get("signedBy") if "signedBy" in payload else (existing["signed_by"] if existing else "") or "").strip()[:200],
        "approved_at": str(payload.get("approvedAt") if "approvedAt" in payload else (existing["approved_at"] if existing else "") or "").strip()[:20],
        "status": status,
        "visibility": visibility,
        "published_at": published_at,
        "published_by": published_by or "",
        "updated_at": now,
    }

    if existing:
        conn.execute(
            """
            UPDATE meeting_proceedings SET
              register_no = :register_no,
              meeting_type = :meeting_type,
              meeting_subtype = :meeting_subtype,
              title = :title,
              meeting_date = :meeting_date,
              meeting_time = :meeting_time,
              venue = :venue,
              chair_person = :chair_person,
              members_present = :members_present,
              members_absent = :members_absent,
              quorum_met = :quorum_met,
              agenda = :agenda,
              proceedings_body = :proceedings_body,
              resolutions_json = :resolutions_json,
              action_items_json = :action_items_json,
              next_meeting_date = :next_meeting_date,
              signed_by = :signed_by,
              approved_at = :approved_at,
              status = :status,
              visibility = :visibility,
              published_at = :published_at,
              published_by = :published_by,
              updated_at = :updated_at
            WHERE id = :id
            """,
            {**fields, "id": pid},
        )
    else:
        conn.execute(
            """
            INSERT INTO meeting_proceedings(
              id, register_no, meeting_type, meeting_subtype, title,
              meeting_date, meeting_time, venue, chair_person,
              members_present, members_absent, quorum_met,
              agenda, proceedings_body, resolutions_json, action_items_json,
              next_meeting_date, signed_by, approved_at,
              status, visibility, published_at, published_by,
              created_by, created_at, updated_at
            ) VALUES (
              :id, :register_no, :meeting_type, :meeting_subtype, :title,
              :meeting_date, :meeting_time, :venue, :chair_person,
              :members_present, :members_absent, :quorum_met,
              :agenda, :proceedings_body, :resolutions_json, :action_items_json,
              :next_meeting_date, :signed_by, :approved_at,
              :status, :visibility, :published_at, :published_by,
              :created_by, :created_at, :updated_at
            )
            """,
            {
                **fields,
                "id": pid,
                "created_by": created_by,
                "created_at": now,
            },
        )
    conn.commit()
    return get_meeting_proceeding(conn, pid, as_admin=True) or {"id": pid}


def delete_meeting_proceeding(conn: sqlite3.Connection, proceeding_id: str) -> None:
    from init_rwa_db import ensure_meeting_proceedings_table

    ensure_meeting_proceedings_table(conn)
    pid = (proceeding_id or "").strip()
    if not pid:
        raise ValueError("id required")
    try:
        import rwa_resolution_votes as _votes

        _votes.delete_votes_for_proceeding(conn, pid)
    except Exception:
        pass
    cur = conn.execute("DELETE FROM meeting_proceedings WHERE id = ?", (pid,))
    if cur.rowcount < 1:
        raise ValueError("Proceeding not found")
    conn.commit()
