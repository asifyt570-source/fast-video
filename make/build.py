"""
Build orchestrator.

  python -m make.build --film films/demo --layout both

Pipeline per film:
  1. read spec.json            (scenes, text, graphics, sfx)
  2. per scene -> .ass + ffmpeg filter graph -> one encoded segment
  3. concat segments (stream copy, instant)
  4. mix narration + sound effects, loudness-normalise
  5. write landscape and portrait masters
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from . import assets, assgen, gfx
from .gfx import Kit, Scene

ROOT = Path(__file__).resolve().parent.parent
FONT_DIR = ROOT / "assets" / "fonts"
SFX_DIR = ROOT / "assets" / "sfx"
BUILD = ROOT / "build"

LAYOUTS = {
    "landscape": (1920, 1080, 1.00),
    "portrait": (1080, 1920, 0.62),
}


def log(msg: str) -> None:
    print(msg, flush=True)


for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def run(cmd: list[str], capture: bool = True) -> subprocess.CompletedProcess:
    r = subprocess.run(cmd, capture_output=capture, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0:
        tail = (r.stderr or "")[-3000:]
        raise RuntimeError(f"ffmpeg failed ({r.returncode}):\n{tail}")
    return r


def probe_duration(path: str | Path) -> float:
    r = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(path)])
    return float(r.stdout.strip())


# ── graphics directives ─────────────────────────────────────────────────────
def apply_gfx(kit: Kit, d: dict, scen: dict, portrait: bool) -> None:
    t = d.get("type")
    s0 = scen["start"] + d.get("start", 0.0)
    s1 = scen["start"] + d.get("end", scen["end"] - scen["start"])

    def at(default):
        a = d.get("at_p" if portrait else "at", d.get("at", default))
        return tuple(a)

    def size(default):
        s = d.get("size_p" if portrait else "size", d.get("size", default))
        return tuple(s) if isinstance(s, (list, tuple)) else s

    if t == "icon":
        kit.icon(d.get("name", "dot"), d.get("colour", "cyan"), at((0.5, 0.5)),
                 size(0.18), s0 if d.get("start") is not None else None,
                 s1 if d.get("end") is not None else None,
                 d.get("enter", "pop"), d.get("ring", False))
    elif t == "panel":
        kit.panel(d.get("colour", "ink"), at((0.5, 0.5)), size((0.5, 0.24)),
                  s0 if d.get("start") is not None else None,
                  s1 if d.get("end") is not None else None,
                  d.get("enter", "slideL"), d.get("alpha", 225),
                  d.get("border", "cyan"), d.get("radius", 30))
    elif t == "bars":
        bw = d.get("width_p") if portrait else None
        kit.bars(d["items"], at((0.12, 0.62)), bw or d.get("width", 0.42),
                 d.get("row_gap", 0.075), d.get("colour", "cyan"),
                 s0 if d.get("start") is not None else None,
                 s1 if d.get("end") is not None else None,
                 d.get("delay", 0.24))
    elif t == "clock":
        kit.clock(at((0.5, 0.5)), size(0.30), d.get("colour", "cyan"),
                  s0 if d.get("start") is not None else None,
                  s1 if d.get("end") is not None else None,
                  d.get("hours", 12), d.get("minutes", 0), d.get("sweep", True))
    elif t == "map":
        kit.map(at((0.5, 0.5)), size((0.44, 0.34)),
                s0 if d.get("start") is not None else None,
                s1 if d.get("end") is not None else None,
                tuple(d.get("pin_at", (0.5, 0.5))), d.get("pin_colour", "amber"))
    elif t == "rule":
        rw = d.get("width_p") if portrait else None
        kit.rule(at((0.5, 0.30)), rw or d.get("width", 0.10) * (2.2 if portrait else 1.0),
                 d.get("colour", "cyan"),
                 d.get("thick", 0.006),
                 s0 if d.get("start") is not None else None,
                 s1 if d.get("end") is not None else None,
                 d.get("delay", 0.0))
    elif t == "line":
        kit.line(at((0.5, 0.62)), d.get("width", 0.50), d.get("colour", "cyan"),
                 d.get("thick", 0.004),
                 s0 if d.get("start") is not None else None,
                 s1 if d.get("end") is not None else None,
                 d.get("delay", 0.0))
    elif t == "skyline":
        kit.skyline(d.get("colour", "cyan"), d.get("height", 0.30),
                    at((0.5, 1.02)), d.get("seed", 5),
                    s0 if d.get("start") is not None else None,
                    s1 if d.get("end") is not None else None,
                    d.get("rise", 40))
    elif t == "beam":
        kit.beam(at((0.5, 0.5)), size((0.55, 1.05)), d.get("colour", "white"),
                 d.get("angle", -22.0),
                 s0 if d.get("start") is not None else None,
                 s1 if d.get("end") is not None else None)
    elif t == "shade":
        kit.shade(s0 if d.get("start") is not None else None,
                  s1 if d.get("end") is not None else None,
                  d.get("alpha", 0.55),
                  d.get("height", 0.34), d.get("from_bottom", True))
    elif t == "flash":
        kit.flash(d.get("start", 0.0), d.get("dur", 0.10))


# ── typography ──────────────────────────────────────────────────────────────
def build_ass(scene: dict, doc: assgen.AssDoc, portrait: bool) -> None:
    s, e = scene["start"], scene["end"]
    accent = scene.get("accent", "cyan")

    kick = scene.get("kicker")
    if kick:
        kx = (scene.get("kicker_at_p" if portrait else "kicker_at") or
              scene.get("kicker_at") or [0.5, 0.285])
        assgen.kicker_event(doc, s + 0.05, e, kick, kx[0], kx[1], accent)

    head = scene["head"] if "head" in scene else scene.get("text", "")
    if head:
        hx = (scene.get("head_at_p" if portrait else "head_at") or
              scene.get("head_at") or [0.5, 0.40])
        assgen.headline_event(
            doc, s + scene.get("head_delay", 0.10), e - scene.get("head_out", 0.0),
            head, hx[0], hx[1],
            scene.get("head_style", "Head"), accent,
            scene.get("emphasise", []),
            int(scene.get("head_enter", 380)), 260,
            scene.get("stagger", 0.0),
            base_fs=doc.fs(0.098 if scene.get("head_style") == "HeadBig" else 0.081),
            max_w=scene.get("head_max_w", 0.90),
        )

    if scene.get("counter") is not None:
        c = scene["counter"]
        cx = (scene.get("counter_at_p" if portrait else "counter_at") or
              scene.get("counter_at") or [0.5, 0.40])
        assgen.counter_events(doc, s + c.get("delay", 0.25), e,
                             c["value"], cx[0], cx[1],
                             c.get("prefix", ""), c.get("suffix", ""),
                             int(c.get("decimals", 0)), c.get("style", "Num"),
                             accent, c.get("ease", 3.0))
        if c.get("label"):
            lx = (c.get("label_at_p" if portrait else "label_at") or
                  c.get("label_at") or [cx[0], cx[1] + 0.085])
            assgen.label_event(doc, s + c.get("delay", 0.25) + 0.1, e,
                               c["label"], lx[0], lx[1])

    for lb in scene.get("labels", []):
        lx = lb.get("at_p" if portrait else "at", lb.get("at", [0.5, 0.55]))
        assgen.label_event(doc, s + lb.get("start", 0.2), e, lb["text"], lx[0], lx[1])

    for d in scene.get("gfx", []):
        if d.get("type") != "bars":
            continue
        at = d.get("at_p" if portrait else "at", d.get("at", [0.12, 0.62]))
        wf = d.get("width_p" if portrait else "width", d.get("width", 0.42))
        gap = d.get("row_gap", 0.075)
        fmt = d.get("value_fmt_p" if portrait else "value_fmt", d.get("value_fmt"))
        vf = None
        if fmt == "pct":
            vf = lambda v: f"{v * 100:.0f}%"
        elif fmt == "num":
            vf = lambda v: f"{v:,.0f}"
        elif fmt == "k":
            vf = lambda v: f"{v / 1000:,.1f}k"
        assgen.bar_label_events(doc, s + d.get("start", 0.0) + d.get("delay", 0.24), e,
                                d["items"], at[0], at[1], gap, wf,
                                d.get("colour", accent), vf)

    if scene.get("sub", True) and scene.get("sub_text", scene.get("text")):
        sy = (scene.get("sub_y_p") or scene.get("sub_y", 0.885)) if portrait \
            else scene.get("sub_y", 0.885)
        assgen.subtitle_event(doc, scene.get("sub_start", s + 0.05), e,
                              scene.get("sub_text") or scene["text"], sy, "Sub",
                              accent)

    if scene.get("chip"):
        assgen.chip_event(doc, s + 0.15, e, scene["chip"], accent=accent)

    if scene.get("_brand"):
        assgen.brand_event(doc, max(s + 0.2, e - 2.4), e, scene["_brand"], accent)


# ── one scene -> one mp4 ────────────────────────────────────────────────────
def render_scene(scene_spec: dict, idx: int, W: int, H: int, fps: int,
                 out_path: Path, work: Path, portrait: bool,
                 total: float = 0.0) -> Path:
    s0, s1 = scene_spec["start"], scene_spec["end"]
    dur = max(0.30, s1 - s0)

    kit = Kit(W, H, s0, s1)
    items = scene_spec.get("gfx", [])
    # Portrait has a lot of vertical air; a giant, very faint copy of the hero
    # icon sits behind the text block so the middle of the frame is not blank.
    if portrait:
        hero = next((d for d in items if d.get("type") == "icon"), None)
        busy = any(d.get("type") in ("panel", "bars", "map", "clock")
                   for d in items)
        if hero and not busy:
            kit.ghost(hero.get("name", "dot"), hero.get("colour", "cyan"))
    for d in items:
        apply_gfx(kit, d, scene_spec, portrait)
    if total:
        kit.progress(s0, total, scene_spec.get("accent", "cyan"))

    doc = assgen.AssDoc(W, H, base_scale=LAYOUTS["portrait" if portrait else "landscape"][2],
                        sub_margin=int(H * 0.115) if portrait else None)
    build_ass(scene_spec, doc, portrait)
    doc.shift(-s0, dur)
    ass_path = work / f"scene_{idx:03d}.ass"
    doc.save(ass_path)

    sc = Scene(index=idx, start=s0, end=s1, kit=kit, ass_path=ass_path,
               mood=scene_spec.get("mood", "night"),
               drift=tuple(scene_spec.get("drift", (26.0, 14.0))))

    bg = assets.backdrop(int(W * 1.16), int(H * 1.16), sc.mood)
    fc, extra = gfx.build_filter_complex(sc, W, H, fps, str(FONT_DIR))

    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
           "-loop", "1", "-framerate", str(fps), "-t", f"{dur:.3f}", "-i", str(bg)]
    for p in extra:
        cmd += ["-loop", "1", "-framerate", str(fps), "-t", f"{dur:.3f}", "-i", p]
    cmd += ["-filter_complex", fc, "-map", "[vfinal]",
            "-t", f"{dur:.3f}", "-r", str(fps),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "19",
            "-pix_fmt", "yuv420p", "-g", str(fps),
            "-an", str(out_path)]
    run(cmd)
    return out_path


# ── audio ───────────────────────────────────────────────────────────────────
def mix_audio(scenes: list[dict], voice: Path | None, out: Path, total: float,
              bed: list | None = None) -> Path:
    if voice is None:
        inputs = [["-f", "lavfi", "-i", f"anullsrc=r=48000:cl=stereo:d={total:.2f}"]]
    else:
        inputs = [["-i", str(voice)]]
    filters = []
    labels = []
    sfx_i = 1
    for sc in scenes:
        for item in sc.get("sfx", []):
            name, off, vol = (item + [0.0, 0.35])[:3] if isinstance(item, list) else (item, 0.0, 0.35)
            p = SFX_DIR / f"{name}.mp3"
            if not p.exists():
                continue
            inputs.append(["-i", str(p)])
            delay = int(max(0.0, sc["start"] + off) * 1000)
            lbl = f"s{sfx_i}"
            filters.append(f"[{sfx_i}:a]volume={vol:.2f},adelay={delay}|{delay},"
                           f"highpass=f=90,alimiter=limit=0.9[{lbl}]")
            labels.append(lbl)
            sfx_i += 1

    for item in (bed or []):
        name, vol = (item + [0.08])[:2] if isinstance(item, list) else (item, 0.08)
        p = SFX_DIR / f"{name}.mp3"
        if not p.exists():
            continue
        inputs.append(["-stream_loop", "-1", "-i", str(p)])
        lbl = f"bed{sfx_i}"
        filters.append(f"[{sfx_i}:a]volume={vol:.2f},atrim=0:{total:.2f},"
                       f"afade=t=in:st=0:d=1.2,afade=t=out:st={max(0.0,total-1.5):.2f}:d=1.5[{lbl}]")
        labels.append(lbl)
        sfx_i += 1

    if labels:
        mix = "".join(f"[{l}]" for l in labels)
        filters.append("[0:a]volume=1.0[narr]")
        filters.append(f"{mix}[narr]amix=inputs={len(labels)+1}:duration=longest:"
                       f"dropout_transition=0:normalize=0,"
                       f"loudnorm=I=-15:TP=-1.5:LRA=11[amixed]")
    else:
        filters.append("[0:a]volume=1.0,loudnorm=I=-15:TP=-1.5:LRA=11[amixed]")

    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
    for pair in inputs:
        cmd += pair
    cmd += ["-filter_complex", ";".join(filters), "-map", "[amixed]",
            "-t", f"{total:.3f}", "-ac", "2", "-c:a", "aac", "-b:a", "192k",
            str(out)]
    run(cmd)
    return out


# ── film ────────────────────────────────────────────────────────────────────
def render_film(spec_path: Path, layout: str, keep: bool = False) -> Path:
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    slug = spec.get("slug", spec_path.parent.name)
    fps = int(spec.get("fps", 30))

    W, H, _scale = LAYOUTS[layout]
    portrait = layout == "portrait"
    out_dir = BUILD / slug / layout
    work = out_dir / "scenes"
    if work.exists() and not keep:
        shutil.rmtree(work)
    work.mkdir(parents=True, exist_ok=True)

    scenes = [dict(s) for s in spec["scenes"]]
    if spec.get("brand"):
        scenes[-1]["_brand"] = spec["brand"]
    for sc in scenes:
        if sc.pop("_brand_pending", None) and spec.get("brand"):
            sc["_brand"] = spec["brand"]
    total = max(sc["end"] for sc in scenes)
    voice = None
    if spec.get("audio"):
        voice = (ROOT / spec["audio"]).resolve()
        if not voice.exists():
            raise SystemExit(f"narration not found: {voice}")
    if voice is None and spec.get("duration"):
        total = float(spec["duration"])

    t_start = time.time()
    segs = []
    for i, sc in enumerate(scenes):
        t0 = time.time()
        p = work / f"seg_{i:03d}.mp4"
        render_scene(sc, i, W, H, fps, p, work, portrait, total)
        segs.append(p)
        log(f"  [{i+1:02d}/{len(scenes)}] {sc['end'] - sc['start']:5.2f}s scene "
            f"in {time.time() - t0:5.2f}s  {sc.get('text','')[:34]}")

    # concat
    listing = work / "concat.txt"
    listing.write_text("".join(f"file '{p.resolve().as_posix()}'\n" for p in segs),
                       encoding="utf-8")
    silent = work / "silent.mp4"
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", str(silent)])

    audio = work / "audio.m4a"
    mix_audio(scenes, voice, audio, total, spec.get("bed"))

    final = out_dir / f"{slug}-{layout}.mp4"
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-i", str(silent), "-i", str(audio),
         "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "copy",
         "-shortest", "-movflags", "+faststart", str(final)])

    log(f"  done in {time.time() - t_start:.1f}s -> {final} "
        f"({final.stat().st_size / 1e6:.1f} MB)")
    return final


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--film", required=True, help="path to a film folder (has spec.json)")
    ap.add_argument("--layout", default="both", choices=["landscape", "portrait", "both"])
    ap.add_argument("--keep", action="store_true")
    a = ap.parse_args()

    fp = Path(a.film)
    spec = fp / "spec.json" if fp.is_dir() else fp
    layouts = ["landscape", "portrait"] if a.layout == "both" else [a.layout]
    for lay in layouts:
        log(f"rendering {spec.parent.name} [{lay}]")
        render_film(spec, lay, a.keep)


if __name__ == "__main__":
    main()
