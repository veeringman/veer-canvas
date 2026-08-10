#!/usr/bin/env python3
"""Verify every logo.manifest.json consumer still points at its role asset.

Also lists unmanaged references under the site (stray mhws-logo / seal paths)
so new placements can be registered.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from logo_registry import (
    SITE_ROOT,
    load_manifest,
    path_match_needles,
    render_readme,
    role_path,
    sync_site_meta_logo_fields,
)

SCAN_GLOBS = (
    "*.html",
    "*.js",
    "*.json",
    "*.webmanifest",
    "*.py",
    "*.css",
    "*.md",
)
SKIP_DIR_NAMES = {
    "node_modules",
    ".git",
    "tmp",
    "__pycache__",
    "data",
}


def _file_has_role(text: str, rel_path: str) -> bool:
    return any(n in text for n in path_match_needles(rel_path))


def check_consumers(manifest: dict) -> list[str]:
    errors: list[str] = []
    roles = manifest.get("roles") or {}
    for c in manifest.get("consumers") or []:
        cid = c.get("id") or "?"
        role = c.get("role")
        rel = c.get("file")
        if role not in roles:
            errors.append(f"{cid}: unknown role `{role}`")
            continue
        path = SITE_ROOT / rel
        if not path.is_file():
            errors.append(f"{cid}: missing file `{rel}`")
            continue
        asset = role_path(manifest, role)
        asset_abs = SITE_ROOT / asset
        if not asset_abs.is_file():
            errors.append(f"{cid}: role `{role}` asset missing on disk: `{asset}`")
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if not _file_has_role(text, asset):
            errors.append(
                f"{cid}: `{rel}` does not reference role `{role}` path `{asset}`"
            )
    return errors


def find_stray_refs(manifest: dict) -> list[str]:
    """Find source files mentioning logo assets that are not registered consumers."""
    registered_files = {c.get("file") for c in manifest.get("consumers") or []}
    # Also allow the registry / tooling itself
    registered_files.update(
        {
            "assets/mhws-logo/logo.manifest.json",
            "assets/mhws-logo/README.md",
            "scripts/logo_registry.py",
            "scripts/check_logo_refs.py",
            "scripts/export_logo_variants.py",
            "scripts/regenerate_official_logo.py",
            "documents/README.md",
        }
    )
    pattern = re.compile(
        r"(mhws-logo-[a-z0-9.-]+\.png|hbcs-sanyard-seal[^\"'\s)]*|favicon-192\.png|"
        r"apple-touch-icon[^\"'\s)]*)",
        re.I,
    )
    strays: list[str] = []
    for glob in SCAN_GLOBS:
        for path in SITE_ROOT.rglob(glob):
            if any(part in SKIP_DIR_NAMES for part in path.parts):
                continue
            rel = str(path.relative_to(SITE_ROOT))
            if rel in registered_files:
                continue
            # Skip binary-ish and generated archives
            if "mhws-logo-official-" in path.name and path.suffix == ".png":
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            hits = pattern.findall(text)
            if hits:
                uniq = sorted(set(hits))
                strays.append(f"{rel}: {', '.join(uniq[:8])}")
    return strays


def write_readme(manifest: dict) -> None:
    readme = SITE_ROOT / "assets" / "mhws-logo" / "README.md"
    readme.write_text(render_readme(manifest), encoding="utf-8")
    print(f"  wrote {readme.relative_to(SITE_ROOT)}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--write-readme", action="store_true", help="Regenerate assets/mhws-logo/README.md")
    ap.add_argument("--sync-meta", action="store_true", help="Sync site-meta.json logo fields from roles")
    ap.add_argument("--strict-stray", action="store_true", help="Fail if unmanaged logo refs found")
    args = ap.parse_args()

    manifest = load_manifest()
    print(f"Logo manifest v{manifest.get('version')} — {len(manifest.get('consumers') or [])} consumers")

    if args.sync_meta:
        sync_site_meta_logo_fields(manifest)
    if args.write_readme:
        write_readme(manifest)

    errors = check_consumers(manifest)
    strays = find_stray_refs(manifest)

    if errors:
        print("\nCONSUMER ERRORS:")
        for e in errors:
            print(f"  ✗ {e}")
    else:
        print("All registered consumers OK.")

    if strays:
        print("\nUnmanaged logo references (add to logo.manifest.json consumers if intentional):")
        for s in strays:
            print(f"  · {s}")
    else:
        print("No unmanaged logo references found.")

    if errors or (args.strict_stray and strays):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
