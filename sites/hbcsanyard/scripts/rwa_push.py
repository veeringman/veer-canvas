"""Web Push (VAPID) subscriptions, prefs, and fan-out for the RWA portal."""

from __future__ import annotations

import base64
import json
import os
import pathlib
import secrets
import sqlite3
from typing import Any

from init_rwa_db import (
    SUPERADMIN_HOUSE_ID,
    SYSTEM_HOUSE_IDS,
    ensure_messages_and_push_tables,
    utc_now,
)

PREF_KEYS = (
    "messages",
    "notices",
    "concerns",
    "dues",
    "treasury",
    "no_dues",
    "no_objection",
    "parking",
    "resolutions",
)
EVENT_PREF = {
    "message": "messages",
    "notice": "notices",
    "concern": "concerns",
    "dues": "dues",
    "treasury": "treasury",
    "no_dues": "no_dues",
    "no_objection": "no_objection",
    "parking": "parking",
    "resolution": "resolutions",
    "test": "messages",
}
# Chat has its own tab badge; resolution votes are first-class ballots.
INBOX_SKIP_TYPES = frozenset({"message", "test", "resolution"})
INBOX_KEEP_PER_HOUSE = 80


def vapid_env_path(site_root: pathlib.Path) -> pathlib.Path:
    return pathlib.Path(site_root) / "data" / "vapid.env"


def _load_env_file(path: pathlib.Path) -> None:
    if not path.is_file():
        return
    try:
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip("'").strip('"')
            if key and key not in os.environ:
                os.environ[key] = value
    except OSError:
        pass


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _generate_vapid_pair() -> tuple[str, str]:
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.backends import default_backend

    priv = ec.generate_private_key(ec.SECP256R1(), default_backend())
    priv_bytes = priv.private_numbers().private_value.to_bytes(32, "big")
    pub_n = priv.public_key().public_numbers()
    pub_bytes = b"\x04" + pub_n.x.to_bytes(32, "big") + pub_n.y.to_bytes(32, "big")
    return _b64url(pub_bytes), _b64url(priv_bytes)


def ensure_vapid_keys(site_root: pathlib.Path) -> dict[str, str]:
    """Load or create data/vapid.env. Returns public/private/subject."""
    path = vapid_env_path(site_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    _load_env_file(path)
    pub = (os.environ.get("RWA_VAPID_PUBLIC_KEY") or "").strip()
    priv = (os.environ.get("RWA_VAPID_PRIVATE_KEY") or "").strip()
    subject = (os.environ.get("RWA_VAPID_SUBJECT") or "").strip()
    if not subject:
        subject = (
            os.environ.get("RWA_SMTP_FROM")
            or os.environ.get("RWA_SMTP_USER")
            or "mailto:rwa@localhost"
        ).strip()
        if not subject.startswith("mailto:"):
            subject = f"mailto:{subject}"
    if pub and priv:
        return {"publicKey": pub, "privateKey": priv, "subject": subject}
    pub, priv = _generate_vapid_pair()
    os.environ["RWA_VAPID_PUBLIC_KEY"] = pub
    os.environ["RWA_VAPID_PRIVATE_KEY"] = priv
    os.environ["RWA_VAPID_SUBJECT"] = subject
    existing = ""
    if path.is_file():
        try:
            existing = path.read_text(encoding="utf-8")
        except OSError:
            existing = ""
    # Preserve unrelated keys
    lines = [
        "# Web Push VAPID keys for Himuda Housing Colony Sanyard (do NOT commit real keys).",
        "# Generated automatically on first use; redeploy preserves this file.",
        f"RWA_VAPID_PUBLIC_KEY={pub}",
        f"RWA_VAPID_PRIVATE_KEY={priv}",
        f"RWA_VAPID_SUBJECT={subject}",
    ]
    for raw in existing.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key = line.partition("=")[0].strip()
        if key.startswith("RWA_VAPID_"):
            continue
        lines.append(raw.rstrip("\n"))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return {"publicKey": pub, "privateKey": priv, "subject": subject}


def load_vapid_config(site_root: pathlib.Path) -> dict[str, str]:
    return ensure_vapid_keys(site_root)


def public_vapid_info(site_root: pathlib.Path) -> dict[str, str]:
    cfg = ensure_vapid_keys(site_root)
    return {"publicKey": cfg["publicKey"], "subject": cfg["subject"]}


def default_prefs() -> dict[str, bool]:
    return {k: True for k in PREF_KEYS}


def get_prefs(conn: sqlite3.Connection, member_id: str | None, house_id: str) -> dict[str, Any]:
    ensure_messages_and_push_tables(conn)
    if not member_id:
        return {"memberId": None, "houseId": house_id, **default_prefs()}
    row = conn.execute(
        "SELECT * FROM notification_prefs WHERE member_id = ?",
        (member_id,),
    ).fetchone()
    if not row:
        return {"memberId": member_id, "houseId": house_id, **default_prefs()}
    return {
        "memberId": member_id,
        "houseId": row["house_id"],
        **{k: bool(row[k]) if k in row.keys() else True for k in PREF_KEYS},
        "updatedAt": row["updated_at"],
    }


def save_prefs(
    conn: sqlite3.Connection,
    *,
    member_id: str,
    house_id: str,
    prefs: dict,
) -> dict[str, Any]:
    ensure_messages_and_push_tables(conn)
    if not member_id:
        raise ValueError("Member identity required for notification preferences")
    now = utc_now()
    vals = {k: 1 if prefs.get(k, True) else 0 for k in PREF_KEYS}
    conn.execute(
        """
        INSERT INTO notification_prefs(
          member_id, house_id, messages, notices, concerns, dues, treasury, no_dues, no_objection, parking, resolutions, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(member_id) DO UPDATE SET
          house_id = excluded.house_id,
          messages = excluded.messages,
          notices = excluded.notices,
          concerns = excluded.concerns,
          dues = excluded.dues,
          treasury = excluded.treasury,
          no_dues = excluded.no_dues,
          no_objection = excluded.no_objection,
          parking = excluded.parking,
          resolutions = excluded.resolutions,
          updated_at = excluded.updated_at
        """,
        (
            member_id,
            house_id,
            vals["messages"],
            vals["notices"],
            vals["concerns"],
            vals["dues"],
            vals["treasury"],
            vals["no_dues"],
            vals["no_objection"],
            vals["parking"],
            vals["resolutions"],
            now,
        ),
    )
    conn.commit()
    return get_prefs(conn, member_id, house_id)


def upsert_subscription(
    conn: sqlite3.Connection,
    *,
    actor: dict,
    subscription: dict,
    user_agent: str = "",
) -> dict:
    ensure_messages_and_push_tables(conn)
    endpoint = (subscription.get("endpoint") or "").strip()
    keys = subscription.get("keys") or {}
    p256dh = (keys.get("p256dh") or "").strip()
    auth = (keys.get("auth") or "").strip()
    if not endpoint or not p256dh or not auth:
        raise ValueError("Invalid push subscription")
    house_id = (actor.get("houseId") or "").strip()
    if not house_id:
        raise ValueError("House required")
    member_id = actor.get("memberId")
    now = utc_now()
    existing = conn.execute(
        "SELECT id FROM push_subscriptions WHERE endpoint = ?",
        (endpoint,),
    ).fetchone()
    sub_id = existing["id"] if existing else f"ps_{secrets.token_hex(8)}"
    if existing:
        conn.execute(
            """
            UPDATE push_subscriptions
            SET p256dh = ?, auth = ?, member_id = ?, house_id = ?, user_agent = ?, updated_at = ?
            WHERE id = ?
            """,
            (p256dh, auth, member_id, house_id, (user_agent or "")[:240], now, sub_id),
        )
    else:
        conn.execute(
            """
            INSERT INTO push_subscriptions(
              id, endpoint, p256dh, auth, member_id, house_id, user_agent, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                sub_id,
                endpoint,
                p256dh,
                auth,
                member_id,
                house_id,
                (user_agent or "")[:240],
                now,
                now,
            ),
        )
    conn.commit()
    return {"id": sub_id, "endpoint": endpoint, "houseId": house_id, "memberId": member_id}


def delete_subscription(conn: sqlite3.Connection, *, endpoint: str = "", member_id: str | None = None) -> int:
    ensure_messages_and_push_tables(conn)
    if endpoint:
        cur = conn.execute("DELETE FROM push_subscriptions WHERE endpoint = ?", (endpoint.strip(),))
    elif member_id:
        cur = conn.execute("DELETE FROM push_subscriptions WHERE member_id = ?", (member_id,))
    else:
        return 0
    conn.commit()
    return int(cur.rowcount or 0)


def subscription_status(conn: sqlite3.Connection, actor: dict) -> dict:
    ensure_messages_and_push_tables(conn)
    member_id = actor.get("memberId")
    house_id = actor.get("houseId")
    if member_id:
        n = conn.execute(
            "SELECT COUNT(*) AS n FROM push_subscriptions WHERE member_id = ?",
            (member_id,),
        ).fetchone()["n"]
    else:
        n = conn.execute(
            "SELECT COUNT(*) AS n FROM push_subscriptions WHERE house_id = ?",
            (house_id,),
        ).fetchone()["n"]
    return {
        "subscribed": int(n) > 0,
        "deviceCount": int(n),
        "prefs": get_prefs(conn, member_id, house_id or ""),
    }


def _pref_allows(conn: sqlite3.Connection, member_id: str | None, house_id: str, pref_key: str) -> bool:
    if pref_key not in PREF_KEYS:
        return True
    prefs = get_prefs(conn, member_id, house_id)
    return bool(prefs.get(pref_key, True))


def _member_house_id(conn: sqlite3.Connection, member_id: str | None) -> str:
    mid = str(member_id or "").strip()
    if not mid:
        return ""
    try:
        row = conn.execute(
            "SELECT house_id FROM household_members WHERE id = ?",
            (mid,),
        ).fetchone()
    except sqlite3.OperationalError:
        return ""
    return str((row["house_id"] if row else "") or "").strip()


def _entitlement_houses(conn: sqlite3.Connection, key: str) -> set[str]:
    houses: set[str] = set()
    if not key:
        return houses
    try:
        import rwa_entitlements as entitlements
    except ImportError:
        entitlements = None
    try:
        grant_rows = conn.execute(
            "SELECT house_id FROM resident_entitlements WHERE entitlement = ?",
            (key,),
        ).fetchall()
        for r in grant_rows:
            houses.add(r["house_id"])
    except sqlite3.OperationalError:
        return houses
    if entitlements and key not in getattr(entitlements, "EXPLICIT_GRANT_ENTITLEMENTS", frozenset()):
        for r in conn.execute(
            """
            SELECT house_id FROM residents
            WHERE status = 'active' AND role = 'admin' AND house_id != ?
            """,
            (SUPERADMIN_HOUSE_ID,),
        ).fetchall():
            houses.add(r["house_id"])
    return {h for h in houses if h and h not in SYSTEM_HOUSE_IDS}


def _resolve_audience_houses(
    conn: sqlite3.Connection,
    audience: dict,
    *,
    exclude_member_id: str | None = None,
) -> list[str]:
    """Plot ids that should receive an in-app inbox row (even without a push subscription)."""
    atype = (audience.get("type") or "all").strip()
    houses: set[str] = set()
    if atype == "all":
        rows = conn.execute(
            "SELECT house_id FROM residents WHERE status = 'active'"
        ).fetchall()
        houses = {r["house_id"] for r in rows}
    elif atype == "houses":
        houses = {
            str(h).strip()
            for h in (audience.get("houseIds") or [])
            if str(h).strip()
        }
    elif atype == "members":
        ids = [str(m).strip() for m in (audience.get("memberIds") or []) if str(m).strip()]
        for mid in ids:
            hid = _member_house_id(conn, mid)
            if hid:
                houses.add(hid)
    elif atype == "entitlement":
        houses = _entitlement_houses(conn, (audience.get("key") or "").strip())
    houses -= SYSTEM_HOUSE_IDS
    skip = _member_house_id(conn, exclude_member_id)
    if skip:
        houses.discard(skip)
    return sorted(h for h in houses if h)


def fanout_inbox(
    conn: sqlite3.Connection,
    *,
    event_type: str,
    pref_key: str,
    title: str,
    body: str,
    url: str,
    audience: dict,
    exclude_member_id: str | None,
    outbox_id: str,
) -> int:
    """Write one inbox row per audience plot. Skips chat / test / resolution ballots."""
    et = (event_type or "").strip()
    if et in INBOX_SKIP_TYPES:
        return 0
    ensure_messages_and_push_tables(conn)
    houses = _resolve_audience_houses(conn, audience, exclude_member_id=exclude_member_id)
    if not houses:
        return 0
    now = utc_now()
    rows = [
        (
            f"ni_{secrets.token_hex(8)}",
            hid,
            et,
            pref_key,
            title,
            body,
            url,
            outbox_id,
            now,
        )
        for hid in houses
    ]
    conn.executemany(
        """
        INSERT INTO notification_inbox(
          id, house_id, event_type, pref_key, title, body, url, outbox_id, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    cutoff_offset = max(INBOX_KEEP_PER_HOUSE - 1, 0)
    for hid in houses:
        cutoff = conn.execute(
            """
            SELECT created_at FROM notification_inbox
            WHERE house_id = ?
            ORDER BY created_at DESC
            LIMIT 1 OFFSET ?
            """,
            (hid, cutoff_offset),
        ).fetchone()
        if cutoff:
            conn.execute(
                "DELETE FROM notification_inbox WHERE house_id = ? AND created_at < ?",
                (hid, cutoff["created_at"]),
            )
    conn.commit()
    return len(rows)


def _inbox_item(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "eventType": row["event_type"],
        "title": row["title"],
        "body": row["body"] or "",
        "url": row["url"] or "/",
        "readAt": row["read_at"] or "",
        "createdAt": row["created_at"] or "",
    }


def list_inbox(conn: sqlite3.Connection, actor: dict, *, limit: int = 40) -> dict[str, Any]:
    ensure_messages_and_push_tables(conn)
    house_id = str((actor or {}).get("houseId") or "").strip()
    if not house_id or house_id in SYSTEM_HOUSE_IDS:
        return {"items": [], "unreadCount": 0}
    rows = conn.execute(
        """
        SELECT * FROM notification_inbox
        WHERE house_id = ?
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (house_id, max(1, min(int(limit), 80))),
    ).fetchall()
    unread = conn.execute(
        """
        SELECT COUNT(*) AS n FROM notification_inbox
        WHERE house_id = ? AND read_at IS NULL
        """,
        (house_id,),
    ).fetchone()["n"]
    return {"items": [_inbox_item(r) for r in rows], "unreadCount": int(unread or 0)}


def mark_inbox_read(
    conn: sqlite3.Connection,
    actor: dict,
    ids: list[str] | None = None,
) -> dict[str, Any]:
    ensure_messages_and_push_tables(conn)
    house_id = str((actor or {}).get("houseId") or "").strip()
    if not house_id or house_id in SYSTEM_HOUSE_IDS:
        return {"items": [], "unreadCount": 0}
    now = utc_now()
    clean_ids = [str(i).strip() for i in (ids or []) if str(i).strip()]
    if clean_ids:
        placeholders = ",".join("?" * len(clean_ids))
        conn.execute(
            f"""
            UPDATE notification_inbox
            SET read_at = ?
            WHERE house_id = ? AND read_at IS NULL AND id IN ({placeholders})
            """,
            [now, house_id, *clean_ids],
        )
    else:
        conn.execute(
            """
            UPDATE notification_inbox
            SET read_at = ?
            WHERE house_id = ? AND read_at IS NULL
            """,
            (now, house_id),
        )
    conn.commit()
    return list_inbox(conn, actor)


def list_notifications(conn: sqlite3.Connection, actor: dict) -> dict[str, Any]:
    """Pending resolution votes + inbox alerts for the signed-in plot."""
    inbox = list_inbox(conn, actor)
    votes: dict[str, Any] = {"pending": [], "recent": []}
    try:
        import rwa_resolution_votes

        votes = rwa_resolution_votes.list_my_ballots(conn, actor)
    except Exception:
        pass
    pending = votes.get("pending") or []
    recent = votes.get("recent") or []
    unread = len(pending) + int(inbox.get("unreadCount") or 0)
    return {
        "pending": pending,
        "recent": recent,
        "items": inbox.get("items") or [],
        "unreadCount": unread,
        "inboxUnread": inbox.get("unreadCount") or 0,
    }


def _resolve_subscription_rows(
    conn: sqlite3.Connection,
    audience: dict,
    *,
    pref_key: str,
    exclude_member_id: str | None = None,
) -> list[sqlite3.Row]:
    ensure_messages_and_push_tables(conn)
    atype = (audience.get("type") or "all").strip()
    rows: list[sqlite3.Row] = []

    if atype == "all":
        rows = list(
            conn.execute(
                """
                SELECT * FROM push_subscriptions
                WHERE house_id != ?
                """,
                (SUPERADMIN_HOUSE_ID,),
            ).fetchall()
        )
    elif atype == "houses":
        ids = [str(h).strip() for h in (audience.get("houseIds") or []) if str(h).strip()]
        if not ids:
            return []
        placeholders = ",".join("?" * len(ids))
        rows = list(
            conn.execute(
                f"SELECT * FROM push_subscriptions WHERE house_id IN ({placeholders})",
                ids,
            ).fetchall()
        )
    elif atype == "members":
        ids = [str(m).strip() for m in (audience.get("memberIds") or []) if str(m).strip()]
        if not ids:
            return []
        placeholders = ",".join("?" * len(ids))
        rows = list(
            conn.execute(
                f"SELECT * FROM push_subscriptions WHERE member_id IN ({placeholders})",
                ids,
            ).fetchall()
        )
    elif atype == "entitlement":
        houses = _entitlement_houses(conn, (audience.get("key") or "").strip())
        if not houses:
            return []
        placeholders = ",".join("?" * len(houses))
        rows = list(
            conn.execute(
                f"SELECT * FROM push_subscriptions WHERE house_id IN ({placeholders})",
                list(houses),
            ).fetchall()
        )
    else:
        return []

    out = []
    for row in rows:
        mid = row["member_id"]
        if exclude_member_id and mid and mid == exclude_member_id:
            continue
        if not _pref_allows(conn, mid, row["house_id"], pref_key):
            continue
        out.append(row)
    return out


def _send_one(site_root: pathlib.Path, row: sqlite3.Row, payload: dict) -> str | None:
    """Return None on success, error string on failure. Deletes dead subs."""
    cfg = ensure_vapid_keys(site_root)
    try:
        from pywebpush import webpush, WebPushException
    except ImportError as exc:
        return f"pywebpush missing: {exc}"

    subscription_info = {
        "endpoint": row["endpoint"],
        "keys": {"p256dh": row["p256dh"], "auth": row["auth"]},
    }
    try:
        webpush(
            subscription_info=subscription_info,
            data=json.dumps(payload, ensure_ascii=False),
            vapid_private_key=cfg["privateKey"],
            vapid_claims={"sub": cfg["subject"]},
            ttl=86400,
        )
        return None
    except WebPushException as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status in (404, 410):
            return "gone"
        return str(exc)[:400]
    except Exception as exc:  # noqa: BLE001
        return str(exc)[:400]


def enqueue_push(
    conn: sqlite3.Connection,
    site_root: pathlib.Path,
    *,
    event_type: str,
    audience: dict,
    title: str,
    body: str,
    url: str = "/",
    exclude_member_id: str | None = None,
    send_now: bool = True,
) -> dict[str, Any]:
    """Queue (and optionally send) a push notification."""
    ensure_messages_and_push_tables(conn)
    ensure_vapid_keys(site_root)
    et = (event_type or "test").strip()
    pref_key = EVENT_PREF.get(et, "messages")
    title = (title or "Himuda Housing Colony Sanyard").strip()[:120]
    body = (body or "").strip()[:240]
    url = (url or "/").strip()[:400]
    now = utc_now()
    outbox_id = f"po_{secrets.token_hex(8)}"
    payload = {
        "title": title,
        "body": body,
        "url": url,
        "eventType": et,
    }
    conn.execute(
        """
        INSERT INTO push_outbox(
          id, event_type, pref_key, audience_json, title, body, url, payload_json, status, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?)
        """,
        (
            outbox_id,
            et,
            pref_key,
            json.dumps(audience, ensure_ascii=False),
            title,
            body,
            url,
            json.dumps(payload, ensure_ascii=False),
            now,
        ),
    )
    conn.commit()

    try:
        fanout_inbox(
            conn,
            event_type=et,
            pref_key=pref_key,
            title=title,
            body=body,
            url=url,
            audience=audience,
            exclude_member_id=exclude_member_id,
            outbox_id=outbox_id,
        )
    except Exception:
        pass

    if not send_now:
        return {"id": outbox_id, "status": "queued", "sent": 0}

    rows = _resolve_subscription_rows(
        conn, audience, pref_key=pref_key, exclude_member_id=exclude_member_id
    )
    if not rows:
        conn.execute(
            "UPDATE push_outbox SET status = 'skipped', sent_at = ? WHERE id = ?",
            (utc_now(), outbox_id),
        )
        conn.commit()
        return {"id": outbox_id, "status": "skipped", "sent": 0}

    conn.execute(
        "UPDATE push_outbox SET status = 'sending' WHERE id = ?",
        (outbox_id,),
    )
    conn.commit()

    sent = 0
    errors: list[str] = []
    for row in rows:
        err = _send_one(site_root, row, payload)
        if err == "gone":
            conn.execute("DELETE FROM push_subscriptions WHERE id = ?", (row["id"],))
            conn.commit()
            continue
        if err:
            errors.append(err)
            continue
        sent += 1

    status = "sent" if sent else ("failed" if errors else "skipped")
    conn.execute(
        """
        UPDATE push_outbox SET status = ?, error = ?, sent_at = ? WHERE id = ?
        """,
        (status, ("; ".join(errors[:3]) if errors else None), utc_now(), outbox_id),
    )
    conn.commit()
    return {"id": outbox_id, "status": status, "sent": sent, "errors": errors[:5]}


def send_test_push(conn: sqlite3.Connection, site_root: pathlib.Path, actor: dict) -> dict:
    mid = actor.get("memberId")
    hid = actor.get("houseId")
    audience = {"type": "members", "memberIds": [mid]} if mid else {"type": "houses", "houseIds": [hid]}
    return enqueue_push(
        conn,
        site_root,
        event_type="test",
        audience=audience,
        title="Himuda Housing Colony Sanyard",
        body="Test notification — push is working on this device.",
        url="/#profile",
    )
