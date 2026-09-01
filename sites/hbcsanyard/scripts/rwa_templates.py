"""EC Desk printable Templates — letterheads, receipt pads, forms.

Storage:
  data/templates/<id>/… for uploads
  documents/… (and assets/) for seeded static site files (doc_type=static)
"""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import re
import secrets
import shutil
import sqlite3
import subprocess
import tempfile
from typing import Any

from init_rwa_db import utc_now

TEMPLATE_CATEGORIES: list[tuple[str, str]] = [
    ("letterhead", "Letterhead"),
    ("envelope", "Envelope"),
    ("receipt", "Cash receipt"),
    ("correspondence", "Letters & resolutions"),
    ("notice", "Notice"),
    ("form", "Form"),
    ("certificate", "Certificate"),
    ("chart", "Chart / roster"),
    ("other", "Other"),
]

TEMPLATE_MAX_BYTES = 20 * 1024 * 1024
COMPOSE_ENGINE_VERSION = 1
COMPOSE_BODY_STORE = "body.html"
TEMPLATE_EXT_MIME = {
    ".html": "text/html",
    ".htm": "text/html",
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}

_STATIC_ALLOWED_PREFIXES = ("documents/", "assets/")

PAPER_SIZES = ("A4", "A5", "A6", "Letter", "E2210", "CUSTOM")
PAPER_SIZE_LABELS = {
    "A4": "A4",
    "A5": "A5",
    "A6": "A6",
    "Letter": "Letter",
    "E2210": "22 × 10 cm (envelope)",
    "CUSTOM": "Custom (cm)",
}
_PAPER_ALIASES = {
    "22X10": "E2210",
    "22CMX10CM": "E2210",
}
CUSTOM_W_CM = (8.0, 40.0, 22.0)
CUSTOM_H_CM = (6.0, 30.0, 10.0)
BACKGROUND_STYLES = ("watermark", "none", "plain")
ORIENTATIONS = ("portrait", "landscape")

DEFAULT_TEMPLATE_OPTIONS: dict[str, Any] = {
    "paperSize": "A4",
    "orientation": "portrait",
    "background": "watermark",
    "customWidthCm": CUSTOM_W_CM[2],
    "customHeightCm": CUSTOM_H_CM[2],
    "colors": {
        "heading": "#0b2a56",
        "body": "#12233f",
        "muted": "#5a6a80",
        "accent": "#1a6b3a",
        "gold": "#c9a227",
    },
}

_SEED_TEMPLATES: list[dict[str, Any]] = [
    {
        "id": "tpl-mhws-letterhead",
        "title": "Official Letterhead Pad",
        "description": "A4 letterhead with logo, office bearers, watermark, and footer contacts.",
        "category": "letterhead",
        "tags": ["letterhead", "a4", "print", "official"],
        "static_path": "documents/mhws-letterhead-pad.html",
    },
    {
        "id": "tpl-rwa-letterhead-blank",
        "title": "Blank Letterhead Pad",
        "description": "Simpler blank writing pad with colony branding.",
        "category": "letterhead",
        "tags": ["letterhead", "a4", "blank"],
        "static_path": "documents/rwa-letterhead-blank.html",
    },
    {
        "id": "tpl-mhws-envelope",
        "title": "Official Envelope",
        "description": "Printable envelope face that scales to the stock: 22×10 cm, C-series (C6/C5/C4), or a custom width × height in cm. Return address pre-filled; type the recipient before printing.",
        "category": "envelope",
        "tags": ["envelope", "22x10", "custom", "c6", "c5", "c4", "print", "official"],
        "static_path": "documents/mhws-envelope-pad.html",
        "options": {"paperSize": "E2210", "orientation": "landscape", "background": "watermark"},
    },
    {
        "id": "tpl-cash-receipt",
        "title": "Cash Receipt Booklet",
        "description": "Blank cash receipts — 210 mm wide on every layout: 2 on A5 landscape, 3 or 4 on A4 portrait.",
        "category": "receipt",
        "tags": ["cash", "treasury", "a4", "a5", "a6", "booklet"],
        "static_path": "documents/mhws-cash-receipt-booklet.html",
    },
    {
        "id": "tpl-ec-committee",
        "title": "Executive Committee Charter",
        "description": "Office bearers + executive members chart for print / notice board (letterhead theme).",
        "category": "chart",
        "tags": ["ec", "office bearers", "charter"],
        "static_path": "documents/ec-committee-pad.html",
    },
    {
        "id": "tpl-ec-press-release",
        "title": "Press Release — New Executive Committee",
        "description": "Official press release announcing the new Executive Committee (office bearers & members).",
        "category": "notice",
        "tags": ["press release", "ec", "media", "notice"],
        "static_path": "documents/ec-press-release.html",
    },
    {
        "id": "tpl-proceedings-gh-mom",
        "title": "General House MOM Register (2 pages)",
        "description": "Two-page A4 register for General House minutes — attendance, agenda, detailed proceedings, resolutions & actions.",
        "category": "form",
        "tags": ["proceedings", "mom", "general house", "register", "a4", "2-page"],
        "static_path": "documents/proceedings-gh-mom-pad.html",
    },
    {
        "id": "tpl-proceedings-ec-mom",
        "title": "Executive Committee MOM Register (2 pages)",
        "description": "Two-page A4 register for EC minutes — attendance, agenda, detailed proceedings, decisions & actions.",
        "category": "form",
        "tags": ["proceedings", "mom", "ec", "register", "a4", "2-page"],
        "static_path": "documents/proceedings-ec-mom-pad.html",
    },
    {
        "id": "tpl-resolution-engage-advocate-path-2026",
        "title": "Resolution — engage Advocate Shailesh Sharma (path case)",
        "description": "Covering letter + certified EC resolution to engage counsel for Court Case No. 01 (path / link road). Professional fee ₹50,000. Fill meeting date and enrollment, then sign.",
        "category": "correspondence",
        "tags": ["resolution", "legal", "advocate", "path", "ec"],
        "static_path": "documents/resolution-engage-advocate-path-case-2026.html",
    },
]


def ensure_print_templates_table(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS print_templates (
          id TEXT PRIMARY KEY,
          title TEXT NOT NULL,
          description TEXT,
          category TEXT NOT NULL DEFAULT 'other',
          tags_json TEXT NOT NULL DEFAULT '[]',
          doc_type TEXT NOT NULL DEFAULT 'file'
            CHECK(doc_type IN ('file','static')),
          filename TEXT,
          original_name TEXT,
          mime_type TEXT,
          size_bytes INTEGER,
          static_path TEXT,
          options_json TEXT NOT NULL DEFAULT '{}',
          status TEXT NOT NULL DEFAULT 'published'
            CHECK(status IN ('draft','published','archived')),
          created_by TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_print_templates_cat
          ON print_templates(status, category, updated_at DESC);
        """
    )
    cols = {str(r[1]) for r in conn.execute("PRAGMA table_info(print_templates)").fetchall()}
    if "options_json" not in cols:
        conn.execute(
            "ALTER TABLE print_templates ADD COLUMN options_json TEXT NOT NULL DEFAULT '{}'"
        )
    ensure_template_versions_table(conn)


def _veercanvas_root() -> pathlib.Path:
    return pathlib.Path(os.environ.get("VEERCANVAS_ROOT", pathlib.Path(__file__).resolve().parents[3]))


def load_society_branding(site_root: pathlib.Path) -> dict[str, Any]:
    """Society strings and logo paths from site-meta.json (see core/document-engine/branding.py)."""
    try:
        import importlib.util

        branding_py = _veercanvas_root() / "core" / "document-engine" / "branding.py"
        if branding_py.is_file():
            spec = importlib.util.spec_from_file_location("veer_document_branding", branding_py)
            if spec and spec.loader:
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                return mod.load_society_branding(site_root)
    except Exception:
        pass
    society = "Residents Welfare Association"
    return {
        "societyName": society,
        "colonyName": society,
        "addressLine": "",
        "email": "",
        "publicOrigin": "",
        "metaLine": "",
        "footerLine": society,
        "logoPrint": "/assets/favicon-192.png",
        "logoWatermark": "/assets/favicon-192.png",
    }


def ensure_template_versions_table(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS template_versions (
          template_id TEXT NOT NULL,
          version INTEGER NOT NULL,
          fingerprint TEXT NOT NULL,
          compiled_html TEXT NOT NULL,
          spec_json TEXT NOT NULL DEFAULT '{}',
          published_at TEXT NOT NULL,
          published_by TEXT,
          PRIMARY KEY (template_id, version)
        );
        CREATE INDEX IF NOT EXISTS idx_template_versions_tpl
          ON template_versions(template_id, version DESC);
        """
    )


def get_latest_template_version(conn: sqlite3.Connection, template_id: str) -> int:
    ensure_template_versions_table(conn)
    row = conn.execute(
        "SELECT MAX(version) FROM template_versions WHERE template_id = ?",
        (str(template_id or "").strip(),),
    ).fetchone()
    return int(row[0] or 0) if row and row[0] is not None else 0


def list_template_versions(
    conn: sqlite3.Connection,
    template_id: str,
    *,
    limit: int = 20,
) -> list[dict[str, Any]]:
    ensure_template_versions_table(conn)
    lim = max(1, min(int(limit or 20), 100))
    rows = conn.execute(
        """
        SELECT version, fingerprint, published_at, published_by
        FROM template_versions
        WHERE template_id = ?
        ORDER BY version DESC
        LIMIT ?
        """,
        (str(template_id or "").strip(), lim),
    ).fetchall()
    return [
        {
            "version": int(r["version"]),
            "fingerprint": r["fingerprint"],
            "publishedAt": r["published_at"],
            "publishedBy": r["published_by"],
        }
        for r in rows
    ]


def load_template_version_html(
    conn: sqlite3.Connection,
    template_id: str,
    version: int,
) -> str | None:
    ensure_template_versions_table(conn)
    if not template_id or not version:
        return None
    row = conn.execute(
        """
        SELECT compiled_html FROM template_versions
        WHERE template_id = ? AND version = ?
        """,
        (str(template_id).strip(), int(version)),
    ).fetchone()
    if not row:
        return None
    return str(row["compiled_html"] or "")


def compile_chrome_template_html(
    conn: sqlite3.Connection,
    site_root: pathlib.Path,
    template_id: str,
) -> str:
    doc = get_template(conn, template_id, site_root=site_root)
    if not doc:
        raise ValueError("Template not found")
    opts = doc.get("options") or {}
    stationery = opts.get("stationery") if isinstance(opts.get("stationery"), dict) else None
    if stationery:
        return render_stationery_html(normalize_stationery(stationery), doc.get("title") or "Letterhead")
    html, _ = render_template_html(conn, site_root, template_id)
    return html


def publish_template_version(
    conn: sqlite3.Connection,
    site_root: pathlib.Path,
    template_id: str,
    *,
    actor: str | None = None,
) -> dict[str, Any]:
    ensure_template_versions_table(conn)
    tid = str(template_id or "").strip()
    if not tid:
        raise ValueError("Template id required")
    html = compile_chrome_template_html(conn, site_root, tid)
    fingerprint = compute_chrome_fingerprint(conn, site_root, tid)
    doc = get_template(conn, tid, site_root=site_root)
    spec_json = json.dumps(doc.get("options") or {}, ensure_ascii=False)
    version = get_latest_template_version(conn, tid) + 1
    now = utc_now()
    conn.execute(
        """
        INSERT INTO template_versions(
          template_id, version, fingerprint, compiled_html, spec_json,
          published_at, published_by
        ) VALUES (?,?,?,?,?,?,?)
        """,
        (tid, version, fingerprint, html, spec_json, now, actor),
    )
    conn.commit()
    return {
        "templateId": tid,
        "version": version,
        "fingerprint": fingerprint,
        "publishedAt": now,
        "publishedBy": actor,
    }


def seed_template_versions(conn: sqlite3.Connection, site_root: pathlib.Path) -> None:
    """Publish v1 snapshots for seeded pads and stationery letterheads (idempotent)."""
    ensure_template_versions_table(conn)
    seed_default_templates(conn, site_root)
    ids: set[str] = {str(item["id"]) for item in _SEED_TEMPLATES}
    rows = conn.execute(
        "SELECT id, options_json FROM print_templates WHERE status != 'archived'"
    ).fetchall()
    for row in rows:
        opts = normalize_options(row["options_json"])
        if opts.get("stationery"):
            ids.add(str(row["id"]))
    for tid in ids:
        if get_latest_template_version(conn, tid) > 0:
            continue
        try:
            publish_template_version(conn, site_root, tid, actor="system")
        except Exception:
            continue


def compose_chrome_status(
    conn: sqlite3.Connection,
    site_root: pathlib.Path,
    options: dict[str, Any] | None,
) -> dict[str, Any]:
    from rwa_compose_export import PLAIN_CHROME_IDS

    opts = normalize_options(options)
    if not opts.get("composed"):
        return {}
    chrome = str(opts.get("composeChrome") or "simple")
    saved_fp = str(opts.get("composeChromeFingerprint") or "").strip()
    current_fp = compute_chrome_fingerprint(conn, site_root, chrome)
    saved_ver = int(opts.get("composeChromeVersion") or 0)
    latest_ver = (
        get_latest_template_version(conn, chrome)
        if chrome not in PLAIN_CHROME_IDS and chrome != "simple"
        else 0
    )
    fp_stale = bool(saved_fp and saved_fp != current_fp)
    ver_stale = bool(latest_ver and saved_ver and saved_ver < latest_ver)
    return {
        "composeChrome": chrome,
        "composeChromeFingerprint": saved_fp,
        "composeChromeFingerprintCurrent": current_fp,
        "composeChromeVersion": saved_ver,
        "composeChromeVersionLatest": latest_ver,
        "composeChromeStale": fp_stale or ver_stale,
    }


def _enrich_template_meta(
    conn: sqlite3.Connection,
    site_root: pathlib.Path,
    dto: dict[str, Any],
) -> dict[str, Any]:
    tid = str(dto.get("id") or "").strip()
    if tid:
        dto["publishedVersion"] = get_latest_template_version(conn, tid)
        dto["publishedVersions"] = list_template_versions(conn, tid, limit=8)
    opts = dto.get("options") or {}
    if opts.get("composed"):
        dto["composeChromeStatus"] = compose_chrome_status(conn, site_root, opts)
    return dto


def _hex_color(raw: Any, fallback: str) -> str:
    text = str(raw or "").strip()
    if re.fullmatch(r"#?[0-9a-fA-F]{6}", text):
        return text if text.startswith("#") else f"#{text}"
    if re.fullmatch(r"#?[0-9a-fA-F]{3}", text):
        t = text[1:] if text.startswith("#") else text
        return f"#{t[0]}{t[0]}{t[1]}{t[1]}{t[2]}{t[2]}"
    return fallback


def _cm_value(raw: Any, bounds: tuple[float, float, float]) -> float:
    lo, hi, default = bounds
    try:
        n = float(raw)
    except (TypeError, ValueError):
        return default
    if n != n:  # NaN
        return default
    return round(min(hi, max(lo, n)), 1)


def _envelope_scale(width_mm: float, height_mm: float) -> tuple[float, float]:
    """Fit the 220×100 mm landscape face into the requested stock (no overflow)."""
    face_w = max(width_mm, height_mm)
    face_h = min(width_mm, height_mm)
    return face_w / 220.0, face_h / 100.0


def normalize_options(raw: Any = None) -> dict[str, Any]:
    base = json.loads(json.dumps(DEFAULT_TEMPLATE_OPTIONS))
    data: dict[str, Any] = {}
    if isinstance(raw, dict):
        data = raw
    elif isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                data = parsed
        except json.JSONDecodeError:
            data = {}
    paper = str(data.get("paperSize") or base["paperSize"]).strip()
    if paper.lower() == "letter":
        paper = "Letter"
    else:
        paper = paper.upper()
    paper = _PAPER_ALIASES.get(paper, paper)
    if paper not in PAPER_SIZES:
        paper = base["paperSize"]
    orientation = str(data.get("orientation") or base.get("orientation") or "portrait").strip().lower()
    if orientation not in ORIENTATIONS:
        orientation = base.get("orientation") or "portrait"
    bg = str(data.get("background") or base["background"]).strip().lower()
    if bg not in BACKGROUND_STYLES:
        bg = base["background"]
    colors_in = data.get("colors") if isinstance(data.get("colors"), dict) else {}
    colors = {
        key: _hex_color(colors_in.get(key), fallback)
        for key, fallback in base["colors"].items()
    }
    out = {
        "paperSize": paper,
        "orientation": orientation,
        "background": bg,
        "customWidthCm": _cm_value(data.get("customWidthCm"), CUSTOM_W_CM),
        "customHeightCm": _cm_value(data.get("customHeightCm"), CUSTOM_H_CM),
        "colors": colors,
    }
    if data.get("composed"):
        out["composed"] = True
        out["composeChrome"] = str(data.get("composeChrome") or "").strip() or "simple"
        out["composeWatermark"] = bool(data.get("composeWatermark", True))
        fp = str(data.get("composeChromeFingerprint") or "").strip()
        if fp:
            out["composeChromeFingerprint"] = fp
        ver = data.get("composeEngineVersion")
        if ver is not None:
            try:
                out["composeEngineVersion"] = int(ver)
            except (TypeError, ValueError):
                out["composeEngineVersion"] = COMPOSE_ENGINE_VERSION
        chrome_ver = data.get("composeChromeVersion")
        if chrome_ver is not None:
            try:
                out["composeChromeVersion"] = int(chrome_ver)
            except (TypeError, ValueError):
                out["composeChromeVersion"] = 0
    if isinstance(data.get("stationery"), dict):
        out["stationery"] = normalize_stationery(data["stationery"])
    return out


STATIONERY_PAPERS: dict[str, tuple[float, float]] = {
    "A3": (297.0, 420.0),
    "A4": (210.0, 297.0),
    "A5": (148.0, 210.0),
    "A6": (105.0, 148.0),
    "B5": (176.0, 250.0),
    "Letter": (215.9, 279.4),
    "Legal": (215.9, 355.6),
    "Tabloid": (279.4, 431.8),
    "Executive": (184.2, 266.7),
}
STATIONERY_FONTS = {
    "noto": '"Noto Sans", "Segoe UI", sans-serif',
    "source": '"Source Sans 3", "Segoe UI", sans-serif',
    "georgia": 'Georgia, "Times New Roman", serif',
    "garamond": '"Cormorant Garamond", Garamond, Georgia, serif',
    "times": '"Times New Roman", Times, serif',
}
STATIONERY_BORDERS = ("none", "navy-rule", "tricolor", "gold-rule", "double-box")
_STATIONERY_URL_RE = re.compile(
    r"^(https?:\/\/|\/|data:image\/(png|jpe?g|gif|webp|svg\+xml);base64,)",
    re.I,
)


def _stationery_url(raw: Any) -> str:
    text = str(raw or "").strip()
    if text and _STATIONERY_URL_RE.match(text):
        return text
    return ""


def _stationery_num(raw: Any, lo: float, hi: float, default: float) -> float:
    try:
        n = float(raw)
    except (TypeError, ValueError):
        return default
    if n != n:
        return default
    return round(min(hi, max(lo, n)), 2)


def default_stationery() -> dict[str, Any]:
    return {
        "paper": {"id": "A4", "widthMm": 210.0, "heightMm": 297.0, "orientation": "portrait"},
        "backgroundColor": "#ffffff",
        "logo": {
            "src": "/assets/mhws-logo/mhws-logo-seal-cert.png?v=20260822logo1",
            "widthMm": 18.0,
            "align": "center",
            "enabled": True,
        },
        "headerLines": [
            {
                "text": "Mandi Housing Welfare Society",
                "font": "garamond",
                "sizePt": 15,
                "weight": "700",
                "color": "#0b2a56",
                "align": "center",
            },
            {
                "text": "Himuda Housing Colony Sanyard",
                "font": "source",
                "sizePt": 10,
                "weight": "600",
                "color": "#1a6b3a",
                "align": "center",
            },
            {
                "text": "Housing Colony Sanyard, Mandi HP 175001 · Registration No. 467 dated 21/07/2012",
                "font": "noto",
                "sizePt": 8,
                "weight": "400",
                "color": "#5a6a80",
                "align": "center",
            },
        ],
        "watermark": {
            "src": "/assets/mhws-logo/mhws-logo-watermark.png?v=20260811wm8",
            "opacity": 0.72,
            "enabled": True,
        },
        "footer": {
            "text": "Unity · Harmony · Progress · Mandi Housing Welfare Society",
            "font": "noto",
            "sizePt": 8,
            "weight": "600",
            "color": "#5a6a80",
        },
        "border": {"style": "tricolor"},
    }


def normalize_stationery(raw: Any = None) -> dict[str, Any]:
    base = default_stationery()
    data = raw if isinstance(raw, dict) else {}
    paper_in = data.get("paper") if isinstance(data.get("paper"), dict) else {}
    paper_id = str(paper_in.get("id") or "A4").strip()
    known = STATIONERY_PAPERS.get(paper_id)
    custom = paper_id == "CUSTOM" or known is None and paper_in.get("widthMm")
    if custom:
        paper_id = "CUSTOM"
        width_mm = _stationery_num(paper_in.get("widthMm"), 70, 450, 210)
        height_mm = _stationery_num(paper_in.get("heightMm"), 70, 500, 297)
    else:
        paper_id = paper_id if known else "A4"
        width_mm, height_mm = STATIONERY_PAPERS[paper_id]
    orientation = "landscape" if str(paper_in.get("orientation") or "").lower() == "landscape" else "portrait"
    if orientation == "landscape":
        width_mm, height_mm = max(width_mm, height_mm), min(width_mm, height_mm)
    logo_in = data.get("logo") if isinstance(data.get("logo"), dict) else {}
    wm_in = data.get("watermark") if isinstance(data.get("watermark"), dict) else {}
    foot_in = data.get("footer") if isinstance(data.get("footer"), dict) else {}
    border_in = data.get("border") if isinstance(data.get("border"), dict) else {}
    lines_in = data.get("headerLines") if isinstance(data.get("headerLines"), list) else base["headerLines"]
    header_lines = []
    for i, line in enumerate(lines_in[:8]):
        src = line if isinstance(line, dict) else {}
        fallback = base["headerLines"][min(i, len(base["headerLines"]) - 1)]
        align = src.get("align") if src.get("align") in ("left", "center", "right") else fallback["align"]
        weight = str(src.get("weight") or fallback["weight"])
        if weight not in {"400", "500", "600", "700"}:
            weight = fallback["weight"]
        font = src.get("font") if src.get("font") in STATIONERY_FONTS else fallback["font"]
        header_lines.append(
            {
                "text": str(src.get("text") or ""),
                "font": font,
                "sizePt": _stationery_num(src.get("sizePt"), 6, 36, fallback["sizePt"]),
                "weight": weight,
                "color": _hex_color(src.get("color"), fallback["color"]),
                "align": align,
            }
        )
    if not header_lines:
        header_lines = [dict(base["headerLines"][0], text="")]
    logo_src = _stationery_url(logo_in.get("src")) or ("" if logo_in.get("enabled") is False else base["logo"]["src"])
    wm_src = _stationery_url(wm_in.get("src")) or ("" if wm_in.get("enabled") is False else base["watermark"]["src"])
    border_style = border_in.get("style") if border_in.get("style") in STATIONERY_BORDERS else "navy-rule"
    return {
        "paper": {
            "id": paper_id,
            "widthMm": width_mm,
            "heightMm": height_mm,
            "orientation": orientation,
        },
        "backgroundColor": _hex_color(data.get("backgroundColor"), base["backgroundColor"]),
        "logo": {
            "src": logo_src,
            "widthMm": _stationery_num(logo_in.get("widthMm"), 8, 60, base["logo"]["widthMm"]),
            "align": logo_in.get("align") if logo_in.get("align") in ("left", "center", "right") else "center",
            "enabled": logo_in.get("enabled") is not False and bool(logo_src),
        },
        "headerLines": header_lines,
        "watermark": {
            "src": wm_src,
            "opacity": _stationery_num(wm_in.get("opacity"), 0.08, 1.0, base["watermark"]["opacity"]),
            "enabled": wm_in.get("enabled") is not False and bool(wm_src),
        },
        "footer": {
            "text": str(foot_in.get("text") or ""),
            "font": foot_in.get("font") if foot_in.get("font") in STATIONERY_FONTS else base["footer"]["font"],
            "sizePt": _stationery_num(foot_in.get("sizePt"), 6, 16, base["footer"]["sizePt"]),
            "weight": (
                str(foot_in.get("weight"))
                if str(foot_in.get("weight") or "") in {"400", "500", "600", "700"}
                else base["footer"]["weight"]
            ),
            "color": _hex_color(foot_in.get("color"), base["footer"]["color"]),
        },
        "border": {"style": border_style},
    }


def _stationery_border_css(style: str) -> str:
    if style == "double-box":
        return (
            ".sheet { outline: 1.4pt solid #0b2a56; outline-offset: -4mm; }\n"
            ".pad { box-shadow: inset 0 0 0 0.6pt rgba(11,42,86,0.35); }\n"
        )
    if style == "gold-rule":
        return ".mhws-st-foot { border-top: 0.8pt solid #c9a227; }\n"
    if style == "navy-rule":
        return ".mhws-st-foot { border-top: 0.7pt solid rgba(11,42,86,0.35); }\n"
    if style == "tricolor":
        return (
            ".sheet::before, .sheet::after { content: \"\"; position: absolute; top: 0; height: 2.8mm; z-index: 2; }\n"
            ".sheet::before { left: 0; width: 42%; background: #0b2a56; }\n"
            ".sheet::after { right: 0; width: 42%; background: #1a6b3a; }\n"
            ".mhws-st-accent { position: absolute; top: 0; left: 42%; width: 16%; height: 2.8mm; background: #c9a227; z-index: 2; }\n"
            ".mhws-st-head { padding-top: 4mm; }\n"
            ".mhws-st-foot { border-top: 0.7pt solid rgba(11,42,86,0.35); }\n"
        )
    return ""


def render_stationery_html(spec_in: Any, title: str = "Letterhead") -> str:
    spec = normalize_stationery(spec_in)
    w = spec["paper"]["widthMm"]
    h = spec["paper"]["heightMm"]
    heading = _html_escape(title or "Letterhead")
    logo = spec["logo"]
    logo_html = (
        f'<img class="mhws-st-logo" src="{_html_escape(logo["src"])}" alt="" style="width:{logo["widthMm"]:g}mm">'
        if logo.get("enabled") and logo.get("src")
        else ""
    )
    lines = []
    for line in spec["headerLines"]:
        font = STATIONERY_FONTS.get(line["font"], STATIONERY_FONTS["noto"])
        text = _html_escape(line["text"]) or "&nbsp;"
        lines.append(
            f'<p class="mhws-st-line" style="font-family:{font};font-size:{line["sizePt"]:g}pt;'
            f'font-weight:{line["weight"]};color:{line["color"]};text-align:{line["align"]}">{text}</p>'
        )
    head_align = logo.get("align") if logo.get("align") in ("left", "right") else "center"
    titles = f'<div class="mhws-st-titles">{"".join(lines)}</div>'
    if head_align == "left":
        head_inner = f"{logo_html}{titles}"
        head_layout = "grid-template-columns:auto 1fr;align-items:center;gap:6mm;"
        head_display = "grid"
    elif head_align == "right":
        head_inner = f"{titles}{logo_html}"
        head_layout = "grid-template-columns:1fr auto;align-items:center;gap:6mm;"
        head_display = "grid"
    else:
        head_inner = f"{logo_html}{titles}"
        head_layout = "flex-direction:column;align-items:center;text-align:center;gap:2.5mm;"
        head_display = "flex"
    wm = spec["watermark"]
    wm_html = (
        f'<img class="wm" src="{_html_escape(wm["src"])}" alt="" style="opacity:{wm["opacity"]:g}">'
        if wm.get("enabled") and wm.get("src")
        else ""
    )
    foot = spec["footer"]
    foot_font = STATIONERY_FONTS.get(foot["font"], STATIONERY_FONTS["noto"])
    foot_html = (
        f'<footer class="mhws-st-foot" style="font-family:{foot_font};font-size:{foot["sizePt"]:g}pt;'
        f'font-weight:{foot["weight"]};color:{foot["color"]}">{_html_escape(foot["text"])}</footer>'
        if foot.get("text")
        else '<footer class="mhws-st-foot"></footer>'
    )
    accent = '<div class="mhws-st-accent"></div>' if spec["border"]["style"] == "tricolor" else ""
    css = f"""
    @page {{ size: {w:g}mm {h:g}mm; margin: 0; }}
    * {{ box-sizing: border-box; }}
    html, body {{ margin: 0; padding: 0; background: #c5cdd8; }}
    .sheet {{
      position: relative; width: {w:g}mm; min-height: {h:g}mm; margin: 0 auto;
      background: {spec["backgroundColor"]}; overflow: hidden;
    }}
    .pad {{
      position: relative; z-index: 1; display: flex; flex-direction: column;
      min-height: {h:g}mm; padding: 8mm 12mm 0;
    }}
    .mhws-st-head {{ display: {head_display}; {head_layout} padding-bottom: 3.5mm; }}
    .mhws-st-logo {{ display: block; height: auto; border: 0; background: transparent; }}
    .mhws-st-titles {{ min-width: 0; width: 100%; }}
    .mhws-st-line {{ margin: 0 0 1mm; line-height: 1.25; }}
    .rule {{
      display: grid;
      grid-template-columns: 1fr auto 1fr;
      align-items: center;
      gap: 3mm;
      margin: 0 0 2.2mm;
      width: 100%;
    }}
    .rule::before, .rule::after {{
      content: "";
      height: 0;
      border-top: 1pt solid #0b2a56;
    }}
    .rule .pip {{
      width: 2.2mm;
      height: 2.2mm;
      background: #c9a227;
      transform: rotate(45deg);
      box-shadow: 0 0 0 1.2pt #fff, 0 0 0 1.7pt rgba(11, 42, 86, 0.35);
    }}
    .mhws-header-gold-rule {{ display: none !important; }}
    .body-area {{ flex: 1 1 auto; min-height: 40mm; }}
    .mhws-st-foot {{ margin-top: auto; padding: 3mm 0 8mm; text-align: center; }}
    img.wm {{
      position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%);
      width: min(112mm, 68%); height: auto; pointer-events: none; z-index: 0;
    }}
    {_stationery_border_css(spec["border"]["style"])}
    """
    return f"""<!DOCTYPE html>
<html lang="en" class="mhws-stationery-pad">
<head>
  <meta charset="UTF-8">
  <title>{heading}</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@700&family=Noto+Sans:wght@400;500;600;700&family=Source+Sans+3:wght@400;600;700&display=swap" rel="stylesheet">
  <style>{css}</style>
</head>
<body>
  <div class="sheet">
    {accent}
    {wm_html}
    <div class="pad">
      <header class="mhws-st-head is-{head_align}">{head_inner}</header>
      <div class="rule" aria-hidden="true"><span class="pip"></span></div>
      <div class="body-area"></div>
      {foot_html}
    </div>
  </div>
</body>
</html>
"""


def stationery_paper_options(spec: dict[str, Any] | None) -> dict[str, Any]:
    """Map a stationery spec onto the existing print-options fields."""
    data = normalize_stationery(spec)
    paper_id = data["paper"]["id"]
    width_cm = round(float(data["paper"]["widthMm"]) / 10.0, 1)
    height_cm = round(float(data["paper"]["heightMm"]) / 10.0, 1)
    mapped = paper_id if paper_id in PAPER_SIZES else "CUSTOM"
    return {
        "paperSize": mapped,
        "orientation": data["paper"]["orientation"],
        "background": "watermark" if data["watermark"].get("enabled") else "none",
        "customWidthCm": width_cm,
        "customHeightCm": height_cm,
        "stationery": data,
    }


def option_presets() -> dict[str, Any]:
    return {
        "paperSizes": [{"id": s, "label": PAPER_SIZE_LABELS.get(s, s)} for s in PAPER_SIZES],
        "backgrounds": [
            {"id": "watermark", "label": "Watermark"},
            {"id": "none", "label": "No watermark"},
            {"id": "plain", "label": "Plain white"},
        ],
        "defaults": DEFAULT_TEMPLATE_OPTIONS,
        "customSize": {
            "widthCm": {"min": CUSTOM_W_CM[0], "max": CUSTOM_W_CM[1], "default": CUSTOM_W_CM[2]},
            "heightCm": {"min": CUSTOM_H_CM[0], "max": CUSTOM_H_CM[1], "default": CUSTOM_H_CM[2]},
        },
    }


def seed_default_templates(conn: sqlite3.Connection, site_root: pathlib.Path) -> None:
    """Insert built-in static templates once (idempotent by id)."""
    ensure_print_templates_table(conn)
    now = utc_now()
    for item in _SEED_TEMPLATES:
        existing = conn.execute(
            "SELECT id FROM print_templates WHERE id = ?",
            (item["id"],),
        ).fetchone()
        if existing:
            continue
        path = pathlib.Path(site_root) / item["static_path"]
        size = path.stat().st_size if path.is_file() else None
        mime = TEMPLATE_EXT_MIME.get(path.suffix.lower(), "text/html")
        options = item.get("options") or DEFAULT_TEMPLATE_OPTIONS
        conn.execute(
            """
            INSERT INTO print_templates(
              id, title, description, category, tags_json, doc_type,
              filename, original_name, mime_type, size_bytes, static_path,
              options_json, status, created_by, created_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                item["id"],
                item["title"],
                item.get("description") or "",
                item.get("category") or "other",
                json.dumps(item.get("tags") or [], ensure_ascii=False),
                "static",
                path.name if path.is_file() else None,
                path.name if path.is_file() else None,
                mime,
                size,
                item["static_path"],
                json.dumps(normalize_options(options), ensure_ascii=False),
                "published",
                "system",
                now,
                now,
            ),
        )
    conn.commit()


def templates_dir(site_root: pathlib.Path) -> pathlib.Path:
    path = pathlib.Path(site_root) / "data" / "templates"
    path.mkdir(parents=True, exist_ok=True)
    return path


def template_item_dir(site_root: pathlib.Path, template_id: str) -> pathlib.Path:
    safe = re.sub(r"[^a-zA-Z0-9_-]", "", (template_id or "").strip())
    if not safe:
        raise ValueError("Invalid template id")
    path = templates_dir(site_root) / safe
    path.mkdir(parents=True, exist_ok=True)
    return path


def categories() -> list[dict[str, str]]:
    return [{"id": k, "label": lab} for k, lab in TEMPLATE_CATEGORIES]


def document_starters() -> list[dict[str, Any]]:
    from rwa_template_starters import list_document_starters

    return list_document_starters()


def compose_chromes(conn: sqlite3.Connection, site_root: pathlib.Path) -> list[dict[str, Any]]:
    """Pads with a `.body-area` writing slot, plus simple header/footer and no-template wraps."""
    ensure_print_templates_table(conn)
    seed_default_templates(conn, site_root)
    seed_template_versions(conn, site_root)
    preferred = ("tpl-mhws-letterhead", "tpl-rwa-letterhead-blank")
    found: dict[str, dict[str, Any]] = {}
    rows = conn.execute(
        """
        SELECT * FROM print_templates
        WHERE status IN ('published', 'draft')
        ORDER BY updated_at DESC
        """
    ).fetchall()
    for row in rows:
        doc = _row_to_dto(row, site_root)
        opts = doc.get("options") or {}
        stationery = opts.get("stationery") if isinstance(opts.get("stationery"), dict) else None
        raw = ""
        if stationery:
            raw = render_stationery_html(stationery, doc.get("title") or "Letterhead")
        else:
            path = resolve_template_file(site_root, doc)
            if not path or path.suffix.lower() not in {".html", ".htm"}:
                continue
            try:
                raw = path.read_text(encoding="utf-8")
            except OSError:
                continue
            if not re.search(r"\bbody-area\b", raw, re.I):
                continue
        paper = (stationery or {}).get("paper") or {}
        found[str(doc["id"])] = {
            "id": doc["id"],
            "title": {
                "tpl-mhws-letterhead": "Official letterhead",
                "tpl-rwa-letterhead-blank": "Blank letterhead",
            }.get(str(doc["id"]), doc.get("title") or doc["id"]),
            "hasWatermark": bool(re.search(r"""class=["'][^"']*\bwm\b""", raw, re.I)),
            "category": doc.get("category") or "",
            "headerHtml": "",
            "footerHtml": "",
            "chromeCss": "",
            "watermarkUrl": "",
            "paperId": paper.get("id") or "A4",
            "widthMm": paper.get("widthMm") or 210,
            "heightMm": paper.get("heightMm") or 297,
            "fingerprint": compute_chrome_fingerprint(conn, site_root, str(doc["id"])),
            "publishedVersion": get_latest_template_version(conn, str(doc["id"])),
        }
        try:
            from rwa_compose_export import extract_pad_chrome, rewrite_pad_urls, strip_screen_chrome

            pad_html, _dto = render_template_html(
                conn,
                site_root,
                str(doc["id"]),
                options_override={
                    "paperSize": "A4",
                    "orientation": "portrait",
                    "background": "none",
                },
            )
            parts = extract_pad_chrome(rewrite_pad_urls(strip_screen_chrome(pad_html)))
            found[str(doc["id"])]["headerHtml"] = parts.get("headerHtml") or ""
            found[str(doc["id"])]["footerHtml"] = parts.get("footerHtml") or ""
            found[str(doc["id"])]["chromeCss"] = parts.get("chromeCss") or ""
            found[str(doc["id"])]["watermarkUrl"] = parts.get("watermarkUrl") or ""
        except Exception:
            try:
                from rwa_compose_export import extract_pad_chrome, rewrite_pad_urls, strip_screen_chrome

                parts = extract_pad_chrome(rewrite_pad_urls(strip_screen_chrome(raw)))
                found[str(doc["id"])]["headerHtml"] = parts.get("headerHtml") or ""
                found[str(doc["id"])]["footerHtml"] = parts.get("footerHtml") or ""
                found[str(doc["id"])]["chromeCss"] = parts.get("chromeCss") or found[str(doc["id"])].get("chromeCss") or ""
                if parts.get("watermarkUrl"):
                    found[str(doc["id"])]["watermarkUrl"] = parts["watermarkUrl"]
            except Exception:
                pass
    ordered: list[dict[str, Any]] = []
    for tid in preferred:
        if tid in found:
            ordered.append(found.pop(tid))
    letterheads = [item for item in found.values() if item.get("category") == "letterhead"]
    rest = [item for item in found.values() if item.get("category") != "letterhead"]
    ordered.extend(letterheads)
    ordered.extend(rest)
    ordered.append({"id": "simple", "title": "Simple header & footer", "hasWatermark": False, "category": ""})
    ordered.append({
        "id": "none",
        "title": "No template",
        "hasWatermark": False,
        "category": "",
        "headerHtml": "",
        "footerHtml": "",
        "chromeCss": "",
        "watermarkUrl": "",
    })
    from rwa_compose_export import COMPOSE_CHROME_LAYOUT_CSS, PLAIN_CHROME_IDS

    layout_css = re.sub(r"</?style[^>]*>", "", COMPOSE_CHROME_LAYOUT_CSS).strip()
    for item in ordered:
        if item.get("id") in PLAIN_CHROME_IDS:
            continue
        if item.get("headerHtml") or item.get("footerHtml"):
            item["chromeCss"] = f"{(item.get('chromeCss') or '').strip()}\n{layout_css}".strip()
    return ordered


_COMPOSE_BLOCK_RE = re.compile(
    r"<(script|iframe|object|embed|link|meta)(\s[^>]*)?>[\s\S]*?</\1\s*>",
    re.I,
)
_COMPOSE_VOID_RE = re.compile(
    r"<(script|iframe|object|embed|link|meta)(\s[^>]*)?/?>",
    re.I,
)
_COMPOSE_ONATTR_RE = re.compile(r"\son[a-z]+\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)", re.I)
_MHWS_MARGINS_RE = re.compile(
    r"<!--\s*mhws-margins:([\d.]+),([\d.]+),([\d.]+),([\d.]+)\s*-->",
    re.I,
)


def parse_doc_margins_mm(html: str) -> dict[str, float]:
    """Page margins saved by the composer: top, right, bottom, left in mm."""
    out = {"top": 16.0, "right": 16.0, "bottom": 16.0, "left": 16.0}
    match = _MHWS_MARGINS_RE.search(html or "")
    if not match:
        return out
    for i, key in enumerate(("top", "right", "bottom", "left"), start=1):
        try:
            val = float(match.group(i))
        except ValueError:
            continue
        if 0 <= val <= 50:
            out[key] = val
    return out


def compose_body_margins_mm(body_html: str, chrome_id: str) -> dict[str, float]:
    """Top/bottom are zero when a letterhead template is applied; sides stay as saved."""
    from rwa_compose_export import PLAIN_CHROME_IDS

    margins = parse_doc_margins_mm(body_html)
    if str(chrome_id or "").strip() not in PLAIN_CHROME_IDS:
        margins["top"] = 0.0
        margins["bottom"] = 0.0
    return margins


def sanitize_compose_html(raw: str) -> str:
    html = str(raw or "")
    from rwa_compose_export import strip_pager_markup

    html = strip_pager_markup(html)
    html = _COMPOSE_BLOCK_RE.sub("", html)
    html = _COMPOSE_VOID_RE.sub("", html)
    html = _COMPOSE_ONATTR_RE.sub("", html)
    html = html.replace("javascript:", "")
    text = re.sub(r"<[^>]+>", " ", html)
    if not re.sub(r"\s+", "", text) and "<" not in (raw or ""):
        html = f"<p>{_html_escape(str(raw or '').strip())}</p>" if str(raw or "").strip() else "<p></p>"
    return html.strip() or "<p></p>"


def compute_chrome_fingerprint(
    conn: sqlite3.Connection,
    site_root: pathlib.Path,
    chrome_id: str,
) -> str:
    """Stable fingerprint for the chrome template at save/render time."""
    from rwa_compose_export import PLAIN_CHROME_IDS

    cid = str(chrome_id or "simple").strip() or "simple"
    if cid in PLAIN_CHROME_IDS or cid == "simple":
        return f"{cid}:engine{COMPOSE_ENGINE_VERSION}"
    try:
        doc = get_template(conn, cid, site_root=site_root)
    except Exception:
        doc = None
    if doc and isinstance(doc.get("options"), dict) and doc["options"].get("stationery"):
        spec = normalize_stationery(doc["options"]["stationery"])
        blob = json.dumps(spec, sort_keys=True, ensure_ascii=False)
        digest = hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]
        return f"stationery:{cid}:{digest}"
    if doc and doc.get("staticPath"):
        rel = _safe_static_path(doc.get("staticPath"))
        if rel:
            path = pathlib.Path(site_root) / rel
            if path.is_file():
                digest = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
                return f"static:{cid}:{digest}"
    path = resolve_template_file(site_root, doc or {})
    if path and path.is_file():
        digest = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
        return f"file:{cid}:{digest}"
    return f"{cid}:engine{COMPOSE_ENGINE_VERSION}"


def read_compose_body_fragment(site_root: pathlib.Path, template_id: str) -> str:
    """Load editable body HTML for a composed library document."""
    from rwa_compose_export import extract_compose_body_from_html

    root = pathlib.Path(site_root).resolve()
    dest_dir = template_item_dir(root, template_id)
    body_path = dest_dir / COMPOSE_BODY_STORE
    if body_path.is_file():
        return body_path.read_text(encoding="utf-8")
    legacy = dest_dir / "doc.html"
    if legacy.is_file():
        return extract_compose_body_from_html(legacy.read_text(encoding="utf-8"))
    return "<p></p>"


def render_saved_compose_html(
    conn: sqlite3.Connection,
    site_root: pathlib.Path,
    doc: dict[str, Any],
) -> str:
    """Wrap a saved composed document using its pinned chrome options."""
    options = normalize_options(doc.get("options"))
    if not options.get("composed"):
        path = resolve_template_file(site_root, doc)
        if path and path.is_file():
            return path.read_text(encoding="utf-8")
        return "<p></p>"
    body = read_compose_body_fragment(site_root, str(doc.get("id") or ""))
    chrome = str(options.get("composeChrome") or "simple")
    watermark = options.get("composeWatermark", True)
    chrome_ver = int(options.get("composeChromeVersion") or 0)
    return wrap_composed_document(
        title=str(doc.get("title") or "Document"),
        body_html=body,
        chrome=chrome,
        watermark=watermark,
        site_root=site_root,
        conn=conn,
        chrome_version=chrome_ver or None,
    )


def wrap_composed_document(
    *,
    title: str,
    body_html: str,
    chrome: str = "simple",
    watermark: bool | None = True,
    site_root: pathlib.Path | None = None,
    conn: sqlite3.Connection | None = None,
    chrome_version: int | None = None,
) -> str:
    from rwa_compose_export import (
        COMPOSE_PAD_BODY_CSS,
        PLAIN_CHROME_IDS,
        as_bool,
        embed_local_asset_urls,
        inject_body_area,
        inject_compose_chrome_layout,
        inject_compose_page_extras,
        inject_compose_pdf_css,
        paginate_pad_html,
        rewrite_pad_urls,
        set_html_title,
        strip_base_tag,
        strip_screen_chrome,
    )

    heading = _html_escape((title or "Document").strip() or "Document")
    chrome_id = str(chrome or "simple").strip() or "simple"
    margins = compose_body_margins_mm(body_html, chrome_id)
    body = sanitize_compose_html(body_html)
    show_wm = as_bool(watermark, True)
    if chrome_id in PLAIN_CHROME_IDS:
        page_margin = (
            f'{margins["top"]:g}mm {margins["right"]:g}mm '
            f'{margins["bottom"]:g}mm {margins["left"]:g}mm'
        )
        plain = f"""<!DOCTYPE html>
<html lang="en" class="mhws-compose-multipage">
<head>
  <meta charset="UTF-8">
  <title>{heading}</title>
  <style>
    @page {{ size: 210mm 297mm; margin: 0; }}
    * {{ box-sizing: border-box; }}
    html, body {{
      margin: 0;
      padding: 0;
      width: 210mm;
      color: #12233f;
      font: 11pt/1.45 "Source Sans 3", "Segoe UI", Georgia, serif;
      background: #fff;
    }}
    .body {{ padding: {page_margin}; }}
    .body p {{ margin: 0 0 8pt; }}
    .body h2 {{ margin: 0 0 8pt; font-size: 18pt; font-weight: 700; color: #0b2a56; }}
    .body h3 {{ margin: 0 0 6pt; font-size: 14pt; font-weight: 700; color: #143a6e; }}
    .body h2 span, .body h3 span {{ font-size: inherit; font-weight: inherit; color: inherit; }}
    .body .mhws-tab {{ white-space: pre; tab-size: 4; }}
    .body .mhws-img-pair {{ display: flex; align-items: stretch; gap: 10pt; width: 100%; margin: 0 0 8pt; }}
    .body table {{ border-collapse: collapse; width: 100%; margin: 8pt 0; }}
    .body th, .body td {{ border: 0.6pt solid #0b2a56; padding: 4pt 6pt; vertical-align: top; }}
    .body th {{ background: #eef2f8; }}
    .body table.mhws-table-noborder th,
    .body table.mhws-table-noborder td {{ border: 0 !important; }}
    .body img {{ max-width: 100%; height: auto; }}
    .body .mhws-img {{ max-width: 100%; }}
    .body .mhws-img img {{ width: 100%; height: auto; display: block; }}
  </style>
</head>
<body>
  <div class="body">{body}</div>
</body>
</html>
""".strip()
        return embed_local_asset_urls(
            inject_compose_page_extras(
                inject_compose_pdf_css(plain), "none", margins, watermark=False
            ),
            site_root,
        )
    if chrome_id != "simple" and conn is not None and site_root is not None:
        pad_html = ""
        if chrome_version:
            snap = load_template_version_html(conn, chrome_id, int(chrome_version))
            if snap:
                pad_html = snap
        try:
            if not pad_html:
                pad_html, _doc = render_template_html(
                    conn,
                    site_root,
                    chrome_id,
                    options_override={
                        "paperSize": "A4",
                        "orientation": "portrait",
                        "background": "watermark" if show_wm else "none",
                    },
                )
        except ValueError:
            pad_html = ""
        if pad_html:
            pad_html = embed_local_asset_urls(
                strip_base_tag(rewrite_pad_urls(strip_screen_chrome(pad_html))),
                site_root,
            )
            injected = inject_body_area(pad_html, body)
            if injected:
                injected = paginate_pad_html(injected)
                pad_css = COMPOSE_PAD_BODY_CSS.replace(
                    ".body-area p {",
                    f".body-area {{ padding: {margins['top']:g}mm {margins['right']:g}mm "
                    f"{margins['bottom']:g}mm {margins['left']:g}mm; }}\n  .body-area p {{",
                    1,
                )
                if "</head>" in injected:
                    injected = injected.replace("</head>", pad_css + "\n</head>", 1)
                injected = inject_compose_page_extras(
                    inject_compose_pdf_css(injected),
                    chrome_id,
                    margins,
                    watermark=show_wm,
                )
                return set_html_title(inject_compose_chrome_layout(injected), title)

    page_margin = (
        f'{margins["top"]:g}mm {margins["right"]:g}mm '
        f'{margins["bottom"]:g}mm {margins["left"]:g}mm'
    )
    brand = load_society_branding(pathlib.Path(site_root)) if site_root else load_society_branding(_veercanvas_root())
    try:
        branding_py = _veercanvas_root() / "core" / "document-engine" / "branding.py"
        import importlib.util

        spec = importlib.util.spec_from_file_location("veer_document_branding_shell", branding_py)
        if spec and spec.loader:
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            header_inner, foot_inner, logo_src = mod.simple_compose_shell_html(brand, body, page_margin)
        else:
            raise RuntimeError("branding module missing")
    except Exception:
        society = brand.get("societyName") or "Society"
        colony = brand.get("colonyName") or society
        meta_line = brand.get("metaLine") or ""
        footer = brand.get("footerLine") or society
        logo_src = brand.get("logoPrint") or "/assets/favicon-192.png"
        header_inner = (
            f"<header class=\"org\">"
            f"<img src=\"{_html_escape(str(logo_src))}\" alt=\"\">"
            f"<h1>{_html_escape(str(society))}</h1>"
            f"<p class=\"sub\">{_html_escape(str(colony))}</p>"
        )
        if meta_line:
            header_inner += f"<p class=\"meta\">{_html_escape(str(meta_line))}</p>"
        header_inner += "</header>"
        foot_inner = f"<footer class=\"foot\">{_html_escape(str(footer))}</footer>"
    simple = f"""<!DOCTYPE html>
<html lang="en" class="mhws-compose-multipage">
<head>
  <meta charset="UTF-8">
  <title>{heading}</title>
  <style>
    @page {{ size: 210mm 297mm; margin: 0; }}
    * {{ box-sizing: border-box; }}
    html, body {{
      margin: 0;
      padding: 0;
      width: 210mm;
      color: #12233f;
      font: 11pt/1.45 "Source Sans 3", "Segoe UI", Georgia, serif;
      background: #fff;
    }}
    .org {{
      text-align: center;
      padding: 5mm 12mm 2pt;
    }}
    .org img {{ width: 14mm; height: auto; border: 0; outline: 0; box-shadow: none; background: transparent; }}
    .org h1 {{
      margin: 3pt 0 0;
      font-size: 13pt;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      color: #0b2a56;
    }}
    .org .sub {{ margin: 1.5pt 0 0; font-size: 9pt; font-weight: 600; color: #1a6b3a; }}
    .org .meta {{ margin: 1.5pt 0 0; font-size: 7.5pt; color: #5a6a80; }}
    .body {{ padding: {page_margin}; }}
    .body p {{ margin: 0 0 8pt; }}
    .body h2 {{ margin: 0 0 8pt; font-size: 18pt; font-weight: 700; color: #0b2a56; }}
    .body h3 {{ margin: 0 0 6pt; font-size: 14pt; font-weight: 700; color: #143a6e; }}
    .body h2 span, .body h3 span {{ font-size: inherit; font-weight: inherit; color: inherit; }}
    .body .mhws-tab {{ white-space: pre; tab-size: 4; }}
    .body .mhws-img-pair {{ display: flex; align-items: stretch; gap: 10pt; width: 100%; margin: 0 0 8pt; }}
    .body table {{ border-collapse: collapse; width: 100%; margin: 8pt 0; }}
    .body th, .body td {{ border: 0.6pt solid #0b2a56; padding: 4pt 6pt; vertical-align: top; }}
    .body th {{ background: #eef2f8; }}
    .body table.mhws-table-noborder th,
    .body table.mhws-table-noborder td {{ border: 0 !important; }}
    .body img {{ max-width: 100%; height: auto; }}
    .body .mhws-img {{ max-width: 100%; }}
    .body .mhws-img img {{ width: 100%; height: auto; display: block; }}
    .foot {{
      padding: 6pt 12mm 10mm;
      border-top: 0.7pt solid rgba(11,42,86,0.35);
      font-size: 8pt;
      color: #5a6a80;
      text-align: center;
    }}
  </style>
</head>
<body>
  <div class="mhws-run-header">
    <div class="mhws-simple-chrome">
    {header_inner}
    <div class="rule" aria-hidden="true"><span class="pip"></span></div>
    </div>
  </div>
  <div class="body">{body}</div>
  <div class="mhws-run-footer">
    {foot_inner}
  </div>
</body>
</html>
""".strip()
    wrapped = embed_local_asset_urls(
        inject_compose_chrome_layout(
            inject_compose_page_extras(inject_compose_pdf_css(simple), "simple", margins, watermark=False)
        ),
        site_root,
    )
    if "</head>" in wrapped and 'id="mhws-compose-body"' not in wrapped:
        wrapped = wrapped.replace("</head>", COMPOSE_PAD_BODY_CSS + "\n</head>", 1)
    return wrapped


def export_composed_document(
    conn: sqlite3.Connection,
    site_root: pathlib.Path,
    *,
    title: str,
    body_html: str,
    fmt: str,
    chrome: str = "simple",
    watermark: bool | None = True,
) -> tuple[bytes, str, str]:
    """Return (bytes, filename, mime) for pdf / docx / txt."""
    from rwa_compose_export import (
        as_bool,
        export_filename,
        html_fragment_to_text,
        inject_compose_pdf_css,
        wrapped_html_to_docx_bytes,
    )

    kind = str(fmt or "pdf").strip().lower()
    if kind in {"word", "doc"}:
        kind = "docx"
    if kind not in {"pdf", "docx", "txt"}:
        raise ValueError("Download as PDF, Word (.docx), or Text (.txt).")
    heading = (title or "Document").strip() or "Document"
    show_wm = as_bool(watermark, True)
    if kind == "txt":
        text = html_fragment_to_text(body_html)
        data = text.encode("utf-8")
        return data, export_filename(heading, ".txt"), "text/plain; charset=utf-8"
    html = wrap_composed_document(
        title=heading,
        body_html=body_html,
        chrome=chrome,
        watermark=show_wm,
        site_root=site_root,
        conn=conn,
    )
    if kind == "docx":
        data = wrapped_html_to_docx_bytes(html=html, site_root=site_root)
        return (
            data,
            export_filename(heading, ".docx"),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
    if kind == "pdf":
        from rwa_compose_export import finalize_compose_pdf_html

        margins = compose_body_margins_mm(body_html, chrome)
        html = finalize_compose_pdf_html(html, margins)
    html = inject_compose_pdf_css(html)
    opts = normalize_options({"paperSize": "A4", "orientation": "portrait", "background": "watermark" if show_wm else "none"})
    pdf = _html_to_pdf_weasyprint(html, site_root, opts, inject_layout=False) or _html_to_pdf_chrome(
        html, site_root, opts, inject_layout=False
    )
    if not pdf:
        raise ValueError(
            "Could not format this document as PDF. Install Chromium on the server (or set RWA_CHROME_BIN)."
        )
    return pdf, export_filename(heading, ".pdf"), "application/pdf"


def _category(raw: str | None) -> str:
    key = (raw or "other").strip().lower()
    allowed = {c[0] for c in TEMPLATE_CATEGORIES}
    return key if key in allowed else "other"


def _status(raw: str | None) -> str:
    key = (raw or "published").strip().lower()
    return key if key in {"draft", "published", "archived"} else "published"


def _parse_tags(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, list):
        items = raw
    else:
        text = str(raw).strip()
        if not text:
            return []
        if text.startswith("["):
            try:
                parsed = json.loads(text)
                items = parsed if isinstance(parsed, list) else [text]
            except json.JSONDecodeError:
                items = re.split(r"[,;]+", text)
        else:
            items = re.split(r"[,;]+", text)
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        tag = re.sub(r"\s+", " ", str(item or "").strip().lower())[:40]
        if not tag or tag in seen:
            continue
        seen.add(tag)
        out.append(tag)
        if len(out) >= 12:
            break
    return out


def _safe_static_path(raw: str | None) -> str | None:
    text = (raw or "").strip().lstrip("/")
    if not text:
        return None
    text = text.replace("\\", "/")
    if ".." in text.split("/"):
        raise ValueError("Invalid static path")
    if not any(text.startswith(p) for p in _STATIC_ALLOWED_PREFIXES):
        raise ValueError("Static path must be under documents/ or assets/")
    return text


def _new_id() -> str:
    return f"tpl-{secrets.token_hex(6)}"


def _row_to_dto(row: sqlite3.Row | dict, site_root: pathlib.Path | None = None) -> dict[str, Any]:
    data = dict(row)
    tags: list[str] = []
    try:
        parsed = json.loads(data.get("tags_json") or "[]")
        if isinstance(parsed, list):
            tags = [str(t) for t in parsed]
    except json.JSONDecodeError:
        tags = []
    cat = data.get("category") or "other"
    cat_label = next((lab for k, lab in TEMPLATE_CATEGORIES if k == cat), cat)
    options = normalize_options(data.get("options_json"))
    dto = {
        "id": data.get("id"),
        "title": data.get("title") or "",
        "description": data.get("description") or "",
        "category": cat,
        "categoryLabel": cat_label,
        "tags": tags,
        "docType": data.get("doc_type") or "file",
        "filename": data.get("filename"),
        "originalName": data.get("original_name"),
        "mimeType": data.get("mime_type"),
        "sizeBytes": data.get("size_bytes"),
        "staticPath": data.get("static_path"),
        "options": options,
        "status": data.get("status") or "published",
        "createdBy": data.get("created_by"),
        "createdAt": data.get("created_at"),
        "updatedAt": data.get("updated_at"),
        "hasFile": False,
        "publicUrl": None,
        "renderUrl": f"/api/rwa/templates/{data.get('id')}/render" if data.get("id") else None,
    }
    if site_root is not None:
        path = resolve_template_file(site_root, dto)
        dto["hasFile"] = path is not None and path.is_file()
        if dto["docType"] == "static" and dto.get("staticPath"):
            dto["publicUrl"] = "/" + str(dto["staticPath"]).lstrip("/")
    return dto


def resolve_template_file(site_root: pathlib.Path, doc: dict[str, Any]) -> pathlib.Path | None:
    root = pathlib.Path(site_root).resolve()
    if (doc.get("docType") or doc.get("doc_type")) == "static":
        rel = _safe_static_path(doc.get("staticPath") or doc.get("static_path"))
        if not rel:
            return None
        path = (root / rel).resolve()
        if not str(path).startswith(str(root)):
            return None
        return path if path.is_file() else None
    filename = doc.get("filename")
    tid = doc.get("id")
    if not filename or not tid:
        return None
    name = pathlib.Path(str(filename)).name
    if name != str(filename):
        return None
    path = template_item_dir(root, tid) / name
    return path if path.is_file() else None


def list_templates(
    conn: sqlite3.Connection,
    *,
    site_root: pathlib.Path,
    status: str | None = None,
    category: str | None = None,
) -> list[dict[str, Any]]:
    ensure_print_templates_table(conn)
    seed_default_templates(conn, site_root)
    seed_template_versions(conn, site_root)
    clauses: list[str] = []
    params: list[Any] = []
    if status and status != "all":
        clauses.append("status = ?")
        params.append(_status(status))
    if category:
        clauses.append("category = ?")
        params.append(_category(category))
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    rows = conn.execute(
        f"""
        SELECT * FROM print_templates
        {where}
        ORDER BY updated_at DESC, title COLLATE NOCASE
        """,
        params,
    ).fetchall()
    return [_enrich_template_meta(conn, site_root, _row_to_dto(r, site_root)) for r in rows]


def get_template(
    conn: sqlite3.Connection,
    template_id: str,
    *,
    site_root: pathlib.Path,
) -> dict[str, Any] | None:
    ensure_print_templates_table(conn)
    row = conn.execute(
        "SELECT * FROM print_templates WHERE id = ?",
        (template_id,),
    ).fetchone()
    if not row:
        return None
    return _enrich_template_meta(conn, site_root, _row_to_dto(row, site_root))


def upsert_template(
    conn: sqlite3.Connection,
    site_root: pathlib.Path,
    payload: dict[str, Any],
    *,
    actor_house_id: str | None,
    file_storage=None,
) -> dict[str, Any]:
    ensure_print_templates_table(conn)
    tid = (payload.get("id") or "").strip() or None
    existing = None
    if tid:
        existing = conn.execute(
            "SELECT * FROM print_templates WHERE id = ?",
            (tid,),
        ).fetchone()
        if not existing:
            raise ValueError("Template not found")
    else:
        tid = _new_id()

    title = str(payload.get("title") or (existing["title"] if existing else "")).strip()
    if not title:
        raise ValueError("Title required")
    description = str(
        payload.get("description")
        if "description" in payload
        else (existing["description"] if existing else "")
    ).strip()
    category = _category(
        payload.get("category")
        if "category" in payload
        else (existing["category"] if existing else "other")
    )
    if "tags" in payload or "tagsJson" in payload:
        tags = _parse_tags(payload.get("tags") if "tags" in payload else payload.get("tagsJson"))
    else:
        tags = _parse_tags(existing["tags_json"] if existing else "[]")
    status = _status(
        payload.get("status")
        if "status" in payload
        else (existing["status"] if existing else "published")
    )
    if "options" in payload or "optionsJson" in payload or "options_json" in payload:
        options = normalize_options(
            payload.get("options")
            if "options" in payload
            else payload.get("optionsJson", payload.get("options_json"))
        )
    else:
        options = normalize_options(existing["options_json"] if existing else None)
    options_json = json.dumps(options, ensure_ascii=False)

    doc_type = (existing["doc_type"] if existing else "file")
    filename = existing["filename"] if existing else None
    original_name = existing["original_name"] if existing else None
    mime_type = existing["mime_type"] if existing else None
    size_bytes = existing["size_bytes"] if existing else None
    static_path = existing["static_path"] if existing else None

    static_in = payload.get("staticPath") or payload.get("static_path")
    if static_in is not None and str(static_in).strip():
        static_path = _safe_static_path(str(static_in))
        path = pathlib.Path(site_root) / static_path
        if not path.is_file():
            raise ValueError(f"Static file not found: {static_path}")
        doc_type = "static"
        filename = path.name
        original_name = path.name
        mime_type = TEMPLATE_EXT_MIME.get(path.suffix.lower(), "application/octet-stream")
        size_bytes = path.stat().st_size

    html_in = None
    if any(k in payload for k in ("htmlBody", "bodyHtml", "html_body")):
        html_in = payload.get("htmlBody", payload.get("bodyHtml", payload.get("html_body")))

    if file_storage is not None and getattr(file_storage, "filename", None):
        orig = pathlib.Path(str(file_storage.filename)).name
        ext = pathlib.Path(orig).suffix.lower()
        if ext not in TEMPLATE_EXT_MIME:
            raise ValueError(
                "Unsupported file type. Use HTML, PDF, PNG, JPG, WEBP, SVG, DOC, or DOCX."
            )
        data = file_storage.read()
        if not data:
            raise ValueError("Empty file")
        if len(data) > TEMPLATE_MAX_BYTES:
            raise ValueError("File too large (max 20 MB)")
        store_name = f"doc{ext}"
        dest_dir = template_item_dir(site_root, tid)
        target = dest_dir / store_name
        tmp = dest_dir / f".{store_name}.{secrets.token_hex(4)}.tmp"
        try:
            tmp.write_bytes(data)
            tmp.replace(target)
        finally:
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass
        for old in list(dest_dir.iterdir()):
            if old.is_file() and old.name != store_name and not old.name.startswith("."):
                try:
                    old.unlink()
                except OSError:
                    pass
        doc_type = "file"
        filename = store_name
        original_name = orig
        mime_type = TEMPLATE_EXT_MIME[ext]
        size_bytes = len(data)
        static_path = None

    elif html_in is not None:
        from rwa_compose_export import as_bool

        chrome = str(payload.get("chrome") or payload.get("composeChrome") or "simple")
        watermark = as_bool(payload.get("watermark"), True)
        body_fragment = sanitize_compose_html(str(html_in or ""))
        fingerprint = compute_chrome_fingerprint(conn, pathlib.Path(site_root), chrome)
        data = body_fragment.encode("utf-8")
        if len(data) > TEMPLATE_MAX_BYTES:
            raise ValueError("Document too large (max 20 MB)")
        store_name = COMPOSE_BODY_STORE
        dest_dir = template_item_dir(site_root, tid)
        target = dest_dir / store_name
        tmp = dest_dir / f".{store_name}.{secrets.token_hex(4)}.tmp"
        try:
            tmp.write_bytes(data)
            tmp.replace(target)
        finally:
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass
        for old in list(dest_dir.iterdir()):
            if old.is_file() and old.name not in {store_name} and not old.name.startswith("."):
                try:
                    old.unlink()
                except OSError:
                    pass
        safe_title = re.sub(r"[^\w.\-]+", "_", title)[:60].strip("._") or "document"
        doc_type = "file"
        filename = store_name
        original_name = f"{safe_title}.html"
        mime_type = "text/html"
        size_bytes = len(data)
        static_path = None
        options["composed"] = True
        options["composeChrome"] = chrome
        options["composeWatermark"] = watermark
        options["composeChromeFingerprint"] = fingerprint
        options["composeEngineVersion"] = COMPOSE_ENGINE_VERSION
        chrome_ver = get_latest_template_version(conn, chrome)
        if chrome_ver:
            options["composeChromeVersion"] = chrome_ver
        options_json = json.dumps(options, ensure_ascii=False)
        if "compose" not in tags:
            tags = list(tags) + ["compose"]

    elif payload.get("stationery") is not None:
        spec = normalize_stationery(payload.get("stationery"))
        stationery_html = render_stationery_html(spec, title)
        data = stationery_html.encode("utf-8")
        if len(data) > TEMPLATE_MAX_BYTES:
            raise ValueError("Template too large (max 20 MB)")
        store_name = "doc.html"
        dest_dir = template_item_dir(site_root, tid)
        target = dest_dir / store_name
        tmp = dest_dir / f".{store_name}.{secrets.token_hex(4)}.tmp"
        try:
            tmp.write_bytes(data)
            tmp.replace(target)
        finally:
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass
        for old in list(dest_dir.iterdir()):
            if old.is_file() and old.name != store_name and not old.name.startswith("."):
                try:
                    old.unlink()
                except OSError:
                    pass
        safe_title = re.sub(r"[^\w.\-]+", "_", title)[:60].strip("._") or "letterhead"
        doc_type = "file"
        filename = store_name
        original_name = f"{safe_title}.html"
        mime_type = "text/html"
        size_bytes = len(data)
        static_path = None
        mapped = stationery_paper_options(spec)
        options.update(mapped)
        options.pop("composed", None)
        options_json = json.dumps(options, ensure_ascii=False)
        if "stationery" not in tags:
            tags = list(tags) + ["stationery"]
        if category in ("other", "correspondence") and "category" not in payload:
            category = "letterhead"

    if not existing and doc_type == "file" and not filename:
        raise ValueError("Choose a file to upload, or provide a static path under documents/")

    now = utc_now()
    created_at = existing["created_at"] if existing else now
    created_by = existing["created_by"] if existing else (actor_house_id or None)

    if existing:
        conn.execute(
            """
            UPDATE print_templates SET
              title = ?, description = ?, category = ?, tags_json = ?,
              doc_type = ?, filename = ?, original_name = ?, mime_type = ?,
              size_bytes = ?, static_path = ?, options_json = ?, status = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                title,
                description,
                category,
                json.dumps(tags, ensure_ascii=False),
                doc_type,
                filename,
                original_name,
                mime_type,
                size_bytes,
                static_path,
                options_json,
                status,
                now,
                tid,
            ),
        )
    else:
        conn.execute(
            """
            INSERT INTO print_templates(
              id, title, description, category, tags_json, doc_type,
              filename, original_name, mime_type, size_bytes, static_path,
              options_json, status, created_by, created_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                tid,
                title,
                description,
                category,
                json.dumps(tags, ensure_ascii=False),
                doc_type,
                filename,
                original_name,
                mime_type,
                size_bytes,
                static_path,
                options_json,
                status,
                created_by,
                created_at,
                now,
            ),
        )
    conn.commit()
    doc = get_template(conn, tid, site_root=site_root)
    if not doc:
        raise ValueError("Failed to save template")
    if payload.get("stationery") is not None:
        try:
            publish_template_version(conn, site_root, tid, actor=actor_house_id)
            doc = get_template(conn, tid, site_root=site_root) or doc
        except Exception:
            pass
    return doc


def delete_template(conn: sqlite3.Connection, site_root: pathlib.Path, template_id: str) -> None:
    ensure_print_templates_table(conn)
    row = conn.execute(
        "SELECT id, doc_type FROM print_templates WHERE id = ?",
        (template_id,),
    ).fetchone()
    if not row:
        raise ValueError("Template not found")
    conn.execute("DELETE FROM template_versions WHERE template_id = ?", (template_id,))
    conn.execute("DELETE FROM print_templates WHERE id = ?", (template_id,))
    conn.commit()
    if (row["doc_type"] if hasattr(row, "keys") else row[1]) == "file":
        dest = templates_dir(site_root) / re.sub(r"[^a-zA-Z0-9_-]", "", template_id)
        if dest.is_dir():
            shutil.rmtree(dest, ignore_errors=True)


def _html_escape(text: Any) -> str:
    s = "" if text is None else str(text)
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _sheet_metrics(
    options: dict[str, Any],
    *,
    landscape: bool | None = None,
    envelope: bool = False,
) -> dict[str, Any]:
    """Page box for a template: width, height, and @page size (A4 / A5 / custom / envelope)."""
    paper = options.get("paperSize") or "A4"
    orient = "landscape" if landscape else (options.get("orientation") or "portrait")
    if orient not in ORIENTATIONS:
        orient = "portrait"
    dims = {
        "A4": ("210mm", "297mm"),
        "A5": ("148mm", "210mm"),
        "A6": ("105mm", "148mm"),
        "Letter": ("8.5in", "11in"),
    }.get(paper, ("210mm", "297mm"))
    sheet_w, sheet_h = dims
    if orient == "landscape":
        sheet_w, sheet_h = sheet_h, sheet_w
    page_size = f"{paper if paper != 'Letter' else 'letter'} {orient}"
    env_scale = 1.0
    fit_x, fit_y = 1.0, 1.0
    if envelope:
        env_key = {
            "A6": "C6",
            "A5": "C5",
            "A4": "C4",
            "C6": "C6",
            "C5": "C5",
            "C4": "C4",
            "E2210": "E2210",
            "22X10": "E2210",
            "CUSTOM": "CUSTOM",
        }.get(paper, "E2210")
        env_dims = {
            "C6": (162.0, 114.0),
            "C5": (229.0, 162.0),
            "C4": (324.0, 229.0),
            "E2210": (220.0, 100.0),
        }
        if env_key == "CUSTOM":
            w_cm = _cm_value(options.get("customWidthCm"), CUSTOM_W_CM)
            h_cm = _cm_value(options.get("customHeightCm"), CUSTOM_H_CM)
            w_mm, h_mm = w_cm * 10.0, h_cm * 10.0
        else:
            w_mm, h_mm = env_dims.get(env_key, env_dims["E2210"])
        face_w, face_h = max(w_mm, h_mm), min(w_mm, h_mm)
        fit_x, fit_y = _envelope_scale(face_w, face_h)
        env_scale = min(fit_x, fit_y)
        sheet_w, sheet_h = f"{face_w:g}mm", f"{face_h:g}mm"
        page_size = f"{sheet_w} {sheet_h}"
    return {
        "sheet_w": sheet_w,
        "sheet_h": sheet_h,
        "page_size": page_size,
        "orient": orient,
        "env_scale": env_scale,
        "fit_x": fit_x,
        "fit_y": fit_y,
    }


def _pdf_page_layout_css(
    options: dict[str, Any],
    *,
    envelope: bool = False,
    mom: bool = False,
    receipt: bool = False,
) -> str:
    """Force the mailed PDF onto the chosen paper and pin the footer to the page bottom.

    Pad CSS relies on flex `margin-top: auto` / `flex: 1` to push the footer down.
    WeasyPrint (and some print stylesheets) collapse that, so the footer sits under
    the header. Absolute positioning against the real page box honours A4/A5/etc.
    """
    metrics = _sheet_metrics(options, landscape=True if envelope else None, envelope=envelope)
    w, h = metrics["sheet_w"], metrics["sheet_h"]
    page_size = f"{w} {h}"
    if receipt:
        return f"""
<style id="tpl-pdf-page">
  @page {{ size: {page_size}; margin: 0; }}
</style>
""".strip()
    if envelope:
        return f"""
<style id="tpl-pdf-page">
  @page {{ size: {page_size}; margin: 0; }}
  html, body {{
    width: {w} !important;
    height: {h} !important;
    margin: 0 !important;
    padding: 0 !important;
    background: #fff !important;
  }}
  .screen-hint {{ display: none !important; }}
  .sheet {{
    position: relative !important;
    width: {w} !important;
    height: {h} !important;
    min-height: {h} !important;
    max-height: {h} !important;
    margin: 0 !important;
  }}
  .pad {{ position: static !important; }}
  .foot, footer.foot {{
    position: absolute !important;
    left: 0 !important;
    right: 0 !important;
    bottom: 0 !important;
    width: 100% !important;
    margin: 0 !important;
  }}
</style>
""".strip()
    if mom:
        return f"""
<style id="tpl-pdf-page">
  @page {{ size: {page_size}; margin: 0; }}
  html, body {{
    width: {w} !important;
    margin: 0 !important;
    padding: 0 !important;
    background: #fff !important;
  }}
  .screen-hint {{ display: none !important; }}
  .sheet {{
    position: relative !important;
    display: flex !important;
    flex-direction: column !important;
    width: {w} !important;
    height: {h} !important;
    min-height: {h} !important;
    max-height: {h} !important;
    margin: 0 !important;
    overflow: hidden !important;
    page-break-after: always;
    break-after: page;
  }}
  .sheet:last-of-type {{
    page-break-after: auto;
    break-after: auto;
  }}
  .pad {{
    position: relative !important;
    flex: 1 1 auto !important;
    display: flex !important;
    flex-direction: column !important;
    min-height: 0 !important;
    padding-bottom: 9mm !important;
    box-sizing: border-box !important;
  }}
  .grow {{
    flex: 1 1 auto !important;
    min-height: 0 !important;
  }}
  .grow .ruled-block.xl,
  .grow .ruled-block.xxl {{
    flex: 1 1 auto !important;
    min-height: 24mm !important;
  }}
  .foot-bar {{
    position: absolute !important;
    left: -11mm !important;
    right: -11mm !important;
    bottom: 0 !important;
    margin: 0 !important;
    z-index: 2 !important;
  }}
</style>
""".strip()
    return f"""
<style id="tpl-pdf-page">
  @page {{ size: {page_size}; margin: 0; }}
  html, body,
  html.pad-a4-full, html.pad-a4-full body {{
    width: {w} !important;
    height: {h} !important;
    min-height: {h} !important;
    max-height: {h} !important;
    margin: 0 !important;
    padding: 0 !important;
    overflow: hidden !important;
    background: #fff !important;
  }}
  .screen-hint, .layout-picker {{ display: none !important; }}
  .sheet,
  html.pad-a4-full .sheet {{
    position: relative !important;
    width: {w} !important;
    height: {h} !important;
    min-height: {h} !important;
    max-height: {h} !important;
    margin: 0 !important;
    overflow: hidden !important;
  }}
  html.pad-a4-full .pad {{
    position: static !important;
    height: auto !important;
    min-height: 0 !important;
    max-height: none !important;
    flex: none !important;
    padding-bottom: 34mm !important;
    overflow: visible !important;
  }}
  html.pad-a4-full .body-area,
  html.pad-a4-full .body-spacer {{
    min-height: 0 !important;
    max-height: none !important;
    flex: none !important;
  }}
  .foot, footer.foot, .foot-bar {{
    position: absolute !important;
    left: 0 !important;
    right: 0 !important;
    bottom: 0 !important;
    width: 100% !important;
    margin: 0 !important;
    flex: none !important;
  }}
  html.pad-a4-full .foot .contacts {{
    padding-left: 12mm;
    padding-right: 12mm;
  }}
  html.pad-a4-full .foot .slogan-bar,
  html.pad-a4-blank .slogan-bar {{
    margin-left: 0 !important;
    margin-right: 0 !important;
  }}
  html.pad-a4-blank .slogan-bar {{
    position: absolute !important;
    left: 0 !important;
    right: 0 !important;
    bottom: 0 !important;
    width: 100% !important;
  }}
</style>
""".strip()


def _inject_pdf_page_css(html: str, options: dict[str, Any] | None = None) -> str:
    text = html or ""
    if "mhws-print-pages" in text or "mhws-compose-multipage" in text:
        from rwa_compose_export import inject_compose_pdf_css

        return inject_compose_pdf_css(text)
    opts = normalize_options(options)
    envelope = bool(re.search(r"envelope-pad", html, re.I))
    mom = bool(re.search(r"pad-mom", html, re.I))
    receipt = bool(re.search(r"pad-receipt", html, re.I))
    css = _pdf_page_layout_css(opts, envelope=envelope, mom=mom, receipt=receipt)
    if "</head>" in html:
        return html.replace("</head>", f"{css}\n</head>", 1)
    return css + html


def _runtime_options_css(
    options: dict[str, Any],
    *,
    landscape: bool | None = None,
    envelope: bool = False,
    mom: bool = False,
) -> str:
    colors = options.get("colors") or {}
    bg = options.get("background") or "watermark"
    heading = colors.get("heading") or "#0b2a56"
    body = colors.get("body") or "#12233f"
    muted = colors.get("muted") or "#5a6a80"
    accent = colors.get("accent") or "#1a6b3a"
    gold = colors.get("gold") or "#c9a227"
    metrics = _sheet_metrics(options, landscape=landscape, envelope=envelope)
    sheet_w = metrics["sheet_w"]
    sheet_min_h = metrics["sheet_h"]
    page_size = metrics["page_size"]
    env_scale = metrics["env_scale"]
    fit_x = metrics["fit_x"]
    fit_y = metrics["fit_y"]
    hide_wm = bg in {"none", "plain"}
    if hide_wm:
        wm_css = "img.wm, .receipt::before { opacity: 0 !important; visibility: hidden !important; }"
    elif envelope:
        wm_css = ""
    else:
        wm_css = (
            "img.wm {"
            " width: min(112mm, 70%) !important; max-height: 46% !important;"
            " height: auto !important; object-fit: contain !important; opacity: 0.75 !important;"
            "}"
            ".receipt::before {"
            " width: min(40mm, 42%) !important; height: min(40mm, 42%) !important;"
            " max-width: 42% !important; max-height: 42% !important; opacity: 0.7 !important;"
            "}"
            "@media print {"
            " img.wm { opacity: 0.7 !important; }"
            " .receipt::before { opacity: 0.65 !important; }"
            "}"
        )
    plain_css = "body { background: #fff !important; }" if bg == "plain" else ""
    sheet_css = ""
    if envelope:
        sheet_css = f"""
  :root, html {{
    --sheet-w: {sheet_w};
    --sheet-h: {sheet_min_h};
    --fit-x: {fit_x:.4f};
    --fit-y: {fit_y:.4f};
    --env-scale: {env_scale:.4f};
  }}
  @page {{ size: {page_size}; margin: 0; }}
  html.envelope-pad, html.envelope-pad body {{
    width: {sheet_w} !important;
    height: {sheet_min_h} !important;
    max-width: {sheet_w} !important;
    max-height: {sheet_min_h} !important;
    overflow: hidden !important;
  }}
  html.envelope-pad .sheet {{
    width: {sheet_w} !important;
    height: {sheet_min_h} !important;
    min-height: {sheet_min_h} !important;
    max-height: {sheet_min_h} !important;
    overflow: hidden !important;
  }}"""
    elif mom:
        sheet_css = f"""
  @page {{ size: {page_size}; margin: 0; }}
  html.pad-mom .sheet {{
    position: relative !important;
    width: {sheet_w} !important;
    height: {sheet_min_h} !important;
    min-height: {sheet_min_h} !important;
    max-height: {sheet_min_h} !important;
  }}
  html.pad-mom .pad {{
    position: relative !important;
    padding-bottom: 9mm !important;
    box-sizing: border-box !important;
  }}
  html.pad-mom .foot-bar {{
    position: absolute !important;
    left: -11mm !important;
    right: -11mm !important;
    bottom: 0 !important;
    margin: 0 !important;
    z-index: 2 !important;
  }}"""
    else:
        sheet_css = f"""
  .sheet {{
    width: {sheet_w};
    min-height: {sheet_min_h};
  }}"""
    return f"""
<style id="tpl-runtime-opts">
  :root {{
    --navy: {heading};
    --navy-2: {heading};
    --green: {accent};
    --gold: {gold};
    --ink: {body};
    --muted: {muted};
    --paper: #ffffff;
  }}
  @page {{ size: {page_size}; margin: 0; }}
  {sheet_css}
  {wm_css}
  {plain_css}
</style>
""".strip()


def _letterhead_officers_html(officers: list[dict[str, Any]]) -> str:
    parts = []
    for o in officers:
        title = _html_escape(o.get("title") or "")
        name = _html_escape(o.get("name") or "—")
        phone = _html_escape(o.get("phone") or "—")
        slot = re.sub(r"[^a-z]+", "-", (o.get("title") or "").strip().lower()).strip("-")
        parts.append(
            f'<div class="role" data-officer-slot="{_html_escape(slot)}">'
            f'<span class="title">{title}</span>'
            f'<span class="name">{name}</span>'
            f'<span class="ph"><span class="lbl">Ph</span>{phone}</span>'
            "</div>"
        )
    return "\n".join(parts)


def _fill_letterhead_officer_slots(html: str, officers: list[dict[str, Any]]) -> str:
    """Update name/phone inside existing data-officer-slot cells (keeps 4-across layout)."""
    if "data-officer-slot=" not in html:
        return _replace_marked_block(html, "letterhead-officers", _letterhead_officers_html(officers))

    by_slot: dict[str, dict[str, Any]] = {}
    for o in officers:
        title = (o.get("title") or "").strip().lower()
        slot = re.sub(r"[^a-z]+", "-", title).strip("-")
        if slot:
            by_slot[slot] = o
        # aliases
        if "general" in title and "secretary" in title:
            by_slot["general-secretary"] = o
        if "vice" in title and "president" in title:
            by_slot["vice-president"] = o

    def _sub_slot(match: re.Match[str]) -> str:
        slot = (match.group("slot") or "").strip().lower()
        block = match.group(0)
        hit = by_slot.get(slot)
        if not hit:
            return block
        name = _html_escape(hit.get("name") or "—")
        phone = _html_escape(hit.get("phone") or "—")
        block = re.sub(
            r'(<span class="name">)(.*?)(</span>)',
            rf"\g<1>{name}\g<3>",
            block,
            count=1,
            flags=re.IGNORECASE | re.DOTALL,
        )
        block = re.sub(
            r'(<span class="ph">\s*<span class="lbl">Ph</span>)(.*?)(</span>)',
            rf"\g<1>{phone}\g<3>",
            block,
            count=1,
            flags=re.IGNORECASE | re.DOTALL,
        )
        return block

    return re.sub(
        r'<div class="role"[^>]*data-officer-slot="(?P<slot>[^"]+)"[^>]*>.*?</div>',
        _sub_slot,
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )


def _ec_office_rows_html(officers: list[dict[str, Any]]) -> str:
    rows = []
    for i, o in enumerate(officers, 1):
        rows.append(
            "<tr>"
            f"<td>{i}</td>"
            f"<td>{_html_escape(o.get('title') or '')}</td>"
            f"<td>{_html_escape(o.get('name') or '—')}</td>"
            f"<td>{_html_escape(o.get('phone') or '—')}</td>"
            "</tr>"
        )
    if not rows:
        return (
            '<tr><td colspan="4" style="text-align:center;padding:8px;">'
            "No office bearers in the charter database yet."
            "</td></tr>"
        )
    return "\n".join(rows)


def _ec_member_columns_html(members: list[dict[str, Any]], start_no: int = 1) -> str:
    if not members:
        return (
            '<table class="member-table"><thead>'
            "<tr><th>S.No.</th><th>Name</th><th>Mobile</th></tr></thead>"
            "<tbody><tr><td colspan=\"3\" style=\"text-align:center\">—</td></tr></tbody></table>"
        )
    mid = (len(members) + 1) // 2
    chunks = [members[:mid], members[mid:]]
    tables = []
    n = start_no
    for chunk in chunks:
        if not chunk:
            continue
        body = []
        for m in chunk:
            body.append(
                "<tr>"
                f"<td>{n}</td>"
                f"<td>{_html_escape(m.get('name') or '—')}</td>"
                f"<td>{_html_escape(m.get('phone') or '—')}</td>"
                "</tr>"
            )
            n += 1
        tables.append(
            '<table class="member-table"><thead>'
            "<tr><th>S.No.</th><th>Name</th><th>Mobile</th></tr></thead>"
            f"<tbody>{''.join(body)}</tbody></table>"
        )
    return "\n".join(tables)


def _replace_marked_block(html: str, marker: str, inner: str) -> str:
    """Replace inner HTML of the element carrying data-tpl-fill=\"marker\" (matched close tag)."""
    open_m = re.search(
        rf"<(?P<tag>\w+)(?P<attrs>[^>]*\bdata-tpl-fill=[\"']{re.escape(marker)}[\"'][^>]*)>",
        html,
        flags=re.IGNORECASE,
    )
    if not open_m:
        return html
    tag = open_m.group("tag")
    attrs = open_m.group("attrs")
    start_inner = open_m.end()
    open_re = re.compile(rf"<{re.escape(tag)}\b[^>]*>", re.IGNORECASE)
    close_re = re.compile(rf"</{re.escape(tag)}\s*>", re.IGNORECASE)
    depth = 1
    pos = start_inner
    end_inner = None
    close_end = None
    while depth > 0 and pos < len(html):
        next_open = open_re.search(html, pos)
        next_close = close_re.search(html, pos)
        if not next_close:
            return html
        if next_open and next_open.start() < next_close.start():
            depth += 1
            pos = next_open.end()
            continue
        depth -= 1
        if depth == 0:
            end_inner = next_close.start()
            close_end = next_close.end()
            break
        pos = next_close.end()
    if end_inner is None or close_end is None:
        return html
    return f"{html[: open_m.start()]}<{tag}{attrs}>{inner}</{tag}>{html[close_end:]}"

def _set_html_attr(html: str, name: str, value: str) -> str:
    match = re.search(r"<html\b[^>]*>", html, flags=re.IGNORECASE)
    if not match:
        return html
    tag = match.group(0)
    attr_re = re.compile(rf"\b{re.escape(name)}\s*=\s*([\"']).*?\1", re.IGNORECASE | re.DOTALL)
    if attr_re.search(tag):
        tag = attr_re.sub(f'{name}="{_html_escape(value)}"', tag, count=1)
    else:
        tag = re.sub(r">\s*$", f' {name}="{_html_escape(value)}">', tag, count=1)
    return html[: match.start()] + tag + html[match.end() :]


def inject_template_runtime(html: str, *, options: dict[str, Any], conn: sqlite3.Connection, base_href: str | None = None) -> str:
    """Inject print options CSS only (pads keep their authored office-bearer markup)."""
    opts = normalize_options(options)
    is_envelope = bool(re.search(r'envelope-pad|data-tpl=["\']envelope["\']', html, re.I))
    is_mom = bool(re.search(r"pad-mom", html, re.I))
    css = _runtime_options_css(
        opts,
        landscape=True if is_envelope else None,
        envelope=is_envelope,
        mom=is_mom,
    )
    base_tag = ""
    if base_href:
        href = base_href if base_href.endswith("/") else f"{base_href}/"
        if re.search(r"<base\b", html, re.IGNORECASE) is None:
            base_tag = f'<base href="{_html_escape(href)}">'
    head_inject = "\n".join(x for x in (base_tag, css) if x)
    if "</head>" in html:
        html = html.replace("</head>", f"{head_inject}\n</head>", 1)
    else:
        html = head_inject + html
    paper = str(opts.get("paperSize") or "A4")
    if is_envelope:
        paper = {
            "A6": "C6",
            "A5": "C5",
            "A4": "C4",
            "22X10": "E2210",
        }.get(paper, paper)
        if paper not in {"C4", "C5", "C6", "E2210", "CUSTOM"}:
            paper = "E2210"
        html = _set_html_attr(html, "data-custom-w", f"{opts.get('customWidthCm') or CUSTOM_W_CM[2]:g}")
        html = _set_html_attr(html, "data-custom-h", f"{opts.get('customHeightCm') or CUSTOM_H_CM[2]:g}")
    html = _set_html_attr(html, "data-paper-size", paper)
    return html


def render_template_html(
    conn: sqlite3.Connection,
    site_root: pathlib.Path,
    template_id: str,
    *,
    options_override: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    """Return rendered HTML and template DTO for an HTML pad."""
    doc = get_template(conn, template_id, site_root=site_root)
    if not doc:
        raise ValueError("Template not found")
    path = resolve_template_file(site_root, doc)
    if not path or not path.is_file():
        raise ValueError("Template file is missing")
    mime = (doc.get("mimeType") or "").lower()
    if "html" not in mime and path.suffix.lower() not in {".html", ".htm"}:
        raise ValueError("Render is only available for HTML templates")
    raw = path.read_text(encoding="utf-8")
    options = normalize_options(options_override if options_override is not None else doc.get("options"))
    static_path = (doc.get("staticPath") or "").replace("\\", "/").lstrip("/")
    if static_path.startswith("documents/"):
        base_href = "/documents/"
    elif static_path.startswith("assets/"):
        base_href = "/assets/"
    else:
        base_href = "/"
    rendered = inject_template_runtime(raw, options=options, conn=conn, base_href=base_href)
    doc = {**doc, "options": options}
    return rendered, doc


_EMAIL_RE = re.compile(r"^[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}$", re.I)
_MAIL_MAX_RECIPIENTS = 20
_MAIL_MAX_ATTACH = 12
_MAIL_MAX_BYTES = 12 * 1024 * 1024


def parse_mail_recipients(raw: Any) -> list[str]:
    if isinstance(raw, list):
        parts = [str(x or "") for x in raw]
    else:
        parts = re.split(r"[,;\s]+", str(raw or ""))
    out: list[str] = []
    seen: set[str] = set()
    for part in parts:
        email = part.strip().lower()
        if not email or email in seen:
            continue
        if not _EMAIL_RE.match(email):
            raise ValueError(f"Invalid email address: {part.strip()}")
        seen.add(email)
        out.append(email)
        if len(out) > _MAIL_MAX_RECIPIENTS:
            raise ValueError(f"At most {_MAIL_MAX_RECIPIENTS} recipients")
    if not out:
        raise ValueError("Enter at least one email address")
    return out


def _safe_attach_name(title: str, suffix: str = ".pdf", fallback: str = "template") -> str:
    stem = re.sub(r"[^\w.\-]+", "_", (title or fallback).strip())[:80].strip("._") or fallback
    suf = suffix if str(suffix).startswith(".") else f".{suffix}"
    if suf and not stem.lower().endswith(suf.lower()):
        stem += suf
    return stem


def _unique_filename(name: str, used: set[str]) -> str:
    candidate = name or "attachment"
    if candidate.lower() not in used:
        return candidate
    stem, ext = os.path.splitext(candidate)
    n = 2
    while True:
        nxt = f"{stem}-{n}{ext}"
        if nxt.lower() not in used:
            return nxt
        n += 1


def _chrome_binary() -> str | None:
    env = (os.environ.get("RWA_CHROME_BIN") or os.environ.get("CHROME_BIN") or "").strip()
    names = ([env] if env else []) + [
        "google-chrome",
        "google-chrome-stable",
        "chromium",
        "chromium-browser",
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    ]
    for name in names:
        if not name:
            continue
        path = pathlib.Path(name)
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
        found = shutil.which(name)
        if found:
            return found
    return None


def _absolutize_site_urls(html: str, site_root: pathlib.Path) -> str:
    root_uri = site_root.resolve().as_uri()
    if not root_uri.endswith("/"):
        root_uri += "/"

    def repl(match: re.Match[str]) -> str:
        attr, quote, path = match.group(1), match.group(2), match.group(3)
        if path.startswith(("http:", "https:", "data:", "file:", "mailto:", "blob:", "#")):
            return match.group(0)
        rel = path.split("?", 1)[0].split("#", 1)[0].lstrip("/")
        return f"{attr}={quote}{root_uri}{rel}{quote}"

    return re.sub(
        r"""((?:src|href))\s*=\s*(['"])(/[^'"]+)\2""",
        repl,
        html,
        flags=re.IGNORECASE,
    )


def _html_to_pdf_chrome(
    html: str,
    site_root: pathlib.Path,
    options: dict[str, Any] | None = None,
    *,
    inject_layout: bool = True,
) -> bytes | None:
    binary = _chrome_binary()
    if not binary:
        return None
    if inject_layout:
        html = _inject_pdf_page_css(html, options)
    localized = _absolutize_site_urls(html, site_root)
    with tempfile.TemporaryDirectory(prefix="rwa-tpl-pdf-") as tmp:
        tmp_path = pathlib.Path(tmp)
        html_path = tmp_path / "template.html"
        pdf_path = tmp_path / "template.pdf"
        html_path.write_text(localized, encoding="utf-8")
        cmd = [
            binary,
            "--headless=new",
            "--disable-gpu",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--allow-file-access-from-files",
            "--no-pdf-header-footer",
            "--hide-scrollbars",
            f"--print-to-pdf={pdf_path}",
            "--virtual-time-budget=12000",
            html_path.resolve().as_uri(),
        ]
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=50)
        except (OSError, subprocess.SubprocessError, subprocess.TimeoutExpired):
            # Older Chromium wants --headless without =new
            cmd[1] = "--headless"
            try:
                subprocess.run(cmd, check=True, capture_output=True, timeout=50)
            except (OSError, subprocess.SubprocessError, subprocess.TimeoutExpired):
                return None
        if pdf_path.is_file() and pdf_path.stat().st_size > 80:
            return pdf_path.read_bytes()
    return None


def _html_to_pdf_weasyprint(
    html: str,
    site_root: pathlib.Path,
    options: dict[str, Any] | None = None,
    *,
    inject_layout: bool = True,
) -> bytes | None:
    try:
        from weasyprint import HTML  # type: ignore
    except Exception:
        return None
    if inject_layout:
        html = _inject_pdf_page_css(html, options)
    localized = re.sub(
        r"""((?:src|href)\s*=\s*['"])/""",
        r"\1",
        html,
        flags=re.IGNORECASE,
    )
    try:
        return HTML(string=localized, base_url=str(site_root.resolve()) + "/").write_pdf()
    except Exception:
        return None


def _image_to_pdf(path: pathlib.Path, options: dict[str, Any]) -> bytes:
    from io import BytesIO

    from reportlab.lib.pagesizes import A4, A5, A6, letter
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas as pdfcanvas

    paper = (options or {}).get("paperSize") or "A4"
    orient = str((options or {}).get("orientation") or "portrait").lower()
    sizes = {"A4": A4, "A5": A5, "A6": A6, "Letter": letter}
    page = sizes.get(paper, A4)
    if orient == "landscape":
        page = (page[1], page[0])
    buf = BytesIO()
    c = pdfcanvas.Canvas(buf, pagesize=page)
    page_w, page_h = page
    img = ImageReader(str(path))
    iw, ih = img.getSize()
    if not iw or not ih:
        raise ValueError("Could not read image template")
    margin = min(page_w, page_h) * 0.04
    box_w, box_h = page_w - 2 * margin, page_h - 2 * margin
    scale = min(box_w / iw, box_h / ih)
    dw, dh = iw * scale, ih * scale
    c.drawImage(img, (page_w - dw) / 2, (page_h - dh) / 2, width=dw, height=dh, preserveAspectRatio=True, mask="auto")
    c.showPage()
    c.save()
    return buf.getvalue()


def build_template_mail_attachment(
    conn: sqlite3.Connection,
    site_root: pathlib.Path,
    template_id: str,
) -> tuple[bytes, str, str, dict[str, Any]]:
    """Return (bytes, filename, mime, dto). Print pads become PDF; Word files stay .doc/.docx."""
    doc = get_template(conn, template_id, site_root=site_root)
    if not doc:
        raise ValueError("Template not found")
    path = resolve_template_file(site_root, doc)
    if not path or not path.is_file():
        raise ValueError("Template file is missing")
    mime = (doc.get("mimeType") or "").lower()
    suffix = path.suffix.lower()
    title = doc.get("title") or path.stem
    original = doc.get("originalName") or path.name
    if suffix in {".doc", ".docx"} or "wordprocessingml" in mime or mime == "application/msword":
        attach_mime = mime or TEMPLATE_EXT_MIME.get(suffix) or "application/octet-stream"
        return path.read_bytes(), original, attach_mime, doc
    filename = _safe_attach_name(title, ".pdf")
    if "pdf" in mime or suffix == ".pdf":
        return path.read_bytes(), filename, "application/pdf", doc
    if suffix in {".png", ".jpg", ".jpeg", ".webp"} or mime.startswith("image/"):
        if suffix == ".svg" or "svg" in mime:
            raise ValueError("SVG templates cannot be mailed yet — download from the portal, or upload a PDF/DOCX.")
        return _image_to_pdf(path, doc.get("options") or {}), filename, "application/pdf", doc
    if "html" in mime or suffix in {".html", ".htm"}:
        html, doc = render_template_html(conn, site_root, template_id)
        opts = doc.get("options") or {}
        pdf = _html_to_pdf_chrome(html, site_root, opts) or _html_to_pdf_weasyprint(html, site_root, opts)
        if not pdf:
            raise ValueError(
                "Could not format this HTML pad as PDF. Install Chromium on the server (or set RWA_CHROME_BIN)."
            )
        return pdf, filename, "application/pdf", doc
    raise ValueError("This file type cannot be mailed. Use HTML, PDF, image, or Word (.doc/.docx).")


def collect_templates_for_mail(
    conn: sqlite3.Connection,
    site_root: pathlib.Path,
    *,
    template_id: str | None = None,
    category: str | None = None,
    status: str | None = "all",
) -> list[dict[str, Any]]:
    if template_id:
        doc = get_template(conn, template_id, site_root=site_root)
        if not doc:
            raise ValueError("Template not found")
        return [doc]
    cat = (category or "").strip().lower()
    if not cat:
        raise ValueError("Choose a template or a category")
    docs = [
        d for d in list_templates(conn, site_root=site_root, status=status or "all")
        if str(d.get("category") or "").lower() == cat
    ]
    if not docs:
        raise ValueError("No templates in that category")
    if len(docs) > _MAIL_MAX_ATTACH:
        raise ValueError(f"At most {_MAIL_MAX_ATTACH} templates can be mailed together")
    return docs


def mail_templates_pdf(
    conn: sqlite3.Connection,
    site_root: pathlib.Path,
    *,
    to_raw: Any,
    template_id: str | None = None,
    category: str | None = None,
    subject: str | None = None,
    message: str | None = None,
    status: str | None = "all",
) -> dict[str, Any]:
    recipients = parse_mail_recipients(to_raw)
    docs = collect_templates_for_mail(
        conn, site_root, template_id=template_id, category=category, status=status
    )
    attachments: list[tuple[str, bytes, str]] = []
    used_names: set[str] = set()
    total = 0
    for doc in docs:
        blob, filename, mime, _meta = build_template_mail_attachment(conn, site_root, doc["id"])
        name = _unique_filename(filename, used_names)
        used_names.add(name.lower())
        total += len(blob)
        if total > _MAIL_MAX_BYTES:
            raise ValueError("Attachments are too large for one email — mail fewer templates")
        attachments.append((name, blob, mime or "application/octet-stream"))

    if template_id:
        title = docs[0].get("title") or "template"
        default_subject = f"MHWS template — {title}"
        lead = f"Please find “{title}” attached."
    else:
        label = docs[0].get("categoryLabel") or category or "templates"
        default_subject = f"MHWS templates — {label}"
        lead = f"Please find {len(docs)} template file{'s' if len(docs) != 1 else ''} ({label}) attached."
    note = (message or "").strip()
    body = (
        f"{lead}\n\n"
        f"{(note + chr(10) + chr(10)) if note else ''}"
        "These files are from the colony Templates library at Himuda Housing Colony Sanyard "
        "(Mandi Housing Welfare Society).\n\n"
        "— Residents Welfare Association\n"
        "  Housing Colony Sanyard, Mandi\n"
    )
    from rwa_portal import send_site_email

    result = send_site_email(
        site_root=site_root,
        to_addrs=recipients,
        subject=(subject or "").strip() or default_subject,
        text_body=body,
        attachments=attachments,
    )
    return {
        "ok": True,
        "to": recipients,
        "count": len(attachments),
        "filenames": [a[0] for a in attachments],
        "channel": result.get("channel"),
        "from": result.get("from"),
    }