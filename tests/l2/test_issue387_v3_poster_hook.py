"""#387: the v3 opening hook reads like a poster, also over bright footage.

Mehran's acceptance review of the v3 run: the hook was too small next to the rest of
the video, its hierarchy was weak, and over a bright shot it was hard to read. Under
v3_staged a semantic poster hook now gets:
  * a dominant subject hero (about 2.7x the setup line) and a bridge close to the setup,
  * a thin accent divider after the setup and a brush underline under the hero,
  * a vertically feathered dark band behind the hook block only (not the whole frame).
v2 output is unchanged. Real Chromium + Film Type fonts (opt-in L2).
"""
from __future__ import annotations

import json
import secrets
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from lib.persian_glyph_verify import COMPOSER, FPS, SCRIPT, verification_props
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


def _rows(prepared: dict) -> dict:
    layout = prepared["filmType"]["moments"]["m-hook"]
    return layout, {row["text"]: row for row in layout["rows"]}


def test_v3_hero_dominates_and_the_bridge_is_not_a_footnote(tmp_path: Path) -> None:
    layout, rows = _rows(_prepare(_props([], [POSTER_HOOK]), tmp_path))
    setup, bridge, hero = rows[SETUP], rows[BRIDGE], rows[HERO]
    assert hero["fontSizePx"] >= 2.5 * setup["fontSizePx"], (hero["fontSizePx"], setup["fontSizePx"])
    assert hero["widthPx"] >= 0.42 * 1080, hero["widthPx"]
    assert bridge["fontSizePx"] >= 0.85 * setup["fontSizePx"]
    assert setup["fontSizePx"] >= 46, "the setup line must not shrink to make room for the hero"
    decor = layout["posterDecor"]
    divider, underline = decor["divider"], decor["underline"]
    # Ornaments live in the gaps, outside every row's ink box.
    assert setup["baselinePx"] + setup["belowPx"] < divider["centerYPx"] < bridge["baselinePx"] - bridge["abovePx"]
    assert underline["topPx"] > hero["baselinePx"] + hero["belowPx"]
    assert underline["topPx"] + underline["heightPx"] <= layout["heightPx"]
    assert decor["band"]["alpha"] >= 0.5


def test_v2_poster_hook_is_unchanged(tmp_path: Path) -> None:
    layout, rows = _rows(_prepare(_props([], [POSTER_HOOK], staged=False), tmp_path))
    assert "posterDecor" not in layout
    assert abs(rows[SETUP]["fontSizePx"] - round(rows[HERO]["fontSizePx"] * .56)) <= 1


def _white_clip(path: Path, seconds: float) -> None:
    subprocess.run(
        ["ffmpeg", "-nostdin", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
         f"color=c=white:s=1080x1920:r={FPS}", "-t", f"{seconds:.3f}", "-c:v", "libx264",
         "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(path)],
        check=True, timeout=120,
    )


def _linear(v: np.ndarray) -> np.ndarray:
    x = v / 255.0
    return np.where(x <= .04045, x / 12.92, ((x + .055) / 1.055) ** 2.4)


def _luma(rgb: np.ndarray) -> np.ndarray:
    return _linear(rgb) @ np.array([.2126, .7152, .0722])


def test_hook_stays_readable_over_pure_white_footage(tmp_path: Path) -> None:
    prepared = _prepare(_props([], [POSTER_HOOK]), tmp_path)
    layout, rows = _rows(prepared)
    run_id = secrets.token_hex(4)
    public = COMPOSER / "public" / "persian" / f"issue387-poster-{run_id}"
    public.mkdir(parents=True, exist_ok=True)
    try:
        _white_clip(public / "white.mp4", DURATION + 1.0)
        vprops = verification_props(prepared, f"persian/issue387-poster-{run_id}/white.mp4")
        with tempfile.TemporaryDirectory(prefix="issue387-poster-") as tmp:
            work = Path(tmp)
            (work / "props.json").write_text(json.dumps(vprops, ensure_ascii=False), encoding="utf-8")
            (work / "request.json").write_text(json.dumps({"frames": [{"momentId": "m-hook", "frame": int(3.0 * FPS)}]}))
            done = subprocess.run(
                ["node", str(SCRIPT), str(work / "props.json"), str(work / "request.json"), str(work / "stills")],
                cwd=COMPOSER, capture_output=True, text=True, timeout=1800,
            )
            assert done.returncode == 0, (done.stderr or "")[-2000:]
            background = np.asarray(Image.open(work / "stills" / "m-hook-background.png").convert("RGB"), dtype=float)
            frame = np.asarray(Image.open(work / "stills" / "m-hook-frame.png").convert("RGB"), dtype=float)
            evidence = Path("test-artifacts") / "issue387-poster-hook"
            evidence.mkdir(parents=True, exist_ok=True)
            shutil.copy(work / "stills" / "m-hook-frame.png", evidence / "white-footage-hook.png")
    finally:
        shutil.rmtree(public, ignore_errors=True)
    h, w = background.shape[:2]
    rect = layout["rect"]
    top, left = rect["y"] * h, rect["x"] * w
    for text, minimum in ((SETUP, 4.5), (BRIDGE, 4.5), (HERO, 3.0)):
        row = rows[text]
        y0, y1 = int(top + row["baselinePx"] - row["abovePx"]), int(top + row["baselinePx"] + row["belowPx"])
        centered = layout["placement"] == "center" or layout["placement"].endswith("-center")
        right = left + (layout["widthPx"] / 2 + row["widthPx"] / 2 if centered else layout["widthPx"] - 12)
        x0, x1 = int(right - row["widthPx"]), int(right)
        behind = float(np.median(_luma(background[y0:y1, x0:x1])))
        ink = 1.0 if text != HERO else float(_luma(np.array([[255.0, 234.0, 0.0]]))[0])
        ratio = (ink + .05) / (behind + .05)
        assert ratio >= minimum, (text, round(ratio, 2), round(behind, 3))
    # The band is local: the lower half of the frame keeps the footage untouched.
    assert float(np.median(_luma(background[int(h * .7):int(h * .9)]))) > .9
    # Both ornaments are painted in the accent yellow (high red+green, low blue).
    yellow = (frame[..., 0] > 200) & (frame[..., 1] > 180) & (frame[..., 2] < 90)
    decor = layout["posterDecor"]
    dy = int(top + decor["divider"]["centerYPx"])
    assert yellow[dy - 2:dy + 3].any(), "divider not painted"
    uy0 = int(top + decor["underline"]["topPx"])
    assert yellow[uy0:uy0 + decor["underline"]["heightPx"]].mean() > 0.02, "underline not painted"
