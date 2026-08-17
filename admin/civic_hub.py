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

from flask import g, jsonify, request, session, send_file
from io import BytesIO

try:
    from admin.hub_boards import (
        LOCALITIES,
        PROFESSION_BOARDS,
        boards_public_meta,
        ensure_provider_tables,
        get_board,
        list_provider_roles,
        migrate_seri_into_providers,
        nearest_locality,
        normalize_board_id,
        normalize_content_lang,
        normalize_locality,
        normalize_preferred_board,
        optimize_provider_photo,
        post_kinds_for_board,
        provider_photo_url,
        provider_public,
        provider_session_payload,
    )
except ImportError:
    from hub_boards import (  # type: ignore
        LOCALITIES,
        PROFESSION_BOARDS,
        boards_public_meta,
        ensure_provider_tables,
        get_board,
        list_provider_roles,
        migrate_seri_into_providers,
        nearest_locality,
        normalize_board_id,
        normalize_content_lang,
        normalize_locality,
        normalize_preferred_board,
        optimize_provider_photo,
        post_kinds_for_board,
        provider_photo_url,
        provider_public,
        provider_session_payload,
    )

try:
    from admin.hub_commerce import register_commerce, active_header_pack_ads
except ImportError:
    from hub_commerce import register_commerce, active_header_pack_ads  # type: ignore

SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
RESERVED_SLUGS = {
    "www", "mail", "smtp", "admin", "cms", "api", "static", "site", "b",
    "join", "publish", "login", "logout", "adda", "contact", "labour", "taxi", "partner",
    "account", "merchant", "delivery", "order",
}
DEFAULT_KINDS = [
    {"id": "news", "title": "News", "lede": "A public update for the city board."},
    {"id": "ad", "title": "Ad / classified", "lede": "Buy, sell, rent, or announce."},
    {"id": "service", "title": "Service", "lede": "Trade, repair, transport, household help."},
    {"id": "business", "title": "Business", "lede": "Directory listing or hosted page."},
    {"id": "place", "title": "Place", "lede": "Somewhere in or near Mandi."},
    {"id": "scitech", "title": "SciTech", "lede": "Science, campus, makers, and tech around Mandi."},
    {"id": "culture", "title": "Culture", "lede": "Festivals, heritage, food, and arts."},
    {"id": "channel", "title": "Channel", "lede": "Announce a topic board or Mandi Adda room."},
    {"id": "event", "title": "Event", "lede": "A gathering, fair, or date."},
    {
        "id": "labour",
        "title": "Labour market",
        "lede": "Morning work needs — construction, garden, clean. Contact private until response.",
    },
    {
        "id": "taxi",
        "title": "Cabs & taxis",
        "lede": "Ride requests and drivers on duty. Contact private until a driver responds.",
    },
    {
        "id": "experts",
        "title": "SME & experts",
        "lede": "Consultants and local experts. Contact private until a response.",
    },
    {
        "id": "vehicle",
        "title": "Vehicle servicing",
        "lede": "Mechanics and service desks. Contact private until a response.",
    },
    {
        "id": "doctor",
        "title": "Doc on call",
        "lede": "Local doctors and clinics. Not an emergency ambulance service.",
    },
    {
        "id": "tours",
        "title": "Tours & travels",
        "lede": "Guides, packages, and travel desks.",
    },
    {
        "id": "tutors",
        "title": "Tutors & mentoring",
        "lede": "Home tutors, coaching, and mentors.",
    },
    {
        "id": "home",
        "title": "Home services",
        "lede": "Plumbers, electricians, carpenters, and household help.",
    },
    {
        "id": "rentals",
        "title": "To rent or sell",
        "lede": "Citizen want-ads for rent/sale — brokers respond from registered desks.",
    },
    {
        "id": "seri",
        "title": "Seri Subah (legacy)",
        "lede": "Legacy alias for labour market needs.",
    },
]
SERI_CATEGORIES = tuple(PROFESSION_BOARDS["labour"]["categories"])
TAXI_CATEGORIES = tuple(PROFESSION_BOARDS["taxi"]["categories"])
BOARD_KINDS = frozenset(set(PROFESSION_BOARDS.keys()) | {"seri", "sme", "doc", "travel", "coaching", "mentor"})
PBKDF2_ROUNDS = 120_000
MAX_PENDING = 8
MAX_POSTS = 40
SYNDICATE_NAMES = {
    "hbcsanyard": "Housing Colony Sanyard",
}
SYNDICATE_ORIGINS = {
    "hbcsanyard": "https://housingcolonysanyard.in",
}

SPONSORED_ANIMATIONS = [
    {"id": "independence", "label": "Independence Day", "hint": "Tricolour wave + festive salute"},
    {"id": "marquee", "label": "Marquee", "hint": "Scrolling headline"},
    {"id": "pulse", "label": "Pulse", "hint": "Soft glowing pulse"},
    {"id": "confetti", "label": "Confetti", "hint": "Celebration burst"},
    {"id": "fade_slide", "label": "Fade & slide", "hint": "Image + text crossfade"},
    {"id": "sparkle", "label": "Sparkle", "hint": "Shimmer title"},
    {"id": "banner", "label": "Image banner", "hint": "Image-forward strip"},
]

DEFAULT_SPONSORED = {
    "ads": [
        {
            "id": "happy-independence-day",
            "title": "Happy Independence Day!",
            "subtitle": "City of Mandi · Jai Hind",
            "animation": "independence",
            "imageUrl": "",
            "linkUrl": "",
            "sponsor": "City of Mandi",
            "active": True,
            "weight": 20,
            "startsAt": "",
            "endsAt": "",
        }
    ]
}

DEFAULT_SPOTLIGHT = {"slots": []}
SPOTLIGHT_KINDS = ("person", "post")
SPOTLIGHT_STATUSES = ("draft", "scheduled", "active", "archived")


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
    sponsored_path = data_dir / "sponsored_ads.json"
    sponsored_dir = data_dir / "sponsored"
    sponsored_dir.mkdir(parents=True, exist_ok=True)
    spotlight_path = data_dir / "spotlight.json"
    spotlight_dir = data_dir / "spotlight"
    spotlight_dir.mkdir(parents=True, exist_ok=True)
    seri_workers_dir = data_dir / "seri_workers"
    seri_workers_dir.mkdir(parents=True, exist_ok=True)
    providers_dir = data_dir / "providers"
    providers_dir.mkdir(parents=True, exist_ok=True)

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
            CREATE TABLE IF NOT EXISTS hub_post_interest (
              id TEXT PRIMARY KEY,
              post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
              from_publisher_id INTEGER REFERENCES publishers(id),
              from_adda_user_id TEXT NOT NULL DEFAULT '',
              name TEXT NOT NULL,
              note TEXT NOT NULL DEFAULT '',
              phone TEXT NOT NULL DEFAULT '',
              status TEXT NOT NULL DEFAULT 'open',
              created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_hub_interest_post
              ON hub_post_interest(post_id, created_at DESC);
            """
        )
        for stmt in (
            "ALTER TABLE posts ADD COLUMN source_site TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE posts ADD COLUMN source_id TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE publishers ADD COLUMN content_lang TEXT NOT NULL DEFAULT 'en'",
            "ALTER TABLE publishers ADD COLUMN preferred_board TEXT NOT NULL DEFAULT 'labour'",
            "ALTER TABLE publishers ADD COLUMN home_locality TEXT NOT NULL DEFAULT 'mandi'",
        ):
            try:
                conn.execute(stmt)
            except sqlite3.OperationalError:
                pass
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_posts_source "
            "ON posts(source_site, source_id) WHERE source_site != '' AND source_id != ''"
        )
        try:
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_hub_interest_pub "
                "ON hub_post_interest(post_id, from_publisher_id) "
                "WHERE from_publisher_id IS NOT NULL AND status = 'open'"
            )
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_hub_interest_adda "
                "ON hub_post_interest(post_id, from_adda_user_id) "
                "WHERE from_adda_user_id != '' AND status = 'open'"
            )
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("ALTER TABLE hub_post_interest ADD COLUMN from_worker_id TEXT NOT NULL DEFAULT ''")
        except sqlite3.OperationalError:
            pass
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS seri_workers (
              id TEXT PRIMARY KEY,
              display_name TEXT NOT NULL,
              phone TEXT NOT NULL UNIQUE,
              email TEXT NOT NULL DEFAULT '',
              password_hash TEXT NOT NULL,
              skills TEXT NOT NULL DEFAULT '',
              location TEXT NOT NULL DEFAULT '',
              address TEXT NOT NULL DEFAULT '',
              official_id TEXT NOT NULL DEFAULT '',
              photo TEXT NOT NULL DEFAULT '',
              status TEXT NOT NULL DEFAULT 'active',
              created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_seri_workers_phone ON seri_workers(phone);
            CREATE TABLE IF NOT EXISTS seri_availability (
              worker_id TEXT NOT NULL REFERENCES seri_workers(id) ON DELETE CASCADE,
              day_ist TEXT NOT NULL,
              available INTEGER NOT NULL DEFAULT 1,
              note TEXT NOT NULL DEFAULT '',
              updated_at TEXT NOT NULL,
              PRIMARY KEY (worker_id, day_ist)
            );
            """
        )
        for stmt in (
            "ALTER TABLE seri_workers ADD COLUMN address TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE seri_workers ADD COLUMN official_id TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE seri_workers ADD COLUMN photo TEXT NOT NULL DEFAULT ''",
        ):
            try:
                conn.execute(stmt)
            except sqlite3.OperationalError:
                pass
        try:
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_hub_interest_worker "
                "ON hub_post_interest(post_id, from_worker_id) "
                "WHERE from_worker_id != '' AND status = 'open'"
            )
        except sqlite3.OperationalError:
            pass
        conn.commit()
        migrate_seri_into_providers(conn, _now())
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

    def _path_stamp(path: pathlib.Path) -> str:
        try:
            st = path.stat()
            return f"{int(st.st_mtime_ns)}:{int(st.st_size)}"
        except OSError:
            return "0"

    def _db_stamp() -> dict:
        """Cheap revision markers for sqlite-backed public surfaces."""
        out = {"feed": "0", "adda": "0", "contact": "0", "seri": "0", "boards": "0"}
        conn = db()
        try:
            row = conn.execute(
                "SELECT COUNT(*) AS n, COALESCE(MAX(updated_at), '') AS u "
                "FROM posts WHERE status = 'published'"
            ).fetchone()
            interest_bit = "0:"
            try:
                irow = conn.execute(
                    "SELECT COUNT(*) AS n, COALESCE(MAX(created_at), '') AS u "
                    "FROM hub_post_interest"
                ).fetchone()
                interest_bit = f"{irow['n']}:{irow['u']}"
            except sqlite3.OperationalError:
                pass
            out["feed"] = f"{row['n']}:{row['u']}:{interest_bit}"
            try:
                day = _ist_day()
                srow = conn.execute(
                    "SELECT COUNT(*) AS n, COALESCE(MAX(updated_at), '') AS u "
                    "FROM hub_provider_availability WHERE day_ist = ? AND available = 1",
                    (day,),
                ).fetchone()
                stamp = f"{day}:{srow['n']}:{srow['u']}"
                out["seri"] = stamp
                out["boards"] = stamp
            except (sqlite3.OperationalError, NameError):
                try:
                    day = _ist_day()
                    srow = conn.execute(
                        "SELECT COUNT(*) AS n, COALESCE(MAX(updated_at), '') AS u "
                        "FROM seri_availability WHERE day_ist = ? AND available = 1",
                        (day,),
                    ).fetchone()
                    out["seri"] = f"{day}:{srow['n']}:{srow['u']}"
                except (sqlite3.OperationalError, NameError):
                    pass
            try:
                t = conn.execute(
                    "SELECT COUNT(*) AS n, COALESCE(MAX(updated_at), '') AS u FROM adda_threads"
                ).fetchone()
                m = conn.execute(
                    "SELECT COALESCE(MAX(id), 0) AS mid FROM adda_messages"
                ).fetchone()
                out["adda"] = f"{t['n']}:{t['u']}:{m['mid']}"
            except sqlite3.OperationalError:
                pass
            try:
                c = conn.execute(
                    "SELECT COUNT(*) AS n, COALESCE(MAX(updated_at), '') AS u FROM board_mail"
                ).fetchone()
                r = conn.execute(
                    "SELECT COALESCE(MAX(id), '') AS rid FROM board_mail_replies"
                ).fetchone()
                out["contact"] = f"{c['n']}:{c['u']}:{r['rid']}"
            except sqlite3.OperationalError:
                pass
        finally:
            conn.close()
        return out

    def _changes_parts() -> dict:
        """Public revision map — clients poll this and refetch only changed parts."""
        _ensure_sponsored()
        _ensure_spotlight()
        sponsored = _read(sponsored_path, DEFAULT_SPONSORED)
        ads = _clean_sponsored_ads(
            sponsored.get("ads") if isinstance(sponsored.get("ads"), list) else []
        )
        active_ids = ",".join(a["id"] for a in _sponsored_active(ads))
        spot = _read(spotlight_path, DEFAULT_SPOTLIGHT)
        slots = _clean_spotlight_slots(
            spot.get("slots") if isinstance(spot.get("slots"), list) else []
        )
        current = _spotlight_current(slots)
        db_stamps = _db_stamp()
        parts = {
            "sponsored": f"{_path_stamp(sponsored_path)}:{active_ids}",
            "spotlight": f"{_path_stamp(spotlight_path)}:{(current or {}).get('id') or 'none'}",
            "hub": _path_stamp(hub_path),
            "businesses": _path_stamp(biz_path),
            "feed": db_stamps["feed"],
            "adda": db_stamps["adda"],
            "contact": db_stamps["contact"],
            "seri": db_stamps.get("seri") or "0",
            "boards": db_stamps.get("boards") or "0",
        }
        blob = "|".join(f"{k}={parts[k]}" for k in sorted(parts))
        rev = hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]
        return {"rev": rev, "parts": parts}

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
        keys = set(row.keys()) if hasattr(row, "keys") else set()
        return {
            "id": row["id"],
            "name": row["name"],
            "email": row["email"],
            "status": row["status"],
            "createdAt": row["created_at"],
            "contentLang": normalize_content_lang(
                row["content_lang"] if "content_lang" in keys else "en"
            ),
        }

    def _post_dict(row, *, include_email=False, public=False, interest_count=0) -> dict:
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
        if item["kind"] in BOARD_KINDS:
            item["interestCount"] = int(interest_count or 0)
            if public:
                item["phone"] = ""
                item["url"] = ""
            # Normalize legacy seri → labour for public grouping
            if public and item["kind"] == "seri":
                item["kind"] = "labour"
            if "locality" in keys:
                item["locality"] = row["locality"] or "mandi"
        return item

    def _is_board_kind(kind: str) -> bool:
        return str(kind or "").strip().lower() in BOARD_KINDS

    def _normalize_feed_kind(kind: str) -> str:
        k = str(kind or "").strip().lower()
        board = get_board(k)
        if board:
            return board["id"]
        return k

    def _interest_counts(conn, post_ids: list[int]) -> dict[int, int]:
        if not post_ids:
            return {}
        placeholders = ",".join("?" for _ in post_ids)
        rows = conn.execute(
            f"""
            SELECT post_id, COUNT(*) AS n FROM hub_post_interest
            WHERE status = 'open' AND post_id IN ({placeholders})
            GROUP BY post_id
            """,
            post_ids,
        ).fetchall()
        return {int(r["post_id"]): int(r["n"]) for r in rows}

    def _clean_post(body: dict) -> dict:
        kinds = _kind_ids()
        kind = str(body.get("kind") or "").strip().lower()
        board = get_board(kind)
        if board:
            kind = board["id"]
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
        category = str(body.get("category") or "").strip()[:40]
        phone = str(body.get("phone") or "").strip()[:24]
        url = str(body.get("url") or "").strip()[:200]
        locality = normalize_locality(body.get("locality") or body.get("homeLocality"))
        summary = str(body.get("summary") or "").strip()[:600]
        post_body = str(body.get("body") or "").strip()[:4000]
        location = str(body.get("location") or "").strip()[:80]
        if kind in BOARD_KINDS:
            phone = ""
            url = ""
            plan = "listed"
            slug = ""
            if not category:
                category = "Other"
            if kind == "taxi":
                pickup = str(body.get("pickup") or body.get("from") or "").strip()[:80]
                dropoff = str(body.get("dropoff") or body.get("to") or "").strip()[:80]
                when = str(body.get("when") or body.get("rideWhen") or "").strip()[:80]
                if pickup or dropoff or when:
                    meta = {"pickup": pickup, "dropoff": dropoff, "when": when}
                    if not summary:
                        bits = [b for b in (pickup and f"From {pickup}", dropoff and f"to {dropoff}", when and f"· {when}") if b]
                        summary = " ".join(bits)[:600]
                    if not location and pickup:
                        location = pickup
                    if not post_body:
                        post_body = json.dumps(meta, ensure_ascii=False)
                    elif not post_body.strip().startswith("{"):
                        post_body = json.dumps({**meta, "note": post_body}, ensure_ascii=False)
        return {
            "kind": kind,
            "title": title[:120],
            "summary": summary,
            "body": post_body,
            "category": category,
            "url": url,
            "phone": phone,
            "location": location,
            "slug": slug[:48],
            "plan": plan,
            "locality": locality,
        }

    def _resolve_interest_actor(conn) -> dict | None:
        provider_id = str(session.get("hub_provider_id") or session.get("seri_worker_id") or "").strip()
        if provider_id:
            row = conn.execute(
                "SELECT * FROM hub_providers WHERE id = ? AND status = 'active'",
                (provider_id,),
            ).fetchone()
            if not row:
                # Legacy fallback during migration
                try:
                    row = conn.execute(
                        "SELECT * FROM seri_workers WHERE id = ? AND status = 'active'",
                        (provider_id,),
                    ).fetchone()
                except sqlite3.OperationalError:
                    row = None
            if row:
                return {
                    "publisher_id": None,
                    "adda_user_id": "",
                    "worker_id": str(row["id"]),
                    "provider_id": str(row["id"]),
                    "name": str(row["display_name"] or "").strip(),
                    "phone": str(row["phone"] or "").strip(),
                }
        pub_id = session.get("publisher_id")
        if pub_id:
            row = _publisher(conn, int(pub_id))
            if row and row["status"] == "active":
                return {
                    "publisher_id": int(row["id"]),
                    "adda_user_id": "",
                    "worker_id": "",
                    "provider_id": "",
                    "name": str(row["name"] or "").strip(),
                    "phone": "",
                }
        adda_id = str(session.get("adda_user_id") or "").strip()
        if not adda_id:
            return None
        try:
            user = conn.execute(
                "SELECT id, display_name FROM adda_users WHERE id = ? AND status = 'active'",
                (adda_id,),
            ).fetchone()
        except sqlite3.OperationalError:
            return None
        if not user:
            return None
        return {
            "publisher_id": None,
            "adda_user_id": str(user["id"]),
            "worker_id": "",
            "provider_id": "",
            "name": str(user["display_name"] or "").strip(),
            "phone": "",
        }

    def _interest_dict(row) -> dict:
        keys = row.keys()
        return {
            "id": row["id"],
            "postId": row["post_id"],
            "name": row["name"],
            "note": row["note"] or "",
            "phone": row["phone"] or "",
            "status": row["status"],
            "createdAt": row["created_at"],
            "workerId": row["from_worker_id"] if "from_worker_id" in keys else "",
            "providerId": row["from_provider_id"] if "from_provider_id" in keys else (
                row["from_worker_id"] if "from_worker_id" in keys else ""
            ),
            "boardId": row["board_id"] if "board_id" in keys else "",
        }

    def _normalize_phone(raw: str) -> str:
        digits = re.sub(r"\D+", "", str(raw or ""))
        if digits.startswith("91") and len(digits) == 12:
            digits = digits[2:]
        return digits[:15]

    def _ist_day(now: datetime | None = None) -> str:
        from datetime import timedelta

        base = now or datetime.now(timezone.utc)
        return (base + timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d")

    def _provider_row_keys(row) -> set:
        return set(row.keys()) if hasattr(row, "keys") else set()

    def _provider_photo_url(raw: str) -> str:
        return provider_photo_url(raw)

    def _optimize_worker_photo(raw: bytes) -> bytes:
        return optimize_provider_photo(raw)

    def _resolve_photo_path(filename: str) -> pathlib.Path | None:
        safe = re.sub(r"[^a-zA-Z0-9._-]+", "", filename or "")
        if not safe or ".." in safe or not safe.endswith(".webp"):
            return None
        for folder in (providers_dir, seri_workers_dir):
            path = folder / safe
            if path.is_file():
                return path
        return None

    def _seed_provider_photo(provider_id: str, label: str) -> str:
        name = f"{provider_id}.webp"
        for folder in (providers_dir, seri_workers_dir):
            if (folder / name).is_file():
                return f"/api/hub/providers/images/{name}"
        try:
            from PIL import Image, ImageDraw, ImageFont
        except ImportError:
            return ""
        colors = {
            "sw_demo_ramesh": (196, 132, 74),
            "sw_demo_sita": (63, 120, 134),
            "sw_demo_ajay": (90, 110, 70),
            "sw_demo_meena": (140, 90, 100),
            "tx_demo_raj": (70, 100, 130),
            "tx_demo_kiran": (120, 90, 60),
        }
        bg = colors.get(provider_id, (70, 100, 110))
        img = Image.new("RGB", (256, 256), bg)
        draw = ImageDraw.Draw(img)
        initial = (label or "?").strip()[:1].upper() or "?"
        try:
            font = ImageFont.load_default()
        except Exception:  # noqa: BLE001
            font = None
        draw.text((108, 108), initial, fill=(255, 252, 246), font=font)
        buf = BytesIO()
        img.save(buf, format="WEBP", quality=50, method=4)
        providers_dir.mkdir(parents=True, exist_ok=True)
        (providers_dir / name).write_bytes(buf.getvalue())
        return f"/api/hub/providers/images/{name}"

    def _role_skills(conn, provider_id: str, board_id: str) -> str:
        row = conn.execute(
            "SELECT skills FROM hub_provider_roles WHERE provider_id = ? AND board_id = ? AND active = 1",
            (provider_id, board_id),
        ).fetchone()
        return str(row["skills"] or "") if row else ""

    def _provider_available(conn, provider_id: str, board_id: str) -> tuple[bool, str]:
        day = _ist_day()
        row = conn.execute(
            """
            SELECT available, note FROM hub_provider_availability
            WHERE provider_id = ? AND board_id = ? AND day_ist = ?
            """,
            (provider_id, board_id, day),
        ).fetchone()
        if not row:
            return False, ""
        return bool(row["available"]), str(row["note"] or "")

    def _available_by_board(conn, provider_id: str) -> dict:
        day = _ist_day()
        rows = conn.execute(
            """
            SELECT board_id, available, note FROM hub_provider_availability
            WHERE provider_id = ? AND day_ist = ?
            """,
            (provider_id, day),
        ).fetchall()
        out = {}
        for row in rows:
            out[row["board_id"]] = {
                "available": bool(row["available"]),
                "note": row["note"] or "",
            }
        return out

    def _worker_public(row, *, available=False, note="", board_id="labour", include_phone=False) -> dict:
        skills = ""
        keys = _provider_row_keys(row)
        if "skills" in keys and row["skills"] is not None:
            skills = str(row["skills"] or "")
        elif "role_skills" in keys:
            skills = str(row["role_skills"] or "")
        return provider_public(
            row,
            board_id=board_id,
            available=available,
            note=note,
            skills=skills,
            include_phone=include_phone,
        )

    def _provider_session_full(conn, row, *, board_id: str | None = None) -> dict:
        roles = list_provider_roles(conn, row["id"])
        avail = _available_by_board(conn, row["id"])
        payload = provider_session_payload(row, roles, available_by_board=avail)
        # Legacy Seri desk fields
        labour_avail = avail.get("labour") or {}
        payload["worker"] = {
            **payload["provider"],
            "skills": next((r["skills"] for r in roles if r["boardId"] == "labour"), []),
            "availableToday": bool(labour_avail.get("available")),
        }
        payload["seriCategories"] = list(SERI_CATEGORIES)
        payload["taxiCategories"] = list(TAXI_CATEGORIES)
        payload["morningWindow"] = {"startHour": 6, "endHour": 10, "tz": "Asia/Kolkata"}
        if board_id:
            board_avail = avail.get(board_id) or {}
            payload["boardId"] = board_id
            payload["availableToday"] = bool(board_avail.get("available"))
        return payload

    def _set_provider_session(row):
        session["hub_provider_id"] = row["id"]
        session["hub_provider_name"] = row["display_name"]
        # Legacy alias for Seri cutover clients
        session["seri_worker_id"] = row["id"]
        session["seri_worker_name"] = row["display_name"]
        session.pop("publisher_id", None)
        session.pop("publisher_name", None)

    def _clear_provider_session():
        session.pop("hub_provider_id", None)
        session.pop("hub_provider_name", None)
        session.pop("seri_worker_id", None)
        session.pop("seri_worker_name", None)

    def _upsert_provider_role(conn, provider_id: str, board_id: str, skills: str = "", meta: dict | None = None):
        conn.execute(
            """
            INSERT INTO hub_provider_roles (provider_id, board_id, skills, meta_json, active)
            VALUES (?, ?, ?, ?, 1)
            ON CONFLICT(provider_id, board_id) DO UPDATE SET
              skills = CASE WHEN excluded.skills != '' THEN excluded.skills ELSE hub_provider_roles.skills END,
              meta_json = CASE WHEN excluded.meta_json != '{}' THEN excluded.meta_json ELSE hub_provider_roles.meta_json END,
              active = 1
            """,
            (provider_id, board_id, skills or "", json.dumps(meta or {}, ensure_ascii=False)),
        )

    def _ensure_board_samples():
        """Seed demo providers + needs for labour and taxi boards."""
        conn = db()
        try:
            ensure_provider_tables(conn)
            migrate_seri_into_providers(conn, _now())
            pub = conn.execute(
                "SELECT id FROM publishers WHERE email = ?",
                ("seri-samples@cityofmandi.local",),
            ).fetchone()
            if not pub:
                cur = conn.execute(
                    "INSERT INTO publishers (name, email, password_hash, status, created_at) "
                    "VALUES (?, ?, ?, 'active', ?)",
                    (
                        "Board Desk Samples",
                        "seri-samples@cityofmandi.local",
                        _hash_password(secrets.token_hex(12)),
                        _now(),
                    ),
                )
                pub_id = int(cur.lastrowid)
            else:
                pub_id = int(pub["id"])

            sample_labour = [
                ("Need 2 masons for terrace plaster", "Construction", "Near Seri · Indira Market side", "Half-day terrace plaster. Bring tools if you have."),
                ("Garden cleanup — 3 hours", "Garden", "Sanyard colony lane", "Weeding and hedge trim. Start after 8 AM."),
                ("House deep clean before guests", "Clean", "Paddal road", "Kitchen + two rooms. Same-day preferred."),
                ("Unload sand bags from truck", "Load/unload", "Seri stand", "About 1.5 hours. Strong hands needed."),
            ]
            for title, category, location, summary in sample_labour:
                exists = conn.execute(
                    "SELECT id FROM posts WHERE source_site = 'seri-sample' AND title = ?",
                    (title,),
                ).fetchone()
                if exists:
                    conn.execute(
                        "UPDATE posts SET kind = 'labour' WHERE id = ? AND kind = 'seri'",
                        (exists["id"],),
                    )
                    continue
                now = _now()
                conn.execute(
                    """
                    INSERT INTO posts (
                      publisher_id, kind, title, summary, body, category, url, phone,
                      location, slug, plan, status, created_at, updated_at, source_site, source_id, locality
                    ) VALUES (?, 'labour', ?, ?, '', ?, '', '', ?, '', 'listed', 'published', ?, ?, 'seri-sample', ?, 'mandi')
                    """,
                    (pub_id, title, summary, category, location, now, now, f"need-{secrets.token_hex(4)}"),
                )

            sample_taxi = [
                ("Airport drop — Mandi to Kullu", "Airport/rail", "Mandi bus stand", "Pickup Mandi ISBT → Bhuntar. Soft bags only.", "Mandi ISBT", "Bhuntar airport", "Today evening"),
                ("Local hops around town", "Local", "Indira Market", "2–3 short rides this afternoon.", "Indira Market", "Around Mandi", "After 2 PM"),
                ("Outstation to Sundernagar", "Outstation", "Padal", "Family of 3 + luggage. Return same day OK.", "Padal", "Sundernagar", "Tomorrow morning"),
            ]
            for title, category, location, summary, pickup, dropoff, when in sample_taxi:
                exists = conn.execute(
                    "SELECT id FROM posts WHERE source_site = 'taxi-sample' AND title = ?",
                    (title,),
                ).fetchone()
                if exists:
                    continue
                now = _now()
                body = json.dumps({"pickup": pickup, "dropoff": dropoff, "when": when}, ensure_ascii=False)
                conn.execute(
                    """
                    INSERT INTO posts (
                      publisher_id, kind, title, summary, body, category, url, phone,
                      location, slug, plan, status, created_at, updated_at, source_site, source_id, locality
                    ) VALUES (?, 'taxi', ?, ?, ?, ?, '', '', ?, '', 'listed', 'published', ?, ?, 'taxi-sample', ?, 'mandi')
                    """,
                    (pub_id, title, summary, body, category, location, now, now, f"ride-{secrets.token_hex(4)}"),
                )

            day = _ist_day()
            demo_hash = _hash_password("seri1234")
            sample_workers = [
                ("sw_demo_ramesh", "Ramesh Kumar", "9805111001", "Construction,Load/unload", "Seri", "Free till noon", "labour"),
                ("sw_demo_sita", "Sita Devi", "9805111002", "Clean,Garden", "Paddal", "Prefer nearby work", "labour"),
                ("sw_demo_ajay", "Ajay Thakur", "9805111003", "Construction", "Bhiuli", "Mason · plaster", "labour"),
                ("sw_demo_meena", "Meena", "9805111004", "Garden,Clean", "Seri", "Available with tools", "labour"),
                ("tx_demo_raj", "Raj Driver", "9805222001", "Local,Outstation", "Mandi stand", "Innova · on duty till 8 PM", "taxi"),
                ("tx_demo_kiran", "Kiran", "9805222002", "Airport/rail,Local", "Padal", "Sedan · airport runs OK", "taxi"),
            ]
            for wid, name, phone, skills, location, note, board_id in sample_workers:
                photo_url = _seed_provider_photo(wid, name)
                row = conn.execute(
                    "SELECT id, photo FROM hub_providers WHERE id = ? OR phone = ?",
                    (wid, phone),
                ).fetchone()
                if not row:
                    conn.execute(
                        """
                        INSERT INTO hub_providers (
                          id, display_name, phone, email, password_hash, photo, address, official_id,
                          location, home_locality, preferred_board, status, created_at
                        ) VALUES (?, ?, ?, '', ?, ?, '', '', ?, 'mandi', ?, 'active', ?)
                        """,
                        (wid, name, phone, demo_hash, photo_url, location, board_id, _now()),
                    )
                    provider_id = wid
                else:
                    provider_id = str(row["id"])
                    if photo_url and not str(row["photo"] or "").strip():
                        conn.execute(
                            "UPDATE hub_providers SET photo = ? WHERE id = ?",
                            (photo_url, provider_id),
                        )
                _upsert_provider_role(conn, provider_id, board_id, skills)
                conn.execute(
                    """
                    INSERT INTO hub_provider_availability (
                      provider_id, board_id, day_ist, available, note, meta_json, updated_at
                    ) VALUES (?, ?, ?, 1, ?, '{}', ?)
                    ON CONFLICT(provider_id, board_id, day_ist) DO UPDATE SET
                      available = 1,
                      note = excluded.note,
                      updated_at = excluded.updated_at
                    """,
                    (provider_id, board_id, day, note, _now()),
                )
                # Keep legacy seri tables in sync for labour demos
                if board_id == "labour":
                    try:
                        exists_w = conn.execute("SELECT id FROM seri_workers WHERE id = ? OR phone = ?", (provider_id, phone)).fetchone()
                        if not exists_w:
                            conn.execute(
                                """
                                INSERT INTO seri_workers (
                                  id, display_name, phone, email, password_hash, skills, location,
                                  address, official_id, photo, status, created_at
                                ) VALUES (?, ?, ?, '', ?, ?, ?, '', '', ?, 'active', ?)
                                """,
                                (provider_id, name, phone, demo_hash, skills, location, photo_url, _now()),
                            )
                        conn.execute(
                            """
                            INSERT INTO seri_availability (worker_id, day_ist, available, note, updated_at)
                            VALUES (?, ?, 1, ?, ?)
                            ON CONFLICT(worker_id, day_ist) DO UPDATE SET
                              available = 1, note = excluded.note, updated_at = excluded.updated_at
                            """,
                            (provider_id, day, note, _now()),
                        )
                    except sqlite3.OperationalError:
                        pass
            conn.commit()
        finally:
            conn.close()

    _ensure_board_samples()

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
            counts = _interest_counts(
                conn,
                [int(r["id"]) for r in rows if _is_board_kind(r["kind"])],
            )
        finally:
            conn.close()
        grouped: dict[str, list] = {}
        items = []
        for row in rows:
            item = _post_dict(
                row,
                public=True,
                interest_count=counts.get(int(row["id"]), 0),
            )
            items.append(item)
            grouped.setdefault(item["kind"], []).append(item)
        meta = boards_public_meta()
        return jsonify({
            "ok": True,
            "posts": items,
            "byKind": grouped,
            "kinds": _kinds(),
            "seriCategories": list(SERI_CATEGORIES),
            "taxiCategories": list(TAXI_CATEGORIES),
            "boards": meta["boards"],
            "localities": meta["localities"],
        })

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
            content_lang = normalize_content_lang(body.get("contentLang") or body.get("lang"))
            preferred = normalize_preferred_board(body.get("preferredBoard") or "labour")
            home_locality = normalize_locality(body.get("homeLocality") or body.get("locality"))
            try:
                cur = conn.execute(
                    """
                    INSERT INTO publishers (
                      name, email, password_hash, status, created_at, content_lang, preferred_board, home_locality
                    ) VALUES (?, ?, ?, 'active', ?, ?, ?, ?)
                    """,
                    (name[:80], email, _hash_password(password), _now(), content_lang, preferred, home_locality),
                )
            except sqlite3.OperationalError:
                cur = conn.execute(
                    "INSERT INTO publishers (name, email, password_hash, status, created_at) VALUES (?, ?, ?, 'active', ?)",
                    (name[:80], email, _hash_password(password), _now()),
                )
            conn.commit()
            pub_id = int(cur.lastrowid)
            try:
                conn.execute(
                    "UPDATE publishers SET content_lang = ?, preferred_board = ?, home_locality = ? WHERE id = ?",
                    (content_lang, preferred, home_locality, pub_id),
                )
                conn.commit()
            except sqlite3.OperationalError:
                pass
            row = _publisher(conn, pub_id)
        finally:
            conn.close()
        session["publisher_id"] = pub_id
        session["publisher_name"] = name[:80]
        _link_adda_identity(row)
        return jsonify({"ok": True, "publisher": _pub_dict(row)})

    def _link_adda_identity(publisher_row):
        """Provision/link Mandi Adda identity when a publisher signs in."""
        linker = getattr(app, "adda_ensure_user_for_publisher", None)
        if not linker or not publisher_row:
            return
        conn = db()
        try:
            uid = linker(conn, publisher_row)
            session["adda_user_id"] = uid
            session["adda_display_name"] = publisher_row["name"]
        except Exception:
            pass
        finally:
            conn.close()

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
        content_lang = body.get("contentLang") or body.get("lang")
        preferred = body.get("preferredBoard")
        home_locality = body.get("homeLocality") or body.get("locality")
        if content_lang or preferred or home_locality:
            conn = db()
            try:
                updates = []
                vals = []
                if content_lang:
                    updates.append("content_lang = ?")
                    vals.append(normalize_content_lang(content_lang))
                if preferred:
                    updates.append("preferred_board = ?")
                    vals.append(normalize_preferred_board(preferred))
                if home_locality:
                    updates.append("home_locality = ?")
                    vals.append(normalize_locality(home_locality))
                if updates:
                    vals.append(row["id"])
                    try:
                        conn.execute(
                            f"UPDATE publishers SET {', '.join(updates)} WHERE id = ?",
                            tuple(vals),
                        )
                        conn.commit()
                        row = _publisher(conn, row["id"])
                    except sqlite3.OperationalError:
                        pass
            finally:
                conn.close()
        _link_adda_identity(row)
        return jsonify({"ok": True, "publisher": _pub_dict(row)})

    @app.post("/api/hub/publisher/logout")
    def publisher_logout():
        session.pop("publisher_id", None)
        session.pop("publisher_name", None)
        return jsonify({"ok": True})

    @app.get("/api/hub/publisher/session")
    def publisher_session():
        pub_id = session.get("publisher_id")
        base = {
            "ok": True,
            "kinds": _kinds(),
            "seriCategories": list(SERI_CATEGORIES),
            "taxiCategories": list(TAXI_CATEGORIES),
            **boards_public_meta(),
        }
        if not pub_id:
            return jsonify({**base, "authenticated": False})
        conn = db()
        try:
            row = _publisher(conn, int(pub_id))
        finally:
            conn.close()
        if not row or row["status"] != "active":
            session.pop("publisher_id", None)
            return jsonify({**base, "authenticated": False})
        return jsonify({**base, "authenticated": True, "publisher": _pub_dict(row)})


    def require_provider(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            provider_id = str(session.get("hub_provider_id") or session.get("seri_worker_id") or "").strip()
            if not provider_id:
                return jsonify({"ok": False, "error": "Provider sign-in required"}), 401
            conn = db()
            try:
                row = conn.execute(
                    "SELECT * FROM hub_providers WHERE id = ? AND status = 'active'",
                    (provider_id,),
                ).fetchone()
                if not row:
                    _clear_provider_session()
                    return jsonify({"ok": False, "error": "Provider account not active"}), 403
                g.hub_provider = row
                g.seri_worker = row  # legacy alias
                return fn(*args, **kwargs)
            finally:
                conn.close()
        return wrapped

    require_seri_worker = require_provider

    def _register_provider(body: dict, *, default_board: str = "labour"):
        phone = _normalize_phone(body.get("phone") or "")
        name = str(body.get("name") or "").strip()[:80]
        email = str(body.get("email") or "").strip().lower()[:120]
        address = str(body.get("address") or "").strip()[:200]
        official_id = str(body.get("officialId") or body.get("official_id") or "").strip()[:40]
        password = str(body.get("password") or body.get("pin") or "")
        skills = str(body.get("skills") or "").strip()[:120]
        photo = _provider_photo_url(body.get("photo") or body.get("photoUrl") or "")
        try:
            board_id = normalize_board_id(body.get("boardId") or body.get("board") or default_board)
        except ValueError:
            board_id = "labour"
        home_locality = normalize_locality(body.get("homeLocality") or body.get("locality"))
        preferred = normalize_preferred_board(body.get("preferredBoard") or board_id)
        content_lang = normalize_content_lang(body.get("contentLang") or body.get("lang"))
        if len(phone) < 10:
            return jsonify({"ok": False, "error": "Enter a valid mobile number"}), 400
        if email and not EMAIL_RE.match(email):
            return jsonify({"ok": False, "error": "Enter a valid email or leave it blank"}), 400
        if len(password) < 4:
            return jsonify({"ok": False, "error": "Choose a PIN / password of at least 4 characters"}), 400
        if not photo:
            return jsonify({"ok": False, "error": "Photo is required (max 5 MB)"}), 400
        if not name:
            name = f"Provider · {phone[-4:]}"
        location = address[:80] if address else ""
        pid = "hp_" + secrets.token_hex(8)
        conn = db()
        try:
            ensure_provider_tables(conn)
            exists = conn.execute("SELECT id FROM hub_providers WHERE phone = ?", (phone,)).fetchone()
            if exists:
                return jsonify({"ok": False, "error": "This mobile is already registered. Sign in instead."}), 409
            conn.execute(
                """
                INSERT INTO hub_providers (
                  id, display_name, phone, email, password_hash, photo, address, official_id,
                  location, home_locality, preferred_board, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?)
                """,
                (
                    pid, name, phone, email, _hash_password(password), photo, address,
                    official_id, location, home_locality, preferred, _now(),
                ),
            )
            try:
                conn.execute(
                    "UPDATE hub_providers SET content_lang = ? WHERE id = ?",
                    (content_lang, pid),
                )
            except sqlite3.OperationalError:
                pass
            _upsert_provider_role(conn, pid, board_id, skills)
            conn.commit()
            row = conn.execute("SELECT * FROM hub_providers WHERE id = ?", (pid,)).fetchone()
            payload = _provider_session_full(conn, row, board_id=board_id)
        except sqlite3.IntegrityError:
            return jsonify({"ok": False, "error": "This mobile is already registered. Sign in instead."}), 409
        finally:
            conn.close()
        _set_provider_session(row)
        return jsonify(payload)

    def _login_provider(body: dict):
        phone = _normalize_phone(body.get("phone") or "")
        password = str(body.get("password") or body.get("pin") or "")
        if len(phone) < 10 or not password:
            return jsonify({"ok": False, "error": "Enter mobile and PIN / password"}), 400
        conn = db()
        try:
            ensure_provider_tables(conn)
            migrate_seri_into_providers(conn, _now())
            row = conn.execute("SELECT * FROM hub_providers WHERE phone = ?", (phone,)).fetchone()
            if not row or not _verify_password(password, row["password_hash"]):
                return jsonify({"ok": False, "error": "Invalid mobile or PIN / password"}), 401
            if row["status"] != "active":
                return jsonify({"ok": False, "error": "This account is paused"}), 403
            board_id = str(body.get("boardId") or row["preferred_board"] or "labour")
            if board_id == "seri":
                board_id = "labour"
            if body.get("contentLang") or body.get("lang") or body.get("preferredBoard") or body.get("homeLocality"):
                content_lang = normalize_content_lang(body.get("contentLang") or body.get("lang") or "en")
                preferred = normalize_preferred_board(body.get("preferredBoard") or row["preferred_board"] or board_id)
                home_locality = normalize_locality(body.get("homeLocality") or row["home_locality"])
                try:
                    conn.execute(
                        "UPDATE hub_providers SET content_lang = ?, preferred_board = ?, home_locality = ? WHERE id = ?",
                        (content_lang, preferred, home_locality, row["id"]),
                    )
                    conn.commit()
                    row = conn.execute("SELECT * FROM hub_providers WHERE id = ?", (row["id"],)).fetchone()
                except sqlite3.OperationalError:
                    pass
            payload = _provider_session_full(conn, row, board_id=board_id)
        finally:
            conn.close()
        _set_provider_session(row)
        return jsonify(payload)

    def _provider_session_response():
        provider_id = str(session.get("hub_provider_id") or session.get("seri_worker_id") or "").strip()
        base = {
            "ok": True,
            "authenticated": False,
            "seriCategories": list(SERI_CATEGORIES),
            "taxiCategories": list(TAXI_CATEGORIES),
            "morningWindow": {"startHour": 6, "endHour": 10, "tz": "Asia/Kolkata"},
            **boards_public_meta(),
        }
        if not provider_id:
            return jsonify(base)
        conn = db()
        try:
            row = conn.execute(
                "SELECT * FROM hub_providers WHERE id = ? AND status = 'active'",
                (provider_id,),
            ).fetchone()
            if not row:
                _clear_provider_session()
                return jsonify(base)
            return jsonify(_provider_session_full(conn, row))
        finally:
            conn.close()

    def _list_board_providers(board_id: str, locality: str | None = None):
        day = _ist_day()
        conn = db()
        try:
            ensure_provider_tables(conn)
            sql = """
                SELECT p.*, a.note AS avail_note, a.available, r.skills AS role_skills
                FROM hub_providers p
                JOIN hub_provider_availability a ON a.provider_id = p.id AND a.board_id = ?
                LEFT JOIN hub_provider_roles r ON r.provider_id = p.id AND r.board_id = ? AND r.active = 1
                WHERE p.status = 'active' AND a.day_ist = ? AND a.available = 1
            """
            params: list = [board_id, board_id, day]
            if locality:
                sql += " AND p.home_locality = ?"
                params.append(normalize_locality(locality))
            sql += " ORDER BY a.updated_at DESC LIMIT 100"
            rows = conn.execute(sql, params).fetchall()
        finally:
            conn.close()
        providers = [
            _worker_public(
                r,
                available=True,
                note=str(r["avail_note"] or ""),
                board_id=board_id,
                include_phone=False,
            )
            for r in rows
        ]
        return {
            "ok": True,
            "day": day,
            "boardId": board_id,
            "locality": normalize_locality(locality) if locality else "",
            "providers": providers,
            "workers": providers,  # legacy Seri key
        }

    def _set_availability(provider, body: dict, board_id: str):
        available = body.get("available", True)
        if isinstance(available, str):
            available = available.strip().lower() in ("1", "true", "yes", "on")
        available = bool(available)
        note = str(body.get("note") or "").strip()[:200]
        photo = _provider_photo_url(provider["photo"] if "photo" in _provider_row_keys(provider) else "")
        if available and not photo:
            return jsonify({
                "ok": False,
                "error": "Upload a photo (max 5 MB) before marking available",
            }), 400
        day = _ist_day()
        conn = db()
        try:
            _upsert_provider_role(conn, provider["id"], board_id)
            conn.execute(
                """
                INSERT INTO hub_provider_availability (
                  provider_id, board_id, day_ist, available, note, meta_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, '{}', ?)
                ON CONFLICT(provider_id, board_id, day_ist) DO UPDATE SET
                  available = excluded.available,
                  note = excluded.note,
                  updated_at = excluded.updated_at
                """,
                (provider["id"], board_id, day, 1 if available else 0, note, _now()),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM hub_providers WHERE id = ?", (provider["id"],)).fetchone()
            payload = _provider_session_full(conn, row, board_id=board_id)
        finally:
            conn.close()
        return jsonify(payload)

    @app.get("/api/hub/boards")
    def hub_boards_meta():
        return jsonify({"ok": True, **boards_public_meta()})

    @app.get("/api/hub/localities/nearest")
    def hub_localities_nearest():
        try:
            lat = float(request.args.get("lat"))
            lng = float(request.args.get("lng"))
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "lat and lng required"}), 400
        hit = nearest_locality(lat, lng)
        if not hit:
            return jsonify({"ok": False, "error": "No localities configured"}), 404
        return jsonify({"ok": True, "locality": hit, "localities": list(LOCALITIES)})

    @app.post("/api/hub/providers/register")
    def providers_register():
        body = request.get_json(force=True, silent=True) or {}
        return _register_provider(body, default_board=str(body.get("boardId") or "labour"))

    @app.post("/api/hub/providers/login")
    def providers_login():
        body = request.get_json(force=True, silent=True) or {}
        return _login_provider(body)

    @app.post("/api/hub/providers/logout")
    def providers_logout():
        _clear_provider_session()
        return jsonify({"ok": True})

    @app.get("/api/hub/providers/session")
    def providers_session():
        return _provider_session_response()

    @app.patch("/api/hub/providers/me")
    @require_provider
    def providers_me_patch():
        body = request.get_json(force=True, silent=True) or {}
        provider = g.hub_provider
        name = str(body.get("name") or provider["display_name"]).strip()[:80] or provider["display_name"]
        email = str(body.get("email") if "email" in body else provider["email"] or "").strip().lower()[:120]
        address = str(body.get("address") if "address" in body else provider["address"] or "").strip()[:200]
        home_locality = normalize_locality(
            body.get("homeLocality") if "homeLocality" in body else provider["home_locality"]
        )
        preferred = normalize_preferred_board(
            body.get("preferredBoard") or provider["preferred_board"] or "labour"
        )
        keys = set(provider.keys()) if hasattr(provider, "keys") else set()
        content_lang = normalize_content_lang(
            body.get("contentLang") if "contentLang" in body or "lang" in body
            else (provider["content_lang"] if "content_lang" in keys else "en")
        )
        roles = body.get("roles")
        conn = db()
        try:
            if email and not EMAIL_RE.match(email):
                return jsonify({"ok": False, "error": "Enter a valid email or leave it blank"}), 400
            conn.execute(
                """
                UPDATE hub_providers SET
                  display_name = ?, email = ?, address = ?, location = ?,
                  home_locality = ?, preferred_board = ?
                WHERE id = ?
                """,
                (
                    name, email, address, address[:80] if address else provider["location"],
                    home_locality, preferred, provider["id"],
                ),
            )
            try:
                conn.execute(
                    "UPDATE hub_providers SET content_lang = ? WHERE id = ?",
                    (content_lang, provider["id"]),
                )
            except sqlite3.OperationalError:
                pass
            if isinstance(roles, list):
                for role in roles:
                    if not isinstance(role, dict):
                        continue
                    try:
                        bid = normalize_board_id(role.get("boardId") or role.get("board"))
                    except ValueError:
                        continue
                    skills = role.get("skills")
                    if isinstance(skills, list):
                        skills_s = ",".join(str(s).strip() for s in skills if str(s).strip())[:120]
                    else:
                        skills_s = str(skills or "").strip()[:120]
                    meta = role.get("meta") if isinstance(role.get("meta"), dict) else {}
                    active = role.get("active", True)
                    if active is False:
                        conn.execute(
                            "UPDATE hub_provider_roles SET active = 0 WHERE provider_id = ? AND board_id = ?",
                            (provider["id"], bid),
                        )
                    else:
                        _upsert_provider_role(conn, provider["id"], bid, skills_s, meta)
            conn.commit()
            row = conn.execute("SELECT * FROM hub_providers WHERE id = ?", (provider["id"],)).fetchone()
            payload = _provider_session_full(conn, row)
        finally:
            conn.close()
        _set_provider_session(row)
        return jsonify(payload)

    @app.post("/api/hub/providers/photo")
    def providers_photo_upload():
        upload = request.files.get("file") or request.files.get("photo") or request.files.get("image")
        if not upload or not upload.filename:
            return jsonify({"ok": False, "error": "Choose a photo"}), 400
        raw = upload.read(5 * 1024 * 1024 + 1)
        if len(raw) > 5 * 1024 * 1024:
            return jsonify({"ok": False, "error": "Photo must be 5 MB or smaller"}), 400
        try:
            data = _optimize_worker_photo(raw)
        except ValueError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        name = f"hp_{secrets.token_hex(8)}.webp"
        providers_dir.mkdir(parents=True, exist_ok=True)
        (providers_dir / name).write_bytes(data)
        url = f"/api/hub/providers/images/{name}"
        provider_id = str(session.get("hub_provider_id") or session.get("seri_worker_id") or "").strip()
        if provider_id:
            conn = db()
            try:
                conn.execute(
                    "UPDATE hub_providers SET photo = ? WHERE id = ? AND status = 'active'",
                    (url, provider_id),
                )
                conn.commit()
            finally:
                conn.close()
        return jsonify({
            "ok": True,
            "photo": url,
            "photoUrl": url,
            "bytes": len(data),
            "maxUploadMb": 5,
        })

    @app.get("/api/hub/providers/images/<filename>")
    def providers_image(filename: str):
        path = _resolve_photo_path(filename)
        if not path:
            return jsonify({"ok": False, "error": "Not found"}), 404
        return send_file(path, mimetype="image/webp", conditional=True)

    @app.get("/api/hub/boards/<board_id>/providers")
    def board_providers_public(board_id: str):
        try:
            bid = normalize_board_id(board_id)
        except ValueError:
            return jsonify({"ok": False, "error": "Unknown board"}), 404
        locality = request.args.get("locality") or ""
        return jsonify(_list_board_providers(bid, locality or None))

    @app.post("/api/hub/boards/<board_id>/availability")
    @require_provider
    def board_availability(board_id: str):
        try:
            bid = normalize_board_id(board_id)
        except ValueError:
            return jsonify({"ok": False, "error": "Unknown board"}), 404
        body = request.get_json(force=True, silent=True) or {}
        return _set_availability(g.hub_provider, body, bid)

    # —— Legacy Seri aliases (labour board) ——
    @app.post("/api/hub/seri/workers/register")
    def seri_worker_register():
        body = request.get_json(force=True, silent=True) or {}
        body = {**body, "boardId": "labour", "preferredBoard": body.get("preferredBoard") or "labour"}
        return _register_provider(body, default_board="labour")

    @app.post("/api/hub/seri/workers/photo")
    def seri_worker_photo_upload():
        return providers_photo_upload()

    @app.get("/api/hub/seri/workers/images/<filename>")
    def seri_worker_image(filename: str):
        return providers_image(filename)

    @app.post("/api/hub/seri/workers/login")
    def seri_worker_login():
        body = request.get_json(force=True, silent=True) or {}
        body = {**body, "boardId": "labour"}
        return _login_provider(body)

    @app.post("/api/hub/seri/workers/logout")
    def seri_worker_logout():
        return providers_logout()

    @app.get("/api/hub/seri/workers/session")
    def seri_worker_session():
        return _provider_session_response()

    @app.get("/api/hub/seri/workers")
    def seri_workers_public():
        return jsonify(_list_board_providers("labour", request.args.get("locality") or None))

    @app.post("/api/hub/seri/workers/availability")
    @require_provider
    def seri_worker_availability():
        body = request.get_json(force=True, silent=True) or {}
        return _set_availability(g.hub_provider, body, "labour")

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
            counts = _interest_counts(
                conn,
                [int(r["id"]) for r in rows if _is_board_kind(r["kind"])],
            )
        finally:
            conn.close()
        posts = [
            _post_dict(row, interest_count=counts.get(int(row["id"]), 0))
            for row in rows
        ]
        return jsonify({
            "ok": True,
            "posts": posts,
            "kinds": _kinds(),
            "seriCategories": list(SERI_CATEGORIES),
            "taxiCategories": list(TAXI_CATEGORIES),
            **boards_public_meta(),
        })

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
            try:
                cur = conn.execute(
                    """
                    INSERT INTO posts (
                      publisher_id, kind, title, summary, body, category, url, phone,
                      location, slug, plan, status, created_at, updated_at, locality
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)
                    """,
                    (
                        pub_id, data["kind"], data["title"], data["summary"], data["body"],
                        data["category"], data["url"], data["phone"], data["location"],
                        data["slug"], data["plan"], now, now, data.get("locality") or "mandi",
                    ),
                )
            except sqlite3.OperationalError:
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

    @app.post("/api/hub/posts/<int:post_id>/interest")
    def hub_post_interest(post_id: int):
        body = request.get_json(force=True, silent=True) or {}
        name = str(body.get("name") or "").strip()[:80]
        phone = _normalize_phone(body.get("phone") or "")
        note = str(body.get("note") or "").strip()[:400]
        conn = db()
        try:
            actor = _resolve_interest_actor(conn)
            if not actor:
                return jsonify({
                    "ok": False,
                    "error": "Sign in as a labour worker (/labour) or on Mandi Adda / publish desk",
                }), 401
            if not name:
                name = actor["name"] or "Worker"
            if len(name) < 2:
                return jsonify({"ok": False, "error": "Enter your name"}), 400
            if actor.get("worker_id") and actor.get("phone"):
                phone = _normalize_phone(actor["phone"])
            if len(phone) < 8:
                return jsonify({"ok": False, "error": "Enter a mobile number so the poster can call you back"}), 400
            post = conn.execute(
                """
                SELECT posts.*, publishers.name AS publisher_name
                FROM posts JOIN publishers ON publishers.id = posts.publisher_id
                WHERE posts.id = ? AND posts.status = 'published' AND publishers.status = 'active'
                """,
                (post_id,),
            ).fetchone()
            if not post:
                return jsonify({"ok": False, "error": "Need not found"}), 404
            if not _is_board_kind(post["kind"]):
                return jsonify({"ok": False, "error": "Interest is only for labour / taxi board needs"}), 400
            board_id = _normalize_feed_kind(post["kind"])
            if actor["publisher_id"] and int(actor["publisher_id"]) == int(post["publisher_id"]):
                return jsonify({"ok": False, "error": "You posted this need"}), 400
            # Replace any prior open interest from the same identity.
            if actor["publisher_id"]:
                conn.execute(
                    "DELETE FROM hub_post_interest WHERE post_id = ? AND from_publisher_id = ? AND status = 'open'",
                    (post_id, actor["publisher_id"]),
                )
            if actor["adda_user_id"]:
                conn.execute(
                    "DELETE FROM hub_post_interest WHERE post_id = ? AND from_adda_user_id = ? AND status = 'open'",
                    (post_id, actor["adda_user_id"]),
                )
            provider_id = actor.get("provider_id") or actor.get("worker_id") or ""
            if provider_id:
                conn.execute(
                    "DELETE FROM hub_post_interest WHERE post_id = ? AND from_worker_id = ? AND status = 'open'",
                    (post_id, provider_id),
                )
                try:
                    conn.execute(
                        "DELETE FROM hub_post_interest WHERE post_id = ? AND from_provider_id = ? AND status = 'open'",
                        (post_id, provider_id),
                    )
                except sqlite3.OperationalError:
                    pass
            iid = "hi_" + secrets.token_hex(8)
            try:
                conn.execute(
                    """
                    INSERT INTO hub_post_interest (
                      id, post_id, from_publisher_id, from_adda_user_id, from_worker_id,
                      from_provider_id, board_id, name, note, phone, status, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?)
                    """,
                    (
                        iid,
                        post_id,
                        actor["publisher_id"],
                        actor["adda_user_id"] or "",
                        provider_id,
                        provider_id,
                        board_id,
                        name,
                        note,
                        phone,
                        _now(),
                    ),
                )
            except sqlite3.OperationalError:
                conn.execute(
                    """
                    INSERT INTO hub_post_interest (
                      id, post_id, from_publisher_id, from_adda_user_id, from_worker_id,
                      name, note, phone, status, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'open', ?)
                    """,
                    (
                        iid,
                        post_id,
                        actor["publisher_id"],
                        actor["adda_user_id"] or "",
                        provider_id,
                        name,
                        note,
                        phone,
                        _now(),
                    ),
                )
            conn.commit()
            row = conn.execute("SELECT * FROM hub_post_interest WHERE id = ?", (iid,)).fetchone()
        except sqlite3.IntegrityError:
            return jsonify({"ok": False, "error": "You already showed interest in this need"}), 409
        finally:
            conn.close()
        return jsonify({"ok": True, "interest": _interest_dict(row)})

    @app.get("/api/hub/publisher/posts/<int:post_id>/interests")
    @require_publisher
    def publisher_post_interests(post_id: int):
        conn = db()
        try:
            post = conn.execute(
                "SELECT * FROM posts WHERE id = ? AND publisher_id = ?",
                (post_id, g.publisher["id"]),
            ).fetchone()
            if not post:
                return jsonify({"ok": False, "error": "Listing not found"}), 404
            if not _is_board_kind(post["kind"]):
                return jsonify({"ok": False, "error": "Interests are only for board needs"}), 400
            rows = conn.execute(
                """
                SELECT * FROM hub_post_interest
                WHERE post_id = ? AND status = 'open'
                ORDER BY created_at DESC
                """,
                (post_id,),
            ).fetchall()
        finally:
            conn.close()
        return jsonify({
            "ok": True,
            "postId": post_id,
            "interests": [_interest_dict(r) for r in rows],
        })

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
        appender = getattr(app, "adda_append_bridge_message", None)
        if appender:
            try:
                appender(
                    title=data["title"],
                    summary=data.get("summary") or "",
                    url=data.get("url") or "",
                    source_site=site_id,
                    source_id=source_id,
                )
            except Exception:
                pass
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
                "scitech": bool(features.get("scitech", True)),
                "culture": bool(features.get("culture", True)),
                "services": bool(features.get("services", True)),
                "seri": bool(features.get("seri", features.get("labour", True))),
                "labour": bool(features.get("labour", features.get("seri", True))),
                "taxi": bool(features.get("taxi", True)),
                "boards": bool(features.get("boards", True)),
                "channels": bool(features.get("channels", True)),
                "ads": bool(features.get("ads", True)),
                "neighbourhoods": bool(features.get("neighbourhoods", True)),
                "businesses": bool(features.get("businesses", True)),
                "heroBoardCards": bool(features.get("heroBoardCards", True)),
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

    def _ensure_sponsored():
        if sponsored_path.is_file():
            return
        _write(sponsored_path, DEFAULT_SPONSORED)

    def _optimize_sponsored_image(raw: bytes) -> bytes:
        if len(raw) > 2_500_000:
            raise ValueError("Image must be under 2.5 MB")
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
        if edge > 1200:
            scale = 1200 / edge
            resample = Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS
            img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))), resample)
        buf = BytesIO()
        img.save(buf, format="WEBP", quality=80, method=4)
        return buf.getvalue()

    def _clean_sponsored_ads(rows) -> list:
        out = []
        seen = set()
        anim_ids = {a["id"] for a in SPONSORED_ANIMATIONS}
        for item in rows or []:
            if not isinstance(item, dict):
                continue
            aid = re.sub(r"[^a-zA-Z0-9._-]+", "-", str(item.get("id") or "").strip())[:64].strip("-")
            if not aid:
                aid = f"ad_{secrets.token_hex(4)}"
            if aid in seen:
                continue
            seen.add(aid)
            anim = str(item.get("animation") or "marquee").strip().lower()
            if anim not in anim_ids:
                anim = "marquee"
            title = str(item.get("title") or "").strip()[:120]
            if not title:
                continue
            image = str(item.get("imageUrl") or item.get("image") or "").strip()
            if image.startswith("/api/hub/sponsored-ads/images/"):
                pass
            elif image.startswith("sponsored/") or re.fullmatch(r"[a-zA-Z0-9._-]+\.webp", image or ""):
                name = image.split("/")[-1]
                image = f"/api/hub/sponsored-ads/images/{name}"
            elif image and not (
                image.startswith("http://") or image.startswith("https://") or image.startswith("/")
            ):
                image = ""
            out.append({
                "id": aid,
                "title": title,
                "subtitle": str(item.get("subtitle") or "").strip()[:160],
                "animation": anim,
                "imageUrl": image[:400],
                "linkUrl": str(item.get("linkUrl") or item.get("url") or "").strip()[:400],
                "sponsor": str(item.get("sponsor") or "").strip()[:80],
                "active": bool(item.get("active", True)),
                "weight": max(1, min(int(item.get("weight") or 1), 100)),
                "startsAt": str(item.get("startsAt") or "").strip()[:32],
                "endsAt": str(item.get("endsAt") or "").strip()[:32],
            })
        return out

    def _sponsored_active(ads: list) -> list:
        now = _now()
        active = []
        for ad in ads:
            if not ad.get("active"):
                continue
            start = ad.get("startsAt") or ""
            end = ad.get("endsAt") or ""
            if start and now < start:
                continue
            if end and now > end:
                continue
            active.append(ad)
        active.sort(key=lambda a: (-int(a.get("weight") or 1), a.get("title") or ""))
        return active

    _ensure_sponsored()

    @app.get("/api/hub/sponsored-ads")
    def hub_sponsored_public():
        _ensure_sponsored()
        data = _read(sponsored_path, DEFAULT_SPONSORED)
        ads = _clean_sponsored_ads(data.get("ads") if isinstance(data.get("ads"), list) else [])
        ads = _sponsored_active(ads)
        try:
            ads = list(ads) + active_header_pack_ads(db)
        except Exception:
            pass
        ads.sort(key=lambda a: (-int(a.get("weight") or 1), a.get("title") or ""))
        return jsonify({
            "ok": True,
            "ads": ads,
            "animations": SPONSORED_ANIMATIONS,
        })

    @app.get("/api/hub/sponsored-ads/manage")
    @require_operator
    def hub_sponsored_manage():
        _ensure_sponsored()
        data = _read(sponsored_path, DEFAULT_SPONSORED)
        ads = _clean_sponsored_ads(data.get("ads") if isinstance(data.get("ads"), list) else [])
        return jsonify({"ok": True, "ads": ads, "animations": SPONSORED_ANIMATIONS})

    @app.put("/api/hub/sponsored-ads")
    @require_operator
    def hub_sponsored_save():
        body = request.get_json(force=True, silent=True) or {}
        ads = _clean_sponsored_ads(body.get("ads") if isinstance(body.get("ads"), list) else [])
        payload = {"ads": ads}
        _write(sponsored_path, payload)
        return jsonify({"ok": True, "ads": ads, "animations": SPONSORED_ANIMATIONS})

    @app.post("/api/hub/sponsored-ads/upload")
    @require_operator
    def hub_sponsored_upload():
        upload = request.files.get("file") or request.files.get("image")
        if not upload or not upload.filename:
            return jsonify({"ok": False, "error": "Choose an image"}), 400
        try:
            data = _optimize_sponsored_image(upload.read())
        except ValueError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        name = f"sp_{secrets.token_hex(8)}.webp"
        (sponsored_dir / name).write_bytes(data)
        url = f"/api/hub/sponsored-ads/images/{name}"
        return jsonify({"ok": True, "imageUrl": url, "filename": name})

    @app.get("/api/hub/sponsored-ads/images/<filename>")
    def hub_sponsored_image(filename: str):
        safe = re.sub(r"[^a-zA-Z0-9._-]+", "", filename or "")
        if not safe or ".." in safe:
            return jsonify({"ok": False, "error": "Not found"}), 404
        path = sponsored_dir / safe
        if not path.is_file():
            return jsonify({"ok": False, "error": "Not found"}), 404
        return send_file(path, mimetype="image/webp", conditional=True)

    def _ensure_spotlight():
        if spotlight_path.is_file():
            return
        _write(spotlight_path, DEFAULT_SPOTLIGHT)

    def _normalize_spotlight_image(image: str) -> str:
        image = str(image or "").strip()
        if not image:
            return ""
        if image.startswith("/api/hub/spotlight/images/"):
            return image[:400]
        if image.startswith("spotlight/") or re.fullmatch(r"[a-zA-Z0-9._-]+\.webp", image or ""):
            name = image.split("/")[-1]
            return f"/api/hub/spotlight/images/{name}"[:400]
        if image.startswith("http://") or image.startswith("https://") or image.startswith("/"):
            return image[:400]
        return ""

    def _clean_spotlight_slots(rows) -> list:
        out = []
        seen = set()
        for item in rows or []:
            if not isinstance(item, dict):
                continue
            sid = re.sub(r"[^a-zA-Z0-9._-]+", "-", str(item.get("id") or "").strip())[:64].strip("-")
            if not sid:
                sid = f"spot_{secrets.token_hex(4)}"
            if sid in seen:
                continue
            seen.add(sid)
            kind = str(item.get("kind") or "person").strip().lower()
            if kind not in SPOTLIGHT_KINDS:
                kind = "person"
            status = str(item.get("status") or "draft").strip().lower()
            if status not in SPOTLIGHT_STATUSES:
                status = "draft"
            title = str(item.get("title") or "").strip()[:140]
            if not title:
                continue
            linked = item.get("linkedPostId")
            try:
                linked_id = int(linked) if linked not in (None, "", 0, "0") else None
            except (TypeError, ValueError):
                linked_id = None
            out.append({
                "id": sid,
                "kind": kind,
                "status": status,
                "title": title,
                "subtitle": str(item.get("subtitle") or "").strip()[:180],
                "body": str(item.get("body") or item.get("richHtml") or "").strip()[:4000],
                "portraitUrl": _normalize_spotlight_image(
                    item.get("portraitUrl") or item.get("portrait") or ""
                ),
                "coverUrl": _normalize_spotlight_image(
                    item.get("coverUrl") or item.get("cover") or item.get("imageUrl") or ""
                ),
                "ctaLabel": str(item.get("ctaLabel") or "").strip()[:60],
                "ctaHref": str(item.get("ctaHref") or item.get("linkUrl") or "").strip()[:400],
                "linkedPostId": linked_id,
                "showInHeroCircle": bool(item.get("showInHeroCircle", False)),
                "startsAt": str(item.get("startsAt") or "").strip()[:32],
                "endsAt": str(item.get("endsAt") or "").strip()[:32],
            })
        return out

    def _spotlight_in_window(slot: dict, now: str) -> bool:
        start = slot.get("startsAt") or ""
        end = slot.get("endsAt") or ""
        if start and now < start:
            return False
        if end and now > end:
            return False
        return True

    def _spotlight_current(slots: list) -> dict | None:
        """One live slot: scheduled/active in window; overlapping → latest startsAt."""
        now = _now()
        candidates = []
        for slot in slots:
            status = slot.get("status") or ""
            if status not in ("active", "scheduled"):
                continue
            if not _spotlight_in_window(slot, now):
                continue
            candidates.append(slot)
        if not candidates:
            return None
        candidates.sort(
            key=lambda s: (s.get("startsAt") or "", s.get("id") or ""),
            reverse=True,
        )
        return candidates[0]

    def _enrich_spotlight_from_post(slot: dict) -> dict:
        """Fill gaps from a linked published post when present."""
        linked = slot.get("linkedPostId")
        if not linked:
            return slot
        conn = db()
        try:
            row = conn.execute(
                """
                SELECT p.*, pub.name AS publisher_name
                FROM posts p
                JOIN publishers pub ON pub.id = p.publisher_id
                WHERE p.id = ? AND p.status = 'published'
                """,
                (int(linked),),
            ).fetchone()
        finally:
            conn.close()
        if not row:
            return slot
        out = dict(slot)
        if not out.get("subtitle") and row["summary"]:
            out["subtitle"] = str(row["summary"]).strip()[:180]
        if not out.get("body") and (row["body"] or row["summary"]):
            out["body"] = str(row["body"] or row["summary"]).strip()[:4000]
        if not out.get("ctaHref"):
            if row["url"]:
                out["ctaHref"] = str(row["url"]).strip()[:400]
            elif row["kind"] == "business" and row["plan"] == "hosted" and row["slug"]:
                out["ctaHref"] = f"/b/{row['slug']}"
        if not out.get("ctaLabel"):
            out["ctaLabel"] = "Read story" if out.get("kind") == "post" else "Meet"
        out["linkedPost"] = {
            "id": row["id"],
            "kind": row["kind"],
            "title": row["title"],
            "summary": row["summary"] or "",
            "publisherName": row["publisher_name"] or "",
        }
        return out

    _ensure_spotlight()

    @app.get("/api/hub/spotlight")
    def hub_spotlight_public():
        _ensure_spotlight()
        data = _read(spotlight_path, DEFAULT_SPOTLIGHT)
        slots = _clean_spotlight_slots(
            data.get("slots") if isinstance(data.get("slots"), list) else []
        )
        current = _spotlight_current(slots)
        if current:
            current = _enrich_spotlight_from_post(current)
        return jsonify({"ok": True, "spotlight": current})

    @app.get("/api/hub/spotlight/manage")
    @require_operator
    def hub_spotlight_manage():
        _ensure_spotlight()
        data = _read(spotlight_path, DEFAULT_SPOTLIGHT)
        slots = _clean_spotlight_slots(
            data.get("slots") if isinstance(data.get("slots"), list) else []
        )
        return jsonify({
            "ok": True,
            "slots": slots,
            "current": _spotlight_current(slots),
            "kinds": list(SPOTLIGHT_KINDS),
            "statuses": list(SPOTLIGHT_STATUSES),
        })

    @app.put("/api/hub/spotlight")
    @require_operator
    def hub_spotlight_save():
        body = request.get_json(force=True, silent=True) or {}
        slots = _clean_spotlight_slots(
            body.get("slots") if isinstance(body.get("slots"), list) else []
        )
        # Soft overlap: still save; public picks latest startsAt.
        _write(spotlight_path, {"slots": slots})
        return jsonify({
            "ok": True,
            "slots": slots,
            "current": _spotlight_current(slots),
        })

    @app.post("/api/hub/spotlight/upload")
    @require_operator
    def hub_spotlight_upload():
        upload = request.files.get("file") or request.files.get("image")
        if not upload or not upload.filename:
            return jsonify({"ok": False, "error": "Choose an image"}), 400
        try:
            data = _optimize_sponsored_image(upload.read())
        except ValueError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        name = f"sl_{secrets.token_hex(8)}.webp"
        (spotlight_dir / name).write_bytes(data)
        url = f"/api/hub/spotlight/images/{name}"
        return jsonify({"ok": True, "imageUrl": url, "filename": name})

    @app.get("/api/hub/spotlight/images/<filename>")
    def hub_spotlight_image(filename: str):
        safe = re.sub(r"[^a-zA-Z0-9._-]+", "", filename or "")
        if not safe or ".." in safe:
            return jsonify({"ok": False, "error": "Not found"}), 404
        path = spotlight_dir / safe
        if not path.is_file():
            return jsonify({"ok": False, "error": "Not found"}), 404
        return send_file(path, mimetype="image/webp", conditional=True)

    @app.get("/api/hub/changes")
    def hub_changes():
        """Cheap revision stamp for live public refresh (poll every ~20–30s)."""
        payload = _changes_parts()
        return jsonify({"ok": True, "rev": payload["rev"], "parts": payload["parts"]})

    register_commerce(
        app,
        db=db,
        require_publisher=require_publisher,
        require_provider=require_provider,
        normalize_locality_fn=normalize_locality,
        data_dir=data_dir,
    )
