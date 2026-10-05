"""#387: the v3 poster hook's finish matches Mehran's reference, not just its sizes.

Mehran's review of the poster hook (#403): the shadow read as a black rectangle, the
divider was a flat line and the underline a flat bar. His reference has:
  * a soft dark glow that is darkest at the centre and fades out on every side,
  * a divider that is thick in the middle and tapers to thin ends,
  * a real brush stroke (ragged edges, dry bristle streaks) under the hero.
These checks measure those shapes on real Chromium pixels over pure white footage.
"""
from __future__ import annotations

import json
import secrets
import tempfile
import subprocess
from pathlib import Path

import numpy as np
import pytest

from PIL import Image

from lib.persian_glyph_verify import COMPOSER, FPS, SCRIPT, verification_props
from tests.l2.test_issue387_staged_text_adapts import DURATION, _prepare, _props, pytestmark  # noqa: F401
from tests.l2.test_issue387_v3_poster_hook import HERO, POSTER_HOOK, _rows, _white_clip
import shutil


@pytest.fixture(scope="module")
def rendered(tmp_path_factory: pytest.TempPathFactory):
    tmp_path = tmp_path_factory.mktemp("poster-finish")
    prepared = _prepare(_props([], [POSTER_HOOK]), tmp_path)
    layout, rows = _rows(prepared)
    run_id = secrets.token_hex(4)
    public = COMPOSER / "public" / "persian" / f"issue387-finish-{run_id}"
    public.mkdir(parents=True, exist_ok=True)
    try:
        _white_clip(public / "white.mp4", DURATION + 1.0)
        vprops = verification_props(prepared, f"persian/issue387-finish-{run_id}/white.mp4")
        with tempfile.TemporaryDirectory(prefix="issue387-finish-") as tmp:
            work = Path(tmp)
            (work / "props.json").write_text(json.dumps(vprops, ensure_ascii=False), encoding="utf-8")
            (work / "request.json").write_text(json.dumps({"frames": [{"momentId": "m-hook", "frame": int(3.0 * FPS)}]}))
            done = subprocess.run(
                ["node", str(SCRIPT), str(work / "props.json"), str(work / "request.json"), str(work / "stills")],
                cwd=COMPOSER, capture_output=True, text=True, timeout=1800,
            )
            assert done.returncode == 0, (done.stderr or "")[-2000:]
            background = np.asarray(Image.open(work / "stills" / "m-hook-background.png").convert("RGB"), dtype=float) / 255.0
            frame = np.asarray(Image.open(work / "stills" / "m-hook-frame.png").convert("RGB"), dtype=float)
            evidence = Path("test-artifacts") / "issue387-poster-finish"
            evidence.mkdir(parents=True, exist_ok=True)
            shutil.copy(work / "stills" / "m-hook-frame.png", evidence / "white-footage-hook.png")
            shutil.copy(work / "stills" / "m-hook-background.png", evidence / "white-footage-background.png")
    finally:
        shutil.rmtree(public, ignore_errors=True)
    return layout, rows, background, frame


def _origin(layout: dict, shape: tuple[int, ...]) -> tuple[float, float, float]:
    h, w = shape[:2]
    rect = layout["rect"]
    return rect["y"] * h, rect["x"] * w, rect["x"] * w + layout["widthPx"] / 2


def _yellow(frame: np.ndarray) -> np.ndarray:
    return (frame[..., 0] > 190) & (frame[..., 1] > 170) & (frame[..., 2] < 110)


def test_shadow_is_a_soft_glow_not_a_rectangle(rendered) -> None:
    layout, _rows_, background, _ = rendered
    gray = background.mean(axis=2)
    h, w = gray.shape
    top, _, cx = _origin(layout, background.shape)
    cy = int(top + layout["rect"]["h"] * h / 2)
    row = gray[cy - 4:cy + 5].mean(axis=0)
    centre = 1.0 - float(row[int(cx) - 4:int(cx) + 5].mean())
    assert centre >= 0.5, f"glow too weak at its centre: {centre:.2f}"
    # Fades sideways: the frame edges at the text's height stay much lighter.
    for x in (int(w * .02), int(w * .98)):
        side = 1.0 - float(row[max(0, x - 4):x + 5].mean())
        assert side <= 0.5 * centre, ("shadow reaches the frame edge like a band", x, round(side, 3), round(centre, 3))
    # No hard edge along the horizontal line through its centre, nor vertically
    # (sampled left of the ornaments, which the background still paints).
    column = gray[: int(h * .7), int(w * .12) - 4:int(w * .12) + 5].mean(axis=1)
    for name, line in (("horizontal", row), ("vertical", column)):
        step = float(np.abs(line[6:] - line[:-6]).max())
        assert step <= 0.035, (f"{name} edge is too sharp", round(step, 3))


def _thickness(mask: np.ndarray) -> np.ndarray:
    return mask.sum(axis=0)


def test_divider_is_thick_in_the_middle_and_tapers(rendered) -> None:
    layout, _rows_, _, frame = rendered
    top, _, cx = _origin(layout, frame.shape)
    dv = layout["posterDecor"]["divider"]
    cy = int(top + dv["centerYPx"])
    band = _yellow(frame[cy - 12:cy + 13])
    x0, width = cx - dv["widthPx"] / 2, dv["widthPx"]
    at = lambda t: float(np.median(_thickness(band[:, int(x0 + width * t) - 3:int(x0 + width * t) + 4])))
    centre = at(.5)
    assert centre >= 4, f"divider too thin at its centre: {centre}"
    for t in (.15, .85):
        assert at(t) <= .5 * centre, ("divider does not taper", t, at(t), centre)


def test_underline_is_a_brush_stroke(rendered) -> None:
    layout, rows, _, frame = rendered
    top, _, cx = _origin(layout, frame.shape)
    u = layout["posterDecor"]["underline"]
    # Start strictly below the hero's ink box so no glyph pixel is counted.
    y0 = int(top + u["topPx"]) + 1
    y1 = int(top + u["topPx"] + 2 * u["heightPx"])
    x0, x1 = int(cx - u["widthPx"] / 2), int(cx + u["widthPx"] / 2)
    mask = _yellow(frame[y0:y1, x0:x1])
    painted = mask.any(axis=0)
    assert painted.mean() > .8, "underline not painted across its width"
    thick = _thickness(mask)
    assert .12 * rows[HERO]["fontSizePx"] <= thick.max() <= .26 * rows[HERO]["fontSizePx"], ("brush body thickness", thick.max())
    # It rises to the right like Mehran's reference stroke (not a flat bar).
    cols_ = np.flatnonzero(painted)
    mid = lambda c: float(np.mean(np.flatnonzero(mask[:, c])))
    left = np.mean([mid(c) for c in cols_ if len(painted) * .25 <= c < len(painted) * .35])
    right = np.mean([mid(c) for c in cols_ if len(painted) * .65 <= c < len(painted) * .75])
    assert left - right >= .018 * u["widthPx"], ("brush has no slope", round(left - right, 1))
    # Dry-brush bristles: some columns cross several separate yellow streaks.
    runs = (np.diff(mask.astype(int), axis=0) == 1).sum(axis=0) + mask[0].astype(int)
    assert (runs >= 2).mean() >= .08, f"no bristle streaks: {(runs >= 2).mean():.3f}"
    # Ragged edge: the top contour wobbles around its own smooth trend.
    cols = np.flatnonzero(painted)
    cols = cols[(cols > len(painted) * .2) & (cols < len(painted) * .8)]
    edge = np.array([np.argmax(mask[:, c]) for c in cols], dtype=float)
    trend = np.convolve(edge, np.ones(41) / 41, mode="same")
    rough = float(np.std((edge - trend)[25:-25]))
    assert rough >= .6, f"underline edge is perfectly smooth (std {rough:.2f}px)"
