"""#228: Film Type row glyph order is checked against a shaped reference, not assumed."""

from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw

from lib.persian_film_verify import _row_font, glyph_order_check

W, H = 1080, 1920
TEXT = "زمانِ پیام بعد از"


def _setup(painted_text: str):
    row = {"text": TEXT, "role": "tail", "fontSizePx": 72, "weight": 700, "family": "Estedad",
           "direction": "rtl", "abovePx": 60, "belowPx": 30, "baselinePx": 90, "widthPx": 0.0}
    font = _row_font(row, 1.0)
    measure = Image.new("L", (1000, 200), 0)
    box = ImageDraw.Draw(measure).textbbox((0, 0), TEXT, font=font, direction="rtl", language="fa")
    row["widthPx"] = float(box[2] - box[0])
    layout = {"rect": {"x": 0.3, "y": 0.45, "w": (row["widthPx"] + 24) / W, "h": 150 / H},
              "widthPx": row["widthPx"] + 24, "placement": "mid-right", "rows": [row]}
    background = np.full((H, W, 3), 30.0)
    image = Image.fromarray(background.astype(np.uint8))
    left = layout["rect"]["x"] * W + layout["widthPx"] - 12 - row["widthPx"]
    top = layout["rect"]["y"] * H + row["baselinePx"] - row["abovePx"]
    ImageDraw.Draw(image).text((left - box[0], top - box[1] + (row["abovePx"] - (box[3] - box[1]))),
                               painted_text, font=font, fill=(255, 255, 255), direction="rtl", language="fa")
    props = {"format": "vertical", "design": {"resolved": {"layout": {"inkPaddingPx": 12}}}}
    return np.asarray(image).astype(float), background, layout, props


def test_correct_order_passes() -> None:
    frame, background, layout, props = _setup(TEXT)
    result = glyph_order_check(frame, background, layout, props)
    assert result["status"] == "pass", result


def test_reversed_word_order_fails() -> None:
    frame, background, layout, props = _setup(" ".join(reversed(TEXT.split())))
    assert glyph_order_check(frame, background, layout, props)["status"] == "fail"


def test_mirrored_row_fails() -> None:
    frame, background, layout, props = _setup(TEXT)
    rect = layout["rect"]
    x0, x1 = int(rect["x"] * W), int((rect["x"] + rect["w"]) * W)
    y0, y1 = int(rect["y"] * H), int((rect["y"] + rect["h"]) * H)
    frame[y0:y1, x0:x1] = frame[y0:y1, x0:x1][:, ::-1]
    assert glyph_order_check(frame, background, layout, props)["status"] == "fail"


def test_missing_font_is_not_checked_never_passed() -> None:
    frame, background, layout, props = _setup(TEXT)
    layout["rows"][0]["family"] = "KahrobaEditorial"
    result = glyph_order_check(frame, background, layout, props)
    if result["rows"][0]["status"] == "not_checked":
        assert result["status"] == "not_checked"


def test_verifier_reports_glyph_order_without_claiming_approval() -> None:
    from lib.persian_film_verify import verify_film_frames

    frame, background, layout, props = _setup(TEXT)
    props.update({
        "design": {"profile": "film-type", "resolved": {
            "layout": {"inkPaddingPx": 12},
            "motion": {"enterSeconds": .56, "cutInSeconds": .48, "exitSeconds": .22},
            "typography": {"ink": "#FFFFFF", "darkInk": "#191919"}}},
        "filmType": {"moments": {"m": {**layout, "contrastMode": "dark"}}},
        "moments": [{"id": "m", "startSeconds": 0, "endSeconds": 5,
                     "segments": [{"text": TEXT, "role": "tail"}]}],
    })
    footage = background + 20
    mask = (frame.min(axis=2) > 250).astype(float)  # fully opaque glyph cores
    report = verify_film_frames([("m", frame)], props, {"m": {
        "background": background, "footage": footage, "ink_mask": mask, "seconds": 2}})
    assert report["frames"]["m"]["glyph_order"] == "pass", report
    assert report["glyph_order_verified"] is True
    assert report["persian_text_verified"] is False
