"""Post-render luminance gate for the Persian composition.

`video_compose` samples a few frames and judges black by PNG file size
(file size heuristic, tools/video/video_compose.py). That answers "is this
frame empty" at four timestamps; it cannot answer "does this video contain a
dead stretch". This module answers the second question: a near-black stretch
(plate with no typography on it) inside an otherwise successful render.

Thresholds are calibrated against measured production data from
coffee-hormones-fa, not chosen from theory — do not "tidy" them:

* the broken render's dead seconds measured YAVG 17-19 (plate #0B0B0C;
  pure black is 16);
* the repaired render measures 55-74 across the same seconds;
* legitimate dark cinematic footage in the same video (macro coffee-bean
  shot, 52.6-58.0s) measures YAVG ~28 and must pass — real footage with
  visible texture and motion.

So a contiguous run of >= 1.0s below 22 fails; a run below 30 is reported
but does not fail. Per-second averaging (not per-frame) is what keeps the
~28 footage safe: a dark-but-textured second still averages above 22.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from statistics import median
from typing import Any, Sequence

#: A contiguous run at or over this length below DEAD_LUMA_FAIL refuses delivery.
DEAD_RUN_MIN_SECONDS = 1.0

#: Fail floor. Above the broken render's 17-19 with margin; below legitimate
#: dark footage at ~28 with margin. Calibrated, see module docstring.
DEAD_LUMA_FAIL = 22.0

#: Advisory floor. Legitimate dark footage (~28) lands here: reported so the
#: reviewer sees it, never a failure.
DEAD_LUMA_WARN = 30.0

#: Pre-render coverage tolerance. Float arithmetic over shot boundaries can
#: leave millisecond seams no viewer can see, and one 30fps frame is ~0.033s,
#: so 0.05s stays above single-frame rounding while a quarter-second hole —
#: a visible black flash — still fails with margin.
COVERAGE_TOLERANCE_SECONDS = 0.05

_FRAME_TIME_RE = re.compile(r"pts_time:([0-9.eE+-]+)")
_YAVG_RE = re.compile(r"lavfi\.signalstats\.YAVG=([0-9.eE+-]+)")


@dataclass
class DarkRun:
    """One contiguous below-floor stretch of the timeline."""

    start_seconds: float
    end_seconds: float
    mean_yavg: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "startSeconds": round(self.start_seconds, 3),
            "endSeconds": round(self.end_seconds, 3),
            "meanYavg": round(self.mean_yavg, 1),
        }


def find_dark_runs(
    per_second: Sequence[tuple[float, float]],
    *,
    below: float,
    min_seconds: float = DEAD_RUN_MIN_SECONDS,
) -> list[DarkRun]:
    """Flag contiguous below-`below` stretches lasting at least `min_seconds`.

    `per_second` is `(second_start, mean_yavg)` pairs in any order. A run's end
    is its last sample plus the series' own median spacing, so 30fps-frame
    input and 1s-bin input both measure duration correctly.
    """
    ordered = sorted(per_second, key=lambda sample: sample[0])
    if not ordered:
        return []
    diffs = [
        later[0] - earlier[0]
        for earlier, later in zip(ordered, ordered[1:])
        if later[0] > earlier[0]
    ]
    step = float(median(diffs)) if diffs else 1.0

    runs: list[DarkRun] = []
    run_start: float | None = None
    run_values: list[float] = []

    def close(last_time: float) -> None:
        if run_start is None or not run_values:
            return
        end = last_time + step
        if end - run_start + 1e-6 >= min_seconds:
            runs.append(
                DarkRun(
                    start_seconds=run_start,
                    end_seconds=end,
                    mean_yavg=sum(run_values) / len(run_values),
                )
            )

    for stamp, yavg in ordered:
        if yavg < below:
            if run_start is None:
                run_start = stamp
                run_values = []
            run_values.append(yavg)
        elif run_start is not None:
            close(previous)
            run_start = None
            run_values = []
        previous = stamp

    if run_start is not None:
        close(ordered[-1][0])
    return runs


def find_coverage_gaps(
    spans: Sequence[tuple[float, float]],
    duration_seconds: float,
    *,
    tolerance: float = COVERAGE_TOLERANCE_SECONDS,
) -> list[tuple[float, float]]:
    """List timeline stretches covered by neither footage nor plate.

    `spans` is `(start, end)` pairs in any order — footage shots plus derived
    beat windows. Gaps at or under `tolerance` are float noise and ignored, so
    only visible black stretches are returned.
    """
    ordered = sorted(spans, key=lambda span: span[0])
    gaps: list[tuple[float, float]] = []
    cursor = 0.0
    for span_start, span_end in ordered:
        if span_start - cursor > tolerance:
            gaps.append((max(cursor, 0.0), span_start))
        cursor = max(cursor, span_end)
    if duration_seconds - cursor > tolerance:
        gaps.append((cursor, duration_seconds))
    return gaps


def window_mean(
    per_second: Sequence[tuple[float, float]],
    start: float,
    end: float,
    *,
    bin_width: float | None = None,
) -> float | None:
    """Mean YAVG of the bins overlapping `[start, end)`; None when empty.

    The bin width defaults to the series' own median spacing (same rule as
    `find_dark_runs`), so frame-rate input and 1s-bin input both overlap
    correctly.
    """
    ordered = sorted(per_second, key=lambda sample: sample[0])
    if bin_width is None:
        diffs = [
            later[0] - earlier[0]
            for earlier, later in zip(ordered, ordered[1:])
            if later[0] > earlier[0]
        ]
        bin_width = float(median(diffs)) if diffs else 1.0
    values = [
        yavg for stamp, yavg in ordered if stamp < end and stamp + bin_width > start
    ]
    if not values:
        return None
    return sum(values) / len(values)


def _parse_signalstats(output: str) -> list[tuple[float, float]]:
    """Pair each frame's `pts_time` with its `YAVG` from a metadata-print pass."""
    samples: list[tuple[float, float]] = []
    pending: float | None = None
    for line in output.splitlines():
        time_match = _FRAME_TIME_RE.search(line)
        if time_match:
            try:
                pending = float(time_match.group(1))
            except ValueError:
                pending = None
            continue
        yavg_match = _YAVG_RE.search(line)
        if yavg_match and pending is not None:
            try:
                samples.append((pending, float(yavg_match.group(1))))
            except ValueError:
                pass
            pending = None
    return samples


def measure_per_second_luma(
    video_path: Path, *, timeout: int = 600
) -> tuple[list[tuple[float, float]], float]:
    """One ffmpeg `signalstats` pass; returns 1s-bin `(second, mean YAVG)` pairs.

    Returns the bins plus the pass's own wall-clock seconds, so the gate's
    cost is visible to the caller. Raises RuntimeError when ffmpeg is absent
    or the pass fails — a render that cannot be measured cannot be reported
    as successful.
    """
    started = time.perf_counter()
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise RuntimeError(
            "ffmpeg is not on PATH, so the rendered output cannot be measured "
            "for dead stretches. Install ffmpeg rather than delivering blind."
        )
    completed = subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-i",
            str(video_path),
            "-vf",
            "signalstats,metadata=print:file=-:key=lavfi.signalstats.YAVG",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    elapsed = time.perf_counter() - started
    if completed.returncode != 0:
        raise RuntimeError(
            "the luminance pass over the rendered output failed "
            f"(exit {completed.returncode}): "
            f"{(completed.stderr or '').strip()[-500:]}"
        )
    frames = _parse_signalstats(completed.stdout + "\n" + (completed.stderr or ""))
    if not frames:
        raise RuntimeError(
            "the luminance pass produced no signalstats samples — the output "
            "file may not be a readable video."
        )
    bins: dict[int, list[float]] = {}
    for stamp, yavg in frames:
        bins.setdefault(int(stamp), []).append(yavg)
    per_second = [
        (float(second), sum(values) / len(values))
        for second, values in sorted(bins.items())
    ]
    return per_second, elapsed


@dataclass
class RenderQa:
    """The luminance gate's verdict over one finished render."""

    passed: bool
    per_second: list[tuple[float, float]] = field(default_factory=list)
    dead_runs: list[DarkRun] = field(default_factory=list)
    warn_runs: list[DarkRun] = field(default_factory=list)
    beat_luma: list[dict[str, Any]] = field(default_factory=list)
    elapsed_seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "deadRuns": [run.to_dict() for run in self.dead_runs],
            "warnRuns": [run.to_dict() for run in self.warn_runs],
            "beatLuma": self.beat_luma,
            "elapsedSeconds": round(self.elapsed_seconds, 1),
        }


def audit_render_luminance(
    video_path: Path,
    *,
    beat_windows: Sequence[dict[str, Any]] = (),
    moment_windows: Sequence[dict[str, Any]] = (),
    timeout: int = 600,
) -> RenderQa:
    """Measure the render and refuse dead darkness, not intentional painted type plates."""
    per_second, elapsed = measure_per_second_luma(video_path, timeout=timeout)

    protected: list[tuple[float, float]] = []
    for beat in beat_windows:
        b0, b1 = float(beat.get("startSeconds", 0.0)), float(beat.get("endSeconds", 0.0))
        for moment in moment_windows:
            m0, m1 = float(moment.get("startSeconds", 0.0)), float(moment.get("endSeconds", 0.0))
            start, end = max(b0, m0), min(b1, m1)
            if end > start:
                protected.append((start, end))

    # A protected interval interrupts a contiguous dead run even when it begins or
    # ends inside an absolute one-second YAVG bin. Because an unprotected remainder
    # of such a partially overlapping bin is necessarily <1s, it cannot by itself
    # satisfy DEAD_RUN_MIN_SECONDS. Lift any overlapping bin for dead/warn detection;
    # untouched footage/empty-plate bins keep the calibrated 22/30 thresholds.
    detection = []
    for stamp, yavg in per_second:
        painted = any(
            stamp < end - 1e-6 and stamp + 1.0 > start + 1e-6
            for start, end in protected
        )
        detection.append((stamp, max(yavg, DEAD_LUMA_WARN) if painted else yavg))
    dead = find_dark_runs(detection, below=DEAD_LUMA_FAIL)
    warned = find_dark_runs(detection, below=DEAD_LUMA_WARN)
    beats = []
    for beat in beat_windows:
        start = float(beat.get("startSeconds", 0.0))
        end = float(beat.get("endSeconds", 0.0))
        beats.append(
            {
                "id": str(beat.get("id", "")),
                "startSeconds": start,
                "endSeconds": end,
                "meanYavg": (
                    round(mean, 1)
                    if (mean := window_mean(per_second, start, end)) is not None
                    else None
                ),
            }
        )
    return RenderQa(
        passed=not dead,
        per_second=per_second,
        dead_runs=dead,
        warn_runs=[run for run in warned if run.mean_yavg >= DEAD_LUMA_FAIL],
        beat_luma=beats,
        elapsed_seconds=elapsed,
    )
