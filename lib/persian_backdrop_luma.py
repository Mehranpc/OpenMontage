"""Backdrop-adaptive text shadow for v3_staged Film Type (#387).

The diffuse shadow behind on-screen text had one strength everywhere. On bright
footage it was clearly visible; on a dark sweater the same field disappeared, so
the reviewer saw "a shadow in one shot and none in the next". Here the footage
under each placed text block is sampled (a few decoded frames per moment and
shot, never the render) and the renderer scales the shadow: stronger on a
bright backdrop, lighter on a dark one.

Cost: one tiny ffmpeg decode per sample (at most three per moment/shot pair),
which is seconds for a whole reel.
"""
from __future__ import annotations

import shutil
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any

BACKDROP_POLICY_VERSION = "1.0"
#: Relative luma (0..1) at or below which the backdrop counts as dark / at or above as bright.
DARK_LUMA = 0.15
BRIGHT_LUMA = 0.55
MIN_MULTIPLIER = 0.7
MAX_MULTIPLIER = 1.3
#: The field reaches past the ink; sample a margin around the text block.
RECT_MARGIN = 0.06
MAX_SAMPLES = 3
FRAME_SIZE = {"vertical": (1080, 1920), "landscape": (1920, 1080), "square": (1080, 1080)}


def luma_multiplier(luma: float) -> float:
    """Shadow multiplier for a backdrop luma; linear between the dark and bright ends."""
    value = min(1.0, max(0.0, float(luma)))
    if value <= DARK_LUMA:
        return MIN_MULTIPLIER
    if value >= BRIGHT_LUMA:
        return MAX_MULTIPLIER
    ratio = (value - DARK_LUMA) / (BRIGHT_LUMA - DARK_LUMA)
    return round(MIN_MULTIPLIER + ratio * (MAX_MULTIPLIER - MIN_MULTIPLIER), 3)


def sample_times(start: float, end: float) -> list[float]:
    """Up to three timeline instants inside an overlap, away from cut edges."""
    span = end - start
    if span <= 0:
        return []
    middle = start + span / 2
    if span < 1.5:
        return [round(middle, 3)]
    return [round(start + 0.3, 3), round(middle, 3), round(end - 0.3, 3)][:MAX_SAMPLES]


def _crop(rect: Mapping[str, Any], width: int, height: int) -> tuple[int, int, int, int]:
    x0 = max(0.0, float(rect["x"]) - RECT_MARGIN)
    y0 = max(0.0, float(rect["y"]) - RECT_MARGIN)
    x1 = min(1.0, float(rect["x"]) + float(rect["w"]) + RECT_MARGIN)
    y1 = min(1.0, float(rect["y"]) + float(rect["h"]) + RECT_MARGIN)
    w = max(2, int((x1 - x0) * width))
    h = max(2, int((y1 - y0) * height))
    return w, h, int(x0 * width), int(y0 * height)


def frame_luma(source: Path, seconds: float, rect: Mapping[str, Any], fmt: str = "vertical") -> float:
    """Mean luma (0..1) of the cover-fitted source frame under ``rect``."""
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise RuntimeError("ffmpeg is not on PATH")
    width, height = FRAME_SIZE.get(fmt, FRAME_SIZE["vertical"])
    cw, ch, cx, cy = _crop(rect, width, height)
    graph = (
        f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},"
        f"crop={cw}:{ch}:{cx}:{cy},format=gray,scale=1:1:flags=area"
    )
    completed = subprocess.run(
        [ffmpeg, "-nostdin", "-v", "error", "-ss", f"{max(0.0, seconds):.3f}", "-i", str(source),
         "-frames:v", "1", "-vf", graph, "-f", "rawvideo", "-"],
        capture_output=True, timeout=60, check=False,
    )
    if completed.returncode != 0 or len(completed.stdout) < 1:
        raise RuntimeError(completed.stderr.decode("utf-8", "replace")[-300:] or "no frame decoded")
    return completed.stdout[0] / 255.0


def measure_backdrop(props: Mapping[str, Any], sources: Mapping[str, Path]) -> dict[str, Any]:
    """Per placed moment and overlapping shot: backdrop luma and shadow multiplier.

    ``sources`` maps shot id to the original footage file. A pair that cannot be
    sampled is recorded with its error and keeps the default strength (multiplier 1).
    """
    film = props.get("filmType") or {}
    layouts = film.get("moments") or {}
    shots = list(props.get("shots") or [])
    fmt = str(props.get("format") or "vertical")
    moments: dict[str, dict[str, Any]] = {}
    for moment in props.get("moments") or []:
        layout = layouts.get(str(moment.get("id"))) if isinstance(layouts, Mapping) else None
        rect = layout.get("rect") if isinstance(layout, Mapping) else None
        if not isinstance(rect, Mapping):
            continue
        m_start, m_end = float(moment["startSeconds"]), float(moment["endSeconds"])
        per_shot: dict[str, Any] = {}
        for shot in shots:
            start = max(m_start, float(shot["startSeconds"]))
            end = min(m_end, float(shot["endSeconds"]))
            times = sample_times(start, end)
            source = sources.get(str(shot.get("id")))
            if not times or source is None:
                continue
            try:
                values = [
                    frame_luma(Path(source), float(shot.get("sourceInSeconds") or 0.0) + t - float(shot["startSeconds"]), rect, fmt)
                    for t in times
                ]
            except (RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
                per_shot[str(shot["id"])] = {"multiplier": 1.0, "error": str(exc)[:200]}
                continue
            luma = round(sum(values) / len(values), 4)
            per_shot[str(shot["id"])] = {"luma": luma, "multiplier": luma_multiplier(luma), "samples": len(values)}
        if per_shot:
            moments[str(moment["id"])] = per_shot
    return {"version": BACKDROP_POLICY_VERSION, "moments": moments}


__all__ = [
    "BACKDROP_POLICY_VERSION", "DARK_LUMA", "BRIGHT_LUMA", "MIN_MULTIPLIER", "MAX_MULTIPLIER",
    "luma_multiplier", "sample_times", "frame_luma", "measure_backdrop",
]
