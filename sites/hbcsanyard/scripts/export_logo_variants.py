#!/usr/bin/env python3
"""Lock the final MHWS logo and export lighter variants for web / PWA / print / watermark.

After export, refreshes assets/mhws-logo/README.md from logo.manifest.json and
syncs site-meta.json role paths. Consumer registry lives in logo.manifest.json.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from PIL import Image

from logo_registry import load_manifest, render_readme, sync_site_meta_logo_fields

SITE_ROOT = Path(__file__).resolve().parents[1]
LOGO_DIR = SITE_ROOT / "assets" / "mhws-logo"
MASTER = LOGO_DIR / "mhws-logo-official.png"
LOCKED = LOGO_DIR / "mhws-logo-official-locked-20260810.png"

# Soft cream plate for app icons (matches PWA background_color).
ICON_BG = (246, 241, 230, 255)
NAVY_BG = (21, 35, 63, 255)


def _load_master() -> Image.Image:
    if not MASTER.is_file():
        raise FileNotFoundError(f"Master logo missing: {MASTER}")
    img = Image.open(MASTER).convert("RGBA")
    # Ensure true transparency outside the seal (no flat black matte).
    return img


def _fit(img: Image.Image, size: int, *, pad_ratio: float = 0.0) -> Image.Image:
    """Scale logo into a size×size transparent canvas with optional relative padding."""
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    inner = max(1, int(size * (1.0 - 2 * pad_ratio)))
    scaled = img.copy()
    scaled.thumbnail((inner, inner), Image.Resampling.LANCZOS)
    x = (size - scaled.size[0]) // 2
    y = (size - scaled.size[1]) // 2
    canvas.alpha_composite(scaled, (x, y))
    return canvas


def _on_plate(img: Image.Image, size: int, bg: tuple[int, int, int, int], *, pad_ratio: float = 0.12) -> Image.Image:
    plate = Image.new("RGBA", (size, size), bg)
    mark = _fit(img, size, pad_ratio=pad_ratio)
    plate.alpha_composite(mark)
    return plate


def _watermark(img: Image.Image, size: int = 1024, alpha: float = 0.10) -> Image.Image:
    base = _fit(img, size, pad_ratio=0.04)
    r, g, b, a = base.split()
    a = a.point(lambda v: int(v * alpha))
    out = Image.merge("RGBA", (r, g, b, a))
    return out


def _save(img: Image.Image, path: Path, *, optimize: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, format="PNG", optimize=optimize)
    print(f"  wrote {path.relative_to(SITE_ROOT)} ({img.size[0]}×{img.size[1]})")


def _save_jpeg(img: Image.Image, path: Path, *, quality: int = 88, bg=(246, 241, 230)) -> None:
    rgb = Image.new("RGB", img.size, bg)
    rgb.paste(img, mask=img.split()[3] if img.mode == "RGBA" else None)
    path.parent.mkdir(parents=True, exist_ok=True)
    rgb.save(path, format="JPEG", quality=quality, optimize=True)
    print(f"  wrote {path.relative_to(SITE_ROOT)} ({img.size[0]}×{img.size[1]} jpeg)")


def export_all() -> None:
    master = _load_master()
    print(f"Locking master {MASTER.name} ({master.size[0]}×{master.size[1]})")
    shutil.copy2(MASTER, LOCKED)
    print(f"  locked → {LOCKED.relative_to(SITE_ROOT)}")

    # Transparent masters / lighter web sizes
    _save(master, MASTER)  # re-save optimized
    _save(_fit(master, 1024, pad_ratio=0.02), LOGO_DIR / "mhws-logo-print.png")
    _save(_fit(master, 512, pad_ratio=0.02), LOGO_DIR / "mhws-logo-web-512.png")
    _save(_fit(master, 256, pad_ratio=0.02), LOGO_DIR / "mhws-logo-web-256.png")
    _save(_fit(master, 128, pad_ratio=0.02), LOGO_DIR / "mhws-logo-icon-128.png")
    _save(_fit(master, 64, pad_ratio=0.02), LOGO_DIR / "mhws-logo-icon-64.png")
    _save(_watermark(master, 1024, alpha=0.10), LOGO_DIR / "mhws-logo-watermark.png")

    # Transparent mark used by legacy seal paths
    mark512 = _fit(master, 512, pad_ratio=0.04)
    _save(mark512, SITE_ROOT / "assets" / "hbcs-sanyard-seal-mark.png")
    _save(mark512, SITE_ROOT / "assets" / "hbcs-sanyard-seal.png")

    # PWA / favicon / apple-touch (cream plate — lighter, OS-safe)
    fav192 = _on_plate(master, 192, ICON_BG, pad_ratio=0.10)
    _save(fav192, SITE_ROOT / "assets" / "favicon-192.png")
    _save_jpeg(fav192, SITE_ROOT / "assets" / "favicon-192.jpg", quality=90)

    for name, size, pad in (
        ("apple-touch-icon.png", 180, 0.10),
        ("apple-touch-icon-167.png", 167, 0.10),
        ("apple-touch-icon-152.png", 152, 0.10),
    ):
        icon = _on_plate(master, size, ICON_BG, pad_ratio=pad)
        _save(icon, SITE_ROOT / "assets" / name)
        if name == "apple-touch-icon.png":
            _save(icon, SITE_ROOT / "apple-touch-icon.png")

    # 512 any + maskable (maskable keeps more padding)
    seal512 = _on_plate(master, 512, ICON_BG, pad_ratio=0.10)
    _save(seal512, SITE_ROOT / "assets" / "hbcs-sanyard-seal-512.png")
    _save_jpeg(seal512, SITE_ROOT / "assets" / "hbcs-sanyard-seal-512.jpg", quality=90)
    maskable = _on_plate(master, 512, NAVY_BG, pad_ratio=0.18)
    _save(maskable, SITE_ROOT / "assets" / "hbcs-sanyard-seal-512-maskable.png")

    # Legacy 240 / 480 caches
    for size, stem in ((240, "hbcs-sanyard-seal-240"), (480, "hbcs-sanyard-seal-480")):
        plate = _on_plate(master, size, ICON_BG, pad_ratio=0.10)
        _save(plate, SITE_ROOT / "assets" / f"{stem}.png")
        _save_jpeg(plate, SITE_ROOT / "assets" / f"{stem}.jpg", quality=88)
        try:
            plate.save(SITE_ROOT / "assets" / f"{stem}.webp", format="WEBP", quality=86, method=6)
            print(f"  wrote assets/{stem}.webp")
        except Exception:
            pass

    mark_jpg_src = _on_plate(master, 512, ICON_BG, pad_ratio=0.08)
    _save_jpeg(mark_jpg_src, SITE_ROOT / "assets" / "hbcs-sanyard-seal-mark.jpg", quality=90)
    try:
        mark512.save(SITE_ROOT / "assets" / "hbcs-sanyard-seal-mark.webp", format="WEBP", quality=86, method=6)
        print("  wrote assets/hbcs-sanyard-seal-mark.webp")
    except Exception:
        pass

    # Lightweight OG-ish square mark (full logo on cream) — keep existing og-share-card if complex
    _save(_on_plate(master, 512, ICON_BG, pad_ratio=0.08), LOGO_DIR / "mhws-logo-og-square.png")

    # Refresh managed docs / meta from registry
    try:
        manifest = load_manifest()
        readme = LOGO_DIR / "README.md"
        readme.write_text(render_readme(manifest), encoding="utf-8")
        print(f"  wrote {readme.relative_to(SITE_ROOT)} (from logo.manifest.json)")
        sync_site_meta_logo_fields(manifest)
    except Exception as exc:
        print(f"  warning: could not refresh registry docs: {exc}")

    print("Done — logo variants exported.")
    print("Next: python3 scripts/check_logo_refs.py")


if __name__ == "__main__":
    export_all()
