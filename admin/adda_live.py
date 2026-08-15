"""Mandi Adda — City of Mandi chat platform (public rooms, DMs, private channels, Sanyard pulse)."""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import re
import secrets
import sqlite3
import urllib.error
import urllib.request
from datetime import datetime, timezone
from functools import wraps
from io import BytesIO

from flask import jsonify, request, session, send_file

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PBKDF2_ROUNDS = 120_000
BODY_MAX = 4000
GROUP_MAX = 30
TITLE_MIN, TITLE_MAX = 2, 80
MSG_MAX_BYTES = 5_000_000
MSG_MAX_ATTACHMENTS = 3
ICON_MAX_EDGE, BG_MAX_EDGE = 512, 1600
ICON_MAX_BYTES, BG_MAX_BYTES = 2_000_000, 4_000_000
VEER_AI_URL = (os.environ.get("VEER_AI_URL") or "http://127.0.0.1:8095").rstrip("/")
VEER_AI_MODE = (os.environ.get("VEER_AI_MODE") or "flag").strip().lower()
VEER_AI_TIMEOUT_MS = max(50, min(int(os.environ.get("VEER_AI_TIMEOUT_MS") or 280), 5000))
SITE_ID_ENV = (os.environ.get("VEERCANVAS_SITE_ID") or "cityofmandi").strip()

CARD_THEMES = {
    "": "Default",
    "notice": "Notice",
    "urgent": "Urgent",
    "celebrate": "Celebrate",
    "official": "Official",
    "thanks": "Thanks",
}
BG_STYLES = {
    "none": "None",
    "soft": "Soft wash",
    "dots": "Dots",
    "grid": "Grid",
    "tiles": "Tiles",
    "diagonal": "Diagonal",
    "leaves": "Leaves",
    "custom": "Custom image",
}

SEED_ROOMS = [
    ("adda_lounge", "public", "Mandi Adda", "City lounge — say hello"),
    ("adda_news", "public", "News", "Talk about city news and updates"),
    ("adda_places", "public", "Places", "Spots in and around Mandi"),
    ("adda_scitech", "public", "SciTech", "Science, campus, makers, and tech"),
    ("adda_culture", "public", "Culture", "Festivals, heritage, food, and arts"),
    ("adda_services", "public", "Services", "Trades, help, and local services"),
    ("adda_jobs", "public", "Jobs", "Openings, gigs, and hiring around Mandi"),
    ("adda_seri_live", "public", "Seri Live", "Seri Live channel"),
    ("adda_dilli_lahore", "public", "Dilli Lahore Ki", "Fun gossip — light chatter only"),
    ("adda_channels", "public", "Channels", "Topic boards and channel talk"),
    ("adda_neighbourhoods", "public", "Neighbourhoods", "Colony and locality chatter"),
    ("adda_nb_sundernagar", "public", "Sunder Nagar", "Sundernagar town board"),
    ("adda_nb_nerchowk", "public", "Ner Chowk", "Ner Chowk locality"),
    ("adda_nb_sarkaghat", "public", "Sarkaghat", "Sarkaghat town board"),
    ("adda_nb_pandoh", "public", "Pandoh", "Pandoh dam town"),
    ("adda_nb_manali", "public", "Manali", "Manali & Mandi ties"),
    ("adda_nb_jogindernagar", "public", "Joginder Nagar", "Joginder Nagar locality"),
    ("adda_nb_chailchowk", "public", "Chail Chowk", "Chail Chowk junction"),
    ("adda_nb_karsog", "public", "Karsog", "Karsog valley"),
    ("adda_nb_siraj", "public", "Siraj", "Siraj region"),
    ("adda_nb_barot", "public", "Barot", "Barot & Uhl valley"),
    ("adda_nb_kamand", "public", "Kamand", "Kamand & IIT Mandi"),
    ("adda_sanyard_pulse", "bridge", "Sanyard pulse", "Highlights from Housing Colony Sanyard"),
]

# Pinned order in the channel list highlight strip.
HIGHLIGHT_ROOM_IDS = (
    "adda_lounge",
    "adda_news",
    "adda_services",
    "adda_jobs",
    "adda_nb_sundernagar",
    "adda_seri_live",
    "adda_dilli_lahore",
)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), PBKDF2_ROUNDS).hex()
    return f"pbkdf2${PBKDF2_ROUNDS}${salt}${digest}"


def _verify_password(password: str, stored: str) -> bool:
    try:
        kind, rounds, salt, digest = stored.split("$", 3)
    except ValueError:
        return False
    if kind != "pbkdf2":
        return False
    check = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(rounds)).hex()
    return secrets.compare_digest(check, digest)


def moderate_with_veer_ai(text: str, *, site_id: str = SITE_ID_ENV) -> dict:
    """Call Rust veer-ai sidecar. Fail-open when mode is not block and service is down."""
    mode = VEER_AI_MODE
    if mode not in {"off", "flag", "block"}:
        mode = "flag"
    if mode == "off" or not (text or "").strip():
        return {"ok": True, "action": "allow", "skipped": True, "mode": mode}
    payload = json.dumps({
        "text": text,
        "site_id": site_id,
        "context": "adda_message",
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{VEER_AI_URL}/v1/moderate",
        data=payload,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=VEER_AI_TIMEOUT_MS / 1000.0) as resp:
            data = json.loads(resp.read().decode("utf-8") or "{}")
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError, OSError):
        # Fail open for availability; operators can set block mode once sidecar is required.
        return {"ok": True, "action": "allow", "degraded": True, "mode": mode, "engine": "unavailable"}
    action = str(data.get("action") or "allow").strip().lower()
    if action not in {"allow", "flag", "block"}:
        action = "allow"
    data["ok"] = True
    data["action"] = action
    data["mode"] = mode
    return data


def _optimize_image(raw: bytes, *, max_edge: int, max_bytes: int) -> bytes:
    if len(raw) > max_bytes:
        raise ValueError(f"Image must be under {max_bytes // (1024 * 1024)} MB")
    try:
        from PIL import Image
    except ImportError as exc:
        raise ValueError("Image processing unavailable") from exc
    try:
        img = Image.open(BytesIO(raw))
        img.load()
    except Exception as exc:  # noqa: BLE001
        raise ValueError("Could not read image") from exc
    if img.mode not in ("RGB", "L"):
        if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
            rgba = img.convert("RGBA")
            bg = Image.new("RGB", rgba.size, (255, 255, 255))
            bg.paste(rgba, mask=rgba.split()[-1])
            img = bg
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
    data = buf.getvalue()
    if not data:
        raise ValueError("Could not encode image")
    return data


def register(app, *, check_login, site_root: pathlib.Path):
    data_dir = pathlib.Path(site_root) / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    db_path = data_dir / "hub.db"
    adda_root = data_dir / "adda"
    adda_root.mkdir(parents=True, exist_ok=True)

    def db():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def init_schema(conn: sqlite3.Connection) -> None:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS adda_users (
              id TEXT PRIMARY KEY,
              display_name TEXT NOT NULL,
              email TEXT NOT NULL UNIQUE,
              password_hash TEXT NOT NULL,
              publisher_id INTEGER,
              status TEXT NOT NULL DEFAULT 'active'
                CHECK(status IN ('active', 'paused')),
              created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_adda_users_email ON adda_users(email);
            CREATE INDEX IF NOT EXISTS idx_adda_users_publisher ON adda_users(publisher_id);

            CREATE TABLE IF NOT EXISTS adda_threads (
              id TEXT PRIMARY KEY,
              kind TEXT NOT NULL CHECK(kind IN ('public', 'dm', 'group', 'bridge')),
              title TEXT NOT NULL,
              subtitle TEXT NOT NULL DEFAULT '',
              user_a TEXT,
              user_b TEXT,
              owner_user_id TEXT,
              is_official INTEGER NOT NULL DEFAULT 0,
              archived_at TEXT,
              icon_filename TEXT,
              bg_style TEXT NOT NULL DEFAULT 'none',
              bg_filename TEXT,
              pinned_message_id TEXT,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_adda_threads_dm
              ON adda_threads(user_a, user_b) WHERE kind = 'dm';
            CREATE INDEX IF NOT EXISTS idx_adda_threads_updated ON adda_threads(updated_at DESC);

            CREATE TABLE IF NOT EXISTS adda_thread_members (
              thread_id TEXT NOT NULL,
              user_id TEXT NOT NULL,
              role TEXT NOT NULL DEFAULT 'member'
                CHECK(role IN ('owner', 'admin', 'member')),
              joined_at TEXT NOT NULL,
              left_at TEXT,
              PRIMARY KEY (thread_id, user_id),
              FOREIGN KEY(thread_id) REFERENCES adda_threads(id)
            );
            CREATE INDEX IF NOT EXISTS idx_adda_members_user
              ON adda_thread_members(user_id, left_at);

            CREATE TABLE IF NOT EXISTS adda_messages (
              id TEXT PRIMARY KEY,
              thread_id TEXT NOT NULL,
              author_user_id TEXT,
              author_name TEXT NOT NULL DEFAULT '',
              body TEXT NOT NULL DEFAULT '',
              status TEXT NOT NULL DEFAULT 'active'
                CHECK(status IN ('active', 'hidden', 'deleted')),
              card_theme TEXT,
              is_system INTEGER NOT NULL DEFAULT 0,
              created_at TEXT NOT NULL,
              edited_at TEXT,
              FOREIGN KEY(thread_id) REFERENCES adda_threads(id)
            );
            CREATE INDEX IF NOT EXISTS idx_adda_messages_thread
              ON adda_messages(thread_id, created_at DESC);

            CREATE TABLE IF NOT EXISTS adda_attachments (
              id TEXT PRIMARY KEY,
              message_id TEXT NOT NULL,
              thread_id TEXT NOT NULL,
              filename TEXT NOT NULL,
              original_name TEXT,
              mime TEXT NOT NULL,
              size_bytes INTEGER NOT NULL DEFAULT 0,
              created_at TEXT NOT NULL,
              FOREIGN KEY(message_id) REFERENCES adda_messages(id)
            );

            CREATE TABLE IF NOT EXISTS adda_reads (
              user_id TEXT NOT NULL,
              thread_id TEXT NOT NULL,
              last_read_at TEXT NOT NULL,
              PRIMARY KEY (user_id, thread_id)
            );

            CREATE TABLE IF NOT EXISTS adda_likes (
              message_id TEXT NOT NULL,
              user_id TEXT NOT NULL,
              created_at TEXT NOT NULL,
              PRIMARY KEY (message_id, user_id)
            );
            """
        )
        cols = {row[1] for row in conn.execute("PRAGMA table_info(adda_threads)").fetchall()}
        if "enabled" not in cols:
            conn.execute(
                "ALTER TABLE adda_threads ADD COLUMN enabled INTEGER NOT NULL DEFAULT 1"
            )
        if "hidden" not in cols:
            conn.execute(
                "ALTER TABLE adda_threads ADD COLUMN hidden INTEGER NOT NULL DEFAULT 0"
            )
        try:
            import board_contact

            board_contact.ensure_schema(conn)
        except Exception:
            pass
        now = _now()
        for tid, kind, title, subtitle in SEED_ROOMS:
            conn.execute(
                """
                INSERT OR IGNORE INTO adda_threads(
                  id, kind, title, subtitle, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (tid, kind, title, subtitle, now, now),
            )
        conn.commit()

    def ensure_db():
        conn = db()
        try:
            init_schema(conn)
        finally:
            conn.close()

    ensure_db()

    def current_user(conn: sqlite3.Connection) -> sqlite3.Row | None:
        uid = (session.get("adda_user_id") or "").strip()
        if not uid:
            return None
        row = conn.execute(
            "SELECT * FROM adda_users WHERE id = ? AND status = 'active'", (uid,)
        ).fetchone()
        if not row:
            session.pop("adda_user_id", None)
            session.pop("adda_display_name", None)
        return row

    def is_operator() -> bool:
        return bool(session.get("hub_operator") or session.get("logged_in"))

    def user_dict(row: sqlite3.Row) -> dict:
        return {
            "id": row["id"],
            "displayName": row["display_name"],
            "email": row["email"],
            "publisherId": row["publisher_id"],
            "status": row["status"],
            "createdAt": row["created_at"],
        }

    def require_user(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            conn = db()
            try:
                user = current_user(conn)
                if not user:
                    return jsonify({"ok": False, "error": "Sign in to Mandi Adda to continue"}), 401
                g_user = user
            finally:
                conn.close()
            return fn(g_user, *args, **kwargs)

        return wrapper

    def ensure_adda_user_for_publisher(conn: sqlite3.Connection, publisher: dict | sqlite3.Row) -> str:
        """Create or link Adda identity for a hub publisher; returns adda user id."""
        init_schema(conn)
        if hasattr(publisher, "keys"):
            pub = {k: publisher[k] for k in publisher.keys()}
        else:
            pub = dict(publisher)
        pub_id = int(pub["id"])
        email = str(pub.get("email") or "").strip().lower()
        name = str(pub.get("name") or "Publisher").strip()[:80] or "Publisher"
        row = conn.execute(
            "SELECT * FROM adda_users WHERE publisher_id = ?", (pub_id,)
        ).fetchone()
        if row:
            return row["id"]
        if email:
            by_email = conn.execute(
                "SELECT * FROM adda_users WHERE email = ?", (email,)
            ).fetchone()
            if by_email:
                conn.execute(
                    "UPDATE adda_users SET publisher_id = ?, display_name = ? WHERE id = ?",
                    (pub_id, name, by_email["id"]),
                )
                conn.commit()
                return by_email["id"]
        uid = f"au_{secrets.token_hex(8)}"
        # Linked publisher accounts use a non-login placeholder hash; they sign in via publisher session.
        conn.execute(
            """
            INSERT INTO adda_users(id, display_name, email, password_hash, publisher_id, status, created_at)
            VALUES (?, ?, ?, ?, ?, 'active', ?)
            """,
            (
                uid,
                name,
                email or f"publisher+{pub_id}@adda.local",
                "pbkdf2$1$x$linked-publisher",
                pub_id,
                _now(),
            ),
        )
        conn.commit()
        return uid

    def link_publisher_session():
        """If publisher is signed in but Adda session missing, provision and set Adda session."""
        pub_id = session.get("publisher_id")
        if not pub_id or session.get("adda_user_id"):
            return
        conn = db()
        try:
            pub = conn.execute("SELECT * FROM publishers WHERE id = ?", (int(pub_id),)).fetchone()
            if not pub or pub["status"] != "active":
                return
            uid = ensure_adda_user_for_publisher(conn, pub)
            session["adda_user_id"] = uid
            session["adda_display_name"] = pub["name"]
        finally:
            conn.close()

    def member_count(conn: sqlite3.Connection, thread_id: str) -> int:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM adda_thread_members WHERE thread_id = ? AND left_at IS NULL",
            (thread_id,),
        ).fetchone()
        return int(row["n"] if row else 0)

    def is_member(conn: sqlite3.Connection, thread_id: str, user_id: str) -> bool:
        return bool(
            conn.execute(
                """
                SELECT 1 FROM adda_thread_members
                WHERE thread_id = ? AND user_id = ? AND left_at IS NULL
                """,
                (thread_id, user_id),
            ).fetchone()
        )

    def can_access(conn: sqlite3.Connection, thread: sqlite3.Row, user: sqlite3.Row | None) -> bool:
        kind = thread["kind"]
        if kind in ("public", "bridge"):
            try:
                import board_contact

                staff_ok = board_contact.can_moderate_area(
                    conn,
                    user["id"] if user else None,
                    thread["id"],
                    operator=is_operator(),
                )
            except Exception:
                staff_ok = is_operator()
            enabled = int(thread["enabled"]) if "enabled" in thread.keys() else 1
            hidden = int(thread["hidden"]) if "hidden" in thread.keys() else 0
            if thread["archived_at"] and not staff_ok:
                return False
            if (not enabled or hidden) and not staff_ok:
                return False
            return True
        if not user:
            return False
        if is_operator():
            return True
        return is_member(conn, thread["id"], user["id"])

    def can_post(conn: sqlite3.Connection, thread: sqlite3.Row, user: sqlite3.Row | None) -> bool:
        if not user:
            return False
        if thread["kind"] == "bridge":
            return False
        if thread["archived_at"]:
            return False
        enabled = int(thread["enabled"]) if "enabled" in thread.keys() else 1
        if not enabled:
            try:
                import board_contact

                if not board_contact.can_moderate_area(
                    conn, user["id"], thread["id"], operator=is_operator()
                ):
                    return False
            except Exception:
                if not is_operator():
                    return False
        if thread["kind"] == "public":
            return True
        return is_member(conn, thread["id"], user["id"])

    def can_moderate_thread(
        conn: sqlite3.Connection, thread: sqlite3.Row, user: sqlite3.Row | None
    ) -> bool:
        if thread["kind"] not in ("public", "bridge"):
            return False
        try:
            import board_contact

            return board_contact.can_moderate_area(
                conn,
                user["id"] if user else None,
                thread["id"],
                operator=is_operator(),
            )
        except Exception:
            return is_operator()

    def can_manage_group(conn: sqlite3.Connection, thread: sqlite3.Row, user: sqlite3.Row | None) -> bool:
        if not user or thread["kind"] != "group":
            return False
        if is_operator():
            return True
        if thread["owner_user_id"] == user["id"]:
            return True
        # Group channel admins
        row = conn.execute(
            """
            SELECT role FROM adda_thread_members
            WHERE thread_id = ? AND user_id = ? AND left_at IS NULL
            """,
            (thread["id"], user["id"]),
        ).fetchone()
        return bool(row and row["role"] == "admin")

    def unread_count(conn: sqlite3.Connection, thread_id: str, user_id: str | None) -> int:
        if not user_id:
            return 0
        read = conn.execute(
            "SELECT last_read_at FROM adda_reads WHERE user_id = ? AND thread_id = ?",
            (user_id, thread_id),
        ).fetchone()
        if not read:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM adda_messages WHERE thread_id = ? AND status = 'active'",
                (thread_id,),
            ).fetchone()
            return int(row["n"])
        row = conn.execute(
            """
            SELECT COUNT(*) AS n FROM adda_messages
            WHERE thread_id = ? AND status = 'active' AND created_at > ?
            """,
            (thread_id, read["last_read_at"]),
        ).fetchone()
        return int(row["n"])

    def last_preview(conn: sqlite3.Connection, thread_id: str) -> dict | None:
        row = conn.execute(
            """
            SELECT author_name, body, created_at FROM adda_messages
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
        return {
            "authorName": row["author_name"],
            "body": body or "[attachment]",
            "createdAt": row["created_at"],
        }

    def public_thread(conn: sqlite3.Connection, thread: sqlite3.Row, user: sqlite3.Row | None) -> dict:
        uid = user["id"] if user else None
        icon = thread["icon_filename"] or ""
        bg_style = (thread["bg_style"] or "none").strip() or "none"
        bg_file = thread["bg_filename"] or ""
        title = thread["title"]
        if thread["kind"] == "dm" and user:
            other = thread["user_b"] if thread["user_a"] == user["id"] else thread["user_a"]
            peer = conn.execute(
                "SELECT display_name FROM adda_users WHERE id = ?", (other,)
            ).fetchone()
            if peer:
                title = peer["display_name"]
        return {
            "id": thread["id"],
            "kind": thread["kind"],
            "title": title,
            "subtitle": thread["subtitle"] or "",
            "isOfficial": bool(thread["is_official"]),
            "archivedAt": thread["archived_at"],
            "enabled": bool(int(thread["enabled"])) if "enabled" in thread.keys() else True,
            "hidden": bool(int(thread["hidden"])) if "hidden" in thread.keys() else False,
            "ownerUserId": thread["owner_user_id"],
            "memberCount": member_count(conn, thread["id"]) if thread["kind"] == "group" else 0,
            "canManage": can_manage_group(conn, thread, user),
            "canPost": can_post(conn, thread, user),
            "canModerate": can_moderate_thread(conn, thread, user),
            "readOnly": thread["kind"] == "bridge",
            "iconUrl": f"/api/adda/threads/{thread['id']}/icon" if icon else "",
            "hasIcon": bool(icon),
            "bgStyle": bg_style,
            "bgUrl": f"/api/adda/threads/{thread['id']}/background" if (bg_style == "custom" and bg_file) else "",
            "hasCustomBg": bool(bg_style == "custom" and bg_file),
            "unread": unread_count(conn, thread["id"], uid),
            "lastMessage": last_preview(conn, thread["id"]),
            "updatedAt": thread["updated_at"],
            "createdAt": thread["created_at"],
            "cardThemes": [{"id": k or "plain", "label": v} for k, v in CARD_THEMES.items()],
            "bgStyles": [{"id": k, "label": v} for k, v in BG_STYLES.items()],
        }

    def public_message(conn: sqlite3.Connection, row: sqlite3.Row, *, viewer_id: str | None, include_hidden=False) -> dict | None:
        if row["status"] == "deleted":
            return None
        likes = conn.execute(
            "SELECT COUNT(*) AS n FROM adda_likes WHERE message_id = ?", (row["id"],)
        ).fetchone()["n"]
        liked = False
        if viewer_id:
            liked = bool(
                conn.execute(
                    "SELECT 1 FROM adda_likes WHERE message_id = ? AND user_id = ?",
                    (row["id"], viewer_id),
                ).fetchone()
            )
        atts = []
        for a in conn.execute(
            "SELECT * FROM adda_attachments WHERE message_id = ? ORDER BY created_at ASC",
            (row["id"],),
        ).fetchall():
            atts.append({
                "id": a["id"],
                "filename": a["original_name"] or a["filename"],
                "mime": a["mime"],
                "sizeBytes": a["size_bytes"],
                "url": f"/api/adda/attachments/{a['id']}",
            })
        theme = (row["card_theme"] or "").strip().lower()
        if theme in ("plain", "none", "default"):
            theme = ""
        if row["status"] == "hidden" and not include_hidden:
            return {
                "id": row["id"],
                "threadId": row["thread_id"],
                "status": "hidden",
                "hidden": True,
                "body": "",
                "createdAt": row["created_at"],
                "likeCount": int(likes),
                "likedByMe": liked,
                "attachments": [],
                "cardTheme": "",
                "isSystem": bool(row["is_system"]),
            }
        return {
            "id": row["id"],
            "threadId": row["thread_id"],
            "authorUserId": row["author_user_id"],
            "authorName": row["author_name"],
            "body": row["body"] if row["status"] == "active" else "",
            "status": row["status"],
            "hidden": row["status"] == "hidden",
            "cardTheme": theme,
            "cardThemeLabel": CARD_THEMES.get(theme, "Default"),
            "isSystem": bool(row["is_system"]),
            "createdAt": row["created_at"],
            "editedAt": row["edited_at"] or "",
            "attachments": atts if row["status"] == "active" else [],
            "likeCount": int(likes),
            "likedByMe": liked,
        }

    def normalize_title(title: str) -> str:
        text = " ".join((title or "").split())
        if len(text) < TITLE_MIN:
            raise ValueError(f"Name needs at least {TITLE_MIN} characters")
        if len(text) > TITLE_MAX:
            raise ValueError(f"Name is too long (max {TITLE_MAX})")
        return text

    def normalize_theme(raw: str | None) -> str:
        theme = (raw or "").strip().lower()
        if theme in ("", "plain", "none", "default"):
            return ""
        if theme not in CARD_THEMES:
            raise ValueError("Unknown card theme")
        return theme

    def prepare_upload(raw: bytes, content_type: str, original_name: str) -> tuple[bytes, str, str]:
        ctype = (content_type or "").split(";")[0].strip().lower()
        name_l = (original_name or "").lower()
        if len(raw) > MSG_MAX_BYTES:
            raise ValueError("Each attachment must be under 5 MB")
        if ctype == "application/pdf" or name_l.endswith(".pdf"):
            if not raw.startswith(b"%PDF"):
                raise ValueError("File does not look like a PDF")
            return raw, "application/pdf", "pdf"
        if ctype.startswith("image/") or re.search(r"\.(jpe?g|png|webp|gif)$", name_l):
            data = _optimize_image(raw, max_edge=1600, max_bytes=MSG_MAX_BYTES)
            return data, "image/webp", "webp"
        raise ValueError("Supported attachments: JPG, PNG, WebP, GIF, or PDF")

    def asset_dir(kind: str) -> pathlib.Path:
        path = adda_root / kind
        path.mkdir(parents=True, exist_ok=True)
        return path

    # —— Bridge writer (called from civic_hub syndicate) ——
    def append_bridge_message(
        *,
        title: str,
        summary: str = "",
        url: str = "",
        source_site: str = "hbcsanyard",
        source_id: str = "",
    ) -> dict | None:
        conn = db()
        try:
            init_schema(conn)
            thread = conn.execute(
                "SELECT * FROM adda_threads WHERE id = ?", ("adda_sanyard_pulse",)
            ).fetchone()
            if not thread:
                return None
            now = _now()
            mid = f"am_{secrets.token_hex(8)}"
            bits = [title.strip()]
            if summary.strip():
                bits.append(summary.strip()[:400])
            if url.strip():
                bits.append(url.strip())
            body = "\n".join(bits)[:BODY_MAX]
            if source_id:
                # de-dupe by embedding source in a system marker check
                exists = conn.execute(
                    """
                    SELECT id FROM adda_messages
                    WHERE thread_id = ? AND is_system = 1 AND body LIKE ?
                    ORDER BY created_at DESC LIMIT 1
                    """,
                    ("adda_sanyard_pulse", f"%[{source_site}:{source_id}]%"),
                ).fetchone()
                if exists:
                    return {"id": exists["id"], "deduped": True}
                body = f"{body}\n[{source_site}:{source_id}]"
            conn.execute(
                """
                INSERT INTO adda_messages(
                  id, thread_id, author_user_id, author_name, body, status, is_system, created_at
                ) VALUES (?, 'adda_sanyard_pulse', NULL, ?, ?, 'active', 1, ?)
                """,
                (mid, "Sanyard", body, now),
            )
            conn.execute(
                "UPDATE adda_threads SET updated_at = ? WHERE id = 'adda_sanyard_pulse'",
                (now,),
            )
            conn.commit()
            return {"id": mid, "threadId": "adda_sanyard_pulse"}
        finally:
            conn.close()

    # Expose for civic_hub
    app.adda_append_bridge_message = append_bridge_message  # type: ignore[attr-defined]
    app.adda_ensure_user_for_publisher = lambda conn, pub: ensure_adda_user_for_publisher(conn, pub)  # type: ignore[attr-defined]

    # —— Auth ——
    @app.post("/api/adda/register")
    def adda_register():
        body = request.get_json(force=True, silent=True) or {}
        name = str(body.get("displayName") or body.get("name") or "").strip()
        email = str(body.get("email") or "").strip().lower()
        password = str(body.get("password") or "")
        if len(name) < 2:
            return jsonify({"ok": False, "error": "Enter a display name"}), 400
        if not EMAIL_RE.match(email):
            return jsonify({"ok": False, "error": "Enter a valid email"}), 400
        if len(password) < 8:
            return jsonify({"ok": False, "error": "Password must be at least 8 characters"}), 400
        conn = db()
        try:
            init_schema(conn)
            if conn.execute("SELECT id FROM adda_users WHERE email = ?", (email,)).fetchone():
                return jsonify({"ok": False, "error": "That email is already on Mandi Adda — sign in"}), 409
            uid = f"au_{secrets.token_hex(8)}"
            conn.execute(
                """
                INSERT INTO adda_users(id, display_name, email, password_hash, status, created_at)
                VALUES (?, ?, ?, ?, 'active', ?)
                """,
                (uid, name[:80], email, _hash_password(password), _now()),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM adda_users WHERE id = ?", (uid,)).fetchone()
        finally:
            conn.close()
        session["adda_user_id"] = uid
        session["adda_display_name"] = name[:80]
        return jsonify({"ok": True, "user": user_dict(row)}), 201

    @app.post("/api/adda/login")
    def adda_login():
        body = request.get_json(force=True, silent=True) or {}
        email = str(body.get("email") or "").strip().lower()
        password = str(body.get("password") or "")
        conn = db()
        try:
            init_schema(conn)
            row = conn.execute("SELECT * FROM adda_users WHERE email = ?", (email,)).fetchone()
        finally:
            conn.close()
        if not row or row["password_hash"].endswith("$linked-publisher"):
            return jsonify({"ok": False, "error": "Invalid email or password"}), 401
        if not _verify_password(password, row["password_hash"]):
            return jsonify({"ok": False, "error": "Invalid email or password"}), 401
        if row["status"] != "active":
            return jsonify({"ok": False, "error": "This Mandi Adda account is paused"}), 403
        session["adda_user_id"] = row["id"]
        session["adda_display_name"] = row["display_name"]
        return jsonify({"ok": True, "user": user_dict(row)})

    @app.post("/api/adda/logout")
    def adda_logout():
        session.pop("adda_user_id", None)
        session.pop("adda_display_name", None)
        return jsonify({"ok": True})

    @app.get("/api/adda/session")
    def adda_session():
        link_publisher_session()
        conn = db()
        try:
            init_schema(conn)
            user = current_user(conn)
            return jsonify({
                "ok": True,
                "authenticated": bool(user),
                "user": user_dict(user) if user else None,
                "isOperator": is_operator(),
                "cardThemes": [{"id": k or "plain", "label": v} for k, v in CARD_THEMES.items()],
                "bgStyles": [{"id": k, "label": v} for k, v in BG_STYLES.items()],
            })
        finally:
            conn.close()

    @app.post("/api/adda/link-publisher")
    def adda_link_publisher():
        """Attach Adda session from an already-signed-in publisher."""
        pub_id = session.get("publisher_id")
        if not pub_id:
            return jsonify({"ok": False, "error": "Sign in as a publisher first"}), 401
        conn = db()
        try:
            pub = conn.execute("SELECT * FROM publishers WHERE id = ?", (int(pub_id),)).fetchone()
            if not pub or pub["status"] != "active":
                return jsonify({"ok": False, "error": "Publisher account not available"}), 403
            uid = ensure_adda_user_for_publisher(conn, pub)
            session["adda_user_id"] = uid
            session["adda_display_name"] = pub["name"]
            user = conn.execute("SELECT * FROM adda_users WHERE id = ?", (uid,)).fetchone()
            return jsonify({"ok": True, "user": user_dict(user)})
        finally:
            conn.close()

    # —— Threads ——
    @app.get("/api/adda/threads")
    def adda_list_threads():
        link_publisher_session()
        conn = db()
        try:
            init_schema(conn)
            user = current_user(conn)
            out = []
            for r in conn.execute(
                """
                SELECT * FROM adda_threads
                WHERE kind IN ('public', 'bridge') AND archived_at IS NULL
                ORDER BY CASE id
                           WHEN 'adda_lounge' THEN 0
                           WHEN 'adda_news' THEN 1
                           WHEN 'adda_services' THEN 2
                           WHEN 'adda_jobs' THEN 3
                           WHEN 'adda_nb_sundernagar' THEN 4
                           WHEN 'adda_seri_live' THEN 5
                           WHEN 'adda_dilli_lahore' THEN 6
                           ELSE 100
                         END,
                         CASE kind WHEN 'public' THEN 0 ELSE 1 END, title
                """
            ).fetchall():
                if not can_access(conn, r, user):
                    continue
                out.append(public_thread(conn, r, user))
            if user:
                for r in conn.execute(
                    """
                    SELECT t.* FROM adda_threads t
                    INNER JOIN adda_thread_members m
                      ON m.thread_id = t.id AND m.user_id = ? AND m.left_at IS NULL
                    WHERE t.kind IN ('dm', 'group') AND t.archived_at IS NULL
                    ORDER BY t.updated_at DESC
                    """,
                    (user["id"],),
                ).fetchall():
                    out.append(public_thread(conn, r, user))
            return jsonify({
                "ok": True,
                "threads": out,
                "unreadTotal": sum(int(t.get("unread") or 0) for t in out),
                "authenticated": bool(user),
            })
        finally:
            conn.close()

    @app.get("/api/adda/threads/<thread_id>")
    def adda_get_thread(thread_id: str):
        link_publisher_session()
        since = (request.args.get("since") or "").strip() or None
        limit = max(1, min(int(request.args.get("limit") or 80), 100))
        conn = db()
        try:
            init_schema(conn)
            user = current_user(conn)
            thread = conn.execute("SELECT * FROM adda_threads WHERE id = ?", (thread_id,)).fetchone()
            if not thread:
                return jsonify({"ok": False, "error": "Room not found"}), 404
            if not can_access(conn, thread, user):
                return jsonify({"ok": False, "error": "Sign in to view this conversation"}), 401
            include_hidden = can_moderate_thread(conn, thread, user)
            if since:
                anchor = conn.execute(
                    "SELECT created_at FROM adda_messages WHERE id = ? AND thread_id = ?",
                    (since, thread_id),
                ).fetchone()
                rows = []
                if anchor:
                    rows = conn.execute(
                        """
                        SELECT * FROM adda_messages
                        WHERE thread_id = ? AND created_at > ? AND status != 'deleted'
                        ORDER BY created_at ASC LIMIT ?
                        """,
                        (thread_id, anchor["created_at"], limit),
                    ).fetchall()
            else:
                rows = list(
                    reversed(
                        conn.execute(
                            """
                            SELECT * FROM adda_messages
                            WHERE thread_id = ? AND status != 'deleted'
                            ORDER BY created_at DESC LIMIT ?
                            """,
                            (thread_id, limit),
                        ).fetchall()
                    )
                )
            messages = []
            viewer = user["id"] if user else None
            for r in rows:
                pub = public_message(conn, r, viewer_id=viewer, include_hidden=include_hidden)
                if pub:
                    messages.append(pub)
            pinned = None
            if thread["pinned_message_id"]:
                prow = conn.execute(
                    "SELECT * FROM adda_messages WHERE id = ?", (thread["pinned_message_id"],)
                ).fetchone()
                if prow:
                    pinned = public_message(conn, prow, viewer_id=viewer, include_hidden=True)
            return jsonify({
                "ok": True,
                "thread": public_thread(conn, thread, user),
                "messages": messages,
                "pinned": pinned,
                "canModerate": can_moderate_thread(conn, thread, user),
                "canManage": can_manage_group(conn, thread, user),
                "canPost": can_post(conn, thread, user),
                "canEscalate": bool(user) and thread["kind"] != "bridge",
                "canLeave": bool(user) and thread["kind"] == "group" and is_member(conn, thread_id, user["id"]),
                "canAdminChannel": (
                    thread["kind"] in ("public", "bridge")
                    and (
                        is_operator()
                        or (
                            user
                            and __import__("board_contact").can_admin_area(
                                conn, user["id"], thread["id"], operator=False
                            )
                        )
                    )
                ),
            })
        finally:
            conn.close()

    @app.post("/api/adda/threads/<thread_id>/messages")
    def adda_post_message(thread_id: str):
        link_publisher_session()
        conn = db()
        try:
            init_schema(conn)
            user = current_user(conn)
            if not user:
                return jsonify({"ok": False, "error": "Sign in to Mandi Adda to post"}), 401
            thread = conn.execute("SELECT * FROM adda_threads WHERE id = ?", (thread_id,)).fetchone()
            if not thread:
                return jsonify({"ok": False, "error": "Room not found"}), 404
            if not can_post(conn, thread, user):
                return jsonify({"ok": False, "error": "You cannot post in this room"}), 403
            files = []
            if request.content_type and "multipart/form-data" in (request.content_type or ""):
                body = (request.form.get("body") or "").strip()
                theme = (request.form.get("cardTheme") or "").strip() or None
                for f in request.files.getlist("files") or request.files.getlist("file"):
                    if f and f.filename:
                        files.append((f.read(), f.mimetype or "", f.filename))
            else:
                payload = request.get_json(force=True, silent=True) or {}
                body = (payload.get("body") or "").strip()
                theme = (payload.get("cardTheme") or "").strip() or None
            theme_n = normalize_theme(theme)
            if len(body) > BODY_MAX:
                return jsonify({"ok": False, "error": f"Message too long (max {BODY_MAX})"}), 400
            if len(files) > MSG_MAX_ATTACHMENTS:
                return jsonify({"ok": False, "error": f"At most {MSG_MAX_ATTACHMENTS} attachments"}), 400
            if not body and not files:
                return jsonify({"ok": False, "error": "Write a message or attach a file"}), 400
            mod = moderate_with_veer_ai(body, site_id=SITE_ID_ENV)
            mod_action = str(mod.get("action") or "allow")
            mode = str(mod.get("mode") or VEER_AI_MODE)
            if mode == "block" and mod_action == "block":
                return jsonify({
                    "ok": False,
                    "error": "Message blocked by Mandi Adda safety checks",
                    "moderation": {
                        "action": mod_action,
                        "labels": mod.get("labels") or [],
                        "reasons": mod.get("reasons") or [],
                    },
                }), 400
            if mode == "flag" and mod_action == "block":
                # Treat hard block as hold-for-review when running in flag mode.
                mod_action = "flag"
            msg_status = "hidden" if (mode in {"flag", "block"} and mod_action == "flag") else "active"
            now = _now()
            mid = f"am_{secrets.token_hex(8)}"
            conn.execute(
                """
                INSERT INTO adda_messages(
                  id, thread_id, author_user_id, author_name, body, status, card_theme, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (mid, thread_id, user["id"], user["display_name"], body, msg_status, theme_n or None, now),
            )
            conn.execute(
                "UPDATE adda_threads SET updated_at = ? WHERE id = ?", (now, thread_id)
            )
            for raw, ctype, oname in files:
                data, mime, ext = prepare_upload(raw, ctype, oname)
                fid = f"aa_{secrets.token_hex(8)}"
                filename = f"{fid}.{ext}"
                dest = asset_dir("files") / thread_id / mid
                dest.mkdir(parents=True, exist_ok=True)
                (dest / filename).write_bytes(data)
                conn.execute(
                    """
                    INSERT INTO adda_attachments(
                      id, message_id, thread_id, filename, original_name, mime, size_bytes, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (fid, mid, thread_id, f"{thread_id}/{mid}/{filename}", (oname or filename)[:180], mime, len(data), now),
                )
            conn.execute(
                """
                INSERT INTO adda_reads(user_id, thread_id, last_read_at)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id, thread_id) DO UPDATE SET last_read_at = excluded.last_read_at
                """,
                (user["id"], thread_id, now),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM adda_messages WHERE id = ?", (mid,)).fetchone()
            out = {
                "ok": True,
                "message": public_message(conn, row, viewer_id=user["id"], include_hidden=True),
                "thread": public_thread(conn, conn.execute("SELECT * FROM adda_threads WHERE id = ?", (thread_id,)).fetchone(), user),
            }
            if msg_status == "hidden":
                out["heldForReview"] = True
                out["notice"] = "Held for review by Mandi Adda safety checks"
                out["moderation"] = {
                    "action": "flag",
                    "labels": mod.get("labels") or [],
                    "reasons": mod.get("reasons") or [],
                    "engine": mod.get("engine") or "",
                }
            return jsonify(out)
        except ValueError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        finally:
            conn.close()

    @app.post("/api/adda/threads/<thread_id>/read")
    def adda_mark_read(thread_id: str):
        link_publisher_session()
        conn = db()
        try:
            user = current_user(conn)
            if not user:
                return jsonify({"ok": True, "skipped": True})
            thread = conn.execute("SELECT * FROM adda_threads WHERE id = ?", (thread_id,)).fetchone()
            if not thread or not can_access(conn, thread, user):
                return jsonify({"ok": False, "error": "Not allowed"}), 403
            now = _now()
            conn.execute(
                """
                INSERT INTO adda_reads(user_id, thread_id, last_read_at)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id, thread_id) DO UPDATE SET last_read_at = excluded.last_read_at
                """,
                (user["id"], thread_id, now),
            )
            conn.commit()
            return jsonify({"ok": True, "unread": unread_count(conn, thread_id, user["id"])})
        finally:
            conn.close()

    @app.post("/api/adda/messages/<message_id>/like")
    def adda_like(message_id: str):
        link_publisher_session()
        conn = db()
        try:
            user = current_user(conn)
            if not user:
                return jsonify({"ok": False, "error": "Sign in required"}), 401
            row = conn.execute("SELECT * FROM adda_messages WHERE id = ?", (message_id,)).fetchone()
            if not row or row["status"] != "active":
                return jsonify({"ok": False, "error": "Message not found"}), 404
            thread = conn.execute("SELECT * FROM adda_threads WHERE id = ?", (row["thread_id"],)).fetchone()
            if not thread or not can_access(conn, thread, user):
                return jsonify({"ok": False, "error": "Not allowed"}), 403
            existing = conn.execute(
                "SELECT 1 FROM adda_likes WHERE message_id = ? AND user_id = ?",
                (message_id, user["id"]),
            ).fetchone()
            if existing:
                conn.execute(
                    "DELETE FROM adda_likes WHERE message_id = ? AND user_id = ?",
                    (message_id, user["id"]),
                )
                liked = False
            else:
                conn.execute(
                    "INSERT INTO adda_likes(message_id, user_id, created_at) VALUES (?, ?, ?)",
                    (message_id, user["id"], _now()),
                )
                liked = True
            conn.commit()
            count = conn.execute(
                "SELECT COUNT(*) AS n FROM adda_likes WHERE message_id = ?", (message_id,)
            ).fetchone()["n"]
            return jsonify({"ok": True, "likedByMe": liked, "likeCount": int(count)})
        finally:
            conn.close()

    @app.get("/api/adda/people")
    def adda_people():
        link_publisher_session()
        q = (request.args.get("q") or "").strip().lower()
        conn = db()
        try:
            user = current_user(conn)
            if not user:
                return jsonify({"ok": False, "error": "Sign in required"}), 401
            rows = conn.execute(
                """
                SELECT id, display_name, email FROM adda_users
                WHERE status = 'active' AND id != ?
                ORDER BY display_name COLLATE NOCASE
                LIMIT 200
                """,
                (user["id"],),
            ).fetchall()
            out = []
            for r in rows:
                label = f"{r['display_name']}"
                hay = f"{label} {r['email']}".lower()
                if q and q not in hay:
                    continue
                out.append({
                    "userId": r["id"],
                    "displayName": r["display_name"],
                    "label": label,
                })
            return jsonify({"ok": True, "people": out[:80]})
        finally:
            conn.close()

    @app.post("/api/adda/dm")
    def adda_open_dm():
        link_publisher_session()
        payload = request.get_json(force=True, silent=True) or {}
        peer = str(payload.get("userId") or payload.get("peerUserId") or "").strip()
        conn = db()
        try:
            user = current_user(conn)
            if not user:
                return jsonify({"ok": False, "error": "Sign in required"}), 401
            if not peer or peer == user["id"]:
                return jsonify({"ok": False, "error": "Choose someone to message"}), 400
            peer_row = conn.execute(
                "SELECT * FROM adda_users WHERE id = ? AND status = 'active'", (peer,)
            ).fetchone()
            if not peer_row:
                return jsonify({"ok": False, "error": "Person not found"}), 404
            a, b = (user["id"], peer) if user["id"] < peer else (peer, user["id"])
            row = conn.execute(
                "SELECT * FROM adda_threads WHERE kind = 'dm' AND user_a = ? AND user_b = ?",
                (a, b),
            ).fetchone()
            now = _now()
            if not row:
                tid = f"adm_{secrets.token_hex(8)}"
                title = peer_row["display_name"]
                conn.execute(
                    """
                    INSERT INTO adda_threads(
                      id, kind, title, user_a, user_b, created_at, updated_at
                    ) VALUES (?, 'dm', ?, ?, ?, ?, ?)
                    """,
                    (tid, title, a, b, now, now),
                )
                for uid in (a, b):
                    conn.execute(
                        """
                        INSERT INTO adda_thread_members(thread_id, user_id, role, joined_at)
                        VALUES (?, ?, 'member', ?)
                        """,
                        (tid, uid, now),
                    )
                conn.commit()
                row = conn.execute("SELECT * FROM adda_threads WHERE id = ?", (tid,)).fetchone()
            # Title from peer perspective
            pub = public_thread(conn, row, user)
            other = peer_row["display_name"] if peer != user["id"] else pub["title"]
            pub["title"] = other
            return jsonify({"ok": True, "thread": pub})
        finally:
            conn.close()

    @app.post("/api/adda/groups")
    def adda_create_group():
        link_publisher_session()
        payload = request.get_json(force=True, silent=True) or {}
        conn = db()
        try:
            user = current_user(conn)
            if not user:
                return jsonify({"ok": False, "error": "Sign in required"}), 401
            title = normalize_title(payload.get("title") or "")
            member_ids = payload.get("memberIds") or []
            if not isinstance(member_ids, list):
                member_ids = []
            cleaned = []
            seen = {user["id"]}
            for raw in member_ids:
                mid = str(raw or "").strip()
                if not mid or mid in seen:
                    continue
                seen.add(mid)
                if not conn.execute(
                    "SELECT 1 FROM adda_users WHERE id = ? AND status = 'active'", (mid,)
                ).fetchone():
                    return jsonify({"ok": False, "error": "One or more people were not found"}), 400
                cleaned.append(mid)
            if 1 + len(cleaned) > GROUP_MAX:
                return jsonify({"ok": False, "error": f"At most {GROUP_MAX} people"}), 400
            now = _now()
            tid = f"agr_{secrets.token_hex(8)}"
            official = 1 if payload.get("isOfficial") else 0
            conn.execute(
                """
                INSERT INTO adda_threads(
                  id, kind, title, owner_user_id, is_official, created_at, updated_at
                ) VALUES (?, 'group', ?, ?, ?, ?, ?)
                """,
                (tid, title, user["id"], official, now, now),
            )
            conn.execute(
                """
                INSERT INTO adda_thread_members(thread_id, user_id, role, joined_at)
                VALUES (?, ?, 'owner', ?)
                """,
                (tid, user["id"], now),
            )
            for mid in cleaned:
                conn.execute(
                    """
                    INSERT INTO adda_thread_members(thread_id, user_id, role, joined_at)
                    VALUES (?, ?, 'member', ?)
                    """,
                    (tid, mid, now),
                )
            conn.commit()
            row = conn.execute("SELECT * FROM adda_threads WHERE id = ?", (tid,)).fetchone()
            return jsonify({"ok": True, "thread": public_thread(conn, row, user)}), 201
        except ValueError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        finally:
            conn.close()

    @app.patch("/api/adda/threads/<thread_id>")
    def adda_patch_thread(thread_id: str):
        link_publisher_session()
        payload = request.get_json(force=True, silent=True) or {}
        conn = db()
        try:
            user = current_user(conn)
            if not user:
                return jsonify({"ok": False, "error": "Sign in required"}), 401
            thread = conn.execute("SELECT * FROM adda_threads WHERE id = ?", (thread_id,)).fetchone()
            if not thread or thread["kind"] != "group":
                return jsonify({"ok": False, "error": "Channel not found"}), 404
            if not can_manage_group(conn, thread, user):
                return jsonify({"ok": False, "error": "Only the owner or operator can manage this channel"}), 403
            now = _now()
            if "title" in payload:
                conn.execute(
                    "UPDATE adda_threads SET title = ?, updated_at = ? WHERE id = ?",
                    (normalize_title(payload.get("title") or ""), now, thread_id),
                )
            if "isOfficial" in payload:
                conn.execute(
                    "UPDATE adda_threads SET is_official = ?, updated_at = ? WHERE id = ?",
                    (1 if payload.get("isOfficial") else 0, now, thread_id),
                )
            archive = payload.get("archive")
            if isinstance(archive, bool):
                if archive:
                    conn.execute(
                        "UPDATE adda_threads SET archived_at = ?, updated_at = ? WHERE id = ?",
                        (now, now, thread_id),
                    )
                else:
                    conn.execute(
                        "UPDATE adda_threads SET archived_at = NULL, updated_at = ? WHERE id = ?",
                        (now, thread_id),
                    )
            if "bgStyle" in payload:
                style = str(payload.get("bgStyle") or "none").strip().lower()
                if style not in BG_STYLES:
                    return jsonify({"ok": False, "error": "Unknown background style"}), 400
                if style == "custom" and not thread["bg_filename"]:
                    return jsonify({"ok": False, "error": "Upload a background image first"}), 400
                conn.execute(
                    "UPDATE adda_threads SET bg_style = ?, updated_at = ? WHERE id = ?",
                    (style, now, thread_id),
                )
            transfer = str(payload.get("transferOwnerTo") or "").strip()
            if transfer:
                if not is_member(conn, thread_id, transfer):
                    return jsonify({"ok": False, "error": "New owner must be a member"}), 400
                conn.execute(
                    "UPDATE adda_thread_members SET role = 'member' WHERE thread_id = ? AND role = 'owner'",
                    (thread_id,),
                )
                conn.execute(
                    "UPDATE adda_thread_members SET role = 'owner' WHERE thread_id = ? AND user_id = ?",
                    (thread_id, transfer),
                )
                conn.execute(
                    "UPDATE adda_threads SET owner_user_id = ?, updated_at = ? WHERE id = ?",
                    (transfer, now, thread_id),
                )
            conn.commit()
            row = conn.execute("SELECT * FROM adda_threads WHERE id = ?", (thread_id,)).fetchone()
            return jsonify({"ok": True, "thread": public_thread(conn, row, user)})
        except ValueError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        finally:
            conn.close()

    @app.get("/api/adda/threads/<thread_id>/members")
    def adda_list_members(thread_id: str):
        link_publisher_session()
        conn = db()
        try:
            user = current_user(conn)
            thread = conn.execute("SELECT * FROM adda_threads WHERE id = ?", (thread_id,)).fetchone()
            if not thread:
                return jsonify({"ok": False, "error": "Not found"}), 404
            if not can_access(conn, thread, user):
                return jsonify({"ok": False, "error": "Not allowed"}), 403
            rows = conn.execute(
                """
                SELECT m.user_id, m.role, m.joined_at, u.display_name
                FROM adda_thread_members m
                JOIN adda_users u ON u.id = m.user_id
                WHERE m.thread_id = ? AND m.left_at IS NULL
                ORDER BY CASE m.role WHEN 'owner' THEN 0 ELSE 1 END, u.display_name
                """,
                (thread_id,),
            ).fetchall()
            members = [
                {
                    "userId": r["user_id"],
                    "role": r["role"],
                    "displayName": r["display_name"],
                    "joinedAt": r["joined_at"],
                    "label": f"{r['display_name']}{' · Owner' if r['role'] == 'owner' else ''}",
                }
                for r in rows
            ]
            return jsonify({"ok": True, "members": members})
        finally:
            conn.close()

    @app.post("/api/adda/threads/<thread_id>/members")
    def adda_add_members(thread_id: str):
        link_publisher_session()
        payload = request.get_json(force=True, silent=True) or {}
        conn = db()
        try:
            user = current_user(conn)
            if not user:
                return jsonify({"ok": False, "error": "Sign in required"}), 401
            thread = conn.execute("SELECT * FROM adda_threads WHERE id = ?", (thread_id,)).fetchone()
            if not thread or thread["kind"] != "group":
                return jsonify({"ok": False, "error": "Channel not found"}), 404
            if not can_manage_group(conn, thread, user):
                return jsonify({"ok": False, "error": "Not allowed"}), 403
            ids = payload.get("memberIds") or []
            if not isinstance(ids, list) or not ids:
                return jsonify({"ok": False, "error": "Choose people to add"}), 400
            now = _now()
            added = 0
            active = member_count(conn, thread_id)
            for raw in ids:
                mid = str(raw or "").strip()
                if not mid:
                    continue
                if not conn.execute(
                    "SELECT 1 FROM adda_users WHERE id = ? AND status = 'active'", (mid,)
                ).fetchone():
                    continue
                existing = conn.execute(
                    "SELECT left_at FROM adda_thread_members WHERE thread_id = ? AND user_id = ?",
                    (thread_id, mid),
                ).fetchone()
                if existing and existing["left_at"] is None:
                    continue
                if active + added >= GROUP_MAX:
                    break
                if existing:
                    conn.execute(
                        """
                        UPDATE adda_thread_members SET left_at = NULL, joined_at = ?, role = 'member'
                        WHERE thread_id = ? AND user_id = ?
                        """,
                        (now, thread_id, mid),
                    )
                else:
                    conn.execute(
                        """
                        INSERT INTO adda_thread_members(thread_id, user_id, role, joined_at)
                        VALUES (?, ?, 'member', ?)
                        """,
                        (thread_id, mid, now),
                    )
                added += 1
            conn.execute("UPDATE adda_threads SET updated_at = ? WHERE id = ?", (now, thread_id))
            conn.commit()
            return jsonify({"ok": True, "added": added})
        finally:
            conn.close()

    @app.delete("/api/adda/threads/<thread_id>/members/<user_id>")
    def adda_remove_member(thread_id: str, user_id: str):
        link_publisher_session()
        conn = db()
        try:
            user = current_user(conn)
            if not user:
                return jsonify({"ok": False, "error": "Sign in required"}), 401
            thread = conn.execute("SELECT * FROM adda_threads WHERE id = ?", (thread_id,)).fetchone()
            if not thread or thread["kind"] != "group":
                return jsonify({"ok": False, "error": "Channel not found"}), 404
            if not can_manage_group(conn, thread, user):
                return jsonify({"ok": False, "error": "Not allowed"}), 403
            if user_id == user["id"]:
                return jsonify({"ok": False, "error": "Use Leave to remove yourself"}), 400
            role = conn.execute(
                "SELECT role FROM adda_thread_members WHERE thread_id = ? AND user_id = ? AND left_at IS NULL",
                (thread_id, user_id),
            ).fetchone()
            if not role:
                return jsonify({"ok": False, "error": "Not a member"}), 404
            if role["role"] == "owner":
                return jsonify({"ok": False, "error": "Transfer ownership first"}), 400
            conn.execute(
                "UPDATE adda_thread_members SET left_at = ? WHERE thread_id = ? AND user_id = ?",
                (_now(), thread_id, user_id),
            )
            conn.commit()
            return jsonify({"ok": True})
        finally:
            conn.close()

    @app.post("/api/adda/threads/<thread_id>/leave")
    def adda_leave(thread_id: str):
        link_publisher_session()
        payload = request.get_json(force=True, silent=True) or {}
        conn = db()
        try:
            user = current_user(conn)
            if not user:
                return jsonify({"ok": False, "error": "Sign in required"}), 401
            thread = conn.execute("SELECT * FROM adda_threads WHERE id = ?", (thread_id,)).fetchone()
            if not thread or thread["kind"] != "group":
                return jsonify({"ok": False, "error": "Channel not found"}), 404
            if not is_member(conn, thread_id, user["id"]):
                return jsonify({"ok": False, "error": "Not in this channel"}), 400
            now = _now()
            role = conn.execute(
                "SELECT role FROM adda_thread_members WHERE thread_id = ? AND user_id = ? AND left_at IS NULL",
                (thread_id, user["id"]),
            ).fetchone()
            if role and role["role"] == "owner":
                others = conn.execute(
                    """
                    SELECT user_id FROM adda_thread_members
                    WHERE thread_id = ? AND left_at IS NULL AND user_id != ?
                    """,
                    (thread_id, user["id"]),
                ).fetchall()
                if others:
                    transfer = str(payload.get("transferOwnerTo") or "").strip()
                    if not transfer or transfer not in {r["user_id"] for r in others}:
                        return jsonify({"ok": False, "error": "Transfer ownership before leaving"}), 400
                    conn.execute(
                        "UPDATE adda_thread_members SET role = 'member' WHERE thread_id = ? AND user_id = ?",
                        (thread_id, user["id"]),
                    )
                    conn.execute(
                        "UPDATE adda_thread_members SET role = 'owner' WHERE thread_id = ? AND user_id = ?",
                        (thread_id, transfer),
                    )
                    conn.execute(
                        "UPDATE adda_threads SET owner_user_id = ? WHERE id = ?",
                        (transfer, thread_id),
                    )
                else:
                    conn.execute(
                        "UPDATE adda_threads SET archived_at = ? WHERE id = ?",
                        (now, thread_id),
                    )
            conn.execute(
                "UPDATE adda_thread_members SET left_at = ?, role = 'member' WHERE thread_id = ? AND user_id = ?",
                (now, thread_id, user["id"]),
            )
            conn.commit()
            return jsonify({"ok": True, "left": True})
        finally:
            conn.close()

    def _media_route(thread_id: str, kind: str):
        link_publisher_session()
        conn = db()
        try:
            user = current_user(conn)
            thread = conn.execute("SELECT * FROM adda_threads WHERE id = ?", (thread_id,)).fetchone()
            if not thread or thread["kind"] != "group":
                return jsonify({"ok": False, "error": "Channel not found"}), 404
            if request.method == "GET":
                if not can_access(conn, thread, user):
                    return jsonify({"ok": False, "error": "Not allowed"}), 403
                filename = thread["icon_filename"] if kind == "icon" else thread["bg_filename"]
                if not filename:
                    return jsonify({"ok": False, "error": "Not found"}), 404
                path = asset_dir(kind + "s") / filename
                if not path.is_file():
                    return jsonify({"ok": False, "error": "File missing"}), 404
                return send_file(path, mimetype="image/webp", conditional=True)
            if not user or not can_manage_group(conn, thread, user):
                return jsonify({"ok": False, "error": "Not allowed"}), 403
            if request.method == "DELETE":
                col = "icon_filename" if kind == "icon" else "bg_filename"
                filename = thread[col]
                if filename:
                    path = asset_dir(kind + "s") / filename
                    if path.is_file():
                        path.unlink()
                if kind == "icon":
                    conn.execute(
                        "UPDATE adda_threads SET icon_filename = NULL, updated_at = ? WHERE id = ?",
                        (_now(), thread_id),
                    )
                else:
                    conn.execute(
                        "UPDATE adda_threads SET bg_filename = NULL, bg_style = 'none', updated_at = ? WHERE id = ?",
                        (_now(), thread_id),
                    )
                conn.commit()
                row = conn.execute("SELECT * FROM adda_threads WHERE id = ?", (thread_id,)).fetchone()
                return jsonify({"ok": True, "thread": public_thread(conn, row, user)})
            upload = request.files.get("file") or request.files.get(kind)
            if kind == "background" and not upload:
                payload = request.get_json(force=True, silent=True) or {}
                style = (request.form.get("bgStyle") or payload.get("bgStyle") or "").strip().lower()
                if style in BG_STYLES:
                    if style == "custom" and not thread["bg_filename"]:
                        return jsonify({"ok": False, "error": "Upload an image first"}), 400
                    conn.execute(
                        "UPDATE adda_threads SET bg_style = ?, updated_at = ? WHERE id = ?",
                        (style, _now(), thread_id),
                    )
                    conn.commit()
                    row = conn.execute("SELECT * FROM adda_threads WHERE id = ?", (thread_id,)).fetchone()
                    return jsonify({"ok": True, "thread": public_thread(conn, row, user)})
            if not upload or not upload.filename:
                return jsonify({"ok": False, "error": "Choose an image"}), 400
            edge = ICON_MAX_EDGE if kind == "icon" else BG_MAX_EDGE
            max_b = ICON_MAX_BYTES if kind == "icon" else BG_MAX_BYTES
            data = _optimize_image(upload.read(), max_edge=edge, max_bytes=max_b)
            filename = f"{thread_id}.webp"
            (asset_dir(kind + "s") / filename).write_bytes(data)
            if kind == "icon":
                conn.execute(
                    "UPDATE adda_threads SET icon_filename = ?, updated_at = ? WHERE id = ?",
                    (filename, _now(), thread_id),
                )
            else:
                conn.execute(
                    "UPDATE adda_threads SET bg_filename = ?, bg_style = 'custom', updated_at = ? WHERE id = ?",
                    (filename, _now(), thread_id),
                )
            conn.commit()
            row = conn.execute("SELECT * FROM adda_threads WHERE id = ?", (thread_id,)).fetchone()
            return jsonify({"ok": True, "thread": public_thread(conn, row, user)})
        except ValueError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        finally:
            conn.close()

    @app.route("/api/adda/threads/<thread_id>/icon", methods=["GET", "POST", "DELETE"])
    def adda_icon(thread_id: str):
        return _media_route(thread_id, "icon")

    @app.route("/api/adda/threads/<thread_id>/background", methods=["GET", "POST", "DELETE"])
    def adda_background(thread_id: str):
        return _media_route(thread_id, "background")

    @app.post("/api/adda/threads/<thread_id>/escalate")
    def adda_escalate(thread_id: str):
        link_publisher_session()
        payload = request.get_json(force=True, silent=True) or {}
        conn = db()
        try:
            user = current_user(conn)
            if not user:
                return jsonify({"ok": False, "error": "Sign in required"}), 401
            thread = conn.execute("SELECT * FROM adda_threads WHERE id = ?", (thread_id,)).fetchone()
            if not thread or thread["kind"] == "bridge":
                return jsonify({"ok": False, "error": "Cannot escalate this room"}), 400
            if not can_access(conn, thread, user):
                return jsonify({"ok": False, "error": "Not allowed"}), 403
            rows = conn.execute(
                """
                SELECT author_name, body FROM adda_messages
                WHERE thread_id = ? AND status = 'active'
                ORDER BY created_at DESC LIMIT 12
                """,
                (thread_id,),
            ).fetchall()
            quotes = []
            for r in reversed(rows):
                line = (r["body"] or "").strip() or "[attachment]"
                if len(line) > 200:
                    line = line[:197] + "…"
                quotes.append(f"- {r['author_name']}: {line}")
            subject = (payload.get("subject") or f"From Mandi Adda: {thread['title']}").strip()[:120]
            note = (payload.get("body") or payload.get("note") or "").strip()
            body_parts = [
                f"Escalated from Mandi Adda ({thread['kind']}): {thread['title']}",
                f"Open: /adda#room/{thread_id}",
            ]
            if quotes:
                body_parts.append("")
                body_parts.append("Quoted:")
                body_parts.extend(quotes)
            body_text = "\n".join(body_parts)[:8000]
            import board_contact

            board_contact.ensure_schema(conn)
            mid = f"bm_{secrets.token_hex(8)}"
            now = _now()
            full = body_text
            if note:
                full = f"{note.strip()}\n\n---\n\n{body_text}"
            conn.execute(
                """
                INSERT INTO board_mail(
                  id, area_id, category, subject, body, status,
                  author_name, author_email, author_user_id, author_publisher_id,
                  source_adda_thread_id, created_at, updated_at
                ) VALUES (?, ?, 'adda', ?, ?, 'open', ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    mid,
                    thread["id"],
                    subject[:160],
                    full[:8000],
                    user["display_name"],
                    user["email"] or "",
                    user["id"],
                    user["publisher_id"],
                    thread["id"],
                    now,
                    now,
                ),
            )
            conn.commit()
            return jsonify({
                "ok": True,
                "mailId": mid,
                "url": f"/contact#mail/{mid}",
                "message": "Sent to the Contact Board mailbox",
            }), 201
        finally:
            conn.close()

    @app.post("/api/adda/messages/<message_id>/moderate")
    def adda_moderate(message_id: str):
        link_publisher_session()
        payload = request.get_json(force=True, silent=True) or {}
        action = str(payload.get("action") or "").strip().lower()
        conn = db()
        try:
            user = current_user(conn)
            row = conn.execute("SELECT * FROM adda_messages WHERE id = ?", (message_id,)).fetchone()
            if not row:
                return jsonify({"ok": False, "error": "Message not found"}), 404
            thread = conn.execute("SELECT * FROM adda_threads WHERE id = ?", (row["thread_id"],)).fetchone()
            if not thread or thread["kind"] not in ("public", "bridge"):
                return jsonify({"ok": False, "error": "Only public rooms can be moderated here"}), 400
            if not can_moderate_thread(conn, thread, user):
                return jsonify({"ok": False, "error": "Moderator access required"}), 403
            if action == "hide":
                conn.execute("UPDATE adda_messages SET status = 'hidden' WHERE id = ?", (message_id,))
            elif action == "unhide":
                conn.execute("UPDATE adda_messages SET status = 'active' WHERE id = ?", (message_id,))
            elif action == "delete":
                conn.execute("UPDATE adda_messages SET status = 'deleted' WHERE id = ?", (message_id,))
                if thread["pinned_message_id"] == message_id:
                    conn.execute(
                        "UPDATE adda_threads SET pinned_message_id = NULL WHERE id = ?",
                        (thread["id"],),
                    )
            elif action == "pin":
                conn.execute(
                    "UPDATE adda_threads SET pinned_message_id = ? WHERE id = ?",
                    (message_id, thread["id"]),
                )
            elif action == "unpin":
                conn.execute(
                    "UPDATE adda_threads SET pinned_message_id = NULL WHERE id = ? AND pinned_message_id = ?",
                    (thread["id"], message_id),
                )
            else:
                return jsonify({"ok": False, "error": "Unknown action"}), 400
            conn.commit()
            return jsonify({"ok": True})
        finally:
            conn.close()

    @app.get("/api/adda/attachments/<file_id>")
    def adda_attachment(file_id: str):
        link_publisher_session()
        conn = db()
        try:
            user = current_user(conn)
            row = conn.execute("SELECT * FROM adda_attachments WHERE id = ?", (file_id,)).fetchone()
            if not row:
                return jsonify({"ok": False, "error": "Not found"}), 404
            thread = conn.execute("SELECT * FROM adda_threads WHERE id = ?", (row["thread_id"],)).fetchone()
            if not thread or not can_access(conn, thread, user):
                return jsonify({"ok": False, "error": "Not allowed"}), 403
            path = asset_dir("files") / row["filename"]
            if not path.is_file():
                return jsonify({"ok": False, "error": "File missing"}), 404
            return send_file(
                path,
                mimetype=row["mime"],
                download_name=row["original_name"] or path.name,
                conditional=True,
            )
        finally:
            conn.close()
