"""
FFmpeg graphics compositor.

Every scene is rendered by one FFmpeg pass: a drifting backdrop, then PNG
overlays (panels, icons, map, clock) animated with time expressions, then
`drawbox` shapes (bars, rules, shade), then the generated .ass typography.

Overlays are anchored by *centre* so that scale animations stay put:
`x='<cx>-overlay_w/2'`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from . import assets


def _hex(rgb) -> str:
    return "0x%02X%02X%02X" % tuple(rgb)


# ── easing snippets (ffmpeg expression language) ────────────────────────────
def ease_out(t0: float, dur: float, v0: float, v1: float, power: float = 3.0) -> str:
    x = f"min(1,max(0,(t-{t0:.3f})/{max(dur, 0.001):.3f}))"
    return f"({v0:.1f}+({v1 - v0:.1f})*(1-pow(1-{x},{power})))"


def ease_out_back(t0: float, dur: float, v0: float, v1: float, s: float = 1.70158) -> str:
    x = f"min(1,max(0,(t-{t0:.3f})/{max(dur, 0.001):.3f}))"
    p = f"({x}-1)"
    return (f"({v0:.1f}+({v1 - v0:.1f})*(1+{2 * s + 1:.4f}*pow({p},3)"
            f"+{s:.4f}*pow({p},2)))")


@dataclass
class Layer:
    png: object
    t0: float
    t1: float
    x: str
    y: str
    fade_in: float = 0.25
    fade_out: float = 0.22
    scale_expr: str | None = None
    rotate: str | None = None
    alpha: float = 1.0
    name: str = ""


@dataclass
class Draw:
    t0: float
    t1: float
    x: str
    y: str
    w: str
    h: str
    colour: str
    alpha: float = 1.0
    name: str = ""


class Kit:
    """Widget factory bound to one canvas and one scene's absolute timing."""

    def __init__(self, W: int, H: int, t0: float, t1: float):
        self.W, self.H = W, H
        self.t0, self.t1 = t0, t1
        self.dur = t1 - t0
        self.layers: list[Layer] = []
        self.draws: list[Draw] = []

    # -- helpers --
    def px(self, f: float) -> int:
        return int(self.W * f)

    def py(self, f: float) -> int:
        return int(self.H * f)

    def _win(self, t0, t1):
        return (self.t0 if t0 is None else t0), (self.t1 if t1 is None else t1)

    def _lt(self, t0) -> float:
        return 0.0 if t0 is None else max(0.0, t0 - self.t0)

    @staticmethod
    def _centre(cx, cy, extra_y=""):
        return (f"({cx})-overlay_w/2", f"({cy}){extra_y}-overlay_h/2")

    # -- primitives --
    def ghost(self, name="dot", colour="cyan", at=(0.5, 0.52), size=0.92,
              alpha=0.12, drift=10):
        """Huge soft silhouette: fills the air behind a portrait text block."""
        w = int(min(self.W, self.H) * size)
        png = assets.ghost(name, colour, 384)
        cx, cy = self.px(at[0]), self.py(at[1])
        x, y = self._centre(cx, cy)
        y = f"({y})+{drift:.0f}*sin(t*0.25)"
        self.layers.append(Layer(png, self.t0, self.t1, x, y, 0.60, 0.40,
                                 scale_expr=f"max(2,{w})", alpha=alpha,
                                 name="ghost"))

    def icon(self, name="dot", colour="cyan", at=(0.5, 0.5), size=0.18,
             t0=None, t1=None, enter="pop", ring=False, alpha=1.0):
        s = int(min(self.W, self.H) * size)
        png = assets.icon_ring(name, colour, 256) if ring else assets.icon(name, colour, 256)
        a, b = self._win(t0, t1)
        lt = self._lt(t0)
        cx, cy = self.px(at[0]), self.py(at[1])

        if enter == "pop":
            w = ease_out_back(lt, 0.42, s * 0.55, s, 2.2)
            x, y = self._centre(cx, cy)
            self.layers.append(Layer(png, a, b, x, y, 0.18, 0.22,
                                     scale_expr=f"max(2,{w})", alpha=alpha,
                                     name=name))
        elif enter.startswith("slide"):
            off = int(self.W * 0.16)
            dx = dy = 0
            if enter == "slideL":
                dx = f"-({off}*(1-{self._back(lt)}))"
            elif enter == "slideR":
                dx = f"+({off}*(1-{self._back(lt)}))"
            elif enter == "slideU":
                dy = f"-({off}*(1-{self._back(lt)}))"
            else:
                dy = f"+({off}*(1-{self._back(lt)}))"
            x, y = self._centre(f"{cx}{dx}" if dx else cx, f"{cy}{dy}" if dy else cy)
            self.layers.append(Layer(png, a, b, x, y, 0.22, 0.22,
                                     alpha=alpha, name=name))
        else:
            x, y = self._centre(cx, cy)
            self.layers.append(Layer(png, a, b, x, y, 0.30, 0.22,
                                     alpha=alpha, name=name))

    @staticmethod
    def _back(lt) -> str:
        x = f"min(1,max(0,(t-{lt:.3f})/0.52))"
        p = f"({x}-1)"
        return f"(1+4.4032*pow({p},3)+1.7016*pow({p},2))"

    def panel(self, colour="ink", at=(0.5, 0.5), size=(0.5, 0.24),
              t0=None, t1=None, enter="slideL", alpha=225, border="cyan", radius=30):
        w, h = int(self.W * size[0]), int(self.H * size[1])
        png = assets.panel(w, h, colour, alpha, radius, border)
        a, b = self._win(t0, t1)
        lt = self._lt(t0)
        cx, cy = self.px(at[0]), self.py(at[1])

        if enter in ("slideL", "slideR", "slideU", "slideD"):
            off = int(self.W * 0.22)
            dx = dy = None
            if enter == "slideL":
                dx = f"-({off}*(1-{self._back(lt)}))"
            elif enter == "slideR":
                dx = f"+({off}*(1-{self._back(lt)}))"
            elif enter == "slideU":
                dy = f"-({off}*(1-{self._back(lt)}))"
            else:
                dy = f"+({off}*(1-{self._back(lt)}))"
            x, y = self._centre(f"{cx}{dx}" if dx else cx, f"{cy}{dy}" if dy else cy)
            self.layers.append(Layer(png, a, b, x, y, 0.28, 0.22, name="panel"))
        elif enter == "pop":
            ww = ease_out_back(lt, 0.45, w * 0.62, w, 1.9)
            x, y = self._centre(cx, cy)
            self.layers.append(Layer(png, a, b, x, y, 0.22, 0.22,
                                     scale_expr=f"max(2,{ww})", name="panel"))
        else:
            x, y = self._centre(cx, cy)
            self.layers.append(Layer(png, a, b, x, y, 0.38, 0.22, name="panel"))

    def rule(self, at=(0.5, 0.30), width=0.10, colour="cyan", thick=0.006,
             t0=None, t1=None, delay=0.0):
        a, b = self._win(t0, t1)
        lt = self._lt(t0)
        wpx = int(self.W * width)
        hpx = max(3, int(self.H * thick))
        self.draws.append(Draw(
            a, b,
            f"{self.px(at[0]) - wpx // 2}",
            f"{self.py(at[1])}",
            ease_out(lt + delay, 0.42, 0, wpx, 3.0),
            f"{hpx}", _hex(assets.ACCENTS.get(colour, assets.CYAN)), 0.95, "rule"))

    def bars(self, items, at=(0.12, 0.62), width=0.42, row_gap=0.075,
             colour="cyan", t0=None, t1=None, delay=0.24):
        a, b = self._win(t0, t1)
        lt = self._lt(t0)
        wpx = int(self.W * width)
        hpx = max(8, int(self.H * 0.026))
        top = self.py(at[1])
        gap = int(self.H * row_gap)
        vmax = max(1e-6, max(abs(float(v)) for _, v in items))
        col = _hex(assets.ACCENTS.get(colour, assets.CYAN))
        for i, (_name, val) in enumerate(items):
            y = top + i * gap
            self.draws.append(Draw(a, b, f"{self.px(at[0])}", f"{y}",
                                   f"{wpx}", f"{hpx}", "0xFFFFFF", 0.10, "track"))
            target = wpx * (abs(float(val)) / vmax)
            self.draws.append(Draw(
                a, b, f"{self.px(at[0])}", f"{y}",
                ease_out(lt + delay + i * 0.13, 0.55, 0, target, 3.0),
                f"{hpx}", col, 0.95, "bar"))

    def clock(self, at=(0.5, 0.5), size=0.30, colour="cyan", t0=None, t1=None,
              hours=12, minutes=0, sweep=True):
        a, b = self._win(t0, t1)
        lt = self._lt(t0)
        s = int(min(self.W, self.H) * size)
        face = assets.clock_face(colour, s)
        cx, cy = self.px(at[0]), self.py(at[1])
        pop = ease_out_back(lt, 0.5, 0.35, 1.0, 2.0)
        sc = f"max(2,{s}*{pop})"
        x, y = self._centre(cx, cy)
        self.layers.append(Layer(face, a, b, x, y, 0.2, 0.22, scale_expr=sc, name="clockface"))

        def hand(ratio, width, colour_, angle0, rate):
            png = assets.clock_hand(ratio, width, colour_, s)
            ang = f"({angle0}+{rate}*(t-{lt:.3f}))" if (sweep and rate) else f"{angle0}"
            self.layers.append(Layer(png, a, b, x, y, 0.25, 0.22,
                                     scale_expr=sc,
                                     rotate=f"({ang})*PI/180", name="hand"))

        hand(0.20, max(6, s // 26), colour, (hours % 12) * 30 + minutes * 0.5,
             0.6 if sweep else 0)
        hand(0.30, max(4, s // 42), "white", minutes * 6, 6.0 if sweep else 0)

    def map(self, at=(0.5, 0.5), size=(0.44, 0.34), t0=None, t1=None,
            pin_at=(0.5, 0.5), pin_colour="amber"):
        a, b = self._win(t0, t1)
        lt = self._lt(t0)
        w, h = int(self.W * size[0]), int(self.H * size[1])
        plate = assets.map_plate(w, h)
        cx, cy = self.px(at[0]), self.py(at[1])
        zoom = ease_out(lt, max(1.0, self.dur * 0.9), 1.0, 1.10, 2.0)
        x, y = self._centre(cx, cy)
        self.layers.append(Layer(plate, a, b, x, y, 0.32, 0.22,
                                 scale_expr=f"{w}*{zoom}", name="map"))

        ps = int(min(w, h) * 0.20)
        pin = assets.icon("pin", pin_colour, 256)
        pcx = cx + int(w * (pin_at[0] - 0.5))
        pcy = cy + int(h * (pin_at[1] - 0.5)) - ps * 0.35
        drop = ease_out_back(lt + 0.35, 0.45, -ps * 0.9, 0, 2.4)
        x2, y2 = self._centre(pcx, f"{pcy}+{drop}")
        self.layers.append(Layer(pin, a + 0.12, b, x2, y2, 0.12, 0.22,
                                 scale_expr=f"max(2,{ps})", name="pin"))

    def skyline(self, colour="cyan", height=0.30, at=(0.5, 1.02), seed=5,
                t0=None, t1=None, rise=40):
        a, b = self._win(t0, t1)
        lt = self._lt(t0)
        w, h = int(self.W * 1.10), int(self.H * height)
        png = assets.skyline(w, h, seed, colour)
        ty = ease_out(lt, 1.2, self.py(at[1]) - h + rise, self.py(at[1]) - h, 2.2)
        tx = self.px(at[0]) - w // 2
        self.layers.append(Layer(png, a, b, f"{tx}", f"{ty}", 0.7, 0.3, name="skyline"))

    def beam(self, at=(0.5, 0.5), size=(0.55, 1.05), colour="white",
             angle=-22.0, t0=None, t1=None):
        a, b = self._win(t0, t1)
        w, h = int(self.W * size[0]), int(self.H * size[1])
        png = assets.beam(w, h, colour)
        x, y = self._centre(self.px(at[0]), self.py(at[1]))
        self.layers.append(Layer(png, a, b, x, y, 0.9, 0.6,
                                 rotate=f"{angle}*PI/180", name="beam"))

    def shade(self, t0=None, t1=None, alpha=0.55, h=0.34, from_bottom=True):
        a, b = self._win(t0, t1)
        hh = int(self.H * h)
        y = self.H - hh if from_bottom else 0
        self.draws.append(Draw(a, b, "0", f"{y}", f"{self.W}", f"{hh}",
                               _hex((4, 6, 14)), alpha, "shade"))

    def flash(self, at=0.0, dur=0.10):
        self.draws.append(Draw(self.t0 + at, self.t0 + at + dur, "0", "0",
                               f"{self.W}", f"{self.H}", _hex((255, 255, 255)),
                               0.30, "flash"))

    def progress(self, film_start: float, total: float, colour="cyan"):
        """Thin timeline bar across the top — always shows how far we are."""
        # isnan(t): drawbox also evaluates its expressions once at configure time
        w = (f"max(1,min({self.W},{self.W}*(({film_start:.3f}"
             f"+if(isnan(t),0,t))/{max(0.1, total):.3f})))")
        self.draws.append(Draw(self.t0, self.t1, "0", "0", w,
                               f"{max(3, self.H // 320)}",
                               _hex(assets.ACCENTS.get(colour, assets.CYAN)), 0.80, "progress"))

    def line(self, at=(0.5, 0.62), width=0.50, colour="cyan", thick=0.004,
             t0=None, t1=None, delay=0.0):
        """Horizontal connector that draws in from the left."""
        a, b = self._win(t0, t1)
        lt = self._lt(t0)
        wpx = int(self.W * width)
        hpx = max(2, int(self.H * thick))
        self.draws.append(Draw(a, b, f"{self.px(at[0]) - wpx // 2}",
                               f"{self.py(at[1])}",
                               ease_out(lt + delay, 0.55, 0, wpx, 2.4),
                               f"{hpx}", _hex(assets.ACCENTS.get(colour, assets.CYAN)),
                               0.55, "line"))


# ── Scene assembly ──────────────────────────────────────────────────────────
@dataclass
class Scene:
    index: int
    start: float
    end: float
    kit: Kit
    ass_path: object
    mood: str = "night"
    drift: tuple = (26.0, 14.0)

    @property
    def dur(self) -> float:
        return self.end - self.start


def build_filter_complex(scene: Scene, W: int, H: int, fps: int,
                         fontsdir: str, deband: bool = True) -> tuple[str, list[str]]:
    """Input 0 is the backdrop; inputs 1.. are the layer PNGs."""
    dur = scene.dur
    parts: list[str] = []
    extra: list[str] = []

    dx, dy = scene.drift
    bw, bh = int(W * 1.16), int(H * 1.16)
    parts.append(
        f"[0:v]format=rgba,"
        f"crop={W}:{H}:"
        f"'({bw}-{W})/2+{dx:.1f}*sin(t*0.42+{scene.index * 1.7:.2f})':"
        f"'({bh}-{H})/2+{dy:.1f}*cos(t*0.35+{scene.index * 1.1:.2f})'"
        f"[base0]"
    )

    cur = "base0"
    # underlays (shade) must sit *behind* the props, not wash them out
    under = [d for d in scene.kit.draws if d.name in ("shade", "vignette")]
    for j, d in enumerate(under):
        a = max(0.0, d.t0 - scene.start)
        b = max(0.01, d.t1 - scene.start)
        nxt = f"u{j}"
        parts.append(
            f"[{cur}]drawbox=x='{d.x}':y='{d.y}':w='max(1,{d.w})':h='{d.h}'"
            f":color={d.colour}@{d.alpha:.2f}:t=fill"
            f":enable='between(t,{a:.3f},{b:.3f})'[{nxt}]"
        )
        cur = nxt

    for i, lay in enumerate(scene.kit.layers):
        idx = i + 1
        extra.append(str(lay.png))
        chain = [f"[{idx}:v]", "format=rgba"]
        if lay.alpha < 1.0:
            chain.append(f"colorchannelmixer=aa={lay.alpha:.2f}")
        if lay.rotate:
            chain.append(f"rotate=angle='{lay.rotate}':ow=iw:oh=ih:fillcolor=black@0")
        chain.append(f"fade=t=in:st=0:d={lay.fade_in:.2f}:alpha=1")
        chain.append(f"fade=t=out:st={max(0.0, dur - lay.fade_out):.2f}:d={lay.fade_out:.2f}:alpha=1")
        # size animation must come *after* fade: fade rejects frame-size changes
        if lay.scale_expr:
            chain.append(f"scale=w='{lay.scale_expr}':h='-1':eval=frame:flags=bilinear")
        parts.append(chain[0] + ",".join(chain[1:]) + f"[ov{i}]")
        nxt = f"v{i}"
        parts.append(
            f"[{cur}][ov{i}]overlay=x='{lay.x}':y='{lay.y}':"
            f"enable='between(t,{max(0.0, lay.t0 - scene.start):.3f},"
            f"{max(0.01, lay.t1 - scene.start):.3f})':eval=frame:format=yuv420[{nxt}]"
        )
        cur = nxt

    for j, d in enumerate(scene.kit.draws):
        if d.name in ("shade", "vignette"):
            continue
        a = max(0.0, d.t0 - scene.start)
        b = max(0.01, d.t1 - scene.start)
        nxt = f"d{j}"
        parts.append(
            f"[{cur}]drawbox=x='{d.x}':y='{d.y}':w='max(1,{d.w})':h='{d.h}'"
            f":color={d.colour}@{d.alpha:.2f}:t=fill"
            f":enable='between(t,{a:.3f},{b:.3f})'[{nxt}]"
        )
        cur = nxt

    ass = str(scene.ass_path).replace("\\", "/").replace(":", "\\:")
    fdir = fontsdir.replace("\\", "/").replace(":", "\\:")
    parts.append(f"[{cur}]ass=filename='{ass}':fontsdir='{fdir}'[vout]")
    # deband: dark gradients are where x264 banding shows up first
    if deband:
        parts.append("[vout]gradfun=strength=0.75:radius=18,format=yuv420p[vfinal]")
    else:
        parts.append("[vout]format=yuv420p[vfinal]")
    return ";".join(parts), extra
