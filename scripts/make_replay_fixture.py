"""Build a replay fixture from an exported production run, keeping no real media (#264).

    python -m scripts.make_replay_fixture <exported-project-dir> <fixture-dir>

The fixture serves `scripts.persian_run_replay --fixture` with the run's *own*
provider results instead of another run's:

- `recorded/search-cache/`: the run's `assets/.search-cache/*.json`, unchanged
  (timing and metadata only);
- `recorded/transcript.json`: the run's transcriber output;
- `recorded/word-timings.json`: the run's committed script word timings;
- `clips/<clip_id>.mp4`: a **synthetic** clip for every clip the run discovered,
  at the recorded width, height and duration (from the discovery records, so the
  export's media are never read);
- `narration.mp3`, `music-bed.mp3`: **synthetic**, at the recorded durations;
- `approved_script.txt` and the command log's `.telemetry/` needed by replay.

No file from the export's media is copied. The real footage, narration and music
stay on the machine that made the export (the #273 history lesson).
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
from pathlib import Path

_MEDIA_SUFFIXES = {".mp4", ".mov", ".mp3", ".wav", ".m4a", ".png", ".jpg", ".jpeg", ".webp"}


def _ffmpeg(args: list[str]) -> None:
    subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-v", "error", "-y", *args], check=True,
                   stdin=subprocess.DEVNULL)


def _synthetic_clip(path: Path, width: int, height: int, duration: float, seed: int, fps: float = 30.0) -> None:
    """A flat colour at the recorded geometry, frame rate and duration.

    Only width, height and duration are ever read from a replayed clip (ffprobe at
    download, geometry at review), so the content is as cheap as ffmpeg allows.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    shade = 0x40 + (seed * 37) % 0x60
    _ffmpeg([
        # The recorded frame rate is kept: durations are compared exactly downstream,
        # and 9.633s at 30 fps is 9.6s at 5 fps.
        "-f", "lavfi", "-i", f"color=c=0x{shade:02x}{shade:02x}{shade:02x}:s={width}x{height}:r={fps:g}:d={duration:.6f}",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "51", "-pix_fmt", "yuv420p", "-an", str(path),
    ])


def _synthetic_audio(path: Path, duration: float, *, tone: bool) -> None:
    source = f"sine=f=220:d={duration:.3f}" if tone else f"anoisesrc=d={duration:.3f}:c=pink:r=44100:a=0.2"
    _ffmpeg(["-f", "lavfi", "-i", source, "-ac", "1", "-ar", "44100", "-c:a", "libmp3lame", "-b:a", "64k",
             "-t", f"{duration:.3f}", str(path)])


def _fps(row: dict | None) -> float:
    extra = (row or {}).get("extra") if isinstance((row or {}).get("extra"), dict) else {}
    try:
        value = float(extra.get("fps") or 30.0)
    except (TypeError, ValueError):
        value = 30.0
    return value if 1.0 <= value <= 120.0 else 30.0


def _duration_of_words(timings: dict) -> float:
    words = timings.get("words") or []
    return max((float(w.get("end") or 0.0) for w in words), default=1.0) + 1.0


def build(export: Path, fixture: Path) -> dict:
    fixture.mkdir(parents=True, exist_ok=True)
    recorded = fixture / "recorded"
    (recorded / "search-cache").mkdir(parents=True, exist_ok=True)
    for cached in sorted((export / "assets" / ".search-cache").glob("*.json")):
        shutil.copyfile(cached, recorded / "search-cache" / cached.name)

    transcripts = sorted((export / "artifacts" / "transcription").rglob("*_transcript.json"))
    if not transcripts:
        raise SystemExit("export has no transcriber output under artifacts/transcription/")
    shutil.copyfile(transcripts[-1], recorded / "transcript.json")
    timings_path = export / "artifacts" / "script-word-timings.json"
    shutil.copyfile(timings_path, recorded / "word-timings.json")
    shutil.copyfile(export / "inputs" / "approved_script.txt", fixture / "approved_script.txt")

    cached: dict[str, dict] = {}
    for path in sorted((recorded / "search-cache").glob("*.json")):
        for row in json.loads(path.read_text(encoding="utf-8")).get("candidates") or []:
            cached.setdefault(f"{row.get('source')}_{row.get('source_id')}", row)
    clips = 0
    discovered = sorted((export / ".asset-workspace" / "discovery" / "candidates").glob("*.json"))
    seen = set()
    for seed, record_path in enumerate(discovered, start=1):
        record = json.loads(record_path.read_text(encoding="utf-8"))
        clip_id = str(record.get("clipId") or "")
        if not clip_id or clip_id in seen:
            continue
        seen.add(clip_id)
        _synthetic_clip(fixture / "clips" / f"{clip_id}.mp4", int(record.get("width") or 1080),
                        int(record.get("height") or 1920), float(record.get("durationSeconds") or 8.0), seed,
                        _fps(cached.get(clip_id)))
        clips += 1
    # A clip the run's download validation rejected must be rejected again: providers'
    # search metadata overstated these (pexels_6611951 advertised 1080 wide and probed
    # 720), so the stand-in takes the probed width the run recorded.
    probed_width: dict[str, int] = {}
    results = [*sorted((export / "artifacts" / "acquisition").glob("search-pass-*.json")),
               *sorted((export / ".workspace").rglob("search-pass-*.json"))]
    for result in results:
        try:
            recorded_errors = json.loads(result.read_text(encoding="utf-8")).get("errors") or []
        except (OSError, json.JSONDecodeError):
            continue
        for error in recorded_errors:
            match = re.search(r"probed width (\d+)", str(error.get("error") or ""))
            if match and error.get("clip_id"):
                probed_width[str(error["clip_id"])] = int(match.group(1))
    # Search results the run never downloaded still need a clip if replay downloads them.
    for seed, (clip_id, row) in enumerate(sorted(cached.items()), start=1000):
        if clip_id in seen:
            continue
        seen.add(clip_id)
        width = probed_width.get(clip_id, int(row.get("width") or 1080))
        height = int(row.get("height") or 1920)
        if clip_id in probed_width and row.get("width"):
            height = max(2, int(height * width / int(row["width"])) // 2 * 2)
        _synthetic_clip(fixture / "clips" / f"{clip_id}.mp4", width, height,
                        float(row.get("duration") or 8.0), seed, _fps(row))
        clips += 1

    duration = _duration_of_words(json.loads(timings_path.read_text(encoding="utf-8")))
    _synthetic_audio(fixture / "narration.mp3", duration, tone=False)
    _synthetic_audio(fixture / "music-bed.mp3", duration, tone=True)

    leaked = [p for p in fixture.rglob("*") if p.is_file() and p.suffix.lower() in _MEDIA_SUFFIXES
              and not (p.parent.name == "clips" or p.name in {"narration.mp3", "music-bed.mp3"})]
    if leaked:
        raise SystemExit(f"unexpected media in fixture: {leaked[:3]}")
    return {"fixture": str(fixture), "searchCache": len(list((recorded / "search-cache").glob("*.json"))),
            "clips": clips, "narrationSeconds": round(duration, 3)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="make-replay-fixture", description=__doc__.splitlines()[0])
    parser.add_argument("export", type=Path)
    parser.add_argument("fixture", type=Path)
    args = parser.parse_args(argv)
    print(json.dumps(build(args.export.resolve(), args.fixture.resolve()), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
