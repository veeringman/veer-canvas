#!/usr/bin/env python3
"""Lock the final MHWS logo and export lighter variants for web / PWA / print / watermark.

After export, refreshes assets/mhws-logo/README.md from logo.manifest.json and
syncs site-meta.json role paths. Consumer registry lives in logo.manifest.json.
"""

from __future__ import annotations

import math
import shutil
from pathlib import Path

from PIL import Image

from logo_registry import load_manifest, render_readme, sync_site_meta_logo_fields

SITE_ROOT = Path(__file__).resolve().parents[1]
LOGO_DIR = SITE_ROOT / "assets" / "mhws-logo"
MASTER = LOGO_DIR / "mhws-logo-official.png"
LOCKED = LOGO_DIR / "mhws-logo-official-locked-20260810.png"

# Soft cream plate for legacy favicons; navy matches manifest theme_color (#15233f).
ICON_BG = (246, 241, 230, 255)
NAVY_BG = (21, 35, 63, 255)
GOLD_RING = (201, 162, 39, 110)


def _strip_lower_crop_box(img: Image.Image) -> Image.Image:
    """Remove the leftover 1px U-shaped crop rectangle around the lower half of the seal.

    Archive masters carried a faint gray bounding box from midline to the bottom edge.
    It survives `_transparent_exterior` (it does not touch the corners) and becomes a
    hard hairline on cream paper / PDF after `_cert_seal` hardens alpha.
    """
    out = img.copy()
    px = out.load()
    w, h = out.size
    cx, cy = (w - 1) / 2.0, (h - 1) / 2.0
    seal_r = min(w, h) * 0.44
    min_col = max(24, int(h * 0.28))
    min_row = max(24, int(w * 0.45))

    def is_mark(x: int, y: int) -> bool:
        r, g, b, a = px[x, y]
        if a < 12:
            return False
        if math.hypot(x - cx, y - cy) < seal_r:
            return False
        return (max(r, g, b) - min(r, g, b)) <= 48

    cleared = 0
    for x in range(w):
        ys = [y for y in range(int(cy), h) if is_mark(x, y)]
        if len(ys) < min_col:
            continue
        for y in ys:
            px[x, y] = (0, 0, 0, 0)
            cleared += 1
        for dx in (-1, 1):
            nx = x + dx
            if 0 <= nx < w:
                for y in ys:
                    if is_mark(nx, y):
                        px[nx, y] = (0, 0, 0, 0)
                        cleared += 1

    for y in range(int(h * 0.82), h):
        xs = [x for x in range(w) if is_mark(x, y)]
        if len(xs) < min_row:
            continue
        for x in xs:
            px[x, y] = (0, 0, 0, 0)
            cleared += 1
        for dy in (-1, 1):
            ny = y + dy
            if 0 <= ny < h:
                for x in xs:
                    if is_mark(x, ny):
                        px[x, ny] = (0, 0, 0, 0)
                        cleared += 1

    if cleared:
        print(f"  stripped {cleared} crop-box pixels from {w}×{h} seal")
    return out


def _load_master() -> Image.Image:
    if not MASTER.is_file():
        raise FileNotFoundError(f"Master logo missing: {MASTER}")
    img = Image.open(MASTER).convert("RGBA")
    # Ensure true transparency outside the seal (no flat black matte / crop hairline).
    return _strip_lower_crop_box(img)


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


def _home_screen_icon(img: Image.Image, size: int, *, maskable: bool = False) -> Image.Image:
    """Navy themed app icon — larger seal; maskable keeps Android safe-zone padding."""
    from PIL import ImageDraw

    pad_ratio = 0.10 if maskable else 0.05
    plate = Image.new("RGBA", (size, size), NAVY_BG)
    ring_inset = max(2, int(size * 0.035))
    ring_width = max(1, size // 72)
    draw = ImageDraw.Draw(plate)
    draw.ellipse(
        (ring_inset, ring_inset, size - ring_inset - 1, size - ring_inset - 1),
        outline=GOLD_RING,
        width=ring_width,
    )
    mark = _fit(img, size, pad_ratio=pad_ratio)
    plate.alpha_composite(mark)
    return plate


def _watermark(img: Image.Image, size: int = 512, alpha: float = 0.13) -> Image.Image:
    """Coloured but faint watermark from the emblem centre (no outer text ring)."""
    from PIL import ImageChops, ImageDraw, ImageEnhance, ImageFilter

    # Crop away arched outer titles that read as a vertical text strip on the page.
    base = _fit(img, 1024, pad_ratio=0.02)
    w, h = base.size
    crop = 0.28
    core = base.crop((int(w * crop), int(h * crop), int(w * (1 - crop)), int(h * (1 - crop))))
    core = core.resize((size, size), Image.Resampling.LANCZOS)

    rgb = core.convert("RGB")
    rgb = ImageEnhance.Contrast(rgb).enhance(0.82)
    rgb = ImageEnhance.Brightness(rgb).enhance(1.22)
    rgb = ImageEnhance.Color(rgb).enhance(1.05)
    r, g, b = rgb.split()

    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    inset = max(1, int(size * 0.02))
    draw.ellipse((inset, inset, size - 1 - inset, size - 1 - inset), fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(radius=max(1, int(size * 0.02))))
    a = ImageChops.multiply(core.split()[3], mask).point(lambda v: int(v * alpha))
    return Image.merge("RGBA", (r, g, b, a))


def _save(img: Image.Image, path: Path, *, optimize: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, format="PNG", optimize=optimize, compress_level=9)
    kb = path.stat().st_size / 1024
    print(f"  wrote {path.relative_to(SITE_ROOT)} ({img.size[0]}×{img.size[1]}, {kb:.1f}KB)")


def _save_webp(img: Image.Image, path: Path, *, quality: int = 80) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, format="WEBP", quality=quality, method=6)
    kb = path.stat().st_size / 1024
    print(f"  wrote {path.relative_to(SITE_ROOT)} ({img.size[0]}×{img.size[1]}, {kb:.1f}KB webp)")


def _save_jpeg(img: Image.Image, path: Path, *, quality: int = 88, bg=(246, 241, 230)) -> None:
    rgb = Image.new("RGB", img.size, bg)
    rgb.paste(img, mask=img.split()[3] if img.mode == "RGBA" else None)
    path.parent.mkdir(parents=True, exist_ok=True)
    rgb.save(path, format="JPEG", quality=quality, optimize=True)
    kb = path.stat().st_size / 1024
    print(f"  wrote {path.relative_to(SITE_ROOT)} ({img.size[0]}×{img.size[1]}, {kb:.1f}KB jpeg)")


def export_all() -> None:
    master = _load_master()
    print(f"Locking master {MASTER.name} ({master.size[0]}×{master.size[1]})")
    shutil.copy2(MASTER, LOCKED)
    print(f"  locked → {LOCKED.relative_to(SITE_ROOT)}")

    # Keep full-res master for archive / regeneration only — do not ship it in UI or PDFs.
    _save(master, MASTER)  # re-save optimized

    def _harden_alpha(img: Image.Image) -> Image.Image:
        """Push soft downscale alpha toward opaque so PDF seals stay full-contrast."""
        r, g, b, a = img.split()

        def boost(v: int) -> int:
            if v <= 8:
                return 0
            if v >= 200:
                return 255
            return min(255, int(48 + (v - 8) * (207 / 192)))

        return Image.merge("RGBA", (r, g, b, a.point(boost)))

    def _cert_seal(img: Image.Image, size: int = 320) -> Image.Image:
        """Vivid certificate/PDF header seal — hard alpha + contrast/color punch."""
        from PIL import ImageEnhance

        base = _fit(img, size, pad_ratio=0.02)
        rgb = ImageEnhance.Contrast(base.convert("RGB")).enhance(1.28)
        rgb = ImageEnhance.Color(rgb).enhance(1.18)
        alpha = base.split()[3].point(lambda v: 255 if v >= 20 else 0)
        return Image.merge("RGBA", (*rgb.split(), alpha))

    # PDF / letterhead seals: prefer dedicated cert seal; keep print/pdf in sync.
    cert320 = _strip_lower_crop_box(_cert_seal(master, 320))
    print256 = _strip_lower_crop_box(_harden_alpha(_fit(master, 256, pad_ratio=0.02)))
    pdf256 = print256
    web512 = _fit(master, 512, pad_ratio=0.02)
    web256 = print256
    _save(cert320, LOGO_DIR / "mhws-logo-seal-cert.png")
    _save(pdf256, LOGO_DIR / "mhws-logo-pdf.png")
    # HTML pads/receipts use "print" — 256px is sharp at ~24mm and much lighter than 512.
    _save(print256, LOGO_DIR / "mhws-logo-print.png")
    _save(web512, LOGO_DIR / "mhws-logo-web-512.png")
    _save(web256, LOGO_DIR / "mhws-logo-web-256.png")
    _save_webp(web512, LOGO_DIR / "mhws-logo-web-512.webp", quality=80)
    _save_webp(web256, LOGO_DIR / "mhws-logo-web-256.webp", quality=80)
    _save(_fit(master, 128, pad_ratio=0.02), LOGO_DIR / "mhws-logo-icon-128.png")
    _save(_fit(master, 64, pad_ratio=0.02), LOGO_DIR / "mhws-logo-icon-64.png")
    # Coloured faint centre emblem (no outer text ring — avoids “vertical text” on the left).
    _save(_watermark(master, 512, alpha=0.11), LOGO_DIR / "mhws-logo-watermark.png")

    # Transparent mark used by legacy seal paths
    mark512 = _fit(master, 512, pad_ratio=0.04)
    _save(mark512, SITE_ROOT / "assets" / "hbcs-sanyard-seal-mark.png")
    _save(mark512, SITE_ROOT / "assets" / "hbcs-sanyard-seal.png")

    # PWA / favicon / apple-touch — navy themed plate, larger seal on home screen
    fav192 = _home_screen_icon(master, 192)
    _save(fav192, SITE_ROOT / "assets" / "favicon-192.png")
    _save_jpeg(fav192, SITE_ROOT / "assets" / "favicon-192.jpg", quality=90, bg=(21, 35, 63))

    for name, size in (
        ("apple-touch-icon.png", 180),
        ("apple-touch-icon-167.png", 167),
        ("apple-touch-icon-152.png", 152),
    ):
        icon = _home_screen_icon(master, size)
        _save(icon, SITE_ROOT / "assets" / name)
        if name == "apple-touch-icon.png":
            _save(icon, SITE_ROOT / "apple-touch-icon.png")

    seal512 = _home_screen_icon(master, 512)
    _save(seal512, SITE_ROOT / "assets" / "hbcs-sanyard-seal-512.png")
    _save_jpeg(seal512, SITE_ROOT / "assets" / "hbcs-sanyard-seal-512.jpg", quality=90, bg=(21, 35, 63))
    maskable = _home_screen_icon(master, 512, maskable=True)
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
