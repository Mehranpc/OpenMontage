"""Build the persistent Remotion Studio preview props for coffee-hormones-fa.

The Studio proposition: `remotion-composer/.studio-props/coffee-hormones-fa.json`
is a hand-built props file that opens the finished video inside Remotion Studio
for visual inspection — scrubbing, frame checks, typography review — without
re-running the pipeline. It is the user's live Studio entry point; do not delete
it.

What it does: reads `projects/coffee-hormones-fa/artifacts/edit_decisions.json`,
mirrors `PersianCompose._build_props` / `_build_moments` exactly (same shot
fields, same moment construction with audits and stack heights), except media is
staged under stable deterministic names in
`remotion-composer/public/persian/coffee-hormones-fa/` instead of the random
run-id directory a pipeline render uses. Stable names mean the props file keeps
working across runs instead of pointing at a staging directory the compose tool
already cleaned up.

What it reads:
- `projects/coffee-hormones-fa/artifacts/edit_decisions.json` — shots, moments,
  audio, watermark, typographic beats.
- Every media file the edit references (shot sources, narration, music bed).

What it writes:
- `remotion-composer/public/persian/coffee-hormones-fa/` — the staged clips and
  audio under deterministic names (`<shot-id>-<filename>`, `narration.mp3`,
  `bed.mp3`).
- `remotion-composer/.studio-props/coffee-hormones-fa.json` — the props file.

How to use it (run from the repo root):

    .venv/bin/python scripts/build_studio_props.py
    cd remotion-composer && npx remotion studio --props=./.studio-props/coffee-hormones-fa.json

Then open the `PersianFootageVertical` composition in Studio.

Warning: never pass `--public-dir` to this pipeline. The composition loads its
Persian font from `public/fonts/estedad/`, and `--public-dir` REPLACES the
default public dir for the render — the font vanishes, `delayRender` never
resolves, and the render hangs rather than failing. Staging the media inside the
real `public/` tree is what keeps the fonts visible.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from lib.persian_music import build_music_track  # noqa: E402
from tools.video.persian_compose import PersianCompose  # noqa: E402

PROJECT = REPO_ROOT / "projects" / "coffee-hormones-fa"
COMPOSER = REPO_ROOT / "remotion-composer"
STAGE = COMPOSER / "public" / "persian" / "coffee-hormones-fa"


def stage_stable(source: str, name: str) -> str:
    resolved = (REPO_ROOT / source).resolve()
    if not resolved.exists():
        raise FileNotFoundError(f"Media file not found: {source}")
    target = STAGE / name
    shutil.copy2(resolved, target)
    return f"persian/coffee-hormones-fa/{name}"


def main() -> None:
    STAGE.mkdir(parents=True, exist_ok=True)

    ed = json.loads(
        (PROJECT / "artifacts" / "edit_decisions.json").read_text(encoding="utf-8")
    )
    persian = ed["persian"]

    # -- shots: same fields as PersianCompose._build_props -------------------------
    shots = []
    for index, shot in enumerate(persian.get("shots") or []):
        source = shot.get("source") or shot.get("path")
        if not source:
            raise ValueError(f"shot[{index}] has no source path")
        attribution = str(shot.get("attribution") or "").strip()
        if not attribution:
            raise ValueError(f"shot[{index}] ({source}) has no attribution")
        staged = stage_stable(source, f"{shot.get('id') or f'shot-{index + 1}'}-{Path(source).name}")
        shots.append(
            {
                "id": str(shot.get("id") or f"shot-{index + 1}"),
                "source": staged,
                "startSeconds": float(shot["startSeconds"]),
                "endSeconds": float(shot["endSeconds"]),
                "sourceInSeconds": float(shot.get("sourceInSeconds") or 0.0),
                "camera": str(shot.get("camera") or "none"),
                "attribution": attribution,
            }
        )

    # -- audio: same keys as PersianCompose._build_props ----------------------------
    audio_props: dict = {}
    audio = persian.get("audio") or {}
    if audio.get("narration"):
        audio_props["narration"] = stage_stable(audio["narration"], "narration.mp3")
    if audio.get("music"):
        audio_props["music"] = stage_stable(audio["music"], "bed.mp3")
    for key in ("musicFlatVolume", "musicBaseVolume", "musicDuckVolume", "musicFadeSeconds"):
        if audio.get(key) is not None:
            audio_props[key] = float(audio[key])
    raw_track = persian.get("musicTrack")
    track = build_music_track(raw_track) if raw_track else None
    if track is not None:
        audio_props["music"] = stage_stable(track.path, "bed.mp3")
        audio_props.setdefault("musicFadeSeconds", 1.5)

    # -- moments: the real pipeline path (build + audits + stack heights) ----------
    duration_seconds = float(persian["durationSeconds"])
    moments = PersianCompose._build_moments(persian, duration_seconds)

    props = {
        "format": str(persian.get("format") or "vertical"),
        "durationSeconds": duration_seconds,
        "shots": shots,
        "moments": moments,
        "typographicBeats": list(persian.get("typographicBeats") or []),
    }
    if audio_props:
        props["audio"] = audio_props
    if persian.get("watermark"):
        props["watermark"] = persian["watermark"]

    out = COMPOSER / ".studio-props" / "coffee-hormones-fa.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(props, ensure_ascii=False, indent=1), encoding="utf-8")

    total = sum(p.stat().st_size for p in STAGE.iterdir() if p.is_file())
    print(f"props: {out} ({out.stat().st_size} bytes)")
    print(f"shots: {len(shots)}, moments: {len(moments)}")
    print(f"staged files: {sorted(p.name for p in STAGE.iterdir())}")
    print(f"staged total bytes: {total} ({total / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
