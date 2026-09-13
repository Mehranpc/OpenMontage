"""Burned Persian caption policy for the persian-footage renderer.

The sidecar SRT and the burned track share approved-script timing authority but have
different layout budgets.  The sidecar may carry longer cues because the platform owns
layout.  Burned captions must fit a conservative two-line phone-safe block, so they are
regrouped from the same aligned timed words with a tighter character ceiling.
"""

from __future__ import annotations

from typing import Any, Iterable

from lib.persian_srt import PersianCue
from lib.persian_text import visible_length

CAPTION_MODES = frozenset({"sidecar_only", "burned_captions", "hybrid"})
BURNED_CAPTION_MODES = frozenset({"burned_captions", "hybrid"})
BURNED_CAPTION_MAX_VISIBLE_CHARS = 56
BURNED_CAPTION_213_MAX_VISIBLE_CHARS = 50
BURNED_CAPTION_214_MAX_VISIBLE_CHARS = 54
BURNED_CAPTION_MAX_LINE_VISIBLE_CHARS = 30
CAPTION_FONT_PX = {"vertical": 48, "landscape": 40}
CAPTION_LINE_HEIGHT = 1.38
CAPTION_VERTICAL_PADDING_PX = 12
CAPTION_EDGE_GAP_FRACTION = 0.015
FRAME_DIMENSIONS = {"vertical": (1080, 1920), "landscape": (1920, 1080)}


def burned_caption_max_visible_chars(profile_version: str | None = None) -> int:
    """Return the cue-grouping budget for the resolved caption geometry.

    Film Type 2.13 mirrors the larger horizontal safe inset on both sides, so its
    physically centered caption band is narrower than pinned 2.12.  Grouping uses a
    tighter conservative ceiling before Chromium performs the authoritative pixel-fit
    check; this is a grouping heuristic, never permission to shrink type.
    """
    if str(profile_version or "") == "2.14.0":
        return BURNED_CAPTION_214_MAX_VISIBLE_CHARS
    if str(profile_version or "") == "2.13.0":
        return BURNED_CAPTION_213_MAX_VISIBLE_CHARS
    return BURNED_CAPTION_MAX_VISIBLE_CHARS


def default_caption_mode(platform_target: Any = None) -> str:
    """Code-owned platform default; missing/legacy platform keeps sidecar-only."""
    target = str(platform_target or "").strip().lower().replace("_", "-")
    if target in {"instagram", "instagram-reels", "reels"}:
        return "hybrid"
    return "sidecar_only"


def resolve_caption_mode(raw: Any, *, platform_target: Any = None) -> str:
    """Resolve explicit mode first, then the platform default."""
    mode = str(raw or default_caption_mode(platform_target)).strip().lower()
    if mode not in CAPTION_MODES:
        raise ValueError(
            f"captionMode must be one of {sorted(CAPTION_MODES)}, got {raw!r}"
        )
    return mode


def _line_length(words: list[str]) -> int:
    return visible_length(" ".join(words))


def layout_caption_lines(text: str) -> list[str]:
    """Lay one approved cue into one or two balanced lines without changing words."""
    words = [word for word in str(text).split(" ") if word]
    if not words:
        raise ValueError("burned caption text is empty")
    if visible_length(text) > BURNED_CAPTION_MAX_VISIBLE_CHARS:
        raise ValueError(
            f"burned caption has {visible_length(text)} visible chars, above the "
            f"{BURNED_CAPTION_MAX_VISIBLE_CHARS}-character display ceiling"
        )
    if _line_length(words) <= BURNED_CAPTION_MAX_LINE_VISIBLE_CHARS:
        return [" ".join(words)]

    candidates: list[tuple[int, int, int, list[str]]] = []
    for split in range(1, len(words)):
        first = words[:split]
        second = words[split:]
        first_len = _line_length(first)
        second_len = _line_length(second)
        if max(first_len, second_len) > BURNED_CAPTION_MAX_LINE_VISIBLE_CHARS:
            continue
        candidates.append(
            (
                abs(first_len - second_len),
                max(first_len, second_len),
                split,
                [" ".join(first), " ".join(second)],
            )
        )
    if not candidates:
        raise ValueError(
            "burned caption cannot fit two conservative lines without changing "
            "approved wording; tighten cue grouping rather than shrinking type"
        )
    return min(candidates, key=lambda item: item[:3])[3]



def caption_band_rect(
    video_format: str,
    *,
    safe_area: dict[str, Any] | None = None,
    profile_version: str | None = None,
    start_seconds: float = 0.0,
    end_seconds: float = 0.0,
) -> dict[str, float]:
    """Mirror the renderer's conservative two-line caption envelope for planners."""
    if video_format not in FRAME_DIMENSIONS:
        raise ValueError(f"unsupported caption format {video_format!r}")
    width, height = FRAME_DIMENSIONS[video_format]
    fallback = (
        {"top": 0.08, "bottom": 0.20, "left": 0.08, "right": 0.08}
        if video_format == "vertical"
        else {"top": 0.08, "bottom": 0.08, "left": 0.08, "right": 0.08}
    )
    raw = safe_area or {}
    side = float(raw.get("side", fallback["left"]))
    top = float(raw.get("top", fallback["top"]))
    bottom = float(raw.get("bottom", fallback["bottom"]))
    left = float(raw.get("left", side))
    right = float(raw.get("right", side))
    refined = profile_version == "2.14.0"
    font_px = (46 if video_format == "vertical" else 38) if refined else CAPTION_FONT_PX[video_format]
    line_height = 1.32 if refined else CAPTION_LINE_HEIGHT
    vertical_padding = 10 if refined else CAPTION_VERTICAL_PADDING_PX
    line_box = font_px * line_height
    h = (2 * line_box + 2 * vertical_padding) / height
    if profile_version in {"2.13.0", "2.14.0"}:
        # Renderer 2.13 uses the larger safe-side inset on both sides so the
        # physical caption band, not merely its safe-area remainder, centers at x=.5.
        caption_side = max(left, right)
        x = caption_side + CAPTION_EDGE_GAP_FRACTION
        w = max(0.0, 1 - 2 * x)
    else:
        # Pinned 2.12 and callers without a profile retain historical geometry.
        x = left + CAPTION_EDGE_GAP_FRACTION
        w = max(0.0, 1 - left - right - 2 * CAPTION_EDGE_GAP_FRACTION)
    y = max(top, 1 - bottom - CAPTION_EDGE_GAP_FRACTION - h)
    return {
        "x": x, "y": y, "w": w, "h": h,
        "startSeconds": float(start_seconds),
        "endSeconds": float(end_seconds),
    }

def build_burned_caption_props(cues: Iterable[PersianCue]) -> list[dict[str, Any]]:
    """Convert approved, aligned cues into renderer props with explicit line breaks."""
    result: list[dict[str, Any]] = []
    for cue in cues:
        lines = layout_caption_lines(cue.text)
        result.append(
            {
                "id": cue.id,
                "text": cue.text,
                "lines": lines,
                "startSeconds": float(cue.start_seconds),
                "endSeconds": float(cue.end_seconds),
            }
        )
    return result


__all__ = [
    "CAPTION_MODES",
    "BURNED_CAPTION_MODES",
    "BURNED_CAPTION_MAX_VISIBLE_CHARS",
    "BURNED_CAPTION_213_MAX_VISIBLE_CHARS",
    "BURNED_CAPTION_214_MAX_VISIBLE_CHARS",
    "BURNED_CAPTION_MAX_LINE_VISIBLE_CHARS",
    "burned_caption_max_visible_chars",
    "default_caption_mode",
    "resolve_caption_mode",
    "layout_caption_lines",
    "build_burned_caption_props",
    "caption_band_rect",
]
