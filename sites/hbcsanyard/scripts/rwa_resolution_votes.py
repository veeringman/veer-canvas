"""Circulation voting on MOM resolutions.

EC sends a request to all members or meeting attendees. Each plot votes once
(first response is recorded) via email public link or the signed-in members area.
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import secrets
import sqlite3
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from init_rwa_db import (
    SUPERADMIN_HOUSE_ID,
    SYSTEM_HOUSE_IDS,
    ensure_resolution_votes_tables,
    system_house_exclude_sql,
    utc_now,
)
import rwa_household as household

IST = ZoneInfo("Asia/Kolkata")

AUDIENCES: list[tuple[str, str]] = (
    ("members", "All society members"),
    ("attendees", "Meeting attendees"),
)

CRITERIA: list[tuple[str, str]] = (
    ("simple_majority", "Simple majority of votes cast"),
    ("two_thirds_cast", "Two-thirds of votes cast"),
    ("two_thirds_eligible", "Two-thirds of those invited"),
    ("three_fifths_cast", "Three-fifths of votes cast"),
)

CHOICES = ("accept", "reject")


def vote_meta() -> dict:
    return {
        "audiences": [{"id": k, "label": lbl} for k, lbl in AUDIENCES],
        "criteria": [{"id": k, "label": lbl} for k, lbl in CRITERIA],
    }


def _audience(raw: str | None) -> str:
    key = (raw or "members").strip().lower()
    allowed = {k for k, _ in AUDIENCES}
    if key not in allowed:
        raise ValueError("audience must be members or attendees")
    return key


def _criteria(raw: str | None) -> str:
    key = (raw or "simple_majority").strip().lower()
    allowed = {k for k, _ in CRITERIA}
    if key not in allowed:
        raise ValueError("Invalid pass criteria")
    return key


def _origin(site_root: pathlib.Path | None = None) -> str:
    return (
        os.environ.get("VEERCANVAS_PUBLIC_ORIGIN")
        or os.environ.get("RWA_PUBLIC_ORIGIN")
        or "https://housingcolonysanyard.in"
    ).rstrip("/")


def public_vote_url(token: str, site_root: pathlib.Path | None = None) -> str:
    return f"{_origin(site_root)}/vote.html?t={token}"


def _parse_deadline(raw: str | None) -> str | None:
    text = str(raw or "").strip()
    if not text:
        return None
    if re.match(r"^\d{4}-\d{2}-\d{2}$", text):
        return f"{text}T23:59:59+05:30"
    if re.match(r"^\d{4}-\d{2}-\d{2}T", text):
        return text[:40]
    raise ValueError("deadline must be YYYY-MM-DD")


def _deadline_passed(deadline: str | None, now: str | None = None) -> bool:
    if not deadline:
        return False
    try:
        stamp = datetime.fromisoformat(str(deadline).replace("Z", "+00:00"))
    except ValueError:
        return False
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=IST)
    current = datetime.fromisoformat((now or utc_now()).replace("Z", "+00:00"))
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current >= stamp


def _criteria_label(key: str) -> str:
    return next((lbl for k, lbl in CRITERIA if k == key), key)


def _audience_label(key: str) -> str:
    return next((lbl for k, lbl in AUDIENCES if k == key), key)


def _status_label(key: str) -> str:
    return {
        "open": "Voting open",
        "passed": "Passed",
        "rejected": "Not passed",
        "withdrawn": "Withdrawn",
    }.get(key or "", key or "")


def _row_dict(row: sqlite3.Row | dict) -> dict:
    if hasattr(row, "keys"):
        return {k: row[k] for k in row.keys()}
    return dict(row)


def _vote_public(row: sqlite3.Row | dict, *, include_ballots: bool = False) -> dict:
    data = _row_dict(row)
    status = data.get("status") or "open"
    criteria = data.get("criteria") or "simple_majority"
    audience = data.get("audience") or "members"
    votes_for = int(data.get("votes_for") or 0)
    votes_against = int(data.get("votes_against") or 0)
    eligible = int(data.get("eligible_count") or 0)
    pending = max(0, eligible - votes_for - votes_against)
    out = {
        "id": data.get("id"),
        "proceedingId": data.get("proceeding_id"),
        "resolutionId": data.get("resolution_id"),
        "resolutionNo": data.get("resolution_no") or "",
        "resolutionText": data.get("resolution_text") or "",
        "audience": audience,
        "audienceLabel": _audience_label(audience),
        "criteria": criteria,
        "criteriaLabel": _criteria_label(criteria),
        "status": status,
        "statusLabel": _status_label(status),
        "deadline": data.get("deadline") or "",
        "note": data.get("note") or "",
        "createdBy": data.get("created_by") or "",
        "createdAt": data.get("created_at"),
        "closedAt": data.get("closed_at") or "",
        "closedBy": data.get("closed_by") or "",
        "votesFor": votes_for,
        "votesAgainst": votes_against,
        "eligibleCount": eligible,
        "pendingCount": pending,
        "castCount": votes_for + votes_against,
    }
    if include_ballots and data.get("_ballots") is not None:
        out["ballots"] = data["_ballots"]
    return out


def _ballot_public(row: sqlite3.Row | dict, *, reveal_token: bool = False) -> dict:
    data = _row_dict(row)
    out = {
        "id": data.get("id"),
        "voteId": data.get("vote_id"),
        "houseId": data.get("house_id"),
        "memberId": data.get("member_id") or "",
        "name": data.get("name") or "",
        "plotLabel": data.get("plot_label") or data.get("house_id") or "",
        "hasEmail": bool(str(data.get("email") or "").strip()),
        "choice": data.get("choice"),
        "votedAt": data.get("voted_at") or "",
        "source": data.get("source") or "",
        "emailSentAt": data.get("email_sent_at") or "",
        "emailError": data.get("email_error") or "",
    }
    if reveal_token:
        out["publicToken"] = data.get("public_token") or ""
        out["publicUrl"] = public_vote_url(data.get("public_token") or "")
        out["email"] = data.get("email") or ""
    return out


def _sync_counts(conn: sqlite3.Connection, vote_id: str) -> None:
    row = conn.execute(
        """
        SELECT
          SUM(CASE WHEN choice = 'accept' THEN 1 ELSE 0 END) AS votes_for,
          SUM(CASE WHEN choice = 'reject' THEN 1 ELSE 0 END) AS votes_against,
          COUNT(*) AS eligible
        FROM resolution_vote_ballots
        WHERE vote_id = ?
        """,
        (vote_id,),
    ).fetchone()
    conn.execute(
        """
        UPDATE resolution_votes
        SET votes_for = ?, votes_against = ?, eligible_count = ?
        WHERE id = ?
        """,
        (int(row["votes_for"] or 0), int(row["votes_against"] or 0), int(row["eligible"] or 0), vote_id),
    )


def _criteria_met(criteria: str, votes_for: int, votes_against: int, eligible: int) -> bool:
    cast = votes_for + votes_against
    if cast < 1:
        return False
    if criteria == "simple_majority":
        return votes_for > votes_against
    if criteria == "two_thirds_cast":
        return votes_for * 3 >= cast * 2
    if criteria == "two_thirds_eligible":
        return eligible > 0 and votes_for * 3 >= eligible * 2
    if criteria == "three_fifths_cast":
        return votes_for * 5 >= cast * 3
    return votes_for > votes_against


def _apply_to_proceeding(conn: sqlite3.Connection, vote_row: sqlite3.Row | dict) -> None:
    data = _row_dict(vote_row)
    pid = data.get("proceeding_id")
    rid = data.get("resolution_id")
    if not pid or not rid:
        return
    proceeding = conn.execute(
        "SELECT resolutions_json FROM meeting_proceedings WHERE id = ?",
        (pid,),
    ).fetchone()
    if not proceeding:
        return
    try:
        resolutions = json.loads(proceeding["resolutions_json"] or "[]")
    except json.JSONDecodeError:
        return
    if not isinstance(resolutions, list):
        return
    status = data.get("status") or "open"
    votes_for = int(data.get("votes_for") or 0)
    votes_against = int(data.get("votes_against") or 0)
    changed = False
    for item in resolutions:
        if not isinstance(item, dict):
            continue
        if str(item.get("id") or "") != str(rid) and str(item.get("no") or "") != str(data.get("resolution_no") or ""):
            continue
        item["votesFor"] = votes_for
        item["votesAgainst"] = votes_against
        if status == "passed":
            item["passed"] = True
        elif status == "rejected":
            item["passed"] = False
        changed = True
        break
    if not changed:
        return
    conn.execute(
        """
        UPDATE meeting_proceedings
        SET resolutions_json = ?, updated_at = ?
        WHERE id = ?
        """,
        (json.dumps(resolutions, ensure_ascii=False), utc_now(), pid),
    )


def _close_vote(
    conn: sqlite3.Connection,
    vote_id: str,
    *,
    actor_house: str = "",
    withdrawn: bool = False,
) -> dict:
    _sync_counts(conn, vote_id)
    row = conn.execute("SELECT * FROM resolution_votes WHERE id = ?", (vote_id,)).fetchone()
    if not row:
        raise ValueError("Vote not found")
    now = utc_now()
    if withdrawn:
        status = "withdrawn"
    else:
        passed = _criteria_met(
            row["criteria"],
            int(row["votes_for"] or 0),
            int(row["votes_against"] or 0),
            int(row["eligible_count"] or 0),
        )
        status = "passed" if passed else "rejected"
    conn.execute(
        """
        UPDATE resolution_votes
        SET status = ?, closed_at = ?, closed_by = ?
        WHERE id = ?
        """,
        (status, now, actor_house, vote_id),
    )
    updated = conn.execute("SELECT * FROM resolution_votes WHERE id = ?", (vote_id,)).fetchone()
    _apply_to_proceeding(conn, updated)
    conn.commit()
    return _vote_public(updated)


def _maybe_finalize(conn: sqlite3.Connection, vote_id: str) -> dict | None:
    row = conn.execute("SELECT * FROM resolution_votes WHERE id = ?", (vote_id,)).fetchone()
    if not row or (row["status"] or "") != "open":
        return _vote_public(row) if row else None
    _sync_counts(conn, vote_id)
    row = conn.execute("SELECT * FROM resolution_votes WHERE id = ?", (vote_id,)).fetchone()
    if _deadline_passed(row["deadline"]):
        return _close_vote(conn, vote_id)
    pending = int(row["eligible_count"] or 0) - int(row["votes_for"] or 0) - int(row["votes_against"] or 0)
    if pending <= 0 and int(row["eligible_count"] or 0) > 0:
        return _close_vote(conn, vote_id)
    _apply_to_proceeding(conn, row)
    conn.commit()
    return _vote_public(row)


def attach_votes(conn: sqlite3.Connection, proceedings: list[dict]) -> None:
    ensure_resolution_votes_tables(conn)
    if not proceedings:
        return
    ids = [p.get("id") for p in proceedings if p.get("id")]
    if not ids:
        return
    placeholders = ",".join("?" * len(ids))
    rows = conn.execute(
        f"""
        SELECT * FROM resolution_votes
        WHERE proceeding_id IN ({placeholders})
        ORDER BY created_at DESC
        """,
        ids,
    ).fetchall()
    by_pid: dict[str, list[dict]] = {}
    for row in rows:
        vote = _vote_public(row)
        if (vote.get("status") or "") == "open":
            refreshed = _maybe_finalize(conn, vote["id"])
            if refreshed:
                vote = refreshed
        by_pid.setdefault(row["proceeding_id"], []).append(vote)
    for proceeding in proceedings:
        votes = by_pid.get(proceeding.get("id") or "", [])
        latest_by_res: dict[str, dict] = {}
        for vote in votes:
            key = vote.get("resolutionId") or vote.get("resolutionNo") or vote["id"]
            latest_by_res.setdefault(key, vote)
        proceeding["votes"] = votes
        proceeding["openVoteCount"] = sum(1 for v in votes if v.get("status") == "open")
        for resolution in proceeding.get("resolutions") or []:
            rid = resolution.get("id") or ""
            rno = str(resolution.get("no") or "")
            match = latest_by_res.get(rid) or next(
                (v for v in votes if v.get("resolutionNo") == rno),
                None,
            )
            if match:
                resolution["vote"] = match


def delete_votes_for_proceeding(conn: sqlite3.Connection, proceeding_id: str) -> None:
    ensure_resolution_votes_tables(conn)
    pid = (proceeding_id or "").strip()
    if not pid:
        return
    ids = [
        r["id"]
        for r in conn.execute(
            "SELECT id FROM resolution_votes WHERE proceeding_id = ?",
            (pid,),
        ).fetchall()
    ]
    if not ids:
        return
    placeholders = ",".join("?" * len(ids))
    conn.execute(f"DELETE FROM resolution_vote_ballots WHERE vote_id IN ({placeholders})", ids)
    conn.execute("DELETE FROM resolution_votes WHERE proceeding_id = ?", (pid,))


def _active_member_plots(conn: sqlite3.Connection) -> list[dict]:
    exclude_sql, exclude_ids = system_house_exclude_sql("house_id")
    rows = conn.execute(
        f"""
        SELECT house_id, plot_no, section, name, email, phone
        FROM residents
        WHERE status = 'active' AND {exclude_sql}
        ORDER BY CAST(plot_no AS INTEGER), plot_no COLLATE NOCASE
        """,
        exclude_ids,
    ).fetchall()
    out = []
    for r in rows:
        hid = r["house_id"]
        if hid in SYSTEM_HOUSE_IDS:
            continue
        primary = household.primary_member(conn, hid) or {}
        email = str(primary.get("email") or r["email"] or "").strip().lower()
        name = str(primary.get("name") or r["name"] or hid).strip()
        member_id = str(primary.get("id") or "").strip()
        plot = str(r["plot_no"] or hid).strip()
        out.append({
            "houseId": hid,
            "plotNo": plot,
            "plotLabel": plot,
            "name": name,
            "email": email,
            "memberId": member_id,
        })
    return out


def _ec_member_plots(conn: sqlite3.Connection) -> list[dict]:
    try:
        import rwa_entitlements as entitlements
    except ImportError:
        return []
    seats = entitlements.list_office_and_ec(conn)
    out = []
    seen = set()
    for seat in seats:
        hid = str(seat.get("houseId") or "").strip()
        if not hid or hid in seen or hid in SYSTEM_HOUSE_IDS:
            continue
        if not seat.get("isEcMember"):
            continue
        seen.add(hid)
        primary = household.primary_member(conn, hid) or {}
        seat_id = str(seat.get("ecMemberId") or "").strip()
        seat_member = household.get_member(conn, seat_id) if seat_id else None
        person = seat_member or primary
        email = str((person or {}).get("email") or "").strip().lower()
        name = str(seat.get("ecSeatHolderName") or seat.get("name") or (person or {}).get("name") or hid)
        out.append({
            "houseId": hid,
            "plotNo": seat.get("plotNo") or hid,
            "plotLabel": f"{seat.get('plotNo') or hid}"
            + (f" · {seat.get('officialTitle')}" if seat.get("officialTitle") else ""),
            "name": name,
            "email": email,
            "memberId": str((person or {}).get("id") or seat_id or ""),
        })
    return out


def _parse_attendee_houses(conn: sqlite3.Connection, text: str, pool: list[dict]) -> list[str]:
    raw = (text or "").strip()
    if not raw:
        return [p["houseId"] for p in pool]
    lowered = raw.lower()
    tokens = {t.lower() for t in re.findall(r"[A-Za-z]?\d{1,4}[A-Za-z]?", raw)}
    matched: list[str] = []
    for person in pool:
        hid = person["houseId"]
        plot = str(person.get("plotNo") or "").lower()
        name = str(person.get("name") or "").strip().lower()
        if hid.lower() in tokens or plot in tokens:
            matched.append(hid)
            continue
        if name and len(name) >= 4 and name in lowered:
            matched.append(hid)
    return matched or [p["houseId"] for p in pool]


def preview_audience(
    conn: sqlite3.Connection,
    proceeding: dict,
    *,
    audience: str,
    house_ids: list[str] | None = None,
) -> list[dict]:
    meeting_type = proceeding.get("meetingType") or "gh"
    if meeting_type == "ec":
        pool = _ec_member_plots(conn)
    else:
        pool = _active_member_plots(conn)
    audience_key = _audience(audience)
    if audience_key == "attendees":
        if house_ids:
            wanted = {str(h).strip() for h in house_ids if str(h).strip()}
            pool = [p for p in pool if p["houseId"] in wanted]
        else:
            present = proceeding.get("membersPresent") or ""
            wanted = set(_parse_attendee_houses(conn, present, pool))
            pool = [p for p in pool if p["houseId"] in wanted]
    elif house_ids:
        wanted = {str(h).strip() for h in house_ids if str(h).strip()}
        pool = [p for p in pool if p["houseId"] in wanted]
    return pool


def _find_resolution(proceeding: dict, payload: dict) -> dict:
    resolutions = proceeding.get("resolutions") or []
    rid = str(payload.get("resolutionId") or payload.get("id") or "").strip()
    rno = str(payload.get("resolutionNo") or payload.get("no") or "").strip()
    text = str(payload.get("resolutionText") or payload.get("text") or "").strip()
    for item in resolutions:
        if rid and item.get("id") == rid:
            return item
        if rno and str(item.get("no") or "") == rno:
            return item
        if text and str(item.get("text") or "").strip() == text:
            return item
    raise ValueError("Resolution not found on this proceeding")


def _send_vote_email(
    *,
    to_email: str,
    name: str,
    vote: dict,
    proceeding: dict,
    public_url: str,
    site_root: pathlib.Path | None = None,
) -> dict:
    try:
        import rwa_portal
    except ImportError:
        return {"ok": False, "reason": "mailer_unavailable"}
    cfg = rwa_portal.load_smtp_config(site_root)
    if not cfg.get("configured"):
        return {"ok": False, "reason": "smtp_not_configured", "publicUrl": public_url}
    meeting_label = proceeding.get("meetingTypeLabel") or "Meeting"
    date_label = proceeding.get("meetingDate") or ""
    res_no = vote.get("resolutionNo") or ""
    title = proceeding.get("title") or "Meeting"
    greeting = f"Dear {name}," if name else "Dear member,"
    deadline = vote.get("deadline") or ""
    deadline_line = f"Please vote by {deadline[:10]}.\n\n" if deadline else ""
    note = vote.get("note") or ""
    note_block = f"Note from the committee:\n{note}\n\n" if note else ""
    body = (
        f"{greeting}\n\n"
        f"The Mandi Housing Welfare Society asks you to accept or reject a resolution "
        f"from the {meeting_label} on {date_label}.\n\n"
        f"Meeting: {title}\n"
        f"Resolution {res_no}:\n{vote.get('resolutionText') or ''}\n\n"
        f"{note_block}"
        f"{deadline_line}"
        f"Vote online (first response is recorded; you may vote only once):\n"
        f"{public_url}\n\n"
        f"You can also vote after signing in — tap the bell in the members header:\n"
        f"{_origin(site_root)}/#alerts\n\n"
        f"— Mandi Housing Welfare Society\n"
        f"  Housing Colony Sanyard, Mandi\n"
    )
    try:
        from email.message import EmailMessage
        import smtplib

        msg = EmailMessage()
        msg["Subject"] = f"Vote requested — Resolution {res_no} · {title[:70]}"
        msg["From"] = f"Housing Colony Sanyard RWA <{cfg['from']}>"
        msg["To"] = to_email
        msg["Reply-To"] = cfg["from"]
        msg.set_content(body)
        rwa_portal.add_branded_html_alternative(msg, text_body=body, site_root=site_root)
        with smtplib.SMTP(cfg["host"], cfg["port"], timeout=25) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.ehlo()
            smtp.login(cfg["user"], cfg["password"])
            smtp.send_message(msg)
        return {"ok": True, "channel": "email", "publicUrl": public_url}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:400], "publicUrl": public_url}


def _notify_vote(
    conn: sqlite3.Connection,
    site_root: pathlib.Path | None,
    *,
    house_ids: list[str],
    title: str,
    body: str,
) -> None:
    if not house_ids or not site_root:
        return
    try:
        import rwa_push
    except ImportError:
        return
    try:
        rwa_push.enqueue_push(
            conn,
            site_root,
            event_type="resolution",
            audience={"type": "houses", "houseIds": house_ids},
            title=title,
            body=body,
            url="/#alerts",
        )
    except Exception:
        pass


def start_vote(
    conn: sqlite3.Connection,
    proceeding_id: str,
    payload: dict,
    *,
    actor: dict | None = None,
    site_root: pathlib.Path | None = None,
) -> dict:
    ensure_resolution_votes_tables(conn)
    import rwa_proceedings

    proceeding = rwa_proceedings.get_meeting_proceeding(conn, proceeding_id, as_admin=True)
    if not proceeding:
        raise ValueError("Proceeding not found")
    resolution = _find_resolution(proceeding, payload)
    rid = str(resolution.get("id") or "").strip()
    if not rid:
        raise ValueError("Resolution is missing an id — save the register entry first")
    open_row = conn.execute(
        """
        SELECT id FROM resolution_votes
        WHERE proceeding_id = ? AND resolution_id = ? AND status = 'open'
        LIMIT 1
        """,
        (proceeding_id, rid),
    ).fetchone()
    if open_row:
        raise ValueError("A vote is already open for this resolution")

    audience = _audience(payload.get("audience"))
    criteria = _criteria(payload.get("criteria"))
    deadline = _parse_deadline(payload.get("deadline"))
    note = str(payload.get("note") or "").strip()[:800]
    raw_houses = payload.get("houseIds") or payload.get("houses") or []
    if isinstance(raw_houses, str):
        raw_houses = [p.strip() for p in raw_houses.split(",") if p.strip()]
    house_ids = [str(h).strip() for h in raw_houses if str(h).strip()] or None
    voters = preview_audience(conn, proceeding, audience=audience, house_ids=house_ids)
    if not voters:
        raise ValueError("No eligible members found for this audience")

    now = utc_now()
    vote_id = f"rv_{secrets.token_hex(6)}"
    actor_house = (actor or {}).get("houseId") or (actor or {}).get("house_id") or ""
    conn.execute(
        """
        INSERT INTO resolution_votes(
          id, proceeding_id, resolution_id, resolution_no, resolution_text,
          audience, criteria, status, deadline, note,
          created_by, created_at, votes_for, votes_against, eligible_count
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 'open', ?, ?, ?, ?, 0, 0, ?)
        """,
        (
            vote_id,
            proceeding_id,
            rid,
            str(resolution.get("no") or ""),
            str(resolution.get("text") or "")[:2000],
            audience,
            criteria,
            deadline,
            note,
            actor_house,
            now,
            len(voters),
        ),
    )

    skipped = 0
    house_ids_sent: list[str] = []
    pending_mail: list[tuple[str, str, str, str]] = []
    vote_snapshot = {
        "resolutionNo": resolution.get("no") or "",
        "resolutionText": resolution.get("text") or "",
        "deadline": deadline or "",
        "note": note,
    }
    for person in voters:
        token = secrets.token_urlsafe(24)
        ballot_id = f"rvb_{secrets.token_hex(6)}"
        email = person.get("email") or ""
        conn.execute(
            """
            INSERT INTO resolution_vote_ballots(
              id, vote_id, house_id, member_id, name, email, plot_label,
              public_token, choice, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)
            """,
            (
                ballot_id,
                vote_id,
                person["houseId"],
                person.get("memberId") or "",
                person.get("name") or "",
                email,
                person.get("plotLabel") or person.get("plotNo") or person["houseId"],
                token,
                now,
            ),
        )
        house_ids_sent.append(person["houseId"])
        pending_mail.append((ballot_id, email, person.get("name") or "", token))
        if not email:
            skipped += 1

    conn.commit()

    emailed = 0
    failed = 0
    for ballot_id, email, name, token in pending_mail:
        if not email:
            continue
        result = _send_vote_email(
            to_email=email,
            name=name,
            vote=vote_snapshot,
            proceeding=proceeding,
            public_url=public_vote_url(token, site_root),
            site_root=site_root,
        )
        if result.get("ok"):
            emailed += 1
            conn.execute(
                "UPDATE resolution_vote_ballots SET email_sent_at = ? WHERE id = ?",
                (utc_now(), ballot_id),
            )
        else:
            failed += 1
            err = str(result.get("error") or result.get("reason") or "send_failed")[:400]
            conn.execute(
                "UPDATE resolution_vote_ballots SET email_error = ? WHERE id = ?",
                (err, ballot_id),
            )
    conn.commit()
    meeting_title = proceeding.get("title") or "Meeting"
    res_no = resolution.get("no") or ""
    _notify_vote(
        conn,
        site_root,
        house_ids=house_ids_sent,
        title="Resolution vote requested",
        body=f"Please accept or reject resolution {res_no} from {meeting_title}."[:240],
    )
    vote = get_vote(conn, vote_id, as_admin=True)
    return {
        "vote": vote,
        "invited": len(voters),
        "emailed": emailed,
        "skippedNoEmail": skipped,
        "emailFailed": failed,
    }


def get_vote(conn: sqlite3.Connection, vote_id: str, *, as_admin: bool = False) -> dict | None:
    ensure_resolution_votes_tables(conn)
    vid = (vote_id or "").strip()
    if not vid:
        return None
    row = conn.execute("SELECT * FROM resolution_votes WHERE id = ?", (vid,)).fetchone()
    if not row:
        return None
    if (row["status"] or "") == "open":
        _maybe_finalize(conn, vid)
        row = conn.execute("SELECT * FROM resolution_votes WHERE id = ?", (vid,)).fetchone()
    vote = _vote_public(row)
    if as_admin:
        ballots = conn.execute(
            """
            SELECT * FROM resolution_vote_ballots
            WHERE vote_id = ?
            ORDER BY plot_label COLLATE NOCASE, name COLLATE NOCASE
            """,
            (vid,),
        ).fetchall()
        vote["ballots"] = [_ballot_public(b, reveal_token=True) for b in ballots]
    return vote


def list_votes_for_proceeding(conn: sqlite3.Connection, proceeding_id: str) -> list[dict]:
    ensure_resolution_votes_tables(conn)
    rows = conn.execute(
        """
        SELECT * FROM resolution_votes
        WHERE proceeding_id = ?
        ORDER BY created_at DESC
        """,
        (proceeding_id,),
    ).fetchall()
    out = []
    for row in rows:
        if (row["status"] or "") == "open":
            _maybe_finalize(conn, row["id"])
            row = conn.execute("SELECT * FROM resolution_votes WHERE id = ?", (row["id"],)).fetchone()
        out.append(_vote_public(row))
    return out


def close_vote(
    conn: sqlite3.Connection,
    vote_id: str,
    *,
    actor: dict | None = None,
    withdraw: bool = False,
) -> dict:
    ensure_resolution_votes_tables(conn)
    row = conn.execute("SELECT * FROM resolution_votes WHERE id = ?", (vote_id,)).fetchone()
    if not row:
        raise ValueError("Vote not found")
    if (row["status"] or "") != "open":
        return get_vote(conn, vote_id, as_admin=True) or _vote_public(row)
    actor_house = (actor or {}).get("houseId") or ""
    return _close_vote(conn, vote_id, actor_house=actor_house, withdrawn=withdraw)


def _record_choice(
    conn: sqlite3.Connection,
    ballot: sqlite3.Row,
    choice: str,
    *,
    source: str,
) -> dict:
    choice_key = (choice or "").strip().lower()
    if choice_key not in CHOICES:
        raise ValueError("Choice must be accept or reject")
    vote_id = ballot["vote_id"]
    vote_row = conn.execute("SELECT * FROM resolution_votes WHERE id = ?", (vote_id,)).fetchone()
    if not vote_row:
        raise ValueError("Vote not found")
    if (vote_row["status"] or "") != "open":
        raise ValueError("Voting is closed")
    if _deadline_passed(vote_row["deadline"]):
        _close_vote(conn, vote_id)
        raise ValueError("Voting closed — the deadline has passed")
    if ballot["choice"]:
        return {
            "ok": True,
            "alreadyVoted": True,
            "choice": ballot["choice"],
            "votedAt": ballot["voted_at"],
            "vote": _vote_public(vote_row),
        }
    now = utc_now()
    cur = conn.execute(
        """
        UPDATE resolution_vote_ballots
        SET choice = ?, voted_at = ?, source = ?
        WHERE id = ? AND choice IS NULL
        """,
        (choice_key, now, source[:20], ballot["id"]),
    )
    if cur.rowcount < 1:
        fresh = conn.execute(
            "SELECT * FROM resolution_vote_ballots WHERE id = ?",
            (ballot["id"],),
        ).fetchone()
        vote = _maybe_finalize(conn, vote_id) or _vote_public(vote_row)
        return {
            "ok": True,
            "alreadyVoted": True,
            "choice": fresh["choice"] if fresh else None,
            "votedAt": fresh["voted_at"] if fresh else now,
            "vote": vote,
        }
    vote = _maybe_finalize(conn, vote_id)
    return {
        "ok": True,
        "alreadyVoted": False,
        "choice": choice_key,
        "votedAt": now,
        "vote": vote,
    }


def get_public_ballot(conn: sqlite3.Connection, token: str) -> dict | None:
    ensure_resolution_votes_tables(conn)
    tok = (token or "").strip()
    if not tok:
        return None
    ballot = conn.execute(
        "SELECT * FROM resolution_vote_ballots WHERE public_token = ?",
        (tok,),
    ).fetchone()
    if not ballot:
        return None
    vote_row = conn.execute(
        "SELECT * FROM resolution_votes WHERE id = ?",
        (ballot["vote_id"],),
    ).fetchone()
    if not vote_row:
        return None
    if (vote_row["status"] or "") == "open":
        _maybe_finalize(conn, vote_row["id"])
        vote_row = conn.execute(
            "SELECT * FROM resolution_votes WHERE id = ?",
            (ballot["vote_id"],),
        ).fetchone()
    proceeding = None
    try:
        import rwa_proceedings

        proceeding = rwa_proceedings.get_meeting_proceeding(
            conn, vote_row["proceeding_id"], as_admin=True
        )
    except Exception:
        proceeding = None
    vote = _vote_public(vote_row)
    closed = vote.get("status") != "open"
    return {
        "ballot": {
            "plotLabel": ballot["plot_label"] or ballot["house_id"],
            "name": ballot["name"] or "",
            "choice": ballot["choice"],
            "votedAt": ballot["voted_at"] or "",
        },
        "vote": {
            "id": vote["id"],
            "resolutionNo": vote["resolutionNo"],
            "resolutionText": vote["resolutionText"],
            "status": vote["status"],
            "statusLabel": vote["statusLabel"],
            "deadline": vote["deadline"],
            "note": vote["note"],
            "criteriaLabel": vote["criteriaLabel"],
            "closed": closed,
            "result": None if not closed or vote["status"] == "withdrawn" else vote["status"],
            "votesFor": vote["votesFor"] if closed else None,
            "votesAgainst": vote["votesAgainst"] if closed else None,
        },
        "meeting": {
            "title": (proceeding or {}).get("title") or "",
            "meetingDate": (proceeding or {}).get("meetingDate") or "",
            "meetingTypeLabel": (proceeding or {}).get("meetingTypeLabel") or "",
            "registerLabel": (proceeding or {}).get("registerLabel") or "",
        },
    }


def submit_public_ballot(conn: sqlite3.Connection, token: str, payload: dict) -> dict:
    ensure_resolution_votes_tables(conn)
    tok = (token or "").strip()
    ballot = conn.execute(
        "SELECT * FROM resolution_vote_ballots WHERE public_token = ?",
        (tok,),
    ).fetchone()
    if not ballot:
        raise ValueError("Invalid or expired voting link")
    result = _record_choice(conn, ballot, payload.get("choice") or "", source="email")
    public = get_public_ballot(conn, tok) or {}
    public.update(result)
    return public


def list_my_ballots(conn: sqlite3.Connection, actor: dict) -> dict:
    ensure_resolution_votes_tables(conn)
    house_id = str((actor or {}).get("houseId") or "").strip()
    if not house_id or house_id == SUPERADMIN_HOUSE_ID:
        return {"pending": [], "recent": []}
    rows = conn.execute(
        """
        SELECT b.*, v.status AS vote_status, v.resolution_no, v.resolution_text,
               v.deadline, v.proceeding_id, v.criteria, v.votes_for, v.votes_against,
               v.eligible_count, v.note, v.closed_at
        FROM resolution_vote_ballots b
        JOIN resolution_votes v ON v.id = b.vote_id
        WHERE b.house_id = ?
        ORDER BY b.created_at DESC
        LIMIT 40
        """,
        (house_id,),
    ).fetchall()
    pending = []
    recent = []
    for row in rows:
        if (row["vote_status"] or "") == "open":
            _maybe_finalize(conn, row["vote_id"])
        vote_row = conn.execute(
            "SELECT * FROM resolution_votes WHERE id = ?",
            (row["vote_id"],),
        ).fetchone()
        if not vote_row:
            continue
        vote = _vote_public(vote_row)
        meeting = None
        try:
            import rwa_proceedings

            meeting = rwa_proceedings.get_meeting_proceeding(
                conn, vote_row["proceeding_id"], as_admin=True
            )
        except Exception:
            meeting = None
        item = {
            "ballotId": row["id"],
            "voteId": row["vote_id"],
            "choice": row["choice"],
            "votedAt": row["voted_at"] or "",
            "resolutionNo": vote["resolutionNo"],
            "resolutionText": vote["resolutionText"],
            "status": vote["status"],
            "statusLabel": vote["statusLabel"],
            "deadline": vote["deadline"],
            "note": vote["note"],
            "meetingTitle": (meeting or {}).get("title") or "",
            "meetingDate": (meeting or {}).get("meetingDate") or "",
            "meetingTypeLabel": (meeting or {}).get("meetingTypeLabel") or "",
        }
        if vote["status"] == "open" and not row["choice"]:
            pending.append(item)
        else:
            recent.append(item)
    return {"pending": pending, "recent": recent[:12]}


def cast_member_vote(conn: sqlite3.Connection, actor: dict, payload: dict) -> dict:
    ensure_resolution_votes_tables(conn)
    house_id = str((actor or {}).get("houseId") or "").strip()
    if not house_id or house_id == SUPERADMIN_HOUSE_ID:
        raise ValueError("Sign in as a colony member to vote")
    vote_id = str(payload.get("voteId") or payload.get("id") or "").strip()
    ballot_id = str(payload.get("ballotId") or "").strip()
    ballot = None
    if ballot_id:
        ballot = conn.execute(
            "SELECT * FROM resolution_vote_ballots WHERE id = ? AND house_id = ?",
            (ballot_id, house_id),
        ).fetchone()
    elif vote_id:
        ballot = conn.execute(
            """
            SELECT * FROM resolution_vote_ballots
            WHERE vote_id = ? AND house_id = ?
            """,
            (vote_id, house_id),
        ).fetchone()
    if not ballot:
        raise ValueError("No voting request found for this plot")
    result = _record_choice(
        conn,
        ballot,
        payload.get("choice") or "",
        source="portal",
    )
    mine = list_my_ballots(conn, actor)
    result["pending"] = mine["pending"]
    result["recent"] = mine["recent"]
    return result
