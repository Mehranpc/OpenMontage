"""Conservative Film Type hard-region geometry proof.

This module may reject only when a mandatory shaped display token cannot fit
anywhere in the platform safe area outside reviewed hard regions. A non-blocking
result is never evidence that browser layout will pass.
"""
from __future__ import annotations

import hashlib
import io
import json
import math
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping, Sequence

from fontTools.ttLib import TTFont
import uharfbuzz as hb

from lib.paths import REPO_ROOT

FORMAT_DIMENSIONS: dict[str, tuple[int, int]] = {
    "vertical": (1080, 1920),
    "landscape": (1920, 1080),
}
_SUPPORTED_PROFILE = "2.16.0"
_TOKEN_RE = re.compile(r"\S+", re.UNICODE)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@lru_cache(maxsize=4)
def _font_bytes(path_text: str, expected_sha256: str) -> bytes | None:
    path = Path(path_text)
    if not path.is_file() or _sha256_file(path) != expected_sha256.lower():
        return None
    font = TTFont(str(path), recalcBBoxes=False, recalcTimestamp=False)
    font.flavor = None
    output = io.BytesIO()
    font.save(output, reorderTables=False)
    return output.getvalue()


@lru_cache(maxsize=512)
def _shaped_advance_lower_bound(
    path_text: str,
    expected_sha256: str,
    text: str,
    size_px: int,
) -> float | None:
    sfnt = _font_bytes(path_text, expected_sha256)
    if sfnt is None or not text:
        return None
    face = hb.Face(sfnt)
    font = hb.Font(face)
    upem = int(face.upem or 0)
    if upem <= 0:
        return None
    font.scale = (upem, upem)
    buffer = hb.Buffer()
    buffer.add_str(text)
    buffer.guess_segment_properties()
    hb.shape(font, buffer)
    advance_units = abs(sum(position.x_advance for position in buffer.glyph_positions))
    # Browser canvas width and HarfBuzz shaped advance use the same font advance
    # metric. Stay four pixels below it so this remains a strict lower bound,
    # not an equality claim across browser/HarfBuzz builds.
    return max(0.0, advance_units * float(size_px) / upem - 4.0)


def _profile(repo_root: Path, expected_version: str) -> dict[str, Any] | None:
    path = repo_root / "styles" / "persian-footage" / "film-type.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if (
        not isinstance(value, dict)
        or value.get("profile") != "film-type"
        or value.get("profileVersion") != expected_version
        or expected_version != _SUPPORTED_PROFILE
    ):
        return None
    return value


def _segment_min_size(segment: Mapping[str, Any], profile: Mapping[str, Any]) -> int | None:
    typography = profile.get("typography")
    if not isinstance(typography, Mapping):
        return None
    ladder = typography.get("statementLadderPx")
    if not isinstance(ladder, list) or not ladder:
        return None
    try:
        main = min(int(value) for value in ladder)
    except (TypeError, ValueError):
        return None
    role = str(segment.get("role") or "")
    if role == "hero":
        return main
    if role in {"lead", "tail"}:
        return round(main * 0.72)
    return None


def _mandatory_token_width(
    moment: Mapping[str, Any],
    profile: Mapping[str, Any],
    *,
    repo_root: Path,
) -> tuple[float, str, str] | None:
    # Start with the failure class that motivated F1. Unsupported moment shapes
    # remain browser-authoritative instead of being approximated here.
    if moment.get("kind") != "statement":
        return None
    typography = profile.get("typography")
    editorial = typography.get("editorial") if isinstance(typography, Mapping) else None
    if not isinstance(editorial, Mapping):
        return None
    asset_path = str(editorial.get("assetPath") or "").strip()
    asset_sha = str(editorial.get("assetSha256") or "").strip().lower()
    if not asset_path or len(asset_sha) != 64:
        return None
    font_path = (repo_root / "remotion-composer" / "public" / asset_path).resolve()

    widest: tuple[float, str] | None = None
    for segment in moment.get("segments") or []:
        if not isinstance(segment, Mapping):
            continue
        size = _segment_min_size(segment, profile)
        if size is None:
            continue
        # Breaking more aggressively than Film Type is conservative. Every
        # non-whitespace token still has to appear intact somewhere; phrase-lock
        # and grammar rules can only make the browser line wider than this bound.
        for token in _TOKEN_RE.findall(str(segment.get("text") or "")):
            width = _shaped_advance_lower_bound(str(font_path), asset_sha, token, size)
            if width is None:
                return None
            if widest is None or width > widest[0]:
                widest = (width, token)
    if widest is None or widest[0] <= 0:
        return None
    token_sha = hashlib.sha256(widest[1].encode("utf-8")).hexdigest()
    return widest[0], token_sha, asset_sha


def _intersects(a: Mapping[str, float], b: Mapping[str, float]) -> bool:
    return (
        a["x"] < b["x"] + b["w"]
        and a["x"] + a["w"] > b["x"]
        and a["y"] < b["y"] + b["h"]
        and a["y"] + a["h"] > b["y"]
    )


def _normalized_rect(value: Mapping[str, float]) -> bool:
    try:
        x, y, w, h = (float(value[key]) for key in ("x", "y", "w", "h"))
    except (KeyError, TypeError, ValueError):
        return False
    return (
        all(math.isfinite(item) for item in (x, y, w, h))
        and x >= 0.0 and y >= 0.0 and w > 0.0 and h > 0.0
        and x + w <= 1.0 + 1e-9 and y + h <= 1.0 + 1e-9
    )


def _can_place_strip(
    *,
    safe: Mapping[str, float],
    obstacles: Sequence[Mapping[str, float]],
    width: float,
    height: float,
) -> bool:
    if width <= 0 or height <= 0 or width > safe["w"] or height > safe["h"]:
        return False
    max_x = safe["x"] + safe["w"] - width
    max_y = safe["y"] + safe["h"] - height
    xs = {safe["x"], max_x}
    ys = {safe["y"], max_y}
    for obstacle in obstacles:
        xs.add(obstacle["x"] + obstacle["w"])
        xs.add(obstacle["x"] - width)
        ys.add(obstacle["y"] + obstacle["h"])
        ys.add(obstacle["y"] - height)
    for x in sorted(xs):
        if x < safe["x"] - 1e-9 or x > max_x + 1e-9:
            continue
        for y in sorted(ys):
            if y < safe["y"] - 1e-9 or y > max_y + 1e-9:
                continue
            candidate = {"x": x, "y": y, "w": width, "h": height}
            if not any(_intersects(candidate, obstacle) for obstacle in obstacles):
                return True
    return False


def prove_mandatory_strip_infeasible(
    *,
    safe_area: Mapping[str, float],
    hard_regions: Sequence[Mapping[str, float]],
    width_fraction: float,
    height_fraction: float,
) -> bool:
    """Pure reject-only rectangle proof used by the F1 fixture regression."""
    if (
        not _normalized_rect(safe_area)
        or not math.isfinite(width_fraction)
        or not math.isfinite(height_fraction)
        or width_fraction <= 0
        or height_fraction <= 0
    ):
        return False
    valid_regions = [region for region in hard_regions if _normalized_rect(region)]
    return not _can_place_strip(
        safe=safe_area,
        obstacles=valid_regions,
        width=width_fraction,
        height=height_fraction,
    )


def geometric_hard_region_precheck(
    edit: Mapping[str, Any],
    *,
    film_type_profile_version: str | None = None,
    repo_root: Path = REPO_ROOT,
) -> dict[str, Any]:
    """Return blockers proven without browser measurement.

    Missing font/profile evidence returns ``status=unknown`` and zero blockers.
    That is deliberately not a pass: downstream Chromium remains authoritative.
    """
    persian = edit.get("persian")
    if not isinstance(persian, Mapping):
        return {"status": "unknown", "blockingIssues": [], "reason": "missing_persian"}
    if film_type_profile_version is None:
        design = persian.get("design")
        if isinstance(design, Mapping):
            raw_version = str(design.get("profileVersion") or "").strip()
            film_type_profile_version = raw_version or None
    if film_type_profile_version != _SUPPORTED_PROFILE:
        return {"status": "unknown", "blockingIssues": [], "reason": "unsupported_profile"}
    profile = _profile(repo_root, film_type_profile_version)
    if profile is None:
        return {"status": "unknown", "blockingIssues": [], "reason": "profile_unavailable"}
    fmt = str(persian.get("format") or "vertical")
    dims = FORMAT_DIMENSIONS.get(fmt)
    formats = profile.get("formats")
    fmt_profile = formats.get(fmt) if isinstance(formats, Mapping) else None
    safe_raw = fmt_profile.get("safeArea") if isinstance(fmt_profile, Mapping) else None
    if dims is None or not isinstance(safe_raw, Mapping):
        return {"status": "unknown", "blockingIssues": [], "reason": "format_unavailable"}
    try:
        left = float(safe_raw.get("left", safe_raw.get("side")))
        right = float(safe_raw.get("right", safe_raw.get("side")))
        top = float(safe_raw["top"])
        bottom = float(safe_raw["bottom"])
    except (KeyError, TypeError, ValueError):
        return {"status": "unknown", "blockingIssues": [], "reason": "safe_area_unavailable"}
    safe = {"x": left, "y": top, "w": 1.0 - left - right, "h": 1.0 - top - bottom}
    if not _normalized_rect(safe):
        return {"status": "unknown", "blockingIssues": [], "reason": "invalid_safe_area"}

    shots = [shot for shot in (persian.get("shots") or []) if isinstance(shot, Mapping)]
    blockers: list[dict[str, Any]] = []
    measured = 0
    for moment in persian.get("moments") or []:
        if not isinstance(moment, Mapping):
            continue
        measurement = _mandatory_token_width(moment, profile, repo_root=repo_root)
        if measurement is None:
            continue
        measured += 1
        width_px, token_sha, font_sha = measurement
        if not math.isfinite(width_px) or width_px <= 0:
            continue
        width_norm = width_px / dims[0]
        # One pixel is smaller than any rendered Film Type row. Using it, the
        # raw platform safe area, and no collision/motion margin makes the search
        # a strict superset of every legal browser placement, including 2.16
        # subject-wrap. Failure here therefore proves browser failure.
        height_norm = 1.0 / dims[1]
        try:
            moment_start = float(moment["startSeconds"])
            moment_end = float(moment["endSeconds"])
        except (KeyError, TypeError, ValueError):
            continue
        if not all(math.isfinite(item) for item in (moment_start, moment_end)) or moment_end <= moment_start:
            continue
        obstacles: list[dict[str, float]] = []
        shot_ids: set[str] = set()
        for shot in shots:
            try:
                shot_start = float(shot.get("startSeconds", 0.0))
                shot_end = float(shot.get("endSeconds", 0.0))
            except (TypeError, ValueError):
                continue
            if (
                not all(math.isfinite(item) for item in (shot_start, shot_end))
                or shot_end <= shot_start
                or shot_start >= moment_end
                or shot_end <= moment_start
            ):
                continue
            for region in shot.get("avoidRegions") or []:
                if not isinstance(region, Mapping):
                    continue
                priority = region.get("priority")
                if priority is not None and str(priority) != "hard":
                    continue
                try:
                    start = float(region.get("startSeconds", shot_start))
                    end = float(region.get("endSeconds", shot_end))
                    obstacle = {
                        "x": float(region["x"]),
                        "y": float(region["y"]),
                        "w": float(region["w"]),
                        "h": float(region["h"]),
                    }
                except (KeyError, TypeError, ValueError):
                    continue
                if (
                    not all(math.isfinite(item) for item in (start, end))
                    or end <= start
                    or start < shot_start - 1e-9
                    or end > shot_end + 1e-9
                    or start >= moment_end
                    or end <= moment_start
                    or not _normalized_rect(obstacle)
                ):
                    continue
                obstacles.append(obstacle)
                shot_ids.add(str(shot.get("id") or ""))
        if not obstacles:
            continue
        if _can_place_strip(safe=safe, obstacles=obstacles, width=width_norm, height=height_norm):
            continue
        blockers.append({
            "code": "ASSET_SELECTION_HARD_REGION_COLLISION",
            "message": (
                f"Moment {moment.get('id')!r}: deterministic Film Type geometry "
                "proves a mandatory display token cannot fit anywhere in the "
                "platform safe area outside reviewed hard regions."
            ),
            "recoveryClass": "ASSET_SELECTION",
            "details": {
                "stage": "geometric_precheck",
                "proof": "mandatory_shaped_token_continuous_safe_area_v1",
                "momentId": str(moment.get("id") or ""),
                "shotIds": sorted(item for item in shot_ids if item),
                "hardRegionCount": len(obstacles),
                "minimumMandatoryTokenWidthPx": round(width_px, 3),
                "minimumMandatoryTokenSha256": token_sha,
                "fontAssetSha256": font_sha,
                "profileVersion": film_type_profile_version,
                "format": fmt,
                "continuousPlacementEnvelope": safe,
                "browserMeasurementRequiredForRejection": False,
            },
        })
    return {
        "status": "refused" if blockers else ("not_provable" if measured else "unknown"),
        "blockingIssues": blockers,
        "measuredMomentCount": measured,
        "proofPolicy": "reject-only; non-blocking results require downstream browser authority",
    }


__all__ = [
    "geometric_hard_region_precheck",
    "prove_mandatory_strip_infeasible",
]
