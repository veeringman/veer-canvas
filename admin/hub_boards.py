"""City of Mandi profession boards — labour, taxi, service desks, shared provider identity."""

from __future__ import annotations

import json
import math
import pathlib
import re
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from io import BytesIO
from typing import Any

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Mandi district + nearby valley hubs (approx. centroids for nearest-match).
LOCALITIES = (
    {"id": "mandi", "label": "Mandi", "labelHi": "मंडी", "lat": 31.7083, "lng": 76.9318},
    {"id": "sundernagar", "label": "Sunder Nagar", "labelHi": "सुंदरनगर", "lat": 31.5332, "lng": 76.8924},
    {"id": "nerchowk", "label": "Ner Chowk", "labelHi": "नेरचौक", "lat": 31.6085, "lng": 76.9142},
    {"id": "sarkaghat", "label": "Sarkaghat", "labelHi": "सरकाघाट", "lat": 31.7000, "lng": 76.7333},
    {"id": "pandoh", "label": "Pandoh", "labelHi": "पंदोह", "lat": 31.6667, "lng": 77.0667},
    {"id": "jogindernagar", "label": "Joginder Nagar", "labelHi": "जोगिंदर नगर", "lat": 31.9872, "lng": 76.7903},
    {"id": "rewalsar", "label": "Rewalsar", "labelHi": "रेवालसर", "lat": 31.6342, "lng": 76.8331},
    {"id": "bagsaid", "label": "Bagsaid", "labelHi": "बगसैद", "lat": 31.5500, "lng": 76.8667},
    {"id": "aut", "label": "Aut", "labelHi": "औट", "lat": 31.7250, "lng": 77.2050},
    {"id": "karsog", "label": "Karsog", "labelHi": "करसोग", "lat": 31.3833, "lng": 77.2000},
    {"id": "gohar", "label": "Gohar", "labelHi": "गोहर", "lat": 31.5500, "lng": 77.0167},
    {"id": "baldwara", "label": "Baldwara", "labelHi": "बल्द्वारा", "lat": 31.5833, "lng": 76.7833},
    {"id": "padhar", "label": "Padhar", "labelHi": "पधार", "lat": 31.9500, "lng": 76.9167},
    {"id": "chauntra", "label": "Chauntra", "labelHi": "चौंतरा", "lat": 32.0167, "lng": 76.8333},
    {"id": "janjehli", "label": "Janjehli", "labelHi": "जंजेहली", "lat": 31.5167, "lng": 77.2167},
    {"id": "thunag", "label": "Thunag", "labelHi": "थुनाग", "lat": 31.5500, "lng": 77.1667},
    {"id": "dharampur", "label": "Dharampur (Mandi)", "labelHi": "धर्मपुर", "lat": 31.3500, "lng": 76.9500},
    {"id": "kullu", "label": "Kullu", "labelHi": "कुल्लू", "lat": 31.9579, "lng": 77.1095},
    {"id": "manali", "label": "Manali", "labelHi": "मनाली", "lat": 32.2432, "lng": 77.1892},
    {"id": "bhuntar", "label": "Bhuntar", "labelHi": "भुंतर", "lat": 31.8760, "lng": 77.1480},
    {"id": "banjar", "label": "Banjar", "labelHi": "बंजार", "lat": 31.6333, "lng": 77.3500},
    {"id": "jibhi", "label": "Jibhi", "labelHi": "जिभी", "lat": 31.5950, "lng": 77.3800},
    {"id": "kasol", "label": "Kasol", "labelHi": "कसोल", "lat": 32.0100, "lng": 77.3150},
    {"id": "birbilling", "label": "Bir-Billing", "labelHi": "बीर-बिलिंग", "lat": 32.0420, "lng": 76.7050},
)

# Boards that benefit from live geo → preferred locality auto-set.
LIVE_LOCALITY_BOARDS = frozenset({
    "labour", "taxi", "food", "grocery", "hardware", "haulage", "rentals",
    "vehicle", "doctor", "tours", "home",
})

PROFESSION_BOARDS = {
    "labour": {
        "id": "labour",
        "kindAliases": ("labour", "seri"),
        "title": "Labour market",
        "titleHi": "मज़दूर बाज़ार",
        "lede": "Morning work needs and available workers. Contact stays private until someone responds in-app.",
        "ledeHi": "सुबह की ज़रूरतें और उपलब्ध मजदूर। संपर्क ऐप में जवाब देने तक निजी रहता है।",
        "categories": ("Construction", "Garden", "Clean", "Load/unload", "Other"),
        "morningWindow": {"startHour": 6, "endHour": 10, "tz": "Asia/Kolkata"},
        "contactPolicy": "reveal_on_response_only",
        "registerPath": "/labour",
        "hash": "landing-labour",
        "legacyHash": "landing-seri",
        "liveLocality": True,
    },
    "taxi": {
        "id": "taxi",
        "kindAliases": ("taxi",),
        "title": "Cabs & taxis",
        "titleHi": "कैब और टैक्सी",
        "lede": "Ride requests and drivers on duty. Contact stays private until a driver responds in-app.",
        "ledeHi": "सवारी अनुरोध और ड्यूटी पर ड्राइवर। संपर्क ऐप में जवाब देने तक निजी रहता है।",
        "categories": ("Local", "Outstation", "Airport/rail", "Shared", "Other"),
        "morningWindow": None,
        "contactPolicy": "reveal_on_response_only",
        "registerPath": "/taxi",
        "hash": "landing-taxi",
        "legacyHash": "",
        "liveLocality": True,
    },
    "experts": {
        "id": "experts",
        "kindAliases": ("experts", "sme"),
        "title": "SME & experts",
        "titleHi": "विशेषज्ञ और SME",
        "lede": "Consultants, freelancers, and local experts — request help; contact stays private until a response.",
        "ledeHi": "सलाहकार और स्थानीय विशेषज्ञ — जवाब तक संपर्क निजी।",
        "categories": ("Business", "Legal", "Accounts", "IT", "Design", "Other"),
        "morningWindow": None,
        "contactPolicy": "reveal_on_response_only",
        "registerPath": "/partner?board=experts",
        "hash": "landing-experts",
        "legacyHash": "",
        "liveLocality": False,
    },
    "vehicle": {
        "id": "vehicle",
        "kindAliases": ("vehicle",),
        "title": "Vehicle servicing",
        "titleHi": "वाहन सर्विस",
        "lede": "Mechanics and service desks on duty — two-wheeler, car, and roadside help.",
        "ledeHi": "मैकेनिक और सर्विस — दुपहिया, कार, रोडसाइड।",
        "categories": ("Two-wheeler", "Car", "Truck/tempo", "Puncture", "Battery", "Other"),
        "morningWindow": None,
        "contactPolicy": "reveal_on_response_only",
        "registerPath": "/partner?board=vehicle",
        "hash": "landing-vehicle",
        "legacyHash": "",
        "liveLocality": True,
    },
    "doctor": {
        "id": "doctor",
        "kindAliases": ("doctor", "doc"),
        "title": "Doc on call",
        "titleHi": "डॉक्टर ऑन कॉल",
        "lede": "Local doctors and clinics available for consults — not an emergency ambulance service.",
        "ledeHi": "स्थानीय डॉक्टर और क्लिनिक — आपातकालीन एम्बुलेंस नहीं।",
        "categories": ("GP", "Pediatric", "Dental", "Physio", "Home visit", "Other"),
        "morningWindow": None,
        "contactPolicy": "reveal_on_response_only",
        "registerPath": "/partner?board=doctor",
        "hash": "landing-doctor",
        "legacyHash": "",
        "liveLocality": True,
    },
    "tours": {
        "id": "tours",
        "kindAliases": ("tours", "travel"),
        "title": "Tours & travels",
        "titleHi": "टूर्स और ट्रैवल",
        "lede": "Guides, packages, and travel desks for Mandi valleys and beyond.",
        "ledeHi": "गाइड, पैकेज और ट्रैवल डेस्क।",
        "categories": ("Day trip", "Trekking", "Taxi tour", "Hotel desk", "Pilgrimage", "Other"),
        "morningWindow": None,
        "contactPolicy": "reveal_on_response_only",
        "registerPath": "/partner?board=tours",
        "hash": "landing-tours",
        "legacyHash": "",
        "liveLocality": True,
    },
    "tutors": {
        "id": "tutors",
        "kindAliases": ("tutors", "coaching", "mentor"),
        "title": "Tutors & mentoring",
        "titleHi": "ट्यूटर और मेंटरिंग",
        "lede": "Home tutors, coaching, and mentors — school to competitive exams.",
        "ledeHi": "होम ट्यूटर, कोचिंग और मेंटर।",
        "categories": ("School", "Competitive", "Languages", "Music/arts", "Career mentor", "Other"),
        "morningWindow": None,
        "contactPolicy": "reveal_on_response_only",
        "registerPath": "/partner?board=tutors",
        "hash": "landing-tutors",
        "legacyHash": "",
        "liveLocality": False,
    },
    "home": {
        "id": "home",
        "kindAliases": ("home", "homeservices"),
        "title": "Home services",
        "titleHi": "घर सेवाएँ",
        "lede": "Plumbers, electricians, carpenters, and household help on the board.",
        "ledeHi": "प्लंबर, बिजली, बढ़ई और घरेलू मदद।",
        "categories": ("Plumber", "Electrician", "Carpenter", "Painter", "Appliance", "Other"),
        "morningWindow": None,
        "contactPolicy": "reveal_on_response_only",
        "registerPath": "/partner?board=home",
        "hash": "landing-home",
        "legacyHash": "",
        "liveLocality": True,
    },
}

# Where a signed-in user “lands” after auth (profession + commerce + Adda).
HUB_HOME_BOARDS = frozenset(
    set(PROFESSION_BOARDS.keys())
    | {"city", "food", "grocery", "hardware", "haulage", "rentals", "adda"}
)

# Citizen / visitor default — city news board, not a trade desk.
DEFAULT_PREFERRED_BOARD = "city"


def normalize_preferred_board(raw: str | None) -> str:
    key = (raw or "").strip().lower()
    if key == "seri":
        key = "labour"
    if key in ("sme",):
        key = "experts"
    if key in ("doc",):
        key = "doctor"
    if key in ("travel",):
        key = "tours"
    if key in ("coaching", "mentor"):
        key = "tutors"
    if key in ("explore", "news", "hub"):
        key = "city"
    if key in HUB_HOME_BOARDS:
        return key
    return DEFAULT_PREFERRED_BOARD


def normalize_content_lang(raw: str | None) -> str:
    key = (raw or "en").strip().lower()
    if key in ("hi", "hin", "hindi", "हिंदी", "हिं"):
        return "hi"
    return "en"


def board_ids() -> list[str]:
    return list(PROFESSION_BOARDS.keys())


def get_board(board_id: str) -> dict | None:
    key = (board_id or "").strip().lower()
    if key == "seri":
        key = "labour"
    if key == "sme":
        key = "experts"
    if key in ("doc",):
        key = "doctor"
    if key in ("travel",):
        key = "tours"
    if key in ("coaching", "mentor"):
        key = "tutors"
    return PROFESSION_BOARDS.get(key)


def normalize_board_id(raw: str | None) -> str:
    board = get_board(raw or "")
    if not board:
        raise ValueError("Unknown board")
    return board["id"]


def post_kinds_for_board(board_id: str) -> tuple[str, ...]:
    board = get_board(board_id)
    if not board:
        return ()
    return tuple(board["kindAliases"])


def locality_ids() -> set[str]:
    return {row["id"] for row in LOCALITIES}


def normalize_locality(raw: str | None) -> str:
    key = (raw or "mandi").strip().lower().replace(" ", "").replace("_", "").replace("-", "")
    aliases = {
        "mandi": "mandi",
        "sundernagar": "sundernagar",
        "sundarnagar": "sundernagar",
        "nerchowk": "nerchowk",
        "nerchowkmandi": "nerchowk",
        "sarkaghat": "sarkaghat",
        "pandoh": "pandoh",
        "jogindernagar": "jogindernagar",
        "jogindernager": "jogindernagar",
        "rewalsar": "rewalsar",
        "bagsaid": "bagsaid",
        "aut": "aut",
        "karsog": "karsog",
        "gohar": "gohar",
        "baldwara": "baldwara",
        "padhar": "padhar",
        "chauntra": "chauntra",
        "janjehli": "janjehli",
        "thunag": "thunag",
        "dharampur": "dharampur",
        "dharampurmandi": "dharampur",
        "kullu": "kullu",
        "manali": "manali",
        "bhuntar": "bhuntar",
        "banjar": "banjar",
        "jibhi": "jibhi",
        "kasol": "kasol",
        "bir": "birbilling",
        "billing": "birbilling",
        "birbilling": "birbilling",
    }
    out = aliases.get(key, key if key in locality_ids() else "mandi")
    return out if out in locality_ids() else "mandi"


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def nearest_locality(lat: float, lng: float) -> dict | None:
    try:
        lat_f, lng_f = float(lat), float(lng)
    except (TypeError, ValueError):
        return None
    best = None
    best_d = 1e18
    for row in LOCALITIES:
        d = _haversine_km(lat_f, lng_f, float(row["lat"]), float(row["lng"]))
        if d < best_d:
            best_d = d
            best = row
    if not best:
        return None
    return {**best, "distanceKm": round(best_d, 2)}


def ist_day(now: datetime | None = None) -> str:
    base = now or datetime.now(timezone.utc)
    return (base + timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d")


def ensure_provider_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS hub_providers (
          id TEXT PRIMARY KEY,
          display_name TEXT NOT NULL,
          phone TEXT NOT NULL UNIQUE,
          email TEXT NOT NULL DEFAULT '',
          password_hash TEXT NOT NULL,
          photo TEXT NOT NULL DEFAULT '',
          address TEXT NOT NULL DEFAULT '',
          official_id TEXT NOT NULL DEFAULT '',
          location TEXT NOT NULL DEFAULT '',
          home_locality TEXT NOT NULL DEFAULT 'mandi',
          preferred_board TEXT NOT NULL DEFAULT 'labour',
          status TEXT NOT NULL DEFAULT 'active',
          created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_hub_providers_phone ON hub_providers(phone);
        CREATE INDEX IF NOT EXISTS idx_hub_providers_locality ON hub_providers(home_locality);
        CREATE TABLE IF NOT EXISTS hub_provider_roles (
          provider_id TEXT NOT NULL,
          board_id TEXT NOT NULL,
          skills TEXT NOT NULL DEFAULT '',
          meta_json TEXT NOT NULL DEFAULT '{}',
          active INTEGER NOT NULL DEFAULT 1,
          PRIMARY KEY (provider_id, board_id),
          FOREIGN KEY (provider_id) REFERENCES hub_providers(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS hub_provider_availability (
          provider_id TEXT NOT NULL,
          board_id TEXT NOT NULL,
          day_ist TEXT NOT NULL,
          available INTEGER NOT NULL DEFAULT 1,
          note TEXT NOT NULL DEFAULT '',
          meta_json TEXT NOT NULL DEFAULT '{}',
          updated_at TEXT NOT NULL,
          PRIMARY KEY (provider_id, board_id, day_ist),
          FOREIGN KEY (provider_id) REFERENCES hub_providers(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_hub_provider_avail_day
          ON hub_provider_availability(board_id, day_ist, available);
        """
    )
    for stmt in (
        "ALTER TABLE hub_post_interest ADD COLUMN from_provider_id TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE hub_post_interest ADD COLUMN board_id TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE posts ADD COLUMN locality TEXT NOT NULL DEFAULT 'mandi'",
        "ALTER TABLE hub_providers ADD COLUMN content_lang TEXT NOT NULL DEFAULT 'en'",
    ):
        try:
            conn.execute(stmt)
        except sqlite3.OperationalError:
            pass
    try:
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_hub_interest_provider "
            "ON hub_post_interest(post_id, from_provider_id) "
            "WHERE from_provider_id != '' AND status = 'open'"
        )
    except sqlite3.OperationalError:
        pass
    conn.commit()


def migrate_seri_into_providers(conn: sqlite3.Connection, now: str) -> None:
    """One-way copy from legacy seri_* tables into hub_providers."""
    ensure_provider_tables(conn)
    try:
        workers = conn.execute("SELECT * FROM seri_workers").fetchall()
    except sqlite3.OperationalError:
        workers = []
    for row in workers:
        keys = set(row.keys())
        wid = str(row["id"])
        exists = conn.execute("SELECT id FROM hub_providers WHERE id = ? OR phone = ?", (wid, row["phone"])).fetchone()
        if not exists:
            conn.execute(
                """
                INSERT INTO hub_providers (
                  id, display_name, phone, email, password_hash, photo, address, official_id,
                  location, home_locality, preferred_board, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'mandi', 'labour', ?, ?)
                """,
                (
                    wid,
                    row["display_name"],
                    row["phone"],
                    row["email"] or "",
                    row["password_hash"],
                    (row["photo"] if "photo" in keys else "") or "",
                    (row["address"] if "address" in keys else "") or "",
                    (row["official_id"] if "official_id" in keys else "") or "",
                    row["location"] or "",
                    row["status"] or "active",
                    row["created_at"] or now,
                ),
            )
        provider_id = wid if not exists else str(exists["id"])
        conn.execute(
            """
            INSERT INTO hub_provider_roles (provider_id, board_id, skills, meta_json, active)
            VALUES (?, 'labour', ?, '{}', 1)
            ON CONFLICT(provider_id, board_id) DO UPDATE SET
              skills = excluded.skills,
              active = 1
            """,
            (provider_id, row["skills"] or ""),
        )
    try:
        avail = conn.execute("SELECT * FROM seri_availability").fetchall()
    except sqlite3.OperationalError:
        avail = []
    for row in avail:
        conn.execute(
            """
            INSERT INTO hub_provider_availability (
              provider_id, board_id, day_ist, available, note, meta_json, updated_at
            ) VALUES (?, 'labour', ?, ?, ?, '{}', ?)
            ON CONFLICT(provider_id, board_id, day_ist) DO UPDATE SET
              available = excluded.available,
              note = excluded.note,
              updated_at = excluded.updated_at
            """,
            (
                row["worker_id"],
                row["day_ist"],
                int(row["available"] or 0),
                row["note"] or "",
                row["updated_at"] or now,
            ),
        )
    # Interest: copy worker id into provider id; board labour
    try:
        conn.execute(
            """
            UPDATE hub_post_interest
            SET from_provider_id = from_worker_id,
                board_id = CASE WHEN board_id = '' THEN 'labour' ELSE board_id END
            WHERE from_worker_id != '' AND (from_provider_id = '' OR from_provider_id IS NULL)
            """
        )
    except sqlite3.OperationalError:
        pass
    # Posts: seri -> labour
    try:
        conn.execute("UPDATE posts SET kind = 'labour' WHERE kind = 'seri'")
    except sqlite3.OperationalError:
        pass
    conn.commit()


def boards_public_meta() -> dict:
    return {
        "boards": [
            {
                "id": b["id"],
                "title": b["title"],
                "titleHi": b["titleHi"],
                "lede": b["lede"],
                "ledeHi": b["ledeHi"],
                "categories": list(b["categories"]),
                "morningWindow": b["morningWindow"],
                "contactPolicy": b["contactPolicy"],
                "registerPath": b["registerPath"],
                "hash": b["hash"],
                "liveLocality": bool(b.get("liveLocality")),
            }
            for b in PROFESSION_BOARDS.values()
        ],
        "localities": list(LOCALITIES),
        "liveLocalityBoards": sorted(LIVE_LOCALITY_BOARDS),
    }


def provider_photo_url(raw: str) -> str:
    photo = str(raw or "").strip()
    if not photo:
        return ""
    if photo.startswith("/api/hub/seri/workers/images/") or photo.startswith("/api/hub/providers/images/"):
        # normalize to providers path when possible
        name = pathlib.Path(photo).name
        if re.fullmatch(r"[a-zA-Z0-9._-]+\.webp", name or ""):
            return f"/api/hub/providers/images/{name}"[:400]
        return photo[:400]
    name = pathlib.Path(photo).name
    if re.fullmatch(r"[a-zA-Z0-9._-]+\.webp", name or ""):
        return f"/api/hub/providers/images/{name}"[:400]
    return ""


def optimize_provider_photo(raw: bytes) -> bytes:
    max_bytes = 5 * 1024 * 1024
    if len(raw) > max_bytes:
        raise ValueError("Photo must be 5 MB or smaller")
    if len(raw) < 200:
        raise ValueError("Photo file looks empty")
    try:
        from PIL import Image
    except ImportError as exc:
        raise ValueError("Image processing unavailable") from exc
    try:
        img = Image.open(BytesIO(raw))
        img.load()
    except Exception as exc:  # noqa: BLE001
        raise ValueError("Could not read photo") from exc
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
    side = min(w, h)
    left = (w - side) // 2
    top = (h - side) // 2
    img = img.crop((left, top, left + side, top + side))
    resample = Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS
    img = img.resize((256, 256), resample)
    buf = BytesIO()
    img.save(buf, format="WEBP", quality=55, method=6)
    out = buf.getvalue()
    if len(out) > 120_000:
        buf = BytesIO()
        img.save(buf, format="WEBP", quality=40, method=6)
        out = buf.getvalue()
    return out


def provider_public(row, *, board_id: str, available=False, note="", skills="", include_phone=False) -> dict:
    keys = set(row.keys()) if hasattr(row, "keys") else set()
    address = str(row["address"] if "address" in keys else "") or ""
    location = str(row["location"] or "").strip() or address[:80]
    payload = {
        "id": row["id"],
        "name": row["display_name"],
        "skills": [s for s in str(skills or "").split(",") if s.strip()],
        "location": location,
        "address": address,
        "photo": provider_photo_url(row["photo"] if "photo" in keys else ""),
        "homeLocality": row["home_locality"] if "home_locality" in keys else "mandi",
        "boardId": board_id,
        "availableToday": bool(available),
        "note": note or "",
        "contactHidden": True,
    }
    if include_phone:
        payload["phone"] = str(row["phone"] or "").strip()
        payload["email"] = str(row["email"] or "").strip()
        payload["contactHidden"] = False
    return payload


def provider_session_payload(row, roles: list[dict], *, available_by_board: dict | None = None) -> dict:
    keys = set(row.keys()) if hasattr(row, "keys") else set()
    official = str(row["official_id"] if "official_id" in keys else "") or ""
    return {
        "ok": True,
        "authenticated": True,
        "provider": {
            "id": row["id"],
            "name": row["display_name"],
            "phone": row["phone"],
            "email": row["email"] or "",
            "photo": provider_photo_url(row["photo"] if "photo" in keys else ""),
            "address": (row["address"] if "address" in keys else "") or "",
            "location": row["location"] or "",
            "homeLocality": (row["home_locality"] if "home_locality" in keys else "mandi") or "mandi",
            "preferredBoard": (row["preferred_board"] if "preferred_board" in keys else "labour") or "labour",
            "contentLang": normalize_content_lang(
                row["content_lang"] if "content_lang" in keys else "en"
            ),
            "hasOfficialId": bool(official.strip()),
            "roles": roles,
            "availableByBoard": available_by_board or {},
        },
        **boards_public_meta(),
    }


def list_provider_roles(conn: sqlite3.Connection, provider_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM hub_provider_roles WHERE provider_id = ? AND active = 1",
        (provider_id,),
    ).fetchall()
    out = []
    for row in rows:
        meta = {}
        try:
            meta = json.loads(row["meta_json"] or "{}")
        except json.JSONDecodeError:
            meta = {}
        out.append({
            "boardId": row["board_id"],
            "skills": [s for s in str(row["skills"] or "").split(",") if s.strip()],
            "meta": meta if isinstance(meta, dict) else {},
        })
    return out
