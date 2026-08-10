"""EC Desk printable Templates — letterheads, receipt pads, forms.

Storage:
  data/templates/<id>/… for uploads
  documents/… (and assets/) for seeded static site files (doc_type=static)
"""

from __future__ import annotations

import json
import pathlib
import re
import secrets
import shutil
import sqlite3
from typing import Any

from init_rwa_db import utc_now

TEMPLATE_CATEGORIES: list[tuple[str, str]] = [
    ("letterhead", "Letterhead"),
    ("receipt", "Cash receipt"),
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
        "id": "tpl-cash-receipt",
        "title": "Cash Receipt Booklet",
        "description": "Three tear-off cash receipt slips per A4 page.",
        "category": "receipt",
        "tags": ["cash", "treasury", "a4", "booklet"],
        "static_path": "documents/mhws-cash-receipt-booklet.html",
    },
    {
        "id": "tpl-ec-committee",
        "title": "Executive Committee Chart",
        "description": "Office bearers chart for print / notice board.",
        "category": "chart",
        "tags": ["ec", "office bearers"],
        "static_path": "documents/ec-committee-pad.html",
    },
    {
        "id": "tpl-proceedings-gh-mom",
        "title": "General House MOM Register (Blank)",
        "description": "Ruled A4 leaf for General House meeting minutes — register style.",
        "category": "form",
        "tags": ["proceedings", "mom", "general house", "register", "a4"],
        "static_path": "documents/proceedings-gh-mom-pad.html",
    },
    {
        "id": "tpl-proceedings-ec-mom",
        "title": "Executive Committee MOM Register (Blank)",
        "description": "Ruled A4 leaf for EC meeting minutes — register style.",
        "category": "form",
        "tags": ["proceedings", "mom", "ec", "register", "a4"],
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
        conn.execute(
            """
            INSERT INTO print_templates(
              id, title, description, category, tags_json, doc_type,
              filename, original_name, mime_type, size_bytes, static_path,
              status, created_by, created_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
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
        "status": data.get("status") or "published",
        "createdBy": data.get("created_by"),
        "createdAt": data.get("created_at"),
        "updatedAt": data.get("updated_at"),
        "hasFile": False,
        "publicUrl": None,
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
              size_bytes = ?, static_path = ?, status = ?, updated_at = ?
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
              status, created_by, created_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
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
