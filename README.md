# fast-video

Turn a **Bengali script + voiceover** into a finished motion-graphics film —
landscape for YouTube, portrait for Facebook/Reels — in a couple of minutes of
machine time per minute of video.

No editor, no timeline scrubbing, no paid services. You supply two files; the
pipeline does the directing.

```
script.txt ──► director ──► spec.json ──► ffmpeg ──► film-landscape.mp4
voice.mp3  ──┘   (timing,    (scenes,     (one pass    film-portrait.mp4
                 layout)      widgets)     per scene)
```

**Measured speed** on a modest laptop (26.5 s film, 9 scenes):

| pass | time | note |
|---|---|---|
| first ever render | ~2.5 min | includes ~18 s whisper + ~40 s texture cache |
| re-render, landscape | ~80 s | ~3× real time |
| re-render, portrait | ~65–95 s | same |
| `--draft` (720p) | ~43 s | ~2× faster, same composition |

A 10-minute film therefore lands around 30 minutes per orientation locally —
and on a GitHub Actions runner you don't pay that cost at all.

---

## 1. Install

Requirements: **Python 3.11+** and an **ffmpeg** build with `libass`,
`libharfbuzz` and `gradfun`.

```powershell
# Windows
winget install Gyan.FFmpeg
cd fast-video
python -m pip install -r requirements.txt
```

```bash
# Linux
sudo apt-get install -y ffmpeg
cd fast-video
python -m pip install -r requirements.txt
```

Check the ffmpeg build:

```bash
ffmpeg -hide_banner -filters | findstr " ass "
```

Everything else ships with the repo: Noto Sans Bengali + Anton fonts
(`assets/fonts/`), 57 sound effects (`assets/sfx/`), and the Bengali shaping
stack (libass uses HarfBuzz, so conjuncts render correctly).

---

## 2. Quick start

Put your files in a film folder:

```
films/my-film/
├── script.txt     ← one sentence per line
└── voice.mp3      ← your narration
```

Run one command:

```powershell
python pipeline.py --script films/my-film/script.txt --voice films/my-film/voice.mp3 --slug my-film
```

Output:

```
build/my-film/landscape/my-film-landscape.mp4   1920×1080
build/my-film/portrait/my-film-portrait.mp4     1080×1920
```

Useful flags:

| flag | effect |
|---|---|
| `--layout landscape` | only one orientation |
| `--force` | re-time from the narration and overwrite `spec.json` |
| `--no-render` | only write the spec (cheap preview of the edit) |
| `--draft` | 720p preview render, about twice as fast |
| `--keep` | keep the per-scene segments for inspection |

Encoders are not the bottleneck: switching x264 to `superfast`/`ultrafast`
measured under 10% (env `FV_PRESET=superfast`, `FV_DEBAND=0`). The time goes
into libass text shaping and the overlay compositor, so `--draft` (fewer
pixels) or the cloud runner are the real levers.

---

## 3. Writing the script

One sentence per line. Punctuation (`।`, `?`, `!`) splits lines into scenes.
`#` lines are metadata, `@` lines are directives for the **next** sentence.

```text
# title: রাত তখন প্রায় বারোটা
# brand: একটি ছোট গল্প
# bed: amb-night

রাত তখন প্রায় বারোটা।
শহরের রাস্তাগুলো একদম ফাঁকা।
একটা ছেলে জানালার পাশে বসে ল্যাপটপে কাজ করছে।
হঠাৎ বিদ্যুৎ চলে গেল!
চারপাশ অন্ধকার।
শুধু জানালা দিয়ে আসা চাঁদের আলো তার মুখে পড়ছে।
সে একটু হাসল, ফোনের টর্চ জ্বালাল, আর আবার কাজে ফিরে গেল।
কারণ তার একটা স্বপ্ন আছে।
আর সেই স্বপ্ন পূরণ করতে হলে, তাকে থেমে গেলে চলবে না।
```

If you write nothing but the sentences, the director still picks a mood,
accent colour, icon, and headline for every scene — that is the point. The
directives below only override what you want to control.

### Directives

| directive | result |
|---|---|
| `@clock 12:30` | animated clock, hands sweep |
| `@counter 125000\|+\|গ্রাহক` | count-up stat: value, suffix, label |
| `@counter 38\|%\|বৃদ্ধি` | percentage count-up |
| `@bars ঢাকা:52, চট্টগ্রাম:31, খুলনা:17` | animated bar chart with labels |
| `@map ঢাকা:0.56,0.46` | map plate with a pin at that relative position |
| `@icon laptop` | force the hero icon |
| `@mood warm` | `night`, `dark`, `warm`, `cool`, `alert` |
| `@accent mint` | `cyan`, `violet`, `mint`, `amber`, `magenta` |
| `@head মনের আগুন` | force the headline |
| `@panel`, `@skyline`, `@beam`, `@flash` | force an atmosphere layer |
| `@nosub` | hide the caption for this scene |

Numbers written in Bengali digits (`১,২৫,০০০`) or Latin digits both work.

### What gets inferred

| in the sentence | on screen |
|---|---|
| a number ≥ 10, or `%`, `লাখ`, `কোটি` | count-up number with Indian grouping (`১,২৫,০০০` → `1,25,000`) |
| `টা`, `ঘণ্টা`, `মিনিট`, `সময়` | animated clock |
| `শহর`, `রাস্তা`, `বাজার`, `ভিড়` | neon skyline + globe |
| `চাঁদ`, `রাত`, `জোছনা` | moonlight beam + moon, night palette |
| `বিদ্যুৎ`, `কারেন্ট` | lightning flash + bolt |
| `স্বপ্ন`, `লক্ষ্য`, `সাফল্য` | star in a ring, warm palette |
| `ল্যাপটপ`, `কাজ`, `অফিস` | laptop panel |
| `টাকা`, `আয়`, `লাভ`, `বৃদ্ধি` | coins / bar chart, cool palette |
| `ফোন`, `টর্চ`, `ইন্টারনেট` | phone icon |
| `হাসল`, `খুশি`, `ভালোবাসা` | heart, warm palette |

Every scene also gets the house signature: a headline that pops in with a
per-word accent pulse, a growing accent rule underneath, a bottom caption, and
a thin scroll-progress bar across the very top.

---

## 4. How the timing works

1. `faster-whisper` (`tiny`, CPU) transcribes the narration with VAD and word
   timestamps. Bengali transcription quality doesn't matter — only *where the
   speech is*.
2. Script sentences are aligned to whisper's segments when the counts match,
   otherwise allocated proportionally by sentence length.
3. Scene boundaries are placed midway between the end of one sentence and the
   start of the next, so scenes tile the timeline with **no gaps** — this is
   what keeps captions, graphics and audio locked together.

Whisper runs once per film; the result lives in `spec.json` afterwards, so
re-renders are instant.

---

## 5. Editing after the fact

`films/<slug>/spec.json` is plain JSON and the whole design is exposed:

```json
{
  "text": "শুধু জানালা দিয়ে আসা চাঁদের আলো তার মুখে পড়ছে।",
  "head": "চাঁদের আলো তার মুখে",
  "emphasise": ["চাঁদের"],
  "start": 11.42, "end": 15.40,
  "mood": "night", "accent": "cyan",
  "head_at": [0.36, 0.52],
  "gfx": [
    {"type": "beam", "colour": "white", "at": [0.30, 0.46],
     "size": [0.60, 1.15], "angle": -20},
    {"type": "icon", "name": "moon", "colour": "amber",
     "at": [0.82, 0.20], "size": 0.15, "ring": true}
  ],
  "sfx": [["whoosh", 0.0, 0.40], ["ping", 1.1, 0.22]]
}
```

All positions are **fractions of the canvas** (`0..1`), so one spec renders to
both orientations. Add a `_p` variant to override a value for portrait only
(`at_p`, `size_p`, `head_at_p`, `width_p`, …).

Then re-render without touching the timing:

```powershell
python -m make.build --film films/my-film --layout both
```

### Widgets

| `type` | keys |
|---|---|
| `icon` | `name`, `colour`, `at`, `size`, `enter` (`pop`/`slideL`/…), `ring` |
| `panel` | `at`, `size`, `colour`, `border`, `alpha`, `radius`, `enter` |
| `bars` | `items` (`[[label, value], …]`), `at`, `width`, `row_gap`, `value_fmt` |
| `clock` | `at`, `size`, `hours`, `minutes`, `sweep` |
| `map` | `at`, `size`, `pin_at`, `pin_colour` |
| `rule` / `line` | `at`, `width`, `colour`, `thick`, `delay` |
| `skyline` | `colour`, `height`, `seed` |
| `beam` | `at`, `size`, `colour`, `angle` |
| `shade` | `alpha`, `height`, `from_bottom` |
| `flash` | `start`, `dur` |
| `counter` (scene-level) | `value`, `prefix`, `suffix`, `decimals`, `label` |

Icon names: `bolt`, `moon`, `sun`, `laptop`, `phone`, `clock`, `chart`,
`trend`, `globe`, `star`, `heart`, `check`, `pin`, `target`, `book`, `coins`,
`people`, `dot`.

`assets/sfx/LIBRARY.txt` lists every sound; reference one by filename stem in
`"sfx": [["whoosh", 0.0, 0.45]]` (name, offset in seconds, volume).

---

## 6. Rendering on GitHub Actions (free)

The workflow in `.github/workflows/render.yml` renders on GitHub's machines.
For **public** repos this is unlimited; for private repos the free tier
(2,000 min/month) covers roughly 80 ten-minute films.

1. Put `films/<slug>/script.txt` and `films/<slug>/voice.mp3` in the repo.
2. **Actions → render → Run workflow**, `slug = <slug>` (or `all`).
3. Download `films-<run>.mp4` from the run's **Artifacts**.

The whisper model is cached between runs, and the workflow attaches the videos
to a GitHub Release when you push a tag like `v1`.

---

## 7. Why it is fast

* **One ffmpeg pass per scene.** No frame-server, no Python per frame.
* **Text is not drawn by Python.** Bengali is shaped by libass/HarfBuzz from a
  generated `.ass` file — correct conjuncts *and* animated typography, in one
  filter.
* **Graphics are textures + compositor expressions.** Panels, icons and maps are
  Pillow-generated PNGs cached once; all motion (drift, slide, pop, sweep,
  count-up) is expressed in ffmpeg's expression language.
* **Concat is stream-copy**, and the audio is mixed in a single `amix`/
  `loudnorm` pass.

---

## 8. Troubleshooting

**Glyphs look separated (`দ া ড়ি় য়েছ`).** Letter-spacing (`\fsp`) breaks
Bengali clusters in libass. The built-in styles use `Spacing = 0`; don't add
`\fsp` to Bengali text.

**Bengali renders as boxes.** `assets/fonts/` must contain the Noto Sans Bengali
files; they are passed to libass via `fontsdir`.

**`No such filter: 'subtitles'` / `ass`.** Install an ffmpeg build with libass
(Gyan's Windows build, or your distro's ffmpeg).

**Captions drift from the voice.** Run with `--force` so the director re-times
from the narration, and don't edit `start`/`end` by hand unless you also keep
them contiguous.

**Whisper fails to install.** It needs `av`; the pinned version in
`requirements.txt` is known-good.

---

## 9. Layout

```
fast-video/
├── pipeline.py            script + voice → film
├── make/
│   ├── director.py        script → timing + spec
│   ├── build.py           orchestration, audio, concat
│   ├── assgen.py          ASS typography and animation
│   ├── gfx.py             ffmpeg compositor (layers, expressions)
│   └── assets.py          Pillow textures: backdrops, icons, map, clock
├── films/
│   ├── rat-tokhon/        story demo (narrated)
│   └── demo-stats/        data-viz demo (silent, shows counter/bars/map)
├── assets/
│   ├── fonts/             Noto Sans Bengali, Anton
│   └── sfx/               57 effects + LIBRARY.txt
└── .github/workflows/     free cloud rendering
```
