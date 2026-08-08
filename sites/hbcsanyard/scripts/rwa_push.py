"""Web Push (VAPID) subscriptions, prefs, and fan-out for the RWA portal."""

from __future__ import annotations

import base64
import json
import os
import pathlib
import secrets
import sqlite3
from typing import Any

from init_rwa_db import SUPERADMIN_HOUSE_ID, ensure_messages_and_push_tables, utc_now

PREF_KEYS = ("messages", "notices", "concerns", "dues", "treasury", "no_dues", "no_objection")
EVENT_PREF = {
    "message": "messages",
    "notice": "notices",
    "concern": "concerns",
    "dues": "dues",
    "treasury": "treasury",
    "no_dues": "no_dues",
    "no_objection": "no_objection",
    "test": "messages",
}


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
        "# Web Push VAPID keys for HBC Sanyard (do NOT commit real keys).",
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
          member_id, house_id, messages, notices, concerns, dues, treasury, no_dues, no_objection, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(member_id) DO UPDATE SET
          house_id = excluded.house_id,
          messages = excluded.messages,
          notices = excluded.notices,
          concerns = excluded.concerns,
          dues = excluded.dues,
          treasury = excluded.treasury,
          no_dues = excluded.no_dues,
          no_objection = excluded.no_objection,
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
        key = (audience.get("key") or "").strip()
        if not key:
            return []
        try:
            import rwa_entitlements as entitlements
        except ImportError:
            return []
        # Collect house_ids that have the entitlement (EC admin implicit + grants)
        houses = set()
        grant_rows = conn.execute(
            "SELECT house_id FROM resident_entitlements WHERE entitlement = ?",
            (key,),
        ).fetchall()
        for r in grant_rows:
            houses.add(r["house_id"])
        # EC admins get implicit entitlements except explicit-only ones
        if key not in getattr(entitlements, "EXPLICIT_GRANT_ENTITLEMENTS", frozenset()):
            for r in conn.execute(
                """
                SELECT house_id FROM residents
                WHERE status = 'active' AND role = 'admin' AND house_id != ?
                """,
                (SUPERADMIN_HOUSE_ID,),
            ).fetchall():
                houses.add(r["house_id"])
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
    title = (title or "HBC Sanyard").strip()[:120]
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
        title="HBC Sanyard",
        body="Test notification — push is working on this device.",
        url="/#profile",
    )
