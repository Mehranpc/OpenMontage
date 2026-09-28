"""Replace the rehearsal fixture's real media with synthetic stand-ins (#260).

The first-date fixture shipped the real narration, Pexels clips and Pixabay bed
for the testing phase only. This regenerates every media file at the same
geometry, duration, frame rate, codec and loudness, so every gate that reads
metadata, timing, luminance, motion or LUFS sees what it saw before, but none of
the original content remains:

- clips: moving colour gradients with drifting noise (motion QA reads frame
  deltas; luminance QA reads YAVG), same WxH / fps / duration as each original;
- narration: shaped noise bursts at the original syllable timing envelope,
  normalised to the original integrated loudness; the transcript and word
  timings stay recorded data, so alignment still maps the approved script;
- music bed: a quiet two-chord pad at the original loudness.

    python -m scripts.make_synthetic_rehearsal_media [--fixture DIR]
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

DEFAULT_FIXTURE = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "rehearsal" / "first-date"


def _probe(path: Path) -> dict:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
                         check=True, capture_output=True, text=True).stdout
    return json.loads(out)


def _lufs(path: Path) -> float:
    out = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-af", "ebur128", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    return float(re.findall(r"I:\s+(-?[0-9.]+) LUFS", out)[-1])


def _run(args: list[str]) -> None:
    subprocess.run(["ffmpeg", "-hide_banner", "-v", "error", "-y", *args], check=True)


def clip(path: Path, seed: int) -> None:
    info = _probe(path)
    video = next(s for s in info["streams"] if s["codec_type"] == "video")
    w, h, rate = int(video["width"]), int(video["height"]), video["r_frame_rate"]
    duration = float(info["format"]["duration"])
    hue = (seed * 47) % 360
    tmp = path.with_suffix(".synthetic.mp4")
    # Lower 70% carries the moving "subject"; the upper band stays a calm gradient,
    # like the plain walls the recorded region reviews marked as negative space.
    _run([
        "-f", "lavfi", "-i", f"gradients=s={w}x{h}:r={rate}:c0=0x5a6b7c:c1=0x9aa4ad:speed=0.02:seed={seed}:d={duration}",
        "-f", "lavfi", "-i", f"testsrc2=s={w}x{int(h*0.7)}:r={rate}:d={duration}",
        "-filter_complex",
        f"[1]hue=h={hue}:s=0.6,boxblur=6,eq=brightness=0.05[s];[0][s]overlay=0:{int(h*0.3)}:shortest=1,"
        "noise=alls=6:allf=t,format=yuv420p",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "46", "-an", "-t", f"{duration:.3f}", str(tmp),
    ])
    tmp.replace(path)


def narration(path: Path, word_timings: Path) -> None:
    target = _lufs(path)
    duration = float(_probe(path)["format"]["duration"])
    _narration(path, word_timings, target, duration)
    _match_loudness(path, target, duration, channels=1, bitrate="128k")


def _narration(path: Path, word_timings: Path, target: float, duration: float) -> None:
    words = json.loads(word_timings.read_text(encoding="utf-8"))["words"]
    # One noise burst per recorded word, band-limited to the speech range.
    gates = "+".join(f"between(t,{w['start']:.3f},{max(w['start'] + 0.06, w['end'] - 0.02):.3f})" for w in words)
    tmp = path.with_suffix(".synthetic.mp3")
    _run([
        "-f", "lavfi", "-i", f"anoisesrc=d={duration:.3f}:c=pink:r=44100:a=0.5",
        "-af", f"bandpass=f=900:w=1400,volume='if({gates},1,0.003)':eval=frame,loudnorm=I={target}:TP=-2:LRA=7",
        "-ac", "1", "-ar", "44100", "-c:a", "libmp3lame", "-b:a", "128k", "-t", f"{duration:.3f}", str(tmp),
    ])
    tmp.replace(path)


def bed(path: Path) -> None:
    target = _lufs(path)
    duration = float(_probe(path)["format"]["duration"])
    _bed(path, target, duration)
    _match_loudness(path, target, duration, channels=2, bitrate="96k")


def _bed(path: Path, target: float, duration: float) -> None:
    tmp = path.with_suffix(".synthetic.mp3")
    _run([
        "-f", "lavfi", "-i", f"sine=f=220:d={duration:.3f}", "-f", "lavfi", "-i", f"sine=f=277.18:d={duration:.3f}",
        "-f", "lavfi", "-i", f"sine=f=329.63:d={duration:.3f}",
        "-filter_complex", f"[0][1][2]amix=inputs=3,tremolo=f=0.25:d=0.3,loudnorm=I={target}:TP=-1.5:LRA=5[a]",
        "-map", "[a]", "-ac", "2", "-ar", "44100", "-c:a", "libmp3lame", "-b:a", "96k", "-t", f"{duration:.3f}", str(tmp),
    ])
    tmp.replace(path)


def _match_loudness(path: Path, target: float, duration: float, *, channels: int, bitrate: str) -> None:
    """loudnorm's single pass lands within a few LU; one linear gain from the
    pristine file finishes it (re-encoding the result repeatedly drifts)."""
    source = path.with_suffix(".pre-gain.mp3")
    path.replace(source)
    gain = target - _lufs(source)
    for _ in range(4):
        _run(["-i", str(source), "-af", f"volume={gain:.2f}dB", "-t", f"{duration:.6f}",
              "-ac", str(channels), "-ar", "44100", "-c:a", "libmp3lame", "-b:a", bitrate, str(path)])
        miss = target - _lufs(path)
        if abs(miss) <= 0.15:
            break
        gain += miss
    source.unlink()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="make-synthetic-rehearsal-media")
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    args = parser.parse_args(argv)
    root = args.fixture
    for seed, path in enumerate(sorted((root / "clips").glob("*.mp4")), start=1):
        clip(path, seed)
        print("clip", path.name)
    narration(root / "narration.mp3", root / "recorded" / "word-timings.json")
    print("narration")
    bed(root / "music-bed.mp3")
    print("bed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
