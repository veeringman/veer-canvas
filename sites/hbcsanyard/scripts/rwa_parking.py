"""Parking passes — member, tenant, visitor, and gate ad-hoc (selfie) passes."""

from __future__ import annotations

import calendar
import base64
import html
import json
import os
import pathlib
import re
import secrets
import shutil
import smtplib
import sqlite3
import subprocess
import tempfile
import logging
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from io import BytesIO
from typing import Any
from zoneinfo import ZoneInfo

from init_rwa_db import SUPERADMIN_HOUSE_ID, ADHOC_GATE_HOUSE_ID, ensure_parking_passes_table, utc_now
import rwa_attest
import rwa_entitlements
import rwa_household

IST = ZoneInfo("Asia/Kolkata")
log = logging.getLogger("rwa_parking")

ALLOWED_HOURS = (4, 8, 12, 24)
DEFAULT_HOURS = 24
ALLOWED_MONTHS = (1, 3, 6, 12)
DEFAULT_MONTHS = 6
ALLOWED_ADHOC_HOURS = (1, 2, 3, 4, 5, 6, 7, 8, 9)
DEFAULT_ADHOC_HOURS = 4
ADHOC_HOUSE_ID = ADHOC_GATE_HOUSE_ID
ADHOC_CATEGORIES = {
    "hawker": "Hawker",
    "scrap": "Scrap collector",
    "labour": "Labourer",
    "maid": "Maid",
    "cook": "Cook",
    "delivery": "Delivery",
    "other": "Other",
}
STAFF_CATEGORIES = {
    "maid": "Maid",
    "cook": "Cook",
    "gardener": "Gardener",
    "driver": "Driver",
    "caretaker": "Caretaker",
    "other": "Other",
}
STAFF_MAX_ACTIVE = 8
DEFAULT_STAFF_MONTHS = 3
ADHOC_PHOTO_MAX = 6_000_000
ADHOC_PHOTO_SIZE = 480
VEHICLE_TYPES = ("car", "suv", "van", "bike", "scooter", "other", "foot")
VEHICLE_LABELS = {
    "car": "Car",
    "suv": "SUV",
    "van": "Van",
    "bike": "Motorcycle",
    "scooter": "Scooter",
    "other": "Other",
    "foot": "On foot",
}
STATUS_LABELS = {
    "active": "Active",
    "expired": "Expired",
    "pending_renewal": "Awaiting EC",
    "revoked": "Revoked",
}
META_DEFAULT_HOURS = "parking_default_hours"
META_OCR_PHONE = "parking_ocr_phone"
META_OCR_LIVE = "parking_ocr_live"
META_OCR_FUZZY = "parking_ocr_fuzzy"
META_OCR_SERVER = "parking_ocr_server"
META_OCR_RUST = "parking_ocr_rust"
OCR_SETTING_DEFAULTS = {
    "phone": True,
    "live": True,
    "fuzzy": True,
    "server": True,
    "rust": False,
}
PERMANENT_EXPIRES = "9999-12-31T00:00:00Z"
KIND_MEMBER = "member"
KIND_VISITOR = "visitor"
KIND_TENANT = "tenant"
KIND_ADHOC = "adhoc"
KIND_STAFF = "staff"
KIND_LABELS = {
    KIND_MEMBER: "Member",
    KIND_VISITOR: "Visitor",
    KIND_TENANT: "Tenant",
    KIND_ADHOC: "Ad-hoc",
    KIND_STAFF: "Staff",
}
IDENTITY_KINDS = (KIND_ADHOC, KIND_STAFF)


def parse_utc(value: str | None) -> datetime | None:
    raw = (value or "").strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_ist(value: str | None) -> str:
    dt = parse_utc(value)
    if not dt:
        return ""
    return dt.astimezone(IST).strftime("%d %b %Y, %I:%M %p IST")


def public_origin(site_root: pathlib.Path | None = None) -> str:
    return (
        os.environ.get("VEERCANVAS_PUBLIC_ORIGIN")
        or os.environ.get("RWA_PUBLIC_ORIGIN")
        or "https://housingcolonysanyard.in"
    ).rstrip("/")


def normalize_plate(raw: str | None) -> tuple[str, str]:
    display = re.sub(r"\s+", " ", (raw or "").strip().upper())
    key = re.sub(r"[^A-Z0-9]", "", display)
    if len(key) < 4:
        raise ValueError("Enter a valid vehicle number (at least 4 characters)")
    if len(key) > 14:
        raise ValueError("Vehicle number is too long")
    return key, display or key


def compact_plate(raw: str | None) -> str:
    return re.sub(r"[^A-Z0-9]", "", (raw or "").upper())


# OCR substitutions common on Indian plates (white/yellow, night, motion).
_PLATE_CONFUSION = {
    "0": "OQD",
    "O": "0QD",
    "Q": "0O",
    "D": "0O",
    "1": "ILT7",
    "I": "1LT",
    "L": "1I",
    "7": "1T",
    "T": "17",
    "8": "B",
    "B": "8",
    "5": "S",
    "S": "5",
    "2": "Z",
    "Z": "2",
    "6": "G",
    "G": "6",
    "A": "4",
    "4": "A",
    "U": "V",
    "V": "U",
}


def plate_confusion_distance(a: str, b: str) -> float:
    """Weighted Levenshtein; lookalike substitutions cost less than arbitrary edits."""
    left = compact_plate(a)
    right = compact_plate(b)
    if left == right:
        return 0.0
    if not left or not right:
        return 99.0
    if abs(len(left) - len(right)) > 2:
        return 99.0
    prev = list(range(len(right) + 1))
    for i, ca in enumerate(left, start=1):
        cur = [float(i)]
        for j, cb in enumerate(right, start=1):
            if ca == cb:
                sub = 0.0
            elif cb in _PLATE_CONFUSION.get(ca, ""):
                sub = 0.35
            else:
                sub = 1.0
            cur.append(min(prev[j] + 1.0, cur[j - 1] + 1.0, prev[j - 1] + sub))
        prev = cur
    return float(prev[-1])


_OCR_PLATE_PATTERNS = (
    re.compile(r"[A-Z]{2}\d{1,2}[A-Z]{1,3}\d{3,4}"),
    re.compile(r"\d{2}BH\d{4}[A-Z]{1,2}"),
    re.compile(r"[A-Z]{2}\d{6,7}"),
)
OCR_IMAGE_MAX = 4_000_000


def extract_plates_from_ocr_text(text: str) -> list[str]:
    """Pull Indian registration numbers out of noisy OCR text."""
    compact = re.sub(r"[^A-Z0-9]", "", (text or "").upper())
    compact = compact.replace("INDIA", "").replace("IND", "")
    found: list[str] = []
    seen: set[str] = set()

    def add(plate: str) -> None:
        key = compact_plate(plate)
        if 6 <= len(key) <= 12 and key not in seen:
            seen.add(key)
            found.append(key)

    for pat in _OCR_PLATE_PATTERNS:
        for match in pat.finditer(compact):
            add(match.group(0))
    if 6 <= len(compact) <= 12:
        add(compact)
    if len(compact) > 12:
        for size in (10, 9, 8, 7):
            for i in range(0, len(compact) - size + 1):
                window = compact[i : i + size]
                if any(pat.fullmatch(window) for pat in _OCR_PLATE_PATTERNS):
                    add(window)
    found.sort(key=len, reverse=True)
    pruned: list[str] = []
    for plate in found:
        if any(keep.startswith(plate) and len(keep) > len(plate) for keep in pruned):
            continue
        pruned.append(plate)
    return pruned


def expand_ocr_plates(plates: list[str], *, max_subs: int = 1) -> list[str]:
    """Generate I/1, O/0, B/8 lookalikes so a one-glyph OCR miss still exact-matches."""
    out: list[str] = []
    seen: set[str] = set()

    def add(plate: str) -> None:
        key = compact_plate(plate)
        if key and key not in seen:
            seen.add(key)
            out.append(key)

    for raw in plates:
        seed = compact_plate(raw)
        if not seed:
            continue
        add(seed)
        chars = list(seed)
        for i, ch in enumerate(chars):
            for alt in _PLATE_CONFUSION.get(ch, ""):
                chars[i] = alt
                add("".join(chars))
                if max_subs >= 2:
                    for j in range(i + 1, len(chars)):
                        for alt2 in _PLATE_CONFUSION.get(chars[j], ""):
                            orig = chars[j]
                            chars[j] = alt2
                            add("".join(chars))
                            chars[j] = orig
                chars[i] = ch
    return out


def plate_ocr_bin(site_root: pathlib.Path | None) -> pathlib.Path | None:
    if not site_root:
        return None
    for rel in ("data/bin/plate-ocr", "bin/plate-ocr"):
        path = site_root / rel
        if path.is_file() and os.access(path, os.X_OK):
            return path
    return None


def ocr_engine_status(site_root: pathlib.Path | None = None) -> dict[str, Any]:
    rust = plate_ocr_bin(site_root)
    return {
        "tesseract": bool(shutil.which("tesseract")),
        "rust": bool(rust),
    }


def ocr_plate_image(
    raw: bytes,
    *,
    site_root: pathlib.Path | None = None,
    engines: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Read a plate photo. Honours enabled engines: native `plate-ocr`, then Tesseract CLI."""
    if not raw:
        raise ValueError("No plate image")
    if len(raw) > OCR_IMAGE_MAX:
        raise ValueError("Plate photo is too large")
    opts = engines or {}
    want_rust = bool(opts.get("rust", True))
    want_server = bool(opts.get("server", True))
    rust = plate_ocr_bin(site_root) if want_rust else None
    if rust:
        try:
            proc = subprocess.run(
                [str(rust)],
                input=raw,
                capture_output=True,
                timeout=8,
                check=False,
            )
            if proc.returncode == 0 and proc.stdout:
                data = json.loads(proc.stdout.decode("utf-8", errors="replace"))
                cands = extract_plates_from_ocr_text(" ".join(
                    str(x) for x in (data.get("candidates") or [])
                ) + " " + str(data.get("text") or ""))
                if not cands:
                    cands = [compact_plate(str(x)) for x in (data.get("candidates") or []) if compact_plate(str(x))]
                if cands:
                    return {
                        "engine": str(data.get("engine") or "rust"),
                        "candidates": cands,
                        "text": str(data.get("text") or ""),
                    }
        except (OSError, json.JSONDecodeError, subprocess.TimeoutExpired, ValueError, TypeError) as exc:
            log.warning("native plate-ocr failed: %s", exc)
        except Exception:
            log.exception("native plate-ocr crashed")
    if want_server:
        try:
            return _ocr_plate_tesseract(raw)
        except Exception:
            log.exception("tesseract plate-ocr failed")
    return {"engine": "none", "candidates": [], "text": ""}


def _ocr_plate_tesseract(raw: bytes) -> dict[str, Any]:
    tess = shutil.which("tesseract")
    if not tess:
        return {"engine": "none", "candidates": [], "text": ""}
    try:
        from PIL import Image, ImageEnhance, ImageFilter, ImageOps
    except ImportError:
        return {"engine": "none", "candidates": [], "text": ""}
    try:
        img = Image.open(BytesIO(raw))
        img.load()
        img = ImageOps.exif_transpose(img)
    except Exception as exc:
        raise ValueError("Could not read that plate photo") from exc
    if img.mode != "RGB":
        img = img.convert("RGB")
    crops = _plate_ocr_crops(img)
    texts: list[str] = []
    try:
        with tempfile.TemporaryDirectory(prefix="plate-ocr-") as tmp:
            tmp_path = pathlib.Path(tmp)
            for idx, crop in enumerate(crops):
                path = tmp_path / f"p{idx}.png"
                crop.save(path, "PNG")
                for psm in ("7", "8"):
                    proc = subprocess.run(
                        [
                            tess,
                            str(path),
                            "stdout",
                            "--psm",
                            psm,
                            "-l",
                            "eng",
                            "-c",
                            "tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
                        ],
                        capture_output=True,
                        timeout=6,
                        check=False,
                    )
                    text = (proc.stdout or b"").decode("utf-8", errors="replace")
                    if text.strip():
                        texts.append(text)
    except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
        log.warning("tesseract CLI failed: %s", exc)
    blob = " ".join(texts)
    return {
        "engine": "tesseract",
        "candidates": extract_plates_from_ocr_text(blob),
        "text": blob[:400],
    }


def _plate_ocr_crops(img: Any) -> list[Any]:
    """Plate-shaped bands plus a contrast/inverted pair. Pillow Image in, Image out."""
    from PIL import Image, ImageEnhance, ImageFilter, ImageOps

    w, h = img.size
    if w < 40 or h < 20:
        return [img]
    resample = Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS
    bands: list[Any] = []
    # Wide close-up of the plate, or a car photo with the plate in the lower half.
    rels = [(0.0, 1.0)] if h / max(1, w) < 0.45 else [(0.35, 0.45), (0.15, 0.4), (0.5, 0.4)]
    for top_frac, height_frac in rels:
        top = int(h * top_frac)
        band_h = max(32, int(h * height_frac))
        if top + band_h > h:
            top = max(0, h - band_h)
        crop = img.crop((0, top, w, top + band_h))
        target_h = 140
        scale = target_h / max(1, crop.size[1])
        crop = crop.resize((max(80, int(crop.size[0] * scale)), target_h), resample)
        gray = ImageOps.grayscale(crop)
        gray = ImageOps.autocontrast(gray)
        gray = gray.filter(ImageFilter.SHARPEN)
        bands.append(gray)
        bands.append(ImageOps.invert(gray))
        bands.append(ImageEnhance.Contrast(gray).enhance(2.2))
        if len(bands) >= 8:
            break
    return bands[:8]


def normalize_colour(raw: str | None) -> str:
    return re.sub(r"\s+", " ", (raw or "").strip())[:40]


def normalize_visitor(raw: str | None) -> str:
    return re.sub(r"\s+", " ", (raw or "").strip())[:80]


def normalize_vehicle_type(raw: str | None) -> str:
    key = (raw or "car").strip().lower()
    return key if key in VEHICLE_TYPES else "car"


def normalize_kind(raw: str | None) -> str:
    key = (raw or KIND_VISITOR).strip().lower()
    if key in ("member", "resident", "permanent", "own"):
        return KIND_MEMBER
    if key in ("tenant", "tenants", "renter", "lessee"):
        return KIND_TENANT
    if key in ("staff", "household-staff", "househelp", "house-help", "domestic"):
        return KIND_STAFF
    if key in ("adhoc", "ad-hoc", "gate", "hawker", "labour", "labor"):
        return KIND_ADHOC
    return KIND_VISITOR


def normalize_adhoc_category(raw: str | None) -> str:
    key = (raw or "other").strip().lower()
    aliases = {
        "labor": "labour",
        "domestic": "maid",
        "househelp": "maid",
        "house-help": "maid",
        "chef": "cook",
    }
    key = aliases.get(key, key)
    return key if key in ADHOC_CATEGORIES else "other"


def normalize_staff_category(raw: str | None) -> str:
    key = (raw or "other").strip().lower()
    aliases = {
        "domestic": "maid",
        "househelp": "maid",
        "house-help": "maid",
        "helper": "maid",
        "chef": "cook",
        "mali": "gardener",
        "garden": "gardener",
        "watchman": "caretaker",
        "guard": "caretaker",
        "chowkidar": "caretaker",
    }
    key = aliases.get(key, key)
    return key if key in STAFF_CATEGORIES else "other"


def is_identity_kind(kind: str | None) -> bool:
    return (kind or "").strip().lower() in IDENTITY_KINDS


def _adhoc_hours_from_payload(payload: dict | None) -> int:
    raw = (payload or {}).get("hours") or (payload or {}).get("leaseHours") or DEFAULT_ADHOC_HOURS
    try:
        n = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("Choose a duration between 1 and 9 hours") from exc
    if n not in ALLOWED_ADHOC_HOURS:
        raise ValueError("Ad-hoc pass duration must be between 1 and 9 hours")
    return n


def _meta_int(conn: sqlite3.Connection, key: str, default: int) -> int:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    if not row:
        return default
    try:
        n = int(str(row["value"] if isinstance(row, sqlite3.Row) else row[0]).strip())
    except (TypeError, ValueError):
        return default
    return n


def _meta_bool(conn: sqlite3.Connection, key: str, default: bool) -> bool:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    if not row:
        return default
    val = str(row["value"] if isinstance(row, sqlite3.Row) else row[0]).strip().lower()
    if val in ("1", "true", "yes", "on"):
        return True
    if val in ("0", "false", "no", "off"):
        return False
    return default


def ocr_settings(conn: sqlite3.Connection, site_root: pathlib.Path | None = None) -> dict[str, Any]:
    flags = {
        "phone": _meta_bool(conn, META_OCR_PHONE, OCR_SETTING_DEFAULTS["phone"]),
        "live": _meta_bool(conn, META_OCR_LIVE, OCR_SETTING_DEFAULTS["live"]),
        "fuzzy": _meta_bool(conn, META_OCR_FUZZY, OCR_SETTING_DEFAULTS["fuzzy"]),
        "server": _meta_bool(conn, META_OCR_SERVER, OCR_SETTING_DEFAULTS["server"]),
        "rust": _meta_bool(conn, META_OCR_RUST, OCR_SETTING_DEFAULTS["rust"]),
    }
    flags["engines"] = ocr_engine_status(site_root)
    return flags


def set_ocr_settings(
    conn: sqlite3.Connection,
    payload: dict | None,
    *,
    actor: dict | None = None,
    site_root: pathlib.Path | None = None,
) -> dict[str, Any]:
    del actor
    data = payload if isinstance(payload, dict) else {}
    mapping = {
        "phone": META_OCR_PHONE,
        "live": META_OCR_LIVE,
        "fuzzy": META_OCR_FUZZY,
        "server": META_OCR_SERVER,
        "rust": META_OCR_RUST,
    }
    for flag, key in mapping.items():
        if flag not in data:
            continue
        raw = data[flag]
        on = raw in (True, 1, "1", "true", "yes", "on")
        conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)", (key, "1" if on else "0"))
    conn.commit()
    return ocr_settings(conn, site_root)


def default_hours(conn: sqlite3.Connection) -> int:
    n = _meta_int(conn, META_DEFAULT_HOURS, DEFAULT_HOURS)
    return n if n in ALLOWED_HOURS else DEFAULT_HOURS


def set_default_hours(conn: sqlite3.Connection, hours: int, *, actor: dict) -> int:
    n = int(hours)
    if n not in ALLOWED_HOURS:
        raise ValueError("Lease duration must be 4, 8, 12, or 24 hours")
    conn.execute(
        "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
        (META_DEFAULT_HOURS, str(n)),
    )
    conn.commit()
    return n


def settings(conn: sqlite3.Connection, site_root: pathlib.Path | None = None) -> dict[str, Any]:
    ensure_parking_passes_table(conn)
    hours = default_hours(conn)
    return {
        "defaultHours": hours,
        "allowedHours": list(ALLOWED_HOURS),
        "defaultMonths": DEFAULT_MONTHS,
        "allowedMonths": list(ALLOWED_MONTHS),
        "adhocHours": list(ALLOWED_ADHOC_HOURS),
        "defaultAdhocHours": DEFAULT_ADHOC_HOURS,
        "adhocCategories": [{"id": k, "label": v} for k, v in ADHOC_CATEGORIES.items()],
        "staffCategories": [{"id": k, "label": v} for k, v in STAFF_CATEGORIES.items()],
        "staffMonths": list(ALLOWED_MONTHS),
        "defaultStaffMonths": DEFAULT_STAFF_MONTHS,
        "maxStaffPerPlot": STAFF_MAX_ACTIVE,
        "gatePassUrl": gate_pass_public_url(),
        "vehicleTypes": [{"id": k, "label": VEHICLE_LABELS[k]} for k in VEHICLE_TYPES if k != "foot"],
        "walletEnabled": _wallet_configured(),
        "googleWalletEnabled": _google_wallet_configured(),
        "ocr": ocr_settings(conn, site_root),
    }


def _wallet_configured() -> bool:
    try:
        import rwa_wallet
        return bool(rwa_wallet.is_configured())
    except Exception:
        return False


def _google_wallet_configured() -> bool:
    try:
        import rwa_wallet
        return bool(rwa_wallet.is_google_configured())
    except Exception:
        return False


def gate_pass_public_url(site_root: pathlib.Path | None = None) -> str:
    return f"{public_origin(site_root).rstrip('/')}/gate-pass.html#needs"


def gate_qr_png(site_root: pathlib.Path | None = None) -> bytes:
    return rwa_attest.qr_png_bytes(gate_pass_public_url(site_root), box_size=12, border=2) or b""


def adhoc_photo_dir(site_root: pathlib.Path) -> pathlib.Path:
    path = pathlib.Path(site_root) / "data" / "parking-adhoc"
    path.mkdir(parents=True, exist_ok=True)
    return path


def adhoc_photo_path(site_root: pathlib.Path, filename: str | None) -> pathlib.Path | None:
    if not filename:
        return None
    name = pathlib.Path(str(filename)).name
    if name != str(filename) or ".." in name or "/" in name or "\\" in name:
        return None
    if not re.fullmatch(r"(adhoc|staff)_[A-Za-z0-9_-]+\.webp", name):
        return None
    path = adhoc_photo_dir(site_root) / name
    return path if path.is_file() else None


def _optimize_adhoc_photo(raw: bytes) -> bytes:
    try:
        from PIL import Image, ImageOps
    except ImportError as exc:  # pragma: no cover
        raise ValueError("Image processing unavailable on server") from exc
    try:
        img = Image.open(BytesIO(raw))
        img.load()
        img = ImageOps.exif_transpose(img) or img
    except Exception as exc:
        raise ValueError("Could not read the selfie. Retake and try again.") from exc
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGBA") if "A" in img.getbands() else img.convert("RGB")
    w, h = img.size
    if w <= 0 or h <= 0:
        raise ValueError("Invalid selfie")
    side = min(w, h)
    left = (w - side) // 2
    top = (h - side) // 2
    img = img.crop((left, top, left + side, top + side))
    resample = Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS
    if side != ADHOC_PHOTO_SIZE:
        img = img.resize((ADHOC_PHOTO_SIZE, ADHOC_PHOTO_SIZE), resample)
    if img.mode == "RGBA":
        background = Image.new("RGB", img.size, (246, 241, 230))
        background.paste(img, mask=img.split()[-1])
        img = background
    else:
        img = img.convert("RGB")
    out = BytesIO()
    img.save(out, format="WEBP", quality=72, method=6)
    data = out.getvalue()
    if not data:
        raise ValueError("Could not save selfie")
    return data


def save_pass_photo(site_root: pathlib.Path, pass_id: str, raw: bytes, *, prefix: str = "adhoc") -> str:
    if not raw:
        raise ValueError("Selfie is required")
    if len(raw) > ADHOC_PHOTO_MAX:
        raise ValueError("Selfie is too large. Retake at a lower quality.")
    tag = "staff" if prefix == "staff" else "adhoc"
    optimized = _optimize_adhoc_photo(raw)
    filename = f"{tag}_{pass_id.replace('pp_', '')}.webp"
    path = adhoc_photo_dir(site_root) / filename
    path.write_bytes(optimized)
    return filename


def save_adhoc_photo(site_root: pathlib.Path, pass_id: str, raw: bytes) -> str:
    return save_pass_photo(site_root, pass_id, raw, prefix="adhoc")


def _new_id() -> str:
    return "pp_" + secrets.token_hex(8)


def _new_code(conn: sqlite3.Connection, kind: str = KIND_VISITOR) -> str:
    prefix = {
        KIND_MEMBER: "MP-",
        KIND_TENANT: "TP-",
        KIND_ADHOC: "AP-",
        KIND_STAFF: "SP-",
    }.get(kind, "VP-")
    for _ in range(12):
        code = prefix + secrets.token_hex(3).upper()
        exists = conn.execute(
            "SELECT 1 FROM parking_passes WHERE public_code = ?",
            (code,),
        ).fetchone()
        if not exists:
            return code
    return prefix + secrets.token_hex(5).upper()


def expire_due_passes(conn: sqlite3.Connection) -> int:
    ensure_parking_passes_table(conn)
    now = utc_now()
    cur = conn.execute(
        """
        UPDATE parking_passes
        SET status = 'expired', updated_at = ?
        WHERE status = 'active'
          AND COALESCE(kind, 'visitor') != 'member'
          AND expires_at <= ?
          AND expires_at < '9000-01-01'
        """,
        (now, now),
    )
    if cur.rowcount:
        conn.commit()
    return int(cur.rowcount or 0)


def _add_event(
    conn: sqlite3.Connection,
    *,
    pass_id: str,
    action: str,
    actor: dict | None,
    note: str = "",
) -> None:
    conn.execute(
        """
        INSERT INTO parking_pass_events(
          id, pass_id, action, actor_house_id, actor_member_id, actor_name, note, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "pe_" + secrets.token_hex(8),
            pass_id,
            action,
            (actor or {}).get("houseId") or (actor or {}).get("house_id") or "",
            (actor or {}).get("memberId") or "",
            (actor or {}).get("name") or "",
            (note or "")[:400],
            utc_now(),
        ),
    )


def _row_pass(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if not row:
        return None
    data = dict(row)
    status = data.get("status") or "expired"
    kind = (data.get("kind") or KIND_VISITOR).strip().lower()
    if kind not in (KIND_MEMBER, KIND_VISITOR, KIND_TENANT, KIND_ADHOC, KIND_STAFF):
        kind = KIND_VISITOR
    permanent = kind == KIND_MEMBER
    tenant = kind == KIND_TENANT
    adhoc = kind == KIND_ADHOC
    staff = kind == KIND_STAFF
    expires_at = data.get("expires_at") or ""
    lease_months = int(data.get("lease_months") or 0)
    category = ""
    category_label = ""
    if adhoc:
        category = normalize_adhoc_category(data.get("tenant_note") or data.get("vehicle_type"))
        note_cat = (data.get("tenant_note") or "").strip().lower()
        if note_cat in ADHOC_CATEGORIES:
            category = note_cat
        category_label = ADHOC_CATEGORIES.get(category, "Ad-hoc")
        status_label = f"{int(data.get('lease_hours') or DEFAULT_ADHOC_HOURS)}h ad-hoc" if status == "active" else STATUS_LABELS.get(status, status.replace("_", " ").title())
    elif staff:
        category = normalize_staff_category(data.get("tenant_note"))
        category_label = STAFF_CATEGORIES.get(category, "Staff")
        status_label = (
            f"{lease_months or DEFAULT_STAFF_MONTHS} mo staff"
            if status == "active"
            else STATUS_LABELS.get(status, status.replace("_", " ").title())
        )
    elif permanent:
        status_label = "Permanent" if status == "active" else STATUS_LABELS.get(status, status.replace("_", " ").title())
    elif tenant and status == "active":
        status_label = f"{lease_months or DEFAULT_MONTHS} mo lease"
    else:
        status_label = STATUS_LABELS.get(status, status.replace("_", " ").title())
    photo_filename = data.get("photo_filename") or ""
    item = {
        "id": data.get("id"),
        "code": data.get("public_code") or "",
        "kind": kind,
        "kindLabel": KIND_LABELS.get(kind, "Visitor"),
        "permanent": permanent,
        "houseId": data.get("house_id") or "",
        "plotNo": "GATE" if adhoc else (data.get("plot_no") or data.get("house_id") or ""),
        "memberId": data.get("member_id") or "",
        "memberName": data.get("member_name") or "",
        "plate": data.get("plate") or "",
        "plateDisplay": data.get("plate_display") or data.get("plate") or "",
        "colour": data.get("colour") or "",
        "vehicleType": data.get("vehicle_type") or "car",
        "vehicleTypeLabel": VEHICLE_LABELS.get(data.get("vehicle_type") or "car", "Car"),
        "visitorName": data.get("visitor_name") or "",
        "tenantId": data.get("tenant_id") or "",
        "tenantName": (data.get("visitor_name") or "") if tenant else "",
        "tenantPhone": data.get("tenant_phone") or "",
        "tenantEmail": data.get("tenant_email") or "",
        "tenantNote": data.get("tenant_note") or "",
        "adhocCategory": category if adhoc else "",
        "adhocCategoryLabel": category_label if adhoc else "",
        "staffCategory": category if staff else "",
        "staffCategoryLabel": category_label if staff else "",
        "category": category if (adhoc or staff) else "",
        "categoryLabel": category_label if (adhoc or staff) else "",
        "leaseHours": 0 if permanent or tenant or staff else int(data.get("lease_hours") or (DEFAULT_ADHOC_HOURS if adhoc else DEFAULT_HOURS)),
        "leaseMonths": lease_months if (tenant or staff) else 0,
        "photoFilename": photo_filename,
        "hasPhoto": bool(photo_filename),
        "photoUrl": f"/api/rwa/parking/passes/{data.get('id')}/photo" if photo_filename else "",
        "cardPngUrl": f"/api/rwa/parking/passes/{data.get('id')}/card.png" if data.get("id") else "",
        "status": status,
        "statusLabel": status_label,
        "issuedAt": data.get("issued_at") or "",
        "issuedAtLabel": format_ist(data.get("issued_at")),
        "expiresAt": "" if permanent else expires_at,
        "expiresAtLabel": "Permanent" if permanent else format_ist(expires_at),
        "renewCount": int(data.get("renew_count") or 0),
        "lastRenewedAt": data.get("last_renewed_at") or "",
        "pendingRenewHours": int(data.get("pending_renew_hours") or 0),
        "pendingRenewAt": data.get("pending_renew_at") or "",
        "approvedByName": data.get("approved_by_name") or "",
        "revokedReason": data.get("revoked_reason") or "",
        "emailSent": bool(int(data.get("email_sent") or 0)),
        "createdAt": data.get("created_at") or "",
        "updatedAt": data.get("updated_at") or "",
        "canRenew": (not permanent) and (not adhoc) and status == "expired",
        "needsEcApproval": (not permanent) and (not adhoc) and (not staff) and status == "expired" and int(data.get("renew_count") or 0) >= 1,
        "canRemove": (permanent or staff) and status == "active",
        "verifyUrl": "",
    }
    item.update(_wallet_public_fields(item))
    return item


def _wallet_public_fields(item: dict[str, Any]) -> dict[str, Any]:
    try:
        import rwa_wallet
    except ImportError:
        return {"walletEnabled": False, "walletUrl": "", "googleWalletEnabled": False, "googleWalletUrl": ""}
    return rwa_wallet.public_fields(item)


def can_download_wallet(
    item: dict[str, Any] | None,
    actor: dict | None,
    *,
    code: str = "",
    can_manage: bool = False,
    can_general: bool = False,
) -> bool:
    """Owner plot, pass staff, or possession of the public pass code."""
    if not item:
        return False
    if str(item.get("status") or "") not in ("active", "pending_renewal"):
        return False
    pub = str(item.get("code") or "").strip().upper()
    offered = (code or "").strip().upper()
    if pub and offered and pub == offered:
        return True
    if can_manage or can_general:
        return True
    actor_house = str((actor or {}).get("houseId") or (actor or {}).get("house_id") or "").strip()
    pass_house = str(item.get("houseId") or item.get("house_id") or "").strip()
    return bool(actor_house and pass_house and actor_house == pass_house)


def can_export_card(
    item: dict[str, Any] | None,
    actor: dict | None,
    *,
    code: str = "",
    can_manage: bool = False,
    can_general: bool = False,
) -> bool:
    """Owner plot, pass desk, or possession of the public pass code — any status."""
    if not item:
        return False
    pub = str(item.get("code") or "").strip().upper()
    offered = (code or "").strip().upper()
    if pub and offered and pub == offered:
        return True
    if can_manage or can_general:
        return True
    actor_house = str((actor or {}).get("houseId") or (actor or {}).get("house_id") or "").strip()
    pass_house = str(item.get("houseId") or item.get("house_id") or "").strip()
    return bool(actor_house and pass_house and actor_house == pass_house)


# Match .parking-card CSS (22.6rem × 1.586, 16px rem) at 3× for a sharp PNG.
_CARD_SCALE = 3
_CARD_REM = 16 * _CARD_SCALE
_CARD_THEMES = {
    "member": {
        "stops": ((58, 46, 22), (26, 39, 68), (14, 24, 44)),
        "glow": ((232, 213, 154, 97), (1.0, 0.0)),
        "accent": (232, 213, 154),
        "chip": ((243, 230, 184), (196, 161, 90), (141, 107, 46)),
        "badge": (196, 161, 90),
        "badge_fg": (21, 35, 63),
        "stripe": ((58, 46, 22), (196, 161, 90), (26, 20, 8)),
    },
    "tenant": {
        "stops": ((30, 61, 42), (20, 51, 34), (11, 31, 22)),
        "glow": ((146, 196, 150, 82), (0.0, 1.0)),
        "accent": (183, 221, 184),
        "chip": ((207, 232, 208), (90, 154, 98), (45, 92, 54)),
        "badge": (77, 143, 87),
        "badge_fg": (246, 241, 230),
        "stripe": ((20, 51, 34), (90, 154, 98), (11, 31, 22)),
    },
    "visitor": {
        "stops": ((90, 42, 28), (61, 28, 24), (28, 16, 16)),
        "glow": ((232, 168, 124, 87), (0.0, 0.0)),
        "accent": (240, 196, 168),
        "chip": ((243, 208, 184), (196, 106, 58), (138, 61, 34)),
        "badge": (196, 106, 58),
        "badge_fg": (255, 248, 242),
        "stripe": ((61, 28, 24), (196, 106, 58), (28, 16, 16)),
    },
    "adhoc": {
        "stops": ((58, 52, 40), (37, 32, 24), (20, 17, 13)),
        "glow": ((212, 175, 90, 71), (1.0, 1.0)),
        "accent": (232, 212, 160),
        "chip": ((239, 224, 184), (184, 146, 63), (111, 85, 32)),
        "badge": (184, 146, 63),
        "badge_fg": (26, 21, 12),
        "stripe": ((42, 36, 24), (184, 146, 63), (20, 17, 13)),
    },
    "staff": {
        "stops": ((58, 42, 72), (36, 24, 48), (20, 14, 28)),
        "glow": ((196, 168, 220, 82), (1.0, 1.0)),
        "accent": (212, 184, 232),
        "chip": ((234, 214, 244), (122, 90, 158), (61, 42, 82)),
        "badge": (122, 90, 158),
        "badge_fg": (246, 241, 230),
        "stripe": ((36, 24, 48), (122, 90, 158), (20, 14, 28)),
    },
}


def _card_font(size: int, *, bold: bool = False, serif: bool = False):
    from PIL import ImageFont

    if serif:
        files = (
            ["DejaVuSerif-Bold.ttf", "LiberationSerif-Bold.ttf", "Georgia Bold.ttf", "Times New Roman.ttf"]
            if bold
            else ["DejaVuSerif.ttf", "LiberationSerif-Regular.ttf", "Georgia.ttf"]
        )
    else:
        files = (
            ["DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf", "Arial Bold.ttf", "Arial.ttf"]
            if bold
            else ["DejaVuSans.ttf", "LiberationSans-Regular.ttf", "Arial.ttf"]
        )
    roots = (
        "/usr/share/fonts/truetype/dejavu",
        "/usr/share/fonts/truetype/liberation",
        "/usr/share/fonts/truetype/liberation2",
        "/System/Library/Fonts/Supplemental",
        "/Library/Fonts",
    )
    for root in roots:
        for name in files:
            path = pathlib.Path(root) / name
            if path.is_file():
                return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default()


def _lerp_rgb(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    t = max(0.0, min(1.0, t))
    return (
        int(a[0] + (b[0] - a[0]) * t),
        int(a[1] + (b[1] - a[1]) * t),
        int(a[2] + (b[2] - a[2]) * t),
    )


def _card_gradient(size: tuple[int, int], stops: tuple[tuple[int, int, int], ...]) -> Any:
    """CSS linear-gradient(145deg, c1 0%, c2 42%, c3 100%)."""
    from PIL import Image
    import math

    w, h = size
    tiny_w, tiny_h = max(2, w // 4), max(2, h // 4)
    img = Image.new("RGB", (tiny_w, tiny_h))
    pix = img.load()
    c1, c2, c3 = stops
    ang = math.radians(145)
    dx, dy = math.sin(ang), -math.cos(ang)
    min_p = max_p = None
    corners = ((0, 0), (tiny_w - 1, 0), (0, tiny_h - 1), (tiny_w - 1, tiny_h - 1))
    for cx, cy in corners:
        p = cx * dx + cy * dy
        min_p = p if min_p is None else min(min_p, p)
        max_p = p if max_p is None else max(max_p, p)
    span = max(1e-6, (max_p or 1) - (min_p or 0))
    for y in range(tiny_h):
        for x in range(tiny_w):
            t = ((x * dx + y * dy) - (min_p or 0)) / span
            if t < 0.42:
                colour = _lerp_rgb(c1, c2, t / 0.42)
            else:
                colour = _lerp_rgb(c2, c3, (t - 0.42) / 0.58)
            pix[x, y] = colour
    return img.resize(size, Image.Resampling.LANCZOS)


def _card_glow(size: tuple[int, int], colour: tuple[int, int, int, int], origin: tuple[float, float]) -> Any:
    from PIL import Image

    w, h = size
    overlay = Image.new("RGBA", size, (0, 0, 0, 0))
    pix = overlay.load()
    ox, oy = origin[0] * (w - 1), origin[1] * (h - 1)
    rx, ry = w * 1.2, h * 0.8
    cr, cg, cb, ca = colour
    step = 3
    for y in range(0, h, step):
        for x in range(0, w, step):
            nx = (x - ox) / max(1, rx)
            ny = (y - oy) / max(1, ry)
            d = (nx * nx + ny * ny) ** 0.5
            if d >= 0.48:
                continue
            alpha = int(ca * (1.0 - d / 0.48))
            if alpha <= 0:
                continue
            for yy in range(y, min(h, y + step)):
                for xx in range(x, min(w, x + step)):
                    pix[xx, yy] = (cr, cg, cb, alpha)
    return overlay


def _circle_face(path: pathlib.Path, size: int) -> Any:
    from PIL import Image, ImageDraw, ImageOps

    src = Image.open(path)
    src = ImageOps.exif_transpose(src) or src
    src = ImageOps.fit(src.convert("RGBA"), (size, size), Image.Resampling.LANCZOS)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((1, 1, size - 2, size - 2), fill=255)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(src, (0, 0), mask)
    return out


def _text_width(draw: Any, text: str, font: Any, tracking: float = 0) -> float:
    if not text:
        return 0.0
    if tracking:
        return sum(draw.textlength(ch, font=font) + (tracking if i else 0) for i, ch in enumerate(text))
    return float(draw.textlength(text, font=font))


def _fit_text(draw: Any, text: str, font: Any, max_width: int, tracking: float = 0) -> str:
    raw = re.sub(r"\s+", " ", (text or "").strip())
    if not raw:
        return ""
    if _text_width(draw, raw, font, tracking) <= max_width:
        return raw
    while raw and _text_width(draw, raw + "…", font, tracking) > max_width:
        raw = raw[:-1]
    return (raw + "…") if raw else ""


def _draw_text(
    draw: Any,
    xy: tuple[int, int],
    text: str,
    *,
    font: Any,
    fill: tuple[int, int, int, int],
    tracking: float = 0,
) -> None:
    x, y = xy
    if not tracking:
        draw.text((x, y), text, fill=fill, font=font)
        return
    for ch in text:
        draw.text((x, y), ch, fill=fill, font=font)
        x += draw.textlength(ch, font=font) + tracking


def render_pass_card_png(
    item: dict[str, Any],
    *,
    site_root: pathlib.Path,
    photo_path: pathlib.Path | None = None,
) -> bytes:
    """Plastic pass card as PNG — same layout as .parking-card, transparent outside."""
    from PIL import Image, ImageChops, ImageDraw

    s = _CARD_SCALE
    rem = _CARD_REM
    width = round(22.6 * rem)
    height = round(width / 1.586)
    radius = 18 * s
    pad_x = 1 * rem
    pad_top = round(0.85 * rem)
    pad_bot = round(0.9 * rem)
    stripe_h = 22 * s
    stripe_mb = round(0.55 * rem)
    chip_w, chip_h, chip_r = 34 * s, 26 * s, 6 * s
    qr_s, qr_pad, qr_r = 64 * s, 3 * s, 8 * s
    face_s = round(2.85 * rem)
    face_gap = round(0.85 * rem)
    badge_top = round(2.35 * rem)
    badge_right = round(0.85 * rem)
    badge_pad_y = round(0.18 * rem)
    badge_pad_x = round(0.45 * rem)

    kind = str(item.get("kind") or "visitor")
    theme = _CARD_THEMES.get(kind, _CARD_THEMES["visitor"])
    identity = is_identity_kind(kind)
    status = str(item.get("status") or "")

    body = _card_gradient((width, height), theme["stops"]).convert("RGBA")
    glow_colour, glow_origin = theme["glow"]
    body = Image.alpha_composite(body, _card_glow((width, height), glow_colour, glow_origin))
    draw = ImageDraw.Draw(body)

    # Magstripe sits inside top padding (CSS margin: 0 -1rem), not flush to the rounded edge.
    stripe_y = pad_top
    unit_a, unit_b, unit_c = 10 * s, 2 * s, 10 * s
    x = 0
    while x < width:
        draw.rectangle((x, stripe_y, x + unit_a, stripe_y + stripe_h), fill=theme["stripe"][0] + (255,))
        draw.rectangle((x + unit_a, stripe_y, x + unit_a + unit_b, stripe_y + stripe_h), fill=theme["stripe"][1] + (255,))
        draw.rectangle(
            (x + unit_a + unit_b, stripe_y, x + unit_a + unit_b + unit_c, stripe_y + stripe_h),
            fill=theme["stripe"][2] + (255,),
        )
        x += unit_a + unit_b + unit_c

    top_y = pad_top + stripe_h + stripe_mb
    brand_font = _card_font(round(0.62 * rem), bold=True)
    title_font = _card_font(round(1.05 * rem), bold=True, serif=True)
    plate_font = _card_font(round(1.45 * rem), bold=True)
    meta_font = _card_font(round(0.72 * rem))
    strong_font = _card_font(round(0.78 * rem), bold=True)
    badge_font = _card_font(round(0.62 * rem), bold=True)

    cream = (246, 241, 230, 255)
    cream_dim = (246, 241, 230, 209)
    plate_fill = (255, 248, 232, 255)

    brand = "HIMUDA HOUSING COLONY SANYARD"
    brand_track = 0.16 * (0.62 * rem)
    _draw_text(draw, (pad_x, top_y), brand, font=brand_font, fill=theme["accent"] + (255,), tracking=brand_track)

    title = str(item.get("kindLabel") or "Pass")
    title_y = top_y + round(0.62 * rem + 0.1 * rem)
    _draw_text(draw, (pad_x, title_y), title, font=title_font, fill=cream)
    title_w = int(draw.textlength(title, font=title_font))
    title_row_h = round(0.62 * rem + 0.1 * rem + 1.05 * rem)

    if identity and photo_path and photo_path.is_file():
        try:
            face = _circle_face(photo_path, face_s)
            ring_s = face_s + 4 * s
            ring = Image.new("RGBA", (ring_s, ring_s), (0, 0, 0, 0))
            ImageDraw.Draw(ring).ellipse((0, 0, ring_s - 1, ring_s - 1), outline=(255, 255, 255, 140), width=2 * s)
            ring.paste(face, (2 * s, 2 * s), face)
            face_x = pad_x + title_w + face_gap
            face_y = title_y + (round(1.05 * rem) - face_s) // 2
            body.paste(ring, (face_x, face_y), ring)
            title_row_h = max(title_row_h, (face_y - top_y) + ring_s)
        except OSError:
            pass

    chip = Image.new("RGBA", (chip_w, chip_h), (0, 0, 0, 0))
    cd = ImageDraw.Draw(chip)
    cd.rounded_rectangle((0, 0, chip_w - 1, chip_h - 1), radius=chip_r, fill=theme["chip"][1] + (255,))
    cd.rounded_rectangle((2 * s, 2 * s, chip_w - 1 - 2 * s, chip_h - 1 - 2 * s), radius=max(2, chip_r - 2), fill=theme["chip"][0] + (255,))
    body.alpha_composite(chip, (width - pad_x - chip_w, top_y))

    badge = str(item.get("statusLabel") or status or "").upper()
    if badge:
        badge_fill = theme["badge"]
        badge_fg = theme["badge_fg"]
        if status == "expired":
            badge_fill, badge_fg = (90, 90, 90), (255, 255, 255)
        elif status == "revoked":
            badge_fill, badge_fg = (155, 44, 44), (255, 255, 255)
        elif status == "pending_renewal":
            badge_fill, badge_fg = (158, 125, 58), (255, 255, 255)
        badge_track = 0.08 * (0.62 * rem)
        tw = _text_width(draw, badge, badge_font, badge_track)
        bw = int(tw + badge_pad_x * 2)
        bh = int(round(0.62 * rem) + badge_pad_y * 2)
        bx = width - badge_right - bw
        by = badge_top
        draw.rounded_rectangle((bx, by, bx + bw, by + bh), radius=bh // 2, fill=badge_fill + (255,))
        _draw_text(
            draw,
            (bx + badge_pad_x, by + badge_pad_y),
            badge,
            font=badge_font,
            fill=badge_fg + (255,),
            tracking=badge_track,
        )

    if identity:
        plate = str(
            item.get("categoryLabel")
            or item.get("staffCategoryLabel")
            or item.get("adhocCategoryLabel")
            or item.get("kindLabel")
            or ""
        )
    else:
        plate = str(item.get("plateDisplay") or item.get("plate") or "")
    who = str(item.get("tenantName") or item.get("visitorName") or item.get("memberName") or "—")
    plot = "Main gate" if kind == "adhoc" else f"Plot {item.get('plotNo') or item.get('houseId') or ''}"
    if not identity:
        extras = " · ".join(
            part for part in (item.get("vehicleTypeLabel") or "", item.get("colour") or "") if part
        )
        if extras:
            plot = f"{plot} · {extras}"
    valid = "Permanent" if item.get("permanent") else (item.get("expiresAtLabel") or "—")
    code = str(item.get("code") or "")
    meta_lines = [
        (who or "—", strong_font, cream, 0),
        (plot, meta_font, cream_dim, 0),
        (f"Valid {valid}", meta_font, cream_dim, 0),
        (code, meta_font, cream_dim, 0),
    ]
    line_gap = round(0.12 * rem)
    meta_text_h = round(0.78 * rem + 0.72 * rem * 3 + line_gap * 3)
    qr_box = qr_s + qr_pad * 2
    meta_h = max(meta_text_h, qr_box)
    meta_y = height - pad_bot - meta_h
    text_max = width - pad_x * 2 - qr_box - round(0.7 * rem)

    y = meta_y + (meta_h - meta_text_h)
    for text, font, fill, track in meta_lines:
        line = _fit_text(draw, text, font, text_max, track)
        _draw_text(draw, (pad_x, y), line, font=font, fill=fill, tracking=track)
        bbox = font.getbbox(line or " ")
        y += (bbox[3] - bbox[1]) + line_gap

    plate_track = 0.14 * (1.45 * rem)
    plate = _fit_text(draw, plate, plate_font, width - pad_x * 2 - round(0.4 * rem), plate_track)
    plate_h = round(1.45 * rem)
    plate_area_top = top_y + title_row_h
    plate_y = plate_area_top + max(0, (meta_y - plate_area_top - plate_h) // 2)
    _draw_text(draw, (pad_x, plate_y), plate, font=plate_font, fill=plate_fill, tracking=plate_track)

    origin = public_origin(site_root)
    verify = item.get("verifyUrl") or (f"{origin}/#parking?pass={code}" if code else origin)
    qr_png = rwa_attest.qr_png_bytes(str(verify), box_size=8, border=2)
    if qr_png:
        inner = qr_s
        outer = qr_box
        qr = Image.open(BytesIO(qr_png)).convert("RGBA").resize((inner, inner), Image.Resampling.NEAREST)
        rounded = Image.new("L", (outer, outer), 0)
        ImageDraw.Draw(rounded).rounded_rectangle((0, 0, outer - 1, outer - 1), radius=qr_r, fill=255)
        white = Image.new("RGBA", (outer, outer), (255, 255, 255, 255))
        white.putalpha(rounded)
        white.paste(qr, (qr_pad, qr_pad), qr)
        body.alpha_composite(white, (width - pad_x - outer, height - pad_bot - outer))

    sheen = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    sp = sheen.load()
    for y in range(0, height, 2):
        for x in range(0, width, 2):
            t = (x * 0.55 + y * 0.84) / max(1, width)
            if 0.40 <= t <= 0.60:
                a = int(20 * (1.0 - abs(t - 0.50) / 0.10))
                if a > 0:
                    for yy in range(y, min(height, y + 2)):
                        for xx in range(x, min(width, x + 2)):
                            sp[xx, yy] = (255, 255, 255, a)
    body = Image.alpha_composite(body, sheen)

    mask = Image.new("L", (width, height), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, width - 1, height - 1), radius=radius, fill=255)
    r, g, b, a = body.split()
    card = Image.merge("RGBA", (r, g, b, ImageChops.multiply(a, mask)))
    # Keep the rounded top off the bitmap edge so viewers don't clip the stripe / corners.
    margin = 8 * s
    out = Image.new("RGBA", (width + margin * 2, height + margin * 2), (0, 0, 0, 0))
    out.paste(card, (margin, margin), card)
    buf = BytesIO()
    out.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _attach_qr(item: dict[str, Any], site_root: pathlib.Path | None) -> dict[str, Any]:
    origin = public_origin(site_root)
    code = item.get("code") or ""
    url = f"{origin}/#parking?pass={code}" if code else origin
    item["verifyUrl"] = url
    png = rwa_attest.qr_png_bytes(url, box_size=5, border=2)
    if png:
        item["qrDataUrl"] = "data:image/png;base64," + base64.b64encode(png).decode("ascii")
    else:
        item["qrDataUrl"] = ""
    return item


def get_pass(
    conn: sqlite3.Connection,
    pass_id: str,
    *,
    site_root: pathlib.Path | None = None,
    with_qr: bool = False,
) -> dict[str, Any] | None:
    ensure_parking_passes_table(conn)
    expire_due_passes(conn)
    row = conn.execute(
        """
        SELECT p.*, r.plot_no
        FROM parking_passes p
        LEFT JOIN residents r ON r.house_id = p.house_id
        WHERE p.id = ? OR p.public_code = ?
        """,
        ((pass_id or "").strip(), (pass_id or "").strip()),
    ).fetchone()
    item = _row_pass(row)
    if item and with_qr:
        _attach_qr(item, site_root)
    return item


def list_passes(
    conn: sqlite3.Connection,
    *,
    house_id: str,
    site_root: pathlib.Path | None = None,
    limit: int = 40,
) -> list[dict[str, Any]]:
    ensure_parking_passes_table(conn)
    expire_due_passes(conn)
    hid = (house_id or "").strip()
    if not hid:
        return []
    lim = max(1, min(int(limit or 40), 100))
    rows = conn.execute(
        """
        SELECT p.*, r.plot_no
        FROM parking_passes p
        LEFT JOIN residents r ON r.house_id = p.house_id
        WHERE p.house_id = ?
        ORDER BY
          CASE
            WHEN COALESCE(p.kind, 'visitor') = 'member' AND p.status = 'active' THEN 0
            WHEN COALESCE(p.kind, 'visitor') = 'tenant' AND p.status = 'active' THEN 1
            WHEN COALESCE(p.kind, 'visitor') = 'staff' AND p.status = 'active' THEN 2
            WHEN p.status = 'active' THEN 3
            WHEN p.status = 'pending_renewal' THEN 4
            ELSE 5
          END,
          p.created_at DESC
        LIMIT ?
        """,
        (hid, lim),
    ).fetchall()
    out = []
    for row in rows:
        item = _row_pass(row)
        if item:
            _attach_qr(item, site_root)
            out.append(item)
    return out


def list_passes_for_report(
    conn: sqlite3.Connection,
    *,
    kinds: list[str] | None = None,
    status: str | None = None,
    house_ids: list[str] | None = None,
    exclude_foot: bool = False,
    limit: int = 3000,
) -> list[dict[str, Any]]:
    """Colony-wide pass rows for EC reports (no QR blobs)."""
    ensure_parking_passes_table(conn)
    expire_due_passes(conn)
    lim = max(1, min(int(limit or 3000), 5000))
    clauses: list[str] = []
    args: list[Any] = []
    if kinds:
        mapped: list[str] = []
        for raw in kinds:
            key = str(raw or "").strip().lower()
            if key in (KIND_MEMBER, KIND_VISITOR, KIND_TENANT, KIND_ADHOC, KIND_STAFF):
                mapped.append(key)
            elif key in ("ad-hoc", "gate"):
                mapped.append(KIND_ADHOC)
            elif key in ("household-staff", "househelp"):
                mapped.append(KIND_STAFF)
        if mapped:
            clauses.append(f"COALESCE(p.kind, 'visitor') IN ({','.join('?' for _ in mapped)})")
            args.extend(mapped)
    st = (status or "all").strip().lower()
    if st and st != "all":
        clauses.append("p.status = ?")
        args.append(st)
    ids = [str(h).strip() for h in (house_ids or []) if str(h).strip()]
    if ids:
        clauses.append(f"p.house_id IN ({','.join('?' for _ in ids)})")
        args.extend(ids)
    if exclude_foot:
        clauses.append("COALESCE(p.vehicle_type, '') != 'foot'")
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    rows = conn.execute(
        f"""
        SELECT p.*,
               CASE WHEN p.house_id = ? THEN 'GATE' ELSE COALESCE(r.plot_no, p.house_id) END AS plot_no
        FROM parking_passes p
        LEFT JOIN residents r ON r.house_id = p.house_id
        {where}
        ORDER BY p.created_at DESC
        LIMIT ?
        """,
        (ADHOC_HOUSE_ID, *args, lim),
    ).fetchall()
    out = []
    for row in rows:
        item = _row_pass(row)
        if item:
            item.pop("qrDataUrl", None)
            item.pop("photoDataUrl", None)
            out.append(item)
    return out


def list_pending_renewals(
    conn: sqlite3.Connection,
    *,
    site_root: pathlib.Path | None = None,
    limit: int = 80,
) -> list[dict[str, Any]]:
    ensure_parking_passes_table(conn)
    expire_due_passes(conn)
    lim = max(1, min(int(limit or 80), 200))
    rows = conn.execute(
        """
        SELECT p.*, r.plot_no
        FROM parking_passes p
        LEFT JOIN residents r ON r.house_id = p.house_id
        WHERE p.status = 'pending_renewal'
        ORDER BY p.pending_renew_at ASC
        LIMIT ?
        """,
        (lim,),
    ).fetchall()
    out = []
    for row in rows:
        item = _row_pass(row)
        if item:
            _attach_qr(item, site_root)
            out.append(item)
    return out


def lookup_pass(
    conn: sqlite3.Connection,
    query: str,
    *,
    site_root: pathlib.Path | None = None,
    candidates: list[str] | None = None,
    ocr: bool = False,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Resolve a pass code or plate. When ocr=True, unique close matches among registered plates are allowed.

    Returns (item, match_meta).
    """
    ensure_parking_passes_table(conn)
    expire_due_passes(conn)
    raw = (query or "").strip()
    guesses = [raw]
    for extra in candidates or []:
        text = str(extra or "").strip()
        if text and text not in guesses:
            guesses.append(text)
    if not any(guesses):
        raise ValueError("Enter a vehicle number or pass code")

    for guess in guesses:
        code = guess.upper()
        if (
            code.startswith("VP-")
            or code.startswith("MP-")
            or code.startswith("TP-")
            or code.startswith("AP-")
            or code.startswith("SP-")
            or code.startswith("PP_")
        ):
            item = get_pass(conn, code, site_root=site_root, with_qr=True)
            if item:
                return item, {"kind": "exact", "query": guess, "plate": item.get("plate") or ""}

    plates: list[str] = []
    for guess in guesses:
        parsed = extract_plates_from_ocr_text(guess) if ocr else []
        try:
            plate, _display = normalize_plate(guess)
        except ValueError:
            plate = compact_plate(guess)
        for item_plate in ([plate] if plate else []) + parsed:
            if item_plate and item_plate not in plates:
                plates.append(item_plate)
    if not plates:
        return None, None

    originals = {compact_plate(g) for g in guesses if compact_plate(g)}
    search = expand_ocr_plates(plates) if ocr else plates
    hits: list[tuple[str, dict[str, Any]]] = []
    seen_ids: set[str] = set()
    for plate in search:
        item = _lookup_plate_exact(conn, plate, site_root=site_root)
        pid = str((item or {}).get("id") or "")
        if item and pid and pid not in seen_ids:
            seen_ids.add(pid)
            hits.append((plate, item))
            if not ocr:
                break
    if len(hits) == 1:
        plate, item = hits[0]
        registered = compact_plate(item.get("plate") or plate)
        kind = "exact" if registered in originals else "lookalike"
        return item, {"kind": kind, "query": plates[0], "plate": item.get("plate") or plate}
    if not ocr:
        return None, None
    return _lookup_plate_fuzzy(conn, plates, site_root=site_root)


def _lookup_plate_exact(
    conn: sqlite3.Connection,
    plate: str,
    *,
    site_root: pathlib.Path | None = None,
) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT p.*, r.plot_no
        FROM parking_passes p
        LEFT JOIN residents r ON r.house_id = p.house_id
        WHERE p.plate = ?
        ORDER BY
          CASE p.status
            WHEN 'active' THEN 0
            WHEN 'pending_renewal' THEN 1
            WHEN 'expired' THEN 2
            ELSE 3
          END,
          p.created_at DESC
        LIMIT 1
        """,
        (plate,),
    ).fetchone()
    item = _row_pass(row)
    if item:
        _attach_qr(item, site_root)
    return item


def _active_registered_plates(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT p.*, r.plot_no
        FROM parking_passes p
        LEFT JOIN residents r ON r.house_id = p.house_id
        WHERE p.status IN ('active', 'pending_renewal')
          AND COALESCE(p.kind, 'visitor') IN ('member', 'tenant', 'visitor')
          AND COALESCE(p.plate, '') NOT LIKE 'ADHOC%'
          AND COALESCE(p.plate, '') NOT LIKE 'STAFF%'
        """
    ).fetchall()


def _lookup_plate_fuzzy(
    conn: sqlite3.Connection,
    queries: list[str],
    *,
    site_root: pathlib.Path | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    rows = _active_registered_plates(conn)
    if not rows:
        return None, None
    best: list[tuple[float, sqlite3.Row, str]] = []
    for row in rows:
        registered = compact_plate(str(row["plate"] or ""))
        if len(registered) < 6:
            continue
        distance = min(plate_confusion_distance(q, registered) for q in queries)
        if distance <= 2.0:
            best.append((distance, row, registered))
    best.sort(key=lambda item: (item[0], item[2]))
    if best:
        top_d, top_row, top_plate = best[0]
        unique = len(best) == 1 or best[1][0] - top_d >= 0.5
        if unique and top_d <= 1.05:
            item = _row_pass(top_row)
            if item:
                _attach_qr(item, site_root)
            return item, {
                "kind": "fuzzy",
                "query": queries[0],
                "plate": top_plate,
                "distance": round(top_d, 2),
            }

    tails = {q[-4:] for q in queries if len(q) >= 4 and q[-4:].isdigit()}
    if len(tails) == 1:
        tail = next(iter(tails))
        hits = [
            row for row in rows
            if compact_plate(str(row["plate"] or "")).endswith(tail)
        ]
        if len(hits) == 1:
            item = _row_pass(hits[0])
            if item:
                _attach_qr(item, site_root)
            return item, {
                "kind": "suffix",
                "query": queries[0],
                "plate": item.get("plate") if item else tail,
                "distance": 1,
            }
    return None, None


def general_lookup_view(item: dict[str, Any] | None) -> dict[str, Any] | None:
    """Type, validity, and code — for other plots when the actor has Pass · general."""
    item = _pass_record(item)
    if not item:
        return None
    status = (item.get("status") or "expired").strip().lower()
    valid = status in ("active", "pending_renewal")
    if valid:
        status_label = "Valid"
    elif status == "revoked":
        status_label = "Not valid (revoked)"
    elif status == "expired":
        status_label = "Not valid (expired)"
    else:
        status_label = "Not valid"
    out = {
        "id": item.get("id") or "",
        "code": item.get("code") or item.get("id") or "",
        "kind": item.get("kind") or "",
        "kindLabel": item.get("kindLabel") or "Pass",
        "status": status,
        "statusLabel": status_label,
        "valid": valid,
        "expiresAtLabel": item.get("expiresAtLabel") or ("Permanent" if item.get("permanent") else ""),
        "detailLevel": "general",
    }
    # Gate must see face + name + plot for on-foot passes.
    if is_identity_kind(item.get("kind")):
        out.update({
            "visitorName": item.get("visitorName") or "",
            "plotNo": item.get("plotNo") or item.get("houseId") or "",
            "houseId": item.get("houseId") or "",
            "memberName": item.get("memberName") or "",
            "hasPhoto": bool(item.get("hasPhoto")),
            "photoUrl": item.get("photoUrl") or "",
            "category": item.get("category") or item.get("staffCategory") or item.get("adhocCategory") or "",
            "categoryLabel": item.get("categoryLabel") or item.get("staffCategoryLabel") or item.get("adhocCategoryLabel") or "",
            "adhocCategoryLabel": item.get("adhocCategoryLabel") or "",
            "staffCategoryLabel": item.get("staffCategoryLabel") or "",
        })
    return out


def _pass_record(item: Any) -> dict[str, Any] | None:
    if item is None:
        return None
    if isinstance(item, (tuple, list)):
        item = item[0] if item else None
    return item if isinstance(item, dict) else None


def manage_lookup_view(item: dict[str, Any] | None) -> dict[str, Any] | None:
    item = _pass_record(item)
    if not item:
        return None
    out = dict(item)
    out["detailLevel"] = "manage"
    status = (out.get("status") or "expired").strip().lower()
    out["valid"] = status in ("active", "pending_renewal")
    return out


def own_house_lookup_view(item: dict[str, Any] | None) -> dict[str, Any] | None:
    """Full vehicle details for a pass belonging to the viewer's own plot."""
    item = _pass_record(item)
    if not item:
        return None
    out = dict(item)
    out["detailLevel"] = "own"
    status = (out.get("status") or "expired").strip().lower()
    out["valid"] = status in ("active", "pending_renewal")
    return out


def lookup_view_for_actor(
    item: dict[str, Any] | None,
    actor: dict | None,
    *,
    can_manage: bool,
) -> dict[str, Any] | None:
    item = _pass_record(item)
    if not item:
        return None
    if can_manage:
        return manage_lookup_view(item)
    actor_house = str((actor or {}).get("houseId") or (actor or {}).get("house_id") or "").strip()
    pass_house = str(item.get("houseId") or item.get("house_id") or "").strip()
    if actor_house and pass_house and actor_house == pass_house:
        return own_house_lookup_view(item)
    return general_lookup_view(item)


def _active_for_plate(conn: sqlite3.Connection, plate: str) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT * FROM parking_passes
        WHERE plate = ? AND status IN ('active', 'pending_renewal')
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (plate,),
    ).fetchone()


def _latest_for_house_plate(
    conn: sqlite3.Connection, house_id: str, plate: str
) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT * FROM parking_passes
        WHERE house_id = ? AND plate = ?
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (house_id, plate),
    ).fetchone()


def actor_email(conn: sqlite3.Connection, actor: dict) -> str:
    mid = (actor.get("memberId") or "").strip()
    if mid:
        member = rwa_household.get_member(conn, mid)
        if member and str(member.get("email") or "").strip():
            return str(member.get("email") or "").strip().lower()
    return str(actor.get("email") or "").strip().lower()


def _actor_name(actor: dict) -> str:
    return (actor.get("name") or actor.get("houseId") or "Member").strip()


def _hours_from_payload(conn: sqlite3.Connection, payload: dict) -> int:
    raw = payload.get("hours") or payload.get("leaseHours") or payload.get("durationHours")
    if raw in (None, ""):
        return default_hours(conn)
    try:
        n = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("Choose a valid lease duration") from exc
    if n not in ALLOWED_HOURS:
        raise ValueError("Lease duration must be 4, 8, 12, or 24 hours")
    return n


def _months_from_payload(payload: dict, *, fallback: int = DEFAULT_MONTHS) -> int:
    raw = payload.get("months") or payload.get("leaseMonths") or payload.get("durationMonths")
    if raw in (None, ""):
        n = int(fallback or DEFAULT_MONTHS)
    else:
        try:
            n = int(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError("Choose a valid tenant lease (1, 3, 6, or 12 months)") from exc
    if n not in ALLOWED_MONTHS:
        raise ValueError("Tenant lease must be 1, 3, 6, or 12 months")
    return n


def _apply_window(hours: int) -> tuple[str, str]:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    end = now + timedelta(hours=int(hours))
    issued = now.isoformat().replace("+00:00", "Z")
    expires = end.isoformat().replace("+00:00", "Z")
    return issued, expires


def _apply_month_window(months: int) -> tuple[str, str]:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    month_index = now.month - 1 + int(months)
    year = now.year + month_index // 12
    month = month_index % 12 + 1
    day = min(now.day, calendar.monthrange(year, month)[1])
    end = now.replace(year=year, month=month, day=day)
    issued = now.isoformat().replace("+00:00", "Z")
    expires = end.isoformat().replace("+00:00", "Z")
    return issued, expires


def _tenant_fields(payload: dict) -> tuple[str, str, str, str]:
    name = normalize_visitor(
        payload.get("tenantName") or payload.get("visitorName") or payload.get("name")
    )
    if not name:
        raise ValueError("Tenant name is required")
    phone = rwa_household.normalize_phone(payload.get("tenantPhone") or payload.get("phone"))
    if not phone or len(re.sub(r"\D", "", phone)) < 10:
        raise ValueError("Tenant mobile number is required")
    email_raw = str(payload.get("tenantEmail") or payload.get("email") or "").strip().lower()
    email = ""
    if email_raw:
        email = rwa_household.validate_email(email_raw)
    note = re.sub(r"\s+", " ", str(payload.get("tenantNote") or payload.get("idNote") or "").strip())[:200]
    return name, phone, email, note


def _kind_of_row(row: sqlite3.Row | None) -> str:
    if not row:
        return KIND_VISITOR
    if "kind" in row.keys():
        return normalize_kind(row["kind"])
    return KIND_VISITOR


def issue_pass(
    conn: sqlite3.Connection,
    *,
    actor: dict,
    payload: dict,
    site_root: pathlib.Path,
) -> dict[str, Any]:
    ensure_parking_passes_table(conn)
    expire_due_passes(conn)
    if actor.get("viewOnly"):
        raise PermissionError("View-only access cannot request a parking pass")
    if actor.get("superAdmin"):
        raise PermissionError("Super admin cannot register a vehicle as a plot")
    house_id = (actor.get("houseId") or "").strip()
    if not house_id or house_id == SUPERADMIN_HOUSE_ID:
        raise ValueError("Sign in from your plot to request a pass")
    kind = normalize_kind(payload.get("kind") or payload.get("passKind"))
    if kind == KIND_ADHOC:
        raise ValueError("Ad-hoc gate passes are issued only at the main gate QR page")
    if kind == KIND_STAFF:
        raise ValueError("Household staff passes need a selfie. Use the staff form on Pass.")
    plate, plate_display = normalize_plate(payload.get("plate") or payload.get("vehicleNumber"))
    colour = normalize_colour(payload.get("colour") or payload.get("color"))
    vehicle_type = normalize_vehicle_type(payload.get("vehicleType") or payload.get("type"))
    visitor_name = normalize_visitor(
        payload.get("visitorName") or payload.get("visitor") or payload.get("driverName")
    )
    tenant_phone = ""
    tenant_email = ""
    tenant_note = ""
    tenant_id = ""
    lease_months = 0
    if kind == KIND_MEMBER and not visitor_name:
        visitor_name = _actor_name(actor)
    if kind == KIND_TENANT:
        import rwa_tenants

        tenant = rwa_tenants.get_tenant(conn, payload.get("tenantId") or payload.get("tenant_id") or "")
        if not tenant or tenant.get("houseId") != house_id:
            raise ValueError("Select a tenant already registered on this plot (Profile → Tenants).")
        if tenant.get("status") != "active":
            raise ValueError("That occupancy has ended. Register the current tenant first.")
        tenant_id = tenant["id"]
        visitor_name = tenant.get("name") or ""
        tenant_phone = tenant.get("phone") or ""
        tenant_email = tenant.get("email") or ""
        tenant_note = tenant.get("note") or ""

    existing = _active_for_plate(conn, plate)
    if existing:
        existing_kind = _kind_of_row(existing)
        label = KIND_LABELS.get(existing_kind, "visitor").lower()
        if existing["house_id"] == house_id:
            if existing_kind == KIND_MEMBER:
                raise ValueError("This vehicle is already registered for a permanent member pass.")
            raise ValueError(f"This vehicle already has an active or pending {label} pass. Renew it from Pass.")
        raise ValueError(f"This vehicle number already has an active {label} pass in the colony")

    if kind in (KIND_VISITOR, KIND_TENANT):
        latest = _latest_for_house_plate(conn, house_id, plate)
        latest_kind = _kind_of_row(latest)
        if latest and latest["status"] == "expired" and latest_kind == kind:
            extra = {"months": _months_from_payload(payload)} if kind == KIND_TENANT else {"hours": _hours_from_payload(conn, payload)}
            return renew_pass(
                conn,
                pass_id=latest["id"],
                actor=actor,
                payload=extra,
                site_root=site_root,
            )

    pid = _new_id()
    code = _new_code(conn, kind)
    now = utc_now()
    hours = 0
    if kind == KIND_MEMBER:
        issued_at = now
        expires_at = PERMANENT_EXPIRES
        note = "permanent member vehicle"
    elif kind == KIND_TENANT:
        lease_months = _months_from_payload(payload)
        issued_at, expires_at = _apply_month_window(lease_months)
        note = f"{lease_months} month tenant lease"
    else:
        hours = _hours_from_payload(conn, payload)
        issued_at, expires_at = _apply_window(hours)
        note = f"{hours}h visitor lease"
    conn.execute(
        """
        INSERT INTO parking_passes(
          id, public_code, house_id, member_id, member_name, kind, plate, plate_display,
          colour, vehicle_type, visitor_name, tenant_id, tenant_phone, tenant_email, tenant_note,
          lease_hours, lease_months, photo_filename, status, issued_at, expires_at,
          renew_count, last_renewed_at, pending_renew_hours, pending_renew_at,
          approved_by_house_id, approved_by_name, revoked_reason, email_sent,
          created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, 'active', ?, ?, 0, NULL, 0, NULL,
                  NULL, NULL, '', 0, ?, ?)
        """,
        (
            pid,
            code,
            house_id,
            actor.get("memberId") or "",
            _actor_name(actor),
            kind,
            plate,
            plate_display,
            colour,
            vehicle_type,
            visitor_name,
            tenant_id,
            tenant_phone,
            tenant_email,
            tenant_note,
            hours,
            lease_months,
            issued_at,
            expires_at,
            now,
            now,
        ),
    )
    _add_event(conn, pass_id=pid, action="issued", actor=actor, note=note)
    conn.commit()
    item = get_pass(conn, pid, site_root=site_root, with_qr=True)
    if not item:
        raise ValueError("Pass could not be loaded after issue")
    delivery = send_pass_email(conn, item, actor=actor, site_root=site_root, reason="issued")
    item["emailDelivery"] = delivery
    return item


def issue_adhoc_pass(
    conn: sqlite3.Connection,
    *,
    name: str,
    photo_bytes: bytes,
    hours: int | None = None,
    category: str | None = None,
    site_root: pathlib.Path,
) -> dict[str, Any]:
    """Public gate flow: selfie + name → short ad-hoc entry pass (1–9 hours)."""
    ensure_parking_passes_table(conn)
    expire_due_passes(conn)
    visitor_name = normalize_visitor(name)
    if len(visitor_name) < 2:
        raise ValueError("Enter your full name")
    cat = normalize_adhoc_category(category)
    lease_hours = int(hours) if hours is not None else DEFAULT_ADHOC_HOURS
    if lease_hours not in ALLOWED_ADHOC_HOURS:
        raise ValueError("Ad-hoc pass duration must be between 1 and 9 hours")
    if not photo_bytes:
        raise ValueError("Take a selfie to continue")

    pid = _new_id()
    code = _new_code(conn, KIND_ADHOC)
    # Synthetic plate key so schema stays unique / non-null without a vehicle.
    plate = f"ADHOC{pid.replace('pp_', '').upper()[:8]}"
    plate_display = "On foot / gate"
    issued_at, expires_at = _apply_window(lease_hours)
    now = utc_now()
    photo_filename = save_adhoc_photo(site_root, pid, photo_bytes)

    conn.execute(
        """
        INSERT INTO parking_passes(
          id, public_code, house_id, member_id, member_name, kind, plate, plate_display,
          colour, vehicle_type, visitor_name, tenant_id, tenant_phone, tenant_email, tenant_note,
          lease_hours, lease_months, photo_filename, status, issued_at, expires_at,
          renew_count, last_renewed_at, pending_renew_hours, pending_renew_at,
          approved_by_house_id, approved_by_name, revoked_reason, email_sent,
          created_at, updated_at
        ) VALUES (?, ?, ?, '', 'Main gate', ?, ?, ?, '', 'foot', ?, '', '', '', ?,
                  ?, 0, ?, 'active', ?, ?, 0, NULL, 0, NULL, NULL, NULL, '', 0, ?, ?)
        """,
        (
            pid,
            code,
            ADHOC_HOUSE_ID,
            KIND_ADHOC,
            plate,
            plate_display,
            visitor_name,
            cat,
            lease_hours,
            photo_filename,
            issued_at,
            expires_at,
            now,
            now,
        ),
    )
    _add_event(
        conn,
        pass_id=pid,
        action="issued",
        actor={"houseId": ADHOC_HOUSE_ID, "name": visitor_name},
        note=f"{lease_hours}h ad-hoc ({ADHOC_CATEGORIES.get(cat, cat)})",
    )
    conn.commit()
    item = get_pass(conn, pid, site_root=site_root, with_qr=True)
    if not item:
        raise ValueError("Pass could not be loaded after issue")
    # Embed selfie once for the public confirmation screen.
    path = adhoc_photo_path(site_root, photo_filename)
    if path and path.is_file():
        item["photoDataUrl"] = "data:image/webp;base64," + base64.b64encode(path.read_bytes()).decode("ascii")
    return item


def issue_staff_pass(
    conn: sqlite3.Connection,
    *,
    actor: dict,
    name: str,
    photo_bytes: bytes,
    category: str | None = None,
    months: int | None = None,
    phone: str | None = None,
    site_root: pathlib.Path,
) -> dict[str, Any]:
    """Signed-in household: selfie staff pass tied to the plot (maid, cook, …)."""
    ensure_parking_passes_table(conn)
    expire_due_passes(conn)
    if actor.get("viewOnly"):
        raise PermissionError("View-only access cannot issue a staff pass")
    if actor.get("superAdmin"):
        raise PermissionError("Super admin cannot issue a staff pass as a plot")
    house_id = (actor.get("houseId") or "").strip()
    if not house_id or house_id in (SUPERADMIN_HOUSE_ID, ADHOC_HOUSE_ID):
        raise ValueError("Sign in from your plot to issue a staff pass")
    visitor_name = normalize_visitor(name)
    if len(visitor_name) < 2:
        raise ValueError("Enter the staff member's full name")
    cat = normalize_staff_category(category)
    lease_months = int(months) if months not in (None, "") else DEFAULT_STAFF_MONTHS
    if lease_months not in ALLOWED_MONTHS:
        raise ValueError("Staff pass duration must be 1, 3, 6, or 12 months")
    if not photo_bytes:
        raise ValueError("Take a selfie of the staff member to continue")
    phone_norm = ""
    if phone:
        phone_norm = rwa_household.normalize_phone(phone) or ""
        digits = re.sub(r"\D", "", phone_norm)
        if phone_norm and len(digits) < 10:
            raise ValueError("Enter a valid 10-digit mobile number, or leave it blank")

    active = conn.execute(
        """
        SELECT COUNT(*) AS n FROM parking_passes
        WHERE house_id = ? AND kind = ? AND status = 'active'
        """,
        (house_id, KIND_STAFF),
    ).fetchone()
    count = int((active["n"] if active else 0) or 0)
    if count >= STAFF_MAX_ACTIVE:
        raise ValueError(f"This plot already has {STAFF_MAX_ACTIVE} active staff passes. End one before adding another.")

    pid = _new_id()
    code = _new_code(conn, KIND_STAFF)
    plate = f"STAFF{pid.replace('pp_', '').upper()[:8]}"
    plate_display = STAFF_CATEGORIES.get(cat, "Staff")
    issued_at, expires_at = _apply_month_window(lease_months)
    now = utc_now()
    photo_filename = save_pass_photo(site_root, pid, photo_bytes, prefix="staff")

    conn.execute(
        """
        INSERT INTO parking_passes(
          id, public_code, house_id, member_id, member_name, kind, plate, plate_display,
          colour, vehicle_type, visitor_name, tenant_id, tenant_phone, tenant_email, tenant_note,
          lease_hours, lease_months, photo_filename, status, issued_at, expires_at,
          renew_count, last_renewed_at, pending_renew_hours, pending_renew_at,
          approved_by_house_id, approved_by_name, revoked_reason, email_sent,
          created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, '', 'foot', ?, '', ?, '', ?,
                  0, ?, ?, 'active', ?, ?, 0, NULL, 0, NULL, NULL, NULL, '', 0, ?, ?)
        """,
        (
            pid,
            code,
            house_id,
            actor.get("memberId") or "",
            _actor_name(actor),
            KIND_STAFF,
            plate,
            plate_display,
            visitor_name,
            phone_norm,
            cat,
            lease_months,
            photo_filename,
            issued_at,
            expires_at,
            now,
            now,
        ),
    )
    _add_event(
        conn,
        pass_id=pid,
        action="issued",
        actor=actor,
        note=f"{lease_months} month staff ({STAFF_CATEGORIES.get(cat, cat)})",
    )
    conn.commit()
    item = get_pass(conn, pid, site_root=site_root, with_qr=True)
    if not item:
        raise ValueError("Pass could not be loaded after issue")
    delivery = send_pass_email(conn, item, actor=actor, site_root=site_root, reason="issued")
    item["emailDelivery"] = delivery
    return item


def list_adhoc_passes(
    conn: sqlite3.Connection,
    *,
    site_root: pathlib.Path | None = None,
    limit: int = 40,
) -> list[dict[str, Any]]:
    ensure_parking_passes_table(conn)
    expire_due_passes(conn)
    rows = conn.execute(
        """
        SELECT p.*, 'GATE' AS plot_no
        FROM parking_passes p
        WHERE p.kind = ?
        ORDER BY p.created_at DESC
        LIMIT ?
        """,
        (KIND_ADHOC, max(1, min(int(limit or 40), 100))),
    ).fetchall()
    out = []
    for row in rows:
        item = _row_pass(row)
        if item:
            _attach_qr(item, site_root)
            out.append(item)
    return out


def renew_pass(
    conn: sqlite3.Connection,
    *,
    pass_id: str,
    actor: dict,
    payload: dict | None = None,
    site_root: pathlib.Path,
) -> dict[str, Any]:
    ensure_parking_passes_table(conn)
    expire_due_passes(conn)
    if actor.get("viewOnly"):
        raise PermissionError("View-only access cannot renew a parking pass")
    item = get_pass(conn, pass_id, site_root=site_root)
    if not item:
        raise ValueError("Pass not found")
    house_id = (actor.get("houseId") or "").strip()
    if item["houseId"] != house_id and not actor.get("superAdmin"):
        raise PermissionError("You can only renew passes for your plot")
    if item.get("permanent") or item.get("kind") == KIND_MEMBER:
        raise ValueError("Member vehicle passes are permanent and do not need renewal")
    if item.get("kind") == KIND_ADHOC:
        raise ValueError("Ad-hoc gate passes cannot be renewed. Scan the main gate QR for a new pass.")
    if item["status"] == "pending_renewal":
        raise ValueError("This renewal is already waiting for EC approval")
    if item["status"] == "revoked":
        raise ValueError("This pass was revoked. Request a new pass.")
    if item["status"] == "active":
        raise ValueError("This pass is still valid. Renew after it expires.")
    if item["status"] != "expired":
        raise ValueError("This pass cannot be renewed")

    payload = payload or {}
    now = utc_now()
    renew_count = int(item.get("renewCount") or 0)
    is_tenant = item.get("kind") == KIND_TENANT
    is_staff = item.get("kind") == KIND_STAFF
    if is_tenant or is_staff:
        fallback = item.get("leaseMonths") or (DEFAULT_STAFF_MONTHS if is_staff else DEFAULT_MONTHS)
        duration = _months_from_payload(payload, fallback=fallback)
        duration_note = f"{duration} month {'staff' if is_staff else 'tenant'} lease"
        window_fn = _apply_month_window
    else:
        duration = _hours_from_payload(conn, payload)
        duration_note = f"{duration}h"
        window_fn = _apply_window

    # Household-sponsored staff: plot owner renews without EC.
    if (not is_staff) and renew_count >= 1:
        conn.execute(
            """
            UPDATE parking_passes
            SET status = 'pending_renewal',
                pending_renew_hours = ?,
                pending_renew_at = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (duration, now, now, item["id"]),
        )
        _add_event(conn, pass_id=item["id"], action="renew_requested", actor=actor, note=duration_note)
        conn.commit()
        out = get_pass(conn, item["id"], site_root=site_root, with_qr=True)
        if not out:
            raise ValueError("Pass not found after renew request")
        out["renewKind"] = "pending_ec"
        return out

    issued_at, expires_at = window_fn(duration)
    if is_tenant or is_staff:
        conn.execute(
            """
            UPDATE parking_passes
            SET status = 'active',
                lease_months = ?,
                issued_at = ?,
                expires_at = ?,
                renew_count = ?,
                last_renewed_at = ?,
                pending_renew_hours = 0,
                pending_renew_at = NULL,
                email_sent = 0,
                updated_at = ?
            WHERE id = ?
            """,
            (duration, issued_at, expires_at, renew_count + 1, now, now, item["id"]),
        )
    else:
        conn.execute(
            """
            UPDATE parking_passes
            SET status = 'active',
                lease_hours = ?,
                issued_at = ?,
                expires_at = ?,
                renew_count = 1,
                last_renewed_at = ?,
                pending_renew_hours = 0,
                pending_renew_at = NULL,
                email_sent = 0,
                updated_at = ?
            WHERE id = ?
            """,
            (duration, issued_at, expires_at, now, now, item["id"]),
        )
    _add_event(
        conn,
        pass_id=item["id"],
        action="renewed",
        actor=actor,
        note=("renewed by household" if is_staff else "1st renew (auto)"),
    )
    conn.commit()
    out = get_pass(conn, item["id"], site_root=site_root, with_qr=True)
    if not out:
        raise ValueError("Pass not found after renew")
    delivery = send_pass_email(conn, out, actor=actor, site_root=site_root, reason="renewed")
    out["emailDelivery"] = delivery
    out["renewKind"] = "auto_notify_ec"
    return out


def approve_renewal(
    conn: sqlite3.Connection,
    *,
    pass_id: str,
    actor: dict,
    site_root: pathlib.Path,
) -> dict[str, Any]:
    ensure_parking_passes_table(conn)
    item = get_pass(conn, pass_id, site_root=site_root)
    if not item:
        raise ValueError("Pass not found")
    if item["status"] != "pending_renewal":
        raise ValueError("This pass is not waiting for EC approval")
    now = utc_now()
    is_tenant = item.get("kind") == KIND_TENANT
    if is_tenant:
        months = int(item.get("pendingRenewHours") or item.get("leaseMonths") or DEFAULT_MONTHS)
        if months not in ALLOWED_MONTHS:
            months = DEFAULT_MONTHS
        issued_at, expires_at = _apply_month_window(months)
        conn.execute(
            """
            UPDATE parking_passes
            SET status = 'active',
                lease_months = ?,
                issued_at = ?,
                expires_at = ?,
                renew_count = renew_count + 1,
                last_renewed_at = ?,
                pending_renew_hours = 0,
                pending_renew_at = NULL,
                approved_by_house_id = ?,
                approved_by_name = ?,
                email_sent = 0,
                updated_at = ?
            WHERE id = ?
            """,
            (
                months,
                issued_at,
                expires_at,
                now,
                actor.get("houseId") or "",
                _actor_name(actor),
                now,
                item["id"],
            ),
        )
    else:
        hours = int(item.get("pendingRenewHours") or item.get("leaseHours") or default_hours(conn))
        if hours not in ALLOWED_HOURS:
            hours = default_hours(conn)
        issued_at, expires_at = _apply_window(hours)
        conn.execute(
            """
            UPDATE parking_passes
            SET status = 'active',
                lease_hours = ?,
                issued_at = ?,
                expires_at = ?,
                renew_count = renew_count + 1,
                last_renewed_at = ?,
                pending_renew_hours = 0,
                pending_renew_at = NULL,
                approved_by_house_id = ?,
                approved_by_name = ?,
                email_sent = 0,
                updated_at = ?
            WHERE id = ?
            """,
            (
                hours,
                issued_at,
                expires_at,
                now,
                actor.get("houseId") or "",
                _actor_name(actor),
                now,
                item["id"],
            ),
        )
    _add_event(conn, pass_id=item["id"], action="renew_approved", actor=actor)
    conn.commit()
    out = get_pass(conn, item["id"], site_root=site_root, with_qr=True)
    if not out:
        raise ValueError("Pass not found after approval")
    delivery = send_pass_email(conn, out, actor=None, site_root=site_root, reason="approved")
    out["emailDelivery"] = delivery
    return out


def reject_renewal(
    conn: sqlite3.Connection,
    *,
    pass_id: str,
    actor: dict,
    note: str = "",
) -> dict[str, Any]:
    ensure_parking_passes_table(conn)
    item = get_pass(conn, pass_id)
    if not item:
        raise ValueError("Pass not found")
    if item["status"] != "pending_renewal":
        raise ValueError("This pass is not waiting for EC approval")
    now = utc_now()
    reason = (note or "").strip()[:240]
    conn.execute(
        """
        UPDATE parking_passes
        SET status = 'expired',
            pending_renew_hours = 0,
            pending_renew_at = NULL,
            revoked_reason = ?,
            updated_at = ?
        WHERE id = ?
        """,
        (reason, now, item["id"]),
    )
    _add_event(conn, pass_id=item["id"], action="renew_rejected", actor=actor, note=reason)
    conn.commit()
    out = get_pass(conn, item["id"])
    if not out:
        raise ValueError("Pass not found after rejection")
    return out


def revoke_pass(
    conn: sqlite3.Connection,
    *,
    pass_id: str,
    actor: dict,
    note: str = "",
) -> dict[str, Any]:
    ensure_parking_passes_table(conn)
    item = get_pass(conn, pass_id)
    if not item:
        raise ValueError("Pass not found")
    if item["status"] == "revoked":
        return item
    now = utc_now()
    reason = (note or "").strip()[:240] or "Revoked by EC"
    conn.execute(
        """
        UPDATE parking_passes
        SET status = 'revoked',
            pending_renew_hours = 0,
            pending_renew_at = NULL,
            revoked_reason = ?,
            updated_at = ?
        WHERE id = ?
        """,
        (reason, now, item["id"]),
    )
    _add_event(conn, pass_id=item["id"], action="revoked", actor=actor, note=reason)
    conn.commit()
    out = get_pass(conn, item["id"])
    if not out:
        raise ValueError("Pass not found after revoke")
    return out


def remove_own_pass(
    conn: sqlite3.Connection,
    *,
    pass_id: str,
    actor: dict,
) -> dict[str, Any]:
    """Member may retire their own registered vehicle."""
    ensure_parking_passes_table(conn)
    item = get_pass(conn, pass_id)
    if not item:
        raise ValueError("Pass not found")
    house_id = (actor.get("houseId") or "").strip()
    if item["houseId"] != house_id and not actor.get("superAdmin"):
        raise PermissionError("You can only remove passes registered to your plot")
    kind = item.get("kind")
    if kind not in (KIND_MEMBER, KIND_STAFF):
        raise ValueError("Only a registered member vehicle or household staff pass can be ended this way")
    if item["status"] == "revoked":
        return item
    note = "Ended by household" if kind == KIND_STAFF else "Removed by member"
    return revoke_pass(conn, pass_id=item["id"], actor=actor, note=note)


def ec_house_ids(conn: sqlite3.Connection) -> list[str]:
    ids: list[str] = []
    for row in rwa_entitlements.list_office_and_ec(conn):
        hid = (row.get("houseId") or "").strip()
        if hid and hid not in ids:
            ids.append(hid)
    return ids


def send_pass_email(
    conn: sqlite3.Connection,
    item: dict[str, Any],
    *,
    actor: dict | None,
    site_root: pathlib.Path,
    reason: str,
) -> dict[str, Any]:
    if item.get("kind") == KIND_ADHOC:
        return {"ok": False, "channel": "none", "reason": "adhoc"}
    to_email = ""
    if actor:
        to_email = actor_email(conn, actor)
    if not to_email:
        member = rwa_household.get_member(conn, item.get("memberId") or "")
        if member:
            to_email = str(member.get("email") or "").strip().lower()
    if not to_email:
        row = conn.execute(
            "SELECT email FROM residents WHERE house_id = ?",
            (item.get("houseId") or "",),
        ).fetchone()
        if row:
            to_email = str(row["email"] or "").strip().lower()
    tenant_email = str(item.get("tenantEmail") or "").strip().lower()
    recipients = []
    if to_email:
        recipients.append(to_email)
    if tenant_email and tenant_email not in recipients:
        recipients.append(tenant_email)
    if not recipients:
        return {"channel": "none", "reason": "no_email"}
    to_email = ", ".join(recipients)

    try:
        import rwa_portal
    except ImportError:
        return {"channel": "none", "reason": "mailer_unavailable"}

    cfg = rwa_portal.load_smtp_config(site_root)
    if not cfg.get("configured"):
        return {"channel": "dev", "reason": "smtp_not_configured"}

    origin = public_origin(site_root)
    pass_url = f"{origin}/#parking"
    plate = html.escape(item.get("plateDisplay") or item.get("plate") or "")
    code = html.escape(item.get("code") or "")
    visitor = html.escape(item.get("visitorName") or item.get("memberName") or "Member")
    colour = html.escape(item.get("colour") or "—")
    vtype = html.escape(item.get("vehicleTypeLabel") or "Car")
    hours = html.escape(str(item.get("leaseHours") or ""))
    expires = html.escape(item.get("expiresAtLabel") or "")
    plot = html.escape(item.get("plotNo") or item.get("houseId") or "")
    member = html.escape(item.get("memberName") or "")
    permanent = bool(item.get("permanent") or item.get("kind") == KIND_MEMBER)
    tenant = item.get("kind") == KIND_TENANT
    staff = item.get("kind") == KIND_STAFF
    headline = visitor if staff else plate
    if permanent:
        card_title = "Member parking pass"
        validity = "Permanent member vehicle"
        subject_map = {"issued": "Member vehicle registered"}
        subject = f"HBC Sanyard — {subject_map.get(reason, 'Member parking pass')}"
        text_title = "Member vehicle parking pass"
        card_bg, accent, btn_bg, btn_fg, stripe = "#15233f", "#c4a15a", "#c4a15a", "#15233f", "#3a2e16"
    elif tenant:
        card_title = "Tenant parking pass"
        validity = f"Tenant lease {html.escape(str(item.get('leaseMonths') or ''))} months · Valid until {expires}"
        subject_map = {
            "issued": "Tenant parking pass issued",
            "renewed": "Tenant parking pass renewed",
            "approved": "Tenant parking pass approved",
        }
        subject = f"HBC Sanyard — {subject_map.get(reason, 'Tenant parking pass')}"
        text_title = "Tenant vehicle parking pass"
        card_bg, accent, btn_bg, btn_fg, stripe = "#143322", "#b7ddb8", "#4d8f57", "#f6f1e6", "#0b1f16"
    elif staff:
        role = html.escape(item.get("staffCategoryLabel") or item.get("categoryLabel") or "Staff")
        card_title = "Household staff pass"
        validity = f"{role} · {html.escape(str(item.get('leaseMonths') or ''))} months · Valid until {expires}"
        subject_map = {
            "issued": "Household staff pass issued",
            "renewed": "Household staff pass renewed",
        }
        subject = f"HBC Sanyard — {subject_map.get(reason, 'Household staff pass')}"
        text_title = "Household staff pass"
        card_bg, accent, btn_bg, btn_fg, stripe = "#241830", "#d4b8e8", "#7a5a9e", "#f6f1e6", "#160e1c"
    else:
        card_title = "Visitor parking pass"
        validity = f"Lease {hours} hours · Valid until {expires}"
        subject_map = {
            "issued": "Visitor parking pass issued",
            "renewed": "Visitor parking pass renewed",
            "approved": "Visitor parking pass approved",
        }
        subject = f"HBC Sanyard — {subject_map.get(reason, 'Visitor parking pass')}"
        text_title = "Visitor vehicle parking pass"
        card_bg, accent, btn_bg, btn_fg, stripe = "#3d1c18", "#f0c4a8", "#c46a3a", "#fff8f2", "#1c1010"
    who_line = f"Staff: {item.get('visitorName')}" if staff else f"Vehicle: {item.get('plateDisplay')}"
    text = (
        f"{text_title}\n\n"
        f"Pass: {item.get('code')}\n"
        f"{who_line}\n"
        f"Valid: {item.get('expiresAtLabel') or 'Permanent'}\n"
        f"Plot: {item.get('plotNo')}\n\n"
        f"Open your pass in the member area: {pass_url}\n\n"
        f"— Residents Welfare Association\n"
        f"  Housing Colony Sanyard, Mandi\n"
    )
    detail_line = (
        f"{html.escape(item.get('staffCategoryLabel') or item.get('categoryLabel') or 'Staff')} · {visitor}"
        if staff
        else f"{vtype} · {colour} · {visitor}"
    )
    gate_note = (
        "Show this pass (QR + selfie) at the gate. Staff is sponsored by your plot."
        if staff
        else "Show this pass at the gate. Any EC member can verify the vehicle number."
    )
    html_body = f"""<!DOCTYPE html>
<html><body style="margin:0;padding:24px;background:#f3eee3;font-family:Georgia,serif;color:#15233f;">
  <table width="100%" cellpadding="0" cellspacing="0" style="max-width:520px;margin:0 auto;background:{card_bg};border-radius:16px;overflow:hidden;">
    <tr><td style="height:18px;background:{stripe};"></td></tr>
    <tr><td style="padding:20px 24px 8px;color:{accent};letter-spacing:.18em;font-size:11px;text-transform:uppercase;">Himuda Housing Colony Sanyard</td></tr>
    <tr><td style="padding:0 24px 4px;color:#f6f1e6;font-size:22px;">{html.escape(card_title)}</td></tr>
    <tr><td style="padding:0 24px 16px;color:{accent};font-size:28px;letter-spacing:.12em;">{headline}</td></tr>
    <tr><td style="padding:0 24px 20px;color:#f6f1e6;font-size:14px;line-height:1.55;">
      Pass {code}<br>
      {detail_line}<br>
      Plot {plot} · {member}<br>
      {validity}
    </td></tr>
    <tr><td style="padding:0 24px 24px;">
      <a href="{html.escape(pass_url)}" style="display:inline-block;background:{btn_bg};color:{btn_fg};text-decoration:none;padding:10px 16px;border-radius:999px;font-family:system-ui,sans-serif;font-weight:600;">Open in Pass</a>
    </td></tr>
  </table>
  <p style="max-width:520px;margin:16px auto 0;font-size:12px;color:#5b6578;">{gate_note}</p>
</body></html>"""
    try:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = f"HBC Sanyard RWA <{cfg['from']}>"
        msg["To"] = to_email
        msg["Reply-To"] = cfg["from"]
        msg.set_content(text)
        msg.add_alternative(html_body, subtype="html")
        with smtplib.SMTP(cfg["host"], cfg["port"], timeout=25) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.ehlo()
            smtp.login(cfg["user"], cfg["password"])
            smtp.send_message(msg)
        conn.execute(
            "UPDATE parking_passes SET email_sent = 1, updated_at = ? WHERE id = ?",
            (utc_now(), item["id"]),
        )
        conn.commit()
        return {"channel": "email", "to": to_email}
    except Exception as exc:  # noqa: BLE001
        return {"channel": "failed", "error": str(exc)}
