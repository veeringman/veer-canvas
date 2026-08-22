"""EC Desk printable Templates — letterheads, receipt pads, forms.

Storage:
  data/templates/<id>/… for uploads
  documents/… (and assets/) for seeded static site files (doc_type=static)
"""

from __future__ import annotations

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
    return {
        "paperSize": paper,
        "orientation": orientation,
        "background": bg,
        "customWidthCm": _cm_value(data.get("customWidthCm"), CUSTOM_W_CM),
        "customHeightCm": _cm_value(data.get("customHeightCm"), CUSTOM_H_CM),
        "colors": colors,
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
    """Pads with a `.body-area` writing slot, plus the simple header/footer wrap."""
    ensure_print_templates_table(conn)
    seed_default_templates(conn, site_root)
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
        path = resolve_template_file(site_root, doc)
        if not path or path.suffix.lower() not in {".html", ".htm"}:
            continue
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if not re.search(r"\bbody-area\b", raw, re.I):
            continue
        found[str(doc["id"])] = {
            "id": doc["id"],
            "title": {
                "tpl-mhws-letterhead": "Official letterhead",
                "tpl-rwa-letterhead-blank": "Blank letterhead",
            }.get(str(doc["id"]), doc.get("title") or doc["id"]),
            "hasWatermark": bool(re.search(r"""class=["'][^"']*\bwm\b""", raw, re.I)),
            "category": doc.get("category") or "",
        }
    ordered: list[dict[str, Any]] = []
    for tid in preferred:
        if tid in found:
            ordered.append(found.pop(tid))
    letterheads = [item for item in found.values() if item.get("category") == "letterhead"]
    rest = [item for item in found.values() if item.get("category") != "letterhead"]
    ordered.extend(letterheads)
    ordered.extend(rest)
    ordered.append({"id": "simple", "title": "Simple header & footer", "hasWatermark": False, "category": ""})
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


def sanitize_compose_html(raw: str) -> str:
    html = str(raw or "")
    html = _COMPOSE_BLOCK_RE.sub("", html)
    html = _COMPOSE_VOID_RE.sub("", html)
    html = _COMPOSE_ONATTR_RE.sub("", html)
    html = html.replace("javascript:", "")
    text = re.sub(r"<[^>]+>", " ", html)
    if not re.sub(r"\s+", "", text) and "<" not in (raw or ""):
        html = f"<p>{_html_escape(str(raw or '').strip())}</p>" if str(raw or "").strip() else "<p></p>"
    return html.strip() or "<p></p>"


def wrap_composed_document(
    *,
    title: str,
    body_html: str,
    chrome: str = "simple",
    watermark: bool | None = True,
    site_root: pathlib.Path | None = None,
    conn: sqlite3.Connection | None = None,
) -> str:
    from rwa_compose_export import (
        COMPOSE_PAD_BODY_CSS,
        as_bool,
        embed_local_asset_urls,
        inject_body_area,
        rewrite_pad_urls,
        set_html_title,
        strip_base_tag,
        strip_screen_chrome,
    )

    heading = _html_escape((title or "Document").strip() or "Document")
    margins = parse_doc_margins_mm(body_html)
    body = sanitize_compose_html(body_html)
    chrome_id = str(chrome or "simple").strip() or "simple"
    show_wm = as_bool(watermark, True)
    if chrome_id != "simple" and conn is not None and site_root is not None:
        try:
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
                if "</head>" in injected:
                    injected = injected.replace("</head>", COMPOSE_PAD_BODY_CSS + "\n</head>", 1)
                return set_html_title(injected, title)

    page_margin = (
        f'{margins["top"]:g}mm {margins["right"]:g}mm '
        f'{margins["bottom"]:g}mm {margins["left"]:g}mm'
    )
    simple = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>{heading}</title>
  <style>
    @page {{ size: A4 portrait; margin: {page_margin}; }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      color: #12233f;
      font: 11pt/1.45 "Source Sans 3", "Segoe UI", Georgia, serif;
    }}
    .org {{
      text-align: center;
      border-bottom: 1.4pt solid #0b2a56;
      padding: 0 0 8pt;
      margin: 0 0 14pt;
    }}
    .org img {{ width: 18mm; height: auto; }}
    .org h1 {{
      margin: 4pt 0 0;
      font-size: 15pt;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      color: #0b2a56;
    }}
    .org .sub {{ margin: 2pt 0 0; font-size: 10pt; font-weight: 600; color: #1a6b3a; }}
    .org .meta {{ margin: 2pt 0 0; font-size: 8.5pt; color: #5a6a80; }}
    .body {{ min-height: 180mm; }}
    .body p {{ margin: 0 0 8pt; }}
    .body table {{ border-collapse: collapse; width: 100%; margin: 8pt 0; }}
    .body th, .body td {{ border: 0.6pt solid #0b2a56; padding: 4pt 6pt; vertical-align: top; }}
    .body th {{ background: #eef2f8; }}
    .body img {{ max-width: 100%; height: auto; }}
    .body .mhws-img {{ max-width: 100%; }}
    .body .mhws-img img {{ width: 100%; height: auto; display: block; }}
    .foot {{
      margin-top: 16pt;
      padding-top: 6pt;
      border-top: 0.7pt solid rgba(11,42,86,0.35);
      font-size: 8pt;
      color: #5a6a80;
      text-align: center;
    }}
  </style>
</head>
<body>
  <header class="org">
    <img src="/assets/mhws-logo/mhws-logo-seal-cert.png" alt="">
    <h1>Mandi Housing Welfare Society</h1>
    <p class="sub">Himuda Housing Colony Sanyard</p>
    <p class="meta">Housing Colony Sanyard, Mandi HP 175001 · Registration No. 467 dated 21/07/2012<br>
      housingcolonysanyard@gmail.com · housingcolonysanyard.in</p>
  </header>
  <main class="body">{body}</main>
  <footer class="foot">Unity · Harmony · Progress · Mandi Housing Welfare Society</footer>
</body>
</html>
""".strip()
    return embed_local_asset_urls(simple, site_root)


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
    html = inject_compose_pdf_css(html)
    opts = normalize_options({"paperSize": "A4", "orientation": "portrait", "background": "watermark" if show_wm else "none"})
    pdf = _html_to_pdf_chrome(html, site_root, opts, inject_layout=False) or _html_to_pdf_weasyprint(
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
    return [_row_to_dto(r, site_root) for r in rows]


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
    return _row_to_dto(row, site_root)


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

        wrapped = wrap_composed_document(
            title=title,
            body_html=str(html_in or ""),
            chrome=str(payload.get("chrome") or payload.get("composeChrome") or "simple"),
            watermark=as_bool(payload.get("watermark"), True),
            site_root=pathlib.Path(site_root),
            conn=conn,
        )
        data = wrapped.encode("utf-8")
        if len(data) > TEMPLATE_MAX_BYTES:
            raise ValueError("Document too large (max 20 MB)")
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
        safe_title = re.sub(r"[^\w.\-]+", "_", title)[:60].strip("._") or "document"
        doc_type = "file"
        filename = store_name
        original_name = f"{safe_title}.html"
        mime_type = "text/html"
        size_bytes = len(data)
        static_path = None

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
    return doc


def delete_template(conn: sqlite3.Connection, site_root: pathlib.Path, template_id: str) -> None:
    ensure_print_templates_table(conn)
    row = conn.execute(
        "SELECT id, doc_type FROM print_templates WHERE id = ?",
        (template_id,),
    ).fetchone()
    if not row:
        raise ValueError("Template not found")
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
  @page {{ size: {page_size}; margin: 10mm; }}
  .screen-hint {{ display: none !important; }}
  .sheet {{
    position: relative !important;
  }}
  .foot-bar {{
    position: absolute !important;
    left: 0 !important;
    right: 0 !important;
    bottom: 0 !important;
    width: 100% !important;
    margin-top: 0 !important;
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
  @page {{ size: {page_size}; }}
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
    css = _runtime_options_css(
        opts,
        landscape=True if is_envelope else None,
        envelope=is_envelope,
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