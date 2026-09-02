"""Tests for the frame-level Persian verification.

This module is a measuring instrument, so the tests are calibration checks: they build
frames whose correct answer is known by construction and confirm the instrument reports
it.

The most important test here is `test_bright_footage_does_not_defeat_detection`. The
naive brightness detector this module replaced passed every dark-footage case and failed
only over bright footage — so a test suite of dark frames would have certified the broken
version. Bright footage is the case that matters.
"""

from __future__ import annotations

import numpy as np
import pytest

from lib.persian_verify import (
    FORMAT_DIMENSIONS,
    PANEL_GUARANTEED_CONTRAST,
    PANEL_WIDTH_FRACTION,
    check_reading_order,
    find_watermark,
    ink_mask,
    measure_subtitle_text,
    subtitle_band,
    verify_frames,
)

#: The composition's actual colours, from `PERSIAN_PALETTE` in `tokens.ts`.
WHITE = (255, 255, 255)
HIGHLIGHT = (255, 234, 0)
VOID = (11, 11, 12)


def _frame(
    fmt: str = "vertical", scale: float = 1.0, background: tuple[int, int, int] = VOID
) -> np.ndarray:
    width, height = FORMAT_DIMENSIONS[fmt]
    frame = np.zeros((int(height * scale), int(width * scale), 3), dtype=int)
    frame[:, :] = background
    return frame


def _paint_line(
    frame: np.ndarray,
    *,
    fmt: str = "vertical",
    line_index: int = 0,
    width_fraction: float = 0.6,
    colour: tuple[int, int, int] = WHITE,
    thickness: int = 26,
) -> tuple[int, int]:
    """Paint a centred bar inside the subtitle band, standing in for a line of text.

    A bar rather than real glyphs: the module measures extent, line count, and
    contrast, none of which depend on glyph shape, and a bar's correct answer is exact.
    """
    height, frame_width, _ = frame.shape
    band_top, band_bottom = subtitle_band(frame_width, height, fmt)  # type: ignore[arg-type]

    # Stack lines upward from the band's bottom, as the real panel does.
    bottom = band_bottom - 30 - line_index * (thickness + 20)
    top = bottom - thickness

    span = int(frame_width * width_fraction)
    left = (frame_width - span) // 2
    frame[top:bottom, left : left + span] = colour
    return top, bottom


class TestSubtitleBand:
    def test_vertical_band_matches_the_tokens(self) -> None:
        """590px from the bottom, four lines of 52px at 1.4, plus 20px padding."""
        top, bottom = subtitle_band(1080, 1920, "vertical")
        assert bottom == 1920 - 590
        assert bottom - top == round(2 * 20 + 4 * 52 * 1.4)

    def test_landscape_band_matches_the_tokens(self) -> None:
        top, bottom = subtitle_band(1920, 1080, "landscape")
        assert bottom == 1080 - 110
        assert bottom - top == round(2 * 18 + 3 * 46 * 1.45)

    def test_band_scales_with_the_frame(self) -> None:
        """Proof renders use `--scale=0.5`; the band must scale with them.

        Without this the band computed for a 540px-wide frame would use full-size
        offsets, land below the frame, and report no text on a correct render.
        """
        full_top, full_bottom = subtitle_band(1080, 1920, "vertical")
        half_top, half_bottom = subtitle_band(540, 960, "vertical")
        assert half_bottom == pytest.approx(full_bottom / 2, abs=1)
        assert half_top == pytest.approx(full_top / 2, abs=1)

    def test_band_excludes_the_watermark_and_hook(self) -> None:
        """Both live far outside it, so neither can contaminate a text measurement."""
        top, bottom = subtitle_band(1080, 1920, "vertical")
        assert top > 1920 * 0.15 + 40, "the migrated watermark sits at 15%"
        assert top > 1920 * 0.18 + 80, "the hook sits at 18%"


class TestInkMask:
    def test_white_text_is_ink(self) -> None:
        frame = _frame()
        _paint_line(frame)
        assert ink_mask(frame).sum() > 0

    def test_the_highlight_yellow_is_ink(self) -> None:
        """`#FFEA00` fails a near-white test, so it needs its own branch."""
        frame = _frame()
        _paint_line(frame, colour=HIGHLIGHT)
        assert ink_mask(frame).sum() > 0

    def test_the_void_background_is_not_ink(self) -> None:
        assert ink_mask(_frame()).sum() == 0

    @pytest.mark.parametrize(
        "footage",
        [
            (200, 195, 190),  # bright warm wall
            (215, 220, 225),  # overcast sky
            (224, 224, 224),  # just below the threshold
            (180, 200, 220),  # bright blue
        ],
    )
    def test_bright_footage_is_not_ink(self, footage: tuple[int, int, int]) -> None:
        """The whole design rests on this.

        Bright footage must not register as text. The threshold is on the minimum
        channel at 225, which is brighter than footage reaches outside actual specular
        clipping.
        """
        frame = _frame(background=footage)
        assert ink_mask(frame).sum() == 0, (
            f"footage {footage} registered as text — every measurement over bright "
            "footage would report the whole frame as text"
        )

    def test_saturated_colour_is_not_ink_even_when_bright(self) -> None:
        """A bright saturated colour is footage, not the neutral subtitle white."""
        for colour in [(255, 40, 40), (40, 255, 40), (40, 40, 255), (255, 0, 255)]:
            frame = _frame(background=colour)
            assert ink_mask(frame).sum() == 0, f"{colour} registered as text"


class TestMeasureSubtitleText:
    def test_a_single_line_is_measured(self) -> None:
        frame = _frame()
        top, bottom = _paint_line(frame, width_fraction=0.6)
        measurement = measure_subtitle_text(frame)
        assert measurement.has_text
        assert measurement.line_count == 1
        assert measurement.glyph_rows == (top, bottom - 1)
        assert measurement.problems == []

    def test_two_lines_are_counted_as_two(self) -> None:
        frame = _frame()
        _paint_line(frame, line_index=0)
        _paint_line(frame, line_index=1, width_fraction=0.45)
        assert measure_subtitle_text(frame).line_count == 2

    def test_three_lines_are_counted_as_three(self) -> None:
        """The vertical cap before escalation."""
        frame = _frame()
        for index in range(3):
            _paint_line(frame, line_index=index, width_fraction=0.5)
        assert measure_subtitle_text(frame).line_count == 3

    def test_centred_text_reports_no_offset(self) -> None:
        frame = _frame()
        _paint_line(frame, width_fraction=0.6)
        assert abs(measure_subtitle_text(frame).centre_offset_px or 99) <= 1

    def test_off_centre_text_is_reported(self) -> None:
        """Detects a broken flex container, which no other check would catch."""
        frame = _frame()
        height, width, _ = frame.shape
        band_top, band_bottom = subtitle_band(width, height, "vertical")
        frame[band_bottom - 60 : band_bottom - 30, 100:400] = WHITE

        measurement = measure_subtitle_text(frame)
        assert measurement.problems
        assert any("centre" in problem for problem in measurement.problems)

    def test_text_inside_the_panel_envelope_passes(self) -> None:
        frame = _frame()
        _paint_line(frame, width_fraction=PANEL_WIDTH_FRACTION - 0.02)
        measurement = measure_subtitle_text(frame)
        assert measurement.inside_panel_envelope is True
        assert measurement.problems == []

    def test_text_past_the_panel_envelope_is_reported(self) -> None:
        """The signature of measuring against one font and painting with another."""
        frame = _frame()
        _paint_line(frame, width_fraction=0.97)
        measurement = measure_subtitle_text(frame)
        assert measurement.inside_panel_envelope is False
        assert any("envelope" in problem for problem in measurement.problems)

    def test_an_empty_band_reports_no_text_without_failing(self) -> None:
        """Sampling between cues is legitimate and must not read as a failure."""
        measurement = measure_subtitle_text(_frame())
        assert not measurement.has_text
        assert measurement.problems == []

    def test_bright_footage_does_not_defeat_detection(self) -> None:
        """The regression that motivated this module.

        A bright clip fills the frame; the panel darkens its own region; white text sits
        on the panel. The naive `max(axis=2) > 200` detector selects the footage here and
        reports text spanning the full frame width — a false envelope violation on a
        correct render.
        """
        frame = _frame(background=(205, 200, 195))
        height, width, _ = frame.shape
        band_top, band_bottom = subtitle_band(width, height, "vertical")

        # The panel: 45% of rgba(20,20,20) over the footage.
        margin = int(width * (1 - PANEL_WIDTH_FRACTION) / 2)
        panel = frame[band_top:band_bottom, margin : width - margin]
        frame[band_top:band_bottom, margin : width - margin] = (
            panel * 0.55 + np.array([20, 20, 20]) * 0.45
        ).astype(int)

        _paint_line(frame, width_fraction=0.6)

        measurement = measure_subtitle_text(frame)
        assert measurement.has_text, "text over bright footage was not detected at all"
        assert measurement.inside_panel_envelope is True, (
            "bright footage was measured as text — the extent expanded to the frame "
            "and produced a false envelope violation"
        )
        assert measurement.problems == []

    def test_contrast_is_measured_against_the_panel(self) -> None:
        """White on the frosted panel is very high contrast; the number should show it."""
        frame = _frame()
        _paint_line(frame)
        ratio = measure_subtitle_text(frame).contrast_ratio
        assert ratio is not None and ratio > 10

    def test_the_panel_guarantees_contrast_above_the_floor(self) -> None:
        """Even fully clipped white footage cannot breach the floor through the panel.

        This is the arithmetic the check relies on: 45% of rgba(20,20,20) over 255 is
        149, and white on 149 is 2.99:1. Verified against a rendered panel rather than
        asserted, so a change to `GLASS.backgroundColor` surfaces here.

        The footage is 250 rather than 255 so the panel's glyph gaps stay just under
        the column gate's ceiling — at literal 255 the panel composites to exactly the
        boundary, which is the gate's own edge case and not what this test is about.
        """
        frame = _frame(background=(250, 250, 250))
        height, width, _ = frame.shape
        band_top, band_bottom = subtitle_band(width, height, "vertical")
        margin = int(width * (1 - PANEL_WIDTH_FRACTION) / 2)

        panel = frame[band_top:band_bottom, margin : width - margin]
        frame[band_top:band_bottom, margin : width - margin] = (
            panel * 0.55 + np.array([20, 20, 20]) * 0.45
        ).astype(int)
        _paint_line(frame)

        measurement = measure_subtitle_text(frame)
        assert measurement.contrast_ratio is not None
        assert measurement.contrast_ratio >= 2.9, (
            "the worst case the panel can present should still clear the floor"
        )
        assert measurement.problems == []

    def test_a_missing_panel_is_reported_as_such(self) -> None:
        """White text directly on bright footage — the panel failed to render.

        The message must say the panel is missing rather than blaming the grade: with
        the panel present this reading is unreachable, so "grade too weak" would send
        the reader to the wrong fix.
        """
        frame = _frame(background=(215, 215, 215))
        _paint_line(frame)

        measurement = measure_subtitle_text(frame)
        assert measurement.contrast_ratio is not None
        assert measurement.contrast_ratio < PANEL_GUARANTEED_CONTRAST
        assert any("panel did not render" in problem for problem in measurement.problems)

    def test_landscape_frames_are_measured_with_landscape_geometry(self) -> None:
        frame = _frame("landscape")
        _paint_line(frame, fmt="landscape", width_fraction=0.6)
        measurement = measure_subtitle_text(frame, "landscape")
        assert measurement.has_text
        assert measurement.problems == []

    def test_the_wrong_format_finds_nothing(self) -> None:
        """Guards against passing the format through incorrectly.

        Landscape's band is nowhere near vertical's, so measuring a landscape frame as
        vertical must come back empty rather than quietly reporting plausible numbers.
        """
        frame = _frame("landscape")
        _paint_line(frame, fmt="landscape")
        assert not measure_subtitle_text(frame, "vertical").has_text

    def test_a_specular_highlight_is_not_counted_as_a_line(self) -> None:
        """A few clipped pixels on wet asphalt must not become a text row.

        The stray patch is deliberately placed high in the band, where a naive extent
        measurement would stretch the reported rows across the whole band and the line
        count to 2.
        """
        frame = _frame(background=(190, 190, 190))
        height, width, _ = frame.shape
        band_top, band_bottom = subtitle_band(width, height, "vertical")
        frame[band_top + 20 : band_top + 23, 300:305] = (255, 255, 255)
        _paint_line(frame, width_fraction=0.6)

        measurement = measure_subtitle_text(frame)
        assert measurement.line_count == 1
        assert measurement.glyph_rows is not None
        assert measurement.glyph_rows[0] > band_top + 30, (
            "the stray highlight was included in the text extent"
        )

    def test_a_stray_highlight_does_not_widen_the_measured_extent(self) -> None:
        """Stray ink outside the text rows must not trigger a false envelope violation."""
        frame = _frame(background=(190, 190, 190))
        height, width, _ = frame.shape
        band_top, band_bottom = subtitle_band(width, height, "vertical")
        margin = int(width * (1 - PANEL_WIDTH_FRACTION) / 2)

        # A real panel, so contrast is measured against the panel and not the clip.
        panel = frame[band_top:band_bottom, margin : width - margin]
        frame[band_top:band_bottom, margin : width - margin] = (
            panel * 0.55 + np.array([20, 20, 20]) * 0.45
        ).astype(int)

        # Stray ink inside the envelope but well above the text rows.
        frame[band_top + 10 : band_top + 13, margin + 20 : margin + 25] = (255, 255, 255)
        _paint_line(frame, width_fraction=0.6)

        measurement = measure_subtitle_text(frame)
        assert measurement.line_count == 1
        assert measurement.inside_panel_envelope is True
        assert measurement.problems == []

    def test_blown_out_footage_beside_the_panel_is_excluded(self) -> None:
        """Clipped white footage is byte-identical to white text.

        No colour test can separate them, so the column gate does it structurally: a
        column through the panel has glyph gaps below the panel's ceiling, and a column
        of clipped footage does not. Without this, a clip that blows out at the frame
        edge produces a false envelope violation.
        """
        frame = _frame(background=(40, 40, 40))
        height, width, _ = frame.shape
        band_top, band_bottom = subtitle_band(width, height, "vertical")
        margin = int(width * (1 - PANEL_WIDTH_FRACTION) / 2)

        panel = frame[band_top:band_bottom, margin : width - margin]
        frame[band_top:band_bottom, margin : width - margin] = (
            panel * 0.55 + np.array([20, 20, 20]) * 0.45
        ).astype(int)
        _paint_line(frame, width_fraction=0.6)

        # Fully clipped footage down both edges, outside the panel.
        edge = margin // 2
        frame[:, :edge] = (255, 255, 255)
        frame[:, width - edge :] = (255, 255, 255)

        measurement = measure_subtitle_text(frame)
        assert measurement.inside_panel_envelope is True, (
            "blown-out footage beside the panel was counted as text"
        )
        assert measurement.glyph_columns is not None
        assert measurement.glyph_columns[0] > edge
        assert measurement.problems == []


class TestReadingOrder:
    """Reading order is the only fault geometry cannot see, so this is the only check
    that can catch it — which makes a false pass here the most expensive kind."""

    def _highlighted(
        self, centre_fraction: float, *, line_index: int = 0
    ) -> np.ndarray:
        frame = _frame()
        height, width, _ = frame.shape
        _, band_bottom = subtitle_band(width, height, "vertical")
        centre = int(width * centre_fraction)
        bottom = band_bottom - 30 - line_index * 46
        frame[bottom - 30 : bottom, centre - 50 : centre + 50] = HIGHLIGHT
        return frame

    def test_an_early_word_on_the_right_is_correct_rtl(self) -> None:
        result = check_reading_order(
            self._highlighted(0.7), highlight_word_index=1, word_count=6
        )
        assert result["found"]
        assert result["rtl_order_correct"] is True

    def test_an_early_word_on_the_left_means_reversed_order(self) -> None:
        """The fault that must never ship, and that geometry alone cannot see."""
        result = check_reading_order(
            self._highlighted(0.3), highlight_word_index=1, word_count=6
        )
        assert result["rtl_order_correct"] is False
        assert result["expected_side"] == "right"
        assert result["actual_side"] == "left"

    def test_a_late_word_belongs_on_the_left(self) -> None:
        result = check_reading_order(
            self._highlighted(0.25), highlight_word_index=5, word_count=6
        )
        assert result["rtl_order_correct"] is True

    def test_a_missing_highlight_is_reported_with_its_cause(self) -> None:
        result = check_reading_order(_frame(), highlight_word_index=1, word_count=6)
        assert result["found"] is False
        assert "highlightPhrases" in result["reason"]

    def test_white_text_is_not_mistaken_for_the_highlight(self) -> None:
        frame = _frame()
        _paint_line(frame, colour=WHITE)
        assert (
            check_reading_order(frame, highlight_word_index=1, word_count=6)["found"]
            is False
        )

    def test_yellow_footage_outside_the_band_is_not_a_highlight(self) -> None:
        """A real false positive, not a hypothetical.

        A sunset frame in the 60-second proof render carried 37 pixels matching
        `#FFEA00` across rows 177-380 — entirely outside the subtitle band, and read as a
        highlight sitting left of centre. On a correctly-ordered cue that is a reported
        reading-order failure, which is the worst possible direction for this check to
        err in.
        """
        frame = _frame()
        height, width, _ = frame.shape
        band_top, _ = subtitle_band(width, height, "vertical")
        frame[band_top - 200 : band_top - 150, 40:120] = HIGHLIGHT

        result = check_reading_order(frame, highlight_word_index=1, word_count=6)
        assert result["found"] is False
        assert "footage, not text" in result["reason"]

    def test_a_multi_line_cue_is_refused(self) -> None:
        """Each line is centred on its own, so a global index means nothing.

        The first word of line 2 sits at the right end of line 2 while its index is
        halfway through the cue. Answering from that would flag correct renders.
        """
        frame = self._highlighted(0.7)
        _paint_line(frame, line_index=1, colour=WHITE)

        result = check_reading_order(frame, highlight_word_index=1, word_count=6)
        assert result["found"] is False
        assert result["line_count"] == 2
        assert "centred independently" in result["reason"]

    def test_a_middle_word_carries_no_signal(self) -> None:
        """It is near the centre under either direction, so it proves nothing."""
        result = check_reading_order(
            self._highlighted(0.5), highlight_word_index=3, word_count=7
        )
        assert result["found"] is False
        assert "near the middle" in result["reason"]

    def test_landscape_uses_the_landscape_band(self) -> None:
        """The bands do not overlap: 68% of height against 52%.

        Passing the wrong format looks for the highlight in rows the subtitle is not in.
        """
        frame = _frame("landscape")
        height, width, _ = frame.shape
        _, band_bottom = subtitle_band(width, height, "landscape")
        frame[band_bottom - 60 : band_bottom - 30, int(width * 0.7) : int(width * 0.7) + 100] = (
            HIGHLIGHT
        )

        assert check_reading_order(
            frame, highlight_word_index=1, word_count=6, fmt="landscape"
        )["found"]
        assert not check_reading_order(
            frame, highlight_word_index=1, word_count=6, fmt="vertical"
        )["found"]


class TestWatermark:
    """The watermark is found by differencing, not by appearance.

    It is white type at 0.6 opacity drawn straight onto the footage with no panel, so it
    composites to roughly `0.6·255 + 0.4·footage`. Every appearance-based discriminator
    was measured against real renders and lost to footage: a brightness threshold made
    35% of one search band "watermark"; local contrast produced a 5003-pixel false
    positive against the real mark's 792; row-gradient energy lost 26:1 to 21:1; and
    temporal invariance failed because H.264 re-quantizes the static mark every frame.

    So the tests below are built around the two supported modes: a diff against the same
    frame rendered with the mark removed, and an ink threshold that is valid only on a
    footage-free frame and refuses to run otherwise.
    """

    def _watermark_at(
        self,
        top_fraction: float,
        *,
        opacity: float = 0.6,
        background: tuple[int, int, int] = VOID,
        width_px: int = 400,
    ) -> tuple[np.ndarray, np.ndarray]:
        """A frame with the mark and the same frame without it.

        Returned as a pair because that is the module's primary input: a lone frame
        cannot be interrogated for the mark, which is the whole finding here.
        """
        without = _frame(background=background)
        with_mark = without.copy()
        height, width, _ = with_mark.shape
        row = int(height * top_fraction)

        # Composite white at `opacity` over whatever is behind it, the way the renderer
        # does — not a flat grey, so the value depends on the background as it really
        # does.
        left = width // 2 - width_px // 2
        region = with_mark[row - 7 : row + 7, left : left + width_px]
        with_mark[row - 7 : row + 7, left : left + width_px] = (
            region * (1 - opacity) + 255 * opacity
        ).astype(int)
        return with_mark, without

    def test_the_mark_is_found_by_differencing(self) -> None:
        with_mark, without = self._watermark_at(0.46)
        result = find_watermark(
            with_mark, expected_top_fraction=0.46, reference=without
        )
        assert result["found"] is True
        assert result["method"] == "difference"
        assert result["clipped_at_edge"] is False

    def test_differencing_works_over_bright_footage(self) -> None:
        """The case that defeats every appearance-based detector.

        Over footage at 205 the mark composites to about 235 — indistinguishable from
        the footage's own highlights by value, and trivially distinguishable by diff.
        """
        with_mark, without = self._watermark_at(0.46, background=(205, 200, 195))
        result = find_watermark(
            with_mark, expected_top_fraction=0.46, reference=without
        )
        assert result["found"] is True
        assert result["method"] == "difference"

    def test_the_measured_extent_is_the_marks_extent(self) -> None:
        """A diff on a lossless pair is exact, so the geometry can be trusted."""
        with_mark, without = self._watermark_at(0.15, width_px=300)
        result = find_watermark(
            with_mark, expected_top_fraction=0.15, reference=without
        )
        height, width, _ = with_mark.shape
        assert result["columns"][0] == pytest.approx(width // 2 - 150, abs=2)
        assert result["columns"][1] == pytest.approx(width // 2 + 150 - 1, abs=2)
        assert result["centre_x"] == pytest.approx(width / 2, abs=2)

    def test_an_absent_mark_is_reported_with_its_cause(self) -> None:
        """Both frames identical: the mark did not render."""
        frame = _frame()
        result = find_watermark(
            frame, expected_top_fraction=0.46, reference=frame.copy()
        )
        assert result["found"] is False
        assert "migration" in result["reason"]

    def test_a_clipped_mark_is_flagged(self) -> None:
        """Running off the frame means position and translate disagree.

        That bug only appears with long text, so it survives every short-text check.
        """
        without = _frame()
        with_mark = without.copy()
        height, width, _ = with_mark.shape
        row = int(height * 0.15)
        with_mark[row - 7 : row + 7, 0:300] = (153, 153, 153)

        result = find_watermark(
            with_mark, expected_top_fraction=0.15, reference=without
        )
        assert result["found"] is True
        assert result["clipped_at_edge"] is True

    def test_looking_in_the_wrong_place_finds_nothing(self) -> None:
        """The search is bounded, so a wrong expected position is a failure.

        This is what caught the landscape watermark sitting inside the subtitle band:
        the position it was found at was not the position it should have been at.
        """
        with_mark, without = self._watermark_at(0.75)
        result = find_watermark(
            with_mark, expected_top_fraction=0.15, reference=without
        )
        assert result["found"] is False

    def test_a_mismatched_reference_is_refused(self) -> None:
        """Two different scales would diff into noise everywhere."""
        with_mark, _ = self._watermark_at(0.46)
        with pytest.raises(ValueError, match="same composition and scale"):
            find_watermark(
                with_mark,
                expected_top_fraction=0.46,
                reference=with_mark[::2, ::2],
            )

    def test_the_ink_fallback_works_on_a_footage_free_frame(self) -> None:
        """Useful on its own: it checks the four phases without any footage."""
        with_mark, _ = self._watermark_at(0.46)
        result = find_watermark(with_mark, expected_top_fraction=0.46)
        assert result["found"] is True
        assert result["method"] == "ink"

    def test_the_ink_fallback_refuses_when_footage_is_present(self) -> None:
        """It would find the footage.

        Refusing and naming the needed input is the only honest option: a threshold
        that cannot separate the two must not pretend it did.
        """
        with_mark, _ = self._watermark_at(0.46, background=(120, 120, 120))
        result = find_watermark(with_mark, expected_top_fraction=0.46)
        assert result["found"] is False
        assert "reference" in result["reason"]

    def test_scattered_noise_is_not_a_watermark(self) -> None:
        """Codec noise in an MP4 diff must not read as the mark."""
        without = _frame()
        with_mark = without.copy()
        height, width, _ = with_mark.shape
        row = int(height * 0.46)
        rng = np.random.default_rng(7)
        for _ in range(60):
            y = rng.integers(row - 40, row + 40)
            x = rng.integers(0, width - 2)
            with_mark[y, x] = (200, 200, 200)

        result = find_watermark(
            with_mark, expected_top_fraction=0.46, reference=without
        )
        assert result["found"] is False

    def test_the_shadow_halo_is_excluded_from_the_extent(self) -> None:
        """The mark's own soft shadow must not inflate the measured height.

        This was a real miss. An absolute row floor alone let the halo through on the
        60-second render — 33 changed pixels per row against a floor of 10 — and the
        reported extent grew from 14 rows to 89. Since the halo scales with the mark, the
        fix is a floor relative to the strongest row, and this test pins it: a faint band
        four times the glyph height, at a fifth of the glyph rows' density.
        """
        without = _frame()
        with_mark = without.copy()
        height, width, _ = with_mark.shape
        row = int(height * 0.46)

        # Halo: wide, faint, and contiguous with the glyph rows.
        rng = np.random.default_rng(3)
        for y in range(row - 28, row + 28):
            columns = rng.choice(width, size=int(width * 0.03), replace=False)
            with_mark[y, columns] = (60, 60, 60)

        # Glyphs: a dense core.
        with_mark[row - 7 : row + 7, width // 2 - 200 : width // 2 + 200] = (153, 153, 153)

        result = find_watermark(
            with_mark, expected_top_fraction=0.46, reference=without
        )
        assert result["found"] is True
        measured = result["rows"][1] - result["rows"][0] + 1
        assert measured <= 18, f"halo inflated the extent to {measured} rows"


class TestVerifyFrames:
    def test_a_clean_set_passes(self) -> None:
        frames = []
        for index in range(3):
            frame = _frame()
            _paint_line(frame, width_fraction=0.5 + index * 0.1)
            frames.append((f"frame-{index}", frame))
        summary = verify_frames(frames)
        assert summary["passed"] is True
        assert len(summary["frames_with_text"]) == 3

    def test_one_bad_frame_fails_the_set_and_is_named(self) -> None:
        good = _frame()
        _paint_line(good, width_fraction=0.6)
        bad = _frame()
        _paint_line(bad, width_fraction=0.97)

        summary = verify_frames([("good", good), ("bad", bad)])
        assert summary["passed"] is False
        assert any(problem.startswith("bad:") for problem in summary["problems"])
        assert not any(problem.startswith("good:") for problem in summary["problems"])

    def test_a_set_with_no_text_anywhere_is_reported(self) -> None:
        """Either the sampling missed every cue or the font failed — both need saying."""
        summary = verify_frames([("a", _frame()), ("b", _frame())])
        assert summary["passed"] is False
        assert any("no sampled frame" in problem for problem in summary["problems"])

    def test_frames_between_cues_do_not_fail_a_set(self) -> None:
        frame = _frame()
        _paint_line(frame, width_fraction=0.6)
        summary = verify_frames([("with-text", frame), ("between-cues", _frame())])
        assert summary["passed"] is True
        assert summary["frames_with_text"] == ["with-text"]
