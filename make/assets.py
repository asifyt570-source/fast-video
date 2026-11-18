"""
Asset factory — all graphics that contain NO Bengali text.

Text is rendered by FFmpeg's drawtext (it has HarfBuzz, so Bengali shaping is
correct). Pillow here only draws geometry: backdrops, panels, icons, clock face,
map pin, glow. Everything is generated once and cached by content hash.
"""

from __future__ import annotations

import hashlib
import math
import os
from pathlib import Path

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
FONT_DIR = ROOT / "assets" / "fonts"
CACHE = ROOT / "build" / "assets"

# ── Design tokens ───────────────────────────────────────────────────────────
INK = (7, 11, 24)
INK2 = (13, 20, 42)
CYAN = (34, 211, 238)
AMBER = (251, 191, 36)
MAGENTA = (244, 114, 182)
MINT = (52, 211, 153)
VIOLET = (139, 92, 246)
WHITE = (248, 250, 252)
MUTED = (148, 163, 184)

ACCENTS = {
    "cyan": CYAN,
    "amber": AMBER,
    "magenta": MAGENTA,
    "mint": MINT,
    "violet": VIOLET,
    "white": WHITE,
}

FONTS = {
    "reg": FONT_DIR / "NotoSansBengali-Regular.ttf",
    "semi": FONT_DIR / "NotoSansBengali-SemiBold.ttf",
    "bold": FONT_DIR / "NotoSansBengali-Bold.ttf",
    "display": FONT_DIR / "Anton-Regular.ttf",
}


def q(path: Path) -> str:
    """Path safe for an ffmpeg filter argument."""
    return str(path).replace("\\", "/").replace(":", "\\:")


def _cache(name: str) -> Path:
    CACHE.mkdir(parents=True, exist_ok=True)
    return CACHE / name


# ── Backdrop ────────────────────────────────────────────────────────────────
def backdrop(w: int, h: int, mood: str = "night") -> Path:
    """Layered gradient backdrop: vertical gradient + two colour glows + grid + grain."""
    out = _cache(f"bg_{mood}_{w}x{h}.png")
    if out.exists():
        return out

    palettes = {
        "night": ((4, 7, 18), (12, 20, 44), (CYAN, 0.075), (VIOLET, 0.060)),
        "dark": ((2, 3, 8), (7, 9, 20), (CYAN, 0.035), (MAGENTA, 0.030)),
        "warm": ((17, 6, 15), (40, 12, 24), (MAGENTA, 0.085), (AMBER, 0.055)),
        "cool": ((3, 8, 14), (8, 24, 32), (MINT, 0.070), (CYAN, 0.065)),
        "alert": ((16, 3, 9), (36, 7, 16), (MAGENTA, 0.090), (AMBER, 0.045)),
    }
    top, bot, (c1, a1), (c2, a2) = palettes.get(mood, palettes["night"])

    ys = np.linspace(0.0, 1.0, h, dtype=np.float32)[:, None]
    ramp = ys ** 0.85
    img = np.zeros((h, w, 3), dtype=np.float32)
    for i in range(3):
        img[..., i] = top[i] + (bot[i] - top[i]) * ramp

    def glow(cx: float, cy: float, radius: float, rgb, strength: float):
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        d = np.sqrt((xx - cx * w) ** 2 + (yy - cy * h) ** 2) / (radius * max(w, h))
        m = np.clip(1.0 - d, 0.0, 1.0) ** 2.2 * strength
        for i in range(3):
            img[..., i] += rgb[i] * m

    glow(0.18, 0.12, 0.75, c1, a1 * 1.5)
    glow(0.86, 0.82, 0.70, c2, a2 * 1.5)
    glow(0.5, 0.5, 1.1, c1, 0.030)

    # grid
    step = max(48, int(min(w, h) / 16))
    gy, gx = np.mgrid[0:h, 0:w]
    lines = ((gx % step) < 1) | ((gy % step) < 1)
    img[lines] += 18.0

    # grain (also breaks up gradient banding)
    rng = np.random.default_rng(7)
    img += rng.normal(0.0, 3.2, (h, w, 1)).astype(np.float32)

    im = Image.fromarray(np.clip(img, 0, 255).astype(np.uint8), "RGB")

    # vignette
    vg = Image.new("L", (w, h), 0)
    dv = ImageDraw.Draw(vg)
    dv.ellipse((-w * 0.25, -h * 0.25, w * 1.25, h * 1.25), fill=255)
    vg = vg.filter(ImageFilter.GaussianBlur(min(w, h) / 12))
    black = Image.new("RGB", (w, h), (0, 0, 0))
    im = Image.composite(im, Image.blend(im, black, 0.62), vg)

    im.save(out)
    return out


# ── Glow blob (for lens flares / light pools) ───────────────────────────────
def glow(colour: str, size: int = 720) -> Path:
    out = _cache(f"glow_{colour}_{size}.png")
    if out.exists():
        return out
    rgb = ACCENTS.get(colour, CYAN)
    n = 256
    yy, xx = np.mgrid[0:n, 0:n].astype(np.float32)
    d = np.sqrt((xx - n / 2) ** 2 + (yy - n / 2) ** 2) / (n / 2)
    a = np.clip(1.0 - d, 0, 1) ** 2.6
    im = np.zeros((n, n, 4), dtype=np.uint8)
    im[..., 0], im[..., 1], im[..., 2] = rgb
    im[..., 3] = (a * 255).astype(np.uint8)
    Image.fromarray(im, "RGBA").resize((size, size), Image.LANCZOS).save(out)
    return out


# ── Panels ──────────────────────────────────────────────────────────────────
def panel(w: int, h: int, colour: str = "ink", alpha: int = 210, radius: int = 28,
          border: str | None = None) -> Path:
    key = hashlib.md5(f"{w}{h}{colour}{alpha}{radius}{border}".encode()).hexdigest()[:10]
    out = _cache(f"panel_{key}.png")
    if out.exists():
        return out
    rgb = {"ink": (12, 18, 36), "deep": (6, 9, 20), "white": WHITE,
           "cyan": CYAN, "amber": AMBER, "magenta": MAGENTA,
           "mint": MINT, "violet": VIOLET}.get(colour, (12, 18, 36))
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((0, 0, w - 1, h - 1), radius=radius, fill=(*rgb, alpha))
    if border:
        b = ACCENTS.get(border, CYAN)
        d.rounded_rectangle((1, 1, w - 2, h - 2), radius=radius,
                            outline=(*b, 255), width=max(2, w // 300))
    im.save(out)
    return out


# ── Icons (white geometry, then tinted) ─────────────────────────────────────
def _icon_mask(name: str, s: int = 256) -> Image.Image:
    im = Image.new("L", (s, s), 0)
    d = ImageDraw.Draw(im)
    c = s / 2
    u = s / 100.0

    if name == "bolt":
        d.polygon([(58 * u, 6 * u), (24 * u, 56 * u), (46 * u, 56 * u),
                   (40 * u, 94 * u), (76 * u, 42 * u), (52 * u, 42 * u)], fill=255)
    elif name == "moon":
        d.ellipse((18 * u, 10 * u, 86 * u, 78 * u), fill=255)
        d.ellipse((34 * u, 2 * u, 102 * u, 70 * u), fill=0)
    elif name == "sun":
        d.ellipse((30 * u, 30 * u, 70 * u, 70 * u), fill=255)
        for k in range(8):
            a = math.radians(k * 45)
            d.line([(c + math.cos(a) * 42 * u, c + math.sin(a) * 42 * u),
                    (c + math.cos(a) * 54 * u, c + math.sin(a) * 54 * u)],
                   fill=255, width=int(6 * u))
    elif name == "laptop":
        d.rounded_rectangle((20 * u, 22 * u, 80 * u, 66 * u), radius=6 * u, fill=255)
        d.rounded_rectangle((28 * u, 30 * u, 72 * u, 58 * u), radius=3 * u, fill=0)
        d.polygon([(10 * u, 74 * u), (90 * u, 74 * u), (82 * u, 84 * u), (18 * u, 84 * u)], fill=255)
    elif name == "phone":
        d.rounded_rectangle((32 * u, 8 * u, 68 * u, 92 * u), radius=10 * u, fill=255)
        d.rounded_rectangle((37 * u, 16 * u, 63 * u, 78 * u), radius=3 * u, fill=0)
        d.ellipse((46 * u, 82 * u, 54 * u, 90 * u), fill=0)
    elif name == "clock":
        d.ellipse((10 * u, 10 * u, 90 * u, 90 * u), fill=255)
        d.ellipse((16 * u, 16 * u, 84 * u, 84 * u), fill=0)
        d.line([(c, c), (c, 32 * u)], fill=255, width=int(7 * u))
        d.line([(c, c), (68 * u, c + 10 * u)], fill=255, width=int(7 * u))
    elif name == "chart":
        for i, hgt in enumerate((34, 52, 44, 72)):
            x0 = (18 + i * 18) * u
            d.rounded_rectangle((x0, (92 - hgt) * u, x0 + 11 * u, 92 * u), radius=3 * u, fill=255)
        d.line([(14 * u, 94 * u), (88 * u, 94 * u)], fill=255, width=int(4 * u))
    elif name == "trend":
        pts = [(12 * u, 76 * u), (34 * u, 52 * u), (52 * u, 62 * u), (84 * u, 22 * u)]
        d.line(pts, fill=255, width=int(9 * u), joint="curve")
        d.polygon([(84 * u, 22 * u), (66 * u, 18 * u), (86 * u, 40 * u)], fill=255)
    elif name == "globe":
        d.ellipse((10 * u, 10 * u, 90 * u, 90 * u), outline=255, width=int(7 * u))
        d.ellipse((34 * u, 10 * u, 66 * u, 90 * u), outline=255, width=int(5 * u))
        d.line([(10 * u, c), (90 * u, c)], fill=255, width=int(5 * u))
        d.line([(16 * u, 36 * u), (84 * u, 36 * u)], fill=255, width=int(4 * u))
        d.line([(16 * u, 64 * u), (84 * u, 64 * u)], fill=255, width=int(4 * u))
    elif name == "star":
        pts = []
        for k in range(10):
            r = 46 if k % 2 == 0 else 19
            a = math.radians(-90 + k * 36)
            pts.append((c + math.cos(a) * r * u, c + math.sin(a) * r * u))
        d.polygon(pts, fill=255)
    elif name == "heart":
        d.ellipse((14 * u, 20 * u, 54 * u, 62 * u), fill=255)
        d.ellipse((46 * u, 20 * u, 86 * u, 62 * u), fill=255)
        d.polygon([(14 * u, 44 * u), (86 * u, 44 * u), (50 * u, 90 * u)], fill=255)
    elif name == "check":
        d.line([(20 * u, 52 * u), (42 * u, 74 * u), (82 * u, 28 * u)],
               fill=255, width=int(12 * u), joint="curve")
    elif name == "pin":
        d.ellipse((26 * u, 8 * u, 74 * u, 56 * u), fill=255)
        d.polygon([(34 * u, 44 * u), (66 * u, 44 * u), (50 * u, 88 * u)], fill=255)
        d.ellipse((40 * u, 22 * u, 60 * u, 42 * u), fill=0)
    elif name == "target":
        for r in (44, 28, 12):
            d.ellipse((c - r * u, c - r * u, c + r * u, c + r * u),
                      outline=255, width=int(7 * u))
    elif name == "book":
        d.rounded_rectangle((14 * u, 16 * u, 86 * u, 84 * u), radius=5 * u, outline=255, width=int(6 * u))
        d.line([(c, 20 * u), (c, 80 * u)], fill=255, width=int(6 * u))
    elif name == "coins":
        for k, dy in enumerate((0, 18)):
            d.ellipse((20 * u, (26 + dy) * u, 80 * u, (62 + dy) * u), fill=255 if k else 255)
            d.ellipse((28 * u, (33 + dy) * u, 72 * u, (55 + dy) * u), fill=0)
    elif name == "people":
        d.ellipse((34 * u, 14 * u, 66 * u, 46 * u), fill=255)
        d.pieslice((18 * u, 46 * u, 82 * u, 100 * u), 180, 360, fill=255)
    else:  # dot fallback
        d.ellipse((32 * u, 32 * u, 68 * u, 68 * u), fill=255)
    return im


def icon(name: str, colour: str = "cyan", size: int = 256) -> Path:
    out = _cache(f"icon_{name}_{colour}_{size}.png")
    if out.exists():
        return out
    mask = _icon_mask(name, size)
    rgb = ACCENTS.get(colour, CYAN)
    tint = Image.new("RGBA", (size, size), (*rgb, 255))
    tint.putalpha(mask)
    tint.save(out)
    return out


def ghost(name: str, colour: str = "cyan", size: int = 512) -> Path:
    """Blurred silhouette of an icon — used as an ambient portrait backdrop."""
    out = _cache(f"ghost_{name}_{colour}_{size}.png")
    if out.exists():
        return out
    src = Image.open(icon(name, colour, size)).convert("RGBA")
    pad = int(size * 0.30)
    canvas = Image.new("RGBA", (size + pad * 2, size + pad * 2), (0, 0, 0, 0))
    canvas.paste(src, (pad, pad), src)
    canvas.filter(ImageFilter.GaussianBlur(size * 0.07)).save(out)
    return out


def icon_ring(name: str, colour: str = "cyan", size: int = 256) -> Path:
    """Icon inside a soft filled disc — good for 'bullet' markers."""
    out = _cache(f"ring_{name}_{colour}_{size}.png")
    if out.exists():
        return out
    rgb = ACCENTS.get(colour, CYAN)
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    # soft halo
    halo = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(halo).ellipse((size * 0.06, size * 0.06, size * 0.94, size * 0.94),
                                 fill=(*rgb, 60))
    im.alpha_composite(halo.filter(ImageFilter.GaussianBlur(size // 22)))
    d = ImageDraw.Draw(im)
    d.ellipse((0, 0, size - 1, size - 1), fill=(*rgb, 16), outline=(*rgb, 210),
              width=max(2, size // 64))
    inner = _icon_mask(name, int(size * 0.56))
    tint = Image.new("RGBA", inner.size, (*rgb, 255))
    tint.putalpha(inner)
    off = int(size * 0.22)
    im.alpha_composite(tint, (off, off))
    im.save(out)
    return out


# ── Clock face (2D watch) ───────────────────────────────────────────────────
def clock_face(colour: str = "cyan", size: int = 620) -> Path:
    out = _cache(f"clockface_{colour}_{size}.png")
    if out.exists():
        return out
    rgb = ACCENTS.get(colour, CYAN)
    s = size
    im = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.ellipse((0, 0, s - 1, s - 1), fill=(8, 12, 26, 235), outline=(*rgb, 220), width=max(3, s // 90))
    d.ellipse((s * 0.055, s * 0.055, s * 0.945, s * 0.945), outline=(*rgb, 60), width=max(2, s // 200))
    for k in range(60):
        a = math.radians(k * 6 - 90)
        r1 = s * (0.375 if k % 5 else 0.345)
        r2 = s * 0.435
        w = max(2, s // 170) if k % 5 else max(4, s // 78)
        col = (*rgb, 210) if k % 5 == 0 else (255, 255, 255, 90)
        d.line([(s / 2 + math.cos(a) * r1, s / 2 + math.sin(a) * r1),
                (s / 2 + math.cos(a) * r2, s / 2 + math.sin(a) * r2)], fill=col, width=w)
    for num in ("১২", "৩", "৬", "৯"):
        pass  # numerals are drawn by ffmpeg drawtext to keep one text path
    im.save(out)
    return out


def clock_hand(length_ratio: float, width: int, colour: str, size: int = 620) -> Path:
    """Vertical hand pointing up from the centre; rotate it in ffmpeg."""
    out = _cache(f"hand_{length_ratio}_{width}_{colour}_{size}.png")
    if out.exists():
        return out
    rgb = ACCENTS.get(colour, WHITE)
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    c = size / 2
    L = size * length_ratio
    d.rounded_rectangle((c - width / 2, c - L, c + width / 2, c + width / 2),
                        radius=width / 2, fill=(*rgb, 255))
    im.save(out)
    return out


# ── Map plate ───────────────────────────────────────────────────────────────
def map_plate(w: int, h: int, seed: int = 3) -> Path:
    """Stylised map: dotted landmass, a dotted route and city nodes.

    Deliberately abstract — reads as a map at a glance without claiming to be
    an accurate cartogram.
    """
    out = _cache(f"map2_{w}x{h}_{seed}.png")
    if out.exists():
        return out

    pts = [(0.10, 0.44), (0.17, 0.27), (0.30, 0.19), (0.43, 0.24),
           (0.54, 0.17), (0.67, 0.22), (0.80, 0.31), (0.88, 0.46),
           (0.80, 0.60), (0.70, 0.72), (0.56, 0.79), (0.40, 0.74),
           (0.27, 0.66), (0.16, 0.58)]
    land = Image.new("L", (w, h), 0)
    ImageDraw.Draw(land).polygon([(x * w, y * h) for x, y in pts], fill=255)
    land = land.filter(ImageFilter.GaussianBlur(min(w, h) * 0.015))

    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((0, 0, w - 1, h - 1), radius=int(min(w, h) * 0.06),
                        fill=(8, 14, 30, 255))

    # graticule
    for k in range(1, 5):
        d.line([(w * k / 4, 0), (w * k / 4, h)], fill=(255, 255, 255, 14), width=1)
    for k in range(1, 3):
        d.line([(0, h * k / 3), (w, h * k / 3)], fill=(255, 255, 255, 14), width=1)

    # dotted landmass
    dot = max(2, int(min(w, h) / 150))
    gap = dot * 4
    px = land.load()
    cols, rows = w // gap, h // gap
    for gy in range(rows):
        for gx in range(cols):
            x, y = gx * gap + gap // 2, gy * gap + gap // 2
            a = px[min(w - 1, x), min(h - 1, y)]
            if a > 110:
                d.ellipse((x - dot, y - dot, x + dot, y + dot),
                          fill=(*CYAN, int(40 + 130 * (a / 255))))

    # dotted route + nodes
    route = [(0.26, 0.58), (0.40, 0.47), (0.54, 0.52), (0.70, 0.36)]
    for (x0, y0), (x1, y1) in zip(route, route[1:]):
        x0, y0, x1, y1 = x0 * w, y0 * h, x1 * w, y1 * h
        steps = max(6, int(math.hypot(x1 - x0, y1 - y0) / (dot * 3.2)))
        for k in range(steps):
            if k % 2:
                continue
            u = k / steps
            x, y = x0 + (x1 - x0) * u, y0 + (y1 - y0) * u
            d.ellipse((x - dot * 0.8, y - dot * 0.8, x + dot * 0.8, y + dot * 0.8),
                      fill=(*AMBER, 190))
    for nx, ny in (route[0], route[-1]):
        cx, cy = nx * w, ny * h
        r = max(5, int(min(w, h) * 0.014))
        d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=(*AMBER, 230),
                  width=max(2, r // 3))

    d.rounded_rectangle((0, 0, w - 1, h - 1), radius=int(min(w, h) * 0.06),
                        outline=(*CYAN, 90), width=max(2, w // 400))
    im.save(out)
    return out


# ── Grain strip for "film texture" overlay ──────────────────────────────────
def grain(w: int, h: int) -> Path:
    out = _cache(f"grain_{w}x{h}.png")
    if out.exists():
        return out
    rng = np.random.default_rng(11)
    a = rng.normal(128, 26, (h, w, 1)).astype(np.uint8)
    rgb = np.repeat(a, 3, axis=2)
    im = Image.fromarray(rgb, "RGB").convert("RGBA")
    al = np.full((h, w, 1), 16, dtype=np.uint8)
    im.putalpha(Image.fromarray(np.repeat(al, 1, axis=2)[..., 0], "L"))
    im.save(out)
    return out


def skyline(w: int, h: int, seed: int = 5, colour: str = "cyan") -> Path:
    """City silhouette band with lit windows — the 'environment' for street scenes."""
    out = _cache(f"skyline_{w}x{h}_{seed}_{colour}.png")
    if out.exists():
        return out
    rgb = ACCENTS.get(colour, CYAN)
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    rng = np.random.default_rng(seed)
    x = -int(w * 0.04)
    while x < w:
        bw = int(rng.uniform(0.055, 0.13) * w)
        bh = int(rng.uniform(0.35, 0.98) * h)
        top = h - bh
        d.rectangle((x, top, x + bw, h), fill=(5, 8, 18, 255))
        d.rectangle((x, top, x + bw, h), outline=(*rgb, 42), width=max(1, w // 900))
        cols = max(1, bw // max(10, w // 90))
        rows = max(1, bh // max(12, h // 34))
        for r in range(rows):
            for c in range(cols):
                if rng.random() < 0.38:
                    wx = x + (c + 0.5) * bw / cols
                    wy = top + (r + 0.6) * bh / rows
                    s = max(2, w // 320)
                    a = int(rng.uniform(90, 220))
                    d.rectangle((wx - s, wy - s, wx + s, wy + s),
                                fill=(*rgb, a) if rng.random() < 0.7 else (255, 236, 180, a))
        x += bw + int(rng.uniform(2, 10) * w / 400)
    im.save(out)
    return out


def beam(w: int, h: int, colour: str = "white") -> Path:
    """Soft light shaft (moonlight through a window) — smooth falloff, no hard edges."""
    out = _cache(f"beam_{w}x{h}_{colour}.png")
    if out.exists():
        return out
    rgb = ACCENTS.get(colour, WHITE)
    n = 256
    yy, xx = np.mgrid[0:n, 0:n].astype(np.float32)
    half = 3.0 + 26.0 * (yy / n)                    # widens as it falls
    d = np.abs(xx - n / 2) / np.maximum(half, 1.0)
    core = np.exp(-(d ** 2) * 2.0)
    fade_y = np.clip(1.05 - (yy / n) * 0.85, 0, 1) ** 1.4
    a = core * fade_y * 0.42
    im = np.zeros((n, n, 4), dtype=np.uint8)
    im[..., 0], im[..., 1], im[..., 2] = rgb
    im[..., 3] = np.clip(a * 255, 0, 255).astype(np.uint8)
    pil = Image.fromarray(im, "RGBA").resize((w, h), Image.BICUBIC)
    pil = pil.filter(ImageFilter.GaussianBlur(max(2, w // 120)))
    pil.save(out)
    return out


def ensure_assets(w: int, h: int, moods: set[str]) -> None:
    for m in moods:
        backdrop(w, h, m)
