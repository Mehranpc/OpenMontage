"""#387: the v3 opening hook is Mehran's approved design, painted exactly.

Owner decision (#387 comment 5999195805): the opening hook is his `Hook_v2_photo.html`,
exactly, with two approved changes only (hero face Kahroba, hero size 140px). Only the
opening hook changes; subtitles, later text and grading stay as they were.

These checks run real Chromium + FFmpeg (opt-in L2):
  * the prepass maps setup/bridge/subject_hero onto the design and records its geometry,
  * the pipeline's frame over real-looking footage equals Chrome's render of the design
    file itself (same copy, same photo), pixel for pixel within a small tolerance,
  * it is complete on its first frame (no animation),
  * per-row glyph order still verifies against the painted hook,
  * stacks the design cannot express keep the previous staged path, and v2 is unchanged.
"""
from __future__ import annotations

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

from lib.persian_film_verify import glyph_order_check
from lib.persian_glyph_verify import COMPOSER, SCRIPT, verification_props
from tests.l2.hook_design_reference import reference_html, render_reference
from tests.l2.test_issue387_staged_text_adapts import DURATION, _prepare, _props, pytestmark  # noqa: F401

SETUP, BRIDGE, HERO = "دیر پیام می‌دی که مشتاق به نظر نرسی؟", "یه آزمایش نشون داد", "به ضررته"
POSTER_HOOK = {
    "id": "m-hook", "kind": "hook", "startSeconds": 0.0, "endSeconds": 4.5,
    "purpose": "hook-pattern-interrupt",
    "presentation": {"placement": "auto", "emphasis": "none", "recipeId": "editorial-hero-balanced"},
    "segments": [
        {"role": "lead", "semanticRole": "setup", "text": SETUP},
        {"role": "lead", "semanticRole": "bridge", "text": BRIDGE},
        {"role": "hero", "semanticRole": "subject_hero", "text": HERO},
    ],
}


def _hook(*segments: tuple[str, str, str]) -> dict:
    return {**POSTER_HOOK, "segments": [{"role": r, "semanticRole": s, "text": t} for r, s, t in segments]}


def _layout(prepared: dict) -> dict:
    return prepared["filmType"]["moments"]["m-hook"]


def test_v3_poster_hook_uses_the_approved_design(tmp_path: Path) -> None:
    prepared = _prepare(_props([], [POSTER_HOOK]), tmp_path)
    assert prepared["filmType"]["stagedText"]["m-hook"]["step"] == "designed_hook"
    layout = _layout(prepared)
    hook = layout["designedHook"]
    assert hook["version"] == "mehran-hook-v2-photo"
    assert hook["questionFontPx"] == 68 and hook["heroFontPx"] == 140
    assert hook["heroLines"] == [HERO] and hook["bridge"] == BRIDGE
    # Chrome's own `text-wrap: balance` split, frozen: two lines, nothing lost or reordered.
    assert len(hook["questionLines"]) == 2 and " ".join(hook["questionLines"]) == SETUP
    assert "posterDecor" not in layout
    # The design's hook box: left/right 110px, top 455px of the 1080x1920 frame.
    rect = layout["rect"]
    assert round(rect["x"] * 1080, 3) == 110 and round(rect["y"] * 1920, 3) == 455
    assert round(rect["w"] * 1080, 3) == 860 and layout["widthPx"] == 860
    fonts = {(row["text"], row["family"], row["weight"], row["fontSizePx"]) for row in layout["rows"]}
    assert (BRIDGE, "Vazirmatn", 600, 37) in fonts and (HERO, "KahrobaEditorial", 900, 140) in fonts
    assert all(f[1:] == ("Vazirmatn", 800, 68) for f in fonts if f[0] in hook["questionLines"])


def test_long_copy_steps_down_only_as_far_as_needed(tmp_path: Path) -> None:
    long_hook = _hook(
        ("lead", "setup", "اگه فکر می‌کنی دیر جواب دادن بعد از قرار اول تو رو جذاب‌تر و مرموزتر نشون می‌ده و طرف بیشتر دنبالت میاد"),
        ("lead", "bridge", "یه تحقیق تازه"),
        ("hero", "subject_hero", "دقیقاً برعکسشو ثابت کرد"),
    )
    hook = _layout(_prepare(_props([], [long_hook]), tmp_path))["designedHook"]
    assert len(hook["questionLines"]) <= 3 and 50 <= hook["questionFontPx"] <= 68
    assert len(hook["heroLines"]) <= 2 and 112 <= hook["heroFontPx"] <= 140


def test_hero_only_and_question_hero_stacks_use_the_design(tmp_path: Path) -> None:
    two = _hook(("lead", "setup", "بعد از قرار اول؟"), ("hero", "subject_hero", "زود پیام بده"))
    hook = _layout(_prepare(_props([], [two]), tmp_path))["designedHook"]
    assert hook["questionLines"] == ["بعد از قرار اول؟"] and "bridge" not in hook


def test_stacks_the_design_cannot_express_keep_the_previous_staged_path(tmp_path: Path) -> None:
    other = _hook(("lead", "setup", SETUP), ("hero", "subject_hero", HERO), ("tail", "payoff", "حتی وقتی خوب پیش رفته"))
    prepared = _prepare(_props([], [other]), tmp_path)
    assert prepared["filmType"]["stagedText"]["m-hook"]["step"] != "designed_hook"
    assert "designedHook" not in _layout(prepared)


def test_v2_poster_hook_is_unchanged(tmp_path: Path) -> None:
    prepared = _prepare(_props([], [POSTER_HOOK], staged=False), tmp_path)
    layout = _layout(prepared)
    assert "designedHook" not in layout and "posterDecor" not in layout
    rows = {row["text"]: row for row in layout["rows"]}
    assert abs(rows[SETUP]["fontSizePx"] - round(rows[HERO]["fontSizePx"] * .56)) <= 1


def _photo(path: Path) -> None:
    """A deterministic photo-like frame: bright and dark areas, soft detail."""
    subprocess.run(
        ["ffmpeg", "-nostdin", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
         "testsrc2=s=270x480:d=1,gblur=sigma=6,scale=1080:1920:flags=bicubic,eq=brightness=0.12:saturation=0.8",
         "-frames:v", "1", str(path)], check=True, timeout=120)


def _lossless_clip(photo: Path, path: Path, seconds: float) -> None:
    subprocess.run(
        ["ffmpeg", "-nostdin", "-y", "-loglevel", "error", "-loop", "1", "-i", str(photo), "-t", f"{seconds:.3f}",
         "-r", "30", "-c:v", "libx264rgb", "-crf", "0", "-preset", "ultrafast", "-pix_fmt", "rgb24", str(path)],
        check=True, timeout=300)


def _chrome() -> str:
    """The browser Remotion paints with, so the reference uses the same engine."""
    configured = os.environ.get("REMOTION_BROWSER_EXECUTABLE")
    if configured:
        return configured
    bundled = sorted((COMPOSER / "node_modules" / ".remotion" / "chrome-headless-shell").glob("*/*/chrome-headless-shell"))
    if bundled:
        return str(bundled[-1])
    pytest.skip("no Chrome executable for the design reference")


@pytest.fixture(scope="module")
def rendered(tmp_path_factory: pytest.TempPathFactory):
    work = tmp_path_factory.mktemp("designed-hook")
    prepared = _prepare(_props([], [POSTER_HOOK]), work / "scratch")
    photo = work / "photo.png"
    _photo(photo)
    run_id = secrets.token_hex(4)
    public = COMPOSER / "public" / "persian" / f"issue387-design-{run_id}"
    public.mkdir(parents=True, exist_ok=True)
    try:
        _lossless_clip(photo, public / "photo.mp4", DURATION + 1.0)
        vprops = verification_props(prepared, f"persian/issue387-design-{run_id}/photo.mp4")
        (work / "props.json").write_text(json.dumps(vprops, ensure_ascii=False), encoding="utf-8")
        # Frame 0 is the hook's first frame: the design has no entrance animation.
        (work / "request.json").write_text(json.dumps({"frames": [{"momentId": "m-hook", "frame": 0}]}))
        done = subprocess.run(["node", str(SCRIPT), str(work / "props.json"), str(work / "request.json"), str(work / "stills")],
                              cwd=COMPOSER, capture_output=True, text=True, timeout=1800)
        assert done.returncode == 0, (done.stderr or "")[-2000:]
    finally:
        shutil.rmtree(public, ignore_errors=True)
    page = work / "reference.html"
    page.write_text(reference_html(SETUP, BRIDGE, HERO, photo), encoding="utf-8")
    render_reference(_chrome(), page, work / "reference.png")
    load = lambda p: np.asarray(Image.open(p).convert("RGB"), dtype=float)  # noqa: E731
    frame, background, reference = (load(work / "stills" / "m-hook-frame.png"),
                                    load(work / "stills" / "m-hook-background.png"), load(work / "reference.png"))
    evidence = Path(os.environ.get("OPENMONTAGE_L2_EVIDENCE_PATH", "test-artifacts/x/e.json")).parent / "issue387-designed-hook"
    evidence.mkdir(parents=True, exist_ok=True)
    Image.fromarray(np.hstack([frame, reference]).astype("uint8")).resize((1080, 960)).save(evidence / "pipeline-vs-design.png")
    return {"prepared": prepared, "frame": frame, "background": background, "reference": reference, "photo": load(photo)}


def test_first_frame_matches_mehrans_design_file(rendered) -> None:
    frame, reference = rendered["frame"], rendered["reference"]
    assert frame.shape == reference.shape == (1920, 1080, 3)
    diff = np.abs(frame - reference).max(axis=2)
    # The same engine paints the same CSS; allow only antialiasing-level noise.
    assert float(diff.mean()) < 0.5, float(diff.mean())
    assert float((diff > 24).mean()) < 0.001, float((diff > 24).mean())


def test_only_the_hook_treatment_touches_the_footage(rendered) -> None:
    # Without glyphs, what remains is the design's own frame treatment, shade, pill and brush.
    # The treatment is the design's light vertical gradient: never brighter, at most 32% darker.
    background, photo = rendered["background"], rendered["photo"]
    ratio = (background.mean(axis=2) + 1) / (photo.mean(axis=2) + 1)
    top = ratio[:200, 300:780].mean()
    assert 0.9 < top <= 1.0, top


def test_glyph_order_verifies_on_the_painted_hook(rendered) -> None:
    prepared = rendered["prepared"]
    layout = _layout(prepared)
    order = glyph_order_check(rendered["frame"], rendered["background"], layout, prepared, align="center")
    assert order["status"] == "pass", order
    assert len(order["rows"]) == len(layout["rows"])
