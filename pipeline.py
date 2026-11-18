"""
One command: script + narration → finished film(s).

  python pipeline.py --script my-script.txt --voice voice.mp3 --slug my-film

Stages
  1. director  — sentence timing, kinetic layout, widgets → films/<slug>/spec.json
  2. build     — per-scene encode, concat, audio mix → build/<slug>/<layout>/*.mp4

Re-run with --force to re-time after changing the narration. If only the
graphics need tweaking, edit films/<slug>/spec.json and run:

  python -m make.build --film films/<slug> --layout both
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from make import director as dr          # noqa: E402
from make.build import LAYOUTS, log, render_film  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--script", required=True, help="plain-text script (UTF-8)")
    ap.add_argument("--voice", help="narration audio (mp3/wav/m4a)")
    ap.add_argument("--slug", required=True, help="output name, e.g. rat-tokhon")
    ap.add_argument("--film-dir", help="where spec.json lives (default films/<slug>)")
    ap.add_argument("--layout", default="both",
                    choices=["landscape", "portrait", "both"])
    ap.add_argument("--force", action="store_true", help="re-time and overwrite spec")
    ap.add_argument("--keep", action="store_true", help="keep per-scene segments")
    ap.add_argument("--draft", action="store_true",
                    help="720p preview render (~2x faster, same composition)")
    ap.add_argument("--no-render", action="store_true", help="only write spec.json")
    a = ap.parse_args()

    script = Path(a.script)
    if not script.exists():
        raise SystemExit(f"script not found: {script}")
    voice = Path(a.voice) if a.voice else None
    if voice and not voice.exists():
        raise SystemExit(f"voice not found: {voice}")

    film_dir = Path(a.film_dir) if a.film_dir else HERE / "films" / a.slug
    spec = film_dir / "spec.json"
    fresh = a.force or not spec.exists()

    t0 = time.time()
    if fresh:
        dr.director(script, voice, a.slug, film_dir)
        doc = json.loads(spec.read_text(encoding="utf-8"))
        log(f"  spec: {len(doc['scenes'])} scenes, "
            f"{doc['scenes'][-1]['end']:.1f}s, "
            f"{'narrated' if doc.get('audio') else 'silent'}")
    else:
        log(f"  spec is up to date: {spec}")

    if a.no_render:
        return

    layouts = ["landscape", "portrait"] if a.layout == "both" else [a.layout]
    made = []
    for lay in layouts:
        log(f"rendering {a.slug} [{lay}{' draft' if a.draft else ''}]  "
            f"{LAYOUTS[lay][0]}x{LAYOUTS[lay][1]}")
        made.append(render_film(spec, lay, a.keep, a.draft))

    log(f"finished {len(made)} file(s) in {time.time() - t0:.0f}s")
    for p in made:
        log(f"  {p}  ({p.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
