"""Colony message center + plot-to-plot DMs."""

from __future__ import annotations

import pathlib
import re
import secrets
import sqlite3
from typing import Any

from init_rwa_db import (
    COLONY_THREAD_ID,
    SUPERADMIN_HOUSE_ID,
    ADHOC_GATE_HOUSE_ID,
    ensure_messages_and_push_tables,
    ensure_msg_likes_and_ai,
    normalize_house_id,
    section_plot_sort_key,
    utc_now,
)

MSG_MAX_BYTES = 5_000_000
MSG_MAX_ATTACHMENTS = 3
MSG_IMAGE_MAX_EDGE = 1600
MSG_IMAGE_QUALITY = 72
BODY_MAX = 4000


def messages_root(site_root: pathlib.Path) -> pathlib.Path:
    root = pathlib.Path(site_root) / "data" / "messages"
    root.mkdir(parents=True, exist_ok=True)
    return root


def attachment_path(site_root: pathlib.Path, thread_id: str, message_id: str, filename: str) -> pathlib.Path:
    return messages_root(site_root) / thread_id / message_id / filename


def _dm_pair(house_a: str, house_b: str) -> tuple[str, str]:
    a = normalize_house_id(house_a)
    b = normalize_house_id(house_b)
    if not a or not b:
        raise ValueError("Both plots are required")
    if a == b:
        raise ValueError("Cannot message your own plot")
    return (a, b) if a < b else (b, a)


def can_moderate(actor: dict | None) -> bool:
    if not actor:
        return False
    if actor.get("superAdmin"):
        return True
    try:
        import rwa_entitlements as entitlements

        return entitlements.actor_has(actor, "moderate_messages") or entitlements.actor_has(
            actor, "manage_notices"
        )
    except Exception:
        return False


def can_access_thread(conn: sqlite3.Connection, thread: dict | sqlite3.Row, actor: dict) -> bool:
    kind = thread["kind"] if isinstance(thread, dict) else thread["kind"]
    if kind == "colony":
        return True
    if kind == "ai":
        owner = thread["owner_member_id"] if isinstance(thread, dict) else thread["owner_member_id"]
        mid = (actor.get("memberId") or "").strip()
        return bool(mid and owner and mid == owner)
    house = (actor.get("houseId") or "").strip()
    if actor.get("superAdmin"):
        return True
    ha = thread["house_a"] if isinstance(thread, dict) else thread["house_a"]
    hb = thread["house_b"] if isinstance(thread, dict) else thread["house_b"]
    return house in {ha, hb}


def _member_name(conn: sqlite3.Connection, member_id: str | None, house_id: str) -> str:
    if member_id:
        row = conn.execute(
            "SELECT name FROM household_members WHERE id = ?",
            (member_id,),
        ).fetchone()
        if row and row["name"]:
            return row["name"]
    row = conn.execute("SELECT name FROM residents WHERE house_id = ?", (house_id,)).fetchone()
    return (row["name"] if row else "") or house_id


def _attachments_for(conn: sqlite3.Connection, message_id: str) -> list[dict]:
    rows = conn.execute(
        """
        SELECT id, message_id, thread_id, filename, original_name, mime, size_bytes, width, height, created_at
        FROM msg_attachments WHERE message_id = ? ORDER BY created_at ASC
        """,
        (message_id,),
    ).fetchall()
    out = []
    for r in rows:
        out.append({
            "id": r["id"],
            "messageId": r["message_id"],
            "threadId": r["thread_id"],
            "filename": r["filename"],
            "originalName": r["original_name"],
            "mime": r["mime"],
            "sizeBytes": r["size_bytes"],
            "width": r["width"],
            "height": r["height"],
            "url": f"/api/rwa/messages/attachments/{r['id']}",
            "createdAt": r["created_at"],
        })
    return out


def _photo_for_member(conn: sqlite3.Connection, member_id: str | None) -> dict:
    mid = (member_id or "").strip()
    if not mid:
        return {"hasPhoto": False, "photoUrl": ""}
    try:
        from rwa_household import photo_fields_for_member
    except ImportError:
        return {"hasPhoto": False, "photoUrl": ""}
    row = conn.execute(
        "SELECT id, photo_filename FROM household_members WHERE id = ? AND status = 'active'",
        (mid,),
    ).fetchone()
    if not row:
        return {"hasPhoto": False, "photoUrl": ""}
    return photo_fields_for_member(row["id"], row["photo_filename"])


def _photo_map_for_members(conn: sqlite3.Connection, member_ids: list[str]) -> dict[str, dict]:
    ids = [m for m in { (x or "").strip() for x in member_ids } if m]
    if not ids:
        return {}
    try:
        from rwa_household import photo_fields_for_member
    except ImportError:
        return {}
    placeholders = ",".join("?" * len(ids))
    rows = conn.execute(
        f"""
        SELECT id, photo_filename FROM household_members
        WHERE status = 'active' AND id IN ({placeholders})
        """,
        ids,
    ).fetchall()
    return {
        str(r["id"]): photo_fields_for_member(r["id"], r["photo_filename"])
        for r in rows
    }


def _like_stats(conn: sqlite3.Connection, message_id: str, member_id: str | None) -> dict:
    ensure_msg_likes_and_ai(conn)
    count = conn.execute(
        "SELECT COUNT(*) AS n FROM msg_likes WHERE message_id = ?",
        (message_id,),
    ).fetchone()["n"]
    liked = False
    if member_id:
        liked = bool(
            conn.execute(
                "SELECT 1 FROM msg_likes WHERE message_id = ? AND member_id = ?",
                (message_id, member_id),
            ).fetchone()
        )
    return {"likeCount": int(count), "likedByMe": liked}


def _public_message(
    conn: sqlite3.Connection,
    row: sqlite3.Row,
    *,
    include_hidden: bool = False,
    photo_map: dict[str, dict] | None = None,
    viewer_member_id: str | None = None,
) -> dict | None:
    if row["status"] == "deleted":
        return None
    mid = row["author_member_id"]
    if photo_map is not None:
        photo = photo_map.get(mid or "", {"hasPhoto": False, "photoUrl": ""})
    else:
        photo = _photo_for_member(conn, mid)
    likes = _like_stats(conn, row["id"], viewer_member_id)
    if row["status"] == "hidden" and not include_hidden:
        return {
            "id": row["id"],
            "threadId": row["thread_id"],
            "status": "hidden",
            "body": "",
            "createdAt": row["created_at"],
            "hidden": True,
            "hasPhoto": False,
            "photoUrl": "",
            "likeCount": likes["likeCount"],
            "likedByMe": likes["likedByMe"],
            "isAi": False,
        }
    is_ai = bool(row["is_ai"]) if "is_ai" in row.keys() else False
    edited_at = ""
    if "edited_at" in row.keys() and row["edited_at"]:
        edited_at = row["edited_at"]
    return {
        "id": row["id"],
        "threadId": row["thread_id"],
        "authorMemberId": mid,
        "houseId": row["house_id"],
        "authorName": row["author_name"],
        "body": row["body"] if row["status"] == "active" else "",
        "status": row["status"],
        "replyToId": row["reply_to_id"],
        "createdAt": row["created_at"],
        "editedAt": edited_at,
        "attachments": _attachments_for(conn, row["id"]) if row["status"] == "active" else [],
        "hidden": row["status"] == "hidden",
        "isAi": is_ai,
        "hasPhoto": bool(photo.get("hasPhoto")) and not is_ai,
        "photoUrl": (photo.get("photoUrl") or "") if not is_ai else "",
        "likeCount": likes["likeCount"],
        "likedByMe": likes["likedByMe"],
    }


def _unread_count(conn: sqlite3.Connection, thread_id: str, member_id: str | None) -> int:
    if not member_id:
        return 0
    read = conn.execute(
        "SELECT last_read_message_id, last_read_at FROM msg_reads WHERE member_id = ? AND thread_id = ?",
        (member_id, thread_id),
    ).fetchone()
    if not read or not read["last_read_at"]:
        row = conn.execute(
            """
            SELECT COUNT(*) AS n FROM msg_messages
            WHERE thread_id = ? AND status = 'active'
            """,
            (thread_id,),
        ).fetchone()
        return int(row["n"])
    row = conn.execute(
        """
        SELECT COUNT(*) AS n FROM msg_messages
        WHERE thread_id = ? AND status = 'active' AND created_at > ?
        """,
        (thread_id, read["last_read_at"]),
    ).fetchone()
    return int(row["n"])


def _last_message_preview(conn: sqlite3.Connection, thread_id: str) -> dict | None:
    row = conn.execute(
        """
        SELECT id, body, author_name, author_member_id, house_id, created_at, status
        FROM msg_messages
        WHERE thread_id = ? AND status = 'active'
        ORDER BY created_at DESC LIMIT 1
        """,
        (thread_id,),
    ).fetchone()
    if not row:
        return None
    body = (row["body"] or "").strip()
    if len(body) > 80:
        body = body[:77] + "…"
    photo = _photo_for_member(conn, row["author_member_id"])
    return {
        "id": row["id"],
        "body": body or "[attachment]",
        "authorName": row["author_name"],
        "authorMemberId": row["author_member_id"],
        "houseId": row["house_id"],
        "createdAt": row["created_at"],
        "hasPhoto": bool(photo.get("hasPhoto")),
        "photoUrl": photo.get("photoUrl") or "",
    }


def _thread_title(conn: sqlite3.Connection, thread: sqlite3.Row, viewer_house: str) -> str:
    if thread["kind"] == "colony":
        return thread["title"] or "Colony channel"
    if thread["kind"] == "ai":
        return thread["title"] or "AI Assistant"
    other = thread["house_b"] if thread["house_a"] == viewer_house else thread["house_a"]
    row = conn.execute(
        "SELECT name, plot_no, section FROM residents WHERE house_id = ?",
        (other,),
    ).fetchone()
    if row:
        label = row["name"] or other
        plot = row["plot_no"] or other
        return f"{plot} · {label}"
    return other or "Direct message"


def _public_thread(conn: sqlite3.Connection, thread: sqlite3.Row, actor: dict) -> dict:
    member_id = actor.get("memberId")
    house = actor.get("houseId") or ""
    peer_house = None
    peer_photo = {"hasPhoto": False, "photoUrl": ""}
    if thread["kind"] == "dm":
        peer_house = thread["house_b"] if thread["house_a"] == house else thread["house_a"]
        try:
            from rwa_household import primary_member_photo_map

            peer_photo = primary_member_photo_map(conn).get(peer_house or "", peer_photo)
        except Exception:
            pass
    return {
        "id": thread["id"],
        "kind": thread["kind"],
        "houseA": thread["house_a"],
        "houseB": thread["house_b"],
        "title": _thread_title(conn, thread, house),
        "pinnedMessageId": thread["pinned_message_id"],
        "createdAt": thread["created_at"],
        "updatedAt": thread["updated_at"],
        "unread": _unread_count(conn, thread["id"], member_id),
        "lastMessage": _last_message_preview(conn, thread["id"]),
        "peerHouseId": peer_house,
        "peerHasPhoto": bool(peer_photo.get("hasPhoto")),
        "peerPhotoUrl": peer_photo.get("photoUrl") or "",
    }


def ensure_colony_thread(conn: sqlite3.Connection) -> str:
    ensure_messages_and_push_tables(conn)
    ensure_msg_likes_and_ai(conn)
    return COLONY_THREAD_ID


def open_ai_thread(conn: sqlite3.Connection, actor: dict) -> dict:
    """Private per-member AI assistant thread (not visible to anyone else)."""
    ensure_messages_and_push_tables(conn)
    ensure_msg_likes_and_ai(conn)
    mid = (actor.get("memberId") or "").strip()
    house = (actor.get("houseId") or "").strip()
    if not mid:
        raise ValueError("Member identity required for AI Assistant")
    if not house:
        raise ValueError("House required")
    now = utc_now()
    row = conn.execute(
        "SELECT * FROM msg_threads WHERE kind = 'ai' AND owner_member_id = ?",
        (mid,),
    ).fetchone()
    if row:
        return _public_thread(conn, row, actor)
    tid = f"ai_{mid}"
    conn.execute(
        """
        INSERT INTO msg_threads(
          id, kind, house_a, house_b, title, pinned_message_id, owner_member_id, created_at, updated_at
        ) VALUES (?, 'ai', ?, NULL, 'AI Assistant', NULL, ?, ?, ?)
        """,
        (tid, house, mid, now, now),
    )
    # Seed a welcome message from the assistant
    welcome = (
        "Hi — I’m your private RWA Assistant. Ask about your dues, concerns, EC members, "
        "notices, or Information Centre documents. Published Info Centre files are included "
        "automatically when you ask — publish a doc and I can use it on the next question. "
        "Only you can see this chat."
    )
    conn.execute(
        """
        INSERT INTO msg_messages(
          id, thread_id, author_member_id, house_id, author_name, body, status, reply_to_id, is_ai, created_at
        ) VALUES (?, ?, NULL, ?, ?, ?, 'active', NULL, 1, ?)
        """,
        (f"mm_{secrets.token_hex(8)}", tid, "__AI__", "RWA Assistant", welcome, now),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM msg_threads WHERE id = ?", (tid,)).fetchone()
    return _public_thread(conn, row, actor)


def list_threads(conn: sqlite3.Connection, actor: dict) -> list[dict]:
    ensure_messages_and_push_tables(conn)
    ensure_msg_likes_and_ai(conn)
    house = (actor.get("houseId") or "").strip()
    out = []
    # Private AI assistant first (only for members)
    if actor.get("memberId") and house and house != SUPERADMIN_HOUSE_ID:
        try:
            out.append(open_ai_thread(conn, actor))
        except ValueError:
            pass
    colony = conn.execute("SELECT * FROM msg_threads WHERE id = ?", (COLONY_THREAD_ID,)).fetchone()
    if colony:
        out.append(_public_thread(conn, colony, actor))
    if house and house != SUPERADMIN_HOUSE_ID:
        rows = conn.execute(
            """
            SELECT * FROM msg_threads
            WHERE kind = 'dm' AND (house_a = ? OR house_b = ?)
            ORDER BY updated_at DESC
            """,
            (house, house),
        ).fetchall()
        for r in rows:
            out.append(_public_thread(conn, r, actor))
    elif actor.get("superAdmin"):
        rows = conn.execute(
            "SELECT * FROM msg_threads WHERE kind = 'dm' ORDER BY updated_at DESC LIMIT 100"
        ).fetchall()
        for r in rows:
            out.append(_public_thread(conn, r, actor))
    return out


def get_thread(conn: sqlite3.Connection, thread_id: str, actor: dict) -> dict:
    ensure_messages_and_push_tables(conn)
    row = conn.execute("SELECT * FROM msg_threads WHERE id = ?", (thread_id,)).fetchone()
    if not row:
        raise ValueError("Thread not found")
    if not can_access_thread(conn, row, actor):
        raise PermissionError("Not allowed to view this thread")
    return _public_thread(conn, row, actor)


def open_dm(conn: sqlite3.Connection, actor: dict, peer_house_id: str) -> dict:
    ensure_messages_and_push_tables(conn)
    my = (actor.get("houseId") or "").strip()
    if not my or my == SUPERADMIN_HOUSE_ID:
        raise ValueError("Sign in as a plot to start a direct message")
    peer = normalize_house_id(peer_house_id)
    if not peer:
        raise ValueError("Peer plot is required")
    exists = conn.execute(
        "SELECT house_id FROM residents WHERE house_id = ? AND status = 'active'",
        (peer,),
    ).fetchone()
    if not exists:
        raise ValueError("Plot not found")
    a, b = _dm_pair(my, peer)
    now = utc_now()
    row = conn.execute(
        "SELECT * FROM msg_threads WHERE kind = 'dm' AND house_a = ? AND house_b = ?",
        (a, b),
    ).fetchone()
    if row:
        return _public_thread(conn, row, actor)
    tid = f"dm_{secrets.token_hex(8)}"
    conn.execute(
        """
        INSERT INTO msg_threads(id, kind, house_a, house_b, title, pinned_message_id, created_at, updated_at)
        VALUES (?, 'dm', ?, ?, NULL, NULL, ?, ?)
        """,
        (tid, a, b, now, now),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM msg_threads WHERE id = ?", (tid,)).fetchone()
    return _public_thread(conn, row, actor)


def list_messages(
    conn: sqlite3.Connection,
    actor: dict,
    thread_id: str,
    *,
    since_id: str | None = None,
    limit: int = 50,
) -> dict:
    ensure_messages_and_push_tables(conn)
    thread = conn.execute("SELECT * FROM msg_threads WHERE id = ?", (thread_id,)).fetchone()
    if not thread:
        raise ValueError("Thread not found")
    if not can_access_thread(conn, thread, actor):
        raise PermissionError("Not allowed")
    limit = max(1, min(int(limit or 50), 100))
    include_hidden = can_moderate(actor) and thread["kind"] == "colony"
    if since_id:
        anchor = conn.execute(
            "SELECT created_at FROM msg_messages WHERE id = ? AND thread_id = ?",
            (since_id, thread_id),
        ).fetchone()
        if not anchor:
            rows = []
        else:
            rows = conn.execute(
                """
                SELECT * FROM msg_messages
                WHERE thread_id = ? AND created_at > ? AND status != 'deleted'
                ORDER BY created_at ASC LIMIT ?
                """,
                (thread_id, anchor["created_at"], limit),
            ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT * FROM msg_messages
            WHERE thread_id = ? AND status != 'deleted'
            ORDER BY created_at DESC LIMIT ?
            """,
            (thread_id, limit),
        ).fetchall()
        rows = list(reversed(rows))

    messages = []
    viewer_mid = actor.get("memberId")
    photo_map = _photo_map_for_members(
        conn, [r["author_member_id"] for r in rows if r["author_member_id"]]
    )
    for r in rows:
        pub = _public_message(
            conn, r, include_hidden=include_hidden, photo_map=photo_map, viewer_member_id=viewer_mid
        )
        if pub:
            messages.append(pub)
    pinned = None
    if thread["pinned_message_id"]:
        prow = conn.execute(
            "SELECT * FROM msg_messages WHERE id = ?",
            (thread["pinned_message_id"],),
        ).fetchone()
        if prow:
            pinned = _public_message(
                conn, prow, include_hidden=True, viewer_member_id=viewer_mid
            )
    return {
        "thread": _public_thread(conn, thread, actor),
        "messages": messages,
        "pinned": pinned,
        "canModerate": can_moderate(actor) and thread["kind"] == "colony",
        "canCleanup": _can_cleanup_thread(thread, actor),
        "isAi": thread["kind"] == "ai",
    }


def _is_message_author(row: sqlite3.Row, actor: dict) -> bool:
    mid = (actor.get("memberId") or "").strip()
    house = (actor.get("houseId") or "").strip()
    author_mid = (row["author_member_id"] or "").strip() if row["author_member_id"] else ""
    if author_mid and mid:
        return author_mid == mid
    if house and row["house_id"] == house and not author_mid:
        return True
    return False


def _can_cleanup_thread(thread: sqlite3.Row | dict, actor: dict) -> bool:
    kind = thread["kind"] if not isinstance(thread, dict) else thread["kind"]
    if kind == "colony":
        return can_moderate(actor)
    if kind == "ai":
        owner = (
            thread["owner_member_id"]
            if not isinstance(thread, dict)
            else thread.get("owner_member_id")
        )
        mid = (actor.get("memberId") or "").strip()
        return bool(mid and owner and mid == owner)
    if kind == "dm":
        if actor.get("superAdmin"):
            return True
        house = (actor.get("houseId") or "").strip()
        ha = thread["house_a"] if not isinstance(thread, dict) else thread.get("house_a")
        hb = thread["house_b"] if not isinstance(thread, dict) else thread.get("house_b")
        return bool(house and house in {ha, hb})
    return False


def edit_message(
    conn: sqlite3.Connection,
    actor: dict,
    message_id: str,
    *,
    body: str,
) -> dict:
    """Author edits their own active (non-AI) message body."""
    ensure_messages_and_push_tables(conn)
    ensure_msg_likes_and_ai(conn)
    try:
        from rwa_household import actor_is_view_only
    except ImportError:
        actor_is_view_only = lambda a: bool(a.get("viewOnly")) and not a.get("superAdmin")  # noqa: E731
    if actor_is_view_only(actor):
        raise PermissionError("View-only access cannot edit messages")

    row = conn.execute("SELECT * FROM msg_messages WHERE id = ?", (message_id,)).fetchone()
    if not row or row["status"] == "deleted":
        raise ValueError("Message not found")
    if row["status"] != "active":
        raise ValueError("Only active messages can be edited")
    is_ai = bool(row["is_ai"]) if "is_ai" in row.keys() else False
    if is_ai:
        raise PermissionError("Assistant messages cannot be edited")

    thread = conn.execute("SELECT * FROM msg_threads WHERE id = ?", (row["thread_id"],)).fetchone()
    if not thread or not can_access_thread(conn, thread, actor):
        raise PermissionError("Not allowed")
    if thread["kind"] == "ai":
        raise PermissionError("AI chat questions cannot be edited — ask a new question")
    if not _is_message_author(row, actor) and not (
        can_moderate(actor) and thread["kind"] == "colony"
    ):
        raise PermissionError("Only the author can edit this message")

    text = (body or "").strip()
    if not text and not conn.execute(
        "SELECT 1 FROM msg_attachments WHERE message_id = ? LIMIT 1", (message_id,)
    ).fetchone():
        raise ValueError("Message cannot be empty")
    if len(text) > BODY_MAX:
        raise ValueError(f"Message too long (max {BODY_MAX} characters)")

    now = utc_now()
    conn.execute(
        "UPDATE msg_messages SET body = ?, edited_at = ? WHERE id = ?",
        (text, now, message_id),
    )
    conn.execute(
        "UPDATE msg_threads SET updated_at = ? WHERE id = ?",
        (now, row["thread_id"]),
    )
    conn.commit()
    updated = conn.execute("SELECT * FROM msg_messages WHERE id = ?", (message_id,)).fetchone()
    return _public_message(
        conn, updated, include_hidden=True, viewer_member_id=actor.get("memberId")
    ) or {"id": message_id, "body": text, "editedAt": now}


def delete_own_message(
    conn: sqlite3.Connection,
    actor: dict,
    message_id: str,
) -> dict:
    """Author soft-deletes their own message (colony / DM)."""
    ensure_messages_and_push_tables(conn)
    try:
        from rwa_household import actor_is_view_only
    except ImportError:
        actor_is_view_only = lambda a: bool(a.get("viewOnly")) and not a.get("superAdmin")  # noqa: E731
    if actor_is_view_only(actor):
        raise PermissionError("View-only access cannot delete messages")

    row = conn.execute("SELECT * FROM msg_messages WHERE id = ?", (message_id,)).fetchone()
    if not row or row["status"] == "deleted":
        raise ValueError("Message not found")
    is_ai = bool(row["is_ai"]) if "is_ai" in row.keys() else False
    if is_ai:
        raise PermissionError("Assistant messages cannot be deleted this way")

    thread = conn.execute("SELECT * FROM msg_threads WHERE id = ?", (row["thread_id"],)).fetchone()
    if not thread or not can_access_thread(conn, thread, actor):
        raise PermissionError("Not allowed")
    if thread["kind"] == "ai":
        raise PermissionError("Clear the AI chat instead of deleting single turns")
    if not _is_message_author(row, actor):
        raise PermissionError("Only the author can delete this message")

    conn.execute("UPDATE msg_messages SET status = 'deleted' WHERE id = ?", (message_id,))
    if thread["pinned_message_id"] == message_id:
        conn.execute("UPDATE msg_threads SET pinned_message_id = NULL WHERE id = ?", (thread["id"],))
    conn.execute(
        "UPDATE msg_threads SET updated_at = ? WHERE id = ?",
        (utc_now(), thread["id"]),
    )
    conn.commit()
    return {"ok": True, "id": message_id, "status": "deleted"}


def cleanup_thread(
    conn: sqlite3.Connection,
    site_root: pathlib.Path,
    actor: dict,
    thread_id: str,
    *,
    action: str,
    days: int | None = None,
) -> dict:
    """Clear messages in a channel.

    Colony: moderators. AI: thread owner. DM: either plot.
    Actions: clear_all | clear_hidden | older_than (requires days).
    """
    ensure_messages_and_push_tables(conn)
    thread = conn.execute("SELECT * FROM msg_threads WHERE id = ?", (thread_id,)).fetchone()
    if not thread:
        raise ValueError("Thread not found")
    if not can_access_thread(conn, thread, actor):
        raise PermissionError("Not allowed")
    if not _can_cleanup_thread(thread, actor):
        raise PermissionError("Cleanup permission required")

    action = (action or "").strip().lower()
    now = utc_now()
    deleted = 0

    if action == "clear_all":
        cur = conn.execute(
            """
            UPDATE msg_messages SET status = 'deleted'
            WHERE thread_id = ? AND status != 'deleted'
            """,
            (thread_id,),
        )
        deleted = cur.rowcount
        conn.execute(
            "UPDATE msg_threads SET pinned_message_id = NULL, updated_at = ? WHERE id = ?",
            (now, thread_id),
        )
    elif action == "clear_hidden":
        cur = conn.execute(
            """
            UPDATE msg_messages SET status = 'deleted'
            WHERE thread_id = ? AND status = 'hidden'
            """,
            (thread_id,),
        )
        deleted = cur.rowcount
        conn.execute("UPDATE msg_threads SET updated_at = ? WHERE id = ?", (now, thread_id))
    elif action == "older_than":
        try:
            n_days = int(days if days is not None else 30)
        except (TypeError, ValueError):
            raise ValueError("days must be a number") from None
        if n_days < 1 or n_days > 3650:
            raise ValueError("days must be between 1 and 3650")
        from datetime import datetime, timedelta, timezone

        cutoff_iso = (datetime.now(timezone.utc) - timedelta(days=n_days)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        cur = conn.execute(
            """
            UPDATE msg_messages SET status = 'deleted'
            WHERE thread_id = ? AND status != 'deleted' AND created_at < ?
            """,
            (thread_id, cutoff_iso),
        )
        deleted = cur.rowcount
        pin = thread["pinned_message_id"]
        if pin:
            still = conn.execute(
                "SELECT status FROM msg_messages WHERE id = ?", (pin,)
            ).fetchone()
            if not still or still["status"] == "deleted":
                conn.execute(
                    "UPDATE msg_threads SET pinned_message_id = NULL WHERE id = ?",
                    (thread_id,),
                )
        conn.execute("UPDATE msg_threads SET updated_at = ? WHERE id = ?", (now, thread_id))
    else:
        raise ValueError("Unknown cleanup action (use clear_all, clear_hidden, or older_than)")

    conn.commit()
    return {
        "ok": True,
        "action": action,
        "deleted": int(deleted or 0),
        "threadId": thread_id,
    }


def _optimize_image(raw: bytes) -> tuple[bytes, str, int | None, int | None]:
    from io import BytesIO

    try:
        from PIL import Image
    except ImportError as exc:  # pragma: no cover
        raise ValueError("Image processing unavailable") from exc
    try:
        img = Image.open(BytesIO(raw))
        img.load()
    except Exception as exc:  # noqa: BLE001
        raise ValueError("Could not read image") from exc
    if img.mode not in ("RGB", "L"):
        if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
            rgba = img.convert("RGBA")
            background = Image.new("RGB", rgba.size, (255, 255, 255))
            background.paste(rgba, mask=rgba.split()[-1])
            img = background
        else:
            img = img.convert("RGB")
    elif img.mode == "L":
        img = img.convert("RGB")
    w, h = img.size
    edge = max(w, h)
    if edge > MSG_IMAGE_MAX_EDGE:
        scale = MSG_IMAGE_MAX_EDGE / edge
        resample = Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS
        img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))), resample)
    buf = BytesIO()
    img.save(buf, format="WEBP", quality=MSG_IMAGE_QUALITY, method=4)
    data = buf.getvalue()
    if not data:
        raise ValueError("Could not encode image")
    return data, "image/webp", img.size[0], img.size[1]


def _prepare_upload(raw: bytes, content_type: str, original_name: str) -> tuple[bytes, str, str, int | None, int | None]:
    ctype = (content_type or "").split(";")[0].strip().lower()
    name_l = (original_name or "").lower()
    is_pdf = ctype == "application/pdf" or name_l.endswith(".pdf")
    is_image = ctype.startswith("image/") or bool(re.search(r"\.(jpe?g|png|webp|gif)$", name_l))
    if len(raw) > MSG_MAX_BYTES:
        raise ValueError(f"Each attachment must be under {MSG_MAX_BYTES // (1024 * 1024)} MB")
    if is_pdf:
        if not raw.startswith(b"%PDF"):
            raise ValueError("File does not look like a PDF")
        return raw, "application/pdf", "pdf", None, None
    if is_image:
        data, mime, w, h = _optimize_image(raw)
        return data, mime, "webp", w, h
    raise ValueError("Supported attachments: JPG, PNG, WebP, GIF, or PDF")


def post_message(
    conn: sqlite3.Connection,
    site_root: pathlib.Path,
    actor: dict,
    thread_id: str,
    *,
    body: str = "",
    reply_to_id: str | None = None,
    files: list[tuple[bytes, str, str]] | None = None,
) -> dict:
    ensure_messages_and_push_tables(conn)
    try:
        from rwa_household import actor_is_view_only
    except ImportError:
        actor_is_view_only = lambda a: bool(a.get("viewOnly")) and not a.get("superAdmin")  # noqa: E731

    if actor_is_view_only(actor):
        raise PermissionError("View-only access cannot post messages")

    thread = conn.execute("SELECT * FROM msg_threads WHERE id = ?", (thread_id,)).fetchone()
    if not thread:
        raise ValueError("Thread not found")
    if not can_access_thread(conn, thread, actor):
        raise PermissionError("Not allowed")

    house_id = (actor.get("houseId") or "").strip()
    if not house_id:
        raise ValueError("House required")
    text = (body or "").strip()
    if len(text) > BODY_MAX:
        raise ValueError(f"Message too long (max {BODY_MAX} characters)")
    files = files or []
    is_ai_thread = thread["kind"] == "ai"
    if is_ai_thread and files:
        raise ValueError("Attachments are not supported in AI Assistant chat")
    if len(files) > MSG_MAX_ATTACHMENTS:
        raise ValueError(f"At most {MSG_MAX_ATTACHMENTS} attachments")
    if not text and not files:
        raise ValueError("Write a message or attach a file")
    if is_ai_thread and not text:
        raise ValueError("Ask the assistant a question")

    if reply_to_id:
        parent = conn.execute(
            "SELECT id FROM msg_messages WHERE id = ? AND thread_id = ?",
            (reply_to_id, thread_id),
        ).fetchone()
        if not parent:
            raise ValueError("Reply target not found")

    now = utc_now()
    mid = f"mm_{secrets.token_hex(8)}"
    author_name = _member_name(conn, actor.get("memberId"), house_id)
    ensure_msg_likes_and_ai(conn)
    conn.execute(
        """
        INSERT INTO msg_messages(
          id, thread_id, author_member_id, house_id, author_name, body, status, reply_to_id, is_ai, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, 'active', ?, 0, ?)
        """,
        (mid, thread_id, actor.get("memberId"), house_id, author_name, text, reply_to_id, now),
    )
    conn.execute(
        "UPDATE msg_threads SET updated_at = ? WHERE id = ?",
        (now, thread_id),
    )

    for raw, ctype, oname in files:
        data, mime, ext, w, h = _prepare_upload(raw, ctype, oname)
        fid = f"ma_{secrets.token_hex(8)}"
        filename = f"{fid}.{ext}"
        dest = attachment_path(site_root, thread_id, mid, filename)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        conn.execute(
            """
            INSERT INTO msg_attachments(
              id, message_id, thread_id, house_id, filename, original_name, mime, size_bytes, width, height, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                fid,
                mid,
                thread_id,
                house_id,
                filename,
                (oname or filename)[:180],
                mime,
                len(data),
                w,
                h,
                now,
            ),
        )

    # Mark author as having read up to this message
    if actor.get("memberId"):
        conn.execute(
            """
            INSERT INTO msg_reads(member_id, thread_id, last_read_message_id, last_read_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(member_id, thread_id) DO UPDATE SET
              last_read_message_id = excluded.last_read_message_id,
              last_read_at = excluded.last_read_at
            """,
            (actor["memberId"], thread_id, mid, now),
        )
    conn.commit()

    assistant_msg = None
    if is_ai_thread and text:
        assistant_msg = _reply_as_ai(conn, site_root, actor, thread_id, question=text)

    row = conn.execute("SELECT * FROM msg_messages WHERE id = ?", (mid,)).fetchone()
    user_msg = _public_message(
        conn, row, include_hidden=True, viewer_member_id=actor.get("memberId")
    )
    if assistant_msg:
        user_msg["_assistant"] = assistant_msg  # type: ignore[index]
    return user_msg  # type: ignore[return-value]


def _reply_as_ai(
    conn: sqlite3.Connection,
    site_root: pathlib.Path,
    actor: dict,
    thread_id: str,
    *,
    question: str,
) -> dict:
    import rwa_ai_chat

    history_rows = conn.execute(
        """
        SELECT body, is_ai FROM msg_messages
        WHERE thread_id = ? AND status = 'active'
        ORDER BY created_at DESC LIMIT 12
        """,
        (thread_id,),
    ).fetchall()
    history = []
    for r in reversed(history_rows):
        # Skip the just-posted question (last user msg) for cleaner history — include prior turns
        history.append({
            "role": "assistant" if r["is_ai"] else "user",
            "content": r["body"] or "",
        })
    # Drop trailing duplicate of current question if present
    if history and history[-1]["role"] == "user" and history[-1]["content"] == question:
        history = history[:-1]

    result = rwa_ai_chat.answer_query(
        conn, site_root, query=question, history=history, actor=actor
    )
    answer = (result.get("answer") or "").strip() or "I could not produce an answer."
    now = utc_now()
    aid = f"mm_{secrets.token_hex(8)}"
    conn.execute(
        """
        INSERT INTO msg_messages(
          id, thread_id, author_member_id, house_id, author_name, body, status, reply_to_id, is_ai, created_at
        ) VALUES (?, ?, NULL, ?, ?, ?, 'active', NULL, 1, ?)
        """,
        (aid, thread_id, "__AI__", "RWA Assistant", answer[:BODY_MAX], now),
    )
    conn.execute(
        "UPDATE msg_threads SET updated_at = ? WHERE id = ?",
        (now, thread_id),
    )
    if actor.get("memberId"):
        conn.execute(
            """
            INSERT INTO msg_reads(member_id, thread_id, last_read_message_id, last_read_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(member_id, thread_id) DO UPDATE SET
              last_read_message_id = excluded.last_read_message_id,
              last_read_at = excluded.last_read_at
            """,
            (actor["memberId"], thread_id, aid, now),
        )
    conn.commit()
    row = conn.execute("SELECT * FROM msg_messages WHERE id = ?", (aid,)).fetchone()
    pub = _public_message(conn, row, include_hidden=True, viewer_member_id=actor.get("memberId"))
    if pub is not None:
        pub["aiMode"] = result.get("mode")
        pub["aiSources"] = result.get("sources") or []
    return pub or {"id": aid, "body": answer, "isAi": True}


def toggle_like(conn: sqlite3.Connection, actor: dict, message_id: str) -> dict:
    ensure_messages_and_push_tables(conn)
    ensure_msg_likes_and_ai(conn)
    try:
        from rwa_household import actor_is_view_only
    except ImportError:
        actor_is_view_only = lambda a: bool(a.get("viewOnly")) and not a.get("superAdmin")  # noqa: E731
    if actor_is_view_only(actor):
        raise PermissionError("View-only access cannot like messages")
    mid = (actor.get("memberId") or "").strip()
    house = (actor.get("houseId") or "").strip()
    if not mid or not house:
        raise ValueError("Member identity required")
    row = conn.execute("SELECT * FROM msg_messages WHERE id = ?", (message_id,)).fetchone()
    if not row or row["status"] != "active":
        raise ValueError("Message not found")
    thread = conn.execute("SELECT * FROM msg_threads WHERE id = ?", (row["thread_id"],)).fetchone()
    if not thread or not can_access_thread(conn, thread, actor):
        raise PermissionError("Not allowed")
    if thread["kind"] == "ai" or (row["is_ai"] if "is_ai" in row.keys() else 0):
        raise ValueError("AI Assistant messages cannot be liked")
    existing = conn.execute(
        "SELECT 1 FROM msg_likes WHERE message_id = ? AND member_id = ?",
        (message_id, mid),
    ).fetchone()
    if existing:
        conn.execute(
            "DELETE FROM msg_likes WHERE message_id = ? AND member_id = ?",
            (message_id, mid),
        )
        liked = False
    else:
        conn.execute(
            """
            INSERT INTO msg_likes(message_id, member_id, house_id, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (message_id, mid, house, utc_now()),
        )
        liked = True
    conn.commit()
    stats = _like_stats(conn, message_id, mid)
    return {"messageId": message_id, "likedByMe": liked, "likeCount": stats["likeCount"]}


def mark_read(conn: sqlite3.Connection, actor: dict, thread_id: str, message_id: str | None = None) -> dict:
    ensure_messages_and_push_tables(conn)
    member_id = actor.get("memberId")
    if not member_id:
        return {"ok": True, "skipped": True}
    thread = conn.execute("SELECT * FROM msg_threads WHERE id = ?", (thread_id,)).fetchone()
    if not thread or not can_access_thread(conn, thread, actor):
        raise PermissionError("Not allowed")
    if message_id:
        row = conn.execute(
            "SELECT id, created_at FROM msg_messages WHERE id = ? AND thread_id = ?",
            (message_id, thread_id),
        ).fetchone()
    else:
        row = conn.execute(
            """
            SELECT id, created_at FROM msg_messages
            WHERE thread_id = ? AND status = 'active'
            ORDER BY created_at DESC LIMIT 1
            """,
            (thread_id,),
        ).fetchone()
    if not row:
        return {"ok": True, "unread": 0}
    now = utc_now()
    conn.execute(
        """
        INSERT INTO msg_reads(member_id, thread_id, last_read_message_id, last_read_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(member_id, thread_id) DO UPDATE SET
          last_read_message_id = excluded.last_read_message_id,
          last_read_at = excluded.last_read_at
        """,
        (member_id, thread_id, row["id"], row["created_at"] or now),
    )
    conn.commit()
    return {"ok": True, "unread": _unread_count(conn, thread_id, member_id)}


def moderate_message(
    conn: sqlite3.Connection,
    actor: dict,
    message_id: str,
    *,
    action: str,
) -> dict:
    ensure_messages_and_push_tables(conn)
    if not can_moderate(actor):
        raise PermissionError("Moderation permission required")
    row = conn.execute("SELECT * FROM msg_messages WHERE id = ?", (message_id,)).fetchone()
    if not row:
        raise ValueError("Message not found")
    thread = conn.execute("SELECT * FROM msg_threads WHERE id = ?", (row["thread_id"],)).fetchone()
    if not thread or thread["kind"] != "colony":
        raise PermissionError("Only colony posts can be moderated here")
    action = (action or "").strip().lower()
    if action == "hide":
        conn.execute("UPDATE msg_messages SET status = 'hidden' WHERE id = ?", (message_id,))
    elif action == "unhide":
        conn.execute("UPDATE msg_messages SET status = 'active' WHERE id = ?", (message_id,))
    elif action == "delete":
        conn.execute("UPDATE msg_messages SET status = 'deleted' WHERE id = ?", (message_id,))
        if thread["pinned_message_id"] == message_id:
            conn.execute("UPDATE msg_threads SET pinned_message_id = NULL WHERE id = ?", (thread["id"],))
    elif action == "pin":
        conn.execute(
            "UPDATE msg_threads SET pinned_message_id = ? WHERE id = ?",
            (message_id, thread["id"]),
        )
    elif action == "unpin":
        conn.execute(
            "UPDATE msg_threads SET pinned_message_id = NULL WHERE id = ? AND pinned_message_id = ?",
            (thread["id"], message_id),
        )
    else:
        raise ValueError("Unknown moderation action")
    conn.commit()
    updated = conn.execute("SELECT * FROM msg_messages WHERE id = ?", (message_id,)).fetchone()
    return _public_message(conn, updated, include_hidden=True) or {"id": message_id, "status": "deleted"}


def get_attachment(conn: sqlite3.Connection, site_root: pathlib.Path, file_id: str, actor: dict) -> tuple[pathlib.Path, dict]:
    ensure_messages_and_push_tables(conn)
    row = conn.execute("SELECT * FROM msg_attachments WHERE id = ?", (file_id,)).fetchone()
    if not row:
        raise ValueError("Attachment not found")
    thread = conn.execute("SELECT * FROM msg_threads WHERE id = ?", (row["thread_id"],)).fetchone()
    if not thread or not can_access_thread(conn, thread, actor):
        raise PermissionError("Not allowed")
    path = attachment_path(site_root, row["thread_id"], row["message_id"], row["filename"])
    if not path.is_file():
        raise FileNotFoundError("File missing")
    return path, {
        "mime": row["mime"],
        "filename": row["original_name"] or row["filename"],
    }


def total_unread(conn: sqlite3.Connection, actor: dict) -> int:
    threads = list_threads(conn, actor)
    return sum(int(t.get("unread") or 0) for t in threads)


def directory_peers(conn: sqlite3.Connection, actor: dict, q: str = "") -> list[dict]:
    """Plots available to DM (for compose search)."""
    my = (actor.get("houseId") or "").strip()
    q = (q or "").strip().lower()
    rows = conn.execute(
        """
        SELECT house_id, name, plot_no, section, phone
        FROM residents
        WHERE status = 'active'
          AND house_id != ?
          AND house_id != ?
          AND house_id != ?
        """,
        (SUPERADMIN_HOUSE_ID, ADHOC_GATE_HOUSE_ID, my or ""),
    ).fetchall()
    out = []
    for r in rows:
        label = f"{r['plot_no'] or r['house_id']} · {r['name'] or ''}"
        if q and q not in label.lower() and q not in (r["house_id"] or "").lower():
            continue
        out.append({
            "houseId": r["house_id"],
            "name": r["name"],
            "plotNo": r["plot_no"],
            "section": r["section"],
            "label": label.strip(" ·"),
        })
    out.sort(key=lambda x: section_plot_sort_key(x.get("section"), x.get("plotNo") or x.get("houseId")))
    return out[:80]


def notify_new_message(
    conn: sqlite3.Connection,
    site_root: pathlib.Path,
    actor: dict,
    thread: dict,
    message: dict,
) -> None:
    if (thread.get("kind") or "") == "ai":
        return
    try:
        import rwa_push
    except ImportError:
        return
    preview = (message.get("body") or "").strip() or "Sent an attachment"
    if len(preview) > 100:
        preview = preview[:97] + "…"
    author = message.get("authorName") or actor.get("name") or "Resident"
    url = f"/#messages/{thread.get('id')}"
    if thread.get("kind") == "colony":
        rwa_push.enqueue_push(
            conn,
            site_root,
            event_type="message",
            audience={"type": "all"},
            title="Colony message",
            body=f"{author}: {preview}",
            url=url,
            exclude_member_id=actor.get("memberId"),
        )
    else:
        peer = thread.get("peerHouseId")
        houses = []
        for h in (thread.get("houseA"), thread.get("houseB")):
            if h and h != actor.get("houseId"):
                houses.append(h)
        if peer and peer not in houses:
            houses.append(peer)
        if not houses:
            return
        rwa_push.enqueue_push(
            conn,
            site_root,
            event_type="message",
            audience={"type": "houses", "houseIds": houses},
            title=f"Message from {actor.get('houseId') or author}",
            body=f"{author}: {preview}",
            url=url,
            exclude_member_id=actor.get("memberId"),
        )
