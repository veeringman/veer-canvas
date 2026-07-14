#!/usr/bin/env python3
"""VeerCanvas admin — content authoring and publishing CMS."""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from functools import wraps

from flask import Flask, jsonify, redirect, render_template_string, request, send_from_directory, session, url_for
import sqlite3

APP_DIR = pathlib.Path(__file__).resolve().parent
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

app = Flask(__name__, static_folder=str(APP_DIR / "static"), static_url_path="/static")
app.secret_key = os.environ.get("VEERCANVAS_ADMIN_SECRET", os.environ.get("VEER_ADMIN_SECRET", "veercanvas-admin-secret"))


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


def require_login(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if session.get("logged_in"):
            return f(*args, **kwargs)
        return redirect(url_for("login"))
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
    visible = [project for project in data if is_enabled(project)]
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
    if not path.exists():
        return {"version": "v1.0.0", "lastUpdated": utc_now(), "siteName": "VeerLabs Solutions"}
    return json.loads(path.read_text(encoding="utf-8"))


def save_site_meta(meta: dict) -> None:
    site_meta_path().write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")


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


def github_token() -> str | None:
    for key in ("GH_TOKEN", "GITHUB_TOKEN"):
        if os.environ.get(key):
            return os.environ[key]
    token_file = APP_DIR.parent / "gh_token.txt"
    if token_file.exists():
        return token_file.read_text(encoding="utf-8").strip()
    return None


def run_import(include_private: bool = True) -> tuple[bool, str]:
    if not IMPORT_SCRIPT.exists():
        return False, f"Import script not found: {IMPORT_SCRIPT}"
    cmd = [
        sys.executable,
        str(IMPORT_SCRIPT),
        DEFAULT_OWNER,
        "imported_projects",
        "--site-root",
        str(SITE_ROOT),
        "--projects-json",
        str(projects_path()),
        "--replace-existing",
        "--fetch-repos",
    ]
    if include_private:
        pass
    else:
        cmd.append("--public-only")
    token = github_token()
    if token:
        cmd.extend(["--token", token])
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(SITE_ROOT))
    output = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode == 0, output[-4000:]


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if check_login(request.form.get("username", ""), request.form.get("password", "")):
            session["logged_in"] = True
            session["username"] = request.form.get("username")
            return redirect(url_for("dashboard"))
        return render_template_string(LOGIN_HTML, error="Invalid credentials")
    return render_template_string(LOGIN_HTML)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@require_login
def dashboard():
    projects = load_projects()
    meta = load_site_meta()
    return render_template_string(
        DASHBOARD_HTML,
        projects=projects,
        meta=meta,
        logo_sizes=LOGO_SIZES,
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
    _, project, _ = find_project(slug)
    if not project:
        return jsonify({"ok": False, "error": "not found"}), 404
    return jsonify({"ok": True, "project": project})


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
    project["enabled"] = not bool(project.get("enabled", True))
    data[idx] = project
    save_projects(data)
    sync_miniapp(slug, project)
    return jsonify({"ok": True, "enabled": project["enabled"]})


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
    save_projects(data)
    add_exclusion(slug)
    return jsonify({"ok": True})


@app.route("/api/update", methods=["POST"])
@require_login
def api_update():
    payload = request.get_json(force=True, silent=True)
    if not payload:
        return jsonify({"ok": False, "error": "invalid json"}), 400
    slug = payload.get("slug")
    if not slug:
        return jsonify({"ok": False, "error": "slug required"}), 400
    payload.setdefault("enabled", True)
    payload.setdefault("logoSize", "md")
    if payload.get("logoSize") not in LOGO_SIZES:
        payload["logoSize"] = "md"
    data, _, idx = find_project(slug)
    if idx >= 0:
        preserved = {k: data[idx][k] for k in ("sortOrder",) if k in data[idx] and "sortOrder" not in payload}
        payload.update(preserved)
        data[idx] = payload
    else:
        payload.setdefault("sortOrder", len(data))
        data.append(payload)
    remove_exclusion(slug)
    save_projects(data)
    sync_miniapp(slug, payload)
    return jsonify({"ok": True, "project": payload})


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
    file.save(dest)
    logo_path = f"miniapps/{slug}/assets/logo{ext}"
    data, project, idx = find_project(slug)
    if project is None:
        return jsonify({"ok": False, "error": "project not found"}), 404
    project["logo"] = logo_path
    data[idx] = project
    save_projects(data)
    sync_miniapp(slug, project)
    return jsonify({"ok": True, "logo": logo_path})


@app.route("/api/import", methods=["POST"])
@require_login
def api_import():
    payload = request.get_json(force=True, silent=True) or {}
    include_private = payload.get("includePrivate", True)
    ok, output = run_import(include_private=include_private)
    meta = load_site_meta()
    return jsonify({
        "ok": ok,
        "output": output,
        "projectCount": len(load_projects()),
        "version": meta.get("version"),
    }), (200 if ok else 500)


@app.route("/api/publish", methods=["POST"])
@require_login
def api_publish():
    meta = load_site_meta()
    meta["version"] = bump_minor_version(meta.get("version", "v1.0.0"))
    meta["lastUpdated"] = utc_now()
    save_site_meta(meta)
    # Re-sync catalog from miniapps to ensure consistency
    if IMPORT_SCRIPT.exists():
        subprocess.run([
            sys.executable, str(IMPORT_SCRIPT), DEFAULT_OWNER, "imported_projects",
            "--site-root", str(SITE_ROOT), "--projects-json", str(projects_path()),
            "--sync-only",
        ], check=False, capture_output=True, text=True)
    else:
        write_public_catalog()
    return jsonify({
        "ok": True,
        "meta": meta,
        "projectCount": len(load_projects()),
        "publicCount": len(json.loads(PUBLIC_CATALOG_PATH.read_text(encoding="utf-8"))) if PUBLIC_CATALOG_PATH.exists() else 0,
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


LOGIN_HTML = """
<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>VeerCanvas Admin</title>
<link rel="stylesheet" href="/static/admin.css"/>
</head><body class="auth-page">
<div class="auth-card">
  <h1>VeerCanvas Admin</h1>
  {% if error %}<p class="error">{{ error }}</p>{% endif %}
  <form method="post">
    <label>Username<input name="username" value="admin" autocomplete="username"/></label>
    <label>Password<input name="password" type="password" autocomplete="current-password"/></label>
    <button type="submit">Sign in</button>
  </form>
</div>
</body></html>
"""

DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>VeerCanvas Admin</title>
<link rel="stylesheet" href="/static/admin.css"/>
</head><body>
<header class="admin-header">
  <div>
    <h1>VeerCanvas Admin</h1>
    <p class="muted">Site {{ meta.version }} · {{ meta.lastUpdated }} · {{ projects|length }} projects</p>
  </div>
  <div class="header-actions">
    <button id="importBtn" class="btn secondary">Import GitHub repos</button>
    <button id="publishBtn" class="btn primary">Publish (bump version)</button>
    <a class="btn ghost" href="/logout">Logout</a>
  </div>
</header>

<main class="admin-layout">
  <section class="panel">
    <div class="panel-head">
      <h2>Projects</h2>
      <input id="search" type="search" placeholder="Search projects..." />
    </div>
    <div class="table-wrap">
      <table>
        <thead>
          <tr><th>Logo</th><th>Name</th><th>Slug</th><th>Visible</th><th>Logo size</th><th>Actions</th></tr>
        </thead>
        <tbody id="projectRows">
        {% for p in projects %}
        <tr data-slug="{{ p.slug }}">
          <td><img class="thumb" src="/site/{{ p.logo if p.logo and (p.logo.startswith('miniapps/') or p.logo.startswith('assets/')) else 'assets/default-project-logo.svg' }}" alt=""/></td>
          <td>{{ p.name }}</td>
          <td><code>{{ p.slug }}</code></td>
          <td><span class="pill {{ 'on' if p.enabled != False else 'off' }}">{{ 'Shown' if p.enabled != False else 'Hidden' }}</span></td>
          <td>{{ p.logoSize or 'md' }}</td>
          <td class="actions">
            <button class="btn small" onclick="editProject('{{ p.slug }}')">Edit</button>
            <button class="btn small" onclick="toggleProject('{{ p.slug }}')">{{ 'Hide' if p.enabled != False else 'Show' }}</button>
            <button class="btn small danger" onclick="deleteProject('{{ p.slug }}')">Delete</button>
          </td>
        </tr>
        {% endfor %}
        </tbody>
      </table>
    </div>
  </section>

  <section class="panel editor-panel" id="editorPanel">
    <h2>Edit project</h2>
    <form id="editorForm" class="editor-form">
      <input type="hidden" name="slug" id="field-slug"/>
      <label>Name<input name="name" id="field-name"/></label>
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
        <label>Logo size<select name="logoSize" id="field-logoSize">{% for s in logo_sizes %}<option value="{{ s }}">{{ s }}</option>{% endfor %}</select></label>
      </div>
      <label>Sort order<input type="number" name="sortOrder" id="field-sortOrder"/></label>
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
          <span class="muted">Uses the same renderer as the public site, including Mermaid.</span>
        </div>
        <div id="contentPreview" class="content-preview-panel project-body"></div>
      </div>
      <div class="editor-actions">
        <button type="submit" class="btn primary">Save changes</button>
        <button type="button" class="btn ghost" onclick="clearEditor()">Clear</button>
      </div>
    </form>
    <pre id="statusLog" class="status-log"></pre>
  </section>
</main>
<link rel="stylesheet" href="/site/style.css"/>
<script src="https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js"></script>
<script src="/site/content-renderer.js"></script>
<script src="/static/content-editor.js"></script>
<script src="/static/admin.js"></script>
</body></html>
"""


if __name__ == "__main__":
    init_db()
    static_dir = APP_DIR / "static"
    static_dir.mkdir(exist_ok=True)
    print("Starting admin app. SITE_ROOT=", SITE_ROOT)
    app.run(host="0.0.0.0", port=8080, debug=False)
