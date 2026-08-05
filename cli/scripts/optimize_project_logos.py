#!/usr/bin/env python3
"""Generate lightweight WebP logo variants for catalog cards and detail headers."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ADMIN_DIR = Path(__file__).resolve().parents[2] / "admin"
if str(ADMIN_DIR) not in sys.path:
    sys.path.insert(0, str(ADMIN_DIR))

from logo_optimize import RASTER_EXT, optimize_logo_file  # noqa: E402


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def load_logo_paths(site_root: Path) -> list[Path]:
    import json

    paths: set[str] = set()
    for name in ("projects.json", "projects-public.json"):
        catalog = site_root / name
        if not catalog.is_file():
            continue
        try:
            data = json.loads(catalog.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        entries = data if isinstance(data, list) else []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            logo = str(entry.get("logo") or "").strip()
            if logo and not logo.startswith("http") and not logo.endswith(".svg"):
                paths.add(logo)
    for project_json in site_root.glob("miniapps/*/project.json"):
        try:
            entry = json.loads(project_json.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        logo = str(entry.get("logo") or "").strip()
        if logo and not logo.startswith("http") and not logo.endswith(".svg"):
            if logo.startswith("miniapps/") or logo.startswith("assets/"):
                paths.add(logo)
            else:
                slug = project_json.parent.parent.name
                paths.add(f"miniapps/{slug}/{logo.lstrip('./')}")
    resolved: list[Path] = []
    for rel in sorted(paths):
        path = site_root / rel
        if path.is_file() and path.suffix.lower() in RASTER_EXT:
            resolved.append(path)
    return resolved


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--site-root",
        default=str(repo_root() / "sites" / "veerlabs"),
        help="Site root containing miniapps/ and projects.json",
    )
    parser.add_argument("--force", action="store_true", help="Regenerate even if outputs are newer")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    site_root = Path(args.site_root).resolve()
    if not site_root.is_dir():
        print(f"error: site root not found: {site_root}", file=sys.stderr)
        return 1

    logos = load_logo_paths(site_root)
    if not logos:
        print("No raster logos found in catalog.")
        return 0

    total_before = 0
    total_after = 0
    made = 0
    for source in logos:
        if args.dry_run:
            print(f"DRY {source.name} -> recompress + card/detail webp")
            continue
        result = optimize_logo_file(source, force=args.force)
        before = result.get("bytes_before") or source.stat().st_size
        total_before += before
        if result.get("error"):
            print(f"FAIL {source}: {result['error']}")
            continue
        after = result.get("bytes_after") or before
        total_after += after
        if result.get("optimized"):
            made += 1
        saved = result.get("saved") or 0
        pct = (100 * saved / before) if before else 0
        print(f"OK   {source.name}  {before // 1024}KB -> {after // 1024}KB master ({pct:.0f}% saved)")

    if not args.dry_run:
        print(f"\nProcessed {len(logos)} logos ({made} optimized). Master total ~{total_before // 1024}KB -> ~{total_after // 1024}KB.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
