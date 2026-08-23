#!/usr/bin/env python3
"""Regenerate mhws-logo-official.png — society hat on outer rim, archive ring preserved."""

from __future__ import annotations

import math
from collections import deque
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

SITE_ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = SITE_ROOT / "assets/mhws-logo/mhws-logo-official-archive-20260810.png"
OUT = SITE_ROOT / "assets/mhws-logo/mhws-logo-official.png"

SOCIETY_ARC = "MANDI HOUSING WELFARE SOCIETY"

NAVY = (4, 23, 62, 255)
NAVY_DEEP = (1, 10, 34, 255)
NAVY_MID = (10, 36, 82, 255)
NAVY_LIFT = (28, 62, 118, 255)
SHINE = (120, 165, 210, 255)
SHINE_SOFT = (70, 115, 170, 200)
GOLD = (201, 162, 39, 255)
GOLD_LIGHT = (235, 210, 130, 255)
GOLD_BRIGHT = (255, 236, 175, 255)
GOLD_EDGE = (255, 245, 200, 255)

INNER_SCENE_MAX_R = 272

# Gap between outermost gold ring body and extended outer hat rim.
# Canvas is padded so the hat can rise above the original seal fringe.
OUTERMOST_RING_R = 343.0
OUTER_RIM_R = 384.0
CANVAS_PAD = 20

# Rim LEDs (outward-facing). Skip only the top navy hat — bottom rim included.
LED_COUNT = 62
LED_RIM_R = 349.0
# atan2 degrees: top≈-90, right≈0, bottom≈+90, left≈±180
LED_TOP_SKIP = (-152.0, -28.0)
# Assorted diode colours — lens only; no coloured light wash thrown onto the rim.
LED_COLORS = (
    (255, 70, 70),    # red
    (70, 220, 90),    # green
    (70, 140, 255),   # blue
    (255, 200, 50),   # amber
    (255, 255, 245),  # white
    (255, 90, 200),   # magenta
    (60, 230, 230),   # cyan
    (255, 140, 50),   # orange
    (180, 100, 255),  # violet
    (140, 255, 80),   # lime
)

HAT_FONT_CANDIDATES = (
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Black.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Georgia Bold.ttf",
)


def _load_hat_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in HAT_FONT_CANDIDATES:
        p = Path(path)
        if p.is_file():
            font = ImageFont.truetype(str(p), size=size)
            font._hat_font_path = str(p)  # type: ignore[attr-defined]
            return font
    return ImageFont.load_default()


def _char_advance(font, ch: str) -> float:
    if hasattr(font, "getlength"):
        return max(1.0, float(font.getlength(ch)))
    bbox = font.getbbox(ch)
    return max(1.0, bbox[2] - bbox[0])


def _arc_text_metrics(text: str, font, radius: float, *, letter_spacing: float) -> tuple[float, list[float]]:
    widths = [_char_advance(font, c) for c in text]
    total = sum(widths) + letter_spacing * max(0, len(text) - 1)
    return math.degrees(total / radius), widths


def _clear_sector(
    img: Image.Image,
    *,
    center: tuple[float, float],
    mid_deg: float,
    span_deg: float,
    r_lo: float,
    r_hi: float,
) -> None:
    px = img.load()
    cx, cy = center
    a0 = mid_deg - span_deg / 2
    a1 = mid_deg + span_deg / 2
    for y in range(img.size[1]):
        for x in range(img.size[0]):
            dx, dy = x - cx, y - cy
            dist = math.hypot(dx, dy)
            if dist < r_lo or dist > r_hi:
                continue
            ang = math.degrees(math.atan2(dy, dx))
            if not (a0 < ang < a1):
                continue
            r, g, b, _ = px[x, y]
            px[x, y] = (r, g, b, 0)


def _paint_sector(
    img: Image.Image,
    *,
    center: tuple[float, float],
    mid_deg: float,
    span_deg: float,
    r_lo: float,
    r_hi: float,
    fill: tuple[int, int, int, int],
) -> None:
    px = img.load()
    cx, cy = center
    a0 = mid_deg - span_deg / 2
    a1 = mid_deg + span_deg / 2
    for y in range(img.size[1]):
        for x in range(img.size[0]):
            dx, dy = x - cx, y - cy
            dist = math.hypot(dx, dy)
            if dist < r_lo or dist > r_hi:
                continue
            ang = math.degrees(math.atan2(dy, dx))
            if not (a0 < ang < a1):
                continue
            px[x, y] = fill


def _font_height(font) -> float:
    asc, desc = font.getmetrics()
    return float(asc + desc)


def _blend_pixel(
    dest_px,
    x: int,
    y: int,
    w: int,
    h: int,
    src: tuple[int, int, int, int],
    cover: float,
) -> None:
    if cover <= 0.02 or not (0 <= x < w and 0 <= y < h):
        return
    a = int(src[3] * cover)
    if a < 1:
        return
    r0, g0, b0, a0 = dest_px[x, y]
    if a0 == 0:
        dest_px[x, y] = (src[0], src[1], src[2], a)
        return
    u = a / 255.0
    dest_px[x, y] = (
        int(r0 * (1 - u) + src[0] * u),
        int(g0 * (1 - u) + src[1] * u),
        int(b0 * (1 - u) + src[2] * u),
        max(a0, a),
    )


def _blit_spoke_glyph(
    dest: Image.Image,
    tile: Image.Image,
    *,
    center: tuple[float, float],
    radius: float,
    mid_ang: float,
    anchor_xy: tuple[float, float],
) -> None:
    """Map upright glyph → polar: +Y_up along radial out, +X along tangent (true spokes)."""
    cx, cy = center
    ax, ay = anchor_xy
    rad = math.radians(mid_ang)
    ux, uy = math.cos(rad), math.sin(rad)  # radial out
    tx, ty = -math.sin(rad), math.cos(rad)  # tangential CCW
    dp = dest.load()
    tp = tile.load()
    tw, th = tile.size
    dw, dh = dest.size
    for y in range(th):
        for x in range(tw):
            src = tp[x, y]
            if src[3] < 8:
                continue
            # local: +x right, +y up (image y grows down)
            lx = x - ax
            ly = -(y - ay)
            sx = cx + (radius + ly) * ux + lx * tx
            sy = cy + (radius + ly) * uy + lx * ty
            x0 = math.floor(sx)
            y0 = math.floor(sy)
            fx = sx - x0
            fy = sy - y0
            _blend_pixel(dp, x0, y0, dw, dh, src, (1 - fx) * (1 - fy))
            _blend_pixel(dp, x0 + 1, y0, dw, dh, src, fx * (1 - fy))
            _blend_pixel(dp, x0, y0 + 1, dw, dh, src, (1 - fx) * fy)
            _blend_pixel(dp, x0 + 1, y0 + 1, dw, dh, src, fx * fy)


def draw_arc_text_radial(
    base: Image.Image,
    text: str,
    *,
    center: tuple[float, float],
    radius: float,
    mid_deg: float,
    font,
    fill,
    stroke_fill=None,
    stroke_width: int = 1,
    letter_spacing: float = 0.8,
) -> float:
    """Place each letter as a wheel spoke: stem along radius, like HOUSING COLONY SANYARD."""
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    total_deg, widths = _arc_text_metrics(text, font, radius, letter_spacing=letter_spacing)
    spacing_deg = math.degrees(letter_spacing / radius)
    angle = mid_deg - total_deg / 2
    # Centre on the arc so stems read as spokes through the band.
    anchor = "mm"

    for ch, w in zip(text, widths):
        char_deg = math.degrees(w / radius)
        mid_ang = angle + char_deg / 2.0

        bbox = font.getbbox(ch)
        char_w = max(w, bbox[2] - bbox[0])
        char_h = max(1.0, bbox[3] - bbox[1])
        pad = int(math.ceil(math.hypot(char_w, char_h) * 1.6)) + stroke_width * 6 + 24
        tile = Image.new("RGBA", (pad * 2, pad * 2), (0, 0, 0, 0))
        draw = ImageDraw.Draw(tile)
        ax = ay = float(pad)

        # Soft bevel in glyph space (no pre-rotate slip).
        draw.text((ax, ay + 1), ch, font=font, fill=(0, 0, 0, 200), anchor=anchor)
        draw.text((ax, ay - 1), ch, font=font, fill=GOLD_EDGE, anchor=anchor)

        if stroke_fill and stroke_width:
            for dx in range(-stroke_width, stroke_width + 1):
                for dy in range(-stroke_width, stroke_width + 1):
                    if dx * dx + dy * dy <= stroke_width * stroke_width + 1:
                        draw.text((ax + dx, ay + dy), ch, font=font, fill=stroke_fill, anchor=anchor)
        draw.text((ax, ay), ch, font=font, fill=fill, anchor=anchor)

        _blit_spoke_glyph(
            layer,
            tile,
            center=center,
            radius=radius,
            mid_ang=mid_ang,
            anchor_xy=(ax, ay),
        )
        angle += char_deg + spacing_deg

    base.alpha_composite(layer)
    return total_deg


def _band_polygon_points(
    cx: float,
    cy: float,
    *,
    mid_deg: float,
    span_deg: float,
    r_outer: float,
    r_inner: float,
) -> list[tuple[float, float]]:
    start = mid_deg - span_deg / 2
    end = mid_deg + span_deg / 2
    steps = max(120, int(span_deg * 4))
    outer: list[tuple[float, float]] = []
    inner: list[tuple[float, float]] = []
    for i in range(steps + 1):
        deg = start + (end - start) * i / steps
        rad = math.radians(deg)
        outer.append((cx + r_outer * math.cos(rad), cy + r_outer * math.sin(rad)))
    for i in range(steps, -1, -1):
        deg = start + (end - start) * i / steps
        rad = math.radians(deg)
        inner.append((cx + r_inner * math.cos(rad), cy + r_inner * math.sin(rad)))
    return outer + inner


def _lerp_rgba(
    a: tuple[int, int, int, int],
    b: tuple[int, int, int, int],
    t: float,
) -> tuple[int, int, int, int]:
    t = max(0.0, min(1.0, t))
    return (
        int(a[0] + (b[0] - a[0]) * t),
        int(a[1] + (b[1] - a[1]) * t),
        int(a[2] + (b[2] - a[2]) * t),
        int(a[3] + (b[3] - a[3]) * t),
    )


def _band_color(t: float, *, shine_boost: float = 0.0) -> tuple[int, int, int, int]:
    """Radial bevel: deep inner → mid navy → bright outer shine → dark lip."""
    if t < 0.18:
        c = _lerp_rgba(NAVY_DEEP, NAVY, t / 0.18)
    elif t < 0.45:
        c = _lerp_rgba(NAVY, NAVY_MID, (t - 0.18) / 0.27)
    elif t < 0.70:
        c = _lerp_rgba(NAVY_MID, NAVY_LIFT, (t - 0.45) / 0.25)
    elif t < 0.88:
        c = _lerp_rgba(NAVY_LIFT, SHINE, (t - 0.70) / 0.18)
    else:
        c = _lerp_rgba(SHINE, NAVY_DEEP, (t - 0.88) / 0.12)

    if shine_boost > 0:
        c = _lerp_rgba(c, GOLD_EDGE, shine_boost * 0.25)
        c = _lerp_rgba(c, SHINE, shine_boost * 0.65)
    return c


def _draw_hat_band(
    base: Image.Image,
    *,
    center: tuple[float, float],
    mid_deg: float,
    span_deg: float,
    r_inner: float,
    r_outer: float,
) -> None:
    """3D navy band: shine + closed gold perimeter (arcs + radial ends, no overhang)."""
    cx, cy = center
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    px = layer.load()
    a0 = mid_deg - span_deg / 2
    a1 = mid_deg + span_deg / 2
    band_h = max(1.0, r_outer - r_inner)
    shine_r = r_inner + band_h * 0.66
    shine_r2 = r_inner + band_h * 0.80

    for y in range(base.size[1]):
        for x in range(base.size[0]):
            dx, dy = x - cx, y - cy
            dist = math.hypot(dx, dy)
            if dist < r_inner or dist > r_outer:
                continue
            ang = math.degrees(math.atan2(dy, dx))
            if not (a0 <= ang <= a1):
                continue
            t = (dist - r_inner) / band_h
            shine = 0.75 * math.exp(-((dist - shine_r) / (band_h * 0.14)) ** 2)
            shine += 0.50 * math.exp(-((dist - shine_r2) / (band_h * 0.10)) ** 2)
            along = 0.28 + 0.22 * math.exp(-((ang - mid_deg) / (span_deg * 0.60)) ** 2)
            color = _band_color(t, shine_boost=min(1.0, shine * (0.70 + along)))
            px[x, y] = color

    draw = ImageDraw.Draw(layer)
    steps = max(220, int(span_deg * 8))

    def arc_pts(radius: float, start: float, end: float) -> list[tuple[float, float]]:
        pts = []
        for i in range(steps + 1):
            deg = start + (end - start) * i / steps
            rad = math.radians(deg)
            pts.append((cx + radius * math.cos(rad), cy + radius * math.sin(rad)))
        return pts

    # Closed perimeter: outer arc → right end → inner arc → left end.
    perimeter = (
        arc_pts(r_outer, a0, a1)
        + arc_pts(r_inner, a1, a0)[1:]
    )
    # Gold lining = exact band outline (ends included).
    draw.line(perimeter + [perimeter[0]], fill=GOLD, width=5, joint="curve")
    draw.line(
        arc_pts(r_outer - 2.2, a0, a1)
        + arc_pts(r_inner + 2.2, a1, a0)[1:]
        + [arc_pts(r_outer - 2.2, a0, a1)[0]],
        fill=GOLD_LIGHT,
        width=3,
        joint="curve",
    )
    draw.line(
        arc_pts(r_outer - 3.6, a0, a1)
        + arc_pts(r_inner + 3.6, a1, a0)[1:]
        + [arc_pts(r_outer - 3.6, a0, a1)[0]],
        fill=GOLD_EDGE,
        width=2,
        joint="curve",
    )

    # Specular streaks across the full angular span (tip to tip).
    draw.line(arc_pts(shine_r, a0, a1), fill=(175, 215, 245, 125), width=3)
    draw.line(arc_pts(shine_r2, a0, a1), fill=(255, 244, 200, 110), width=2)

    base.alpha_composite(layer)


def _angle_in_skip(ang: float, lo: float, hi: float) -> bool:
    """True if ang is inside [lo, hi] on the circle (handles wrap)."""
    ang = (ang + 180.0) % 360.0 - 180.0
    lo = (lo + 180.0) % 360.0 - 180.0
    hi = (hi + 180.0) % 360.0 - 180.0
    if lo <= hi:
        return lo <= ang <= hi
    return ang >= lo or ang <= hi


def _rim_led_angles(count: int = LED_COUNT) -> list[float]:
    """Evenly space LEDs all around the rim except the top navy hat."""
    # One continuous arc: just after hat (right) → bottom → left → just before hat.
    a0 = LED_TOP_SKIP[1]
    a1 = LED_TOP_SKIP[0] + 360.0
    if count <= 0 or a1 <= a0:
        return []
    out: list[float] = []
    for i in range(count):
        t = (i + 0.5) / count  # inset from hat tips
        ang = a0 + (a1 - a0) * t
        out.append(((ang + 180.0) % 360.0) - 180.0)
    return out


def _draw_rim_leds(
    base: Image.Image,
    *,
    center: tuple[float, float],
    count: int = LED_COUNT,
    rim_r: float = LED_RIM_R,
) -> None:
    """62 large assorted LEDs on the gold rim — coloured lenses only, no light throw."""
    cx, cy = center
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    angles = _rim_led_angles(count)

    for i, ang in enumerate(angles):
        rad = math.radians(ang)
        ux, uy = math.cos(rad), math.sin(rad)
        px = cx + rim_r * ux
        py = cy + rim_r * uy
        cr, cg, cb = LED_COLORS[i % len(LED_COLORS)]

        # Large gold bezel cup (no coloured halo / ray)
        draw.ellipse((px - 8.0, py - 8.0, px + 8.0, py + 8.0), fill=(140, 105, 28, 255))
        draw.ellipse((px - 7.0, py - 7.0, px + 7.0, py + 7.0), fill=(215, 170, 55, 255))
        draw.ellipse((px - 5.8, py - 5.8, px + 5.8, py + 5.8), fill=(90, 70, 20, 255))
        # Coloured LED lens only
        draw.ellipse((px - 4.8, py - 4.8, px + 4.8, py + 4.8), fill=(cr, cg, cb, 255))
        draw.ellipse(
            (px - 3.0, py - 3.0, px + 3.0, py + 3.0),
            fill=(min(255, cr + 55), min(255, cg + 55), min(255, cb + 55), 255),
        )
        draw.ellipse((px - 1.8, py - 2.4, px + 0.4, py - 0.2), fill=(255, 255, 255, 235))

    base.alpha_composite(layer)


def _restore_inner_scene(img: Image.Image, archive: Image.Image) -> None:
    px = img.load()
    pa = archive.load()
    w, h = img.size
    cx, cy = w / 2, h / 2
    for y in range(h):
        for x in range(w):
            if math.hypot(x - cx, y - cy) < INNER_SCENE_MAX_R:
                px[x, y] = pa[x, y]


def _restore_ring_sector(
    img: Image.Image,
    archive: Image.Image,
    *,
    lo_deg: float,
    hi_deg: float,
    r_lo: float,
    r_hi: float,
) -> None:
    px = img.load()
    pa = archive.load()
    w, h = img.size
    cx, cy = w / 2, h / 2
    for y in range(h):
        for x in range(w):
            dx, dy = x - cx, y - cy
            dist = math.hypot(dx, dy)
            if dist < r_lo or dist > r_hi:
                continue
            ang = math.degrees(math.atan2(dy, dx))
            if lo_deg < ang < hi_deg:
                px[x, y] = pa[x, y]


def _strip_top_light_rim(img: Image.Image, *, center: tuple[float, float], min_dist: float) -> None:
    px = img.load()
    w, h = img.size
    cx, cy = center
    for y in range(int(cy)):
        for x in range(w):
            dx, dy = x - cx, y - cy
            if dy >= 0:
                continue
            if math.hypot(dx, dy) < min_dist:
                continue
            r, g, b, a = px[x, y]
            if a and r > 130 and g > 125 and b > 115:
                px[x, y] = (r, g, b, 0)


def _draw_society_hat(
    base: Image.Image,
    *,
    center: tuple[float, float],
    mid_deg: float,
    font,
) -> None:
    """Taller navy hat from outermost gold ring to extended outer rim."""
    r_inner = OUTERMOST_RING_R
    r_outer = OUTER_RIM_R
    # Glyph centres on mid-band; stems run as spokes between the gold linings.
    text_radius = (r_inner + r_outer) * 0.5
    letter_spacing = 0.55

    text_span, _ = _arc_text_metrics(SOCIETY_ARC, font, text_radius, letter_spacing=letter_spacing)
    # Lining, shine, and end-caps share this exact span — no navy overhang.
    band_span = text_span + 9.0

    _paint_sector(
        base,
        center=center,
        mid_deg=mid_deg,
        span_deg=band_span,
        r_lo=r_inner,
        r_hi=r_outer,
        fill=NAVY_DEEP,
    )

    _draw_hat_band(
        base,
        center=center,
        mid_deg=mid_deg,
        span_deg=band_span,
        r_inner=r_inner,
        r_outer=r_outer,
    )

    # Gold face + deep navy outline (readable on navy band; stems match HOUSING stance).
    draw_arc_text_radial(
        base,
        SOCIETY_ARC,
        center=center,
        radius=text_radius,
        mid_deg=mid_deg,
        font=font,
        fill=GOLD_BRIGHT,
        stroke_fill=(2, 10, 36, 255),
        stroke_width=3,
        letter_spacing=letter_spacing,
    )

    _strip_top_light_rim(base, center=center, min_dist=r_outer)
    _finalize_hat_edges(
        base,
        center=center,
        mid_deg=mid_deg,
        span_deg=band_span,
        r_inner=r_inner,
        r_outer=r_outer,
    )


def _finalize_hat_edges(
    base: Image.Image,
    *,
    center: tuple[float, float],
    mid_deg: float,
    span_deg: float,
    r_inner: float,
    r_outer: float,
) -> None:
    """Hard-clip hat to band span; keep gold lining / navy / shine; kill overhang."""
    px = base.load()
    w, h = base.size
    cx, cy = center
    a0 = mid_deg - span_deg / 2
    a1 = mid_deg + span_deg / 2

    def is_gold_ink(r: int, g: int, b: int, a: int) -> bool:
        return a > 80 and r > 140 and g > 110 and (r + g) > (b + 80)

    def is_navy_ink(r: int, g: int, b: int, a: int) -> bool:
        return a > 80 and r < 80 and g < 120 and b > 35

    def is_shine_ink(r: int, g: int, b: int, a: int) -> bool:
        return a > 60 and b > 100 and g > 70 and r < 180 and b >= r - 20

    for y in range(h):
        for x in range(w):
            dx, dy = x - cx, y - cy
            if dy >= 0:
                continue
            dist = math.hypot(dx, dy)
            if dist < r_inner - 3 or dist > r_outer + 3:
                # Only strip stray hat fringe above the outer rim near the crown.
                if dist > r_outer + 0.5:
                    r, g, b, a = px[x, y]
                    if a and not is_gold_ink(r, g, b, a):
                        # Outside the sealed band: no navy overhang past the rim.
                        if is_navy_ink(r, g, b, a) or is_shine_ink(r, g, b, a):
                            px[x, y] = (r, g, b, 0)
                continue

            ang = math.degrees(math.atan2(dy, dx))
            r, g, b, a = px[x, y]
            if a == 0:
                continue

            # Outside angular span: remove hat navy/shine so tips don't outrun lining.
            if ang < a0 - 0.15 or ang > a1 + 0.15:
                if dist >= r_inner - 1 and is_navy_ink(r, g, b, a):
                    px[x, y] = (r, g, b, 0)
                continue

            if dist > r_outer + 0.25:
                if not is_gold_ink(r, g, b, a):
                    px[x, y] = (r, g, b, 0)
                continue

            if dist >= r_inner - 2:
                if is_gold_ink(r, g, b, a) or is_navy_ink(r, g, b, a) or is_shine_ink(r, g, b, a):
                    continue
                px[x, y] = NAVY if dist <= r_outer else (r, g, b, 0)


def _transparent_exterior(img: Image.Image) -> None:
    px = img.load()
    w, h = img.size
    cx, cy = w / 2, h / 2

    def is_bg(r: int, g: int, b: int) -> bool:
        if r < 28 and g < 28 and b < 28:
            return True
        if r > 228 and g > 223 and b > 208:
            return True
        if abs(r - g) < 12 and abs(g - b) < 18 and r > 210:
            return True
        return False

    def is_logo_ink(r: int, g: int, b: int) -> bool:
        if r < 35 and g < 45 and b > 45:
            return True
        if r > 170 and g > 130 and b < 120:
            return True
        if r > 230 and g > 210 and b > 120:
            return True
        return False

    seen = [[False] * w for _ in range(h)]
    q = deque()
    for x, y in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
        q.append((x, y))
        seen[y][x] = True
    while q:
        x, y = q.popleft()
        r, g, b, a = px[x, y]
        if a == 0:
            continue
        if is_logo_ink(r, g, b):
            continue
        dx, dy = x - cx, y - cy
        if math.hypot(dx, dy) > 368 and is_bg(r, g, b):
            px[x, y] = (r, g, b, 0)
        elif is_bg(r, g, b) and math.hypot(dx, dy) > 355:
            px[x, y] = (r, g, b, 0)
            for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if 0 <= nx < w and 0 <= ny < h and not seen[ny][nx]:
                    seen[ny][nx] = True
                    q.append((nx, ny))


def regenerate(source: Path | None = None) -> Path:
    src = source or ARCHIVE
    if not src.is_file():
        raise FileNotFoundError(f"Logo archive missing: {src}")
    archive = Image.open(src).convert("RGBA")
    # Pad canvas so the hat can rise above the original seal fringe
    pad = CANVAS_PAD
    img = Image.new("RGBA", (archive.size[0] + pad * 2, archive.size[1] + pad * 2), (0, 0, 0, 0))
    img.paste(archive, (pad, pad))
    archive_padded = img.copy()

    # Shifted centre after padding
    cx = archive.size[0] / 2 + pad
    cy = archive.size[1] / 2 + pad

    # Restore using padded archive reference for absolute coords
    _restore_inner_scene_at(img, archive_padded, center=(cx, cy))
    _restore_ring_sector_at(img, archive_padded, center=(cx, cy), lo_deg=-158, hi_deg=-22, r_lo=274, r_hi=326)

    _transparent_exterior_at(img, center=(cx, cy))
    _strip_top_light_rim(img, center=(cx, cy), min_dist=352)

    # Bold caps sized for spoke stance in the hat band.
    society_font = _load_hat_font(32)
    _draw_society_hat(img, center=(cx, cy), mid_deg=-90.0, font=society_font)

    # Rim LEDs after the hat so top skip stays clear of the navy band.
    _draw_rim_leds(img, center=(cx, cy))

    from export_logo_variants import _strip_lower_crop_box

    img = _strip_lower_crop_box(img)
    img.save(OUT, optimize=True)
    return OUT


def _restore_inner_scene_at(img: Image.Image, archive: Image.Image, *, center: tuple[float, float]) -> None:
    px = img.load()
    pa = archive.load()
    w, h = img.size
    cx, cy = center
    for y in range(h):
        for x in range(w):
            if math.hypot(x - cx, y - cy) < INNER_SCENE_MAX_R:
                px[x, y] = pa[x, y]


def _restore_ring_sector_at(
    img: Image.Image,
    archive: Image.Image,
    *,
    center: tuple[float, float],
    lo_deg: float,
    hi_deg: float,
    r_lo: float,
    r_hi: float,
) -> None:
    px = img.load()
    pa = archive.load()
    w, h = img.size
    cx, cy = center
    for y in range(h):
        for x in range(w):
            dx, dy = x - cx, y - cy
            dist = math.hypot(dx, dy)
            if dist < r_lo or dist > r_hi:
                continue
            ang = math.degrees(math.atan2(dy, dx))
            if lo_deg < ang < hi_deg:
                px[x, y] = pa[x, y]


def _transparent_exterior_at(img: Image.Image, *, center: tuple[float, float]) -> None:
    px = img.load()
    w, h = img.size
    cx, cy = center

    def is_bg(r: int, g: int, b: int) -> bool:
        if r < 28 and g < 28 and b < 28:
            return True
        if r > 228 and g > 223 and b > 208:
            return True
        if abs(r - g) < 12 and abs(g - b) < 18 and r > 210:
            return True
        return False

    def is_logo_ink(r: int, g: int, b: int) -> bool:
        if r < 35 and g < 45 and b > 45:
            return True
        if r > 170 and g > 130 and b < 120:
            return True
        if r > 230 and g > 210 and b > 120:
            return True
        return False

    seen = [[False] * w for _ in range(h)]
    q = deque()
    for x, y in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
        q.append((x, y))
        seen[y][x] = True
    while q:
        x, y = q.popleft()
        r, g, b, a = px[x, y]
        if a == 0:
            continue
        if is_logo_ink(r, g, b):
            continue
        dx, dy = x - cx, y - cy
        if math.hypot(dx, dy) > 368 and is_bg(r, g, b):
            px[x, y] = (r, g, b, 0)
        elif is_bg(r, g, b) and math.hypot(dx, dy) > 355:
            px[x, y] = (r, g, b, 0)
            for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if 0 <= nx < w and 0 <= ny < h and not seen[ny][nx]:
                    seen[ny][nx] = True
                    q.append((nx, ny))


if __name__ == "__main__":
    print(f"Wrote {regenerate()}")
