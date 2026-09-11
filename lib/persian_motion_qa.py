"""Conservative post-render motion audit for Persian short-form video.

Timeline retention checks prove that visual events were authored. This module checks
that the finished MP4 actually changes on screen. It deliberately detects only
near-frozen stretches: subtle or slow footage should not fail because a generic pixel
threshold decided it was boring.

Frames are sampled at 2 fps, scaled to 64x36 grayscale, and compared with mean
absolute pixel delta. A <=1.0/255 delta is effectively frozen at this resolution.
Because sampled deltas under-measure a visible run by up to one sample interval,
7s/9s measured runs correspond roughly to the spec's ~8s warning / ~10s high-risk
range. The shorter boundary warns; only the longer near-frozen run blocks delivery.
"""
from __future__ import annotations

import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

MOTION_SAMPLE_FPS = 2.0
MOTION_SAMPLE_WIDTH = 64
MOTION_SAMPLE_HEIGHT = 36
NEAR_STATIC_DELTA_MAX = 1.0
NEAR_STATIC_WARN_SECONDS = 7.0
NEAR_STATIC_FAIL_SECONDS = 9.0


@dataclass(frozen=True)
class MotionDelta:
    at_seconds: float
    mean_abs_delta: float

    def to_dict(self) -> dict[str, float]:
        return {
            "atSeconds": round(self.at_seconds, 3),
            "meanAbsDelta": round(self.mean_abs_delta, 3),
        }


@dataclass(frozen=True)
class StaticRun:
    start_seconds: float
    end_seconds: float
    mean_abs_delta: float

    @property
    def duration_seconds(self) -> float:
        return self.end_seconds - self.start_seconds

    def to_dict(self) -> dict[str, float]:
        return {
            "startSeconds": round(self.start_seconds, 3),
            "endSeconds": round(self.end_seconds, 3),
            "durationSeconds": round(self.duration_seconds, 3),
            "meanAbsDelta": round(self.mean_abs_delta, 3),
        }


def frame_mean_abs_delta(previous: bytes, current: bytes) -> float:
    """Mean absolute difference for equally sized grayscale frames."""
    if len(previous) != len(current) or not previous:
        raise ValueError("motion QA frames must be non-empty and equal-sized")
    return sum(abs(a - b) for a, b in zip(previous, current)) / len(previous)


def find_near_static_runs(
    deltas: Sequence[MotionDelta],
    *,
    max_delta: float = NEAR_STATIC_DELTA_MAX,
    min_seconds: float,
    sample_fps: float = MOTION_SAMPLE_FPS,
) -> list[StaticRun]:
    """Return contiguous low-delta runs lasting at least ``min_seconds``."""
    if sample_fps <= 0:
        raise ValueError("sample_fps must be positive")
    step = 1.0 / sample_fps
    ordered = sorted(deltas, key=lambda item: item.at_seconds)
    runs: list[StaticRun] = []
    start: float | None = None
    values: list[float] = []
    previous_stamp: float | None = None

    def close(end_stamp: float) -> None:
        nonlocal start, values
        if start is None or not values:
            return
        if end_stamp - start + 1e-9 >= min_seconds:
            runs.append(StaticRun(start, end_stamp, sum(values) / len(values)))

    for item in ordered:
        contiguous = previous_stamp is None or abs(item.at_seconds - previous_stamp - step) <= step * 0.2
        low = item.mean_abs_delta <= max_delta
        if low and contiguous:
            if start is None:
                start = max(0.0, item.at_seconds - step)
                values = []
            values.append(item.mean_abs_delta)
        else:
            if start is not None and previous_stamp is not None:
                close(previous_stamp)
            start = max(0.0, item.at_seconds - step) if low else None
            values = [item.mean_abs_delta] if low else []
        previous_stamp = item.at_seconds

    if start is not None and previous_stamp is not None:
        close(previous_stamp)
    return runs


def measure_motion_deltas(
    video_path: Path,
    *,
    timeout: int = 600,
    sample_fps: float = MOTION_SAMPLE_FPS,
) -> tuple[list[MotionDelta], float]:
    """Decode tiny grayscale samples from the finished MP4 and compare them."""
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise RuntimeError("ffmpeg is not on PATH, so post-render motion cannot be measured")
    frame_bytes = MOTION_SAMPLE_WIDTH * MOTION_SAMPLE_HEIGHT
    started = time.perf_counter()
    completed = subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(video_path),
            "-vf",
            f"fps={sample_fps},scale={MOTION_SAMPLE_WIDTH}:{MOTION_SAMPLE_HEIGHT}:flags=area,format=gray",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "gray",
            "-",
        ],
        capture_output=True,
        timeout=timeout,
    )
    elapsed = time.perf_counter() - started
    if completed.returncode != 0:
        stderr = completed.stderr.decode("utf-8", errors="replace") if isinstance(completed.stderr, bytes) else str(completed.stderr or "")
        raise RuntimeError(
            "post-render motion decode failed "
            f"(exit {completed.returncode}): {stderr.strip()[-500:]}"
        )
    payload = bytes(completed.stdout or b"")
    if len(payload) < frame_bytes:
        raise RuntimeError("post-render motion decode produced no complete sample frame")
    frame_count = len(payload) // frame_bytes
    payload = payload[: frame_count * frame_bytes]
    frames = [payload[i * frame_bytes : (i + 1) * frame_bytes] for i in range(frame_count)]
    deltas = [
        MotionDelta(index / sample_fps, frame_mean_abs_delta(frames[index - 1], frames[index]))
        for index in range(1, len(frames))
    ]
    return deltas, elapsed


@dataclass
class MotionQa:
    passed: bool
    deltas: list[MotionDelta] = field(default_factory=list)
    warn_runs: list[StaticRun] = field(default_factory=list)
    fail_runs: list[StaticRun] = field(default_factory=list)
    elapsed_seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "sampleFps": MOTION_SAMPLE_FPS,
            "nearStaticDeltaMax": NEAR_STATIC_DELTA_MAX,
            "warningRunSeconds": NEAR_STATIC_WARN_SECONDS,
            "failRunSeconds": NEAR_STATIC_FAIL_SECONDS,
            "deltas": [item.to_dict() for item in self.deltas],
            "warnRuns": [run.to_dict() for run in self.warn_runs],
            "failRuns": [run.to_dict() for run in self.fail_runs],
            "elapsedSeconds": round(self.elapsed_seconds, 2),
        }


def audit_render_motion(video_path: Path, *, timeout: int = 600) -> MotionQa:
    deltas, elapsed = measure_motion_deltas(video_path, timeout=timeout)
    warned = find_near_static_runs(deltas, min_seconds=NEAR_STATIC_WARN_SECONDS)
    failed = find_near_static_runs(deltas, min_seconds=NEAR_STATIC_FAIL_SECONDS)
    failed_spans = {(r.start_seconds, r.end_seconds) for r in failed}
    warnings_only = [r for r in warned if (r.start_seconds, r.end_seconds) not in failed_spans]
    return MotionQa(
        passed=not failed,
        deltas=deltas,
        warn_runs=warnings_only,
        fail_runs=failed,
        elapsed_seconds=elapsed,
    )


__all__ = [
    "MOTION_SAMPLE_FPS",
    "MOTION_SAMPLE_WIDTH",
    "MOTION_SAMPLE_HEIGHT",
    "NEAR_STATIC_DELTA_MAX",
    "NEAR_STATIC_WARN_SECONDS",
    "NEAR_STATIC_FAIL_SECONDS",
    "MotionDelta",
    "StaticRun",
    "MotionQa",
    "frame_mean_abs_delta",
    "find_near_static_runs",
    "measure_motion_deltas",
    "audit_render_motion",
]
