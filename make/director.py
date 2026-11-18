"""
Director — turns a plain script + narration into a renderable spec.

  python -m make.director --script script.txt --voice voice.mp3 --slug my-film

What it does
------------
1. splits the script into one scene per sentence;
2. aligns each sentence to the narration with whisper (VAD-filtered word
   timestamps), falling back to character-proportional timing;
3. chooses mood / accent / widgets from Bengali keywords, numbers, and
   explicit `@` directives;
4. writes films/<slug>/spec.json (plus a copy of the script for reference).

Script syntax
-------------
    # comment
    রাত তখন প্রায় বারোটা।
    শহরের রাস্তাগুলো একদম ফাঁকা।

Optional directives on the line *before* a sentence::

    @clock 12:30
    রাত তখন প্রায় বারোটা।

    @counter 120000|+|গ্রাহক
    গত বছর গ্রাহক বেড়েছে এক লক্ষ বিশ হাজার।

    @bars ঘুম:38, কাজ:52, বাকি:10
    দিনটা তিন ভাগে ভাগ হয়ে যায়।

    @map ঢাকা:0.55,0.44
    ঢাকা থেকে শুরু।

Other directives: @mood warm, @accent mint, @icon laptop, @head <text>,
@nosub, @brand <text>, @panel, @skyline, @beam, @flash

Everything is overridable — the generated spec is plain JSON.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ── Bengali text helpers ────────────────────────────────────────────────────
BN_DIGITS = "০১২৩৪৫৬৭৮৯"
BN_SCALE = {"হাজার": 1_000, "লাখ": 100_000, "লক্ষ": 100_000,
            "কোটি": 10_000_000}

STOPWORDS = {
    "একটা", "একটি", "আর", "সেই", "তার", "তাকে", "তারা", "এবং", "কিন্তু",
    "করে", "করা", "হলে", "হয়", "হয়েছে", "আছে", "ছিল", "গেল", "গেলে",
    "থেকে", "জন্য", "সাথে", "মধ্যে", "ভিতরে", "বাইরে", "ও", "বা", "না",
    "আমি", "আমরা", "তুমি", "আপনি", "সে", "এই", "ওই", "কি", "কেন", "যখন",
    "তখন", "শুধু", "একদম", "আবার", "খুব", "সব", "সবাই", "নেই", "চলে",
}

FILLER = {"আর", "কারণ", "শুধু", "তখন", "সে", "তার", "সেই", "দিয়ে", "থেকে",
          "জন্য", "সাথে", "আবার", "এবং", "কিন্তু", "তাই", "যদি", "একটা"}

ACCENT_CYCLE = ["cyan", "violet", "mint", "amber", "magenta"]

# keyword → recipe. First match wins; longer phrases are checked first.
TOPICS: list[tuple[tuple[str, ...], dict]] = [
    (("বিদ্যুৎ", "কারেন্ট", "ব্ল্যাকআউট", "চলে গেল"),
     dict(mood="alert", accent="magenta", icon="bolt", flash=True)),
    (("অন্ধকার", "নিঃশব্দ", "একা", "ভয়"),
     dict(mood="dark", accent="violet", icon="moon")),
    (("চাঁদ", "চাঁদের", "জোছনা", "তারারা", "রাত", "মধ্যরাত", "বারোটা"),
     dict(mood="night", accent="cyan", icon="moon", beam=True)),
    (("সূর্য", "সকাল", "ভোর", "দুপুর", "বিকেল"),
     dict(mood="warm", accent="amber", icon="sun")),
    (("শহর", "রাস্তা", "গাড়ি", "বাস", "ট্রেন", "বাজার", "ভিড়", "ট্রাফিক"),
     dict(mood="dark", accent="cyan", icon="globe", skyline=True, map=True)),
    (("স্বপ্ন", "লক্ষ্য", "সাফল্য", "ভবিষ্যৎ", "ইচ্ছা", "আশা"),
     dict(mood="warm", accent="amber", icon="star", ring=True)),
    (("ল্যাপটপ", "অফিস", "পরিশ্রম", "প্রজেক্ট", "কোড", "পড়া", "বই", "কাজে", "কাজ"),
     dict(mood="night", accent="violet", icon="laptop", panel=True)),
    (("টাকা", "আয়", "লাভ", "বিনিয়োগ", "সেভিংস", "ব্যবসা", "বাজেট", "খরচ"),
     dict(mood="cool", accent="mint", icon="coins", bars=True)),
    (("বৃদ্ধি", "বাড়ল", "বেড়েছে", "শতাংশ", "লাখ", "কোটি", "হাজার"),
     dict(mood="cool", accent="mint", icon="trend", bars=True)),
    (("মানুষ", "ছেলে", "মেয়ে", "বন্ধু", "পরিবার", "দল", "গ্রাহক"),
     dict(mood="night", accent="mint", icon="people")),
    (("ফোন", "মোবাইল", "ইন্টারনেট", "টর্চ", "মেসেজ"),
     dict(mood="night", accent="cyan", icon="phone")),
    (("ভালো", "হাসল", "খুশি", "ভালোবাসা", "হৃদয়"),
     dict(mood="warm", accent="magenta", icon="heart")),
    (("স্বাস্থ্য", "শরীর", "ঘুম", "ব্যায়াম", "রোগ", "ওষুধ"),
     dict(mood="cool", accent="mint", icon="check")),
]

TIME_RE = re.compile(r"[০-৯0-9]+\s*টা|ঘণ্টা|মিনিট|সময়|বারোটা|টায়")

SFX_ACCENT = {
    "cyan": "ping",
    "amber": "ping",
    "magenta": "switch",
    "mint": "ping",
    "violet": "pop",
}


def bn_to_int(text: str) -> int:
    """Bengali or latin digits → int (commas, Bengali scale words allowed)."""
    t = "".join(str(BN_DIGITS.index(ch)) if ch in BN_DIGITS else ch for ch in text)
    t = t.replace(",", "").strip()
    m = re.fullmatch(r"(\d+(?:\.\d+)?)", t)
    if not m:
        return 0
    return int(float(m.group(1)))


def has_digit(text: str) -> bool:
    return any(ch in BN_DIGITS for ch in text) or bool(re.search(r"\d", text))


def find_number(text: str) -> tuple[float, str] | None:
    """Return (value, suffix) for 'বেড়েছে ১২০%' style sentences."""
    m = re.search(r"([০-৯0-9][০-৯0-9,.]*)\s*(%|শতাংশ|হাজার|লাখ|লক্ষ|কোটি|টাকা|জন)?",
                  text)
    if not m:
        return None
    raw, unit = m.group(1), (m.group(2) or "")
    val = float(bn_to_int(raw))
    if unit in BN_SCALE:
        val *= BN_SCALE[unit]
    suffix = "%" if unit in ("%", "শতাংশ") else ""
    return val, suffix


def salient_word(text: str, extra: set[str] | None = None) -> str:
    words = [w.strip("।,!?—-‘’\"'") for w in text.split()]
    cands = [w for w in words if w and w not in STOPWORDS and w not in (extra or set())]
    if not cands:
        return ""
    # prefer later clauses, then the longest word
    cands = cands[-3:] or cands
    return max(cands, key=lambda w: (len(w), -text.find(w)))


def headline_for(text: str, emphasise: str = "", max_words: int = 5) -> str:
    """A short, punchy headline: the last clause, trimmed to a readable line."""
    body = text.strip().rstrip("।.!?")
    clauses = [c.strip() for c in re.split(r"[,;—]", body) if c.strip()]
    pick = clauses[-1] if clauses else body
    words = pick.split()
    if len(words) > max_words:
        words = words[-max_words:]
        # never start a headline on a dangling particle
        while len(words) > 2 and words[0] in FILLER:
            words = words[1:]
    return " ".join(words)


def topic_for(text: str) -> dict:
    """Pick the recipe with the most specific (longest) keyword in the sentence."""
    best, best_score = {}, 0
    for keys, recipe in TOPICS:
        for k in keys:
            i = text.find(k)
            if i < 0:
                continue
            score = len(k) * 100 - i
            if score > best_score:
                best, best_score = dict(recipe), score
    return best


# ── script parsing ──────────────────────────────────────────────────────────
def parse_script(text: str) -> tuple[list[dict], dict]:
    meta: dict = {}
    scenes: list[dict] = []
    pending: dict = {}

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("//"):
            continue
        if line.startswith("#"):
            body = line.lstrip("#").strip()
            if ":" in body:
                k, v = body.split(":", 1)
                meta[k.strip()] = v.strip()
            continue
        if line.startswith("@"):
            cmd, _, arg = line[1:].partition(" ")
            pending[cmd.strip()] = arg.strip()
            continue

        sentences = [s.strip() for s in re.split(r"(?<=[।?!])\s+", line) if s.strip()]
        for s in sentences:
            if s:
                scenes.append({"text": s, **pending})
        pending = {}
    return scenes, meta


# ── alignment ───────────────────────────────────────────────────────────────
def transcribe(audio: Path) -> list[dict]:
    from faster_whisper import WhisperModel

    model = WhisperModel("tiny", device="cpu", compute_type="int8")
    segments, _info = model.transcribe(
        str(audio), language="bn", vad_filter=True,
        word_timestamps=True, beam_size=1, temperature=0.0,
    )
    out = []
    for seg in segments:
        words = [(w.start, w.end) for w in (seg.words or [])]
        if not words:
            words = [(seg.start, seg.end)]
        out.append({
            "start": words[0][0],
            "end": words[-1][1],
            "words": len(words),
            "text": (seg.text or "").strip(),
        })
    return [s for s in out if s["end"] > s["start"]]


def align(sentences: list[str], audio: Path) -> list[tuple[float, float]]:
    """Sentence → (start, end). Whisper segments when they line up, else weights."""
    try:
        segs = transcribe(audio)
    except Exception as exc:  # no whisper, no problem
        print(f"  ! transcription failed ({exc}); using even timing", file=sys.stderr)
        segs = []

    total = probe_duration(audio)
    if len(segs) == len(sentences) and segs:
        spans = [(s["start"], s["end"]) for s in segs]
        spans[-1] = (spans[-1][0], min(total, spans[-1][1] + 0.30))
        return spans

    if segs:
        lo, hi = segs[0]["start"], min(total, segs[-1]["end"] + 0.30)
    else:
        lo, hi = 0.0, min(total, 0.62 * len(sentences) + 1.0)

    weights = [max(1.0, len(s) ** 0.92) for s in sentences]
    scale = (hi - lo) / sum(weights)
    spans, t = [], lo
    for i, w in enumerate(weights):
        d = w * scale
        # a small breath before each new sentence
        gap = 0.0 if i == 0 else min(0.16, d * 0.10)
        spans.append((t + gap, t + d))
        t += d
    return spans


def probe_duration(path: Path) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


# ── scene synthesis ─────────────────────────────────────────────────────────
def build_scene(text: str, start: float, end: float, idx: int,
                directives: dict) -> dict:
    dur = max(0.6, end - start)
    recipe = topic_for(text)
    mood = directives.get("mood") or recipe.get("mood") or "night"
    accent = directives.get("accent") or recipe.get("accent") or ACCENT_CYCLE[idx % 5]

    head = directives.get("head") or headline_for(text)
    emph = salient_word(head) or salient_word(text)

    gfx: list[dict] = []
    counter: dict | None = None
    done: set[str] = set()

    # ── explicit widgets (directives) ───────────────────────────────────────
    if "clock" in directives:
        hh, _, mm = directives["clock"].partition(":")
        gfx.append({"type": "clock", "at": [0.745, 0.42], "at_p": [0.5, 0.60],
                    "size": 0.28, "size_p": 0.44, "hours": int(hh or 12),
                    "minutes": int(mm or 0), "colour": accent})
        done.add("clock")

    if "counter" in directives:
        parts = [p.strip() for p in directives["counter"].split("|")]
        val = float(bn_to_int(parts[0].replace("%", "")))
        suffix = parts[1] if len(parts) > 1 else ("%" if "%" in parts[0] else "")
        label = parts[2] if len(parts) > 2 else ""
        counter = counter_spec(val, suffix, label)
        done.add("counter")

    if "bars" in directives:
        items = []
        for chunk in directives["bars"].split(","):
            name, _, val = chunk.partition(":")
            items.append([name.strip(), max(1.0, float(bn_to_int(val) or 1))])
        build_bars(gfx, items, accent)
        done.add("bars")

    if "map" in directives:
        pin = [0.55, 0.44]
        spec = directives["map"]
        if ":" in spec:
            _, _, coords = spec.partition(":")
            try:
                pin = [float(v) for v in coords.split(",")[:2]]
            except ValueError:
                pass
        gfx.append({"type": "map", "at": [0.5, 0.52], "at_p": [0.5, 0.56],
                    "size": [0.42, 0.32], "size_p": [0.86, 0.34],
                    "pin_at": pin, "pin_colour": accent, "start": 0.1})
        done.add("map")

    # ── inferred widgets ────────────────────────────────────────────────────
    if not done:
        num = find_number(text)
        if num and num[0] >= 10:
            counter = counter_spec(num[0], num[1], "")
            done.add("counter")
        elif TIME_RE.search(text):
            gfx.append({"type": "clock", "at": [0.745, 0.42], "at_p": [0.5, 0.60],
                        "size": 0.28, "size_p": 0.44, "hours": 12, "minutes": 30,
                        "colour": accent})
            done.add("clock")

    # ── atmosphere, drawn first so it stays behind the layout ───────────────
    if recipe.get("beam") or directives.get("beam"):
        gfx.insert(0, {"type": "beam", "colour": "white",
                       "at": [0.30, 0.46], "at_p": [0.42, 0.40],
                       "size": [0.60, 1.15], "size_p": [0.85, 0.90],
                       "angle": -20, "start": 0.0})
    if recipe.get("skyline") or directives.get("skyline"):
        gfx.insert(0, {"type": "skyline", "colour": accent, "height": 0.36,
                       "seed": 6 + idx, "start": 0.0})
    if recipe.get("flash") or directives.get("flash"):
        gfx.insert(0, {"type": "flash", "start": 0.0, "dur": 0.12})
    if mood in ("dark", "alert"):
        gfx.append({"type": "shade", "alpha": 0.40, "height": 1.0,
                    "from_bottom": False})

    # ── hero icon (+ its panel) ─────────────────────────────────────────────
    icon = directives.get("icon") or recipe.get("icon")
    has_panel = bool(recipe.get("panel") or directives.get("panel"))
    if recipe.get("flash"):
        hero, hero_size, hero_p, hero_size_p = [0.5, 0.295], 0.19, [0.5, 0.36], 0.24
    elif has_panel:
        hero, hero_size, hero_p, hero_size_p = [0.765, 0.455], 0.15, [0.5, 0.62], 0.19
    else:
        hero, hero_size, hero_p, hero_size_p = [0.862, 0.195], 0.115, [0.74, 0.19], 0.13
    if icon and not counter and not ({"bars", "map"} & done) \
            and not any(g["type"] == "icon" for g in gfx):
        if has_panel:
            gfx.append({"type": "panel", "at": hero, "at_p": [0.5, 0.62],
                        "size": [0.25, 0.24], "size_p": [0.62, 0.20],
                        "colour": "ink", "border": accent, "enter": "slideR",
                        "radius": 34, "alpha": 190})
        gfx.append({
            "type": "icon", "name": icon, "colour": accent,
            "at": hero, "at_p": hero_p,
            "size": hero_size, "size_p": hero_size_p,
            "enter": "pop", "ring": bool(recipe.get("ring")),
            "start": 0.10,
        })

    # ── layout: where the headline lives, and its signature rule ────────────
    scene = {
        "text": text,
        "head": head,
        "emphasise": [emph] if emph else [],
        "start": round(start, 3),
        "end": round(end, 3),
        "mood": mood,
        "accent": accent,
        "gfx": gfx,
        "sfx": [["whoosh", 0.0, 0.45], [SFX_ACCENT.get(accent, "ping"), 0.14, 0.26]],
    }
    head_at, head_at_p = [0.5, 0.40], [0.5, 0.34]
    rule_at, rule_at_p = [0.5, 0.475], [0.5, 0.44]
    head_max_w = 0.90

    if counter:
        scene["counter"] = counter
        scene["head"] = ""
        scene["kicker"] = kicker_for(text, 2 if counter.get("label") else 3)
        scene["kicker_at"] = [0.5, 0.255]
        scene["kicker_at_p"] = [0.5, 0.24]
        scene["counter_at"] = [0.5, 0.435]
        scene["counter_at_p"] = [0.5, 0.42]
        gfx.append({"type": "rule", "at": [0.5, 0.335], "at_p": [0.5, 0.375],
                    "width": 0.10, "colour": accent, "start": 0.14})
        if counter.get("label"):
            scene["counter"]["label_at"] = [0.5, 0.575]
            scene["counter"]["label_at_p"] = [0.5, 0.52]
    elif "bars" in done:
        head_at, rule_at = [0.5, 0.285], [0.5, 0.36]
        head_at_p, rule_at_p = [0.5, 0.235], [0.5, 0.31]
    elif "map" in done:
        head_at, rule_at = [0.5, 0.235], [0.5, 0.315]
        head_at_p, rule_at_p = [0.5, 0.215], [0.5, 0.295]
    elif has_panel:
        head_at, rule_at = [0.335, 0.435], [0.335, 0.512]
        head_at_p, rule_at_p = [0.5, 0.335], [0.5, 0.412]
        head_max_w = 0.58
    elif recipe.get("flash"):
        head_at, head_at_p = [0.5, 0.66], [0.5, 0.60]
        rule_at, rule_at_p = [0.5, 0.738], [0.5, 0.678]
    elif any(g["type"] == "clock" for g in gfx):
        head_at, rule_at = [0.345, 0.40], [0.345, 0.477]
        head_at_p, rule_at_p = [0.5, 0.30], [0.5, 0.375]
        head_max_w = 0.60

    scene["head_at"], scene["head_at_p"] = head_at, head_at_p
    scene["head_max_w"] = head_max_w
    if not counter:
        gfx.append({"type": "rule", "at": rule_at, "at_p": rule_at_p,
                    "width": 0.12, "colour": accent, "start": 0.22})
    if recipe.get("flash"):
        scene["head_style"] = "HeadBig"
    if directives.get("nosub"):
        scene["sub"] = False
    if dur < 2.0:
        scene["head_delay"] = 0.06
        scene["head_enter"] = 300
    return scene


def kicker_for(text: str, n: int = 3) -> str:
    """Short eyebrow above a stat: the opening words carry the context."""
    words = text.strip().rstrip("।.!?").split()
    return " ".join(words[:n])


def counter_spec(value: float, suffix: str, label: str) -> dict:
    return {
        "value": value,
        "suffix": suffix,
        "label": label,
        "delay": 0.22,
        "ease": 3.2,
        "style": "Num",
    }


def build_bars(gfx: list, items: list, accent: str) -> None:
    gfx.append({"type": "bars", "items": items, "at": [0.14, 0.47],
                "at_p": [0.19, 0.42], "width": 0.38, "width_p": 0.54,
                "row_gap": 0.078, "colour": accent, "delay": 0.28,
                "value_fmt": "num", "value_fmt_p": "num"})


def director(script: Path, voice: Path | None, slug: str, out: Path,
             brand: str = "", bed: str = "amb-night") -> Path:
    text = script.read_text(encoding="utf-8")
    raw_scenes, meta = parse_script(text)
    if not raw_scenes:
        raise SystemExit("script has no sentences")
    for spec in raw_scenes:
        if spec.get("brand"):
            meta["brand"] = spec["brand"]

    sentences = [s["text"] for s in raw_scenes]
    if voice:
        spans = align(sentences, voice)
        total = probe_duration(voice)
        # scenes must tile the timeline exactly: one cut every boundary, no gaps
        bounds = [0.0]
        for i in range(len(spans) - 1):
            bounds.append(round((spans[i][1] + spans[i + 1][0]) / 2, 3))
        bounds.append(round(total, 3))
        spans = list(zip(bounds[:-1], bounds[1:]))
    else:
        spans = [(i * 2.8, (i + 1) * 2.8) for i in range(len(sentences))]
        total = len(sentences) * 2.8

    scenes = []
    for i, (spec, (a, b)) in enumerate(zip(raw_scenes, spans)):
        scenes.append(build_scene(spec["text"], a, b, i, spec))

    # hold the final frame a moment after the last word
    scenes[-1]["end"] = round(min(total, max(scenes[-1]["end"],
                                             scenes[-1]["start"] + 1.2)), 3)

    doc = {
        "slug": slug,
        "title": meta.get("title") or scenes[0]["head"],
        "brand": meta.get("brand", brand),
        "fps": int(meta.get("fps", 30)),
        "bed": [[meta.get("bed", bed), 0.09]],
        "scenes": scenes,
    }
    if voice:
        try:
            rel = voice.resolve().relative_to(ROOT)
            doc["audio"] = rel.as_posix()
        except ValueError:
            doc["audio"] = str(voice.resolve())

    out.mkdir(parents=True, exist_ok=True)
    (out / "spec.json").write_text(
        json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "script.txt").write_text(text, encoding="utf-8")
    return out / "spec.json"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--script", required=True)
    ap.add_argument("--voice")
    ap.add_argument("--slug")
    ap.add_argument("--out")
    ap.add_argument("--brand", default="একটি ছোট গল্প")
    ap.add_argument("--bed", default="amb-night")
    a = ap.parse_args()

    script = Path(a.script)
    slug = a.slug or re.sub(r"[^a-z0-9]+", "-", script.stem.lower()).strip("-")
    out = Path(a.out) if a.out else ROOT / "films" / slug
    voice = Path(a.voice) if a.voice else None
    if voice and not voice.exists():
        raise SystemExit(f"voice not found: {voice}")

    spec = director(script, voice, slug, out, a.brand, a.bed)
    doc = json.loads(spec.read_text(encoding="utf-8"))
    print(f"wrote {spec}  ({len(doc['scenes'])} scenes, "
          f"{doc['scenes'][-1]['end']:.1f}s)")
    for s in doc["scenes"]:
        kinds = ",".join(g["type"] for g in s["gfx"])
        title = s.get("head") or s.get("kicker", "")
        print(f"  {s['start']:6.2f}-{s['end']:6.2f}  {s['accent']:<8} "
              f"{s['mood']:<5} [{kinds}]  {title}")


if __name__ == "__main__":
    main()
