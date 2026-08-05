"""Raster project logo optimization — master recompress + card/detail WebP variants."""

from __future__ import annotations

import pathlib

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    Image = None  # type: ignore[misc, assignment]

RASTER_EXT = {".png", ".jpg", ".jpeg", ".webp"}
SKIP_EXT = {".svg", ".gif", ".ico"}

# Display caps in site-utils.js: card ~54px / detail ~160px height; 2× retina.
VARIANTS = {
    "card": {"max_px": 256, "quality": 84},
    "detail": {"max_px": 560, "quality": 88},
}
MAX_MASTER_PX = 1024
MASTER_PNG_COMPRESS = 6


def variant_path(source: pathlib.Path, variant: str) -> pathlib.Path:
    return source.with_name(f"{source.stem}.{variant}.webp")


def _resample():
    if Image is None:
        return None
    return Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS


def resize_to_fit(img: Image.Image, max_px: int) -> Image.Image:
    w, h = img.size
    if w <= 0 or h <= 0:
        return img
    scale = min(max_px / w, max_px / h, 1.0)
    if scale >= 1.0:
        return img
    resample = _resample()
    new_w = max(1, round(w * scale))
    new_h = max(1, round(h * scale))
    return img.resize((new_w, new_h), resample)


def _prepare_rgba(img: Image.Image) -> Image.Image:
    if img.mode in ("RGB", "RGBA"):
        return img
    return img.convert("RGBA")


def _save_master(img: Image.Image, dest: pathlib.Path) -> None:
    ext = dest.suffix.lower()
    fitted = resize_to_fit(img, MAX_MASTER_PX)
    if ext == ".png":
        if fitted.mode == "RGBA":
            fitted.save(dest, format="PNG", optimize=True, compress_level=MASTER_PNG_COMPRESS)
        else:
            fitted.convert("RGB").save(dest, format="PNG", optimize=True, compress_level=MASTER_PNG_COMPRESS)
    elif ext in {".jpg", ".jpeg"}:
        fitted.convert("RGB").save(dest, format="JPEG", quality=88, optimize=True, progressive=True)
    elif ext == ".webp":
        fitted.save(dest, format="WEBP", quality=90, method=6)
    else:
        fitted.save(dest)


def _remove_stale_variants(source: pathlib.Path) -> None:
    """Drop WebP variants from a previous master filename (e.g. after logo.jpeg -> logo.png)."""
    parent = source.parent
    keep = {variant_path(source, v).resolve() for v in VARIANTS}
    for pattern in ("*.card.webp", "*.detail.webp"):
        for old in parent.glob(pattern):
            if old.resolve() not in keep:
                try:
                    old.unlink()
                except OSError:
                    pass


def optimize_logo_file(source: pathlib.Path, *, force: bool = True) -> dict:
    """Recompress the stored logo and emit card/detail WebP siblings."""
    source = source.resolve()
    result: dict = {"source": str(source), "variants": [], "optimized": False}
    if not source.is_file():
        result["error"] = "file not found"
        return result
    ext = source.suffix.lower()
    if ext in SKIP_EXT:
        result["skipped"] = "vector_or_gif"
        return result
    if ext not in RASTER_EXT:
        result["skipped"] = "unsupported"
        return result
    if Image is None:
        result["error"] = "Pillow not installed"
        return result

    bytes_before = source.stat().st_size
    try:
        with Image.open(source) as img:
            img.load()
            prepared = _prepare_rgba(img)
            _save_master(prepared, source)
            for variant, cfg in VARIANTS.items():
                dest = variant_path(source, variant)
                if dest.exists() and not force and dest.stat().st_mtime >= source.stat().st_mtime:
                    result["variants"].append({"path": str(dest), "skipped": True})
                    continue
                fitted = resize_to_fit(prepared, cfg["max_px"])
                dest.parent.mkdir(parents=True, exist_ok=True)
                fitted.save(dest, format="WEBP", quality=cfg["quality"], method=6)
                try:
                    dest.chmod(0o644)
                except OSError:
                    pass
                result["variants"].append({
                    "path": str(dest),
                    "bytes": dest.stat().st_size,
                    "width": fitted.size[0],
                    "height": fitted.size[1],
                })
        try:
            source.chmod(0o644)
        except OSError:
            pass
        _remove_stale_variants(source)
    except OSError as exc:
        result["error"] = str(exc)
        return result

    bytes_after = source.stat().st_size
    result["optimized"] = True
    result["bytes_before"] = bytes_before
    result["bytes_after"] = bytes_after
    result["saved"] = max(0, bytes_before - bytes_after)
    return result


def optimize_logo_paths(paths: list[pathlib.Path], *, force: bool = True) -> list[dict]:
    return [optimize_logo_file(path, force=force) for path in paths]
