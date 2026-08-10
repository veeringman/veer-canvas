#!/usr/bin/env python3
"""Load assets/mhws-logo/logo.manifest.json — single source of truth for logo roles & consumers."""

from __future__ import annotations

import json
from pathlib import Path

SITE_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = SITE_ROOT / "assets" / "mhws-logo" / "logo.manifest.json"


def load_manifest(path: Path | None = None) -> dict:
    p = path or MANIFEST_PATH
    if not p.is_file():
        raise FileNotFoundError(f"Logo manifest missing: {p}")
    return json.loads(p.read_text(encoding="utf-8"))


def role_path(manifest: dict, role: str) -> str:
    roles = manifest.get("roles") or {}
    if role not in roles:
        raise KeyError(f"Unknown logo role: {role}")
    return str(roles[role]["path"])


def role_basename(manifest: dict, role: str) -> str:
    return Path(role_path(manifest, role)).name


def path_match_needles(rel_path: str) -> list[str]:
    """Filenames / path suffixes that count as a hit for this asset in source files."""
    p = Path(rel_path)
    name = p.name
    needles = [name, rel_path, f"/{rel_path}", f"../{rel_path}"]
    # Common site-relative forms
    if rel_path.startswith("assets/"):
        needles.append(rel_path)
        needles.append(f"../{rel_path}")
        needles.append(f"/{rel_path}")
    return list(dict.fromkeys(needles))


def consumers_for_role(manifest: dict, role: str) -> list[dict]:
    return [c for c in manifest.get("consumers") or [] if c.get("role") == role]


def render_readme(manifest: dict) -> str:
    lines = [
        "# MHWS logo pack — managed registry",
        "",
        "Single source of truth: [`logo.manifest.json`](logo.manifest.json).",
        "",
        "## How to change the logo",
        "",
    ]
    for step in manifest.get("howtoChange") or []:
        lines.append(f"- {step}")
    lines += [
        "",
        "When you add a new place that shows the logo, **append a consumer** in",
        "`logo.manifest.json`, then run `python3 scripts/check_logo_refs.py`.",
        "",
        "## Roles",
        "",
        "| Role | Path | Use |",
        "|------|------|-----|",
    ]
    for role, meta in (manifest.get("roles") or {}).items():
        lines.append(f"| `{role}` | `{meta.get('path')}` | {meta.get('use', '')} |")
    lines += [
        "",
        "## Consumers (places the logo is applied)",
        "",
        "| Id | File | Role | Kind | Note |",
        "|----|------|------|------|------|",
    ]
    for c in manifest.get("consumers") or []:
        lines.append(
            f"| `{c.get('id')}` | `{c.get('file')}` | `{c.get('role')}` | `{c.get('kind')}` | {c.get('note', '')} |"
        )
    lines += [
        "",
        f"Version: `{manifest.get('version')}` · Updated: `{manifest.get('updated')}`",
        "",
        "Master: `" + str(manifest.get("master")) + "`  ",
        "Locked: `" + str(manifest.get("locked")) + "`  ",
        "Archive (regen source): `" + str(manifest.get("archive")) + "`",
        "",
    ]
    return "\n".join(lines)


def sync_site_meta_logo_fields(manifest: dict) -> None:
    """Keep site-meta.json brand/logo keys aligned with roles."""
    meta_path = SITE_ROOT / "site-meta.json"
    if not meta_path.is_file():
        return
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    mapping = {
        "favicon": "favicon",
        "brandMark": "official",
        "logoPrint": "print",
        "logoWatermark": "watermark",
        "logoWeb": "web512",
    }
    changed = False
    for key, role in mapping.items():
        want = role_path(manifest, role)
        if meta.get(key) != want:
            meta[key] = want
            changed = True
    if changed:
        meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"  synced {meta_path.relative_to(SITE_ROOT)}")
