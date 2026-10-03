"""#387 increment 3: under v3_staged, styled text adapts to locked footage.

Real Chromium + Film Type fonts (opt-in L2, run in CI with the licensed Kahroba font).
The ladder is deterministic: free area -> top/bottom band -> scaled band -> scrim ->
subtitle fallback. It never refuses for subject geometry and never asks for other
footage. Stills of the scrim moment and of the subtitle-fallback span are written as
evidence next to the L2 artifacts.

Local runs without the licensed font may pin the Estedad-only 2.15 profile with
``OPENMONTAGE_L2_FILM_TYPE_PIN=2.15.0``; CI uses the default 2.16 profile.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from lib.persian_design import canonical_numbers, resolve_design
from lib.persian_film_type import FilmTypePreflightError, prepare_film_type_props
from lib.persian_glyph_verify import COMPOSER, FPS, SCRIPT, _black_clip, verification_props

ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.skipif(
    os.environ.get("OPENMONTAGE_L2_MEDIA_TESTS") != "1",
    reason="opt-in real Chromium/FFmpeg suite",
)

DURATION = 14.0
HOOK = {
    "id": "m-hook", "kind": "hook", "startSeconds": 0.0, "endSeconds": 5.0,
    "segments": [{"role": "hero", "text": "صبحِ روز بعد"},
                 {"role": "tail", "text": "زمانِ پیام بعد از قرار اول"}],
}
# One unbreakable ZWNJ-joined word: no ladder size fits it inside the safe area.
UNPLACEABLE = {
    "id": "m-long", "kind": "statement", "startSeconds": 7.0, "endSeconds": 13.0,
    "segments": [{"role": "hero", "text": "بزرگ‌ترین‌بی‌نظیرترین‌شگفت‌انگیزترین‌هایشان"}],
}
FULL_FRAME_FACE = [{"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0, "priority": "hard"}]
CORNER_FACE = [{"x": 0.3, "y": 0.1, "w": 0.45, "h": 0.25, "priority": "hard"}]


def _design() -> dict:
    pin = os.environ.get("OPENMONTAGE_L2_FILM_TYPE_PIN")
    raw = {"version": 2, "profile": "film-type", "seed": "issue387-l2"}
    if pin:
        profile = canonical_numbers(json.loads(
            (ROOT / "styles" / "persian-footage" / f"film-type-{pin}.json").read_text(encoding="utf-8")))
        digest = hashlib.sha256(json.dumps(
            profile, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")).hexdigest()
        raw.update(resolved=profile, profileVersion=pin, contentHash=digest)
    return resolve_design(raw)


def _props(regions: list[dict], moments: list[dict], *, staged: bool = True) -> dict:
    props = {
        "format": "vertical", "durationSeconds": DURATION, "design": _design(),
        "watermark": {"persianText": "طریقت تسلیم", "latinText": "Pathway_of_Surrender"},
        "typographicBeats": [], "captionMode": "hybrid",
        "captions": [
            {"id": f"c{i}", "startSeconds": 0.2 + i * 3.4, "endSeconds": 0.2 + i * 3.4 + 3.2,
             "text": "طرف مقابل پیام می‌داد", "lines": ["طرف مقابل پیام می‌داد"]}
            for i in range(4)
        ],
        "shots": [{
            "id": "s1", "source": "unused.mp4", "startSeconds": 0.0, "endSeconds": DURATION,
            "avoidRegions": [{**r, "startSeconds": 0.0, "endSeconds": DURATION} for r in regions],
        }],
        "moments": [dict(m) for m in moments],
    }
    if staged:
        props["pipelineProfile"] = "v3_staged"
    return props


def _prepare(props: dict, tmp_path: Path) -> dict:
    return prepare_film_type_props(props, ROOT / "remotion-composer", scratch_dir=tmp_path)


def test_v2_still_refuses_text_on_a_full_frame_subject(tmp_path: Path) -> None:
    with pytest.raises(FilmTypePreflightError):
        _prepare(_props(FULL_FRAME_FACE, [HOOK], staged=False), tmp_path)


def test_free_area_is_the_first_step(tmp_path: Path) -> None:
    prepared = _prepare(_props(CORNER_FACE, [HOOK]), tmp_path)
    assert prepared["filmType"]["stagedText"]["m-hook"]["step"] == "free_area"


def test_text_over_a_full_frame_subject_uses_a_scrim_not_a_send_back(tmp_path: Path) -> None:
    prepared = _prepare(_props(FULL_FRAME_FACE, [HOOK]), tmp_path)
    decision = prepared["filmType"]["stagedText"]["m-hook"]
    assert decision["step"] == "scrim", decision
    layout = prepared["filmType"]["moments"]["m-hook"]
    assert layout["strength"] == "strong"
    assert prepared["moments"][0]["subtitleFallback"] is False


def test_unplaceable_copy_keeps_the_subtitle_and_is_recorded(tmp_path: Path) -> None:
    prepared = _prepare(_props(CORNER_FACE, [HOOK, UNPLACEABLE]), tmp_path)
    decision = prepared["filmType"]["stagedText"]["m-long"]
    assert decision["step"] == "subtitle_fallback", decision
    assert "m-long" not in prepared["filmType"]["moments"]
    flags = {m["id"]: m["subtitleFallback"] for m in prepared["moments"]}
    assert flags == {"m-hook": False, "m-long": True}
    assert any("styled-text-subtitle-fallback" in w for w in prepared["filmType"]["warnings"])
    # The saved layout is reproducible: a second prepass over the prepared props agrees.
    again = _prepare(prepared, tmp_path)
    assert again["filmType"] == prepared["filmType"]


def _evidence_dir() -> Path:
    base = os.environ.get("OPENMONTAGE_L2_EVIDENCE_PATH")
    root = Path(base).parent if base else ROOT / "test-artifacts" / "issue387-l2"
    path = root / "issue387-staged-text"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _ink_fraction(image: np.ndarray, y0: float, y1: float) -> float:
    h = image.shape[0]
    band = image[int(h * y0):int(h * y1)]
    return float((band.max(axis=2) > 140).mean())


def test_stills_show_the_scrim_moment_and_the_subtitle_in_the_fallback_span(tmp_path: Path) -> None:
    prepared = _prepare(_props(FULL_FRAME_FACE, [HOOK, UNPLACEABLE]), tmp_path)
    assert prepared["filmType"]["stagedText"]["m-hook"]["step"] == "scrim"
    assert prepared["filmType"]["stagedText"]["m-long"]["step"] == "subtitle_fallback"
    run_id = secrets.token_hex(4)
    public = COMPOSER / "public" / "persian" / f"issue387-{run_id}"
    public.mkdir(parents=True, exist_ok=True)
    try:
        _black_clip(public / "black.mp4", DURATION + 1.0, "vertical")
        vprops = verification_props(prepared, f"persian/issue387-{run_id}/black.mp4")
        frames = {"hook": int(4.0 * FPS), "fallback": int(9.0 * FPS)}
        with tempfile.TemporaryDirectory(prefix="issue387-stills-") as tmp:
            work = Path(tmp)
            (work / "props.json").write_text(json.dumps(vprops, ensure_ascii=False), encoding="utf-8")
            (work / "request.json").write_text(json.dumps(
                {"frames": [{"momentId": key, "frame": frame} for key, frame in frames.items()]}))
            done = subprocess.run(
                ["node", str(SCRIPT), str(work / "props.json"), str(work / "request.json"), str(work / "stills")],
                cwd=COMPOSER, capture_output=True, text=True, timeout=1800,
            )
            assert done.returncode == 0, (done.stderr or "")[-2000:]
            evidence = _evidence_dir()
            stills = {}
            for key in frames:
                source = work / "stills" / f"{key}-frame.png"
                shutil.copy(source, evidence / f"{key}-frame.png")
                stills[key] = np.asarray(Image.open(source).convert("RGB"))
    finally:
        shutil.rmtree(public, ignore_errors=True)
    # The hook paints ink inside its measured rect over the full-frame subject (the clip
    # itself is black). The fallback span rendered at all, which needs the renderer to
    # skip the unplaced moment, and its burned subtitle paints in the lower band.
    rect = prepared["filmType"]["moments"]["m-hook"]["rect"]
    h, w = stills["hook"].shape[:2]
    inside = stills["hook"][int(rect["y"] * h):int((rect["y"] + rect["h"]) * h),
                            int(rect["x"] * w):int((rect["x"] + rect["w"]) * w)]
    assert float((inside.max(axis=2) > 140).mean()) > 0.01
    assert _ink_fraction(stills["fallback"], 0.6, 0.97) > 0.001
    (evidence / "decisions.json").write_text(json.dumps(
        prepared["filmType"]["stagedText"], ensure_ascii=False, indent=2), encoding="utf-8")
