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
    ensure_msg_private_channels,
    normalize_house_id,
    section_plot_sort_key,
    utc_now,
)

MSG_MAX_BYTES = 5_000_000
MSG_MAX_ATTACHMENTS = 3
MSG_IMAGE_MAX_EDGE = 1600
MSG_IMAGE_QUALITY = 72
BODY_MAX = 4000
GROUP_MAX_MEMBERS = 30
GROUP_TITLE_MIN = 2
GROUP_TITLE_MAX = 80
TENANT_MEMBER_PREFIX = "tenant:"
CARD_THEMES = frozenset({"", "plain", "notice", "urgent", "celebrate", "official", "thanks"})
CARD_THEME_LABELS = {
    "": "Default",
    "plain": "Default",
    "notice": "Notice",
    "urgent": "Urgent",
    "celebrate": "Celebrate",
    "official": "Official",
    "thanks": "Thanks",
}
CHANNEL_BG_STYLES = {
    "none": "None",
    "soft": "Soft wash",
    "dots": "Dots",
    "grid": "Grid",
    "tiles": "Tiles",
    "diagonal": "Diagonal",
    "leaves": "Leaves",
    "custom": "Custom image",
}
CHANNEL_ICON_MAX_EDGE = 512
CHANNEL_BG_MAX_EDGE = 1600
CHANNEL_ICON_MAX_BYTES = 2_000_000
CHANNEL_BG_MAX_BYTES = 4_000_000


def _ensure_msg_schema(conn: sqlite3.Connection) -> None:
    ensure_messages_and_push_tables(conn)
    ensure_msg_likes_and_ai(conn)
    ensure_msg_private_channels(conn)


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
    if kind == "group":
        if actor.get("superAdmin") or can_moderate(actor):
            return True
        mid = (actor.get("memberId") or "").strip()
        if not mid:
            return False
        tid = thread["id"] if isinstance(thread, dict) else thread["id"]
        return _is_active_group_member(conn, tid, mid)
    house = (actor.get("houseId") or "").strip()
    if actor.get("superAdmin"):
        return True
    ha = thread["house_a"] if isinstance(thread, dict) else thread["house_a"]
    hb = thread["house_b"] if isinstance(thread, dict) else thread["house_b"]
    return house in {ha, hb}


def _is_active_group_member(conn: sqlite3.Connection, thread_id: str, member_id: str) -> bool:
    if not thread_id or not member_id:
        return False
    row = conn.execute(
        """
        SELECT 1 FROM msg_thread_members
        WHERE thread_id = ? AND member_id = ? AND left_at IS NULL
        """,
        (thread_id, member_id),
    ).fetchone()
    return bool(row)


def _group_member_role(conn: sqlite3.Connection, thread_id: str, member_id: str) -> str | None:
    if not thread_id or not member_id:
        return None
    row = conn.execute(
        """
        SELECT role FROM msg_thread_members
        WHERE thread_id = ? AND member_id = ? AND left_at IS NULL
        """,
        (thread_id, member_id),
    ).fetchone()
    return (row["role"] if row else None) or None


def _group_member_count(conn: sqlite3.Connection, thread_id: str) -> int:
    row = conn.execute(
        """
        SELECT COUNT(*) AS n FROM msg_thread_members
        WHERE thread_id = ? AND left_at IS NULL
        """,
        (thread_id,),
    ).fetchone()
    return int(row["n"] if row else 0)


def can_manage_group(conn: sqlite3.Connection, thread: dict | sqlite3.Row, actor: dict) -> bool:
    kind = thread["kind"] if isinstance(thread, dict) else thread["kind"]
    if kind != "group":
        return False
    if can_moderate(actor) or actor.get("superAdmin"):
        return True
    mid = (actor.get("memberId") or "").strip()
    owner = thread["owner_member_id"] if isinstance(thread, dict) else thread["owner_member_id"]
    if mid and owner and mid == owner:
        return True
    tid = thread["id"] if isinstance(thread, dict) else thread["id"]
    return _group_member_role(conn, tid, mid) == "owner"


def _thread_col(thread: dict | sqlite3.Row, key: str, default=None):
    if isinstance(thread, dict):
        return thread.get(key, default)
    try:
        return thread[key]
    except (IndexError, KeyError):
        return default


def _actor_view_only(actor: dict) -> bool:
    try:
        from rwa_household import actor_is_view_only

        return actor_is_view_only(actor)
    except ImportError:
        return bool(actor.get("viewOnly")) and not actor.get("superAdmin")


def _normalize_group_title(title: str) -> str:
    text = " ".join((title or "").split())
    if len(text) < GROUP_TITLE_MIN:
        raise ValueError(f"Channel name needs at least {GROUP_TITLE_MIN} characters")
    if len(text) > GROUP_TITLE_MAX:
        raise ValueError(f"Channel name is too long (max {GROUP_TITLE_MAX})")
    return text


def _tenant_member_key(tenant_id: str) -> str:
    return f"{TENANT_MEMBER_PREFIX}{(tenant_id or '').strip()}"


def _parse_tenant_member_key(member_id: str) -> str | None:
    mid = (member_id or "").strip()
    if mid.startswith(TENANT_MEMBER_PREFIX):
        tid = mid[len(TENANT_MEMBER_PREFIX) :].strip()
        return tid or None
    return None


def _normalize_card_theme(raw: str | None) -> str:
    theme = (raw or "").strip().lower()
    if theme in ("", "plain", "none", "default"):
        return ""
    if theme not in CARD_THEMES:
        raise ValueError("Unknown card theme")
    return theme


def _member_role_label(row: sqlite3.Row | dict) -> str:
    def g(key: str, default=None):
        if isinstance(row, dict):
            return row.get(key, default)
        try:
            return row[key]
        except (IndexError, KeyError):
            return default

    if int(g("is_primary_delegate") or 0):
        return "Primary delegate"
    if int(g("is_primary") or 0):
        return "Owner"
    relation = (g("relation") or "other").strip().lower()
    labels = {
        "owner": "Owner",
        "spouse": "Spouse",
        "parent": "Parent",
        "child": "Child",
        "other": "Household member",
    }
    base = labels.get(relation, "Household member")
    if int(g("can_manage") or 0) and relation != "owner":
        return f"{base} · delegate"
    if int(g("view_only") or 0):
        return f"{base} · view-only"
    return base


def _validate_member_ids(conn: sqlite3.Connection, member_ids: list[str], *, exclude: str | None = None) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in member_ids or []:
        mid = str(raw or "").strip()
        if not mid or mid.startswith(TENANT_MEMBER_PREFIX) or mid in seen or (exclude and mid == exclude):
            continue
        seen.add(mid)
        cleaned.append(mid)
    if not cleaned:
        return []
    placeholders = ",".join("?" * len(cleaned))
    rows = conn.execute(
        f"""
        SELECT id FROM household_members
        WHERE status = 'active' AND id IN ({placeholders})
        """,
        cleaned,
    ).fetchall()
    found = {str(r["id"]) for r in rows}
    missing = [m for m in cleaned if m not in found]
    if missing:
        raise ValueError("One or more people were not found in the directory")
    return cleaned


def _validate_tenant_ids(conn: sqlite3.Connection, tenant_ids: list[str]) -> list[str]:
    from init_rwa_db import ensure_household_tenants_table

    ensure_household_tenants_table(conn)
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in tenant_ids or []:
        tid = str(raw or "").strip()
        if not tid or tid in seen:
            continue
        seen.add(tid)
        cleaned.append(tid)
    if not cleaned:
        return []
    placeholders = ",".join("?" * len(cleaned))
    rows = conn.execute(
        f"""
        SELECT id FROM household_tenants
        WHERE status = 'active' AND id IN ({placeholders})
        """,
        cleaned,
    ).fetchall()
    found = {str(r["id"]) for r in rows}
    missing = [t for t in cleaned if t not in found]
    if missing:
        raise ValueError("One or more tenants were not found (or occupancy has ended)")
    return cleaned


def _icon_url(thread_id: str, icon_filename: str | None) -> str:
    if not icon_filename:
        return ""
    return f"/api/rwa/messages/threads/{thread_id}/icon"


def _bg_url(thread_id: str, bg_style: str | None, bg_filename: str | None) -> str:
    if (bg_style or "") == "custom" and bg_filename:
        return f"/api/rwa/messages/threads/{thread_id}/background"
    return ""


def _normalize_bg_style(raw: str | None) -> str:
    style = (raw or "none").strip().lower()
    if style not in CHANNEL_BG_STYLES:
        raise ValueError("Unknown channel background style")
    return style


def _channel_asset_dir(site_root: pathlib.Path, kind: str) -> pathlib.Path:
    root = messages_root(site_root) / kind
    root.mkdir(parents=True, exist_ok=True)
    return root


def _optimize_channel_image(raw: bytes, *, max_edge: int, max_bytes: int) -> tuple[bytes, str]:
    if len(raw) > max_bytes:
        raise ValueError(f"Image must be under {max_bytes // (1024 * 1024)} MB")
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
    if edge > max_edge:
        scale = max_edge / edge
        resample = Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS
        img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))), resample)
    buf = BytesIO()
    img.save(buf, format="WEBP", quality=78, method=4)
    out = buf.getvalue()
    if not out:
        raise ValueError("Could not encode image")
    return out, "image/webp"


def _upsert_participant(
    conn: sqlite3.Connection,
    thread_id: str,
    *,
    member_id: str,
    role: str = "member",
    tenant_id: str | None = None,
    now: str | None = None,
) -> bool:
    """Insert or re-activate a channel participant. Returns True if newly active."""
    stamp = now or utc_now()
    existing = conn.execute(
        "SELECT left_at FROM msg_thread_members WHERE thread_id = ? AND member_id = ?",
        (thread_id, member_id),
    ).fetchone()
    if existing and existing["left_at"] is None:
        return False
    if existing:
        conn.execute(
            """
            UPDATE msg_thread_members
            SET role = ?, joined_at = ?, left_at = NULL, tenant_id = ?
            WHERE thread_id = ? AND member_id = ?
            """,
            (role, stamp, tenant_id, thread_id, member_id),
        )
    else:
        conn.execute(
            """
            INSERT INTO msg_thread_members(thread_id, member_id, role, joined_at, left_at, tenant_id)
            VALUES (?, ?, ?, ?, NULL, ?)
            """,
            (thread_id, member_id, role, stamp, tenant_id),
        )
    return True


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
    card_theme = ""
    if "card_theme" in row.keys() and row["card_theme"]:
        card_theme = str(row["card_theme"] or "").strip().lower()
        if card_theme in ("plain", "none", "default"):
            card_theme = ""
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
        "cardTheme": card_theme,
        "cardThemeLabel": CARD_THEME_LABELS.get(card_theme, "Default"),
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
    if thread["kind"] == "group":
        return thread["title"] or "Private channel"
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
    is_official = bool(_thread_col(thread, "is_official", 0))
    archived_at = _thread_col(thread, "archived_at") or None
    icon_filename = _thread_col(thread, "icon_filename") or ""
    bg_style = (_thread_col(thread, "bg_style") or "none").strip().lower() or "none"
    if bg_style not in CHANNEL_BG_STYLES:
        bg_style = "none"
    bg_filename = _thread_col(thread, "bg_filename") or ""
    member_count = 0
    my_role = None
    can_manage = False
    if thread["kind"] == "group":
        member_count = _group_member_count(conn, thread["id"])
        my_role = _group_member_role(conn, thread["id"], member_id or "")
        can_manage = can_manage_group(conn, thread, actor)
    return {
        "id": thread["id"],
        "kind": thread["kind"],
        "houseA": thread["house_a"],
        "houseB": thread["house_b"],
        "title": _thread_title(conn, thread, house),
        "pinnedMessageId": thread["pinned_message_id"],
        "ownerMemberId": _thread_col(thread, "owner_member_id") or None,
        "isOfficial": is_official,
        "archivedAt": archived_at,
        "iconUrl": _icon_url(thread["id"], icon_filename),
        "hasIcon": bool(icon_filename),
        "bgStyle": bg_style,
        "bgStyleLabel": CHANNEL_BG_STYLES.get(bg_style, "None"),
        "bgUrl": _bg_url(thread["id"], bg_style, bg_filename),
        "hasCustomBg": bool(bg_style == "custom" and bg_filename),
        "memberCount": member_count,
        "myRole": my_role,
        "canManage": can_manage,
        "createdAt": thread["created_at"],
        "updatedAt": thread["updated_at"],
        "unread": _unread_count(conn, thread["id"], member_id),
        "lastMessage": _last_message_preview(conn, thread["id"]),
        "peerHouseId": peer_house,
        "peerHasPhoto": bool(peer_photo.get("hasPhoto")),
        "peerPhotoUrl": peer_photo.get("photoUrl") or "",
        "cardThemes": [
            {"id": k or "plain", "label": CARD_THEME_LABELS.get(k, "Default")}
            for k in ("", "notice", "urgent", "celebrate", "official", "thanks")
        ],
        "bgStyles": [
            {"id": k, "label": v} for k, v in CHANNEL_BG_STYLES.items()
        ],
    }


def ensure_colony_thread(conn: sqlite3.Connection) -> str:
    _ensure_msg_schema(conn)
    return COLONY_THREAD_ID


def open_ai_thread(conn: sqlite3.Connection, actor: dict) -> dict:
    """Private per-member AI assistant thread (not visible to anyone else)."""
    _ensure_msg_schema(conn)
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


def list_threads(conn: sqlite3.Connection, actor: dict, *, include_archived: bool = False) -> list[dict]:
    _ensure_msg_schema(conn)
    house = (actor.get("houseId") or "").strip()
    mid = (actor.get("memberId") or "").strip()
    out = []
    # Private AI assistant first (only for members)
    if mid and house and house != SUPERADMIN_HOUSE_ID:
        try:
            out.append(open_ai_thread(conn, actor))
        except ValueError:
            pass
    colony = conn.execute("SELECT * FROM msg_threads WHERE id = ?", (COLONY_THREAD_ID,)).fetchone()
    if colony:
        out.append(_public_thread(conn, colony, actor))
    if mid:
        if include_archived:
            group_sql = """
                SELECT t.* FROM msg_threads t
                INNER JOIN msg_thread_members m
                  ON m.thread_id = t.id AND m.member_id = ? AND m.left_at IS NULL
                WHERE t.kind = 'group'
                ORDER BY t.updated_at DESC
            """
        else:
            group_sql = """
                SELECT t.* FROM msg_threads t
                INNER JOIN msg_thread_members m
                  ON m.thread_id = t.id AND m.member_id = ? AND m.left_at IS NULL
                WHERE t.kind = 'group' AND t.archived_at IS NULL
                ORDER BY t.updated_at DESC
            """
        for r in conn.execute(group_sql, (mid,)).fetchall():
            out.append(_public_thread(conn, r, actor))
    elif actor.get("superAdmin") or can_moderate(actor):
        sql = "SELECT * FROM msg_threads WHERE kind = 'group'"
        if not include_archived:
            sql += " AND archived_at IS NULL"
        sql += " ORDER BY updated_at DESC LIMIT 100"
        for r in conn.execute(sql).fetchall():
            out.append(_public_thread(conn, r, actor))
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
    _ensure_msg_schema(conn)
    row = conn.execute("SELECT * FROM msg_threads WHERE id = ?", (thread_id,)).fetchone()
    if not row:
        raise ValueError("Thread not found")
    if not can_access_thread(conn, row, actor):
        raise PermissionError("Not allowed to view this thread")
    return _public_thread(conn, row, actor)


def open_dm(conn: sqlite3.Connection, actor: dict, peer_house_id: str) -> dict:
    _ensure_msg_schema(conn)
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
    _ensure_msg_schema(conn)
    thread = conn.execute("SELECT * FROM msg_threads WHERE id = ?", (thread_id,)).fetchone()
    if not thread:
        raise ValueError("Thread not found")
    if not can_access_thread(conn, thread, actor):
        raise PermissionError("Not allowed")
    if thread["kind"] == "group" and _thread_col(thread, "archived_at"):
        # Still readable when member; posting blocked separately
        pass
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
        "canManage": can_manage_group(conn, thread, actor) if thread["kind"] == "group" else False,
        "canLeave": (
            thread["kind"] == "group"
            and bool(actor.get("memberId"))
            and _is_active_group_member(conn, thread["id"], actor.get("memberId") or "")
        ),
        "canEscalate": thread["kind"] in ("group", "dm", "colony") and not _actor_view_only(actor),
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
    if kind == "group":
        # can_manage_group needs conn — approximate via owner / moderate for cleanup gate
        if can_moderate(actor) or actor.get("superAdmin"):
            return True
        mid = (actor.get("memberId") or "").strip()
        owner = (
            thread["owner_member_id"]
            if not isinstance(thread, dict)
            else thread.get("owner_member_id")
        )
        return bool(mid and owner and mid == owner)
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
    card_theme: str | None = None,
) -> dict:
    _ensure_msg_schema(conn)
    if _actor_view_only(actor):
        raise PermissionError("View-only access cannot post messages")

    thread = conn.execute("SELECT * FROM msg_threads WHERE id = ?", (thread_id,)).fetchone()
    if not thread:
        raise ValueError("Thread not found")
    if not can_access_thread(conn, thread, actor):
        raise PermissionError("Not allowed")
    if thread["kind"] == "group" and _thread_col(thread, "archived_at"):
        raise PermissionError("This channel is archived")

    house_id = (actor.get("houseId") or "").strip()
    if not house_id:
        raise ValueError("House required")
    text = (body or "").strip()
    if len(text) > BODY_MAX:
        raise ValueError(f"Message too long (max {BODY_MAX} characters)")
    files = files or []
    is_ai_thread = thread["kind"] == "ai"
    theme = _normalize_card_theme(card_theme)
    if theme and is_ai_thread:
        raise ValueError("Card themes are not available in AI chat")
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
          id, thread_id, author_member_id, house_id, author_name, body, status,
          reply_to_id, is_ai, card_theme, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, 'active', ?, 0, ?, ?)
        """,
        (mid, thread_id, actor.get("memberId"), house_id, author_name, text, reply_to_id, theme or None, now),
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


def directory_people(conn: sqlite3.Connection, actor: dict, q: str = "") -> list[dict]:
    """Colony people for private-channel invites: members, delegates, and registered tenants."""
    _ensure_msg_schema(conn)
    from init_rwa_db import ensure_household_tenants_table

    ensure_household_tenants_table(conn)
    my_mid = (actor.get("memberId") or "").strip()
    q = (q or "").strip().lower()
    out: list[dict] = []

    member_rows = conn.execute(
        """
        SELECT m.id, m.name, m.house_id, m.relation, m.is_primary, m.is_primary_delegate,
               m.can_manage, m.view_only, m.phone, m.email,
               r.plot_no, r.section, r.name AS house_name
        FROM household_members m
        JOIN residents r ON r.house_id = m.house_id
        WHERE m.status = 'active'
          AND r.status = 'active'
          AND m.house_id != ?
          AND m.house_id != ?
        ORDER BY r.section, r.plot_no, m.is_primary DESC, m.is_primary_delegate DESC, m.name
        """,
        (SUPERADMIN_HOUSE_ID, ADHOC_GATE_HOUSE_ID),
    ).fetchall()
    for r in member_rows:
        mid = str(r["id"])
        if my_mid and mid == my_mid:
            continue
        plot = r["plot_no"] or r["house_id"]
        name = r["name"] or "Resident"
        role = _member_role_label(r)
        label = f"{name} · {plot} · {role}"
        hay = " ".join(
            [
                label,
                r["house_name"] or "",
                r["house_id"] or "",
                r["phone"] or "",
                r["email"] or "",
                role,
            ]
        ).lower()
        if q and q not in hay:
            continue
        out.append({
            "kind": "member",
            "memberId": mid,
            "tenantId": "",
            "name": name,
            "houseId": r["house_id"],
            "plotNo": r["plot_no"],
            "section": r["section"],
            "roleLabel": role,
            "label": label,
            "canMessage": True,
        })

    tenant_rows = conn.execute(
        """
        SELECT t.id, t.name, t.house_id, t.phone, t.email,
               r.plot_no, r.section, r.name AS house_name
        FROM household_tenants t
        JOIN residents r ON r.house_id = t.house_id
        WHERE t.status = 'active'
          AND r.status = 'active'
          AND t.house_id != ?
          AND t.house_id != ?
        ORDER BY r.section, r.plot_no, t.name
        """,
        (SUPERADMIN_HOUSE_ID, ADHOC_GATE_HOUSE_ID),
    ).fetchall()
    for r in tenant_rows:
        tid = str(r["id"])
        plot = r["plot_no"] or r["house_id"]
        name = r["name"] or "Tenant"
        role = "Tenant"
        label = f"{name} · {plot} · {role}"
        hay = " ".join(
            [
                label,
                r["house_name"] or "",
                r["house_id"] or "",
                r["phone"] or "",
                r["email"] or "",
                "tenant",
            ]
        ).lower()
        if q and q not in hay:
            continue
        out.append({
            "kind": "tenant",
            "memberId": "",
            "tenantId": tid,
            "name": name,
            "houseId": r["house_id"],
            "plotNo": r["plot_no"],
            "section": r["section"],
            "roleLabel": role,
            "label": label,
            # Occupancy record only — listed on the channel roster; no portal login yet.
            "canMessage": False,
            "note": "Registered tenant (occupancy) — listed on the channel; no portal login",
        })

    return out[:100]


def create_group(
    conn: sqlite3.Connection,
    actor: dict,
    *,
    title: str,
    member_ids: list[str] | None = None,
    tenant_ids: list[str] | None = None,
    is_official: bool = False,
) -> dict:
    _ensure_msg_schema(conn)
    if _actor_view_only(actor):
        raise PermissionError("View-only access cannot create channels")
    mid = (actor.get("memberId") or "").strip()
    house = (actor.get("houseId") or "").strip()
    if not mid or not house or house == SUPERADMIN_HOUSE_ID:
        raise ValueError("Sign in as a household member to create a channel")
    name = _normalize_group_title(title)
    others = _validate_member_ids(conn, member_ids or [], exclude=mid)
    tenants = _validate_tenant_ids(conn, tenant_ids or [])
    if 1 + len(others) + len(tenants) > GROUP_MAX_MEMBERS:
        raise ValueError(f"At most {GROUP_MAX_MEMBERS} people per channel")
    now = utc_now()
    tid = f"grp_{secrets.token_hex(8)}"
    conn.execute(
        """
        INSERT INTO msg_threads(
          id, kind, house_a, house_b, title, pinned_message_id, owner_member_id,
          is_official, archived_at, created_at, updated_at
        ) VALUES (?, 'group', ?, NULL, ?, NULL, ?, ?, NULL, ?, ?)
        """,
        (tid, house, name, mid, 1 if is_official else 0, now, now),
    )
    _upsert_participant(conn, tid, member_id=mid, role="owner", now=now)
    for other in others:
        _upsert_participant(conn, tid, member_id=other, role="member", now=now)
    for tenant_id in tenants:
        _upsert_participant(
            conn,
            tid,
            member_id=_tenant_member_key(tenant_id),
            role="member",
            tenant_id=tenant_id,
            now=now,
        )
    conn.commit()
    row = conn.execute("SELECT * FROM msg_threads WHERE id = ?", (tid,)).fetchone()
    return _public_thread(conn, row, actor)


def update_group(
    conn: sqlite3.Connection,
    actor: dict,
    thread_id: str,
    *,
    title: str | None = None,
    is_official: bool | None = None,
    archive: bool | None = None,
    transfer_owner_to: str | None = None,
    bg_style: str | None = None,
) -> dict:
    _ensure_msg_schema(conn)
    thread = conn.execute("SELECT * FROM msg_threads WHERE id = ?", (thread_id,)).fetchone()
    if not thread or thread["kind"] != "group":
        raise ValueError("Channel not found")
    if not can_manage_group(conn, thread, actor):
        raise PermissionError("Only the channel owner or EC can manage this channel")
    now = utc_now()
    if title is not None:
        name = _normalize_group_title(title)
        conn.execute("UPDATE msg_threads SET title = ?, updated_at = ? WHERE id = ?", (name, now, thread_id))
    if is_official is not None:
        conn.execute(
            "UPDATE msg_threads SET is_official = ?, updated_at = ? WHERE id = ?",
            (1 if is_official else 0, now, thread_id),
        )
    if archive is True:
        conn.execute(
            "UPDATE msg_threads SET archived_at = ?, updated_at = ? WHERE id = ?",
            (now, now, thread_id),
        )
    elif archive is False:
        conn.execute(
            "UPDATE msg_threads SET archived_at = NULL, updated_at = ? WHERE id = ?",
            (now, thread_id),
        )
    if bg_style is not None:
        style = _normalize_bg_style(bg_style)
        if style == "custom" and not _thread_col(thread, "bg_filename"):
            raise ValueError("Upload a background image before choosing Custom image")
        conn.execute(
            "UPDATE msg_threads SET bg_style = ?, updated_at = ? WHERE id = ?",
            (style, now, thread_id),
        )
    if transfer_owner_to:
        new_owner = str(transfer_owner_to).strip()
        if _parse_tenant_member_key(new_owner):
            raise ValueError("Cannot transfer ownership to a tenant listing")
        if not _is_active_group_member(conn, thread_id, new_owner):
            raise ValueError("New owner must be an active channel member")
        conn.execute(
            "UPDATE msg_thread_members SET role = 'member' WHERE thread_id = ? AND role = 'owner'",
            (thread_id,),
        )
        conn.execute(
            """
            UPDATE msg_thread_members SET role = 'owner'
            WHERE thread_id = ? AND member_id = ? AND left_at IS NULL
            """,
            (thread_id, new_owner),
        )
        conn.execute(
            "UPDATE msg_threads SET owner_member_id = ?, updated_at = ? WHERE id = ?",
            (new_owner, now, thread_id),
        )
    conn.commit()
    row = conn.execute("SELECT * FROM msg_threads WHERE id = ?", (thread_id,)).fetchone()
    return _public_thread(conn, row, actor)


def list_group_members(conn: sqlite3.Connection, actor: dict, thread_id: str) -> list[dict]:
    _ensure_msg_schema(conn)
    from init_rwa_db import ensure_household_tenants_table

    ensure_household_tenants_table(conn)
    thread = conn.execute("SELECT * FROM msg_threads WHERE id = ?", (thread_id,)).fetchone()
    if not thread or thread["kind"] != "group":
        raise ValueError("Channel not found")
    if not can_access_thread(conn, thread, actor):
        raise PermissionError("Not allowed")
    rows = conn.execute(
        """
        SELECT m.member_id, m.role, m.joined_at, m.tenant_id
        FROM msg_thread_members m
        WHERE m.thread_id = ? AND m.left_at IS NULL
        ORDER BY CASE m.role WHEN 'owner' THEN 0 WHEN 'admin' THEN 1 ELSE 2 END, m.joined_at ASC
        """,
        (thread_id,),
    ).fetchall()
    out = []
    for r in rows:
        mid = r["member_id"]
        tenant_id = (r["tenant_id"] or _parse_tenant_member_key(mid) or "").strip()
        if tenant_id:
            trow = conn.execute(
                """
                SELECT t.name, t.house_id, r.plot_no, r.section
                FROM household_tenants t
                LEFT JOIN residents r ON r.house_id = t.house_id
                WHERE t.id = ?
                """,
                (tenant_id,),
            ).fetchone()
            name = (trow["name"] if trow else None) or "Tenant"
            house_id = (trow["house_id"] if trow else "") or ""
            plot = (trow["plot_no"] if trow else None) or house_id
            out.append({
                "kind": "tenant",
                "memberId": mid,
                "tenantId": tenant_id,
                "role": r["role"],
                "roleLabel": "Tenant",
                "name": name,
                "houseId": house_id,
                "plotNo": plot,
                "section": (trow["section"] if trow else "") or "",
                "joinedAt": r["joined_at"],
                "hasPhoto": False,
                "photoUrl": "",
                "canMessage": False,
                "label": f"{name} · {plot} · Tenant",
            })
            continue
        hm = conn.execute(
            """
            SELECT hm.name, hm.house_id, hm.relation, hm.is_primary, hm.is_primary_delegate,
                   hm.can_manage, hm.view_only, r.plot_no, r.section
            FROM household_members hm
            LEFT JOIN residents r ON r.house_id = hm.house_id
            WHERE hm.id = ?
            """,
            (mid,),
        ).fetchone()
        name = (hm["name"] if hm else None) or "Resident"
        house_id = (hm["house_id"] if hm else "") or ""
        plot = (hm["plot_no"] if hm else None) or house_id
        role_label = _member_role_label(hm) if hm else "Household member"
        if r["role"] == "owner":
            role_label = "Owner"
        photo = _photo_for_member(conn, mid)
        out.append({
            "kind": "member",
            "memberId": mid,
            "tenantId": "",
            "role": r["role"],
            "roleLabel": role_label,
            "name": name,
            "houseId": house_id,
            "plotNo": plot,
            "section": (hm["section"] if hm else "") or "",
            "joinedAt": r["joined_at"],
            "hasPhoto": bool(photo.get("hasPhoto")),
            "photoUrl": photo.get("photoUrl") or "",
            "canMessage": True,
            "label": f"{name} · {plot} · {role_label}",
        })
    return out


def add_group_members(
    conn: sqlite3.Connection,
    actor: dict,
    thread_id: str,
    member_ids: list[str] | None = None,
    tenant_ids: list[str] | None = None,
) -> dict:
    _ensure_msg_schema(conn)
    thread = conn.execute("SELECT * FROM msg_threads WHERE id = ?", (thread_id,)).fetchone()
    if not thread or thread["kind"] != "group":
        raise ValueError("Channel not found")
    if not can_manage_group(conn, thread, actor):
        raise PermissionError("Only the channel owner or EC can add people")
    if _thread_col(thread, "archived_at"):
        raise PermissionError("This channel is archived")
    to_add = _validate_member_ids(conn, member_ids or [])
    tenants = _validate_tenant_ids(conn, tenant_ids or [])
    if not to_add and not tenants:
        raise ValueError("Choose at least one person to add")
    active = _group_member_count(conn, thread_id)
    if active + len(to_add) + len(tenants) > GROUP_MAX_MEMBERS:
        raise ValueError(f"At most {GROUP_MAX_MEMBERS} people per channel")
    now = utc_now()
    added = 0
    for mid in to_add:
        if _upsert_participant(conn, thread_id, member_id=mid, role="member", now=now):
            added += 1
    for tenant_id in tenants:
        if _upsert_participant(
            conn,
            thread_id,
            member_id=_tenant_member_key(tenant_id),
            role="member",
            tenant_id=tenant_id,
            now=now,
        ):
            added += 1
    conn.execute("UPDATE msg_threads SET updated_at = ? WHERE id = ?", (now, thread_id))
    conn.commit()
    return {
        "ok": True,
        "added": added,
        "members": list_group_members(conn, actor, thread_id),
        "thread": get_thread(conn, thread_id, actor),
    }


def remove_group_member(
    conn: sqlite3.Connection,
    actor: dict,
    thread_id: str,
    member_id: str,
) -> dict:
    _ensure_msg_schema(conn)
    thread = conn.execute("SELECT * FROM msg_threads WHERE id = ?", (thread_id,)).fetchone()
    if not thread or thread["kind"] != "group":
        raise ValueError("Channel not found")
    if not can_manage_group(conn, thread, actor):
        raise PermissionError("Only the channel owner or EC can remove people")
    target = str(member_id or "").strip()
    if not target:
        raise ValueError("Member required")
    if target == (actor.get("memberId") or "").strip():
        raise ValueError("Use Leave channel to remove yourself")
    role = _group_member_role(conn, thread_id, target)
    if not role:
        raise ValueError("That person is not in this channel")
    if role == "owner":
        raise ValueError("Transfer ownership before removing the owner")
    now = utc_now()
    conn.execute(
        """
        UPDATE msg_thread_members SET left_at = ?
        WHERE thread_id = ? AND member_id = ? AND left_at IS NULL
        """,
        (now, thread_id, target),
    )
    conn.execute("UPDATE msg_threads SET updated_at = ? WHERE id = ?", (now, thread_id))
    conn.commit()
    return {
        "ok": True,
        "members": list_group_members(conn, actor, thread_id),
        "thread": get_thread(conn, thread_id, actor),
    }


def leave_group(
    conn: sqlite3.Connection,
    actor: dict,
    thread_id: str,
    *,
    transfer_owner_to: str | None = None,
) -> dict:
    _ensure_msg_schema(conn)
    if _actor_view_only(actor):
        raise PermissionError("View-only access cannot leave channels this way")
    mid = (actor.get("memberId") or "").strip()
    if not mid:
        raise ValueError("Member identity required")
    thread = conn.execute("SELECT * FROM msg_threads WHERE id = ?", (thread_id,)).fetchone()
    if not thread or thread["kind"] != "group":
        raise ValueError("Channel not found")
    if not _is_active_group_member(conn, thread_id, mid):
        raise PermissionError("You are not in this channel")
    role = _group_member_role(conn, thread_id, mid)
    now = utc_now()
    if role == "owner":
        others = conn.execute(
            """
            SELECT member_id FROM msg_thread_members
            WHERE thread_id = ? AND left_at IS NULL AND member_id != ?
            ORDER BY joined_at ASC
            """,
            (thread_id, mid),
        ).fetchall()
        if others:
            new_owner = str(transfer_owner_to or "").strip()
            if not new_owner:
                raise ValueError("Transfer ownership to another member before leaving")
            if new_owner not in {str(r["member_id"]) for r in others}:
                raise ValueError("New owner must be an active channel member")
            conn.execute(
                "UPDATE msg_thread_members SET role = 'member' WHERE thread_id = ? AND member_id = ?",
                (thread_id, mid),
            )
            conn.execute(
                """
                UPDATE msg_thread_members SET role = 'owner'
                WHERE thread_id = ? AND member_id = ? AND left_at IS NULL
                """,
                (thread_id, new_owner),
            )
            conn.execute(
                "UPDATE msg_threads SET owner_member_id = ?, updated_at = ? WHERE id = ?",
                (new_owner, now, thread_id),
            )
        else:
            conn.execute(
                "UPDATE msg_threads SET archived_at = ?, updated_at = ? WHERE id = ?",
                (now, now, thread_id),
            )
    conn.execute(
        """
        UPDATE msg_thread_members SET left_at = ?, role = 'member'
        WHERE thread_id = ? AND member_id = ? AND left_at IS NULL
        """,
        (now, thread_id, mid),
    )
    conn.execute("UPDATE msg_threads SET updated_at = ? WHERE id = ?", (now, thread_id))
    conn.commit()
    return {"ok": True, "threadId": thread_id, "left": True}


def escalate_to_concern(
    conn: sqlite3.Connection,
    actor: dict,
    thread_id: str,
    *,
    message_ids: list[str] | None = None,
    body: str | None = None,
    subject: str | None = None,
    category: str | None = None,
) -> dict:
    """Create a Concerns mailbox item from chat context."""
    _ensure_msg_schema(conn)
    if _actor_view_only(actor):
        raise PermissionError("View-only access cannot escalate to Concerns")
    house = (actor.get("houseId") or "").strip()
    if not house or house == SUPERADMIN_HOUSE_ID:
        raise ValueError("Sign in as a plot to file a concern")
    thread = conn.execute("SELECT * FROM msg_threads WHERE id = ?", (thread_id,)).fetchone()
    if not thread:
        raise ValueError("Thread not found")
    if thread["kind"] == "ai":
        raise ValueError("AI chat cannot be escalated to Concerns")
    if not can_access_thread(conn, thread, actor):
        raise PermissionError("Not allowed")

    quotes: list[str] = []
    ids = [str(x).strip() for x in (message_ids or []) if str(x).strip()]
    if ids:
        placeholders = ",".join("?" * len(ids))
        rows = conn.execute(
            f"""
            SELECT id, author_name, house_id, body, created_at FROM msg_messages
            WHERE thread_id = ? AND status = 'active' AND id IN ({placeholders})
            ORDER BY created_at ASC
            """,
            (thread_id, *ids),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT id, author_name, house_id, body, created_at FROM msg_messages
            WHERE thread_id = ? AND status = 'active'
            ORDER BY created_at DESC LIMIT 12
            """,
            (thread_id,),
        ).fetchall()
        rows = list(reversed(rows))
    for r in rows:
        line = (r["body"] or "").strip() or "[attachment]"
        if len(line) > 280:
            line = line[:277] + "…"
        who = r["author_name"] or r["house_id"] or "Resident"
        quotes.append(f"{who}: {line}")

    channel_title = _thread_title(conn, thread, house)
    extra = (body or "").strip()
    parts = [
        f"Escalated from Chat ({thread['kind']}): {channel_title}",
        f"Open channel: /#messages/{thread_id}",
    ]
    if quotes:
        parts.append("")
        parts.append("Quoted messages:")
        parts.extend(f"- {q}" for q in quotes)
    if extra:
        parts.append("")
        parts.append(extra)
    concern_body = "\n".join(parts).strip()
    if len(concern_body) < 8:
        raise ValueError("Add a short note or select messages to escalate")
    if len(concern_body) > 4000:
        concern_body = concern_body[:3997] + "…"

    subj = (subject or "").strip()
    if not subj:
        subj = f"From Chat: {channel_title}"[:160]
    if len(subj) < 4:
        subj = "Escalated from Chat"

    import rwa_portal

    cat = (category or "other").strip().lower()
    created = rwa_portal.create_grievance(
        conn,
        house,
        {
            "category": cat if cat in rwa_portal.GRIEVANCE_CATEGORIES else "other",
            "subject": subj,
            "body": concern_body,
        },
    )
    return {
        "ok": True,
        "grievance": created,
        "concernId": created.get("id"),
        "url": "/#concerns",
    }


def set_group_icon(
    conn: sqlite3.Connection,
    site_root: pathlib.Path,
    actor: dict,
    thread_id: str,
    *,
    raw: bytes,
    content_type: str = "",
    original_name: str = "",
) -> dict:
    _ensure_msg_schema(conn)
    thread = conn.execute("SELECT * FROM msg_threads WHERE id = ?", (thread_id,)).fetchone()
    if not thread or thread["kind"] != "group":
        raise ValueError("Channel not found")
    if not can_manage_group(conn, thread, actor):
        raise PermissionError("Only the channel owner or EC can change the icon")
    data, _mime = _optimize_channel_image(
        raw, max_edge=CHANNEL_ICON_MAX_EDGE, max_bytes=CHANNEL_ICON_MAX_BYTES
    )
    filename = f"{thread_id}.webp"
    dest = _channel_asset_dir(site_root, "icons") / filename
    dest.write_bytes(data)
    now = utc_now()
    conn.execute(
        "UPDATE msg_threads SET icon_filename = ?, updated_at = ? WHERE id = ?",
        (filename, now, thread_id),
    )
    conn.commit()
    return get_thread(conn, thread_id, actor)


def clear_group_icon(
    conn: sqlite3.Connection,
    site_root: pathlib.Path,
    actor: dict,
    thread_id: str,
) -> dict:
    _ensure_msg_schema(conn)
    thread = conn.execute("SELECT * FROM msg_threads WHERE id = ?", (thread_id,)).fetchone()
    if not thread or thread["kind"] != "group":
        raise ValueError("Channel not found")
    if not can_manage_group(conn, thread, actor):
        raise PermissionError("Only the channel owner or EC can change the icon")
    filename = _thread_col(thread, "icon_filename") or ""
    if filename:
        path = _channel_asset_dir(site_root, "icons") / filename
        try:
            path.unlink(missing_ok=True)
        except TypeError:
            if path.is_file():
                path.unlink()
    now = utc_now()
    conn.execute(
        "UPDATE msg_threads SET icon_filename = NULL, updated_at = ? WHERE id = ?",
        (now, thread_id),
    )
    conn.commit()
    return get_thread(conn, thread_id, actor)


def get_group_icon_file(
    conn: sqlite3.Connection,
    site_root: pathlib.Path,
    actor: dict,
    thread_id: str,
) -> tuple[pathlib.Path, str]:
    _ensure_msg_schema(conn)
    thread = conn.execute("SELECT * FROM msg_threads WHERE id = ?", (thread_id,)).fetchone()
    if not thread or thread["kind"] != "group":
        raise ValueError("Channel not found")
    if not can_access_thread(conn, thread, actor):
        raise PermissionError("Not allowed")
    filename = _thread_col(thread, "icon_filename") or ""
    if not filename:
        raise FileNotFoundError("No channel icon")
    path = _channel_asset_dir(site_root, "icons") / filename
    if not path.is_file():
        raise FileNotFoundError("Icon file missing")
    return path, "image/webp"


def set_group_background(
    conn: sqlite3.Connection,
    site_root: pathlib.Path,
    actor: dict,
    thread_id: str,
    *,
    style: str | None = None,
    raw: bytes | None = None,
    clear_image: bool = False,
) -> dict:
    _ensure_msg_schema(conn)
    thread = conn.execute("SELECT * FROM msg_threads WHERE id = ?", (thread_id,)).fetchone()
    if not thread or thread["kind"] != "group":
        raise ValueError("Channel not found")
    if not can_manage_group(conn, thread, actor):
        raise PermissionError("Only the channel owner or EC can change the background")
    now = utc_now()
    filename = _thread_col(thread, "bg_filename") or ""
    if clear_image and filename:
        path = _channel_asset_dir(site_root, "backgrounds") / filename
        try:
            path.unlink(missing_ok=True)
        except TypeError:
            if path.is_file():
                path.unlink()
        filename = ""
        conn.execute(
            "UPDATE msg_threads SET bg_filename = NULL, updated_at = ? WHERE id = ?",
            (now, thread_id),
        )
    if raw is not None:
        data, _mime = _optimize_channel_image(
            raw, max_edge=CHANNEL_BG_MAX_EDGE, max_bytes=CHANNEL_BG_MAX_BYTES
        )
        filename = f"{thread_id}.webp"
        dest = _channel_asset_dir(site_root, "backgrounds") / filename
        dest.write_bytes(data)
        conn.execute(
            "UPDATE msg_threads SET bg_filename = ?, bg_style = 'custom', updated_at = ? WHERE id = ?",
            (filename, now, thread_id),
        )
    elif style is not None:
        chosen = _normalize_bg_style(style)
        if chosen == "custom" and not filename:
            raise ValueError("Upload a background image before choosing Custom image")
        conn.execute(
            "UPDATE msg_threads SET bg_style = ?, updated_at = ? WHERE id = ?",
            (chosen, now, thread_id),
        )
    conn.commit()
    return get_thread(conn, thread_id, actor)


def get_group_background_file(
    conn: sqlite3.Connection,
    site_root: pathlib.Path,
    actor: dict,
    thread_id: str,
) -> tuple[pathlib.Path, str]:
    _ensure_msg_schema(conn)
    thread = conn.execute("SELECT * FROM msg_threads WHERE id = ?", (thread_id,)).fetchone()
    if not thread or thread["kind"] != "group":
        raise ValueError("Channel not found")
    if not can_access_thread(conn, thread, actor):
        raise PermissionError("Not allowed")
    filename = _thread_col(thread, "bg_filename") or ""
    if not filename:
        raise FileNotFoundError("No custom background")
    path = _channel_asset_dir(site_root, "backgrounds") / filename
    if not path.is_file():
        raise FileNotFoundError("Background file missing")
    return path, "image/webp"


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
    kind = thread.get("kind") or ""
    if kind == "colony":
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
        return
    if kind == "group":
        rows = conn.execute(
            """
            SELECT member_id FROM msg_thread_members
            WHERE thread_id = ? AND left_at IS NULL
            """,
            (thread.get("id"),),
        ).fetchall()
        member_ids = [str(r["member_id"]) for r in rows if r["member_id"] and not str(r["member_id"]).startswith(TENANT_MEMBER_PREFIX)]
        if not member_ids:
            return
        title = thread.get("title") or "Private channel"
        if thread.get("isOfficial"):
            title = f"Official · {title}"
        rwa_push.enqueue_push(
            conn,
            site_root,
            event_type="message",
            audience={"type": "members", "memberIds": member_ids},
            title=title,
            body=f"{author}: {preview}",
            url=url,
            exclude_member_id=actor.get("memberId"),
        )
        return
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
