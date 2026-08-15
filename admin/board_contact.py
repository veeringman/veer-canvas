"""City of Mandi — Contact Board mailbox, channel staff, and visibility controls."""

from __future__ import annotations

import pathlib
import re
import secrets
import sqlite3
from datetime import datetime, timezone
from functools import wraps

from flask import jsonify, request, session

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
CITYWIDE = "citywide"
STAFF_ROLES = ("admin", "moderator")
MAIL_STATUSES = ("open", "in_progress", "resolved", "hidden")
MAIL_CATEGORIES = (
    {"id": "general", "title": "General"},
    {"id": "safety", "title": "Safety / urgent"},
    {"id": "listing", "title": "Listing / publish"},
    {"id": "adda", "title": "Mandi Adda"},
    {"id": "channel", "title": "Channel / neighbourhood"},
    {"id": "other", "title": "Other"},
)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS board_staff (
          area_id TEXT NOT NULL,
          user_id TEXT NOT NULL,
          role TEXT NOT NULL CHECK(role IN ('admin', 'moderator')),
          created_at TEXT NOT NULL,
          PRIMARY KEY (area_id, user_id)
        );
        CREATE INDEX IF NOT EXISTS idx_board_staff_user ON board_staff(user_id);

        CREATE TABLE IF NOT EXISTS board_mail (
          id TEXT PRIMARY KEY,
          area_id TEXT NOT NULL DEFAULT 'citywide',
          category TEXT NOT NULL DEFAULT 'general',
          subject TEXT NOT NULL,
          body TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'open'
            CHECK(status IN ('open', 'in_progress', 'resolved', 'hidden')),
          author_name TEXT NOT NULL,
          author_email TEXT NOT NULL DEFAULT '',
          author_user_id TEXT,
          author_publisher_id INTEGER,
          source_adda_thread_id TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_board_mail_status ON board_mail(status, updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_board_mail_author ON board_mail(author_user_id);

        CREATE TABLE IF NOT EXISTS board_mail_replies (
          id TEXT PRIMARY KEY,
          mail_id TEXT NOT NULL,
          author_name TEXT NOT NULL,
          author_role TEXT NOT NULL DEFAULT 'citizen'
            CHECK(author_role IN ('citizen', 'staff', 'operator')),
          author_user_id TEXT,
          body TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'active'
            CHECK(status IN ('active', 'hidden', 'deleted')),
          created_at TEXT NOT NULL,
          FOREIGN KEY(mail_id) REFERENCES board_mail(id)
        );
        CREATE INDEX IF NOT EXISTS idx_board_mail_replies
          ON board_mail_replies(mail_id, created_at ASC);
        """
    )
    cols = {row[1] for row in conn.execute("PRAGMA table_info(adda_threads)").fetchall()}
    if cols:
        if "enabled" not in cols:
            conn.execute(
                "ALTER TABLE adda_threads ADD COLUMN enabled INTEGER NOT NULL DEFAULT 1"
            )
        if "hidden" not in cols:
            conn.execute(
                "ALTER TABLE adda_threads ADD COLUMN hidden INTEGER NOT NULL DEFAULT 0"
            )
    conn.commit()


def staff_role(conn: sqlite3.Connection, user_id: str | None, area_id: str | None) -> str | None:
    if not user_id:
        return None
    # Citywide staff apply everywhere.
    row = conn.execute(
        "SELECT role FROM board_staff WHERE user_id = ? AND area_id = ?",
        (user_id, CITYWIDE),
    ).fetchone()
    if row:
        return row["role"]
    if area_id and area_id != CITYWIDE:
        row = conn.execute(
            "SELECT role FROM board_staff WHERE user_id = ? AND area_id = ?",
            (user_id, area_id),
        ).fetchone()
        if row:
            return row["role"]
    return None


def is_hub_operator() -> bool:
    return bool(session.get("hub_operator") or session.get("logged_in"))


def can_moderate_area(
    conn: sqlite3.Connection,
    user_id: str | None,
    area_id: str | None,
    *,
    operator: bool | None = None,
) -> bool:
    if operator if operator is not None else is_hub_operator():
        return True
    role = staff_role(conn, user_id, area_id)
    return role in ("admin", "moderator")


def can_admin_area(
    conn: sqlite3.Connection,
    user_id: str | None,
    area_id: str | None,
    *,
    operator: bool | None = None,
) -> bool:
    if operator if operator is not None else is_hub_operator():
        return True
    return staff_role(conn, user_id, area_id) == "admin"


def thread_visible_to_public(thread: sqlite3.Row | dict) -> bool:
    enabled = thread["enabled"] if "enabled" in thread.keys() else 1
    hidden = thread["hidden"] if "hidden" in thread.keys() else 0
    archived = thread["archived_at"] if "archived_at" in thread.keys() else None
    return bool(int(enabled or 0)) and not bool(int(hidden or 0)) and not archived


def register(app, *, check_login, site_root: pathlib.Path):
    hub_db = pathlib.Path(site_root) / "data" / "hub.db"
    hub_db.parent.mkdir(parents=True, exist_ok=True)

    def db() -> sqlite3.Connection:
        conn = sqlite3.connect(hub_db)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def require_operator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if not session.get("hub_operator"):
                return jsonify({"ok": False, "error": "Operator sign-in required"}), 401
            return fn(*args, **kwargs)

        return wrapper

    def current_adda_user(conn: sqlite3.Connection) -> sqlite3.Row | None:
        uid = (session.get("adda_user_id") or "").strip()
        if not uid:
            return None
        return conn.execute(
            "SELECT * FROM adda_users WHERE id = ? AND status = 'active'", (uid,)
        ).fetchone()

    def mail_dict(row: sqlite3.Row, *, replies: list | None = None) -> dict:
        out = {
            "id": row["id"],
            "areaId": row["area_id"],
            "category": row["category"],
            "subject": row["subject"],
            "body": row["body"],
            "status": row["status"],
            "authorName": row["author_name"],
            "authorEmail": row["author_email"],
            "authorUserId": row["author_user_id"],
            "sourceAddaThreadId": row["source_adda_thread_id"],
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        }
        if replies is not None:
            out["replies"] = replies
        return out

    def reply_dict(row: sqlite3.Row) -> dict:
        return {
            "id": row["id"],
            "mailId": row["mail_id"],
            "authorName": row["author_name"],
            "authorRole": row["author_role"],
            "authorUserId": row["author_user_id"],
            "body": row["body"],
            "status": row["status"],
            "createdAt": row["created_at"],
        }

    def area_title(conn: sqlite3.Connection, area_id: str) -> str:
        if area_id == CITYWIDE:
            return "Citywide"
        row = conn.execute(
            "SELECT title FROM adda_threads WHERE id = ?", (area_id,)
        ).fetchone()
        return row["title"] if row else area_id

    # —— Public contact ——
    @app.get("/api/board/contact/meta")
    def board_contact_meta():
        conn = db()
        try:
            ensure_schema(conn)
            areas = [{"id": CITYWIDE, "title": "Citywide / general"}]
            for r in conn.execute(
                """
                SELECT id, title FROM adda_threads
                WHERE kind IN ('public', 'bridge')
                  AND archived_at IS NULL
                  AND COALESCE(enabled, 1) = 1
                  AND COALESCE(hidden, 0) = 0
                ORDER BY title COLLATE NOCASE
                """
            ).fetchall():
                areas.append({"id": r["id"], "title": r["title"]})
            user = current_adda_user(conn)
            return jsonify({
                "ok": True,
                "categories": MAIL_CATEGORIES,
                "areas": areas,
                "authenticated": bool(user),
                "displayName": user["display_name"] if user else "",
                "email": user["email"] if user else "",
            })
        finally:
            conn.close()

    @app.post("/api/board/contact")
    def board_contact_submit():
        payload = request.get_json(force=True, silent=True) or {}
        subject = str(payload.get("subject") or "").strip()[:160]
        body = str(payload.get("body") or "").strip()[:6000]
        name = str(payload.get("name") or "").strip()[:80]
        email = str(payload.get("email") or "").strip().lower()[:160]
        category = str(payload.get("category") or "general").strip().lower()[:40]
        area_id = str(payload.get("areaId") or CITYWIDE).strip()[:80] or CITYWIDE
        if category not in {c["id"] for c in MAIL_CATEGORIES}:
            category = "general"
        if not subject or not body:
            return jsonify({"ok": False, "error": "Subject and message are required"}), 400
        if not name:
            return jsonify({"ok": False, "error": "Your name is required"}), 400
        if email and not EMAIL_RE.match(email):
            return jsonify({"ok": False, "error": "Enter a valid email"}), 400

        conn = db()
        try:
            ensure_schema(conn)
            user = current_adda_user(conn)
            if user:
                name = name or user["display_name"]
                email = email or (user["email"] or "")
            if area_id != CITYWIDE:
                area = conn.execute(
                    "SELECT id FROM adda_threads WHERE id = ?", (area_id,)
                ).fetchone()
                if not area:
                    area_id = CITYWIDE
            mid = f"bm_{secrets.token_hex(8)}"
            now = _now()
            pub_id = session.get("publisher_id")
            conn.execute(
                """
                INSERT INTO board_mail(
                  id, area_id, category, subject, body, status,
                  author_name, author_email, author_user_id, author_publisher_id,
                  source_adda_thread_id, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'open', ?, ?, ?, ?, NULL, ?, ?)
                """,
                (
                    mid,
                    area_id,
                    category,
                    subject,
                    body,
                    name,
                    email,
                    user["id"] if user else None,
                    int(pub_id) if pub_id else None,
                    now,
                    now,
                ),
            )
            conn.commit()
            return jsonify({
                "ok": True,
                "id": mid,
                "message": "Message sent to the Contact Board mailbox",
            }), 201
        finally:
            conn.close()

    def create_mail_from_escalate(
        conn: sqlite3.Connection,
        *,
        user: sqlite3.Row,
        thread: sqlite3.Row,
        subject: str,
        body: str,
        note: str,
    ) -> str:
        ensure_schema(conn)
        mid = f"bm_{secrets.token_hex(8)}"
        now = _now()
        full = body
        if note:
            full = f"{note.strip()}\n\n---\n\n{body}"
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
        return mid

    # Expose for adda_live escalate
    app.board_create_mail_from_escalate = create_mail_from_escalate  # type: ignore[attr-defined]

    @app.get("/api/board/mailbox/mine")
    def board_mailbox_mine():
        conn = db()
        try:
            ensure_schema(conn)
            user = current_adda_user(conn)
            if not user:
                return jsonify({"ok": False, "error": "Sign in to view your messages"}), 401
            rows = conn.execute(
                """
                SELECT * FROM board_mail
                WHERE author_user_id = ? AND status != 'hidden'
                ORDER BY updated_at DESC LIMIT 40
                """,
                (user["id"],),
            ).fetchall()
            return jsonify({"ok": True, "items": [mail_dict(r) for r in rows]})
        finally:
            conn.close()

    @app.get("/api/board/mailbox/<mail_id>")
    def board_mailbox_get(mail_id: str):
        conn = db()
        try:
            ensure_schema(conn)
            user = current_adda_user(conn)
            row = conn.execute("SELECT * FROM board_mail WHERE id = ?", (mail_id,)).fetchone()
            if not row:
                return jsonify({"ok": False, "error": "Not found"}), 404
            staff_ok = can_moderate_area(conn, user["id"] if user else None, row["area_id"])
            owner = bool(user and row["author_user_id"] == user["id"])
            if not staff_ok and not owner:
                return jsonify({"ok": False, "error": "Not allowed"}), 403
            if row["status"] == "hidden" and not staff_ok:
                return jsonify({"ok": False, "error": "Not found"}), 404
            replies = [
                reply_dict(r)
                for r in conn.execute(
                    """
                    SELECT * FROM board_mail_replies
                    WHERE mail_id = ? AND status != 'deleted'
                    ORDER BY created_at ASC
                    """,
                    (mail_id,),
                ).fetchall()
                if staff_ok or r["status"] == "active"
            ]
            return jsonify({
                "ok": True,
                "item": mail_dict(row, replies=replies),
                "canManage": staff_ok,
                "areaTitle": area_title(conn, row["area_id"]),
            })
        finally:
            conn.close()

    @app.get("/api/board/mailbox")
    def board_mailbox_list():
        conn = db()
        try:
            ensure_schema(conn)
            user = current_adda_user(conn)
            op = is_hub_operator()
            if not op and not user:
                return jsonify({"ok": False, "error": "Sign in required"}), 401
            status = str(request.args.get("status") or "").strip().lower()
            rows = conn.execute(
                "SELECT * FROM board_mail ORDER BY updated_at DESC LIMIT 120"
            ).fetchall()
            items = []
            for r in rows:
                if not can_moderate_area(conn, user["id"] if user else None, r["area_id"], operator=op):
                    continue
                if status and r["status"] != status:
                    continue
                if not status and r["status"] == "hidden" and not op:
                    continue
                items.append({
                    **mail_dict(r),
                    "areaTitle": area_title(conn, r["area_id"]),
                })
            return jsonify({"ok": True, "items": items, "isOperator": op})
        finally:
            conn.close()

    @app.patch("/api/board/mailbox/<mail_id>")
    def board_mailbox_patch(mail_id: str):
        payload = request.get_json(force=True, silent=True) or {}
        conn = db()
        try:
            ensure_schema(conn)
            user = current_adda_user(conn)
            op = is_hub_operator()
            row = conn.execute("SELECT * FROM board_mail WHERE id = ?", (mail_id,)).fetchone()
            if not row:
                return jsonify({"ok": False, "error": "Not found"}), 404
            if not can_moderate_area(conn, user["id"] if user else None, row["area_id"], operator=op):
                return jsonify({"ok": False, "error": "Not allowed"}), 403
            status = str(payload.get("status") or "").strip().lower()
            if status not in MAIL_STATUSES:
                return jsonify({"ok": False, "error": "Unknown status"}), 400
            # Only admins/operators can fully hide mailbox threads
            if status == "hidden" and not can_admin_area(
                conn, user["id"] if user else None, row["area_id"], operator=op
            ):
                return jsonify({"ok": False, "error": "Only area admins can hide mailbox items"}), 403
            conn.execute(
                "UPDATE board_mail SET status = ?, updated_at = ? WHERE id = ?",
                (status, _now(), mail_id),
            )
            conn.commit()
            return jsonify({"ok": True})
        finally:
            conn.close()

    @app.post("/api/board/mailbox/<mail_id>/reply")
    def board_mailbox_reply(mail_id: str):
        payload = request.get_json(force=True, silent=True) or {}
        body = str(payload.get("body") or "").strip()[:6000]
        if not body:
            return jsonify({"ok": False, "error": "Reply body required"}), 400
        conn = db()
        try:
            ensure_schema(conn)
            user = current_adda_user(conn)
            op = is_hub_operator()
            row = conn.execute("SELECT * FROM board_mail WHERE id = ?", (mail_id,)).fetchone()
            if not row:
                return jsonify({"ok": False, "error": "Not found"}), 404
            staff_ok = can_moderate_area(conn, user["id"] if user else None, row["area_id"], operator=op)
            owner = bool(user and row["author_user_id"] == user["id"])
            if not staff_ok and not owner:
                return jsonify({"ok": False, "error": "Not allowed"}), 403
            if row["status"] in ("resolved", "hidden") and not staff_ok:
                return jsonify({"ok": False, "error": "This thread is closed"}), 400
            rid = f"br_{secrets.token_hex(8)}"
            if op:
                role = "operator"
                name = "Board operator"
            elif staff_ok and user:
                role = "staff"
                name = user["display_name"]
            else:
                role = "citizen"
                name = user["display_name"] if user else row["author_name"]
            now = _now()
            conn.execute(
                """
                INSERT INTO board_mail_replies(
                  id, mail_id, author_name, author_role, author_user_id, body, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'active', ?)
                """,
                (rid, mail_id, name, role, user["id"] if user else None, body, now),
            )
            if staff_ok and row["status"] == "open":
                conn.execute(
                    "UPDATE board_mail SET status = 'in_progress', updated_at = ? WHERE id = ?",
                    (now, mail_id),
                )
            else:
                conn.execute(
                    "UPDATE board_mail SET updated_at = ? WHERE id = ?",
                    (now, mail_id),
                )
            conn.commit()
            return jsonify({"ok": True, "id": rid}), 201
        finally:
            conn.close()

    @app.post("/api/board/mailbox/<mail_id>/replies/<reply_id>/moderate")
    def board_reply_moderate(mail_id: str, reply_id: str):
        payload = request.get_json(force=True, silent=True) or {}
        action = str(payload.get("action") or "").strip().lower()
        conn = db()
        try:
            ensure_schema(conn)
            user = current_adda_user(conn)
            op = is_hub_operator()
            mail = conn.execute("SELECT * FROM board_mail WHERE id = ?", (mail_id,)).fetchone()
            if not mail:
                return jsonify({"ok": False, "error": "Not found"}), 404
            if not can_moderate_area(conn, user["id"] if user else None, mail["area_id"], operator=op):
                return jsonify({"ok": False, "error": "Not allowed"}), 403
            if action == "hide":
                conn.execute(
                    "UPDATE board_mail_replies SET status = 'hidden' WHERE id = ? AND mail_id = ?",
                    (reply_id, mail_id),
                )
            elif action == "unhide":
                conn.execute(
                    "UPDATE board_mail_replies SET status = 'active' WHERE id = ? AND mail_id = ?",
                    (reply_id, mail_id),
                )
            elif action == "delete":
                conn.execute(
                    "UPDATE board_mail_replies SET status = 'deleted' WHERE id = ? AND mail_id = ?",
                    (reply_id, mail_id),
                )
            else:
                return jsonify({"ok": False, "error": "Unknown action"}), 400
            conn.commit()
            return jsonify({"ok": True})
        finally:
            conn.close()

    # —— Staff ——
    @app.get("/api/board/staff")
    @require_operator
    def board_staff_list():
        conn = db()
        try:
            ensure_schema(conn)
            rows = conn.execute(
                """
                SELECT s.*, u.display_name, u.email
                FROM board_staff s
                LEFT JOIN adda_users u ON u.id = s.user_id
                ORDER BY s.area_id, s.role, u.display_name COLLATE NOCASE
                """
            ).fetchall()
            return jsonify({
                "ok": True,
                "staff": [
                    {
                        "areaId": r["area_id"],
                        "areaTitle": area_title(conn, r["area_id"]),
                        "userId": r["user_id"],
                        "displayName": r["display_name"] or r["user_id"],
                        "email": r["email"] or "",
                        "role": r["role"],
                        "createdAt": r["created_at"],
                    }
                    for r in rows
                ],
            })
        finally:
            conn.close()

    @app.post("/api/board/staff")
    @require_operator
    def board_staff_add():
        payload = request.get_json(force=True, silent=True) or {}
        area_id = str(payload.get("areaId") or CITYWIDE).strip()[:80] or CITYWIDE
        role = str(payload.get("role") or "moderator").strip().lower()
        email = str(payload.get("email") or "").strip().lower()
        user_id = str(payload.get("userId") or "").strip()
        if role not in STAFF_ROLES:
            return jsonify({"ok": False, "error": "Role must be admin or moderator"}), 400
        conn = db()
        try:
            ensure_schema(conn)
            if area_id != CITYWIDE:
                if not conn.execute(
                    "SELECT 1 FROM adda_threads WHERE id = ?", (area_id,)
                ).fetchone():
                    return jsonify({"ok": False, "error": "Unknown channel/area"}), 400
            user = None
            if user_id:
                user = conn.execute(
                    "SELECT * FROM adda_users WHERE id = ?", (user_id,)
                ).fetchone()
            elif email:
                user = conn.execute(
                    "SELECT * FROM adda_users WHERE email = ?", (email,)
                ).fetchone()
            if not user:
                return jsonify({
                    "ok": False,
                    "error": "Adda user not found — they must register on Mandi Adda first",
                }), 404
            conn.execute(
                """
                INSERT INTO board_staff(area_id, user_id, role, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(area_id, user_id) DO UPDATE SET role = excluded.role
                """,
                (area_id, user["id"], role, _now()),
            )
            conn.commit()
            return jsonify({"ok": True}), 201
        finally:
            conn.close()

    @app.delete("/api/board/staff")
    @require_operator
    def board_staff_remove():
        payload = request.get_json(force=True, silent=True) or {}
        area_id = str(payload.get("areaId") or "").strip()
        user_id = str(payload.get("userId") or "").strip()
        if not area_id or not user_id:
            return jsonify({"ok": False, "error": "areaId and userId required"}), 400
        conn = db()
        try:
            ensure_schema(conn)
            conn.execute(
                "DELETE FROM board_staff WHERE area_id = ? AND user_id = ?",
                (area_id, user_id),
            )
            conn.commit()
            return jsonify({"ok": True})
        finally:
            conn.close()

    # —— Channel visibility ——
    @app.get("/api/board/channels")
    def board_channels_list():
        conn = db()
        try:
            ensure_schema(conn)
            user = current_adda_user(conn)
            op = is_hub_operator()
            if not op and not (user and staff_role(conn, user["id"], CITYWIDE)):
                # Area admins can still list channels they admin
                if not user:
                    return jsonify({"ok": False, "error": "Sign in required"}), 401
            rows = conn.execute(
                """
                SELECT * FROM adda_threads
                WHERE kind IN ('public', 'bridge')
                ORDER BY title COLLATE NOCASE
                """
            ).fetchall()
            out = []
            for r in rows:
                admin_ok = can_admin_area(conn, user["id"] if user else None, r["id"], operator=op)
                mod_ok = can_moderate_area(conn, user["id"] if user else None, r["id"], operator=op)
                if not admin_ok and not mod_ok and not op:
                    continue
                out.append({
                    "id": r["id"],
                    "title": r["title"],
                    "kind": r["kind"],
                    "subtitle": r["subtitle"] or "",
                    "enabled": bool(int(r["enabled"] if "enabled" in r.keys() else 1)),
                    "hidden": bool(int(r["hidden"] if "hidden" in r.keys() else 0)),
                    "archived": bool(r["archived_at"]),
                    "canAdmin": admin_ok,
                    "canModerate": mod_ok,
                })
            return jsonify({"ok": True, "channels": out, "isOperator": op})
        finally:
            conn.close()

    @app.patch("/api/board/channels/<thread_id>")
    def board_channel_patch(thread_id: str):
        payload = request.get_json(force=True, silent=True) or {}
        conn = db()
        try:
            ensure_schema(conn)
            user = current_adda_user(conn)
            op = is_hub_operator()
            thread = conn.execute(
                "SELECT * FROM adda_threads WHERE id = ?", (thread_id,)
            ).fetchone()
            if not thread or thread["kind"] not in ("public", "bridge"):
                return jsonify({"ok": False, "error": "Channel not found"}), 404
            if not can_admin_area(conn, user["id"] if user else None, thread_id, operator=op):
                return jsonify({"ok": False, "error": "Only area admins or operators can change visibility"}), 403
            sets = []
            vals = []
            if "enabled" in payload:
                sets.append("enabled = ?")
                vals.append(1 if payload.get("enabled") else 0)
            if "hidden" in payload:
                sets.append("hidden = ?")
                vals.append(1 if payload.get("hidden") else 0)
            if "archive" in payload and isinstance(payload.get("archive"), bool):
                if payload["archive"]:
                    sets.append("archived_at = ?")
                    vals.append(_now())
                else:
                    sets.append("archived_at = NULL")
            if not sets:
                return jsonify({"ok": False, "error": "Nothing to update"}), 400
            sets.append("updated_at = ?")
            vals.append(_now())
            vals.append(thread_id)
            conn.execute(
                f"UPDATE adda_threads SET {', '.join(sets)} WHERE id = ?",
                vals,
            )
            conn.commit()
            return jsonify({"ok": True})
        finally:
            conn.close()

    @app.get("/api/board/me")
    def board_me():
        conn = db()
        try:
            ensure_schema(conn)
            user = current_adda_user(conn)
            op = is_hub_operator()
            roles = []
            if user:
                for r in conn.execute(
                    "SELECT * FROM board_staff WHERE user_id = ?", (user["id"],)
                ).fetchall():
                    roles.append({
                        "areaId": r["area_id"],
                        "areaTitle": area_title(conn, r["area_id"]),
                        "role": r["role"],
                    })
            return jsonify({
                "ok": True,
                "isOperator": op,
                "authenticated": bool(user),
                "user": {
                    "id": user["id"],
                    "displayName": user["display_name"],
                    "email": user["email"],
                } if user else None,
                "staffRoles": roles,
                "canAccessMailbox": op or any(True for _ in roles),
            })
        finally:
            conn.close()
