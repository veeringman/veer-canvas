"""City of Mandi hub — operators, publishers, and public feed."""

from __future__ import annotations

import hashlib
import json
import pathlib
import re
import secrets
import sqlite3
from datetime import datetime, timezone
from functools import wraps

from flask import g, jsonify, request, session

SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
RESERVED_SLUGS = {
    "www", "mail", "smtp", "admin", "cms", "api", "static", "site", "b",
    "join", "publish", "login", "logout",
}
DEFAULT_KINDS = [
    {"id": "news", "title": "News", "lede": "A public update for the city board."},
    {"id": "ad", "title": "Ad / classified", "lede": "Buy, sell, rent, or announce."},
    {"id": "service", "title": "Service", "lede": "Trade, repair, transport, household help."},
    {"id": "business", "title": "Business", "lede": "Directory listing or hosted page."},
    {"id": "place", "title": "Place", "lede": "Somewhere in or near Mandi."},
    {"id": "event", "title": "Event", "lede": "A gathering, fair, or date."},
]
PBKDF2_ROUNDS = 120_000
MAX_PENDING = 8
MAX_POSTS = 40
SYNDICATE_NAMES = {
    "hbcsanyard": "Housing Colony Sanyard",
}
SYNDICATE_ORIGINS = {
    "hbcsanyard": "https://housingcolonysanyard.in",
}


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


def register(app, *, check_login, site_root: pathlib.Path):
    hub_path = site_root / "hub.json"
    biz_path = site_root / "businesses.json"
    data_dir = site_root / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    db_path = data_dir / "hub.db"

    def db():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def init_db():
        conn = db()
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS publishers (
              id INTEGER PRIMARY KEY,
              name TEXT NOT NULL,
              email TEXT NOT NULL UNIQUE,
              password_hash TEXT NOT NULL,
              status TEXT NOT NULL DEFAULT 'active',
              created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS posts (
              id INTEGER PRIMARY KEY,
              publisher_id INTEGER NOT NULL REFERENCES publishers(id),
              kind TEXT NOT NULL,
              title TEXT NOT NULL,
              summary TEXT NOT NULL DEFAULT '',
              body TEXT NOT NULL DEFAULT '',
              category TEXT NOT NULL DEFAULT '',
              url TEXT NOT NULL DEFAULT '',
              phone TEXT NOT NULL DEFAULT '',
              location TEXT NOT NULL DEFAULT '',
              slug TEXT NOT NULL DEFAULT '',
              plan TEXT NOT NULL DEFAULT 'listed',
              status TEXT NOT NULL DEFAULT 'pending',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_posts_status_kind ON posts(status, kind);
            CREATE INDEX IF NOT EXISTS idx_posts_publisher ON posts(publisher_id);
            """
        )
        for stmt in (
            "ALTER TABLE posts ADD COLUMN source_site TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE posts ADD COLUMN source_id TEXT NOT NULL DEFAULT ''",
        ):
            try:
                conn.execute(stmt)
            except sqlite3.OperationalError:
                pass
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_posts_source "
            "ON posts(source_site, source_id) WHERE source_site != '' AND source_id != ''"
        )
        conn.commit()
        conn.close()

    init_db()

    def _ensure_syndicate_env():
        path = data_dir / "syndicate.env"
        existing = ""
        if path.is_file():
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                text = ""
            for raw in text.splitlines():
                line = raw.strip()
                if line.startswith("SYNDICATE_TOKEN_HBCSANYARD="):
                    existing = line.split("=", 1)[1].strip().strip("'").strip('"')
                    break
            if existing:
                return
        token = secrets.token_hex(24)
        line = f"SYNDICATE_TOKEN_HBCSANYARD={token}\n"
        if path.is_file() and not existing:
            with path.open("a", encoding="utf-8") as handle:
                handle.write("\n" + line)
        else:
            path.write_text(
                "# Neighbourhood tokens. On the source site, set the same value as CITY_HUB_TOKEN.\n"
                + line,
                encoding="utf-8",
            )
        try:
            path.chmod(0o600)
        except OSError:
            pass

    _ensure_syndicate_env()

    def _read(path: pathlib.Path, fallback):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return fallback
        return data if isinstance(data, dict) else fallback

    def _write(path: pathlib.Path, payload: dict):
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    def _kinds():
        hub = _read(hub_path, {})
        extra = hub.get("publishKinds") if isinstance(hub.get("publishKinds"), list) else []
        seen = {row["id"] for row in DEFAULT_KINDS}
        out = list(DEFAULT_KINDS)
        for item in extra:
            if not isinstance(item, dict):
                continue
            kid = re.sub(r"[^a-z0-9-]+", "-", str(item.get("id") or "").strip().lower()).strip("-")
            title = str(item.get("title") or kid).strip()[:80]
            if not kid or kid in seen:
                continue
            seen.add(kid)
            out.append({"id": kid, "title": title, "lede": str(item.get("lede") or "").strip()[:240]})
        return out

    def _kind_ids():
        return {row["id"] for row in _kinds()}

    def _publisher(conn, pub_id: int):
        return conn.execute("SELECT * FROM publishers WHERE id = ?", (pub_id,)).fetchone()

    def _pub_dict(row) -> dict:
        return {
            "id": row["id"],
            "name": row["name"],
            "email": row["email"],
            "status": row["status"],
            "createdAt": row["created_at"],
        }

    def _post_dict(row, *, include_email=False) -> dict:
        keys = row.keys()
        item = {
            "id": row["id"],
            "publisherId": row["publisher_id"],
            "kind": row["kind"],
            "title": row["title"],
            "summary": row["summary"],
            "body": row["body"],
            "category": row["category"],
            "url": row["url"],
            "phone": row["phone"],
            "location": row["location"],
            "slug": row["slug"],
            "plan": row["plan"],
            "status": row["status"],
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
            "publisherName": row["publisher_name"] if "publisher_name" in keys else "",
            "sourceSite": row["source_site"] if "source_site" in keys else "",
            "sourceId": row["source_id"] if "source_id" in keys else "",
        }
        if include_email and "publisher_email" in keys:
            item["publisherEmail"] = row["publisher_email"]
        return item

    def _clean_post(body: dict) -> dict:
        kinds = _kind_ids()
        kind = str(body.get("kind") or "").strip().lower()
        if kind not in kinds:
            custom = re.sub(r"[^a-z0-9-]+", "-", kind).strip("-")
            if not custom or len(custom) > 32:
                raise ValueError("Choose a listing type (news, ad, service, business, …)")
            kind = custom
        title = str(body.get("title") or "").strip()
        if len(title) < 3:
            raise ValueError("Title is too short")
        plan = str(body.get("plan") or "listed").strip().lower()
        if plan not in {"listed", "featured", "hosted"}:
            plan = "listed"
        slug = str(body.get("slug") or "").strip().lower()
        if slug and (not SLUG_RE.match(slug) or slug in RESERVED_SLUGS):
            raise ValueError("Slug must be lowercase letters, numbers, and hyphens")
        if kind == "business" and plan == "hosted" and not slug:
            raise ValueError("A hosted business page needs a slug (e.g. veerlabs)")
        return {
            "kind": kind,
            "title": title[:120],
            "summary": str(body.get("summary") or "").strip()[:600],
            "body": str(body.get("body") or "").strip()[:4000],
            "category": str(body.get("category") or "").strip()[:40],
            "url": str(body.get("url") or "").strip()[:200],
            "phone": str(body.get("phone") or "").strip()[:24],
            "location": str(body.get("location") or "").strip()[:80],
            "slug": slug[:48],
            "plan": plan,
        }

    def _upsert_hosted_business(post: dict):
        if post["kind"] != "business" or post["plan"] != "hosted" or not post["slug"]:
            return
        payload = _read(biz_path, {"businesses": []})
        rows = payload.get("businesses") if isinstance(payload.get("businesses"), list) else []
        entry = {
            "slug": post["slug"],
            "name": post["title"],
            "tagline": post["summary"][:120],
            "summary": post["summary"] or post["body"],
            "category": post["category"] or "Business",
            "website": post["url"],
            "location": post["location"],
            "plan": "hosted",
            "status": "published",
        }
        replaced = False
        out = []
        for row in rows:
            if isinstance(row, dict) and str(row.get("slug") or "") == post["slug"]:
                out.append({**row, **entry})
                replaced = True
            elif isinstance(row, dict):
                out.append(row)
        if not replaced:
            out.append(entry)
        _write(biz_path, {"businesses": out})

    def require_operator(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            if not session.get("hub_operator"):
                return jsonify({"ok": False, "error": "Operator sign-in required"}), 401
            return fn(*args, **kwargs)
        return wrapped

    def require_publisher(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            pub_id = session.get("publisher_id")
            if not pub_id:
                return jsonify({"ok": False, "error": "Sign in to publish"}), 401
            conn = db()
            try:
                row = _publisher(conn, int(pub_id))
                if not row or row["status"] != "active":
                    session.pop("publisher_id", None)
                    return jsonify({"ok": False, "error": "This publisher account is not active"}), 403
                g.publisher = row
                return fn(*args, **kwargs)
            finally:
                conn.close()
        return wrapped

    @app.post("/api/hub/login")
    def hub_login():
        body = request.get_json(force=True, silent=True) or {}
        username = str(body.get("username") or "").strip()
        password = str(body.get("password") or "")
        if not username or not password or not check_login(username, password):
            return jsonify({"ok": False, "error": "Invalid username or password"}), 401
        session["hub_operator"] = True
        session["hub_username"] = username
        return jsonify({"ok": True, "username": username})

    @app.post("/api/hub/logout")
    def hub_logout():
        session.pop("hub_operator", None)
        session.pop("hub_username", None)
        return jsonify({"ok": True})

    @app.get("/api/hub/session")
    def hub_session():
        if not session.get("hub_operator"):
            return jsonify({"ok": True, "authenticated": False})
        return jsonify({
            "ok": True,
            "authenticated": True,
            "username": session.get("hub_username") or "",
        })

    @app.get("/api/hub/kinds")
    def hub_kinds():
        return jsonify({"ok": True, "kinds": _kinds()})

    @app.get("/api/hub/feed")
    def hub_feed():
        conn = db()
        try:
            rows = conn.execute(
                """
                SELECT posts.*, publishers.name AS publisher_name
                FROM posts JOIN publishers ON publishers.id = posts.publisher_id
                WHERE posts.status = 'published' AND publishers.status = 'active'
                ORDER BY posts.updated_at DESC
                LIMIT 200
                """
            ).fetchall()
        finally:
            conn.close()
        grouped: dict[str, list] = {}
        items = []
        for row in rows:
            item = _post_dict(row)
            items.append(item)
            grouped.setdefault(item["kind"], []).append(item)
        return jsonify({"ok": True, "posts": items, "byKind": grouped, "kinds": _kinds()})

    @app.post("/api/hub/register")
    def hub_register():
        body = request.get_json(force=True, silent=True) or {}
        name = str(body.get("name") or "").strip()
        email = str(body.get("email") or "").strip().lower()
        password = str(body.get("password") or "")
        if len(name) < 2:
            return jsonify({"ok": False, "error": "Enter your name"}), 400
        if not EMAIL_RE.match(email):
            return jsonify({"ok": False, "error": "Enter a valid email"}), 400
        if len(password) < 8:
            return jsonify({"ok": False, "error": "Password must be at least 8 characters"}), 400
        conn = db()
        try:
            exists = conn.execute("SELECT id FROM publishers WHERE email = ?", (email,)).fetchone()
            if exists:
                return jsonify({"ok": False, "error": "That email is already registered — sign in instead"}), 409
            cur = conn.execute(
                "INSERT INTO publishers (name, email, password_hash, status, created_at) VALUES (?, ?, ?, 'active', ?)",
                (name[:80], email, _hash_password(password), _now()),
            )
            conn.commit()
            pub_id = int(cur.lastrowid)
        finally:
            conn.close()
        session["publisher_id"] = pub_id
        session["publisher_name"] = name[:80]
        return jsonify({"ok": True, "publisher": {"id": pub_id, "name": name[:80], "email": email}})

    @app.post("/api/hub/publisher/login")
    def publisher_login():
        body = request.get_json(force=True, silent=True) or {}
        email = str(body.get("email") or "").strip().lower()
        password = str(body.get("password") or "")
        conn = db()
        try:
            row = conn.execute("SELECT * FROM publishers WHERE email = ?", (email,)).fetchone()
        finally:
            conn.close()
        if not row or not _verify_password(password, row["password_hash"]):
            return jsonify({"ok": False, "error": "Invalid email or password"}), 401
        if row["status"] != "active":
            return jsonify({"ok": False, "error": "This account is paused. Write to the portal desk."}), 403
        session["publisher_id"] = row["id"]
        session["publisher_name"] = row["name"]
        return jsonify({"ok": True, "publisher": _pub_dict(row)})

    @app.post("/api/hub/publisher/logout")
    def publisher_logout():
        session.pop("publisher_id", None)
        session.pop("publisher_name", None)
        return jsonify({"ok": True})

    @app.get("/api/hub/publisher/session")
    def publisher_session():
        pub_id = session.get("publisher_id")
        if not pub_id:
            return jsonify({"ok": True, "authenticated": False, "kinds": _kinds()})
        conn = db()
        try:
            row = _publisher(conn, int(pub_id))
        finally:
            conn.close()
        if not row or row["status"] != "active":
            session.pop("publisher_id", None)
            return jsonify({"ok": True, "authenticated": False, "kinds": _kinds()})
        return jsonify({"ok": True, "authenticated": True, "publisher": _pub_dict(row), "kinds": _kinds()})

    @app.get("/api/hub/publisher/posts")
    @require_publisher
    def publisher_posts():
        conn = db()
        try:
            rows = conn.execute(
                """
                SELECT posts.*, publishers.name AS publisher_name
                FROM posts JOIN publishers ON publishers.id = posts.publisher_id
                WHERE posts.publisher_id = ?
                ORDER BY posts.updated_at DESC
                """,
                (g.publisher["id"],),
            ).fetchall()
        finally:
            conn.close()
        return jsonify({"ok": True, "posts": [_post_dict(row) for row in rows], "kinds": _kinds()})

    @app.post("/api/hub/publisher/posts")
    @require_publisher
    def publisher_create_post():
        body = request.get_json(force=True, silent=True) or {}
        try:
            data = _clean_post(body)
        except ValueError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        conn = db()
        try:
            pub_id = g.publisher["id"]
            total = conn.execute("SELECT COUNT(*) FROM posts WHERE publisher_id = ?", (pub_id,)).fetchone()[0]
            pending = conn.execute(
                "SELECT COUNT(*) FROM posts WHERE publisher_id = ? AND status = 'pending'",
                (pub_id,),
            ).fetchone()[0]
            if total >= MAX_POSTS:
                return jsonify({"ok": False, "error": "Listing limit reached for this account"}), 400
            if pending >= MAX_PENDING:
                return jsonify({"ok": False, "error": "Too many listings waiting for review"}), 400
            now = _now()
            cur = conn.execute(
                """
                INSERT INTO posts (
                  publisher_id, kind, title, summary, body, category, url, phone,
                  location, slug, plan, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)
                """,
                (
                    pub_id, data["kind"], data["title"], data["summary"], data["body"],
                    data["category"], data["url"], data["phone"], data["location"],
                    data["slug"], data["plan"], now, now,
                ),
            )
            conn.commit()
            row = conn.execute(
                """
                SELECT posts.*, publishers.name AS publisher_name
                FROM posts JOIN publishers ON publishers.id = posts.publisher_id
                WHERE posts.id = ?
                """,
                (cur.lastrowid,),
            ).fetchone()
        finally:
            conn.close()
        return jsonify({"ok": True, "post": _post_dict(row)})

    @app.delete("/api/hub/publisher/posts/<int:post_id>")
    @require_publisher
    def publisher_delete_post(post_id: int):
        conn = db()
        try:
            row = conn.execute(
                "SELECT * FROM posts WHERE id = ? AND publisher_id = ?",
                (post_id, g.publisher["id"]),
            ).fetchone()
            if not row:
                return jsonify({"ok": False, "error": "Listing not found"}), 404
            if row["status"] == "published":
                return jsonify({"ok": False, "error": "Published listings can only be taken down by the portal desk"}), 400
            conn.execute("DELETE FROM posts WHERE id = ?", (post_id,))
            conn.commit()
        finally:
            conn.close()
        return jsonify({"ok": True})

    def _load_env_map(path: pathlib.Path) -> dict[str, str]:
        out: dict[str, str] = {}
        if not path.is_file():
            return out
        try:
            for raw in path.read_text(encoding="utf-8").splitlines():
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip("'").strip('"')
                if key:
                    out[key] = value
        except OSError:
            return out
        return out

    def _syndicate_tokens() -> dict[str, str]:
        env = _load_env_map(data_dir / "syndicate.env")
        tokens = {}
        for key, value in env.items():
            if not key.startswith("SYNDICATE_TOKEN_") or not value:
                continue
            site_id = key[len("SYNDICATE_TOKEN_"):].strip().lower().replace("_", "")
            if site_id:
                tokens[value] = site_id
        return tokens

    def _source_publisher(conn, site_id: str):
        name = SYNDICATE_NAMES.get(site_id, site_id.replace("-", " ").title())
        email = f"syndicate+{site_id}@cityofmandi.local"
        row = conn.execute("SELECT * FROM publishers WHERE email = ?", (email,)).fetchone()
        if row:
            return row
        cur = conn.execute(
            "INSERT INTO publishers (name, email, password_hash, status, created_at) VALUES (?, ?, ?, 'active', ?)",
            (name[:80], email, "pbkdf2$1$x$unavailable", _now()),
        )
        conn.commit()
        return _publisher(conn, int(cur.lastrowid))

    @app.post("/api/hub/syndicate")
    def hub_syndicate():
        auth = (request.headers.get("Authorization") or "").strip()
        token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
        site_id = str(request.headers.get("X-Hub-Source") or "").strip().lower()
        tokens = _syndicate_tokens()
        if not token or token not in tokens:
            return jsonify({"ok": False, "error": "Unknown neighbourhood token"}), 401
        expected = tokens[token]
        if site_id and site_id != expected:
            return jsonify({"ok": False, "error": "Source does not match token"}), 403
        site_id = expected
        body = request.get_json(force=True, silent=True) or {}
        try:
            data = _clean_post(body)
        except ValueError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        source_id = re.sub(r"[^a-zA-Z0-9._-]+", "-", str(body.get("sourceId") or "").strip())[:80]
        if not source_id:
            return jsonify({"ok": False, "error": "sourceId is required"}), 400
        origin = SYNDICATE_ORIGINS.get(site_id, "").rstrip("/")
        if origin and not data["url"]:
            data["url"] = origin
        if not data["location"]:
            data["location"] = SYNDICATE_NAMES.get(site_id, site_id)
        conn = db()
        try:
            pub = _source_publisher(conn, site_id)
            now = _now()
            existing = conn.execute(
                "SELECT * FROM posts WHERE source_site = ? AND source_id = ?",
                (site_id, source_id),
            ).fetchone()
            if existing:
                next_status = existing["status"] if existing["status"] == "published" else "pending"
                conn.execute(
                    """
                    UPDATE posts SET kind = ?, title = ?, summary = ?, body = ?, category = ?,
                      url = ?, phone = ?, location = ?, slug = ?, plan = ?, status = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        data["kind"], data["title"], data["summary"], data["body"], data["category"],
                        data["url"], data["phone"], data["location"], data["slug"], data["plan"],
                        next_status, now, existing["id"],
                    ),
                )
                post_id = existing["id"]
            else:
                cur = conn.execute(
                    """
                    INSERT INTO posts (
                      publisher_id, kind, title, summary, body, category, url, phone,
                      location, slug, plan, status, created_at, updated_at, source_site, source_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?)
                    """,
                    (
                        pub["id"], data["kind"], data["title"], data["summary"], data["body"],
                        data["category"], data["url"], data["phone"], data["location"],
                        data["slug"], data["plan"], now, now, site_id, source_id,
                    ),
                )
                post_id = int(cur.lastrowid)
            conn.commit()
            row = conn.execute(
                """
                SELECT posts.*, publishers.name AS publisher_name
                FROM posts JOIN publishers ON publishers.id = posts.publisher_id
                WHERE posts.id = ?
                """,
                (post_id,),
            ).fetchone()
        finally:
            conn.close()
        return jsonify({"ok": True, "post": _post_dict(row), "sourceSite": site_id})

    @app.get("/api/hub/state")
    @require_operator
    def hub_state():
        return jsonify({
            "ok": True,
            "hub": _read(hub_path, {"features": {}, "services": []}),
            "businesses": _read(biz_path, {"businesses": []}),
            "kinds": _kinds(),
        })

    @app.put("/api/hub/hub")
    @require_operator
    def hub_save():
        body = request.get_json(force=True, silent=True) or {}
        features = body.get("features") if isinstance(body.get("features"), dict) else {}
        services = body.get("services") if isinstance(body.get("services"), list) else []
        cleaned_services = []
        for item in services:
            if not isinstance(item, dict):
                continue
            sid = re.sub(r"[^a-z0-9-]+", "-", str(item.get("id") or "").strip().lower()).strip("-")
            title = str(item.get("title") or "").strip()
            if not sid or not title:
                continue
            cleaned_services.append({
                "id": sid,
                "title": title[:80],
                "lede": str(item.get("lede") or "").strip()[:240],
                "enabled": bool(item.get("enabled", True)),
            })
        existing = _read(hub_path, {})
        payload = {
            "features": {
                "news": bool(features.get("news", True)),
                "places": bool(features.get("places", True)),
                "services": bool(features.get("services", True)),
                "ads": bool(features.get("ads", True)),
                "neighbourhoods": bool(features.get("neighbourhoods", True)),
                "businesses": bool(features.get("businesses", True)),
            },
            "services": cleaned_services,
            "publishKinds": existing.get("publishKinds") or [],
        }
        _write(hub_path, payload)
        return jsonify({"ok": True, "hub": payload})

    @app.put("/api/hub/businesses")
    @require_operator
    def hub_save_businesses():
        body = request.get_json(force=True, silent=True) or {}
        rows = body.get("businesses") if isinstance(body.get("businesses"), list) else []
        cleaned = []
        seen = set()
        for item in rows:
            if not isinstance(item, dict):
                continue
            slug = str(item.get("slug") or "").strip().lower()
            if not SLUG_RE.match(slug) or slug in RESERVED_SLUGS or slug in seen:
                continue
            plan = str(item.get("plan") or "listed").strip().lower()
            if plan not in {"listed", "featured", "hosted"}:
                plan = "listed"
            status = str(item.get("status") or "draft").strip().lower()
            if status not in {"draft", "published"}:
                status = "draft"
            seen.add(slug)
            cleaned.append({
                "slug": slug,
                "name": str(item.get("name") or slug).strip()[:80],
                "tagline": str(item.get("tagline") or "").strip()[:120],
                "summary": str(item.get("summary") or "").strip()[:600],
                "category": str(item.get("category") or "").strip()[:40],
                "website": str(item.get("website") or "").strip()[:200],
                "location": str(item.get("location") or "").strip()[:80],
                "plan": plan,
                "status": status,
            })
        payload = {"businesses": cleaned}
        _write(biz_path, payload)
        return jsonify({"ok": True, "businesses": payload})

    @app.get("/api/hub/moderation")
    @require_operator
    def hub_moderation():
        conn = db()
        try:
            pending = conn.execute(
                """
                SELECT posts.*, publishers.name AS publisher_name, publishers.email AS publisher_email
                FROM posts JOIN publishers ON publishers.id = posts.publisher_id
                WHERE posts.status = 'pending'
                ORDER BY posts.created_at ASC
                """
            ).fetchall()
            publishers = conn.execute(
                "SELECT id, name, email, status, created_at FROM publishers ORDER BY created_at DESC"
            ).fetchall()
        finally:
            conn.close()
        return jsonify({
            "ok": True,
            "pending": [_post_dict(row, include_email=True) for row in pending],
            "publishers": [_pub_dict(row) for row in publishers],
        })

    @app.post("/api/hub/moderation/<int:post_id>/approve")
    @require_operator
    def hub_approve(post_id: int):
        conn = db()
        try:
            row = conn.execute(
                """
                SELECT posts.*, publishers.name AS publisher_name
                FROM posts JOIN publishers ON publishers.id = posts.publisher_id
                WHERE posts.id = ?
                """,
                (post_id,),
            ).fetchone()
            if not row:
                return jsonify({"ok": False, "error": "Listing not found"}), 404
            conn.execute(
                "UPDATE posts SET status = 'published', updated_at = ? WHERE id = ?",
                (_now(), post_id),
            )
            conn.commit()
            item = _post_dict(row)
            item["status"] = "published"
        finally:
            conn.close()
        _upsert_hosted_business(item)
        return jsonify({"ok": True, "post": item})

    @app.post("/api/hub/moderation/<int:post_id>/reject")
    @require_operator
    def hub_reject(post_id: int):
        conn = db()
        try:
            row = conn.execute("SELECT id FROM posts WHERE id = ?", (post_id,)).fetchone()
            if not row:
                return jsonify({"ok": False, "error": "Listing not found"}), 404
            conn.execute(
                "UPDATE posts SET status = 'rejected', updated_at = ? WHERE id = ?",
                (_now(), post_id),
            )
            conn.commit()
        finally:
            conn.close()
        return jsonify({"ok": True})

    @app.post("/api/hub/publishers/<int:pub_id>/status")
    @require_operator
    def hub_publisher_status(pub_id: int):
        body = request.get_json(force=True, silent=True) or {}
        status = str(body.get("status") or "").strip().lower()
        if status not in {"active", "disabled"}:
            return jsonify({"ok": False, "error": "status must be active or disabled"}), 400
        conn = db()
        try:
            row = _publisher(conn, pub_id)
            if not row:
                return jsonify({"ok": False, "error": "Publisher not found"}), 404
            conn.execute("UPDATE publishers SET status = ? WHERE id = ?", (status, pub_id))
            conn.commit()
        finally:
            conn.close()
        return jsonify({"ok": True})
