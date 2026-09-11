from __future__ import annotations

import pytest

from lib.persian_captions import (
    BURNED_CAPTION_MAX_LINE_VISIBLE_CHARS,
    build_burned_caption_props,
    default_caption_mode,
    layout_caption_lines,
    resolve_caption_mode,
)
from lib.persian_srt import PersianCue
from lib.persian_text import visible_length


def test_legacy_absence_resolves_to_sidecar_only() -> None:
    assert resolve_caption_mode(None) == "sidecar_only"


def test_instagram_reels_default_is_hybrid() -> None:
    assert default_caption_mode("instagram-reels") == "hybrid"
    assert resolve_caption_mode(None, platform_target="instagram") == "hybrid"


def test_explicit_sidecar_overrides_instagram_default() -> None:
    assert resolve_caption_mode("sidecar_only", platform_target="instagram-reels") == "sidecar_only"


@pytest.mark.parametrize("mode", ["sidecar_only", "burned_captions", "hybrid"])
def test_all_caption_modes_are_declared(mode: str) -> None:
    assert resolve_caption_mode(mode) == mode


def test_unknown_caption_mode_is_refused() -> None:
    with pytest.raises(ValueError, match="captionMode"):
        resolve_caption_mode("karaoke")


def test_short_caption_stays_one_line() -> None:
    assert layout_caption_lines("این یک کپشن کوتاه است.") == ["این یک کپشن کوتاه است."]


def test_longer_caption_balances_into_two_bounded_lines() -> None:
    lines = layout_caption_lines(
        "وقتی عذرخواهی می‌کنی روشن حرف بزن تا منظورت گم نشود."
    )
    assert len(lines) == 2
    assert all(visible_length(line) <= BURNED_CAPTION_MAX_LINE_VISIBLE_CHARS for line in lines)


def test_unfit_caption_is_refused_instead_of_shrinking_type() -> None:
    with pytest.raises(ValueError, match="display ceiling|fit two"):
        layout_caption_lines("واژه " * 30)


def test_burned_props_preserve_approved_text_and_timing() -> None:
    cue = PersianCue(
        id="caption-1",
        text="این متن تاییدشده است.",
        start_seconds=1.25,
        end_seconds=3.5,
    )
    props = build_burned_caption_props([cue])
    assert props == [{
        "id": "caption-1",
        "text": cue.text,
        "lines": [cue.text],
        "startSeconds": 1.25,
        "endSeconds": 3.5,
    }]
