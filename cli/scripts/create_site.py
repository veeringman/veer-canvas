#!/usr/bin/env python3
"""Scaffold a new VeerCanvas website under sites/<site-id>.

Usage:
  python cli/scripts/create_site.py my-catalog \\
    --name "My Catalog" \\
    --domain mycatalog.example.com \\
    --github-owner veeringman

Domain defaults to <site-id>.veerlabs.solutions when omitted.

Then run admin against it:
  export VEERCANVAS_SITE_ID=my-catalog
  export VEERCANVAS_SITE_ROOT="$(pwd)/sites/my-catalog"
  python admin/admin_app.py

Deploy:
  SITE_ID=my-catalog EC2_KEY=./VeerSetuHost.pem ./deploy/remote-deploy.sh
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import shutil
import sys
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parents[2]
SITES = ROOT / "sites"
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
THEME_FILES = (
    "index.html",
    "project.html",
    "style.css",
    "content-renderer.js",
    "pagination.js",
    "project.js",
    "site-meta.js",
    "site-utils.js",
)


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _next_port(sites_root: pathlib.Path) -> int:
    used = {8080}
    if sites_root.is_dir():
        for path in sites_root.iterdir():
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


def create_site(site_id: str, *, name: str, domain: str, github_owner: str, force: bool) -> pathlib.Path:
    site_id = slugify(site_id)
    if not site_id or not SLUG_RE.match(site_id):
        raise SystemExit("error: site id must be lowercase letters/numbers/hyphens")
    if site_id in {"_template", "admin", "api"}:
        raise SystemExit(f"error: reserved site id: {site_id}")

    dest = SITES / site_id
    if dest.exists() and any(dest.iterdir()) and not force:
        raise SystemExit(f"error: site already exists: {dest} (pass --force to overwrite theme files)")
    dest.mkdir(parents=True, exist_ok=True)

    theme_src = SITES / "veerlabs"
    if not theme_src.is_dir():
        theme_src = SITES / "_template"

    display_name = (name or site_id.replace("-", " ").title()).strip()
    domain_value = (domain or f"{site_id}.veerlabs.solutions").strip()
    owner = (github_owner or "veeringman").strip()

    config = {
        "id": site_id,
        "name": display_name,
        "description": f"{display_name} — VeerCanvas site",
        "domain": domain_value,
        "aliases": [f"www.{domain_value}"] if domain_value else [],
        "webRoot": f"/var/www/{domain_value}",
        "githubOwner": owner,
        "admin": {
            "serviceName": f"veercanvas-admin-{site_id}",
            "port": _next_port(SITES),
        },
        "platform": False,
    }
    (dest / "site.config.json").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")

    meta = {
        "version": "v1.0.0",
        "lastUpdated": utc_now(),
        "siteName": display_name,
        "brandName": display_name.split()[0] if display_name else site_id,
        "brandTag": " ".join(display_name.split()[1:]) if len(display_name.split()) > 1 else "Site",
        "eyebrow": f"{display_name} catalog",
        "title": display_name,
        "subtitle": f"Explore projects published on {display_name}.",
        "chipPrimary": "Project catalog",
        "chipSecondary": "Powered by VeerCanvas",
        "platform": "VeerCanvas",
        "platformSiteId": site_id,
        "favicon": "assets/favicon.svg",
        "brandMark": "assets/veer-canvas-icon.svg",
    }
    (dest / "site-meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    (dest / "projects.json").write_text("[]\n", encoding="utf-8")
    (dest / "projects-public.json").write_text("[]\n", encoding="utf-8")
    (dest / "catalog-exclusions.json").write_text(
        json.dumps({"deletedSlugs": []}, indent=2) + "\n", encoding="utf-8"
    )
    (dest / "miniapps").mkdir(exist_ok=True)
    (dest / "assets" / "site").mkdir(parents=True, exist_ok=True)

    for theme_file in THEME_FILES:
        src = theme_src / theme_file
        if src.exists():
            shutil.copy2(src, dest / theme_file)

    assets_src = theme_src / "assets"
    assets_dest = dest / "assets"
    if assets_src.is_dir():
        for item in assets_src.iterdir():
            if item.name == "site":
                continue
            target = assets_dest / item.name
            if item.is_dir():
                if target.exists():
                    shutil.rmtree(target)
                shutil.copytree(item, target)
            else:
                shutil.copy2(item, target)

    return dest


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a new VeerCanvas website scaffold")
    parser.add_argument("site_id", help="Site folder id (e.g. my-catalog)")
    parser.add_argument("--name", default="", help="Display name")
    parser.add_argument("--domain", default="", help="Primary domain")
    parser.add_argument("--github-owner", default="veeringman", help="GitHub owner/org for imports")
    parser.add_argument("--force", action="store_true", help="Overwrite theme files if site exists")
    args = parser.parse_args()

    dest = create_site(
        args.site_id,
        name=args.name,
        domain=args.domain,
        github_owner=args.github_owner,
        force=args.force,
    )
    print(f"Created VeerCanvas site at {dest}")
    print("")
    print("Run admin against this site:")
    print(f"  export VEERCANVAS_SITE_ID={dest.name}")
    print(f"  export VEERCANVAS_SITE_ROOT=\"{dest}\"")
    print("  python admin/admin_app.py")
    print("")
    print("Deploy:")
    print(f"  SITE_ID={dest.name} EC2_KEY=./VeerSetuHost.pem ./deploy/remote-deploy.sh")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
