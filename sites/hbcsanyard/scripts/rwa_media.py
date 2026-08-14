"""Shared image trim/compress for news, ads, and marketplace cards."""

from __future__ import annotations

from io import BytesIO

UPLOAD_MAX_BYTES = 5 * 1024 * 1024
OUTPUT_TARGET_BYTES = 32 * 1024
ALLOWED_IMAGE_TYPES = frozenset({"image/jpeg", "image/png", "image/webp"})


def _load_rgb(raw: bytes):
    try:
        from PIL import Image
    except ImportError as exc:  # pragma: no cover
        raise ValueError("Image processing unavailable on server") from exc

    try:
        img = Image.open(BytesIO(raw))
        img.load()
    except Exception as exc:  # noqa: BLE001
        raise ValueError("Could not read image") from exc
    if img.mode not in ("RGB", "L"):
        if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
            rgba = img.convert("RGBA")
            background = Image.new("RGB", rgba.size, (255, 255, 255))
            background.paste(rgba, mask=rgba.split()[-1])
            return background
        return img.convert("RGB")
    if img.mode == "L":
        return img.convert("RGB")
    return img


def _resize(img, max_edge: int):
    from PIL import Image

    w, h = img.size
    edge = max(w, h)
    if edge <= max_edge:
        return img
    scale = max_edge / edge
    resample = Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS
    return img.resize((max(1, int(w * scale)), max(1, int(h * scale))), resample)


def _encode_webp(img, quality: int) -> bytes:
    buf = BytesIO()
    img.save(buf, format="WEBP", quality=quality, method=6)
    data = buf.getvalue()
    if not data:
        raise ValueError("Could not encode image")
    return data


def optimize_portal_card_image(raw: bytes) -> tuple[bytes, str]:
    """Accept a large phone photo; return a small WebP for fast card display."""
    img = _load_rgb(raw)
    for max_edge in (640, 512, 400):
        sized = _resize(img, max_edge)
        for quality in (68, 58, 48, 38, 30):
            data = _encode_webp(sized, quality)
            if len(data) <= OUTPUT_TARGET_BYTES:
                return data, "image/webp"
        if max_edge == 400:
            return data, "image/webp"
    raise ValueError("Could not compress image")
