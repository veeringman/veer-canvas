#!/usr/bin/env python3
"""VeerCanvas admin — content authoring and publishing CMS."""
from __future__ import annotations

import hashlib
import io
import json
import os
import pathlib
import re
import secrets
import shutil
import smtplib
import subprocess
import sys
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from functools import wraps
from urllib.parse import urlparse

from flask import Flask, jsonify, redirect, render_template_string, request, send_file, send_from_directory, session, url_for
import sqlite3

APP_DIR = pathlib.Path(__file__).resolve().parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))
from logo_optimize import optimize_logo_file  # noqa: E402
import rwa_portal  # noqa: E402
import rwa_household  # noqa: E402
import rwa_entitlements  # noqa: E402
import rwa_reports  # noqa: E402
import rwa_translate  # noqa: E402

VEERCANVAS_ROOT = pathlib.Path(
    os.environ.get("VEERCANVAS_ROOT", str(APP_DIR.parent))
).resolve()
SITE_ID = os.environ.get("VEERCANVAS_SITE_ID", "veerlabs")
_legacy_site = os.environ.get("VEER_SITE_ROOT")
SITE_ROOT = pathlib.Path(
    os.environ.get("VEERCANVAS_SITE_ROOT", _legacy_site or str(VEERCANVAS_ROOT / "sites" / SITE_ID))
).resolve()
DB_PATH = APP_DIR / "admin.db"
IMPORT_SCRIPT = VEERCANVAS_ROOT / "cli" / "scripts" / "import_github_projects_full.py"
EXCLUSIONS_PATH = SITE_ROOT / "catalog-exclusions.json"
PUBLIC_CATALOG_PATH = SITE_ROOT / "projects-public.json"
DEFAULT_OWNER = os.environ.get("VEERCANVAS_GITHUB_OWNER", os.environ.get("VEER_GITHUB_OWNER", "veeringman"))
LOGO_SIZES = ("sm", "md", "lg", "xl")
LOGO_PRESET_HEIGHTS = {"sm": 44, "md": 64, "lg": 88, "xl": 112}
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SITE_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
DEFAULT_PROJECT_LOGO = "assets/default-project-logo.svg"
THEME_FILES = (
    "index.html",
    "project.html",
    "style.css",
    "content-renderer.js",
    "pagination.js",
    "project.js",
    "site-meta.js",
    "site-utils.js",
    "engagement.js",
)
SITE_STATUSES = ("defined", "authoring", "published", "disabled", "deleted")
SITE_TYPES = ("static", "dynamic", "responsive")
REPO_ROLES = ("content", "app", "services")
KNOWN_INTEGRATIONS = (
    "contact",
    "engagement",
    "github-sync",
    "auth",
    "api-backend",
    "analytics",
)
TEMPLATE_COPY_SKIP = {"preview.svg", "README.md", "site.config.json", "registry.json"}
PROTECTED_SITE_IDS = frozenset({"canvas", "ops"})
SITE_DEFINITION_PATCH_FIELDS = (
    "name",
    "description",
    "domain",
    "aliases",
    "githubOwner",
    "siteType",
    "templateId",
    "templateVersion",
    "locales",
    "defaultLocale",
    "repos",
    "integrations",
)
SITE_CONTENT_FIELDS = (
    "siteName",
    "brandName",
    "brandTag",
    "eyebrow",
    "title",
    "subtitle",
    "chipPrimary",
    "chipSecondary",
    "platform",
    "favicon",
    "brandMark",
    "platformMark",
)

app = Flask(__name__, static_folder=str(APP_DIR / "static"), static_url_path="/static")
app.secret_key = os.environ.get("VEERCANVAS_ADMIN_SECRET", os.environ.get("VEER_ADMIN_SECRET", "veercanvas-admin-secret"))
app.config["MAX_CONTENT_LENGTH"] = int(os.environ.get("VEERCANVAS_MAX_UPLOAD_MB", "20")) * 1024 * 1024
IS_PLATFORM = os.environ.get("VEERCANVAS_PLATFORM", "").strip().lower() in {"1", "true", "yes", "on"}
IS_OPS = os.environ.get("VEERCANVAS_OPS", "").strip().lower() in {"1", "true", "yes", "on"}
ADMIN_PREFIX = os.environ.get("VEERCANVAS_ADMIN_PREFIX", "/admin").rstrip("/") or "/admin"


class _ReverseProxied:
    """Honor X-Forwarded-Prefix so url_for redirects stay under /admin when nginx strips the prefix."""

    def __init__(self, wsgi_app):
        self.wsgi_app = wsgi_app

    def __call__(self, environ, start_response):
        prefix = (environ.get("HTTP_X_FORWARDED_PREFIX") or "").rstrip("/")
        if prefix:
            environ["SCRIPT_NAME"] = prefix
            path = environ.get("PATH_INFO") or ""
            if path.startswith(prefix + "/") or path == prefix:
                environ["PATH_INFO"] = path[len(prefix) :] or "/"
        return self.wsgi_app(environ, start_response)


app.wsgi_app = _ReverseProxied(app.wsgi_app)


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    if DB_PATH.exists():
        return
    conn = get_db()
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT UNIQUE, password_hash TEXT)")
    pw = hashlib.sha256("vijay123".encode()).hexdigest()
    conn.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)", ("admin", pw))
    conn.commit()
    conn.close()


def check_login(username: str, password: str) -> bool:
    conn = get_db()
    row = conn.execute("SELECT password_hash FROM users WHERE username = ?", (username,)).fetchone()
    conn.close()
    return bool(row and hashlib.sha256(password.encode()).hexdigest() == row["password_hash"])


def safe_next_url(candidate: str | None) -> str | None:
    """Allow only same-origin relative paths (optionally under /admin)."""
    if not candidate:
        return None
    value = candidate.strip()
    if not value.startswith("/") or value.startswith("//") or "://" in value:
        return None
    if value.startswith("/admin"):
        return value
    # Ops observability + platform create-site consoles live at site root (outside /admin).
    if (IS_OPS or IS_PLATFORM) and value == "/":
        return "/"
    # Paths relative to the Flask app (nginx already stripped /admin).
    return f"{ADMIN_PREFIX}{value}" if value != "/" else f"{ADMIN_PREFIX}/"


def require_login(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if session.get("logged_in"):
            return f(*args, **kwargs)
        # APIs used by the ops dashboard shell need JSON 401 (not HTML redirect).
        if request.path.startswith("/api/"):
            return jsonify({"ok": False, "error": "Authentication required", "authenticated": False}), 401
        next_target = request.full_path if request.query_string else request.path
        if next_target.endswith("?"):
            next_target = next_target[:-1]
        return redirect(url_for("login", next=next_target))
    return wrapped


def require_platform(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if not IS_PLATFORM:
            return jsonify({
                "ok": False,
                "error": "Website creation is only available on the VeerCanvas platform (canvas.veerlabs.solutions).",
            }), 403
        return f(*args, **kwargs)
    return wrapped


def require_ops(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if not IS_OPS:
            return jsonify({
                "ok": False,
                "error": "Observability is only available on the VeerCanvas Ops console (ops.veerlabs.solutions).",
            }), 403
        return f(*args, **kwargs)
    return wrapped


def projects_path() -> pathlib.Path:
    return SITE_ROOT / "projects.json"


def site_meta_path() -> pathlib.Path:
    return SITE_ROOT / "site-meta.json"


def load_projects() -> list[dict]:
    path = projects_path()
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def save_projects(data: list[dict]) -> None:
    data.sort(key=lambda item: (item.get("sortOrder", 9999), item.get("name", "")))
    projects_path().write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    write_public_catalog(data)


def renumber_sort_orders(projects: list[dict], step: int = 10) -> list[dict]:
    """Assign sequential sortOrder values for the current list order."""
    for index, project in enumerate(projects):
        project["sortOrder"] = (index + 1) * step
    return projects


def ordered_projects(data: list[dict] | None = None) -> list[dict]:
    projects = list(data if data is not None else load_projects())
    projects.sort(key=lambda item: (item.get("sortOrder", 9999), item.get("name", "")))
    return projects


def apply_dashboard_position(data: list[dict], slug: str, position: int) -> list[dict]:
    """Move slug to 1-based dashboard position and renumber sortOrder."""
    projects = ordered_projects(data)
    current_idx = next((i for i, item in enumerate(projects) if item.get("slug") == slug), -1)
    if current_idx < 0:
        raise KeyError(slug)
    target = max(1, min(len(projects), int(position))) - 1
    if current_idx == target:
        return renumber_sort_orders(projects)
    item = projects.pop(current_idx)
    projects.insert(target, item)
    return renumber_sort_orders(projects)


def sync_reorder(projects: list[dict]) -> None:
    save_projects(projects)
    for project in projects:
        slug = project.get("slug")
        if slug:
            sync_miniapp(slug, project)


def is_enabled(project: dict) -> bool:
    value = project.get("enabled", True)
    if value is False or value == 0:
        return False
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"false", "0", "no", "off"}:
            return False
    return True


def write_public_catalog(projects: list[dict] | None = None) -> int:
    data = projects if projects is not None else load_projects()
    excluded = load_exclusions()
    visible = [
        project for project in data
        if is_enabled(project) and project.get("slug") not in excluded
    ]
    visible.sort(key=lambda item: (item.get("sortOrder", 9999), item.get("name", "")))
    PUBLIC_CATALOG_PATH.write_text(json.dumps(visible, indent=2) + "\n", encoding="utf-8")
    return len(visible)


def load_exclusions() -> set[str]:
    if not EXCLUSIONS_PATH.exists():
        return set()
    try:
        data = json.loads(EXCLUSIONS_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return set()
    return {slug for slug in (data.get("deletedSlugs") or []) if isinstance(slug, str) and slug.strip()}


def save_exclusions(slugs: set[str]) -> None:
    EXCLUSIONS_PATH.write_text(
        json.dumps({"deletedSlugs": sorted(slugs)}, indent=2) + "\n",
        encoding="utf-8",
    )


def add_exclusion(slug: str) -> None:
    slugs = load_exclusions()
    slugs.add(slug)
    save_exclusions(slugs)


def remove_exclusion(slug: str) -> None:
    slugs = load_exclusions()
    slugs.discard(slug)
    save_exclusions(slugs)


def load_site_meta() -> dict:
    path = site_meta_path()
    defaults = {
        "version": "v1.0.0",
        "lastUpdated": utc_now(),
        "siteName": "VeerLabs Solutions",
        "brandName": "VeerLabs",
        "brandTag": "Solutions",
        "eyebrow": "Veeringman studio catalog",
        "title": "VeerLabs Solutions",
        "subtitle": "Explore Veer Labs projects.",
        "chipPrimary": "Project catalog",
        "chipSecondary": "Powered by VeerCanvas",
        "platform": "VeerCanvas",
        "platformSiteId": SITE_ID,
        "favicon": "assets/favicon.svg",
        "brandMark": "assets/veer-canvas-icon.svg",
        "platformMark": "assets/veer-canvas-icon.svg",
    }
    if not path.exists():
        return defaults
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return defaults
    merged = dict(defaults)
    merged.update(data if isinstance(data, dict) else {})
    return merged


def save_site_meta(meta: dict) -> None:
    site_meta_path().write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")


def apply_site_content(meta: dict, payload: dict) -> dict:
    updated = dict(meta)
    for key in SITE_CONTENT_FIELDS:
        if key in payload and payload[key] is not None:
            updated[key] = str(payload[key]).strip()
    # Keep title/siteName aligned when one is blank.
    if updated.get("title") and not updated.get("siteName"):
        updated["siteName"] = updated["title"]
    if updated.get("siteName") and not updated.get("title"):
        updated["title"] = updated["siteName"]
    return updated


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def bump_minor_version(version: str) -> str:
    match = re.match(r"^v?(\d+)\.(\d+)\.(\d+)$", version or "v1.0.0")
    if not match:
        return "v1.1.0"
    major, minor, _patch = map(int, match.groups())
    return f"v{major}.{minor + 1}.0"


def find_project(slug: str) -> tuple[list[dict], dict | None, int]:
    data = load_projects()
    for i, project in enumerate(data):
        if project.get("slug") == slug:
            return data, project, i
    return data, None, -1


def sync_miniapp(slug: str, project: dict) -> None:
    package_dir = SITE_ROOT / "miniapps" / slug
    package_dir.mkdir(parents=True, exist_ok=True)
    (package_dir / "project.json").write_text(json.dumps(project, indent=2) + "\n", encoding="utf-8")


def slugify_value(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")


def validate_slug(slug: str) -> str:
    cleaned = slugify_value(slug)
    if not cleaned or not SLUG_RE.match(cleaned):
        raise ValueError("slug must be lowercase letters, numbers, and hyphens (e.g. my-project)")
    if cleaned in {"admin", "api", "static", "site", "assets", "miniapps"}:
        raise ValueError("slug is reserved")
    return cleaned


def new_project_defaults(slug: str, payload: dict | None = None) -> dict:
    data = dict(payload or {})
    name = str(data.get("name") or slug).strip() or slug
    project = {
        "slug": slug,
        "name": name,
        "subtitle": str(data.get("subtitle") or "").strip(),
        "summary": str(data.get("summary") or "").strip(),
        "summaryFormat": data.get("summaryFormat") or "auto",
        "summaryAlign": data.get("summaryAlign") or "",
        "summarySize": data.get("summarySize") or "",
        "enabled": True,
        "requireAuth": False,
        "logoSize": data.get("logoSize") or "md",
        "reimport": False,
        "tags": data.get("tags") if isinstance(data.get("tags"), list) else [],
        "status": data.get("status") if isinstance(data.get("status"), list) else ["Draft"],
        "logo": data.get("logo") or DEFAULT_PROJECT_LOGO,
        "logoAlt": data.get("logoAlt") or f"{name} logo",
        "details": data.get("details") if isinstance(data.get("details"), list) else [],
    }
    if data.get("logoWidth"):
        project["logoWidth"] = data["logoWidth"]
    if data.get("logoHeight"):
        project["logoHeight"] = data["logoHeight"]
    return project


def sites_root() -> pathlib.Path:
    return VEERCANVAS_ROOT / "sites"


def templates_root() -> pathlib.Path:
    return sites_root() / "_templates"


def templates_registry_path() -> pathlib.Path:
    return templates_root() / "registry.json"


def utc_iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def next_admin_port(root: pathlib.Path) -> int:
    used = {8080}
    if root.is_dir():
        for path in root.iterdir():
            cfg_path = path / "site.config.json"
            if not cfg_path.is_file():
                continue
            try:
                cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            port = (cfg.get("admin") or {}).get("port")
            if isinstance(port, int) and 1024 <= port <= 65535:
                used.add(port)
    port = 8080
    while port in used:
        port += 1
    return port


def load_template_registry() -> dict:
    path = templates_registry_path()
    if not path.is_file():
        return {"templates": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"templates": []}
    if not isinstance(data, dict):
        return {"templates": []}
    templates = data.get("templates")
    if not isinstance(templates, list):
        data["templates"] = []
    return data


def save_template_registry(data: dict) -> None:
    root = templates_root()
    root.mkdir(parents=True, exist_ok=True)
    templates_registry_path().write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def get_template_entry(template_id: str) -> dict | None:
    tid = (template_id or "").strip()
    for item in load_template_registry().get("templates") or []:
        if isinstance(item, dict) and item.get("id") == tid:
            return item
    return None


def normalize_repos(raw) -> list[dict]:
    out = []
    if not isinstance(raw, list):
        return out
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        url = str(item.get("url") or "").strip()
        role = str(item.get("role") or "content").strip().lower()
        if role not in REPO_ROLES:
            role = "content"
        if not name and not url:
            continue
        out.append({"name": name or url, "url": url, "role": role})
    return out


def normalize_integrations(raw) -> list[str]:
    values = []
    if isinstance(raw, str):
        raw = [part.strip() for part in raw.split(",")]
    if not isinstance(raw, list):
        return values
    seen = set()
    for item in raw:
        key = str(item or "").strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        values.append(key)
    return values


def normalize_locales(raw, default_locale: str = "en") -> tuple[list[str], str]:
    locales = []
    if isinstance(raw, str):
        raw = [part.strip() for part in raw.split(",")]
    if isinstance(raw, list):
        for item in raw:
            code = str(item or "").strip()
            if code and code not in locales:
                locales.append(code)
    if not locales:
        locales = [default_locale or "en"]
    default = str(default_locale or locales[0]).strip() or locales[0]
    if default not in locales:
        locales.insert(0, default)
    return locales, default


def append_status_history(cfg: dict, status: str, note: str = "") -> None:
    history = cfg.get("statusHistory")
    if not isinstance(history, list):
        history = []
    history.append({
        "status": status,
        "at": utc_iso_now(),
        "note": note or "",
    })
    cfg["statusHistory"] = history[-40:]


def normalize_site_config(raw: dict | None, *, site_id: str, path: pathlib.Path | None = None) -> dict:
    cfg = dict(raw or {})
    sid = str(cfg.get("id") or site_id).strip() or site_id
    name = str(cfg.get("name") or sid).strip()
    domain = str(cfg.get("domain") or f"{sid}.veerlabs.solutions").strip()
    status = str(cfg.get("status") or "defined").strip().lower()
    if status not in SITE_STATUSES:
        status = "defined"
    site_type = str(cfg.get("siteType") or "responsive").strip().lower()
    if site_type not in SITE_TYPES:
        site_type = "responsive"
    template_id = str(cfg.get("templateId") or "catalog-static").strip() or "catalog-static"
    template_entry = get_template_entry(template_id)
    template_version = str(
        cfg.get("templateVersion")
        or ((template_entry or {}).get("version") if template_entry else "")
        or "1.0.0"
    ).strip()
    locales, default_locale = normalize_locales(cfg.get("locales"), str(cfg.get("defaultLocale") or "en"))
    admin = cfg.get("admin") if isinstance(cfg.get("admin"), dict) else {}
    port = admin.get("port")
    if not isinstance(port, int):
        port = None
    created = str(cfg.get("createdAt") or "").strip() or utc_iso_now()
    updated = str(cfg.get("updatedAt") or created).strip() or created
    aliases = cfg.get("aliases") if isinstance(cfg.get("aliases"), list) else []
    aliases = [str(a).strip() for a in aliases if str(a).strip()]
    if domain and f"www.{domain}" not in aliases:
        # keep existing aliases as-is if already set; don't force-add on every normalize of old configs
        pass
    normalized = {
        "id": sid,
        "name": name,
        "description": str(cfg.get("description") or f"{name} — VeerCanvas site").strip(),
        "domain": domain,
        "aliases": aliases,
        "webRoot": str(cfg.get("webRoot") or f"/var/www/{domain}").strip(),
        "githubOwner": str(cfg.get("githubOwner") or DEFAULT_OWNER).strip(),
        "status": status,
        "siteType": site_type,
        "templateId": template_id,
        "templateVersion": template_version,
        "locales": locales,
        "defaultLocale": default_locale,
        "repos": normalize_repos(cfg.get("repos")),
        "integrations": normalize_integrations(cfg.get("integrations")),
        "admin": {
            "serviceName": str(admin.get("serviceName") or f"veercanvas-admin-{sid}").strip(),
            "port": port,
        },
        "platform": bool(cfg.get("platform")),
        "ops": bool(cfg.get("ops")),
        "createdAt": created,
        "updatedAt": updated,
        "statusHistory": cfg.get("statusHistory") if isinstance(cfg.get("statusHistory"), list) else [],
    }
    if path is not None:
        normalized["path"] = str(path)
        normalized["active"] = path.resolve() == SITE_ROOT.resolve()
        normalized["adminPort"] = port
        normalized["serviceName"] = normalized["admin"]["serviceName"]
    return normalized


def load_site_config(site_id: str) -> dict | None:
    path = sites_root() / site_id
    cfg_path = path / "site.config.json"
    if not path.is_dir() or not cfg_path.is_file():
        return None
    try:
        raw = json.loads(cfg_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        raw = {}
    return normalize_site_config(raw, site_id=site_id, path=path)


def save_site_config(site_id: str, cfg: dict) -> dict:
    path = sites_root() / site_id
    path.mkdir(parents=True, exist_ok=True)
    normalized = normalize_site_config(cfg, site_id=site_id, path=path)
    # Persist without list-only presentation fields
    persist = {k: v for k, v in normalized.items() if k not in {"path", "active", "adminPort", "serviceName"}}
    if persist["admin"].get("port") is None:
        persist["admin"].pop("port", None)
    (path / "site.config.json").write_text(json.dumps(persist, indent=2) + "\n", encoding="utf-8")
    return normalize_site_config(persist, site_id=site_id, path=path)


def list_local_sites(*, include_deleted: bool = False, status: str | None = None) -> list[dict]:
    root = sites_root()
    if not root.is_dir():
        return []
    sites = []
    for path in sorted(root.iterdir()):
        if not path.is_dir() or path.name.startswith("_") or path.name.startswith("."):
            continue
        cfg_path = path / "site.config.json"
        raw = {}
        if cfg_path.exists():
            try:
                raw = json.loads(cfg_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                raw = {}
        site = normalize_site_config(raw, site_id=path.name, path=path)
        if status:
            if site.get("status") != status:
                continue
        elif not include_deleted and site.get("status") == "deleted":
            continue
        sites.append(site)
    return sites


def resolve_template_source(template_id: str) -> pathlib.Path:
    root = sites_root()
    entry = get_template_entry(template_id)
    source_name = str((entry or {}).get("source") or template_id or "catalog-static").strip()
    candidates = [
        templates_root() / source_name,
        root / "veerlabs",
        root / "_template",
    ]
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    raise FileNotFoundError(f"template source not found: {template_id}")


def copy_template_package(theme_src: pathlib.Path, dest: pathlib.Path) -> None:
    for item in theme_src.iterdir():
        if item.name in TEMPLATE_COPY_SKIP or item.name.startswith("."):
            continue
        target = dest / item.name
        if item.is_dir():
            if item.name == "assets":
                assets_dest = dest / "assets"
                assets_dest.mkdir(parents=True, exist_ok=True)
                for asset in item.iterdir():
                    if asset.name == "site":
                        continue
                    asset_target = assets_dest / asset.name
                    if asset.is_dir():
                        if asset_target.exists():
                            shutil.rmtree(asset_target)
                        shutil.copytree(asset, asset_target)
                    else:
                        shutil.copy2(asset, asset_target)
                continue
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(item, target)
        else:
            shutil.copy2(item, target)

    # Legacy fallback if package only has partial theme files under a flat layout
    for theme_file in THEME_FILES:
        src = theme_src / theme_file
        if src.is_file() and not (dest / theme_file).exists():
            shutil.copy2(src, dest / theme_file)


def create_site_scaffold(
    site_id: str,
    *,
    name: str = "",
    domain: str = "",
    github_owner: str = "",
    description: str = "",
    site_type: str = "responsive",
    template_id: str = "catalog-static",
    locales=None,
    default_locale: str = "en",
    repos=None,
    integrations=None,
    force: bool = False,
) -> dict:
    site_id = validate_slug(site_id)
    if site_id in {"_template", "_templates", "admin", "api"}:
        raise ValueError(f"reserved site id: {site_id}")
    root = sites_root()
    root.mkdir(parents=True, exist_ok=True)
    dest = root / site_id
    if dest.exists() and any(dest.iterdir()) and not force:
        raise FileExistsError(f"site already exists: {site_id}")
    dest.mkdir(parents=True, exist_ok=True)

    template_id = (template_id or "catalog-static").strip() or "catalog-static"
    template_entry = get_template_entry(template_id)
    if template_entry is None and not (templates_root() / template_id).is_dir():
        # allow unknown ids only if a package folder exists; else fall back
        template_id = "catalog-static"
        template_entry = get_template_entry(template_id)
    theme_src = resolve_template_source(template_id)

    display_name = (name or site_id.replace("-", " ").title()).strip()
    domain_value = (domain or f"{site_id}.veerlabs.solutions").strip()
    owner = (github_owner or DEFAULT_OWNER).strip()
    admin_port = next_admin_port(root)
    site_type_value = (site_type or "responsive").strip().lower()
    if site_type_value not in SITE_TYPES:
        site_type_value = "responsive"
    locale_list, default_loc = normalize_locales(locales, default_locale or "en")
    integration_list = normalize_integrations(integrations)
    if not integration_list and template_entry:
        integration_list = normalize_integrations(template_entry.get("defaultIntegrations"))
    now = utc_iso_now()

    config = {
        "id": site_id,
        "name": display_name,
        "description": (description or f"{display_name} — VeerCanvas site").strip(),
        "domain": domain_value,
        "aliases": [f"www.{domain_value}"] if domain_value else [],
        "webRoot": f"/var/www/{domain_value}",
        "githubOwner": owner,
        "status": "authoring",
        "siteType": site_type_value,
        "templateId": template_id,
        "templateVersion": str((template_entry or {}).get("version") or "1.0.0"),
        "locales": locale_list,
        "defaultLocale": default_loc,
        "repos": normalize_repos(repos),
        "integrations": integration_list,
        "admin": {
            "serviceName": f"veercanvas-admin-{site_id}",
            "port": admin_port,
        },
        "platform": False,
        "ops": False,
        "createdAt": now,
        "updatedAt": now,
        "statusHistory": [],
    }
    append_status_history(config, "defined", "Site definition created")
    append_status_history(config, "authoring", f"Scaffolded from template {template_id}")
    save_site_config(site_id, config)

    # Docs-hub gets slightly different default chrome
    if template_id == "docs-hub":
        eyebrow = f"{display_name} docs"
        subtitle = f"Documentation and guides published on {display_name}."
        chip = "Docs hub"
    else:
        eyebrow = f"{display_name} catalog"
        subtitle = f"Explore projects published on {display_name}."
        chip = "Project catalog"

    meta = {
        "version": "v1.0.0",
        "lastUpdated": utc_now(),
        "siteName": display_name,
        "brandName": display_name.split()[0] if display_name else site_id,
        "brandTag": " ".join(display_name.split()[1:]) if len(display_name.split()) > 1 else "Site",
        "eyebrow": eyebrow,
        "title": display_name,
        "subtitle": subtitle,
        "chipPrimary": chip,
        "chipSecondary": "Powered by VeerCanvas",
        "platform": "VeerCanvas",
        "platformSiteId": site_id,
        "favicon": "assets/favicon.svg",
        "brandMark": "assets/veer-canvas-icon.svg",
        "platformMark": "assets/veer-canvas-icon.svg",
    }
    (dest / "site-meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    (dest / "projects.json").write_text("[]\n", encoding="utf-8")
    (dest / "projects-public.json").write_text("[]\n", encoding="utf-8")
    (dest / "catalog-exclusions.json").write_text(
        json.dumps({"deletedSlugs": []}, indent=2) + "\n", encoding="utf-8"
    )
    (dest / "miniapps").mkdir(exist_ok=True)
    (dest / "assets" / "site").mkdir(parents=True, exist_ok=True)

    copy_template_package(theme_src, dest)

    saved = load_site_config(site_id)
    return {
        "id": site_id,
        "path": str(dest),
        "config": saved,
        "hint": (
            f"Scaffold ready. Content CMS will be at https://{domain_value}/admin/ after deploy. "
            f"Deploy with: SITE_ID={site_id} EC2_KEY=./VeerSetuHost.pem ./deploy/remote-deploy.sh"
        ),
    }


def soft_delete_site(site_id: str) -> dict:
    cfg = load_site_config(site_id)
    if not cfg:
        raise FileNotFoundError(f"unknown site: {site_id}")
    if cfg.get("platform") or cfg.get("ops") or site_id in PROTECTED_SITE_IDS:
        raise PermissionError("platform and ops sites cannot be deleted")
    if cfg.get("status") == "deleted":
        return cfg
    cfg["status"] = "deleted"
    cfg["updatedAt"] = utc_iso_now()
    append_status_history(cfg, "deleted", "Soft-deleted from Site Studio")
    return save_site_config(site_id, cfg)


def hard_delete_site(site_id: str) -> None:
    cfg = load_site_config(site_id)
    if not cfg:
        raise FileNotFoundError(f"unknown site: {site_id}")
    if cfg.get("platform") or cfg.get("ops") or site_id in PROTECTED_SITE_IDS:
        raise PermissionError("platform and ops sites cannot be deleted")
    if cfg.get("status") != "deleted":
        raise ValueError("hard delete requires status=deleted first")
    dest = sites_root() / site_id
    if dest.is_dir():
        shutil.rmtree(dest)


def clone_template_package(
    new_id: str,
    *,
    name: str,
    description: str = "",
    site_types=None,
    clone_from: str = "catalog-static",
    layout: str = "",
) -> dict:
    tid = validate_slug(new_id)
    if tid in {"registry", "admin", "api"}:
        raise ValueError(f"reserved template id: {tid}")
    registry = load_template_registry()
    if any(t.get("id") == tid for t in registry.get("templates") or [] if isinstance(t, dict)):
        raise FileExistsError(f"template already exists: {tid}")
    source = resolve_template_source(clone_from)
    dest = templates_root() / tid
    if dest.exists() and any(dest.iterdir()):
        raise FileExistsError(f"template package already exists: {tid}")
    dest.mkdir(parents=True, exist_ok=True)
    copy_template_package(source, dest)
    preview = dest / "preview.svg"
    if not preview.exists():
        preview.write_text(
            f'<svg xmlns="http://www.w3.org/2000/svg" width="320" height="180">'
            f'<rect width="320" height="180" fill="#0d1b26"/>'
            f'<text x="160" y="95" fill="#00c6fb" font-size="18" text-anchor="middle">{tid}</text></svg>\n',
            encoding="utf-8",
        )
    types = []
    if isinstance(site_types, list):
        for item in site_types:
            value = str(item or "").strip().lower()
            if value in SITE_TYPES and value not in types:
                types.append(value)
    if not types:
        types = ["static", "responsive"]
    entry = {
        "id": tid,
        "name": (name or tid.replace("-", " ").title()).strip(),
        "description": (description or f"Custom template cloned from {clone_from}").strip(),
        "siteTypes": types,
        "layout": (layout or tid).strip() or tid,
        "source": tid,
        "version": "1.0.0",
        "preview": f"{tid}/preview.svg",
        "builtin": False,
        "defaultIntegrations": ["github-sync"],
        "clonedFrom": clone_from,
        "createdAt": utc_iso_now(),
    }
    templates = list(registry.get("templates") or [])
    templates.append(entry)
    registry["templates"] = templates
    save_template_registry(registry)
    return entry


def parse_logo_px(value, *, field_name: str) -> int | None:
    if value is None or value == "":
        return None
    try:
        num = int(float(value))
    except (TypeError, ValueError):
        raise ValueError(f"{field_name} must be a positive integer (px)") from None
    if num <= 0 or num > 1024:
        raise ValueError(f"{field_name} must be between 1 and 1024")
    return num


def normalize_logo_dims(payload: dict) -> dict:
    size = payload.get("logoSize") or "md"
    if size not in LOGO_SIZES:
        size = "md"
    payload["logoSize"] = size
    width = parse_logo_px(payload.get("logoWidth"), field_name="logoWidth")
    height = parse_logo_px(payload.get("logoHeight"), field_name="logoHeight")
    if width is None:
        payload.pop("logoWidth", None)
    else:
        payload["logoWidth"] = width
    if height is None:
        payload.pop("logoHeight", None)
    else:
        payload["logoHeight"] = height
    return payload


def github_token_candidates() -> list[pathlib.Path]:
    """Local token files — support both gh_token.txt and gt_token.txt."""
    roots = [VEERCANVAS_ROOT, APP_DIR.parent]
    names = ("gt_token.txt", "gh_token.txt")
    seen: set[pathlib.Path] = set()
    out: list[pathlib.Path] = []
    for root in roots:
        try:
            root = root.resolve()
        except OSError:
            continue
        for name in names:
            path = root / name
            if path in seen:
                continue
            seen.add(path)
            out.append(path)
    return out


def github_token_path() -> pathlib.Path:
    # Prefer an existing file; otherwise default write path for admin saves.
    for path in github_token_candidates():
        if path.exists() and path.read_text(encoding="utf-8").strip():
            return path
    return VEERCANVAS_ROOT / "gh_token.txt"


def github_token() -> str | None:
    # Prefer on-disk token files over ambient env (CI/shell often has a stale GITHUB_TOKEN).
    for path in github_token_candidates():
        if path.exists():
            value = path.read_text(encoding="utf-8").strip()
            if value:
                return value
    for key in ("GH_TOKEN", "GITHUB_TOKEN"):
        if os.environ.get(key):
            return os.environ[key]
    return None


def github_token_status() -> dict:
    token = github_token()
    configured = bool(token)
    source = None
    for path in github_token_candidates():
        if path.exists() and path.read_text(encoding="utf-8").strip():
            source = path.name
            break
    if not source:
        if os.environ.get("GH_TOKEN"):
            source = "env:GH_TOKEN"
        elif os.environ.get("GITHUB_TOKEN"):
            source = "env:GITHUB_TOKEN"
    return {
        "configured": configured,
        "source": source,
        "canImportPrivate": configured,
        "hint": None if configured else "Save a GitHub PAT with repo scope to import private repos like matteros.",
    }


def run_import(
    include_private: bool = True,
    *,
    reimport_all: bool = False,
    reimport_slugs: list[str] | None = None,
    only_slugs: list[str] | None = None,
) -> tuple[bool, str, dict]:
    if not IMPORT_SCRIPT.exists():
        return False, f"Import script not found: {IMPORT_SCRIPT}", {}
    cmd = [
        sys.executable,
        str(IMPORT_SCRIPT),
        DEFAULT_OWNER,
        "imported_projects",
        "--site-root",
        str(SITE_ROOT),
        "--projects-json",
        str(projects_path()),
        "--fetch-repos",
    ]
    if reimport_all:
        cmd.append("--reimport-all")
    elif reimport_slugs:
        cmd.extend(["--reimport-slugs", ",".join(reimport_slugs)])
    if only_slugs:
        cmd.extend(["--only-slugs", ",".join(only_slugs)])
    if not include_private:
        cmd.append("--public-only")
    token = github_token()
    if token:
        cmd.extend(["--token", token])
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(SITE_ROOT),
        timeout=600,
    )
    output = (proc.stdout or "") + (proc.stderr or "")
    summary = parse_import_output(output)
    summary_path = SITE_ROOT / "imported_projects" / "import-summary.json"
    if summary_path.exists():
        try:
            packages = json.loads(summary_path.read_text(encoding="utf-8"))
            if isinstance(packages, list):
                summary["packages"] = [
                    {
                        "slug": item.get("slug"),
                        "action": item.get("action"),
                        "logo_found": item.get("logo_found"),
                        "repo_url": item.get("repo_url") or item.get("html_url"),
                    }
                    for item in packages
                    if isinstance(item, dict)
                ]
                summary["importedSlugs"] = [
                    item.get("slug") for item in summary["packages"] if item.get("slug")
                ]
        except (OSError, json.JSONDecodeError):
            pass
    return proc.returncode == 0, output[-6000:], summary


def parse_import_output(output: str) -> dict:
    summary = {
        "imported": None,
        "skipped": None,
        "repoCount": None,
        "importedSlugs": [],
        "packages": [],
    }
    for line in (output or "").splitlines():
        if line.startswith("Found ") and " repositories for " in line:
            try:
                summary["repoCount"] = int(line.split()[1])
            except (IndexError, ValueError):
                pass
        if line.startswith("Import complete:"):
            # Import complete: imported=1 skipped=47
            for part in line.replace("Import complete:", "").split():
                if part.startswith("imported="):
                    try:
                        summary["imported"] = int(part.split("=", 1)[1])
                    except ValueError:
                        pass
                if part.startswith("skipped="):
                    try:
                        summary["skipped"] = int(part.split("=", 1)[1])
                    except ValueError:
                        pass
        if line.startswith("Processing ") and "(" in line:
            # Processing veeringman/matteros (new)...
            try:
                full = line.split()[1]
                slug = full.split("/")[-1].lower().replace("_", "-")
                action = line[line.find("(") + 1:line.find(")")]
                summary["packages"].append({"slug": slug, "action": action, "repo": full})
            except (IndexError, ValueError):
                pass
    if summary["packages"] and not summary["importedSlugs"]:
        summary["importedSlugs"] = [p["slug"] for p in summary["packages"] if p.get("slug")]
    return summary


def probe_github_token() -> dict:
    token = github_token()
    status = github_token_status()
    result = {
        **status,
        "ok": False,
        "login": None,
        "repoCount": None,
        "error": None,
    }
    if not token:
        result["error"] = "No GitHub token configured"
        return result
    try:
        req = urllib.request.Request(
            "https://api.github.com/user",
            headers={
                "Accept": "application/vnd.github.v3+json",
                "User-Agent": "VeerCanvas-Admin/1.0",
                "Authorization": f"token {token}",
            },
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            user = json.loads(resp.read().decode("utf-8", errors="replace"))
        result["login"] = user.get("login")
        # Prefer user repos when token owner matches DEFAULT_OWNER.
        if result["login"] and result["login"].lower() == DEFAULT_OWNER.lower():
            repos_url = "https://api.github.com/user/repos?per_page=100&type=all&sort=updated"
        else:
            repos_url = f"https://api.github.com/orgs/{DEFAULT_OWNER}/repos?per_page=100&type=all&sort=updated"
        req2 = urllib.request.Request(
            repos_url,
            headers={
                "Accept": "application/vnd.github.v3+json",
                "User-Agent": "VeerCanvas-Admin/1.0",
                "Authorization": f"token {token}",
            },
        )
        with urllib.request.urlopen(req2, timeout=30) as resp:
            repos = json.loads(resp.read().decode("utf-8", errors="replace"))
        result["repoCount"] = len(repos) if isinstance(repos, list) else None
        result["ok"] = True
    except urllib.error.HTTPError as exc:
        result["error"] = f"GitHub HTTP {exc.code}"
    except Exception as exc:  # noqa: BLE001 — surface probe failures to admin UI
        result["error"] = str(exc)[:200]
    return result


@app.route("/login", methods=["GET", "POST"])
def login():
    root_console = IS_OPS or IS_PLATFORM
    next_raw = request.values.get("next") or ("/" if root_console else "")
    if request.method == "POST":
        if check_login(request.form.get("username", ""), request.form.get("password", "")):
            session["logged_in"] = True
            session["username"] = request.form.get("username")
            default_next = "/" if root_console else url_for("dashboard")
            return redirect(safe_next_url(next_raw) or default_next)
        return render_template_string(
            LOGIN_HTML,
            error="Invalid credentials",
            next=next_raw,
            is_ops=IS_OPS,
            is_platform=IS_PLATFORM,
        )
    return render_template_string(
        LOGIN_HTML,
        error=None,
        next=next_raw,
        is_ops=IS_OPS,
        is_platform=IS_PLATFORM,
    )


@app.route("/logout")
def logout():
    session.clear()
    if IS_OPS or IS_PLATFORM:
        return redirect(url_for("login", next="/"))
    return redirect(url_for("login"))


@app.route("/")
@require_login
def dashboard():
    projects = ordered_projects()
    meta = ensure_brand_assets()
    return render_template_string(
        DASHBOARD_HTML,
        projects=projects,
        meta=meta,
        logo_sizes=LOGO_SIZES,
        logo_preset_heights=LOGO_PRESET_HEIGHTS,
        github_token=github_token_status(),
        github_owner=DEFAULT_OWNER,
        is_platform=IS_PLATFORM,
        is_ops=IS_OPS,
        site_id=SITE_ID,
    )


@app.route("/site/<path:asset_path>")
@require_login
def site_asset(asset_path):
    return send_from_directory(SITE_ROOT, asset_path)


@app.route("/api/projects", methods=["GET"])
@require_login
def api_projects():
    return jsonify(load_projects())


@app.route("/api/project/<slug>", methods=["GET"])
@require_login
def api_get_project(slug):
    data = ordered_projects()
    for index, project in enumerate(data):
        if project.get("slug") == slug:
            return jsonify({
                "ok": True,
                "project": project,
                "position": index + 1,
                "total": len(data),
            })
    return jsonify({"ok": False, "error": "not found"}), 404


@app.route("/api/toggle", methods=["POST"])
@require_login
def api_toggle():
    payload = request.get_json(force=True, silent=True) or {}
    slug = payload.get("slug")
    if not slug:
        return jsonify({"ok": False, "error": "slug required"}), 400
    data, project, idx = find_project(slug)
    if project is None:
        return jsonify({"ok": False, "error": "not found"}), 404
    project["enabled"] = not is_enabled(project)
    data[idx] = project
    save_projects(data)
    sync_miniapp(slug, project)
    return jsonify({"ok": True, "enabled": project["enabled"], "publicCount": write_public_catalog(data)})


@app.route("/api/reorder", methods=["POST"])
@require_login
def api_reorder():
    payload = request.get_json(force=True, silent=True) or {}
    slug = payload.get("slug")
    if not slug:
        return jsonify({"ok": False, "error": "slug required"}), 400

    data = ordered_projects()
    idx = next((i for i, item in enumerate(data) if item.get("slug") == slug), -1)
    if idx < 0:
        return jsonify({"ok": False, "error": "not found"}), 404

    direction = str(payload.get("direction") or "").strip().lower()
    if "position" in payload and payload.get("position") is not None and payload.get("position") != "":
        try:
            position = int(payload.get("position"))
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "position must be an integer"}), 400
        data = apply_dashboard_position(data, slug, position)
    elif direction == "up":
        if idx == 0:
            return jsonify({"ok": True, "position": 1, "unchanged": True, "publicCount": write_public_catalog(data)})
        data[idx - 1], data[idx] = data[idx], data[idx - 1]
        data = renumber_sort_orders(data)
    elif direction == "down":
        if idx >= len(data) - 1:
            return jsonify({"ok": True, "position": len(data), "unchanged": True, "publicCount": write_public_catalog(data)})
        data[idx + 1], data[idx] = data[idx], data[idx + 1]
        data = renumber_sort_orders(data)
    elif direction == "normalize":
        data = renumber_sort_orders(data)
    else:
        return jsonify({"ok": False, "error": "direction (up|down|normalize) or position required"}), 400

    sync_reorder(data)
    new_idx = next((i for i, item in enumerate(data) if item.get("slug") == slug), 0)
    return jsonify({
        "ok": True,
        "slug": slug,
        "position": new_idx + 1,
        "sortOrder": data[new_idx].get("sortOrder"),
        "publicCount": len([p for p in data if is_enabled(p)]),
    })


@app.route("/api/delete", methods=["POST"])
@require_login
def api_delete():
    slug = request.form.get("slug") or (request.get_json(force=True, silent=True) or {}).get("slug")
    if not slug:
        return jsonify({"ok": False, "error": "slug required"}), 400
    miniapp_dir = SITE_ROOT / "miniapps" / slug
    if miniapp_dir.exists():
        shutil.rmtree(miniapp_dir)
    data, _, _ = find_project(slug)
    data = [p for p in data if p.get("slug") != slug]
    add_exclusion(slug)
    data = renumber_sort_orders(ordered_projects(data))
    sync_reorder(data)
    return jsonify({"ok": True, "publicCount": write_public_catalog(data)})


@app.route("/api/update", methods=["POST"])
@require_login
def api_update():
    payload = request.get_json(force=True, silent=True)
    if not payload:
        return jsonify({"ok": False, "error": "invalid json"}), 400
    raw_slug = payload.get("slug")
    if not raw_slug:
        return jsonify({"ok": False, "error": "slug required"}), 400
    try:
        slug = validate_slug(str(raw_slug))
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    payload["slug"] = slug
    payload.setdefault("enabled", True)
    payload.setdefault("requireAuth", False)
    payload.setdefault("logoSize", "md")
    payload.setdefault("reimport", False)
    try:
        normalize_logo_dims(payload)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    # Normalize boolean-ish fields.
    payload["enabled"] = bool(payload.get("enabled") is True or str(payload.get("enabled")).lower() == "true")
    payload["requireAuth"] = bool(payload.get("requireAuth") is True or str(payload.get("requireAuth")).lower() == "true")
    payload["reimport"] = bool(payload.get("reimport") is True or str(payload.get("reimport")).lower() == "true")

    desired_position = None
    if "sortOrder" in payload and payload.get("sortOrder") is not None and payload.get("sortOrder") != "":
        try:
            # Editor treats this as 1-based dashboard position.
            desired_position = max(1, int(payload.get("sortOrder")))
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "sortOrder/position must be an integer"}), 400

    data, _, idx = find_project(slug)
    creating = idx < 0
    if creating:
        if not str(payload.get("name") or "").strip():
            return jsonify({"ok": False, "error": "name required when creating a project"}), 400
        payload = new_project_defaults(slug, payload)
        payload["sortOrder"] = (len(data) + 1) * 10
        data.append(payload)
    else:
        existing = dict(data[idx])
        existing.update(payload)
        # Clearing width/height in the editor must remove prior values.
        if "logoWidth" not in payload:
            existing.pop("logoWidth", None)
        if "logoHeight" not in payload:
            existing.pop("logoHeight", None)
        data[idx] = existing
        payload = existing

    # Updating/saving a project means it is intentionally present again.
    remove_exclusion(slug)

    if desired_position is not None:
        data = apply_dashboard_position(data, slug, desired_position)
        sync_reorder(data)
        refreshed = next(item for item in data if item.get("slug") == slug)
        return jsonify({
            "ok": True,
            "created": creating,
            "project": refreshed,
            "position": desired_position,
            "publicCount": write_public_catalog(data),
        })

    save_projects(data)
    sync_miniapp(slug, payload)
    position = next((i + 1 for i, item in enumerate(ordered_projects(data)) if item.get("slug") == slug), len(data))
    return jsonify({
        "ok": True,
        "created": creating,
        "project": payload,
        "position": position,
        "publicCount": write_public_catalog(data),
    })


@app.route("/api/create", methods=["POST"])
@require_login
def api_create():
    """Create a brand-new project tile without GitHub import."""
    payload = request.get_json(force=True, silent=True) or {}
    try:
        slug = validate_slug(str(payload.get("slug") or payload.get("name") or ""))
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    data, existing, _ = find_project(slug)
    if existing is not None:
        return jsonify({"ok": False, "error": f"slug already exists: {slug}"}), 409
    name = str(payload.get("name") or "").strip()
    if not name:
        return jsonify({"ok": False, "error": "name required"}), 400
    try:
        normalize_logo_dims(payload)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    project = new_project_defaults(slug, payload)
    project["enabled"] = bool(payload.get("enabled", True) is True or str(payload.get("enabled", True)).lower() == "true")
    project["requireAuth"] = bool(payload.get("requireAuth") is True or str(payload.get("requireAuth")).lower() == "true")
    project["sortOrder"] = (len(data) + 1) * 10
    if isinstance(payload.get("details"), list):
        project["details"] = payload["details"]
    if isinstance(payload.get("tags"), list):
        project["tags"] = payload["tags"]
    if isinstance(payload.get("status"), list) and payload["status"]:
        project["status"] = payload["status"]
    data.append(project)
    remove_exclusion(slug)
    save_projects(data)
    sync_miniapp(slug, project)
    (SITE_ROOT / "miniapps" / slug / "assets").mkdir(parents=True, exist_ok=True)
    return jsonify({
        "ok": True,
        "created": True,
        "project": project,
        "position": len(data),
        "publicCount": write_public_catalog(data),
    })


@app.route("/api/sites", methods=["GET"])
@require_login
@require_platform
def api_list_sites():
    root = sites_root()
    status = str(request.args.get("status") or "").strip().lower() or None
    if status and status not in SITE_STATUSES:
        return jsonify({"ok": False, "error": f"invalid status filter: {status}"}), 400
    include_deleted = str(request.args.get("includeDeleted") or "").strip().lower() in {"1", "true", "yes"}
    return jsonify({
        "ok": True,
        "platform": True,
        "available": root.is_dir(),
        "sitesRoot": str(root),
        "activeSiteId": SITE_ID,
        "statuses": list(SITE_STATUSES),
        "siteTypes": list(SITE_TYPES),
        "integrationsCatalog": list(KNOWN_INTEGRATIONS),
        "sites": list_local_sites(include_deleted=include_deleted, status=status),
        "hint": None if root.is_dir() else "Site scaffolding is available via CLI: python cli/scripts/create_site.py <site-id>",
    })


@app.route("/api/sites", methods=["POST"])
@require_login
@require_platform
def api_create_site():
    """Scaffold a new VeerCanvas website under sites/<id> (platform control plane only)."""
    root = sites_root()
    if not root.parent.exists():
        return jsonify({
            "ok": False,
            "error": "Platform sites directory is not available in this deployment layout. Use CLI create_site.py on the repo checkout.",
        }), 400
    payload = request.get_json(force=True, silent=True) or {}
    site_id = str(payload.get("id") or payload.get("siteId") or "").strip()
    if not site_id:
        return jsonify({"ok": False, "error": "id required"}), 400
    try:
        created = create_site_scaffold(
            site_id,
            name=str(payload.get("name") or "").strip(),
            domain=str(payload.get("domain") or "").strip(),
            github_owner=str(payload.get("githubOwner") or "").strip(),
            description=str(payload.get("description") or "").strip(),
            site_type=str(payload.get("siteType") or "responsive").strip(),
            template_id=str(payload.get("templateId") or "catalog-static").strip(),
            locales=payload.get("locales"),
            default_locale=str(payload.get("defaultLocale") or "en").strip(),
            repos=payload.get("repos"),
            integrations=payload.get("integrations"),
            force=bool(payload.get("force")),
        )
    except FileExistsError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 409
    except FileNotFoundError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    return jsonify({"ok": True, "site": created, "sites": list_local_sites()})


@app.route("/api/sites/<site_id>", methods=["GET"])
@require_login
@require_platform
def api_get_site(site_id: str):
    try:
        site_id = validate_slug(site_id)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    cfg = load_site_config(site_id)
    if not cfg:
        return jsonify({"ok": False, "error": f"unknown site: {site_id}"}), 404
    return jsonify({"ok": True, "site": cfg})


@app.route("/api/sites/<site_id>", methods=["PATCH"])
@require_login
@require_platform
def api_patch_site(site_id: str):
    try:
        site_id = validate_slug(site_id)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    cfg = load_site_config(site_id)
    if not cfg:
        return jsonify({"ok": False, "error": f"unknown site: {site_id}"}), 404
    payload = request.get_json(force=True, silent=True) or {}

    if "status" in payload:
        new_status = str(payload.get("status") or "").strip().lower()
        if new_status not in SITE_STATUSES:
            return jsonify({"ok": False, "error": f"invalid status: {new_status}"}), 400
        if new_status == "deleted":
            try:
                cfg = soft_delete_site(site_id)
            except PermissionError as exc:
                return jsonify({"ok": False, "error": str(exc)}), 403
            return jsonify({"ok": True, "site": cfg, "sites": list_local_sites(include_deleted=True)})
        cfg["status"] = new_status
        append_status_history(cfg, new_status, str(payload.get("statusNote") or "Status updated"))

    for field in SITE_DEFINITION_PATCH_FIELDS:
        if field not in payload:
            continue
        if field == "locales":
            locales, default_locale = normalize_locales(
                payload.get("locales"),
                str(payload.get("defaultLocale") or cfg.get("defaultLocale") or "en"),
            )
            cfg["locales"] = locales
            cfg["defaultLocale"] = default_locale
        elif field == "defaultLocale" and "locales" not in payload:
            locales, default_locale = normalize_locales(cfg.get("locales"), str(payload.get("defaultLocale") or "en"))
            cfg["locales"] = locales
            cfg["defaultLocale"] = default_locale
        elif field == "repos":
            cfg["repos"] = normalize_repos(payload.get("repos"))
        elif field == "integrations":
            cfg["integrations"] = normalize_integrations(payload.get("integrations"))
        elif field == "aliases":
            aliases = payload.get("aliases")
            if isinstance(aliases, list):
                cfg["aliases"] = [str(a).strip() for a in aliases if str(a).strip()]
        elif field == "siteType":
            site_type = str(payload.get("siteType") or "").strip().lower()
            if site_type not in SITE_TYPES:
                return jsonify({"ok": False, "error": f"invalid siteType: {site_type}"}), 400
            cfg["siteType"] = site_type
        elif field == "templateId":
            tid = str(payload.get("templateId") or "").strip()
            if tid:
                cfg["templateId"] = tid
                entry = get_template_entry(tid)
                if entry and entry.get("version"):
                    cfg["templateVersion"] = entry["version"]
        elif field == "domain":
            domain = str(payload.get("domain") or "").strip()
            if domain:
                cfg["domain"] = domain
                cfg["webRoot"] = f"/var/www/{domain}"
        else:
            value = payload.get(field)
            if value is not None:
                cfg[field] = str(value).strip() if isinstance(value, str) else value

    existing = load_site_config(site_id) or {}
    cfg["platform"] = bool(existing.get("platform"))
    cfg["ops"] = bool(existing.get("ops"))
    cfg["updatedAt"] = utc_iso_now()
    saved = save_site_config(site_id, cfg)
    return jsonify({"ok": True, "site": saved, "sites": list_local_sites(include_deleted=True)})


@app.route("/api/sites/<site_id>", methods=["DELETE"])
@require_login
@require_platform
def api_delete_site(site_id: str):
    try:
        site_id = validate_slug(site_id)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    hard = str(request.args.get("hard") or "").strip().lower() in {"1", "true", "yes"}
    try:
        if hard:
            hard_delete_site(site_id)
            return jsonify({"ok": True, "hardDeleted": True, "siteId": site_id, "sites": list_local_sites(include_deleted=True)})
        cfg = soft_delete_site(site_id)
        return jsonify({"ok": True, "site": cfg, "sites": list_local_sites(include_deleted=True)})
    except FileNotFoundError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 404
    except PermissionError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 403
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


@app.route("/api/templates", methods=["GET"])
@require_login
@require_platform
def api_list_templates():
    registry = load_template_registry()
    return jsonify({
        "ok": True,
        "templates": registry.get("templates") or [],
        "siteTypes": list(SITE_TYPES),
        "templatesRoot": str(templates_root()),
    })


@app.route("/api/templates/<template_id>/preview", methods=["GET"])
@require_login
@require_platform
def api_template_preview(template_id: str):
    try:
        tid = validate_slug(template_id)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    entry = get_template_entry(tid)
    source = str((entry or {}).get("source") or tid)
    package = templates_root() / source
    preview = package / "preview.svg"
    if not preview.is_file():
        return jsonify({"ok": False, "error": "preview not found"}), 404
    return send_from_directory(package, "preview.svg", mimetype="image/svg+xml")


@app.route("/api/templates", methods=["POST"])
@require_login
@require_platform
def api_create_template():
    payload = request.get_json(force=True, silent=True) or {}
    template_id = str(payload.get("id") or "").strip()
    if not template_id:
        return jsonify({"ok": False, "error": "id required"}), 400
    try:
        entry = clone_template_package(
            template_id,
            name=str(payload.get("name") or "").strip(),
            description=str(payload.get("description") or "").strip(),
            site_types=payload.get("siteTypes"),
            clone_from=str(payload.get("cloneFrom") or "catalog-static").strip() or "catalog-static",
            layout=str(payload.get("layout") or "").strip(),
        )
    except FileExistsError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 409
    except FileNotFoundError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    return jsonify({"ok": True, "template": entry, "templates": load_template_registry().get("templates") or []})


@app.route("/api/sites/<site_id>/deploy", methods=["POST"])
@require_login
@require_platform
def api_deploy_site(site_id: str):
    """Run remote-deploy.sh for a scaffolded site (production promote)."""
    try:
        site_id = validate_slug(site_id)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    cfg = load_site_config(site_id)
    if not cfg:
        return jsonify({"ok": False, "error": f"unknown site: {site_id}"}), 404
    if cfg.get("status") in {"deleted", "disabled"}:
        return jsonify({
            "ok": False,
            "error": f"cannot deploy site while status is {cfg.get('status')}",
        }), 400
    site_dir = sites_root() / site_id
    if not site_dir.is_dir():
        return jsonify({"ok": False, "error": f"unknown site: {site_id}"}), 404
    payload = request.get_json(force=True, silent=True) or {}
    deploy_script = VEERCANVAS_ROOT / "deploy" / "remote-deploy.sh"
    if not deploy_script.is_file():
        return jsonify({
            "ok": False,
            "error": "remote-deploy.sh not found on this host",
            "cli": f"SITE_ID={site_id} EC2_KEY=./VeerSetuHost.pem ./deploy/remote-deploy.sh",
        }), 400
    key = (
        str(payload.get("ec2Key") or "").strip()
        or os.environ.get("VEERCANVAS_DEPLOY_KEY", "").strip()
        or os.environ.get("EC2_KEY", "").strip()
    )
    host = str(payload.get("ec2Host") or os.environ.get("EC2_HOST", "")).strip()
    env = os.environ.copy()
    env["SITE_ID"] = site_id
    if key:
        env["EC2_KEY"] = key
    if host:
        env["EC2_HOST"] = host
    if not key or not pathlib.Path(key).is_file():
        return jsonify({
            "ok": False,
            "error": "Deploy key not configured on platform host. Set VEERCANVAS_DEPLOY_KEY or pass ec2Key.",
            "cli": f"SITE_ID={site_id} EC2_KEY=./VeerSetuHost.pem ./deploy/remote-deploy.sh",
        }), 400
    try:
        completed = subprocess.run(
            ["bash", str(deploy_script)],
            cwd=str(VEERCANVAS_ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=int(payload.get("timeout") or 900),
            check=False,
        )
    except subprocess.TimeoutExpired:
        return jsonify({"ok": False, "error": "Deploy timed out"}), 504
    ok = completed.returncode == 0
    if ok:
        cfg["status"] = "published"
        cfg["updatedAt"] = utc_iso_now()
        append_status_history(cfg, "published", "Deploy succeeded")
        save_site_config(site_id, cfg)
    return jsonify({
        "ok": ok,
        "siteId": site_id,
        "site": load_site_config(site_id),
        "returncode": completed.returncode,
        "stdout": (completed.stdout or "")[-8000:],
        "stderr": (completed.stderr or "")[-4000:],
    }), (200 if ok else 500)


@app.route("/api/upload-logo", methods=["POST"])
@require_login
def api_upload_logo():
    slug = request.form.get("slug")
    file = request.files.get("logo")
    if not slug or not file:
        return jsonify({"ok": False, "error": "slug and logo file required"}), 400
    ext = pathlib.Path(file.filename or "").suffix.lower()
    if ext not in {".png", ".jpg", ".jpeg", ".svg", ".webp", ".gif"}:
        return jsonify({"ok": False, "error": "unsupported image type"}), 400
    assets_dir = SITE_ROOT / "miniapps" / slug / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    dest = assets_dir / f"logo{ext}"
    for old in assets_dir.glob("logo.*"):
        if old.name != dest.name:
            try:
                old.unlink()
            except OSError:
                pass
    file.save(dest)
    opt = optimize_logo_file(dest, force=True)
    try:
        os.chmod(dest, 0o644)
    except OSError:
        pass
    logo_path = f"miniapps/{slug}/assets/logo{ext}"
    data, project, idx = find_project(slug)
    if project is None:
        return jsonify({"ok": False, "error": "project not found"}), 404
    project["logo"] = logo_path
    data[idx] = project
    save_projects(data)
    sync_miniapp(slug, project)
    return jsonify({
        "ok": True,
        "logo": logo_path,
        "optimized": bool(opt.get("optimized")),
        "bytesBefore": opt.get("bytes_before"),
        "bytesAfter": opt.get("bytes_after"),
        "variants": [v.get("path") for v in opt.get("variants") or [] if v.get("path")],
        "optimizeError": opt.get("error") or opt.get("skipped"),
    })


@app.route("/api/upload-brand", methods=["POST"])
@require_login
def api_upload_brand():
    """Upload/replace site brand mark or favicon under assets/site/."""
    kind = (request.form.get("kind") or "brandMark").strip()
    file = request.files.get("file") or request.files.get("logo")
    if kind not in {"brandMark", "favicon", "platformMark"}:
        return jsonify({"ok": False, "error": "kind must be brandMark, platformMark, or favicon"}), 400
    if not file:
        return jsonify({"ok": False, "error": "image file required"}), 400
    ext = pathlib.Path(file.filename or "").suffix.lower()
    if ext not in {".png", ".jpg", ".jpeg", ".svg", ".webp", ".gif", ".ico"}:
        return jsonify({"ok": False, "error": "unsupported image type"}), 400
    if kind == "favicon" and ext not in {".png", ".svg", ".ico", ".webp", ".gif"}:
        return jsonify({"ok": False, "error": "favicon must be png, svg, ico, webp, or gif"}), 400

    assets_dir = SITE_ROOT / "assets" / "site"
    assets_dir.mkdir(parents=True, exist_ok=True)
    stem = {
        "brandMark": "brand-mark",
        "platformMark": "platform-mark",
        "favicon": "favicon",
    }[kind]
    # Remove previous variants so only one active file remains.
    for old in assets_dir.glob(f"{stem}.*"):
        try:
            old.unlink()
        except OSError:
            pass
    dest = assets_dir / f"{stem}{ext}"
    file.save(dest)
    if not dest.exists() or dest.stat().st_size <= 0:
        return jsonify({"ok": False, "error": f"failed to write {dest}"}), 500
    # Keep permissions readable by nginx.
    try:
        os.chmod(dest, 0o644)
    except OSError:
        pass
    rel_path = f"assets/site/{stem}{ext}"

    meta = load_site_meta()
    meta[kind] = rel_path
    meta["lastUpdated"] = utc_now()
    save_site_meta(meta)
    return jsonify({
        "ok": True,
        "kind": kind,
        "path": rel_path,
        "bytes": dest.stat().st_size,
        "meta": meta,
        "publicUrl": f"/{rel_path}",
        "adminUrl": f"/site/{rel_path}",
    })


def resolve_site_asset_path(rel: str) -> pathlib.Path | None:
    if not rel or not isinstance(rel, str):
        return None
    cleaned = rel.split("?", 1)[0].strip().lstrip("/")
    if not cleaned or ".." in cleaned.split("/"):
        return None
    path = (SITE_ROOT / cleaned).resolve()
    try:
        path.relative_to(SITE_ROOT.resolve())
    except ValueError:
        return None
    return path


def ensure_brand_assets(meta: dict | None = None) -> dict:
    """If configured brand/favicon paths are missing on disk, fall back to bundled defaults."""
    data = dict(meta or load_site_meta())
    defaults = {
        "brandMark": "assets/veer-canvas-icon.svg",
        "platformMark": "assets/veer-canvas-icon.svg",
        "favicon": "assets/favicon.svg",
    }
    changed = False
    for key, fallback in defaults.items():
        rel = str(data.get(key) or "").strip()
        path = resolve_site_asset_path(rel) if rel else None
        if path and path.exists() and path.is_file():
            continue
        # Prefer a previously uploaded assets/site file when path is broken.
        stem = {
            "brandMark": "brand-mark",
            "platformMark": "platform-mark",
            "favicon": "favicon",
        }[key]
        uploaded = None
        site_dir = SITE_ROOT / "assets" / "site"
        if site_dir.exists():
            matches = sorted(site_dir.glob(f"{stem}.*"))
            uploaded = next((p for p in matches if p.is_file() and p.stat().st_size > 0), None)
        if uploaded:
            data[key] = f"assets/site/{uploaded.name}"
        else:
            data[key] = fallback
        changed = True
    if changed:
        data["lastUpdated"] = utc_now()
        save_site_meta(data)
    return data


@app.route("/api/site-meta", methods=["GET"])
@require_login
def api_get_site_meta():
    return jsonify({"ok": True, "meta": ensure_brand_assets()})


@app.route("/api/site-meta", methods=["POST"])
@require_login
def api_update_site_meta():
    payload = request.get_json(force=True, silent=True) or {}
    meta = apply_site_content(load_site_meta(), payload)
    # Reject brand/favicon paths that do not exist on disk (common cause of live 404s).
    for key in ("brandMark", "platformMark", "favicon"):
        rel = str(meta.get(key) or "").strip()
        if not rel:
            continue
        path = resolve_site_asset_path(rel)
        if not path or not path.exists():
            return jsonify({
                "ok": False,
                "error": f"{key} file not found: {rel}. Upload the asset first.",
            }), 400
    meta["lastUpdated"] = utc_now()
    save_site_meta(meta)
    return jsonify({"ok": True, "meta": meta})


@app.route("/api/import", methods=["POST"])
@require_login
def api_import():
    status = github_token_status()
    if not status["configured"]:
        return jsonify({
            "ok": False,
            "error": "GitHub token not configured. Save a PAT with repo scope under GitHub access, then Sync again.",
            "token": status,
        }), 400
    payload = request.get_json(force=True, silent=True) or {}
    include_private = payload.get("includePrivate", True)
    reimport_all = bool(payload.get("reimportAll", False))
    reimport_slugs = payload.get("reimportSlugs") or []
    only_slugs = payload.get("onlySlugs") or []
    if isinstance(reimport_slugs, str):
        reimport_slugs = [s.strip() for s in reimport_slugs.split(",") if s.strip()]
    if isinstance(only_slugs, str):
        only_slugs = [s.strip() for s in only_slugs.split(",") if s.strip()]
    # Collect projects marked reimport:true unless caller forces everything / specific slugs.
    if not reimport_all and not reimport_slugs:
        reimport_slugs = [p["slug"] for p in load_projects() if p.get("slug") and (
            p.get("reimport") is True or str(p.get("reimport", "")).lower() in {"true", "1", "yes", "on"}
        )]
    before_slugs = {p.get("slug") for p in load_projects() if p.get("slug")}
    try:
        ok, output, summary = run_import(
            include_private=include_private,
            reimport_all=reimport_all,
            reimport_slugs=reimport_slugs or None,
            only_slugs=only_slugs or None,
        )
    except subprocess.TimeoutExpired:
        return jsonify({
            "ok": False,
            "error": "GitHub sync timed out after 10 minutes. Try again or sync specific slugs.",
            "token": status,
        }), 504
    if not ok and ("401" in output or "Bad credentials" in output or "Requires authentication" in output):
        return jsonify({
            "ok": False,
            "error": "GitHub rejected the token (401). Update the PAT under GitHub access.",
            "output": output,
            "token": status,
            "summary": summary,
        }), 401
    meta = load_site_meta()
    public_count = write_public_catalog()
    after = load_projects()
    after_slugs = {p.get("slug") for p in after if p.get("slug")}
    new_slugs = sorted(after_slugs - before_slugs)
    if new_slugs:
        summary["newSlugs"] = new_slugs
        if not summary.get("importedSlugs"):
            summary["importedSlugs"] = new_slugs
    return jsonify({
        "ok": ok,
        "output": output,
        "summary": summary,
        "projectCount": len(after),
        "publicCount": public_count,
        "newSlugs": new_slugs,
        "version": meta.get("version"),
        "token": status,
    }), (200 if ok else 500)


@app.route("/api/github-status", methods=["GET", "POST"])
@require_login
def api_github_status():
    return jsonify({"ok": True, "github": probe_github_token(), "owner": DEFAULT_OWNER})


@app.route("/api/github-token", methods=["GET"])
@require_login
def api_github_token_status():
    return jsonify({"ok": True, "token": github_token_status(), "github": probe_github_token()})


@app.route("/api/github-token", methods=["POST"])
@require_login
def api_save_github_token():
    payload = request.get_json(force=True, silent=True) or {}
    token = str(payload.get("token") or "").strip()
    if not token:
        return jsonify({"ok": False, "error": "token required"}), 400
    if len(token) < 20:
        return jsonify({"ok": False, "error": "token looks too short"}), 400
    path = github_token_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(token + "\n", encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return jsonify({"ok": True, "token": github_token_status(), "github": probe_github_token()})


@app.route("/api/mark-reimport", methods=["POST"])
@require_login
def api_mark_reimport():
    payload = request.get_json(force=True, silent=True) or {}
    slug = payload.get("slug")
    if not slug:
        return jsonify({"ok": False, "error": "slug required"}), 400
    data, project, idx = find_project(slug)
    if project is None:
        return jsonify({"ok": False, "error": "not found"}), 404
    project["reimport"] = True
    data[idx] = project
    save_projects(data)
    sync_miniapp(slug, project)
    return jsonify({"ok": True, "slug": slug, "reimport": True})


@app.route("/api/publish", methods=["POST"])
@require_login
def api_publish():
    meta = load_site_meta()
    meta["version"] = bump_minor_version(meta.get("version", "v1.0.0"))
    meta["lastUpdated"] = utc_now()
    save_site_meta(meta)
    # Re-sync catalog from miniapps to ensure consistency (does not contact GitHub).
    if IMPORT_SCRIPT.exists():
        subprocess.run([
            sys.executable, str(IMPORT_SCRIPT), DEFAULT_OWNER, "imported_projects",
            "--site-root", str(SITE_ROOT), "--projects-json", str(projects_path()),
            "--sync-only",
        ], check=False, capture_output=True, text=True)
    public_count = write_public_catalog()
    return jsonify({
        "ok": True,
        "meta": meta,
        "projectCount": len(load_projects()),
        "publicCount": public_count,
    })


@app.route("/api/lookup", methods=["GET"])
@require_login
def api_lookup():
    q = request.args.get("q", "").lower()
    results = []
    for project in load_projects():
        hay = " ".join([
            project.get("slug", ""),
            project.get("name", ""),
            project.get("subtitle", ""),
            project.get("summary", ""),
        ]).lower()
        if not q or q in hay:
            results.append(project)
    return jsonify(results)


# --- Public engagement + contact (no login) ---------------------------------

def engagement_path() -> pathlib.Path:
    return SITE_ROOT / "engagement.json"


def contact_inbox_path() -> pathlib.Path:
    return SITE_ROOT / "contact-messages.json"


def load_engagement() -> dict:
    path = engagement_path()
    if not path.exists():
        return {"projects": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"projects": {}}
    if not isinstance(data, dict):
        return {"projects": {}}
    projects = data.get("projects")
    if not isinstance(projects, dict):
        data["projects"] = {}
    return data


def save_engagement(data: dict) -> None:
    engagement_path().write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def load_contact_inbox() -> dict:
    path = contact_inbox_path()
    if not path.exists():
        return {"messages": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"messages": []}
    if not isinstance(data, dict) or not isinstance(data.get("messages"), list):
        return {"messages": []}
    return data


def save_contact_inbox(data: dict) -> None:
    contact_inbox_path().write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def project_engagement(slug: str, data: dict | None = None) -> dict:
    store = data if data is not None else load_engagement()
    projects = store.setdefault("projects", {})
    entry = projects.get(slug)
    if not isinstance(entry, dict):
        entry = {"likes": 0, "dislikes": 0, "votes": {}, "comments": []}
        projects[slug] = entry
    entry.setdefault("likes", 0)
    entry.setdefault("dislikes", 0)
    entry.setdefault("votes", {})
    entry.setdefault("comments", [])
    if not isinstance(entry["votes"], dict):
        entry["votes"] = {}
    if not isinstance(entry["comments"], list):
        entry["comments"] = []
    return entry


def public_comments(entry: dict) -> list[dict]:
    out = []
    for comment in entry.get("comments") or []:
        if not isinstance(comment, dict) or comment.get("hidden"):
            continue
        out.append({
            "id": comment.get("id"),
            "name": comment.get("name") or "Guest",
            "text": comment.get("text") or "",
            "createdAt": comment.get("createdAt"),
        })
    return out


def engagement_summary(entry: dict, visitor_id: str | None = None) -> dict:
    vote = None
    if visitor_id and isinstance(entry.get("votes"), dict):
        vote = entry["votes"].get(visitor_id)
    return {
        "likes": int(entry.get("likes") or 0),
        "dislikes": int(entry.get("dislikes") or 0),
        "commentCount": len(public_comments(entry)),
        "vote": vote if vote in {"like", "dislike"} else None,
    }


def client_ip() -> str:
    forwarded = (request.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
    return forwarded or (request.remote_addr or "unknown")


def honeypot_tripped(payload: dict) -> bool:
    bait = str(payload.get("website") or payload.get("companyUrl") or "").strip()
    return bool(bait)


@app.route("/api/public/engagement", methods=["GET"])
def api_public_engagement_all():
    visitor_id = (request.args.get("visitorId") or "").strip()[:80]
    store = load_engagement()
    summary = {}
    for slug, entry in (store.get("projects") or {}).items():
        if not isinstance(entry, dict):
            continue
        summary[slug] = engagement_summary(entry, visitor_id or None)
    return jsonify({"ok": True, "projects": summary})


@app.route("/api/public/engagement/<slug>", methods=["GET"])
def api_public_engagement_one(slug: str):
    try:
        slug = validate_slug(slug)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    visitor_id = (request.args.get("visitorId") or "").strip()[:80]
    include_comments = (request.args.get("comments") or "").lower() in {"1", "true", "yes"}
    entry = project_engagement(slug)
    payload = {"ok": True, "slug": slug, **engagement_summary(entry, visitor_id or None)}
    if include_comments:
        payload["comments"] = public_comments(entry)
    return jsonify(payload)


@app.route("/api/public/engagement/<slug>/vote", methods=["POST"])
def api_public_vote(slug: str):
    try:
        slug = validate_slug(slug)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    payload = request.get_json(force=True, silent=True) or {}
    if honeypot_tripped(payload):
        return jsonify({"ok": True, "ignored": True})
    action = str(payload.get("action") or "").strip().lower()
    if action not in {"like", "dislike", "clear"}:
        return jsonify({"ok": False, "error": "action must be like, dislike, or clear"}), 400
    visitor_id = str(payload.get("visitorId") or "").strip()[:80]
    if not visitor_id or not re.match(r"^[a-zA-Z0-9_-]{8,80}$", visitor_id):
        return jsonify({"ok": False, "error": "visitorId required"}), 400

    store = load_engagement()
    entry = project_engagement(slug, store)
    votes = entry["votes"]
    previous = votes.get(visitor_id)
    if previous == "like":
        entry["likes"] = max(0, int(entry.get("likes") or 0) - 1)
    elif previous == "dislike":
        entry["dislikes"] = max(0, int(entry.get("dislikes") or 0) - 1)

    if action == "clear" or previous == action:
        votes.pop(visitor_id, None)
    else:
        votes[visitor_id] = action
        if action == "like":
            entry["likes"] = int(entry.get("likes") or 0) + 1
        else:
            entry["dislikes"] = int(entry.get("dislikes") or 0) + 1

    # Cap stored vote map size per project to avoid unbounded growth.
    if len(votes) > 5000:
        for old_key in list(votes.keys())[: len(votes) - 5000]:
            votes.pop(old_key, None)

    save_engagement(store)
    return jsonify({"ok": True, "slug": slug, **engagement_summary(entry, visitor_id)})


@app.route("/api/public/engagement/<slug>/comments", methods=["POST"])
def api_public_comment(slug: str):
    try:
        slug = validate_slug(slug)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    payload = request.get_json(force=True, silent=True) or {}
    if honeypot_tripped(payload):
        return jsonify({"ok": True, "ignored": True})
    name = re.sub(r"\s+", " ", str(payload.get("name") or "Guest")).strip()[:60] or "Guest"
    text = re.sub(r"\s+", " ", str(payload.get("text") or payload.get("comment") or "")).strip()
    if len(text) < 3:
        return jsonify({"ok": False, "error": "Comment is too short"}), 400
    if len(text) > 1000:
        return jsonify({"ok": False, "error": "Comment is too long (max 1000 chars)"}), 400

    store = load_engagement()
    entry = project_engagement(slug, store)
    comment = {
        "id": uuid.uuid4().hex[:12],
        "name": name,
        "text": text,
        "createdAt": utc_now(),
        "ip": client_ip()[:64],
        "hidden": False,
    }
    entry["comments"].append(comment)
    # Keep last 200 comments per project.
    if len(entry["comments"]) > 200:
        entry["comments"] = entry["comments"][-200:]
    save_engagement(store)
    return jsonify({
        "ok": True,
        "slug": slug,
        "comment": {
            "id": comment["id"],
            "name": comment["name"],
            "text": comment["text"],
            "createdAt": comment["createdAt"],
        },
        **engagement_summary(entry, str(payload.get("visitorId") or "").strip()[:80] or None),
    })


@app.route("/api/public/contact", methods=["POST"])
def api_public_contact():
    payload = request.get_json(force=True, silent=True) or {}
    if honeypot_tripped(payload):
        return jsonify({"ok": True, "ignored": True})
    name = re.sub(r"\s+", " ", str(payload.get("name") or "")).strip()[:80]
    email = str(payload.get("email") or "").strip()[:120]
    message = re.sub(r"\s+", " ", str(payload.get("message") or "")).strip()
    if len(name) < 2:
        return jsonify({"ok": False, "error": "Name is required"}), 400
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        return jsonify({"ok": False, "error": "Valid email is required"}), 400
    if len(message) < 5:
        return jsonify({"ok": False, "error": "Message is too short"}), 400
    if len(message) > 4000:
        return jsonify({"ok": False, "error": "Message is too long"}), 400

    inbox = load_contact_inbox()
    item = {
        "id": uuid.uuid4().hex[:12],
        "name": name,
        "email": email,
        "message": message,
        "createdAt": utc_now(),
        "ip": client_ip()[:64],
        "read": False,
    }
    inbox["messages"].insert(0, item)
    inbox["messages"] = inbox["messages"][:500]
    save_contact_inbox(inbox)
    return jsonify({"ok": True, "id": item["id"]})


VISITOR_TOKEN_TTL_SECONDS = int(os.environ.get("VEERCANVAS_VISITOR_TOKEN_TTL", "3600"))
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def visitor_access_path() -> pathlib.Path:
    return SITE_ROOT / "visitor-access.json"


def load_visitor_access() -> dict:
    path = visitor_access_path()
    if not path.exists():
        return {"visitors": {}, "tokens": {}, "events": [], "visits": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"visitors": {}, "tokens": {}, "events": [], "visits": []}
    if not isinstance(data, dict):
        return {"visitors": {}, "tokens": {}, "events": [], "visits": []}
    data.setdefault("visitors", {})
    data.setdefault("tokens", {})
    data.setdefault("events", [])
    data.setdefault("visits", [])
    return data


def save_visitor_access(data: dict) -> None:
    visitor_access_path().write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def purge_expired_visitor_tokens(store: dict) -> None:
    now = datetime.now(timezone.utc)
    tokens = store.get("tokens") if isinstance(store.get("tokens"), dict) else {}
    keep = {}
    for token, meta in tokens.items():
        if not isinstance(meta, dict):
            continue
        expires = str(meta.get("expiresAt") or "")
        try:
            exp_dt = datetime.fromisoformat(expires.replace("Z", "+00:00"))
        except ValueError:
            continue
        if exp_dt > now:
            keep[token] = meta
    store["tokens"] = keep


def parse_user_agent(ua: str) -> dict:
    text = (ua or "").strip()
    lower = text.lower()
    browser = "Other"
    if "edg/" in lower:
        browser = "Edge"
    elif "chrome/" in lower and "chromium" not in lower:
        browser = "Chrome"
    elif "firefox/" in lower:
        browser = "Firefox"
    elif "safari/" in lower and "chrome/" not in lower:
        browser = "Safari"
    elif "msie" in lower or "trident/" in lower:
        browser = "IE"
    os_name = "Other"
    if "android" in lower:
        os_name = "Android"
    elif "iphone" in lower or "ipad" in lower or "ios" in lower:
        os_name = "iOS"
    elif "mac os" in lower or "macintosh" in lower:
        os_name = "macOS"
    elif "windows" in lower:
        os_name = "Windows"
    elif "linux" in lower:
        os_name = "Linux"
    device = "desktop"
    if "mobile" in lower or "android" in lower or "iphone" in lower:
        device = "mobile"
    elif "ipad" in lower or "tablet" in lower:
        device = "tablet"
    return {"browser": browser, "os": os_name, "device": device}


def append_visit(store: dict, payload: dict | None = None) -> dict:
    """Record a page visit (authed or anonymous) with metrics-friendly fields."""
    payload = payload if isinstance(payload, dict) else {}
    token = (request.headers.get("X-Visitor-Token") or payload.get("token") or "").strip()
    auth = access_authorized(store, token)
    ua = str(payload.get("userAgent") or request.headers.get("User-Agent") or "")[:400]
    ua_meta = parse_user_agent(ua)
    path = str(payload.get("path") or request.path or "/")[:300]
    referrer = str(payload.get("referrer") or request.headers.get("Referer") or "")[:500]
    referrer_host = ""
    if referrer:
        try:
            referrer_host = (urlparse(referrer).hostname or "")[:120]
        except Exception:  # noqa: BLE001
            referrer_host = ""
    visitor_id = str(payload.get("visitorId") or auth.get("visitorId") or "").strip()[:80]
    if visitor_id and not re.match(r"^[a-zA-Z0-9_-]{8,80}$", visitor_id):
        visitor_id = ""
    if not visitor_id:
        visitor_id = f"anon_{secrets.token_urlsafe(8)}"[:24]

    page = str(payload.get("page") or "").strip().lower()[:40]
    if not page:
        if "project.html" in path:
            page = "project"
        elif path in {"/", "/index.html", "index.html"} or path.endswith("/index.html"):
            page = "home"
        else:
            page = "other"

    try:
        screen_w = max(0, int(float(payload.get("screenW") or 0)))
        screen_h = max(0, int(float(payload.get("screenH") or 0)))
    except (TypeError, ValueError):
        screen_w, screen_h = 0, 0

    slug = str(payload.get("slug") or "").strip()[:80]
    utm = payload.get("utm") if isinstance(payload.get("utm"), dict) else {}
    auth_mode = auth.get("mode") or "anonymous"
    visit = {
        "id": uuid.uuid4().hex[:12],
        "at": utc_now(),
        "ip": client_ip()[:64],
        "visitorId": visitor_id,
        "path": path,
        "page": page,
        "slug": slug,
        "title": str(payload.get("title") or "")[:200],
        "referrer": referrer,
        "referrerHost": referrer_host,
        "userAgent": ua,
        "browser": ua_meta["browser"],
        "os": ua_meta["os"],
        "device": ua_meta["device"],
        "language": str(payload.get("language") or request.headers.get("Accept-Language") or "")[:80],
        "timezone": str(payload.get("timezone") or "")[:80],
        "screenW": screen_w,
        "screenH": screen_h,
        "authMode": auth_mode,
        "hasToken": auth_mode == "visitor",
        "isAdmin": auth_mode == "admin",
        "name": auth.get("username") or auth.get("name") or "",
        "email": auth.get("email") or "",
        "sessionId": str(payload.get("sessionId") or "")[:64],
        "utmSource": str(utm.get("source") or payload.get("utmSource") or "")[:80],
        "utmMedium": str(utm.get("medium") or payload.get("utmMedium") or "")[:80],
        "utmCampaign": str(utm.get("campaign") or payload.get("utmCampaign") or "")[:80],
        "siteId": SITE_ID,
    }

    visits = store.get("visits")
    if not isinstance(visits, list):
        visits = []
    visits.insert(0, visit)
    store["visits"] = visits[:5000]

    # Touch anonymous/known visitor profile lightly for metrics continuity
    visitors = store.setdefault("visitors", {})
    prev = visitors.get(visitor_id) if isinstance(visitors.get(visitor_id), dict) else {}
    visitors[visitor_id] = {
        "name": visit["name"] or prev.get("name") or "",
        "email": visit["email"] or prev.get("email") or "",
        "createdAt": prev.get("createdAt") or visit["at"],
        "lastSeenAt": visit["at"],
        "lastIp": visit["ip"],
        "lastPath": visit["path"],
        "visitCount": int(prev.get("visitCount") or 0) + 1,
    }
    return visit


def append_visitor_event(store: dict, *, event_type: str, visitor_id: str, name: str = "", email: str = "", slug: str = "", note: str = "") -> None:
    events = store.get("events")
    if not isinstance(events, list):
        events = []
    events.insert(0, {
        "id": uuid.uuid4().hex[:12],
        "at": utc_now(),
        "type": event_type,
        "visitorId": visitor_id,
        "name": name,
        "email": email,
        "slug": slug,
        "siteId": SITE_ID,
        "note": note,
        "ip": client_ip()[:64],
    })
    store["events"] = events[:1000]


def resolve_visitor_token(store: dict, token: str | None) -> dict | None:
    if not token:
        return None
    purge_expired_visitor_tokens(store)
    meta = (store.get("tokens") or {}).get(token)
    if not isinstance(meta, dict):
        return None
    return meta


def project_requires_auth(slug: str) -> bool:
    _, project, _ = find_project(slug)
    if not project:
        return False
    value = project.get("requireAuth", False)
    if value is True or value == 1:
        return True
    if isinstance(value, str) and value.strip().lower() in {"true", "1", "yes", "on"}:
        return True
    return False


def access_authorized(store: dict | None = None, token: str | None = None) -> dict:
    """Return auth state for public Learn More gates."""
    if session.get("logged_in"):
        return {
            "authorized": True,
            "mode": "admin",
            "username": session.get("username") or "admin",
            "expiresAt": None,
            "visitorId": None,
        }
    store = store if store is not None else load_visitor_access()
    token = (token or request.headers.get("X-Visitor-Token") or request.args.get("token") or "").strip()
    meta = resolve_visitor_token(store, token)
    if meta:
        return {
            "authorized": True,
            "mode": "visitor",
            "username": meta.get("name") or "",
            "expiresAt": meta.get("expiresAt"),
            "visitorId": meta.get("visitorId"),
            "email": meta.get("email") or "",
            "token": token,
        }
    return {"authorized": False, "mode": None}


@app.route("/api/public/access/status", methods=["GET"])
def api_public_access_status():
    store = load_visitor_access()
    token = (request.headers.get("X-Visitor-Token") or request.args.get("token") or "").strip()
    auth = access_authorized(store, token)
    slug = (request.args.get("slug") or "").strip()
    requires = project_requires_auth(slug) if slug else None
    return jsonify({
        "ok": True,
        "authorized": bool(auth.get("authorized")),
        "mode": auth.get("mode"),
        "expiresAt": auth.get("expiresAt"),
        "visitorId": auth.get("visitorId") or (request.args.get("visitorId") or "").strip()[:80] or None,
        "requireAuth": requires,
        "ttlSeconds": VISITOR_TOKEN_TTL_SECONDS,
    })


@app.route("/api/public/access/token", methods=["POST"])
def api_public_access_token():
    """Issue or renew a 1-hour visitor access token (name + email required)."""
    payload = request.get_json(force=True, silent=True) or {}
    if honeypot_tripped(payload):
        return jsonify({"ok": True, "ignored": True})
    name = re.sub(r"\s+", " ", str(payload.get("name") or "")).strip()[:80]
    email = str(payload.get("email") or "").strip()[:120].lower()
    visitor_id = str(payload.get("visitorId") or "").strip()[:80]
    slug = str(payload.get("slug") or "").strip()[:80]
    renew = bool(payload.get("renew"))
    if len(name) < 2:
        return jsonify({"ok": False, "error": "Name is required"}), 400
    if not EMAIL_RE.match(email):
        return jsonify({"ok": False, "error": "Valid email is required"}), 400
    if not visitor_id or not re.match(r"^[a-zA-Z0-9_-]{8,80}$", visitor_id):
        visitor_id = f"v_{secrets.token_urlsafe(12)}"[:32]

    store = load_visitor_access()
    purge_expired_visitor_tokens(store)
    visitors = store.setdefault("visitors", {})
    prev = visitors.get(visitor_id) if isinstance(visitors.get(visitor_id), dict) else {}
    visitors[visitor_id] = {
        "name": name,
        "email": email,
        "createdAt": prev.get("createdAt") or utc_now(),
        "lastSeenAt": utc_now(),
    }

    # Drop prior tokens for this visitor (single active token).
    tokens = store.setdefault("tokens", {})
    for existing, meta in list(tokens.items()):
        if isinstance(meta, dict) and meta.get("visitorId") == visitor_id:
            tokens.pop(existing, None)

    token = f"vat_{secrets.token_urlsafe(24)}"
    expires_at = (datetime.now(timezone.utc) + timedelta(seconds=VISITOR_TOKEN_TTL_SECONDS)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    tokens[token] = {
        "visitorId": visitor_id,
        "name": name,
        "email": email,
        "createdAt": utc_now(),
        "expiresAt": expires_at,
    }
    append_visitor_event(
        store,
        event_type="token_renewed" if renew else "token_issued",
        visitor_id=visitor_id,
        name=name,
        email=email,
        slug=slug,
        note="Visitor access token",
    )
    save_visitor_access(store)
    return jsonify({
        "ok": True,
        "token": token,
        "visitorId": visitor_id,
        "expiresAt": expires_at,
        "ttlSeconds": VISITOR_TOKEN_TTL_SECONDS,
        "name": name,
        "email": email,
    })


@app.route("/api/public/access/gate", methods=["POST"])
def api_public_access_gate():
    """Authorize Learn More / project view for a gated slug; log visitor tracking."""
    payload = request.get_json(force=True, silent=True) or {}
    slug = str(payload.get("slug") or "").strip()
    if not slug:
        return jsonify({"ok": False, "error": "slug required"}), 400
    try:
        slug = validate_slug(slug)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    requires = project_requires_auth(slug)
    store = load_visitor_access()
    token = (request.headers.get("X-Visitor-Token") or payload.get("token") or "").strip()
    auth = access_authorized(store, token)

    if requires and not auth.get("authorized"):
        return jsonify({
            "ok": False,
            "error": "Authentication required",
            "requireAuth": True,
            "authorized": False,
        }), 401

    if requires and auth.get("authorized"):
        append_visitor_event(
            store,
            event_type=str(payload.get("event") or "learn_more"),
            visitor_id=auth.get("visitorId") or (payload.get("visitorId") or "admin"),
            name=auth.get("username") or auth.get("name") or "",
            email=auth.get("email") or "",
            slug=slug,
            note=auth.get("mode") or "",
        )
        if auth.get("visitorId"):
            visitors = store.setdefault("visitors", {})
            prev = visitors.get(auth["visitorId"]) if isinstance(visitors.get(auth["visitorId"]), dict) else {}
            visitors[auth["visitorId"]] = {
                **prev,
                "name": auth.get("username") or prev.get("name") or "",
                "email": auth.get("email") or prev.get("email") or "",
                "lastSeenAt": utc_now(),
                "createdAt": prev.get("createdAt") or utc_now(),
            }
        save_visitor_access(store)

    return jsonify({
        "ok": True,
        "authorized": True,
        "requireAuth": requires,
        "mode": auth.get("mode") or ("open" if not requires else None),
        "expiresAt": auth.get("expiresAt"),
        "slug": slug,
    })


@app.route("/api/public/visit", methods=["POST"])
def api_public_visit():
    """Record a page visit (with or without visitor token) for metrics."""
    payload = request.get_json(force=True, silent=True) or {}
    if honeypot_tripped(payload):
        return jsonify({"ok": True, "ignored": True})
    store = load_visitor_access()
    visit = append_visit(store, payload)
    save_visitor_access(store)
    return jsonify({
        "ok": True,
        "id": visit.get("id"),
        "at": visit.get("at"),
        "visitorId": visit.get("visitorId"),
        "authMode": visit.get("authMode"),
    })


def _rwa_token() -> str:
    return (
        request.headers.get("X-RWA-Token")
        or request.cookies.get("rwa_session")
        or (request.get_json(force=True, silent=True) or {}).get("token")
        or request.args.get("token")
        or ""
    ).strip()


def _rwa_conn():
    return rwa_portal.open_rwa(SITE_ROOT)


@app.after_request
def _rwa_log_access(response):
    """Record RWA API usage for the master-admin observability dashboard."""
    try:
        path = request.path or ""
        method = request.method or "GET"
        if not rwa_portal.should_log_rwa_request(method, path):
            return response
        # Avoid logging binary/file noise and huge bodies; path + status is enough.
        conn = _rwa_conn()
        try:
            sess = rwa_portal.session_from_token(conn, _rwa_token())
            actor = sess["resident"] if sess else None
            # Anonymous OTP/login attempts still get logged (house unknown).
            rwa_portal.record_access_event(
                conn,
                actor=actor,
                event_type="api",
                method=method,
                path=path,
                status_code=response.status_code,
                ip=request.headers.get("X-Forwarded-For", request.remote_addr or "")[:80],
                user_agent=(request.headers.get("User-Agent") or "")[:240],
            )
        finally:
            conn.close()
    except Exception:
        # Never break the response because of logging.
        pass
    return response


@app.route("/api/rwa/observability", methods=["GET"])
def api_rwa_observability():
    """Master admin: who used the app and which functions."""
    conn = _rwa_conn()
    try:
        sess = rwa_portal.session_from_token(conn, _rwa_token())
        if not sess or not sess["resident"].get("superAdmin"):
            return jsonify({"ok": False, "error": "Super admin access required"}), 403
        days = request.args.get("days", 7)
        limit = request.args.get("limit", 200)
        house = (request.args.get("houseId") or "").strip() or None
        try:
            days_i = int(days)
        except (TypeError, ValueError):
            days_i = 7
        try:
            limit_i = int(limit)
        except (TypeError, ValueError):
            limit_i = 200
        data = rwa_portal.observability_dashboard(conn, days=days_i, limit=limit_i, house_id=house)
        return jsonify({"ok": True, **data})
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    finally:
        conn.close()


@app.route("/api/rwa/observability/event", methods=["POST"])
def api_rwa_observability_event():
    """Client panel / UI navigation breadcrumbs (signed-in users)."""
    conn = _rwa_conn()
    try:
        sess = rwa_portal.session_from_token(conn, _rwa_token())
        if not sess:
            return jsonify({"ok": False, "error": "Sign in required"}), 401
        payload = request.get_json(force=True, silent=True) or {}
        panel = str(payload.get("panel") or "").strip().lower()[:40]
        if not panel:
            return jsonify({"ok": False, "error": "panel required"}), 400
        detail = str(payload.get("detail") or "").strip()[:500] or None
        rwa_portal.record_access_event(
            conn,
            actor=sess["resident"],
            event_type="panel",
            method="UI",
            path=f"/panel/{panel}",
            action=rwa_portal.access_action_label("UI", "", panel=panel),
            status_code=200,
            panel=panel,
            detail=detail,
            ip=request.headers.get("X-Forwarded-For", request.remote_addr or "")[:80],
            user_agent=(request.headers.get("User-Agent") or "")[:240],
        )
        return jsonify({"ok": True})
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    finally:
        conn.close()


@app.route("/api/rwa/session", methods=["GET"])
def api_rwa_session():
    conn = _rwa_conn()
    try:
        sess = rwa_portal.session_from_token(conn, _rwa_token())
        if not sess:
            return jsonify({"ok": True, "authenticated": False})
        return jsonify({"ok": True, "authenticated": True, **sess})
    finally:
        conn.close()


@app.route("/api/rwa/otp/request", methods=["POST"])
def api_rwa_otp_request():
    payload = request.get_json(force=True, silent=True) or {}
    if honeypot_tripped(payload):
        return jsonify({"ok": True, "ignored": True})
    house_id = str(payload.get("houseId") or payload.get("plotNo") or "").strip()
    member_id = str(payload.get("memberId") or payload.get("member_id") or "").strip() or None
    if not house_id:
        return jsonify({"ok": False, "error": "House / plot number required"}), 400
    if house_id.upper().replace(" ", "") in {"ADMIN", "__SUPERADMIN__", "SUPERADMIN"}:
        return jsonify({"ok": False, "error": "Use Super admin password login"}), 400
    conn = _rwa_conn()
    try:
        rwa_portal.ensure_household_ready(conn)
        resident = rwa_portal.find_resident(conn, house_id)
        if not resident:
            return jsonify({"ok": False, "error": "Plot not found in colony register"}), 404
        if resident.get("house_id") == rwa_portal.SUPERADMIN_HOUSE_ID:
            return jsonify({"ok": False, "error": "Use Super admin password login"}), 400

        members = rwa_household.login_members_public(conn, resident["house_id"])
        if not members:
            return jsonify({"ok": False, "error": "No active household members for this plot"}), 400

        # Multiple people: ask which person is signing in (unless already chosen).
        if len(members) > 1 and not member_id:
            return jsonify({
                "ok": True,
                "needsMemberPick": True,
                "houseId": resident["house_id"],
                "householdName": resident.get("name") or "",
                "members": members,
                "message": "Who is signing in for this plot?",
            })

        if member_id:
            member = rwa_household.get_member(conn, member_id)
            if not member or member.get("house_id") != resident["house_id"]:
                return jsonify({"ok": False, "error": "Household member not found"}), 404
            if (member.get("status") or "active") != "active":
                return jsonify({"ok": False, "error": "This household member is inactive"}), 400
        else:
            member = rwa_household.get_member(conn, members[0]["id"])

        gaps = rwa_household.member_contact_gaps(member)
        provided_email = str(payload.get("email") or "").strip()
        provided_phone = str(payload.get("phone") or "").strip()
        contact_supplied = bool(provided_email or provided_phone)

        if gaps["needsContact"] and not contact_supplied:
            return jsonify({
                "ok": True,
                "needsContact": True,
                "houseId": resident["house_id"],
                "memberId": member["id"],
                "name": member.get("name") or "",
                "missingEmail": gaps["missingEmail"],
                "missingPhone": gaps["missingPhone"],
                "message": (
                    f"Contact details are missing for {member.get('name') or 'this person'}. "
                    "Enter them below — we email a one-time code, and only after you verify "
                    "that code will email/phone be saved."
                ),
            })

        pending_email = None
        pending_phone = None
        delivery_email = member.get("email")

        if gaps["needsContact"]:
            try:
                prepared = rwa_household.prepare_member_pending_contacts(
                    member,
                    email=provided_email or None,
                    phone=provided_phone or None,
                )
            except ValueError as exc:
                return jsonify({
                    "ok": False,
                    "error": str(exc),
                    "needsContact": True,
                    "missingEmail": gaps["missingEmail"],
                    "missingPhone": gaps["missingPhone"],
                    "houseId": resident["house_id"],
                    "memberId": member["id"],
                }), 400
            pending_email = prepared["pendingEmail"]
            pending_phone = prepared["pendingPhone"]
            delivery_email = prepared["deliveryEmail"]
        elif not (member.get("email") or "").strip():
            return jsonify({
                "ok": False,
                "error": "Email is required to receive a login code",
                "needsContact": True,
                "missingEmail": True,
                "missingPhone": gaps["missingPhone"],
                "houseId": resident["house_id"],
                "memberId": member["id"],
            }), 400

        result = rwa_portal.create_otp(
            conn,
            resident["house_id"],
            delivery_email,
            site_root=SITE_ROOT,
            member_id=member["id"],
            pending_email=pending_email,
            pending_phone=pending_phone,
        )
        result["houseId"] = resident["house_id"]
        result["memberId"] = member["id"]
        result["memberName"] = member.get("name") or ""
        result["contactPending"] = bool(pending_email or pending_phone)
        if result["contactPending"]:
            result["message"] = (
                "Code sent. Email/phone will be saved only after you enter the correct code."
            )
        return jsonify({"ok": True, **result})
    finally:
        conn.close()


@app.route("/api/rwa/login", methods=["POST"])
def api_rwa_password_login():
    """Super-admin / portal password login."""
    payload = request.get_json(force=True, silent=True) or {}
    if honeypot_tripped(payload):
        return jsonify({"ok": True, "ignored": True})

    username = str(payload.get("username") or payload.get("user") or "").strip()
    password = str(payload.get("password") or "")
    if not username or not password:
        return jsonify({"ok": False, "error": "Username and password required"}), 400
    conn = _rwa_conn()
    try:
        sess = rwa_portal.login_with_password(conn, username, password)
        if not sess:
            return jsonify({"ok": False, "error": "Invalid username or password"}), 401
        resp = jsonify({"ok": True, **sess})
        resp.set_cookie(
            "rwa_session",
            sess["token"],
            httponly=True,
            samesite="Lax",
            max_age=int(os.environ.get("RWA_SESSION_TTL", str(7 * 24 * 3600))),
        )
        return resp
    finally:
        conn.close()


@app.route("/api/rwa/otp/verify", methods=["POST"])
def api_rwa_otp_verify():
    payload = request.get_json(force=True, silent=True) or {}
    house_id = str(payload.get("houseId") or payload.get("plotNo") or "").strip()
    member_id = str(payload.get("memberId") or payload.get("member_id") or "").strip() or None
    code = str(payload.get("code") or payload.get("otp") or "").strip()
    if not house_id or not code:
        return jsonify({"ok": False, "error": "House / plot number and code required"}), 400
    conn = _rwa_conn()
    try:
        sess = rwa_portal.verify_otp(conn, house_id, code, member_id=member_id)
        if not sess:
            return jsonify({"ok": False, "error": "Invalid or expired code"}), 401
        resp = jsonify({"ok": True, **sess})
        resp.set_cookie(
            "rwa_session",
            sess["token"],
            httponly=True,
            samesite="Lax",
            max_age=int(os.environ.get("RWA_SESSION_TTL", str(7 * 24 * 3600))),
        )
        return resp
    finally:
        conn.close()


@app.route("/api/rwa/logout", methods=["POST"])
def api_rwa_logout():
    conn = _rwa_conn()
    try:
        rwa_portal.destroy_session(conn, _rwa_token())
        resp = jsonify({"ok": True})
        resp.set_cookie("rwa_session", "", expires=0)
        return resp
    finally:
        conn.close()


@app.route("/api/rwa/household/<path:house_id>/members", methods=["GET", "POST"])
def api_rwa_household_members(house_id: str):
    """List or add household members (owner / EC)."""
    conn = _rwa_conn()
    try:
        sess = rwa_portal.session_from_token(conn, _rwa_token())
        if not sess:
            return jsonify({"ok": False, "error": "Sign in required"}), 401
        actor = sess["resident"]
        resident = rwa_portal.find_resident(conn, house_id, include_inactive=True)
        if not resident:
            return jsonify({"ok": False, "error": "Plot not found"}), 404
        hid = resident["house_id"]
        same_house = actor.get("houseId") == hid
        if not same_house and not rwa_household.actor_can_use_ec_desk(actor) and not actor.get("superAdmin"):
            return jsonify({"ok": False, "error": "Not allowed"}), 403
        if request.method == "GET":
            include_inactive = rwa_household.can_actor_manage_household(actor, hid)
            members = [
                rwa_household.public_member(m, include_contacts=include_inactive or same_house)
                for m in rwa_household.list_members(conn, hid, include_inactive=include_inactive)
            ]
            return jsonify({
                "ok": True,
                "houseId": hid,
                "householdName": resident.get("name") or "",
                "canManage": rwa_household.can_actor_manage_household(actor, hid),
                "members": members,
            })
        payload = request.get_json(force=True, silent=True) or {}
        member = rwa_household.add_member(conn, hid, payload, actor=actor)
        return jsonify({"ok": True, "member": member})
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    finally:
        conn.close()


@app.route("/api/rwa/household/<path:house_id>/members/<member_id>", methods=["PATCH", "DELETE"])
def api_rwa_household_member_item(house_id: str, member_id: str):
    conn = _rwa_conn()
    try:
        sess = rwa_portal.session_from_token(conn, _rwa_token())
        if not sess:
            return jsonify({"ok": False, "error": "Sign in required"}), 401
        actor = sess["resident"]
        resident = rwa_portal.find_resident(conn, house_id, include_inactive=True)
        if not resident:
            return jsonify({"ok": False, "error": "Plot not found"}), 404
        hid = resident["house_id"]
        if request.method == "DELETE":
            rwa_household.delete_member(conn, hid, member_id, actor=actor)
            return jsonify({"ok": True, "deleted": member_id})
        payload = request.get_json(force=True, silent=True) or {}
        member = rwa_household.update_member(conn, hid, member_id, payload, actor=actor)
        return jsonify({"ok": True, "member": member})
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    finally:
        conn.close()


@app.route("/api/rwa/notices", methods=["GET"])
def api_rwa_notices():
    conn = _rwa_conn()
    try:
        sess = rwa_portal.session_from_token(conn, _rwa_token())
        status = (request.args.get("status") or "published").strip().lower()
        # Public board is always published. Drafts/all require EC.
        if status != "published":
            if not sess or not rwa_entitlements.actor_has(sess["resident"], "manage_notices"):
                return jsonify({"ok": False, "error": "Admin access required"}), 403
        viewer = sess["resident"] if sess else None
        return jsonify({"ok": True, "notices": rwa_portal.list_notices(conn, status=status, viewer=viewer)})
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    finally:
        conn.close()


@app.route("/api/rwa/ec-members", methods=["GET"])
def api_rwa_ec_members():
    """EC roster for draft sharing pickers."""
    conn = _rwa_conn()
    try:
        sess = rwa_portal.session_from_token(conn, _rwa_token())
        if not sess or not rwa_entitlements.actor_has(sess["resident"], "manage_notices"):
            return jsonify({"ok": False, "error": "Admin access required"}), 403
        me = sess["resident"].get("houseId")
        members = [m for m in rwa_portal.list_ec_members(conn) if m["houseId"] != me]
        return jsonify({"ok": True, "members": members})
    finally:
        conn.close()


@app.route("/api/rwa/notices", methods=["POST"])
def api_rwa_notices_write():
    conn = _rwa_conn()
    try:
        sess = rwa_portal.session_from_token(conn, _rwa_token())
        if not sess or not rwa_entitlements.actor_has(sess["resident"], "manage_notices"):
            return jsonify({"ok": False, "error": "Admin access required"}), 403
        payload = request.get_json(force=True, silent=True) or {}
        notice = rwa_portal.upsert_notice(
            conn,
            payload,
            sess["resident"].get("houseId"),
            actor=sess["resident"],
        )
        return jsonify({"ok": True, "notice": notice})
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    finally:
        conn.close()


@app.route("/api/rwa/notices/<notice_id>", methods=["PATCH", "DELETE"])
def api_rwa_notice_item(notice_id: str):
    """EC: update, pin/unpin, or delete a notice."""
    conn = _rwa_conn()
    try:
        sess = rwa_portal.session_from_token(conn, _rwa_token())
        if not sess or not rwa_entitlements.actor_has(sess["resident"], "manage_notices"):
            return jsonify({"ok": False, "error": "Admin access required"}), 403
        actor = sess["resident"]
        if request.method == "DELETE":
            rwa_portal.delete_notice(conn, notice_id, actor=actor)
            return jsonify({"ok": True, "deleted": notice_id})
        payload = request.get_json(force=True, silent=True) or {}
        move = (payload.get("move") or "").strip().lower()
        if move:
            notice = rwa_portal.move_pinned_notice(conn, notice_id, move)
            return jsonify({"ok": True, "notice": notice, "notices": rwa_portal.list_notices(conn, status="published", viewer=actor)})
        payload["id"] = notice_id
        notice = rwa_portal.upsert_notice(conn, payload, actor.get("houseId"), actor=actor)
        return jsonify({"ok": True, "notice": notice})
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    finally:
        conn.close()


@app.route("/api/rwa/notices/<notice_id>/shares", methods=["GET", "PUT"])
def api_rwa_notice_shares(notice_id: str):
    """Owner: list or replace who a draft is shared with (per-member view/edit)."""
    conn = _rwa_conn()
    try:
        sess = rwa_portal.session_from_token(conn, _rwa_token())
        if not sess or not rwa_entitlements.actor_has(sess["resident"], "manage_notices"):
            return jsonify({"ok": False, "error": "Admin access required"}), 403
        actor = sess["resident"]
        if request.method == "GET":
            notice = rwa_portal.get_notice(conn, notice_id, viewer=actor)
            if not notice:
                return jsonify({"ok": False, "error": "Notice not found"}), 404
            return jsonify({"ok": True, "notice": notice, "sharedWith": notice.get("sharedWith") or []})
        payload = request.get_json(force=True, silent=True) or {}
        shares = payload.get("shares")
        if shares is None:
            # Legacy: houseIds + optional global canEdit (defaults to edit).
            house_ids = payload.get("houseIds") or payload.get("sharedWith") or []
            default_edit = bool(payload.get("canEdit", True))
            if isinstance(house_ids, dict):
                house_ids = list(house_ids.keys())
            shares = []
            for item in house_ids:
                if isinstance(item, dict):
                    shares.append({
                        "houseId": item.get("houseId") or item.get("house_id"),
                        "canEdit": bool(item.get("canEdit", item.get("can_edit", default_edit))),
                    })
                else:
                    shares.append({"houseId": item, "canEdit": default_edit})
        notice = rwa_portal.set_notice_shares(conn, notice_id, shares, actor=actor)
        return jsonify({"ok": True, "notice": notice})
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    finally:
        conn.close()


@app.route("/api/rwa/notices/<notice_id>/like", methods=["POST"])
def api_rwa_notice_like(notice_id: str):
    """Toggle like on a published notice (any signed-in resident)."""
    conn = _rwa_conn()
    try:
        sess = rwa_portal.session_from_token(conn, _rwa_token())
        if not sess:
            return jsonify({"ok": False, "error": "Sign in required"}), 401
        result = rwa_portal.toggle_notice_like(conn, notice_id, sess["resident"])
        return jsonify({"ok": True, **result})
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    finally:
        conn.close()


@app.route("/api/rwa/notices/<notice_id>/comments", methods=["GET", "POST"])
def api_rwa_notice_comments(notice_id: str):
    """List or add comments on a published notice."""
    conn = _rwa_conn()
    try:
        sess = rwa_portal.session_from_token(conn, _rwa_token())
        if not sess:
            return jsonify({"ok": False, "error": "Sign in required"}), 401
        if request.method == "GET":
            comments = rwa_portal.list_notice_comments(conn, notice_id)
            notice = rwa_portal.get_notice(conn, notice_id, viewer=sess["resident"])
            return jsonify({
                "ok": True,
                "comments": comments,
                "likeCount": (notice or {}).get("likeCount", 0),
                "commentCount": (notice or {}).get("commentCount", 0),
                "likedByMe": (notice or {}).get("likedByMe", False),
            })
        payload = request.get_json(force=True, silent=True) or {}
        comment = rwa_portal.add_notice_comment(
            conn,
            notice_id,
            sess["resident"],
            payload.get("body") or payload.get("text") or "",
        )
        return jsonify({"ok": True, "comment": comment, **{
            "likeCount": comment.get("likeCount", 0),
            "commentCount": comment.get("commentCount", 0),
            "likedByMe": comment.get("likedByMe", False),
        }})
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    finally:
        conn.close()


@app.route("/api/rwa/notices/<notice_id>/comments/<comment_id>", methods=["DELETE"])
def api_rwa_notice_comment_delete(notice_id: str, comment_id: str):
    """Remove own comment (or any comment if EC/super admin)."""
    conn = _rwa_conn()
    try:
        sess = rwa_portal.session_from_token(conn, _rwa_token())
        if not sess:
            return jsonify({"ok": False, "error": "Sign in required"}), 401
        result = rwa_portal.delete_notice_comment(
            conn, notice_id, comment_id, sess["resident"]
        )
        return jsonify({"ok": True, **result})
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    finally:
        conn.close()


@app.route("/api/rwa/grievances/categories", methods=["GET"])
def api_rwa_grievance_categories():
    return jsonify({"ok": True, "categories": rwa_portal.grievance_categories()})


@app.route("/api/rwa/grievances", methods=["GET", "POST"])
def api_rwa_grievances():
    conn = _rwa_conn()
    try:
        sess = rwa_portal.session_from_token(conn, _rwa_token())
        if not sess:
            return jsonify({"ok": False, "error": "Sign in required"}), 401
        resident = sess["resident"]
        is_admin = rwa_entitlements.actor_has(resident, "manage_concerns")

        if request.method == "GET":
            # Shared colony mailbox: every signed-in resident sees all threads + replies.
            status = (request.args.get("status") or "").strip() or None
            category = (request.args.get("category") or "").strip() or None
            mine_only = request.args.get("scope") == "mine"
            items = rwa_portal.list_grievances(
                conn,
                house_id=resident["houseId"] if mine_only else None,
                status=status,
                category=category,
                limit=request.args.get("limit") or 150,
                include_contacts=is_admin,
            )
            return jsonify({
                "ok": True,
                "grievances": items,
                "stats": rwa_portal.grievance_stats(conn),
                "categories": rwa_portal.grievance_categories(),
                "scope": "mine" if mine_only else "mailbox",
            })

        payload = request.get_json(force=True, silent=True) or {}
        if rwa_household.actor_is_view_only(resident):
            return jsonify({"ok": False, "error": "View-only access cannot post concerns"}), 403
        created = rwa_portal.create_grievance(conn, resident["houseId"], payload)
        return jsonify({"ok": True, "grievance": created}), 201
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    finally:
        conn.close()


@app.route("/api/rwa/grievances/<grievance_id>/messages", methods=["POST"])
def api_rwa_grievance_message(grievance_id: str):
    """Any signed-in resident/EC can add a reply on the shared mailbox thread."""
    conn = _rwa_conn()
    try:
        sess = rwa_portal.session_from_token(conn, _rwa_token())
        if not sess:
            return jsonify({"ok": False, "error": "Sign in required"}), 401
        if rwa_household.actor_is_view_only(sess["resident"]):
            return jsonify({"ok": False, "error": "View-only access cannot reply to concerns"}), 403
        payload = request.get_json(force=True, silent=True) or {}
        updated = rwa_portal.add_grievance_message(conn, grievance_id, payload, sess["resident"])
        return jsonify({
            "ok": True,
            "grievance": updated,
            "stats": rwa_portal.grievance_stats(conn),
        })
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    finally:
        conn.close()


@app.route("/api/rwa/grievances/<grievance_id>", methods=["PATCH"])
def api_rwa_grievance_respond(grievance_id: str):
    """EC: respond and/or update status on a resident concern."""
    conn = _rwa_conn()
    try:
        sess = rwa_portal.session_from_token(conn, _rwa_token())
        if not sess or not rwa_entitlements.actor_has(sess["resident"], "manage_concerns"):
            return jsonify({"ok": False, "error": "Admin access required"}), 403
        payload = request.get_json(force=True, silent=True) or {}
        updated = rwa_portal.respond_grievance(conn, grievance_id, payload, sess["resident"])
        return jsonify({
            "ok": True,
            "grievance": updated,
            "stats": rwa_portal.grievance_stats(conn),
        })
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    finally:
        conn.close()


@app.route("/api/rwa/directory", methods=["GET"])
def api_rwa_directory():
    conn = _rwa_conn()
    try:
        sess = rwa_portal.session_from_token(conn, _rwa_token())
        if not sess:
            return jsonify({"ok": False, "error": "Sign in required"}), 401
        return jsonify({"ok": True, "residents": rwa_portal.directory(conn, include_contacts=False)})
    finally:
        conn.close()


@app.route("/api/rwa/residents", methods=["GET"])
def api_rwa_residents_roster():
    """EC roster with phone/email for contact management (admin only)."""
    conn = _rwa_conn()
    try:
        sess = rwa_portal.session_from_token(conn, _rwa_token())
        if not sess or not (
            rwa_entitlements.actor_has(sess["resident"], "manage_roster")
            or rwa_entitlements.actor_has(sess["resident"], "sensitive_ops")
        ):
            return jsonify({"ok": False, "error": "Admin access required"}), 403
        return jsonify({
            "ok": True,
            "stats": rwa_portal.roster_stats(conn),
            "residents": rwa_portal.directory(conn, include_contacts=True),
        })
    finally:
        conn.close()


@app.route("/api/rwa/residents/<path:house_id>", methods=["PATCH"])
def api_rwa_resident_patch(house_id: str):
    """EC: update resident name / phone / email / role / notes / status."""
    conn = _rwa_conn()
    try:
        sess = rwa_portal.session_from_token(conn, _rwa_token())
        if not sess or not (
            rwa_entitlements.actor_has(sess["resident"], "manage_roster")
            or rwa_entitlements.actor_has(sess["resident"], "sensitive_ops")
        ):
            return jsonify({"ok": False, "error": "Admin access required"}), 403
        payload = request.get_json(force=True, silent=True) or {}
        updated = rwa_portal.update_profile(
            conn,
            house_id,
            payload,
            as_admin=True,
            actor=sess["resident"],
            change_source="roster",
        )
        return jsonify({"ok": True, "resident": updated, "stats": rwa_portal.roster_stats(conn)})
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    finally:
        conn.close()


@app.route("/api/rwa/residents/revisions", methods=["GET"])
def api_rwa_resident_revisions():
    """EC-only revision history for resident contact/profile fields."""
    conn = _rwa_conn()
    try:
        sess = rwa_portal.session_from_token(conn, _rwa_token())
        if not sess or not (rwa_entitlements.is_ec_admin(sess["resident"]) or sess["resident"].get("superAdmin")):
            return jsonify({"ok": False, "error": "Admin access required"}), 403
        house_id = (request.args.get("houseId") or request.args.get("plot") or "").strip() or None
        limit = request.args.get("limit") or 100
        return jsonify({
            "ok": True,
            "revisions": rwa_portal.list_resident_revisions(conn, house_id=house_id, limit=limit),
        })
    finally:
        conn.close()


@app.route("/api/rwa/payments/me", methods=["GET"])
def api_rwa_payments_me():
    conn = _rwa_conn()
    try:
        sess = rwa_portal.session_from_token(conn, _rwa_token())
        if not sess:
            return jsonify({"ok": False, "error": "Sign in required"}), 401
        house_id = sess["resident"]["houseId"]
        if rwa_entitlements.actor_has(sess["resident"], "manage_dues") and request.args.get("houseId"):
            house_id = request.args.get("houseId")
        payment = rwa_portal.latest_payment_for(conn, house_id)
        summary = rwa_portal.payments_summary(conn)
        if not rwa_entitlements.actor_has(sess["resident"], "manage_dues"):
            summary = {"bank": summary.get("bank")}
        return jsonify({"ok": True, "payment": payment, "summary": summary})
    finally:
        conn.close()


@app.route("/api/rwa/payments", methods=["GET"])
def api_rwa_payments_all():
    conn = _rwa_conn()
    try:
        sess = rwa_portal.session_from_token(conn, _rwa_token())
        if not sess or not rwa_entitlements.actor_has(sess["resident"], "manage_dues"):
            return jsonify({"ok": False, "error": "Admin access required"}), 403
        rows = conn.execute(
            """
            SELECT pr.*, r.name, r.section, r.plot_no
            FROM payment_rows pr
            JOIN residents r ON r.house_id = pr.house_id
            WHERE pr.ledger_id = (SELECT id FROM payment_ledgers ORDER BY as_of DESC, id DESC LIMIT 1)
            ORDER BY r.section, r.plot_no
            """
        ).fetchall()
        return jsonify({
            "ok": True,
            "summary": rwa_portal.payments_summary(conn),
            "rows": [
                {
                    **rwa_portal.enrich_payment_row(r),
                    "plotNo": r["plot_no"],
                    "section": r["section"],
                    "name": r["name"],
                }
                for r in rows
            ],
        })
    finally:
        conn.close()


def _rwa_ec_session(conn, entitlement=None, *, ec_admin=False):
    """Return session if actor may use EC desk / entitlement; else (None, error_response)."""
    sess = rwa_portal.session_from_token(conn, _rwa_token())
    if not sess:
        return None, (jsonify({"ok": False, "error": "Sign in required"}), 401)
    actor = sess["resident"]
    if ec_admin:
        if not (rwa_entitlements.is_ec_admin(actor) or actor.get("superAdmin")):
            return None, (jsonify({"ok": False, "error": "EC Admin access required"}), 403)
        return sess, None
    if entitlement:
        if not rwa_entitlements.actor_has(actor, entitlement):
            return None, (jsonify({"ok": False, "error": "Permission denied"}), 403)
        return sess, None
    if not rwa_household.actor_can_use_ec_desk(actor):
        return None, (jsonify({"ok": False, "error": "EC access required"}), 403)
    return sess, None


def _rwa_actor_has(actor, key: str) -> bool:
    return rwa_entitlements.actor_has(actor, key)


@app.route("/api/rwa/reports/meta", methods=["GET"])
def api_rwa_reports_meta():
    """Field catalog and defaults for EC PDF reports."""
    conn = _rwa_conn()
    try:
        _sess, err = _rwa_ec_session(conn, "generate_reports")
        if err:
            return err
        meta = rwa_reports.reports_meta(conn)
        return jsonify({"ok": True, **meta})
    finally:
        conn.close()


@app.route("/api/rwa/entitlements/meta", methods=["GET"])
def api_rwa_entitlements_meta():
    conn = _rwa_conn()
    try:
        sess, err = _rwa_ec_session(conn)
        if err:
            return err
        return jsonify({"ok": True, **rwa_entitlements.entitlements_meta()})
    finally:
        conn.close()


@app.route("/api/rwa/translate", methods=["POST"])
def api_rwa_translate():
    """Translate text EN↔HI for bilingual overlays / authoring helpers."""
    conn = _rwa_conn()
    try:
        sess = rwa_portal.session_from_token(conn, _rwa_token())
        if not sess:
            return jsonify({"ok": False, "error": "Sign in required"}), 401
        payload = request.get_json(force=True, silent=True) or {}
        source = payload.get("source") or "en"
        target = payload.get("target") or "hi"
        if "text" in payload and "texts" not in payload:
            texts = [payload.get("text") or ""]
        else:
            texts = payload.get("texts") or []
        if not isinstance(texts, list):
            return jsonify({"ok": False, "error": "texts must be an array"}), 400
        if len(texts) > 40:
            return jsonify({"ok": False, "error": "Too many strings (max 40)"}), 400
        cleaned = []
        for t in texts:
            s = str(t or "")
            if len(s) > 8000:
                s = s[:8000]
            cleaned.append(s)
        results = rwa_translate.translate_batch(cleaned, source=source, target=target)
        return jsonify({
            "ok": True,
            "source": rwa_translate.normalize_lang(source),
            "target": rwa_translate.normalize_lang(target),
            "translations": [r.get("text") or "" for r in results],
            "results": results,
        })
    except Exception as exc:
        return jsonify({"ok": False, "error": f"Translation failed: {exc}"}), 502
    finally:
        conn.close()


@app.route("/api/rwa/roles", methods=["GET"])
def api_rwa_roles_list():
    """Office bearers + EC admins with entitlements (sensitive ops / EC Admin)."""
    conn = _rwa_conn()
    try:
        sess, err = _rwa_ec_session(conn, "sensitive_ops")
        if err:
            return err
        return jsonify({"ok": True, "members": rwa_entitlements.list_office_and_ec(conn)})
    finally:
        conn.close()


@app.route("/api/rwa/reports/pending-dues", methods=["POST"])
def api_rwa_report_pending_dues():
    """Generate Pending Dues PDF (customizable columns + filters)."""
    conn = _rwa_conn()
    try:
        _sess, err = _rwa_ec_session(conn, "generate_reports")
        if err:
            return err
        payload = request.get_json(force=True, silent=True) or {}
        fields = payload.get("fields")
        if fields is not None and not isinstance(fields, list):
            return jsonify({"ok": False, "error": "fields must be a list of field ids"}), 400
        filters = payload.get("filters") if isinstance(payload.get("filters"), dict) else {}
        for key in ("pendingOnly", "section", "search", "houseIds"):
            if key in payload and key not in filters:
                filters[key] = payload[key]
        try:
            pdf_bytes = rwa_reports.build_pending_dues_pdf(
                conn,
                site_root=SITE_ROOT,
                enrich_payment_row=rwa_portal.enrich_payment_row,
                fields=fields,
                filters=filters,
            )
        except ImportError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 500
        except Exception as exc:
            return jsonify({"ok": False, "error": f"Report failed: {exc}"}), 500

        stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
        filename = f"pending-dues-{stamp}.pdf"
        return send_file(
            io.BytesIO(pdf_bytes),
            mimetype="application/pdf",
            as_attachment=True,
            download_name=filename,
        )
    finally:
        conn.close()


@app.route("/api/rwa/reports/generate", methods=["POST"])
def api_rwa_reports_generate():
    """Generate a built-in or custom/saved-template PDF report."""
    conn = _rwa_conn()
    try:
        sess, err = _rwa_ec_session(conn, "generate_reports")
        if err:
            return err
        payload = request.get_json(force=True, silent=True) or {}
        try:
            pdf_bytes, filename = rwa_reports.generate_report_pdf(
                conn,
                site_root=SITE_ROOT,
                enrich_payment_row=rwa_portal.enrich_payment_row,
                payload=payload,
                list_grievances=rwa_portal.list_grievances,
                directory_fn=rwa_portal.directory,
            )
        except ValueError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        except ImportError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 500
        except Exception as exc:
            return jsonify({"ok": False, "error": f"Report failed: {exc}"}), 500
        return send_file(
            io.BytesIO(pdf_bytes),
            mimetype="application/pdf",
            as_attachment=True,
            download_name=filename,
        )
    finally:
        conn.close()


@app.route("/api/rwa/reports/templates", methods=["GET", "POST"])
def api_rwa_report_templates():
    """List or save custom report templates."""
    conn = _rwa_conn()
    try:
        sess, err = _rwa_ec_session(conn, "generate_reports")
        if err:
            return err
        if request.method == "GET":
            return jsonify({"ok": True, "templates": rwa_reports.list_report_templates(conn)})
        payload = request.get_json(force=True, silent=True) or {}
        tpl = rwa_reports.save_report_template(
            conn, payload, created_by=sess["resident"].get("houseId")
        )
        return jsonify({"ok": True, "template": tpl})
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    finally:
        conn.close()


@app.route("/api/rwa/reports/templates/<template_id>", methods=["DELETE", "PATCH"])
def api_rwa_report_template_item(template_id: str):
    conn = _rwa_conn()
    try:
        sess, err = _rwa_ec_session(conn, "generate_reports")
        if err:
            return err
        if request.method == "DELETE":
            rwa_reports.delete_report_template(conn, template_id)
            return jsonify({"ok": True})
        payload = request.get_json(force=True, silent=True) or {}
        tpl = rwa_reports.save_report_template(
            conn,
            {**payload, "id": template_id},
            created_by=sess["resident"].get("houseId"),
        )
        return jsonify({"ok": True, "template": tpl})
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    finally:
        conn.close()


@app.route("/api/rwa/payments/<path:house_id>", methods=["PATCH"])
def api_rwa_payment_patch(house_id: str):
    """EC: update / curate a household payment ledger row."""
    conn = _rwa_conn()
    try:
        sess = rwa_portal.session_from_token(conn, _rwa_token())
        if not sess or not rwa_entitlements.actor_has(sess["resident"], "manage_dues"):
            return jsonify({"ok": False, "error": "Admin access required"}), 403
        payload = request.get_json(force=True, silent=True) or {}
        updated = rwa_portal.update_payment_row(conn, house_id, payload)
        return jsonify({
            "ok": True,
            "payment": updated,
            "summary": rwa_portal.payments_summary(conn),
        })
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    finally:
        conn.close()


@app.route("/api/rwa/bank", methods=["GET", "PATCH"])
def api_rwa_bank():
    """Residents: read collection account. EC: update bank + UPI details."""
    conn = _rwa_conn()
    try:
        sess = rwa_portal.session_from_token(conn, _rwa_token())
        if not sess:
            return jsonify({"ok": False, "error": "Sign in required"}), 401
        if request.method == "GET":
            return jsonify({"ok": True, "bank": rwa_portal.get_primary_bank(conn)})
        if not rwa_entitlements.actor_has(sess["resident"], "manage_bank"):
            return jsonify({"ok": False, "error": "Admin access required"}), 403
        payload = request.get_json(force=True, silent=True) or {}
        bank = rwa_portal.update_primary_bank(conn, payload)
        return jsonify({"ok": True, "bank": bank})
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    finally:
        conn.close()


@app.route("/api/rwa/bank/qr", methods=["GET", "POST", "DELETE"])
def api_rwa_bank_qr():
    """Serve / upload / clear the UPI QR image for dues payments."""
    if request.method == "GET":
        conn = _rwa_conn()
        try:
            sess = rwa_portal.session_from_token(conn, _rwa_token())
            if not sess:
                return jsonify({"ok": False, "error": "Sign in required"}), 401
            bank = rwa_portal.get_primary_bank(conn)
            path = rwa_portal.bank_qr_path(SITE_ROOT, (bank or {}).get("qrFilename"))
            if not path:
                return jsonify({"ok": False, "error": "No UPI QR uploaded yet"}), 404
            return send_from_directory(path.parent, path.name, max_age=300)
        finally:
            conn.close()

    conn = _rwa_conn()
    try:
        sess = rwa_portal.session_from_token(conn, _rwa_token())
        if not sess or not rwa_entitlements.actor_has(sess["resident"], "manage_bank"):
            return jsonify({"ok": False, "error": "Admin access required"}), 403
        if request.method == "DELETE":
            bank = rwa_portal.clear_bank_qr(conn, SITE_ROOT)
            return jsonify({"ok": True, "bank": bank})
        upload = request.files.get("qr") or request.files.get("file") or request.files.get("image")
        bank = rwa_portal.save_bank_qr(conn, SITE_ROOT, file_storage=upload)
        return jsonify({"ok": True, "bank": bank})
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    finally:
        conn.close()


@app.route("/api/rwa/info-centre/categories", methods=["GET"])
def api_rwa_info_categories():
    return jsonify({"ok": True, "categories": rwa_portal.info_centre_categories()})


@app.route("/api/rwa/info-centre", methods=["GET", "POST"])
def api_rwa_info_centre():
    """List / create Information Centre documents."""
    conn = _rwa_conn()
    try:
        sess = rwa_portal.session_from_token(conn, _rwa_token())
        if not sess:
            return jsonify({"ok": False, "error": "Sign in required"}), 401
        is_admin = rwa_entitlements.actor_has(sess["resident"], "manage_info")

        if request.method == "GET":
            status = (request.args.get("status") or "published").strip().lower()
            if status != "published" and not is_admin:
                return jsonify({"ok": False, "error": "Admin access required"}), 403
            category = (request.args.get("category") or "").strip() or None
            docs = rwa_portal.list_info_documents(
                conn, status=status, category=category, as_admin=is_admin
            )
            return jsonify({
                "ok": True,
                "documents": docs,
                "categories": rwa_portal.info_centre_categories(),
            })

        if not is_admin:
            return jsonify({"ok": False, "error": "Admin access required"}), 403

        # Multipart (file upload) or JSON (HTML content)
        upload = request.files.get("file") or request.files.get("document")
        if upload is not None:
            payload = {
                "title": request.form.get("title"),
                "summary": request.form.get("summary"),
                "titleHi": request.form.get("titleHi"),
                "summaryHi": request.form.get("summaryHi"),
                "category": request.form.get("category"),
                "status": request.form.get("status") or "published",
                "audience": request.form.get("audience") or "all",
                "docType": request.form.get("docType") or "file",
                "id": request.form.get("id") or None,
            }
        else:
            payload = request.get_json(force=True, silent=True) or {}
            upload = None

        doc = rwa_portal.upsert_info_document(
            conn,
            SITE_ROOT,
            payload,
            publisher=sess["resident"].get("houseId"),
            file_storage=upload,
        )
        return jsonify({"ok": True, "document": doc})
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    finally:
        conn.close()


@app.route("/api/rwa/info-centre/<doc_id>", methods=["GET", "PATCH", "DELETE"])
def api_rwa_info_centre_item(doc_id: str):
    conn = _rwa_conn()
    try:
        sess = rwa_portal.session_from_token(conn, _rwa_token())
        if not sess:
            return jsonify({"ok": False, "error": "Sign in required"}), 401
        is_admin = rwa_entitlements.actor_has(sess["resident"], "manage_info")

        if request.method == "GET":
            doc = rwa_portal.get_info_document(conn, doc_id, as_admin=is_admin)
            if not doc:
                return jsonify({"ok": False, "error": "Document not found"}), 404
            return jsonify({"ok": True, "document": doc})

        if not is_admin:
            return jsonify({"ok": False, "error": "Admin access required"}), 403

        if request.method == "DELETE":
            rwa_portal.delete_info_document(conn, SITE_ROOT, doc_id)
            return jsonify({"ok": True, "deleted": doc_id})

        upload = request.files.get("file") or request.files.get("document")
        if upload is not None:
            payload = {
                "id": doc_id,
                "title": request.form.get("title"),
                "summary": request.form.get("summary"),
                "titleHi": request.form.get("titleHi"),
                "summaryHi": request.form.get("summaryHi"),
                "category": request.form.get("category"),
                "status": request.form.get("status"),
                "audience": request.form.get("audience"),
                "docType": request.form.get("docType"),
            }
            # Drop empty keys so upsert keeps existing values
            payload = {k: v for k, v in payload.items() if v is not None and str(v).strip() != ""}
            payload["id"] = doc_id
        else:
            payload = request.get_json(force=True, silent=True) or {}
            payload["id"] = doc_id
            upload = None

        doc = rwa_portal.upsert_info_document(
            conn,
            SITE_ROOT,
            payload,
            publisher=sess["resident"].get("houseId"),
            file_storage=upload,
        )
        return jsonify({"ok": True, "document": doc})
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    finally:
        conn.close()


@app.route("/api/rwa/info-centre/<doc_id>/file", methods=["GET"])
def api_rwa_info_centre_file(doc_id: str):
    """Download or open a published (or EC-visible) document file."""
    conn = _rwa_conn()
    try:
        sess = rwa_portal.session_from_token(conn, _rwa_token())
        if not sess:
            return jsonify({"ok": False, "error": "Sign in required"}), 401
        is_admin = rwa_entitlements.actor_has(sess["resident"], "manage_info")
        doc = rwa_portal.get_info_document(conn, doc_id, as_admin=is_admin)
        if not doc or not doc.get("filename"):
            return jsonify({"ok": False, "error": "Document not found"}), 404
        path = rwa_portal.info_doc_file_path(SITE_ROOT, doc_id, doc.get("filename"))
        lang = (request.args.get("lang") or "en").strip().lower()
        if lang == "hi" and doc.get("docType") == "html" and doc.get("hasHtmlHi"):
            hi_path = rwa_portal.info_doc_file_path(SITE_ROOT, doc_id, "content_hi.html")
            if hi_path:
                path = hi_path
        if not path:
            return jsonify({"ok": False, "error": "File missing on server"}), 404
        download_name = doc.get("originalName") or path.name
        if lang == "hi" and path.name == "content_hi.html":
            download_name = f"{pathlib.Path(download_name).stem}-hi.html"
        as_attachment = not rwa_portal.info_doc_should_inline(doc.get("mimeType"), doc.get("filename"))
        return send_file(
            path,
            mimetype=doc.get("mimeType") or None,
            as_attachment=as_attachment,
            download_name=download_name,
            max_age=120,
        )
    finally:
        conn.close()


@app.route("/api/rwa/works/meta", methods=["GET"])
def api_rwa_works_meta():
    return jsonify({"ok": True, **rwa_portal.works_meta()})


@app.route("/api/rwa/works", methods=["GET", "POST"])
def api_rwa_works():
    """List / create Works & Events items."""
    conn = _rwa_conn()
    try:
        sess = rwa_portal.session_from_token(conn, _rwa_token())
        if not sess:
            return jsonify({"ok": False, "error": "Sign in required"}), 401
        is_admin = rwa_entitlements.actor_has(sess["resident"], "manage_works")

        if request.method == "GET":
            kind = (request.args.get("kind") or "").strip() or None
            status = (request.args.get("status") or "").strip() or None
            visibility = (request.args.get("visibility") or "").strip() or None
            if visibility == "draft" and not is_admin:
                return jsonify({"ok": False, "error": "Admin access required"}), 403
            works = rwa_portal.list_colony_works(
                conn,
                kind=kind,
                status=status,
                visibility=visibility,
                as_admin=is_admin,
            )
            return jsonify({"ok": True, "works": works, **rwa_portal.works_meta()})

        if not is_admin:
            return jsonify({"ok": False, "error": "Admin access required"}), 403
        payload = request.get_json(force=True, silent=True) or {}
        work = rwa_portal.upsert_colony_work(conn, payload, actor=sess["resident"])
        return jsonify({"ok": True, "work": work})
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    finally:
        conn.close()


@app.route("/api/rwa/works/<work_id>", methods=["GET", "PATCH", "DELETE"])
def api_rwa_works_item(work_id: str):
    conn = _rwa_conn()
    try:
        sess = rwa_portal.session_from_token(conn, _rwa_token())
        if not sess:
            return jsonify({"ok": False, "error": "Sign in required"}), 401
        is_admin = rwa_entitlements.actor_has(sess["resident"], "manage_works")

        if request.method == "GET":
            work = rwa_portal.get_colony_work(conn, work_id, as_admin=is_admin)
            if not work:
                return jsonify({"ok": False, "error": "Not found"}), 404
            return jsonify({"ok": True, "work": work})

        if not is_admin:
            return jsonify({"ok": False, "error": "Admin access required"}), 403

        if request.method == "DELETE":
            rwa_portal.delete_colony_work(conn, work_id)
            return jsonify({"ok": True, "deleted": work_id})

        payload = request.get_json(force=True, silent=True) or {}
        payload["id"] = work_id
        work = rwa_portal.upsert_colony_work(conn, payload, actor=sess["resident"])
        return jsonify({"ok": True, "work": work})
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    finally:
        conn.close()


@app.route("/api/rwa/profile", methods=["GET", "PATCH"])
def api_rwa_profile():
    conn = _rwa_conn()
    try:
        sess = rwa_portal.session_from_token(conn, _rwa_token())
        if not sess:
            return jsonify({"ok": False, "error": "Sign in required"}), 401
        if request.method == "GET":
            return jsonify({"ok": True, "resident": sess["resident"]})
        payload = request.get_json(force=True, silent=True) or {}
        actor = sess["resident"]
        target = actor["houseId"]
        as_admin = rwa_entitlements.actor_has(actor, "manage_roster") or rwa_entitlements.actor_has(actor, "sensitive_ops")
        if as_admin and payload.get("houseId"):
            target = str(payload["houseId"]).strip()
        admin_mode = bool(as_admin and (target != actor["houseId"] or payload.get("role")))
        member_id = actor.get("memberId")

        # Self profile: update the logged-in household member for personal fields.
        if member_id and target == actor["houseId"] and not admin_mode:
            member_payload = {}
            for key in ("name", "title", "email", "phone"):
                if key in payload:
                    member_payload[key] = payload.get(key)
            if member_payload:
                if rwa_household.actor_is_view_only(actor):
                    # View-only may only refresh own contact channels for OTP.
                    member_payload = {k: v for k, v in member_payload.items() if k in {"email", "phone"}}
                if member_payload:
                    rwa_household.update_member(
                        conn, target, member_id, member_payload, actor=actor
                    )
            # Plot-level fields only for primary / managing owners.
            plot_payload = {}
            if actor.get("isPrimary") or actor.get("canManageHousehold"):
                for key in ("profession", "employmentStatus", "officialTitle"):
                    if key in payload:
                        plot_payload[key] = payload.get(key)
            if plot_payload:
                rwa_portal.update_profile(
                    conn,
                    target,
                    plot_payload,
                    as_admin=False,
                    actor=actor,
                    change_source="profile",
                )
            refreshed = rwa_portal.session_from_token(conn, sess["token"])
            return jsonify({"ok": True, "resident": (refreshed or sess)["resident"]})

        updated = rwa_portal.update_profile(
            conn,
            target,
            payload,
            as_admin=admin_mode,
            actor=actor,
            change_source="roster" if admin_mode and target != actor["houseId"] else "profile",
        )
        return jsonify({"ok": True, "resident": updated})
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    finally:
        conn.close()


@app.route("/api/rwa/profile/photo", methods=["POST", "DELETE"])
def api_rwa_profile_photo_self():
    """Upload or clear the signed-in member's profile photo."""
    conn = _rwa_conn()
    try:
        sess = rwa_portal.session_from_token(conn, _rwa_token())
        if not sess:
            return jsonify({"ok": False, "error": "Sign in required"}), 401
        actor = sess["resident"]
        member_id = actor.get("memberId")
        if not member_id or actor.get("superAdmin"):
            return jsonify({"ok": False, "error": "Profile photo is for household logins"}), 400
        if request.method == "DELETE":
            member = rwa_portal.clear_member_photo(conn, SITE_ROOT, member_id, actor=actor)
            refreshed = rwa_portal.session_from_token(conn, sess["token"])
            return jsonify({"ok": True, "member": member, "resident": (refreshed or sess)["resident"]})
        upload = request.files.get("photo") or request.files.get("file") or request.files.get("image")
        member = rwa_portal.save_member_photo(
            conn, SITE_ROOT, member_id, file_storage=upload, actor=actor
        )
        refreshed = rwa_portal.session_from_token(conn, sess["token"])
        return jsonify({"ok": True, "member": member, "resident": (refreshed or sess)["resident"]})
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    finally:
        conn.close()


@app.route("/api/rwa/profile/photo/<member_id>", methods=["GET"])
def api_rwa_profile_photo_get(member_id: str):
    """Serve a household member profile photo (any signed-in resident)."""
    conn = _rwa_conn()
    try:
        sess = rwa_portal.session_from_token(conn, _rwa_token())
        if not sess:
            return jsonify({"ok": False, "error": "Sign in required"}), 401
        member = rwa_household.get_member(conn, member_id)
        if not member:
            return jsonify({"ok": False, "error": "Not found"}), 404
        path = rwa_portal.profile_photo_path(SITE_ROOT, member.get("photo_filename"))
        if not path:
            return jsonify({"ok": False, "error": "No photo"}), 404
        return send_file(
            path,
            mimetype="image/webp",
            as_attachment=False,
            download_name=path.name,
            max_age=86400,
        )
    finally:
        conn.close()


@app.route("/api/rwa/residents/<path:house_id>/promote", methods=["POST"])
def api_rwa_promote(house_id: str):
    """Assign / remove / suspend EC admin role (super admin only)."""
    conn = _rwa_conn()
    try:
        sess = rwa_portal.session_from_token(conn, _rwa_token())
        if not sess or not sess["resident"].get("superAdmin"):
            return jsonify({"ok": False, "error": "Super admin access required"}), 403
        payload = request.get_json(force=True, silent=True) or {}
        action = str(payload.get("action") or "").strip().lower()
        role = payload.get("role")
        status = payload.get("status")
        if action == "assign":
            role = "admin"
            status = status or "active"
        elif action in {"remove", "demote"}:
            role = "resident"
        elif action == "suspend":
            role = role or "admin"
            status = "inactive"
        elif action == "reinstate":
            role = "admin"
            status = "active"
        body = {}
        if role in {"admin", "resident"}:
            body["role"] = role
        if status in {"active", "inactive"}:
            body["status"] = status
        if payload.get("officialTitle") is not None:
            body["officialTitle"] = payload.get("officialTitle")
        if not body:
            return jsonify({"ok": False, "error": "role, status, or action required"}), 400
        updated = rwa_portal.update_profile(
            conn,
            house_id,
            body,
            as_admin=True,
            actor=sess["resident"],
            change_source="ec_role",
        )
        return jsonify({"ok": True, "resident": updated})
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    finally:
        conn.close()


@app.route("/api/rwa/smtp/status", methods=["GET"])
def api_rwa_smtp_status():
    sess_ok = False
    conn = _rwa_conn()
    try:
        sess = rwa_portal.session_from_token(conn, _rwa_token())
        sess_ok = bool(sess and rwa_household.actor_can_use_ec_desk(sess["resident"]))
    finally:
        conn.close()
    # Public: only whether configured. Details for admin.
    status = rwa_portal.smtp_status(SITE_ROOT)
    if not sess_ok:
        return jsonify({"ok": True, "configured": status["configured"], "provider": status["provider"]})
    return jsonify({"ok": True, **status, "passwordSet": bool(status.get("passwordSet"))})


@app.route("/api/rwa/settings", methods=["GET", "PUT", "PATCH"])
def api_rwa_settings():
    """Super-admin platform settings (SMTP, OTP TTL, superadmin password)."""
    conn = _rwa_conn()
    try:
        sess = rwa_portal.session_from_token(conn, _rwa_token())
        if not sess or not sess["resident"].get("superAdmin"):
            return jsonify({"ok": False, "error": "Super admin access required"}), 403
        if request.method == "GET":
            return jsonify({"ok": True, "settings": rwa_portal.read_platform_settings(SITE_ROOT)})
        payload = request.get_json(force=True, silent=True) or {}
        settings = rwa_portal.save_platform_settings(SITE_ROOT, payload, conn=conn)
        return jsonify({"ok": True, "settings": settings})
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except OSError as exc:
        return jsonify({"ok": False, "error": f"Could not write settings: {exc}"}), 500
    finally:
        conn.close()


@app.route("/api/rwa/ops/status", methods=["GET"])
def api_rwa_ops_status():
    """Super-admin: live server vitals + last backup/vitals cron results."""
    conn = _rwa_conn()
    try:
        sess = rwa_portal.session_from_token(conn, _rwa_token())
        if not sess or not sess["resident"].get("superAdmin"):
            return jsonify({"ok": False, "error": "Super admin access required"}), 403
        site_id = os.environ.get("VEERCANVAS_SITE_ID") or ""
        return jsonify({"ok": True, **rwa_portal.read_ops_status(SITE_ROOT, site_id=site_id or None)})
    finally:
        conn.close()


@app.route("/api/rwa/ops/test-alert", methods=["POST"])
def api_rwa_ops_test_alert():
    """Super-admin: send a test ops alert email."""
    conn = _rwa_conn()
    try:
        sess = rwa_portal.session_from_token(conn, _rwa_token())
        if not sess or not sess["resident"].get("superAdmin"):
            return jsonify({"ok": False, "error": "Super admin access required"}), 403
        result = rwa_portal.send_ops_alert(
            SITE_ROOT,
            "[VeerCanvas] Test ops alert",
            "This is a test alert from the master admin console.\n\nIf you received this, backup/vitals notifications are wired correctly.",
        )
        return jsonify({"ok": True, **result})
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except smtplib.SMTPException as exc:
        return jsonify({"ok": False, "error": f"SMTP failed: {exc}"}), 502
    finally:
        conn.close()


@app.route("/api/rwa/ledger/import", methods=["POST"])
def api_rwa_ledger_import():
    """EC: upload HIMUDA-style ledger PDF into SQLite."""
    conn = _rwa_conn()
    try:
        sess = rwa_portal.session_from_token(conn, _rwa_token())
        if not sess or not (rwa_entitlements.is_ec_admin(sess["resident"]) or sess["resident"].get("superAdmin")):
            return jsonify({"ok": False, "error": "Admin access required"}), 403
    finally:
        conn.close()

    upload = request.files.get("file") or request.files.get("pdf")
    if not upload:
        return jsonify({"ok": False, "error": "PDF file required"}), 400
    imports_dir = SITE_ROOT / "data" / "imports"
    imports_dir.mkdir(parents=True, exist_ok=True)
    dest = imports_dir / "HIMUDA-HOUSING-COLONY-SANYARD-LIST.pdf"
    upload.save(dest)

    script = SITE_ROOT / "scripts" / "import_ledger_pdf.py"
    if not script.is_file():
        script = VEERCANVAS_ROOT / "sites" / "hbcsanyard" / "scripts" / "import_ledger_pdf.py"
    completed = subprocess.run(
        [sys.executable, str(script), str(dest), "--db", str(SITE_ROOT / "data" / "rwa.db")],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        return jsonify({
            "ok": False,
            "error": "Import failed",
            "stderr": (completed.stderr or "")[-2000:],
            "stdout": (completed.stdout or "")[-2000:],
        }), 500
    try:
        payload = json.loads(completed.stdout.strip().splitlines()[-1])
    except json.JSONDecodeError:
        payload = {"stdout": completed.stdout}
    return jsonify({"ok": True, **payload})


@app.route("/api/inbox", methods=["GET"])
@require_login
def api_inbox():
    """Site-local inbox (current SITE_ROOT). Platform uses /api/observability for all sites."""
    inbox = load_contact_inbox()
    store = load_engagement()
    comments = []
    for slug, entry in (store.get("projects") or {}).items():
        if not isinstance(entry, dict):
            continue
        for comment in entry.get("comments") or []:
            if not isinstance(comment, dict):
                continue
            comments.append({
                "siteId": SITE_ID,
                "slug": slug,
                "id": comment.get("id"),
                "name": comment.get("name"),
                "text": comment.get("text"),
                "createdAt": comment.get("createdAt"),
                "hidden": bool(comment.get("hidden")),
            })
    comments.sort(key=lambda c: c.get("createdAt") or "", reverse=True)
    messages = []
    for item in inbox.get("messages") or []:
        if isinstance(item, dict):
            messages.append({**item, "siteId": SITE_ID})
    return jsonify({
        "ok": True,
        "siteId": SITE_ID,
        "messages": messages,
        "comments": comments[:200],
    })


def _read_json_file(path: pathlib.Path, fallback):
    if not path.is_file():
        return fallback
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return fallback
    return data if isinstance(data, type(fallback)) else fallback


def site_data_roots(site_id: str, cfg: dict | None = None) -> list[pathlib.Path]:
    """Candidate directories that may hold live engagement/contact JSON for a site."""
    cfg = cfg or {}
    roots: list[pathlib.Path] = []
    web_root = str(cfg.get("webRoot") or "").strip()
    if web_root:
        roots.append(pathlib.Path(web_root))
    domain = str(cfg.get("domain") or "").strip()
    if domain:
        roots.append(pathlib.Path(f"/var/www/{domain}"))
    roots.append(sites_root() / site_id)
    # Deduplicate while preserving order.
    seen = set()
    unique = []
    for root in roots:
        key = str(root.resolve()) if root.exists() else str(root)
        if key in seen:
            continue
        seen.add(key)
        unique.append(root)
    return unique


def resolve_site_data_root(site_id: str, cfg: dict | None = None) -> pathlib.Path | None:
    for root in site_data_roots(site_id, cfg):
        if (
            (root / "engagement.json").is_file()
            or (root / "contact-messages.json").is_file()
            or (root / "visitor-access.json").is_file()
            or (root / "projects.json").is_file()
        ):
            return root
    for root in site_data_roots(site_id, cfg):
        if root.is_dir():
            return root
    return None


def load_json_for_site(site_id: str, filename: str, fallback):
    cfg = {}
    cfg_path = sites_root() / site_id / "site.config.json"
    if cfg_path.is_file():
        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            cfg = {}
    for root in site_data_roots(site_id, cfg):
        path = root / filename
        if not path.is_file():
            continue
        return _read_json_file(path, fallback), root
    return fallback, resolve_site_data_root(site_id, cfg)


def _top_counts(counter: dict, limit: int = 15) -> list:
    items = sorted(counter.items(), key=lambda kv: kv[1], reverse=True)[:limit]
    return [{"key": k, "count": c} for k, c in items]


def collect_platform_observability() -> dict:
    sites_out = []
    all_messages = []
    all_comments = []
    all_visitors = []
    all_visitor_events = []
    all_visits = []
    top_projects = []
    path_counts: dict[str, int] = {}
    referrer_counts: dict[str, int] = {}
    browser_counts: dict[str, int] = {}
    device_counts: dict[str, int] = {}
    unique_ips: set[str] = set()
    unique_visit_visitors: set[str] = set()
    totals = {
        "sites": 0,
        "likes": 0,
        "dislikes": 0,
        "comments": 0,
        "hiddenComments": 0,
        "messages": 0,
        "unreadMessages": 0,
        "visitors": 0,
        "activeTokens": 0,
        "visitorEvents": 0,
        "visits": 0,
        "uniqueIps": 0,
        "uniqueVisitVisitors": 0,
        "authedVisits": 0,
        "anonymousVisits": 0,
        "adminVisits": 0,
    }

    for site in list_local_sites(include_deleted=True):
        if site.get("status") == "deleted":
            continue
        site_id = site["id"]
        engagement, eng_root = load_json_for_site(site_id, "engagement.json", {"projects": {}})
        inbox, inbox_root = load_json_for_site(site_id, "contact-messages.json", {"messages": []})
        access, access_root = load_json_for_site(
            site_id,
            "visitor-access.json",
            {"visitors": {}, "tokens": {}, "events": [], "visits": []},
        )
        projects = engagement.get("projects") if isinstance(engagement, dict) else {}
        if not isinstance(projects, dict):
            projects = {}
        messages = inbox.get("messages") if isinstance(inbox, dict) else []
        if not isinstance(messages, list):
            messages = []

        site_likes = site_dislikes = site_comments = site_hidden = 0
        for slug, entry in projects.items():
            if not isinstance(entry, dict):
                continue
            likes = int(entry.get("likes") or 0)
            dislikes = int(entry.get("dislikes") or 0)
            comments = entry.get("comments") if isinstance(entry.get("comments"), list) else []
            visible = [c for c in comments if isinstance(c, dict) and not c.get("hidden")]
            hidden = [c for c in comments if isinstance(c, dict) and c.get("hidden")]
            site_likes += likes
            site_dislikes += dislikes
            site_comments += len(visible)
            site_hidden += len(hidden)
            top_projects.append({
                "siteId": site_id,
                "domain": site.get("domain") or "",
                "slug": slug,
                "likes": likes,
                "dislikes": dislikes,
                "commentCount": len(visible),
                "score": likes - dislikes + len(visible),
            })
            for comment in comments:
                if not isinstance(comment, dict):
                    continue
                all_comments.append({
                    "siteId": site_id,
                    "domain": site.get("domain") or "",
                    "slug": slug,
                    "id": comment.get("id"),
                    "name": comment.get("name"),
                    "text": comment.get("text"),
                    "createdAt": comment.get("createdAt"),
                    "hidden": bool(comment.get("hidden")),
                })

        unread = 0
        for item in messages:
            if not isinstance(item, dict):
                continue
            if not item.get("read"):
                unread += 1
            all_messages.append({
                **item,
                "siteId": site_id,
                "domain": site.get("domain") or "",
            })

        visitors_map = access.get("visitors") if isinstance(access.get("visitors"), dict) else {}
        tokens_map = access.get("tokens") if isinstance(access.get("tokens"), dict) else {}
        events = [e for e in (access.get("events") or []) if isinstance(e, dict)]
        visits = [v for v in (access.get("visits") or []) if isinstance(v, dict)]
        now = datetime.now(timezone.utc)
        active_tokens = 0
        for meta in tokens_map.values():
            if not isinstance(meta, dict):
                continue
            try:
                exp = datetime.fromisoformat(str(meta.get("expiresAt") or "").replace("Z", "+00:00"))
            except ValueError:
                continue
            if exp > now:
                active_tokens += 1
        for vid, meta in visitors_map.items():
            if not isinstance(meta, dict):
                continue
            all_visitors.append({
                "siteId": site_id,
                "visitorId": vid,
                "name": meta.get("name") or "",
                "email": meta.get("email") or "",
                "createdAt": meta.get("createdAt") or "",
                "lastSeenAt": meta.get("lastSeenAt") or "",
                "lastIp": meta.get("lastIp") or "",
                "lastPath": meta.get("lastPath") or "",
                "visitCount": int(meta.get("visitCount") or 0),
            })
        for event in events:
            all_visitor_events.append({**event, "siteId": site_id, "domain": site.get("domain") or ""})

        site_unique_ips: set[str] = set()
        site_authed = site_anon = site_admin = 0
        for visit in visits:
            enriched = {**visit, "siteId": site_id, "domain": site.get("domain") or ""}
            all_visits.append(enriched)
            ip = str(visit.get("ip") or "").strip()
            if ip:
                unique_ips.add(ip)
                site_unique_ips.add(ip)
            vid = str(visit.get("visitorId") or "").strip()
            if vid:
                unique_visit_visitors.add(f"{site_id}:{vid}")
            mode = str(visit.get("authMode") or "anonymous")
            if mode == "admin":
                site_admin += 1
                totals["adminVisits"] += 1
            elif mode == "visitor" or visit.get("hasToken"):
                site_authed += 1
                totals["authedVisits"] += 1
            else:
                site_anon += 1
                totals["anonymousVisits"] += 1
            path_key = str(visit.get("path") or "/")[:120]
            path_counts[path_key] = path_counts.get(path_key, 0) + 1
            ref_key = str(visit.get("referrerHost") or "(direct)")[:120]
            referrer_counts[ref_key] = referrer_counts.get(ref_key, 0) + 1
            browser_counts[str(visit.get("browser") or "Other")] = browser_counts.get(str(visit.get("browser") or "Other"), 0) + 1
            device_counts[str(visit.get("device") or "other")] = device_counts.get(str(visit.get("device") or "other"), 0) + 1

        totals["sites"] += 1
        totals["likes"] += site_likes
        totals["dislikes"] += site_dislikes
        totals["comments"] += site_comments
        totals["hiddenComments"] += site_hidden
        totals["messages"] += len(messages)
        totals["unreadMessages"] += unread
        totals["visitors"] += len(visitors_map)
        totals["activeTokens"] += active_tokens
        totals["visitorEvents"] += len(events)
        totals["visits"] += len(visits)

        sites_out.append({
            "id": site_id,
            "name": site.get("name") or site_id,
            "domain": site.get("domain") or "",
            "platform": bool(site.get("platform")),
            "ops": bool(site.get("ops")),
            "likes": site_likes,
            "dislikes": site_dislikes,
            "comments": site_comments,
            "messages": len([m for m in messages if isinstance(m, dict)]),
            "unreadMessages": unread,
            "visitors": len(visitors_map),
            "activeTokens": active_tokens,
            "visits": len(visits),
            "uniqueIps": len(site_unique_ips),
            "authedVisits": site_authed,
            "anonymousVisits": site_anon,
            "adminVisits": site_admin,
            "dataRoot": str(eng_root or inbox_root or access_root or ""),
        })

    totals["uniqueIps"] = len(unique_ips)
    totals["uniqueVisitVisitors"] = len(unique_visit_visitors)

    all_messages.sort(key=lambda m: m.get("createdAt") or "", reverse=True)
    all_comments.sort(key=lambda c: c.get("createdAt") or "", reverse=True)
    all_visitor_events.sort(key=lambda e: e.get("at") or "", reverse=True)
    all_visitors.sort(key=lambda v: v.get("lastSeenAt") or v.get("createdAt") or "", reverse=True)
    all_visits.sort(key=lambda v: v.get("at") or "", reverse=True)
    top_projects.sort(key=lambda p: (p.get("score") or 0, p.get("likes") or 0), reverse=True)

    return {
        "ok": True,
        "totals": totals,
        "sites": sites_out,
        "messages": all_messages[:200],
        "comments": all_comments[:200],
        "visitors": all_visitors[:200],
        "visitorEvents": all_visitor_events[:300],
        "visits": all_visits[:500],
        "topPaths": _top_counts(path_counts, 15),
        "topReferrers": _top_counts(referrer_counts, 15),
        "browsers": _top_counts(browser_counts, 10),
        "devices": _top_counts(device_counts, 10),
        "topProjects": top_projects[:25],
        "generatedAt": utc_now(),
    }


@app.route("/api/platform/session", methods=["GET"])
@require_platform
def api_platform_session():
    """Auth check for the canvas site-root platform console (create/deploy sites)."""
    if not session.get("logged_in"):
        return jsonify({"ok": False, "authenticated": False}), 401
    return jsonify({
        "ok": True,
        "authenticated": True,
        "username": session.get("username") or "",
        "siteId": SITE_ID,
        "githubOwner": DEFAULT_OWNER,
    })


@app.route("/api/ops/session", methods=["GET"])
@require_ops
def api_ops_session():
    """Lightweight auth check for the ops site-root dashboard shell."""
    if not session.get("logged_in"):
        return jsonify({"ok": False, "authenticated": False}), 401
    return jsonify({
        "ok": True,
        "authenticated": True,
        "username": session.get("username") or "",
        "siteId": SITE_ID,
    })


@app.route("/api/observability", methods=["GET"])
@require_login
@require_ops
def api_observability():
    return jsonify(collect_platform_observability())


@app.route("/api/inbox/contact/<msg_id>/read", methods=["POST"])
@require_login
def api_inbox_mark_read(msg_id: str):
    payload = request.get_json(force=True, silent=True) or {}
    site_id = str(payload.get("siteId") or SITE_ID).strip() or SITE_ID
    if site_id != SITE_ID and not IS_OPS:
        return jsonify({"ok": False, "error": "Cross-site moderation requires Ops console"}), 403

    if site_id == SITE_ID:
        inbox = load_contact_inbox()
        save = save_contact_inbox
    else:
        data, root = load_json_for_site(site_id, "contact-messages.json", {"messages": []})
        if root is None:
            return jsonify({"ok": False, "error": f"site data root not found: {site_id}"}), 404
        inbox = data if isinstance(data, dict) else {"messages": []}
        inbox.setdefault("messages", [])

        def save(obj, _root=root):
            (_root / "contact-messages.json").write_text(json.dumps(obj, indent=2) + "\n", encoding="utf-8")

    found = False
    for item in inbox.get("messages") or []:
        if item.get("id") == msg_id:
            item["read"] = True
            found = True
            break
    if not found:
        return jsonify({"ok": False, "error": "message not found"}), 404
    save(inbox)
    return jsonify({"ok": True, "siteId": site_id})


@app.route("/api/inbox/comments/hide", methods=["POST"])
@require_login
def api_inbox_hide_comment():
    payload = request.get_json(force=True, silent=True) or {}
    site_id = str(payload.get("siteId") or SITE_ID).strip() or SITE_ID
    slug = str(payload.get("slug") or "").strip()
    comment_id = str(payload.get("id") or "").strip()
    if site_id != SITE_ID and not IS_OPS:
        return jsonify({"ok": False, "error": "Cross-site moderation requires Ops console"}), 403
    try:
        slug = validate_slug(slug)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    if not comment_id:
        return jsonify({"ok": False, "error": "id required"}), 400

    if site_id == SITE_ID:
        store = load_engagement()
        entry = project_engagement(slug, store)
        found = False
        for comment in entry.get("comments") or []:
            if comment.get("id") == comment_id:
                comment["hidden"] = True
                found = True
                break
        if not found:
            return jsonify({"ok": False, "error": "comment not found"}), 404
        save_engagement(store)
        return jsonify({"ok": True, "siteId": site_id})

    data, root = load_json_for_site(site_id, "engagement.json", {"projects": {}})
    if root is None:
        return jsonify({"ok": False, "error": f"site data root not found: {site_id}"}), 404
    store = data if isinstance(data, dict) else {"projects": {}}
    projects = store.setdefault("projects", {})
    entry = projects.get(slug)
    if not isinstance(entry, dict):
        return jsonify({"ok": False, "error": "comment not found"}), 404
    found = False
    for comment in entry.get("comments") or []:
        if isinstance(comment, dict) and comment.get("id") == comment_id:
            comment["hidden"] = True
            found = True
            break
    if not found:
        return jsonify({"ok": False, "error": "comment not found"}), 404
    (root / "engagement.json").write_text(json.dumps(store, indent=2) + "\n", encoding="utf-8")
    return jsonify({"ok": True, "siteId": site_id})


LOGIN_HTML = """
<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>VeerCanvas Admin</title>
<link rel="icon" href="/static/veer-canvas-icon.svg" type="image/svg+xml"/>
<link rel="stylesheet" href="/static/admin.css?v=20260725access1"/>
</head><body class="auth-page">
  <div class="auth-card">
  <div class="brand-lockup">
    <img class="brand-icon" src="/static/veer-canvas-icon.svg" alt="VeerCanvas"/>
    <h1>{% if is_ops %}VeerLabs Ops{% elif is_platform %}VeerCanvas Platform{% else %}VeerCanvas Admin{% endif %}</h1>
  </div>
  {% if error %}<p class="error">{{ error }}</p>{% endif %}
  <form method="post" action="{{ url_for('login') }}">
    {% if next %}<input type="hidden" name="next" value="{{ next }}"/>{% endif %}
    <label>Username<input name="username" value="admin" autocomplete="username"/></label>
    <label>Password<input name="password" type="password" autocomplete="current-password"/></label>
    <button class="btn primary" type="submit">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4"/><polyline points="10 17 15 12 10 7"/><line x1="15" y1="12" x2="3" y2="12"/></svg>
      Sign in
    </button>
  </form>
</div>
</body></html>
"""

DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>VeerCanvas Admin</title>
<link rel="icon" href="/static/veer-canvas-icon.svg" type="image/svg+xml"/>
<link rel="stylesheet" href="/static/admin.css?v=20260725access1"/>
</head><body>
<header class="admin-header">
  <div class="brand-lockup">
    <img class="brand-icon" src="/static/veer-canvas-icon.svg" alt="VeerCanvas"/>
    <div>
    <h1>VeerCanvas Admin</h1>
    <div class="meta-row">
      <span class="meta-chip">{{ meta.version }}</span>
      <span class="meta-chip">{{ site_id }}</span>
      <span class="meta-chip">{{ projects|length }} projects</span>
      <span class="meta-chip">{{ meta.lastUpdated }}</span>
    </div>
    </div>
  </div>
  <div class="header-actions">
    <button id="importBtn" class="btn secondary compact" type="button" title="Sync new GitHub repos into the live catalog">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
      Sync repos
    </button>
    <button id="publishBtn" class="btn primary compact" type="button">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M12 19V5"/><path d="m5 12 7-7 7 7"/><path d="M5 19h14"/></svg>
      Publish
    </button>
    <a class="btn ghost compact" href="{{ url_for('logout') }}">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>
      Logout
    </a>
  </div>
</header>

<main class="admin-layout">
  <section class="panel site-settings-panel">
    <div class="panel-head">
      <h2>Site &amp; dashboard content</h2>
      <span class="muted">Edits the public VeerLabs homepage chrome</span>
    </div>
    <form id="siteSettingsForm" class="editor-form">
      <div class="grid-2">
        <label>Site name<input id="site-siteName" name="siteName" value="{{ meta.siteName or '' }}"/></label>
        <label>Platform label<input id="site-platform" name="platform" value="{{ meta.platform or 'VeerCanvas' }}"/></label>
      </div>
      <div class="grid-2">
        <label>Brand name<input id="site-brandName" name="brandName" value="{{ meta.brandName or '' }}"/></label>
        <label>Brand tag<input id="site-brandTag" name="brandTag" value="{{ meta.brandTag or '' }}"/></label>
      </div>
      <label>Eyebrow<input id="site-eyebrow" name="eyebrow" value="{{ meta.eyebrow or '' }}" placeholder="Small label above the title"/></label>
      <label>Dashboard title<input id="site-title" name="title" value="{{ meta.title or meta.siteName or '' }}"/></label>
      <label>Dashboard subtitle<textarea id="site-subtitle" name="subtitle" rows="3">{{ meta.subtitle or '' }}</textarea></label>
      <div class="grid-2">
        <label>Top chip (primary)<input id="site-chipPrimary" name="chipPrimary" value="{{ meta.chipPrimary or '' }}"/></label>
        <label>Top chip (secondary)<input id="site-chipSecondary" name="chipSecondary" value="{{ meta.chipSecondary or '' }}"/></label>
      </div>
      <div class="grid-2">
        <label>Favicon path<input id="site-favicon" name="favicon" value="{{ meta.favicon or 'assets/favicon.svg' }}"/></label>
        <label>Site brand mark (header)<input id="site-brandMark" name="brandMark" value="{{ meta.brandMark or 'assets/veer-canvas-icon.svg' }}"/></label>
      </div>
      <label>VeerCanvas mark (footer)<input id="site-platformMark" name="platformMark" value="{{ meta.platformMark or 'assets/veer-canvas-icon.svg' }}"/>
        <span class="field-hint">Shown in the “Powered by VeerCanvas” footer — separate from the site header logo.</span>
      </label>
      <div class="brand-assets-grid">
        <div class="brand-asset-card">
          <div class="brand-asset-preview-wrap">
            <img id="site-brandMark-preview" class="brand-asset-preview" src="/site/{{ meta.brandMark or 'assets/veer-canvas-icon.svg' }}" alt="Site brand logo preview"/>
          </div>
          <label>Replace site brand logo
            <input type="file" id="site-brandMark-file" accept="image/png,image/jpeg,image/svg+xml,image/webp,image/gif,.png,.jpg,.jpeg,.svg,.webp,.gif"/>
            <span class="field-hint">Header / topbar logo for this website.</span>
          </label>
          <button type="button" class="btn secondary compact" id="uploadBrandMarkBtn">Upload site logo</button>
        </div>
        <div class="brand-asset-card">
          <div class="brand-asset-preview-wrap">
            <img id="site-platformMark-preview" class="brand-asset-preview" src="/site/{{ meta.platformMark or 'assets/veer-canvas-icon.svg' }}" alt="VeerCanvas footer logo preview"/>
          </div>
          <label>Replace VeerCanvas footer logo
            <input type="file" id="site-platformMark-file" accept="image/png,image/jpeg,image/svg+xml,image/webp,image/gif,.png,.jpg,.jpeg,.svg,.webp,.gif"/>
            <span class="field-hint">Icon next to “Powered by VeerCanvas” in the footer.</span>
          </label>
          <button type="button" class="btn secondary compact" id="uploadPlatformMarkBtn">Upload VeerCanvas logo</button>
        </div>
        <div class="brand-asset-card">
          <div class="brand-asset-preview-wrap is-favicon">
            <img id="site-favicon-preview" class="brand-asset-preview" src="/site/{{ meta.favicon or 'assets/favicon.svg' }}" alt="Favicon preview"/>
          </div>
          <label>Replace favicon
            <input type="file" id="site-favicon-file" accept="image/png,image/svg+xml,image/x-icon,image/webp,image/gif,.png,.svg,.ico,.webp,.gif"/>
            <span class="field-hint">Browser tab icon. PNG, SVG, ICO, or WebP.</span>
          </label>
          <button type="button" class="btn secondary compact" id="uploadFaviconBtn">Upload favicon</button>
        </div>
      </div>
      <div class="editor-actions">
        <button type="submit" class="btn primary compact">Save site content</button>
      </div>
    </form>
  </section>

  <section class="panel site-settings-panel">
    <div class="panel-head">
      <h2>GitHub sync</h2>
      <span class="muted" id="githubTokenStatus">
        {% if github_token.configured %}Token configured ({{ github_token.source }}) — private imports enabled
        {% else %}No token — private repos cannot be imported{% endif %}
      </span>
    </div>
    <form id="githubTokenForm" class="editor-form">
      <label>GitHub personal access token
        <input id="github-token-input" name="token" type="password" autocomplete="off" placeholder="ghp_… (repo scope for private repos)"/>
        <span class="field-hint">Stored on this server as <code>veercanvas/gh_token.txt</code>. Required once; then Sync works without redeploy.</span>
      </label>
      <div class="editor-actions">
        <button type="submit" class="btn primary compact">Save GitHub token</button>
        <button type="button" class="btn ghost compact" id="testGithubBtn">Test connection</button>
      </div>
    </form>
    <div class="sync-panel">
      <div class="panel-head">
        <h3>Pull repositories</h3>
        <span class="muted">Imports new GitHub repos into the live catalog — no redeploy needed</span>
      </div>
      <label>Only these slugs (optional)
        <input id="sync-only-slugs" type="text" placeholder="e.g. matteros, new-repo (leave blank for all new repos)"/>
        <span class="field-hint">Comma-separated. Blank = import every new repo under <code>{{ github_owner }}</code>.</span>
      </label>
      <div class="editor-actions">
        <button type="button" class="btn secondary compact" id="syncNewReposBtn">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
          Sync new repos
        </button>
        <button type="button" class="btn ghost compact" id="syncQueuedBtn">Sync queued re-imports</button>
      </div>
      <pre id="syncStatusLog" class="status-log sync-status-log" hidden></pre>
    </div>
  </section>

  <div class="workspace-row" id="workspaceRow">
  <section class="panel projects-panel" id="projectsPanel">
    <div class="panel-head">
      <h2>Projects</h2>
      <div class="panel-head-actions">
        <button id="newProjectBtn" class="btn primary compact" type="button" title="Create a project tile without GitHub import">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M12 5v14"/><path d="M5 12h14"/></svg>
          New project
        </button>
        <button id="normalizeOrderBtn" class="btn ghost compact" type="button" title="Renumber positions 1…N from the current list order">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M3 6h18"/><path d="M7 12h10"/><path d="M10 18h4"/></svg>
          Normalize order
        </button>
        <div class="search-wrap">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>
          <input id="search" type="search" placeholder="Search projects..." aria-label="Search projects"/>
        </div>
      </div>
    </div>
    <div class="table-wrap">
      <table>
        <thead>
          <tr><th>Pos</th><th>Logo</th><th>Name</th><th>Slug</th><th>Visible</th><th>Re-import</th><th>Size</th><th>Actions</th></tr>
        </thead>
        <tbody id="projectRows">
        {% for p in projects %}
        <tr data-slug="{{ p.slug }}">
          <td class="order-cell">
            <div class="order-controls">
              <button class="btn icon-btn order-btn" type="button" title="Move up" aria-label="Move {{ p.slug }} up" onclick="moveProject('{{ p.slug }}', 'up')" {% if loop.first %}disabled{% endif %}>
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="m18 15-6-6-6 6"/></svg>
              </button>
              <input class="order-input" type="number" min="1" max="{{ projects|length }}" value="{{ loop.index }}" title="Dashboard position" aria-label="Position for {{ p.slug }}" onchange="setProjectPosition('{{ p.slug }}', this.value)"/>
              <button class="btn icon-btn order-btn" type="button" title="Move down" aria-label="Move {{ p.slug }} down" onclick="moveProject('{{ p.slug }}', 'down')" {% if loop.last %}disabled{% endif %}>
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="m6 9 6 6 6-6"/></svg>
              </button>
            </div>
          </td>
          <td><img class="thumb" src="/site/{{ p.logo if p.logo and (p.logo.startswith('miniapps/') or p.logo.startswith('assets/')) else 'assets/default-project-logo.svg' }}" alt=""/></td>
          <td>{{ p.name }}</td>
          <td><code>{{ p.slug }}</code></td>
          <td><span class="pill {{ 'on' if p.enabled != False else 'off' }}">{{ 'Shown' if p.enabled != False else 'Hidden' }}</span></td>
          <td><span class="pill {{ 'warn' if p.reimport else 'off' }}">{{ 'Queued' if p.reimport else 'Idle' }}</span></td>
          <td>{% set _size = p.logoSize or 'md' %}{% if p.logoWidth or p.logoHeight %}{{ p.logoWidth or 'auto' }}×{{ p.logoHeight or logo_preset_heights.get(_size, 64) }}{% else %}{{ _size }}{% endif %}</td>
          <td class="actions">
            <button class="btn icon-btn edit" type="button" title="Edit {{ p.name }}" aria-label="Edit {{ p.slug }}" onclick="editProject('{{ p.slug }}')">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M12 20h9"/><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z"/></svg>
              <span class="sr-only">Edit</span>
            </button>
            {% if p.enabled != False %}
            <button class="btn icon-btn toggle" type="button" title="Hide {{ p.name }}" aria-label="Hide {{ p.slug }}" onclick="toggleProject('{{ p.slug }}')">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M17.94 17.94A10.94 10.94 0 0 1 12 20c-5 0-9.27-3.11-11-8 1.02-2.89 2.98-5.15 5.36-6.53"/><path d="M1 1l22 22"/><path d="M9.9 4.24A10.94 10.94 0 0 1 12 4c5 0 9.27 3.11 11 8a11.57 11.57 0 0 1-2.16 3.19"/><path d="M14.12 14.12a3 3 0 1 1-4.24-4.24"/></svg>
              <span class="sr-only">Hide</span>
            </button>
            {% else %}
            <button class="btn icon-btn toggle" type="button" title="Show {{ p.name }}" aria-label="Show {{ p.slug }}" onclick="toggleProject('{{ p.slug }}')">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8Z"/><circle cx="12" cy="12" r="3"/></svg>
              <span class="sr-only">Show</span>
            </button>
            {% endif %}
            <button class="btn icon-btn reimport" type="button" title="Queue re-import for {{ p.name }}" aria-label="Queue re-import {{ p.slug }}" onclick="queueReimport('{{ p.slug }}')">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/><path d="M3.51 9a9 9 0 0 1 14.13-3.36L23 10"/><path d="M20.49 15a9 9 0 0 1-14.13 3.36L1 14"/></svg>
              <span class="sr-only">Re-import</span>
            </button>
            <button class="btn icon-btn danger" type="button" title="Delete {{ p.name }}" aria-label="Delete {{ p.slug }}" onclick="deleteProject('{{ p.slug }}')">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><line x1="10" y1="11" x2="10" y2="17"/><line x1="14" y1="11" x2="14" y2="17"/></svg>
              <span class="sr-only">Delete</span>
            </button>
          </td>
        </tr>
        {% endfor %}
        </tbody>
      </table>
    </div>
  </section>

  <div
    class="pane-resizer"
    id="paneResizer"
    role="separator"
    aria-orientation="vertical"
    aria-label="Resize projects and editor panes"
    aria-controls="projectsPanel editorPanel"
    tabindex="0"
    title="Drag to resize panes"
  >
    <span class="pane-resizer-grip" aria-hidden="true"></span>
  </div>

  <section class="panel editor-panel" id="editorPanel">
    <div class="panel-head editor-panel-head">
      <h2 id="editorTitle">Edit project</h2>
      <button type="button" class="btn ghost compact" id="resetPaneWidthsBtn" title="Reset pane widths">Reset panes</button>
    </div>
    <form id="editorForm" class="editor-form">
      <input type="hidden" id="field-isNew" value="false"/>
      <label id="slugFieldWrap">Slug
        <input name="slug" id="field-slug" placeholder="my-project" autocomplete="off"/>
        <span class="field-hint" id="slugFieldHint">Lowercase letters, numbers, hyphens. Locked after create.</span>
      </label>
      <label>Name<input name="name" id="field-name" placeholder="Project display name"/></label>
      <label>Subtitle<textarea name="subtitle" id="field-subtitle" rows="2"></textarea></label>
      <label>Summary<textarea name="summary" id="field-summary" rows="4" placeholder="Plain text, markdown, or HTML"></textarea></label>
      <div class="grid-3">
        <label>Summary format<select name="summaryFormat" id="field-summaryFormat">
          <option value="auto">Auto detect</option>
          <option value="text">Plain text</option>
          <option value="markdown">Markdown</option>
          <option value="html">HTML</option>
        </select></label>
        <label>Summary align<select name="summaryAlign" id="field-summaryAlign">
          <option value="">Default</option>
          <option value="left">Left</option>
          <option value="center">Center</option>
          <option value="right">Right</option>
          <option value="justify">Justify</option>
        </select></label>
        <label>Summary size<select name="summarySize" id="field-summarySize">
          <option value="">Default</option>
          <option value="sm">Small</option>
          <option value="md">Medium</option>
          <option value="lg">Large</option>
          <option value="xl">Extra large</option>
        </select></label>
      </div>
      <div class="grid-2">
        <label>Enabled<select name="enabled" id="field-enabled"><option value="true">Shown</option><option value="false">Hidden</option></select></label>
        <label>Learn More auth<select name="requireAuth" id="field-requireAuth"><option value="false">Open (no gate)</option><option value="true">Require auth / visitor token</option></select>
          <span class="field-hint">When on, Learn More needs admin login or a 1-hour visitor access token.</span>
        </label>
      </div>
      <div class="grid-2">
        <label>Tile logo preset<select name="logoSize" id="field-logoSize">
          <option value="sm">Small (44px tall)</option>
          <option value="md">Medium (64px tall)</option>
          <option value="lg">Large (88px tall)</option>
          <option value="xl">Extra large (112px tall)</option>
        </select>
        <span class="field-hint">Used when custom height is blank.</span>
        </label>
      </div>
      <div class="grid-2">
        <label>Tile logo width (px)
          <input type="number" name="logoWidth" id="field-logoWidth" min="1" max="1024" step="1" placeholder="auto"/>
          <span class="field-hint">Leave blank for auto width.</span>
        </label>
        <label>Tile logo height (px)
          <input type="number" name="logoHeight" id="field-logoHeight" min="1" max="1024" step="1" placeholder="from preset"/>
          <span class="field-hint">Overrides the preset height on dashboard tiles.</span>
        </label>
      </div>
      <div class="logo-preview-wrap">
        <span class="field-hint">Tile preview</span>
        <img id="logoPreview" class="logo-preview" src="" alt="Logo preview"/>
      </div>
      <label>Queue re-import on next Import<select name="reimport" id="field-reimport"><option value="false">No</option><option value="true">Yes — refresh from GitHub</option></select></label>
      <label>Dashboard position
        <input type="number" name="sortOrder" id="field-sortOrder" min="1" step="1"/>
        <span class="field-hint">1 = first card on the public website. Use the Pos column arrows for quick reordering.</span>
      </label>
      <label>Tags (comma-separated)<input name="tags" id="field-tags"/></label>
      <label>Status (comma-separated)<input name="status" id="field-status"/></label>
      <label>Logo path<input name="logo" id="field-logo"/></label>
      <label>Upload logo<input type="file" id="field-logo-file" accept="image/*"/></label>

      <div class="content-editor-head">
        <h3>Content sections</h3>
        <div class="editor-mode-toggle">
          <button type="button" id="editorModeVisual" class="btn small ghost active">Visual</button>
          <button type="button" id="editorModeJson" class="btn small ghost">JSON</button>
        </div>
      </div>
      <div id="sectionEditor" class="section-editor"></div>
      <div id="detailsJsonWrap" hidden>
        <label>Details JSON<textarea name="details" id="field-details" rows="12"></textarea></label>
      </div>

      <div class="content-preview-wrap">
        <div class="content-editor-head">
          <h3>Live preview</h3>
          <span class="muted">Same renderer as the public site</span>
        </div>
        <div id="contentPreview" class="content-preview-panel project-body"></div>
      </div>
      <div class="editor-actions">
        <button type="submit" class="btn primary compact">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2Z"/><polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/></svg>
          Save changes
        </button>
        <button type="button" class="btn ghost compact" onclick="clearEditor()">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M3 6h18"/><path d="M8 6V4h8v2"/><path d="M19 6l-1 14H6L5 6"/></svg>
          Clear
        </button>
      </div>
    </form>
    <pre id="statusLog" class="status-log"></pre>
  </section>
  </div>
</main>
<link rel="stylesheet" href="/site/style.css"/>
<script src="https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js"></script>
<script src="/site/content-renderer.js"></script>
<script src="/static/content-editor.js?v=20260725cms1"></script>
<script src="/static/admin.js?v=20260725access1"></script>
</body></html>
"""


if __name__ == "__main__":
    init_db()
    static_dir = APP_DIR / "static"
    static_dir.mkdir(exist_ok=True)
    port = int(os.environ.get("PORT", os.environ.get("VEERCANVAS_ADMIN_PORT", "8080")))
    print("Starting admin app. SITE_ROOT=", SITE_ROOT, "PORT=", port, "PLATFORM=", IS_PLATFORM, "OPS=", IS_OPS)
    app.run(host="0.0.0.0", port=port, debug=False)
