"""#252: the glyph-verification plan picks a fully-arrived frame and strips only media."""

from __future__ import annotations

from lib.persian_glyph_verify import FPS, stable_frame, verification_props

MOTION = {"exitSeconds": 0.22}


def test_stable_frame_is_inside_the_moment_before_its_exit() -> None:
    frame, rows = stable_frame({"startSeconds": 8.0, "endSeconds": 12.0},
                               {"rows": [{"role": "hero", "text": "x"}, {"role": "brand", "text": "b"}]}, MOTION)
    assert 8.0 * FPS < frame < (12.0 - 0.22) * FPS
    assert [row["role"] for row in rows] == ["hero"]


def test_replace_sequence_checks_only_the_rows_on_screen() -> None:
    _, rows = stable_frame(
        {"startSeconds": 0.0, "endSeconds": 5.0, "presentation": {"sequenceMode": "replace"}},
        {"rows": [{"role": "hero", "text": "a", "revealAfterSeconds": 0.0},
                  {"role": "hero", "text": "b", "revealAfterSeconds": 2.0}]}, MOTION)
    assert [row["text"] for row in rows] == ["b"]


def test_verification_props_keep_layout_and_timing_but_drop_media() -> None:
    props = {"shots": [{"id": "s", "source": "clip.mp4", "sourceInSeconds": 3.0, "startSeconds": 0.0,
                        "endSeconds": 5.0, "avoidRegions": [{"x": 0.1}]}],
             "audio": {"narration": "n.wav"}, "filmType": {"inputHash": "h"}}
    out = verification_props(props, "persian/v/black.mp4")
    assert out["shots"][0]["source"] == "persian/v/black.mp4"
    assert "sourceInSeconds" not in out["shots"][0]
    assert out["shots"][0]["avoidRegions"] == [{"x": 0.1}] and out["filmType"] == {"inputHash": "h"}
    assert out["audio"] == {} and props["shots"][0]["source"] == "clip.mp4"
