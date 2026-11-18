"""
ASS (Advanced SubStation Alpha) generation — all text and typography.

Everything textual lives here because libass is the only renderer in this
toolchain that shapes Bengali correctly (HarfBuzz) *and* can animate it.

Position convention: scenes describe positions as fractions of the canvas
(0..1). This file converts them to script coordinates so one spec renders to
landscape and portrait alike.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

# ── Colour helpers ──────────────────────────────────────────────────────────
RGB = {
    "white": (248, 250, 252),    "cyan": (34, 211, 238),
    "amber": (251, 191, 36),
    "magenta": (244, 114, 182),
    "mint": (52, 211, 153),
    "violet": (139, 92, 246),
    "muted": (148, 163, 184),
    "ink": (7, 11, 24),
    "black": (0, 0, 0),
}

BN_DIGITS = "০১২৩৪৫৬৭৮৯"


def ass_colour(name_or_rgb, alpha: int = 0) -> str:
    r, g, b = RGB.get(name_or_rgb, name_or_rgb) if isinstance(name_or_rgb, str) else name_or_rgb
    return f"&H{alpha:02X}{b:02X}{g:02X}{r:02X}"


def ts(t: float) -> str:
    t = max(0.0, t)
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def esc(text: str) -> str:
    return (text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}"))


def est_width(text: str, fs: int) -> float:
    """Rough advance width. Shaping needs libass, but for a fit check this is enough."""
    spaces = text.count(" ")
    glyphs = max(0, len(text) - spaces)
    return fs * (0.545 * glyphs + 0.29 * spaces)


# ── Animation tag recipes ───────────────────────────────────────────────────
def fade(fi: int, fo: int) -> str:
    return f"\\fad({fi},{fo})"


def popin(dur: int = 320, amount: int = 55) -> str:
    """Scale up with a soft overshoot — the house 'card enter'."""
    return (f"\\fscx{amount}\\fscy{amount}"
            f"\\t(0,{int(dur*0.62)},\\fscx108\\fscy108)"
            f"\\t({int(dur*0.62)},{dur},\\fscx100\\fscy100)")


def popout(dur: int = 220, amount: int = 80) -> str:
    return f"\\t(0,{dur},\\fscx{amount}\\fscy{amount}\\alpha&HFF&)"


def blur_in(dur: int = 300, amount: float = 6.0) -> str:
    return f"\\blur{amount}\\t(0,{dur},\\blur0)"


def tracking(px: int) -> str:
    return f"\\fsp{px}"


def rotate(a: float) -> str:
    return f"\\frz{a}"


# ── Document ────────────────────────────────────────────────────────────────
@dataclass
class Event:
    start: float
    end: float
    style: str
    text: str
    layer: int = 0
    name: str = ""


@dataclass
class AssDoc:
    W: int
    H: int
    events: list[Event] = field(default_factory=list)
    fontsdir: str = ""
    base_scale: float = 1.0

    # — geometry helpers —
    def x(self, frac: float) -> int:
        return int(round(self.W * frac))

    def y(self, frac: float) -> int:
        return int(round(self.H * frac))

    def fs(self, frac_of_h: float) -> int:
        """Font size expressed as a fraction of canvas height."""
        return max(10, int(round(self.H * frac_of_h * self.base_scale)))

    def add(self, start, end, style, text, layer=0, name=""):
        if end - start <= 0.01 or not text:
            return
        self.events.append(Event(start, end, style, text, layer, name))

    # — serialisation —
    def render(self, palette_accents: dict[str, str] | None = None) -> str:
        acc = palette_accents or {}
        a = lambda k: ass_colour(acc.get(k, "cyan"))

        styles = [
            # Name, Font, Size, Primary, Secondary, Outline, Back, Bold, Italic,
            # Underline, Strike, ScaleX, ScaleY, Spacing, Angle, BorderStyle,
            # Outline, Shadow, Alignment, L, R, V, Encoding
            f"Style: Head,Noto Sans Bengali,{self.fs(0.081)},{ass_colour('white')},"
            f"{ass_colour('cyan')},&H00100804,&H78000000,-1,0,0,0,100,100,0,0,1,4,3,5,80,80,80,1",
            f"Style: HeadBig,Noto Sans Bengali,{self.fs(0.098)},{ass_colour('white')},"
            f"{ass_colour('cyan')},&H00100804,&H78000000,-1,0,0,0,100,100,0,0,1,5,3,5,80,80,80,1",
            f"Style: Sub,Noto Sans Bengali,{self.fs(0.038)},{ass_colour('white')},"
            f"{ass_colour('cyan')},&H00201008,&H8C000000,-1,0,0,0,100,100,0,0,1,3,2,2,"
            f"{int(self.W*0.075)},{int(self.W*0.075)},{int(self.H*0.055)},1",
            f"Style: Kick,Noto Sans Bengali,{self.fs(0.026)},{a('cyan')},"
            f"{a('cyan')},&H00100804,&H00000000,-1,0,0,0,100,100,0,0,1,2,0,5,60,60,60,1",
            f"Style: Num,Anton,{self.fs(0.168)},{a('cyan')},"
            f"{a('cyan')},&H00100804,&H00000000,-1,0,0,0,100,100,0,0,1,3,0,5,40,40,40,1",
            f"Style: NumSm,Anton,{self.fs(0.062)},{ass_colour('white')},"
            f"{ass_colour('white')},&H00100804,&H00000000,-1,0,0,0,100,100,0,0,1,2,0,5,40,40,40,1",
            f"Style: Label,Noto Sans Bengali,{self.fs(0.028)},{ass_colour('muted')},"
            f"{ass_colour('muted')},&H00100804,&H00000000,0,0,0,0,100,100,0,0,1,2,0,5,40,40,40,1",
            f"Style: Card,Noto Sans Bengali,{self.fs(0.040)},{ass_colour('white')},"
            f"{a('amber')},&H00100804,&H00000000,-1,0,0,0,100,100,0,0,1,3,1,5,40,40,40,1",
            f"Style: Brand,Noto Sans Bengali,{self.fs(0.020)},{ass_colour('muted')},"
            f"{ass_colour('muted')},&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,5,40,40,40,1",
        ]

        out = [
            "[Script Info]",
            "ScriptType: v4.00+",
            f"PlayResX: {self.W}",
            f"PlayResY: {self.H}",
            "WrapStyle: 0",
            "ScaledBorderAndShadow: yes",
            "YCbCr Matrix: TV.709",
            "",
            "[V4+ Styles]",
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
            "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
            "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
            "Alignment, MarginL, MarginR, MarginV, Encoding",
            *styles,
            "",
            "[Events]",
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        ]
        for e in sorted(self.events, key=lambda e: (e.layer, e.start)):
            out.append(
                f"Dialogue: {e.layer},{ts(e.start)},{ts(e.end)},{e.style},"
                f"{e.name},0,0,0,,{e.text}"
            )
        return "\n".join(out) + "\n"

    def save(self, path: str | Path, accents: dict[str, str] | None = None):
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(self.render(accents), encoding="utf-8")
        return p

    def shift(self, dt: float, dur: float | None = None) -> None:
        """Move events by dt and clamp into [0, dur] — per-scene files are local."""
        out = []
        for e in self.events:
            e.start += dt
            e.end += dt
            if e.start < 0:
                e.start = 0.0
            if dur is not None and e.start >= dur - 0.02:
                continue
            if dur is not None:
                e.end = min(e.end, dur)
            if e.end - e.start > 0.03:
                out.append(e)
        self.events = out


# ── High-level text blocks ──────────────────────────────────────────────────
def headline_event(
    doc: AssDoc,
    start: float,
    end: float,
    text: str,
    xf: float = 0.5,
    yf: float = 0.44,
    style: str = "Head",
    accent: str = "cyan",
    emphasise: list[str] | None = None,
    enter: int = 380,
    exit_: int = 300,
    stagger: float = 0.0,
    base_fs: int | None = None,
    max_w: float = 0.90,
) -> None:
    """One headline with per-word emphasis pulses — no width measurement needed."""
    emphasise = emphasise or []
    acc = ass_colour(accent)
    words = text.split()

    # shrink rather than overflow: libass has no wrapping when \pos is used
    fit = ""
    if base_fs:
        est = est_width(text, base_fs)
        limit = doc.W * max_w
        if est > limit:
            fit = f"\\fs{max(22, int(base_fs * limit / est))}"

    if stagger > 0:
        # sequential word build: each word fades+rises on its own beat
        for i, w in enumerate(words):
            t0 = start + i * stagger
            if t0 >= end - 0.15:
                break
            body = esc(w)
            if w.strip("।,?!") in emphasise:
                body = f"{{\\c{acc}}}{body}{{\\c&HFFFFFF&}}"
            tag = (f"{{\\an5\\pos({doc.x(xf)},{doc.y(yf)}){fit}"
                   f"\\alpha&HFF&\\blur6\\t(0,{enter},\\alpha&H00&\\blur0)"
                   f"\\fad(0,{exit_})}}")
            doc.add(t0, end, style, tag + body)
        return

    # single line, words pulse in sequence
    parts = []
    for i, w in enumerate(words):
        d = int(i * 90)
        if w.strip("।,?!") in emphasise:
            parts.append(
                f"{{\\c{acc}\\fscx100\\fscy100"
                f"\\t({d},{d + 260},\\fscx118\\fscy118)"
                f"\\t({d + 260},{d + 520},\\fscx100\\fscy100)}}{esc(w)}{{\\c&HFFFFFF&}}"
            )
        else:
            parts.append(esc(w))
    body = " ".join(parts)
    tag = (f"{{\\an5\\pos({doc.x(xf)},{doc.y(yf)}){fit}{popin(enter)}"
           f"\\fad({int(enter*0.7)},{exit_})}}")
    doc.add(start, end, style, tag + body)


def subtitle_event(doc: AssDoc, start, end, text, yf: float = 0.885,
                   style: str = "Sub", accent: str = "amber") -> None:
    """Bottom narration caption. No \\pos: that would disable libass wrapping."""
    tag = "{\\fad(160,200)}"
    doc.add(start, end, style, tag + esc(text))


def kicker_event(doc: AssDoc, start, end, text, xf=0.5, yf=0.30,
                 accent="cyan", style="Kick") -> None:
    # NB: never use \fsp / style Spacing on Bengali — libass applies tracking
    # per character, which splits conjuncts and vowel signs apart.
    tag = (f"{{\\an5\\pos({doc.x(xf)},{doc.y(yf)})"
           f"\\alpha&HFF&\\t(0,300,\\alpha&H00&)\\fad(0,220)}}")
    doc.add(start, end, style, tag + esc(text.upper() if text.isascii() else text))


def fmt_num(v: float, decimals: int = 0, latin: bool = True) -> str:
    """Indian digit grouping (12,34,567) — reads naturally to a Bengali audience."""
    if decimals:
        s = f"{v:,.{decimals}f}"
    else:
        n = int(round(v))
        s = str(abs(n))
        if len(s) > 3:
            head, tail = s[:-3], s[-3:]
            groups = []
            while len(head) > 2:
                groups.insert(0, head[-2:])
                head = head[:-2]
            groups.insert(0, head)
            s = ",".join(groups) + "," + tail
        s = ("-" if n < 0 else "") + s
    if latin:
        return s
    return "".join(BN_DIGITS[int(ch)] if ch.isdigit() else ch for ch in s)


def counter_events(doc: AssDoc, start, end, value: float, xf=0.5, yf=0.42,
                   prefix="", suffix="", decimals=0, style="Num",
                   accent="cyan", ease_power=3.0, step=0.05) -> None:
    """Animated count-up. Emits one short event per step so digits actually roll."""
    span = max(0.15, end - start)
    pos = f"\\an5\\pos({doc.x(xf)},{doc.y(yf)})"
    acc = ass_colour(accent)

    # one soft fade-in across the first few frames, then discrete steps
    first_dur = min(0.14, span * 0.5)
    u0 = first_dur / span
    v0 = value * (1 - (1 - u0) ** ease_power)
    tag = (f"{{{pos}\\alpha&HFF&\\t(0,{int(first_dur * 1000)},"
           f"\\alpha&H00&)}}")
    doc.add(start, min(end, start + first_dur + 0.02), style,
            tag + f"{prefix}{fmt_num(v0, decimals)}{suffix}")

    t = start + first_dur
    while t < end - 1e-6:
        u = min(1.0, (t - start) / span)
        e = 1 - (1 - u) ** ease_power
        txt = f"{prefix}{fmt_num(value * e, decimals)}{suffix}"
        doc.add(t, min(end, t + step + 0.02), style, f"{{{pos}}}{txt}")
        t += step

    # a final, emphasised landing value
    doc.add(max(start + first_dur, end - 0.30), end, style,
            f"{{{pos}\\c{acc}}}{prefix}{fmt_num(value, decimals)}{suffix}")


def label_event(doc: AssDoc, start, end, text, xf=0.5, yf=0.54, style="Label") -> None:
    tag = f"{{\\an5\\pos({doc.x(xf)},{doc.y(yf)}){popin(280)}\\fad(150,200)}}"
    doc.add(start, end, style, tag + esc(text))


def brand_event(doc: AssDoc, start, end, text, accent="cyan") -> None:
    tag = (f"{{\\an5\\pos({doc.x(0.5)},{doc.y(0.972)})"
           f"\\fad(500,400)\\alpha&H70&}}")
    doc.add(start, end, "Brand", tag + esc(text))


def chip_event(doc: AssDoc, start, end, text, xf=0.88, yf=0.055,
               accent="cyan") -> None:
    acc = ass_colour(accent)
    tag = (f"{{\\an5\\pos({doc.x(xf)},{doc.y(yf)}){popin(260)}"
           f"\\fad(120,200)\\c{acc}}}")
    doc.add(start, end, "NumSm", tag + esc(text))


def bar_label_events(doc: AssDoc, start, end, items, xf, yf, row_gap,
                     width_frac=0.42, accent="cyan", value_fmt=None) -> None:
    """Chart labels: name to the left of the bar, value to the right."""
    for i, (name, val) in enumerate(items):
        y = yf + i * row_gap - 0.003
        tag = (f"{{\\an6\\pos({doc.x(xf - 0.012)},{doc.y(y)})"
               f"\\alpha&HFF&\\t({i * 70},{i * 70 + 280},\\alpha&H00&)\\fad(0,180)}}")
        doc.add(start + 0.0, end, "Label", tag + esc(name))

        if value_fmt:
            txt = value_fmt(val)
            tag2 = (f"{{\\an4\\pos({doc.x(xf + width_frac + 0.014)},{doc.y(y)})"
                    f"\\alpha&HFF&\\t({i * 70 + 120},{i * 70 + 420},\\alpha&H00&)"
                    f"\\fad(0,180)\\c{ass_colour(accent)}}}")
            doc.add(start, end, "Label", tag2 + esc(txt))
