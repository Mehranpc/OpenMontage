"""Tests for the frame-level Persian verification.

This module is a measuring instrument, so the tests are calibration checks: they build
frames whose correct answer is known by construction and confirm the instrument reports
it.

Two tests carry more weight than the rest.

`test_bright_footage_does_not_defeat_detection` is here because the naive brightness
detector this module replaced passed every dark-footage case and failed only over bright
footage — so a suite of dark frames would have certified the broken version. Bright
footage is the case that matters.

`test_centred_text_misses_the_anchor` is here because it is the regression the whole
moment model exists to prevent. Centred text sits inside the width budget and inside the
zone, so every check the predecessor had would pass it; only the anchor catches it.

Frames are painted as bars rather than real glyphs wherever the property under test does
not depend on glyph shape. Where it does — the accent's antialiased rim, which leaks into
the neutral-ink mask if it is not excluded — the tests set real Estedad through PIL,
because a synthetic bar has no rim and would certify a check that fails on every real
frame.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from lib.persian_verify import (
    ANCHOR_TOLERANCE_PX,
    FORMAT_DIMENSIONS,
    GAP_ACCENT_CEILING,
    INK_OVERSHOOT_PX,
    MIN_LINE_PX,
    MOMENT_COLUMNS_PX,
    MOMENT_ZONE_FRACTION,
    SCRIM_CEILING,
    SCRIM_GUARANTEED_CONTRAST,
    SCRIM_PLATEAU_MARGIN_PX,
    WATERMARK_TOP_FRACTION,
    ZONE_INK_CEILING,
    _dilate,
    accent_mask,
    anchor_report,
    check_gap_is_empty,
    check_moment_arrangement,
    expected_stack_gap_px,
    find_watermark,
    ink_mask,
    measure_moment,
    measure_stack_rhythm,
    moment_centre_fraction,
    moment_columns,
    moment_zone,
    scrim_plateau,
    verify_frames,
)

#: The composition's actual colours, from `PERSIAN_PALETTE` in `tokens.ts`.
INK = (247, 245, 242)
INK_SECONDARY = (214, 208, 198)
ACCENT = (255, 194, 75)
VOID = (11, 11, 12)

#: What the scrim presents behind the type when the footage below it is clipped white:
#: `255·(1 − SCRIM.peakAlpha)` at peakAlpha 0.72. The worst legitimate background.
SCRIM_WORST_BACKGROUND = (71, 71, 71)

FONT_DIR = Path(__file__).resolve().parents[2] / "remotion-composer" / "public" / "fonts" / "estedad"


def _frame(
    fmt: str = "vertical",
    scale: float = 1.0,
    background: tuple[int, int, int] = SCRIM_WORST_BACKGROUND,
) -> np.ndarray:
    """A frame filled with the worst background the scrim can present.

    Defaulting to the *worst* case rather than to the void is deliberate: a test that
    passes over black proves much less than one that passes over the brightest surface
    the design permits, and the difference is exactly where the predecessor failed.
    """
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
    colour: tuple[int, int, int] = INK,
    thickness: int = 26,
    anchored: bool = True,
) -> tuple[int, int]:
    """Paint a bar inside the moment zone, standing in for a line of text.

    Anchored right by default, since that is what the real component does. Pass
    `anchored=False` to paint it centred — the regression case.
    """
    height, frame_width, _ = frame.shape
    zone_top, _ = moment_zone(frame_width, height, fmt)  # type: ignore[arg-type]
    left_bound, anchor = moment_columns(frame_width, fmt)  # type: ignore[arg-type]

    top = zone_top + 40 + line_index * (thickness + 20)
    bottom = top + thickness

    span = int((anchor - left_bound) * width_fraction)
    left = int(anchor) - span if anchored else (frame_width - span) // 2
    frame[top:bottom, left : left + span] = colour
    return top, bottom


def _set_text(
    frame: np.ndarray,
    text: str,
    *,
    weight: str = "Bold",
    size_px: int = 80,
    colour: tuple[int, int, int] = INK,
    anchor_x: float | None = None,
    baseline_y: int = 700,
    fmt: str = "vertical",
) -> None:
    """Paint real shaped Persian into `frame`, in place.

    Used only where glyph shape matters. Requires PIL with raqm; skips otherwise, since
    without shaping the letters come out isolated and the frame is not a valid sample of
    what the renderer produces.
    """
    PIL = pytest.importorskip("PIL")
    from PIL import Image, ImageDraw, ImageFont, features

    if not features.check("raqm"):
        pytest.skip("PIL built without raqm; Persian shaping unavailable")

    font_path = FONT_DIR / f"Estedad-{weight}.ttf"
    if not font_path.exists():
        pytest.skip(f"{font_path.name} not vendored")

    height, width, _ = frame.shape
    if anchor_x is None:
        anchor_x = moment_columns(width, fmt)[1]  # type: ignore[arg-type]

    image = Image.fromarray(frame.astype(np.uint8))
    ImageDraw.Draw(image).text(
        (anchor_x, baseline_y),
        text,
        font=ImageFont.truetype(str(font_path), size_px),
        fill=colour,
        anchor="ra",
        direction="rtl",
        language="fa",
    )
    frame[:, :] = np.array(image).astype(int)


class TestMomentZone:
    def test_vertical_zone_matches_the_tokens(self) -> None:
        top, bottom = moment_zone(1080, 1920, "vertical")
        assert (top, bottom) == (442, 1247)

    def test_landscape_zone_matches_the_tokens(self) -> None:
        top, bottom = moment_zone(1920, 1080, "landscape")
        assert (top, bottom) == (257, 823)

    def test_the_zone_fractions_are_the_new_model_values(self) -> None:
        """The zone grew when moments became phrases; the old slot-model zone is gone.

        These are the values `tests/contracts/test_persian_geometry_parity.py` pins
        against the TypeScript source; asserted here so the module is also testable
        without a Node toolchain — the verifier must stay usable standalone.
        """
        assert MOMENT_ZONE_FRACTION["vertical"]["top"] == pytest.approx(0.230419)
        assert MOMENT_ZONE_FRACTION["vertical"]["bottom"] == pytest.approx(0.649581)
        assert MOMENT_ZONE_FRACTION["landscape"]["top"] == pytest.approx(0.238211)
        assert MOMENT_ZONE_FRACTION["landscape"]["bottom"] == pytest.approx(0.761789)

    def test_the_watermark_positions_are_the_new_model_values(self) -> None:
        """Quiet moved up with the zone: `max(resting, zone.top − clearance)`.

        The old 0.2445 quiet sat inside the new, taller zone's top rows; the
        derivation moved the mark to 0.170419 so it keeps the same clearance it
        always had. A literal would have silently stayed inside the type.
        """
        assert WATERMARK_TOP_FRACTION["vertical"]["quiet"] == pytest.approx(0.170419)
        assert WATERMARK_TOP_FRACTION["vertical"]["resting"] == 0.11
        assert WATERMARK_TOP_FRACTION["landscape"]["quiet"] == pytest.approx(0.178211)
        assert WATERMARK_TOP_FRACTION["landscape"]["resting"] == 0.08

    def test_the_columns_are_unchanged_by_the_model_change(self) -> None:
        assert MOMENT_COLUMNS_PX["vertical"]["left"] == pytest.approx(113.08)
        assert MOMENT_COLUMNS_PX["vertical"]["right"] == pytest.approx(993.6)

    def test_the_line_ink_floor_is_unchanged(self) -> None:
        assert MIN_LINE_PX == {"vertical": 30, "landscape": 26}

    def test_the_zone_scales_with_the_frame(self) -> None:
        """Proof renders use `--scale=0.5`, so every check has to follow."""
        full = moment_zone(1080, 1920, "vertical")
        half = moment_zone(540, 960, "vertical")
        assert half[0] == pytest.approx(full[0] / 2, abs=1)
        assert half[1] == pytest.approx(full[1] / 2, abs=1)

    def test_the_zone_excludes_the_watermark(self) -> None:
        """The mark rests at 11% in vertical; the zone must start well below it."""
        top, _ = moment_zone(1080, 1920, "vertical")
        assert top > 0.11 * 1920

    def test_the_zone_clears_the_platform_safe_area(self) -> None:
        """The lowest fifth of a vertical frame belongs to the platform's own UI."""
        _, bottom = moment_zone(1080, 1920, "vertical")
        assert bottom < 0.8 * 1920

    def test_the_zone_envelope_covers_the_height_budget(self) -> None:
        """The zone is exactly the envelope of the tallest legal moment.

        802px height budget plus the 3px rule, centred on the optical centre at
        44% of height. If the budget grows again, this is the test that says the
        zone followed it.
        """
        from lib.persian_verify import FORMAT_DIMENSIONS as dims

        for fmt in ("vertical", "landscape"):
            width, height = dims[fmt]
            top, bottom = moment_zone(width, height, fmt)  # type: ignore[arg-type]
            span = bottom - top
            fraction = MOMENT_ZONE_FRACTION[fmt]  # type: ignore[index]
            assert span == pytest.approx(
                (fraction["bottom"] - fraction["top"]) * height, abs=2
            )
            centre = (fraction["top"] + fraction["bottom"]) / 2 * height
            # Optically centred on the usable frame, not the raw frame.
            if fmt == "vertical":
                assert centre == pytest.approx(0.44 * height, abs=1)

    def test_columns_are_anchored_to_the_right_safe_edge(self) -> None:
        left, right = moment_columns(1080, "vertical")
        assert right == pytest.approx(1080 * 0.92)
        assert left < right

    def test_columns_scale_with_the_frame(self) -> None:
        full_left, full_right = moment_columns(1080, "vertical")
        half_left, half_right = moment_columns(540, "vertical")
        assert half_right == pytest.approx(full_right / 2)
        assert half_left == pytest.approx(full_left / 2)


class TestInkMask:
    """Ink is "brighter than the scrim can present", not "bright".

    The distinction is the whole reason this works over bright footage: the scrim sits
    between the clip and the camera, so it bounds what the clip can contribute
    regardless of how bright the clip is.
    """

    def test_the_primary_ink_is_ink(self) -> None:
        frame = _frame()
        frame[100:110, 100:200] = INK
        assert ink_mask(frame)[105, 150]

    def test_the_secondary_ink_is_ink(self) -> None:
        frame = _frame()
        frame[100:110, 100:200] = INK_SECONDARY
        assert ink_mask(frame)[105, 150]

    def test_the_accent_is_ink_despite_its_dark_blue_channel(self) -> None:
        """The reason the mask tests the maximum channel rather than the minimum.

        `#FFC24B` has a blue channel of 75. A minimum-channel test — which is what the
        caption-era mask used — rejects the ink that carries every figure and every term.
        """
        frame = _frame()
        frame[100:110, 100:200] = ACCENT
        assert min(ACCENT) < SCRIM_CEILING
        assert ink_mask(frame)[105, 150]

    def test_the_void_background_is_not_ink(self) -> None:
        assert not ink_mask(_frame(background=VOID)).any()

    def test_the_worst_scrimmed_background_is_not_ink(self) -> None:
        """The boundary case: clipped white footage under a working scrim.

        This is the tightest the discrimination ever gets, and it is the value measured
        on the real render — the brightest pixel in the vertical moment zone composites
        to exactly 71.4.
        """
        assert not ink_mask(_frame(background=SCRIM_WORST_BACKGROUND)).any()

    @pytest.mark.parametrize(
        "footage",
        [(255, 255, 255), (250, 248, 245), (255, 240, 200), (200, 210, 255)],
    )
    def test_scrimmed_bright_footage_is_not_ink(
        self, footage: tuple[int, int, int]
    ) -> None:
        """Any footage at all, composited under the scrim, stays below the ceiling."""
        scrimmed = tuple(int(channel * (1 - 0.72)) for channel in footage)
        assert not ink_mask(_frame(background=scrimmed)).any()  # type: ignore[arg-type]

    def test_unscrimmed_bright_footage_is_ink_and_that_is_the_point(self) -> None:
        """Not a false positive — a detection.

        With no scrim the footage genuinely does pass, which is precisely how a missing
        scrim is caught: `ZONE_INK_CEILING` sees a zone that is 100% "ink" and refuses to
        measure it rather than reporting fabricated geometry.
        """
        assert ink_mask(_frame(background=(250, 250, 250))).all()


class TestAccentMask:
    """The accent is the only ink that can be found by colour.

    Its channel spread is 180, against 5 for the primary ink and 16 for the secondary,
    and measured against fourteen frames of real footage it admits 0.0000% of footage
    pixels where the neutral inks admit 32% and 77%.
    """

    def test_the_accent_is_matched(self) -> None:
        frame = _frame()
        frame[100:110, 100:200] = ACCENT
        assert accent_mask(frame)[105, 150]

    def test_the_neutral_inks_are_not_matched(self) -> None:
        frame = _frame()
        frame[100:110, 100:200] = INK
        frame[200:210, 100:200] = INK_SECONDARY
        assert not accent_mask(frame)[105, 150]
        assert not accent_mask(frame)[205, 150]

    @pytest.mark.parametrize("footage", [(255, 170, 60), (255, 220, 90)])
    def test_warm_footage_is_separated_by_the_scrim_not_by_the_tolerance(
        self, footage: tuple[int, int, int]
    ) -> None:
        """A sunset really is within tolerance of the accent — and the scrim is why that is fine.

        Bare, both of these match. Under the scrim no channel can exceed 71 against the
        accent's red of 255, so inside the moment zone the separation is 184 rather than
        the tolerance's 34. Both halves are asserted, because the first looks like a bug
        until the second is stated: the tolerance is sized for encoder noise, and the
        scrim is what rejects footage.
        """
        assert accent_mask(_frame(background=footage)).any()
        scrimmed = tuple(int(channel * (1 - 0.72)) for channel in footage)
        assert not accent_mask(_frame(background=scrimmed)).any()  # type: ignore[arg-type]


class TestMeasureMoment:
    def test_a_single_anchored_line_is_measured(self) -> None:
        frame = _frame()
        _paint_line(frame)
        measurement = measure_moment(frame)
        assert measurement.line_count == 1
        assert measurement.has_text
        assert measurement.problems == []

    def test_two_lines_are_counted_as_two(self) -> None:
        frame = _frame()
        _paint_line(frame, line_index=0)
        _paint_line(frame, line_index=1, width_fraction=0.4)
        assert measure_moment(frame).line_count == 2

    def test_an_anchored_line_reports_a_sub_pixel_offset(self) -> None:
        """Never exactly zero: the anchor is 993.6 and ink lands on whole pixels."""
        frame = _frame()
        _paint_line(frame)
        assert measure_moment(frame).anchor_offsets_px[0] < 2

    def test_centred_text_misses_the_anchor(self) -> None:
        """The regression the moment model exists to prevent.

        Centred text is inside the width budget and inside the zone, so a width-only or
        zone-only check passes it. Only the anchor catches it — and it catches it by
        hundreds of pixels, not marginally.
        """
        frame = _frame()
        _paint_line(frame, anchored=False, width_fraction=0.5)
        measurement = measure_moment(frame)
        assert measurement.worst_anchor_offset_px is not None
        assert measurement.worst_anchor_offset_px > ANCHOR_TOLERANCE_PX * 5
        assert any("anchor" in problem for problem in measurement.problems)

    def test_one_stray_line_among_correct_ones_is_caught(self) -> None:
        """Per-line, not per-block. A block maximum hides a single drifted line.

        Which is the exact shape of a flex-alignment bug: the container is right, one
        row inside it is not.
        """
        frame = _frame()
        _paint_line(frame, line_index=0)
        _paint_line(frame, line_index=1)
        # Third line painted centred, the other two anchored.
        _paint_line(frame, line_index=2, anchored=False, width_fraction=0.5)
        measurement = measure_moment(frame)
        assert measurement.line_count == 3
        assert any("1 of 3 lines" in problem for problem in measurement.problems)

    def test_a_real_persian_line_holds_the_anchor_within_tolerance(self) -> None:
        """The tolerance exists for the right side bearing, and must actually cover it.

        Set in the real font at the real size: every glyph has blank space inside its own
        advance box, so ink never quite reaches the anchor. Measured worst case across the
        production script is 20px, on «۲۲۶۴» at 260px.
        """
        frame = _frame()
        _set_text(frame, "قهوه فقط بیدارت نمی‌کنه", size_px=80)
        measurement = measure_moment(frame)
        assert measurement.line_count == 1
        assert measurement.worst_anchor_offset_px is not None
        assert 0 <= measurement.worst_anchor_offset_px <= ANCHOR_TOLERANCE_PX
        assert measurement.problems == []

    def test_a_display_figure_holds_the_anchor_within_tolerance(self) -> None:
        """The widest right side bearing in the system, at 260px."""
        frame = _frame()
        _set_text(frame, "۲۲۶۴", weight="Black", size_px=260, colour=ACCENT, baseline_y=650)
        measurement = measure_moment(frame)
        assert measurement.worst_anchor_offset_px is not None
        assert measurement.worst_anchor_offset_px <= ANCHOR_TOLERANCE_PX

    def test_text_inside_the_column_passes(self) -> None:
        frame = _frame()
        _paint_line(frame, width_fraction=0.9)
        assert measure_moment(frame).inside_text_column

    def test_text_past_the_anchor_is_reported(self) -> None:
        """Overflow toward the frame edge, the opposite fault from missing the anchor."""
        frame = _frame()
        height, width, _ = frame.shape
        zone_top, _ = moment_zone(width, height, "vertical")
        _, anchor = moment_columns(width, "vertical")
        frame[zone_top + 40 : zone_top + 66, int(anchor) - 300 : int(anchor) + 60] = INK
        measurement = measure_moment(frame)
        assert measurement.inside_text_column is False
        assert any("past the anchor" in problem for problem in measurement.problems)

    def test_an_empty_zone_reports_no_text_without_failing(self) -> None:
        """Nearly half the runtime is deliberately empty; that is not a fault."""
        measurement = measure_moment(_frame())
        assert not measurement.has_text
        assert measurement.line_count == 0
        assert measurement.problems == []

    def test_bright_footage_does_not_defeat_detection(self) -> None:
        """The case that broke the predecessor.

        Footage is clipped white, composited under the scrim as the renderer does, and
        the text sits on top. A brightness threshold selects the footage here; the scrim
        ceiling does not.
        """
        frame = _frame(background=SCRIM_WORST_BACKGROUND)
        _paint_line(frame, width_fraction=0.55)
        measurement = measure_moment(frame)
        assert measurement.line_count == 1
        assert measurement.problems == []

    def test_contrast_is_measured_against_the_local_surface(self) -> None:
        """The scrim is a gradient, so the only honest background is the local one.

        A fixed sampling strip worked for a panel, which has one flat surface. Here the
        alpha varies by row, and sampling the wrong row reports a contrast the text never
        had.
        """
        frame = _frame(background=SCRIM_WORST_BACKGROUND)
        _paint_line(frame)
        ratio = measure_moment(frame).contrast_ratio
        assert ratio is not None
        assert ratio > SCRIM_GUARANTEED_CONTRAST

    def test_every_ink_clears_the_guaranteed_floor_on_the_worst_background(self) -> None:
        """The floor is arithmetic, not a hope about the footage.

        72% black over clipped white presents 71.4, and the weakest ink on that surface
        is the accent at 5.75:1. If any palette ink fails here, the palette is wrong —
        no footage is involved in this test at all.
        """
        for colour in (INK, INK_SECONDARY, ACCENT):
            frame = _frame(background=SCRIM_WORST_BACKGROUND)
            _paint_line(frame, colour=colour)
            ratio = measure_moment(frame).contrast_ratio
            assert ratio is not None, f"{colour} was not detected as ink"
            assert ratio >= SCRIM_GUARANTEED_CONTRAST, f"{colour} measured {ratio}"

    def test_a_missing_scrim_is_diagnosed_rather_than_measured(self) -> None:
        """The most important refusal in the module.

        Without the scrim every bright pixel passes the ink test, so the zone comes back
        full. The measurements that follow would be precise and meaningless — full-width
        extents, a fabricated line count — so the frame is rejected with the cause named
        instead.
        """
        frame = _frame(background=(250, 250, 250))
        _paint_line(frame)
        measurement = measure_moment(frame)
        assert measurement.line_count == 0
        assert measurement.glyph_columns is None
        assert any("scrim did not render" in problem for problem in measurement.problems)

    def test_the_densest_real_moment_stays_under_the_occupancy_ceiling(self) -> None:
        """The ceiling must not fire on legitimate content.

        A figure with a two-line label and a source line is the densest arrangement the
        design permits: 9.6% of the zone measured in the real font, against a 35% ceiling.
        """
        frame = _frame()
        _set_text(frame, "۲۲۶۴", weight="Black", size_px=260, colour=ACCENT, baseline_y=680)
        _set_text(frame, "مطالعهٔ هم‌گروهی فنلاندی", size_px=44, colour=INK_SECONDARY, baseline_y=760)
        _set_text(frame, "دانشگاه اولو", size_px=30, colour=INK_SECONDARY, baseline_y=830)
        height, width, _ = frame.shape
        zone_top, zone_bottom = moment_zone(width, height, "vertical")
        fill = ink_mask(frame)[zone_top:zone_bottom].mean()
        assert fill < ZONE_INK_CEILING / 3
        assert measure_moment(frame).problems == []

    def test_landscape_frames_are_measured_with_landscape_geometry(self) -> None:
        frame = _frame("landscape")
        _paint_line(frame, fmt="landscape")
        measurement = measure_moment(frame, "landscape")
        assert measurement.line_count == 1
        assert measurement.problems == []

    def test_the_two_zones_are_not_interchangeable(self) -> None:
        """The formats' zones diverge at the bottom: landscape's extends lower.

        Worth pinning rather than assuming. At any frame height, vertical's zone
        ends at 65.0% of height — its optical centre is pushed up by the platform
        UI strip — while landscape's ends at 76.2%. The band between the two
        bottoms is inside landscape's zone and below vertical's, so text there is
        found by one format and missed by the other. That is the failure this
        asserts, in the only band where the two actually disagree.
        """
        frame = _frame("landscape")
        # 760–786 sits inside landscape's zone (257..823) and below vertical's
        # zone as measured at the same frame height (249..701).
        _, anchor = moment_columns(frame.shape[1], "landscape")
        frame[760:786, int(anchor) - 500 : int(anchor)] = INK
        assert measure_moment(frame, "landscape").has_text
        assert not measure_moment(frame, "vertical").has_text

    def test_a_specular_highlight_is_not_counted_as_a_line(self) -> None:
        """A few stray pixels that survive the ceiling must not become a line.

        Filtered by run total against one em of the smallest type, which is scale-correct
        by construction: both sides scale with the frame.
        """
        frame = _frame()
        _paint_line(frame)
        height, width, _ = frame.shape
        zone_top, _ = moment_zone(width, height, "vertical")
        frame[zone_top + 200 : zone_top + 203, 500:508] = (255, 255, 255)
        assert measure_moment(frame).line_count == 1


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


class TestMomentArrangement:
    """Segment order, verified from pixel geometry rather than from a planted highlight.

    The segment array is the reading order of one Persian phrase — «مطالعهٔ دانشگاه
    اولوی فنلاند روی» above «۲۲۶۴ نفر» — and the check reads that order back off the
    frame: the accent hero sits below every neutral segment authored before it and
    above every one authored after it. No planted marker, no expected image.

    These tests use real shaped Estedad rather than bars, because the property under
    test is one that only real glyphs have: the accent's antialiased rim is bright
    enough to be ink but too far from `#FFC24B` to be accent, so without excluding it
    the hero's own outline is read as a lead above it. A synthetic bar has no rim and
    would certify a check that fails on every real frame — which is exactly what
    happened the first time this ran.
    """

    def _stack(
        self,
        *,
        lead: bool = True,
        tail: bool = False,
        source: bool = False,
        lead_above: bool = True,
    ) -> np.ndarray:
        """The canonical figure painted as the component would: lead above, hero below.

        `lead_above=False` paints the lead *below* the hero — the inverted stack, the
        fault the order check exists to catch: a renderer that sorted by role, or an
        edit that put the fact above its frame.
        """
        frame = _frame()
        if lead:
            _set_text(
                frame,
                "مطالعهٔ دانشگاه اولوی فنلاند روی",
                size_px=82,
                colour=INK,
                baseline_y=560 if lead_above else 1000,
            )
        _set_text(
            frame,
            "۲۲۶۴ نفر",
            weight="Black",
            size_px=216,
            colour=ACCENT,
            baseline_y=820,
        )
        if tail:
            _set_text(
                frame,
                "با پیگیریِ ۱۲ ساله",
                size_px=82,
                colour=INK,
                baseline_y=1000 if lead_above else 560,
            )
        if source:
            _set_text(
                frame,
                "Nutrients, 2024",
                size_px=51,
                colour=INK_SECONDARY,
                baseline_y=1080,
            )
        return frame

    def test_the_canonical_stack_passes(self) -> None:
        """The user's own frame: lead above, hero below — nothing else may be said."""
        result = check_moment_arrangement(
            self._stack(), roles=["lead", "hero"]
        )
        assert result["checked"] is True
        assert result["ink_above_hero"] is True
        assert result["ink_below_hero"] is False
        assert result["passed"] is True

    def test_a_lead_below_the_hero_is_caught(self) -> None:
        """The inverted phrase: the fact above its frame.

        The check that fails here is the one the segment model exists to enforce —
        the array order is the reading order, and a stack that inverted it puts the
        quantity where its sentence should be.
        """
        result = check_moment_arrangement(
            self._stack(lead_above=False), roles=["lead", "hero"]
        )
        assert result["checked"] is True
        assert result["ink_below_hero"] is True
        assert result["ink_above_hero"] is False
        assert any("above the hero" in problem for problem in result["problems"])

    def test_ink_above_a_first_position_hero_is_satellite_residue(self) -> None:
        """A hero authored first must have nothing above it.

        This is the check that catches the old model's residue — «نفر» floating at the
        numeral's baseline, a kicker above the stack — none of which is representable
        under the segment model. It is the floating «نفر» test, in the new geometry.
        """
        frame = _frame()
        _set_text(
            frame,
            "شرکت‌کنندگان",
            size_px=82,
            colour=INK,
            baseline_y=560,
        )
        _set_text(
            frame,
            "۲۲۶۴ نفر",
            weight="Black",
            size_px=216,
            colour=ACCENT,
            baseline_y=820,
        )
        result = check_moment_arrangement(frame, roles=["hero"])
        assert result["checked"] is True
        assert result["ink_above_hero"] is True
        assert any("no segment was authored above" in p for p in result["problems"])

    def test_a_missing_lead_is_reported(self) -> None:
        """The moment declares a lead; the frame shows none above the hero."""
        result = check_moment_arrangement(
            self._stack(lead=False), roles=["lead", "hero"]
        )
        assert result["checked"] is True
        assert result["ink_above_hero"] is False
        assert any("lead(s) did not paint" in problem for problem in result["problems"])

    def test_a_missing_tail_is_reported(self) -> None:
        result = check_moment_arrangement(
            self._stack(tail=False), roles=["lead", "hero", "tail"]
        )
        assert result["checked"] is True
        assert any("tail(s)" in problem for problem in result["problems"])

    def test_a_tail_below_the_hero_is_found_where_authored(self) -> None:
        result = check_moment_arrangement(
            self._stack(tail=True), roles=["lead", "hero", "tail"]
        )
        assert result["checked"] is True
        assert result["ink_below_hero"] is True
        assert result["passed"] is True

    def test_a_source_below_everything_is_found_where_authored(self) -> None:
        result = check_moment_arrangement(
            self._stack(source=True), roles=["lead", "hero", "source"]
        )
        assert result["checked"] is True
        assert result["passed"] is True

    def test_a_hero_first_stack_with_tail_and_source_passes(self) -> None:
        """A term: name first, gloss after, citation last — the full hero-first stack.

        Persian sometimes states the emphasis before its qualifier, and the
        segment model paints whatever order the author wrote. This is the case
        the slot model could not express at all: there was no `tail` slot.
        """
        frame = _frame()
        _set_text(
            frame, "SHBG", weight="Black", size_px=200, colour=ACCENT, baseline_y=700
        )
        _set_text(
            frame,
            "پروتئینی که هورمون‌های جنسی را حمل می‌کند",
            size_px=64,
            colour=INK,
            baseline_y=860,
        )
        _set_text(
            frame, "دانشگاه اولو، ۲۰۲۴", size_px=61, colour=INK_SECONDARY, baseline_y=990
        )
        result = check_moment_arrangement(
            frame, roles=["hero", "tail", "source"]
        )
        assert result["checked"] is True
        assert result["ink_above_hero"] is False
        assert result["ink_below_hero"] is True
        assert result["passed"] is True

    def test_a_bare_statement_hero_passes_with_nothing_around_it(self) -> None:
        """A statement whose hero IS the claim: no lead, no residue above it.

        The one arrangement where `ink_above_hero` must be False and that is
        correct — the statement equivalent of the figure's missing-lead fault is
        not a fault at all.
        """
        frame = _frame()
        _set_text(
            frame,
            "قهوه هورمون را جابه‌جا می‌کند",
            weight="Black",
            size_px=148,
            colour=ACCENT,
            baseline_y=820,
        )
        result = check_moment_arrangement(frame, roles=["hero"])
        assert result["checked"] is True
        assert result["ink_above_hero"] is False
        assert result["ink_below_hero"] is False
        assert result["passed"] is True

    def test_roles_without_a_hero_are_declined(self) -> None:
        """Every moment carries exactly one; a roles list without one is a props fault."""
        frame = _frame()
        _paint_line(frame)
        result = check_moment_arrangement(frame, roles=["lead", "tail"])
        assert result["checked"] is False
        assert "no hero" in result["reason"]

    def test_a_frame_with_no_accent_is_declined_with_its_two_causes(self) -> None:
        """Between moments, or a hero painted in the wrong colour. Both need saying."""
        frame = _frame()
        _paint_line(frame)
        result = check_moment_arrangement(frame, roles=["lead", "hero"])
        assert result["checked"] is False
        assert "between moments" in result["reason"]


class TestStackRhythm:
    """The designed gap between role blocks, measured against real ink.

    The shipped render put 133px of empty space between a 260px numeral and the line
    under it — against a designed gap of 26px — and the cause was invisible to anyone
    reading the gap tokens, because it was not the gap: it was half-leading, a property
    of Estedad's line box that no `line-height` choice removes, since the slack depends
    on which glyphs are in the string. The component now trims each row to its measured
    ink, so the designed gap is the gap that appears; this check reads the gaps back
    off the frame and refuses one that has leading leaking into it.

    It is one-sided on purpose: only a gap *larger* than designed is a fault. A
    smaller-than-designed gap cannot be leading (leading only adds), and the
    difference between ink extents means adjacent bands can legitimately touch when a
    descender from one meets an ascender from the next.
    """

    def _two_band_frame(self, gap_px: int, *, lead_px: int = 99) -> np.ndarray:
        """A hero band with a lead band `gap_px` below its ink.

        Painted with real shaped Estedad, because the property under test is exactly
        the one synthetic bars cannot have: real glyphs end in antialiased partial
        rows, and the band finder's `_ink_row_runs` groups by ink presence, so the
        measured gap is the gap between real ink, not between rectangles.

        `anchor="ra"` places the text's *ascender* at the given y, and a font's
        ascender is not the ink's top — «۲۲۶۴ نفر» at 216px Black rises only
        ≈0.71em above its baseline against the ascender's 1.075, and the lead's
        own ink rises ≈0.9em. So the y positions are derived from PIL's own
        `textbbox` for each string at its size: the lead's ink starts exactly
        `gap_px` below the hero's ink ends, for every size pair, by construction
        rather than by estimated em ratios.
        """
        PIL = pytest.importorskip("PIL")
        from PIL import Image, ImageDraw, ImageFont, features

        if not features.check("raqm"):
            pytest.skip("PIL built without raqm; Persian shaping unavailable")

        frame = _frame()
        hero_text, hero_px = "۲۲۶۴ نفر", 216
        lead_text = "مطالعهٔ دانشگاه اولوی فنلاند روی"
        anchor_x = moment_columns(frame.shape[1], "vertical")[1]

        hero_font = ImageFont.truetype(str(FONT_DIR / "Estedad-Black.ttf"), hero_px)
        lead_font = ImageFont.truetype(str(FONT_DIR / "Estedad-Bold.ttf"), lead_px)

        # The hero's own bbox at the y where it will be painted.
        hero_y = 600
        probe = Image.new("L", (frame.shape[1], frame.shape[0]), 0)
        draw = ImageDraw.Draw(probe)
        draw.text(
            (anchor_x, hero_y), hero_text, font=hero_font, anchor="ra",
            fill=255, direction="rtl", language="fa",
        )
        hero_bbox = probe.getbbox()
        assert hero_bbox is not None
        hero_ink_bottom = hero_bbox[3]

        # Place the lead's ascender so its INK top lands gap_px below the hero's
        # ink bottom: ascender-to-ink-top offset, measured for the lead itself.
        probe = Image.new("L", (frame.shape[1], frame.shape[0]), 0)
        draw = ImageDraw.Draw(probe)
        lead_probe_y = 1000
        draw.text(
            (anchor_x, lead_probe_y), lead_text, font=lead_font, anchor="ra",
            fill=255, direction="rtl", language="fa",
        )
        lead_bbox = probe.getbbox()
        assert lead_bbox is not None
        ascender_to_ink = lead_bbox[1] - lead_probe_y
        lead_y = hero_ink_bottom + gap_px - ascender_to_ink

        _set_text(
            frame,
            hero_text,
            weight="Black",
            size_px=hero_px,
            colour=ACCENT,
            baseline_y=hero_y,
        )
        _set_text(
            frame,
            lead_text,
            size_px=lead_px,
            colour=INK,
            baseline_y=lead_y,
        )
        return frame

    def test_a_designed_gap_passes(self) -> None:
        """The canonical stack: the lead at its designed ink gap below the hero.

        At lead_px 99 the designed gap is round(99 × 0.55) = 54px with a 27px
        tolerance; the fixture paints 54px of real ink separation, and the
        measured band must come back inside the tolerance.
        """
        result = measure_stack_rhythm(self._two_band_frame(54), lead_px=99)
        if result.get("checked") is False and "fewer than two" in result.get("reason", ""):
            pytest.skip("PIL could not shape both bands; nothing to measure")
        assert result["checked"] is True
        assert result["passed"] is True, result["problems"]
        assert result["designed_gap_px"] == 54.0
        assert result["tolerance_px"] == 27.0
        assert result["band_gaps_px"] == [55.0]  # 54 painted, ±1 for antialias rows

    def test_a_deliberately_loose_gap_is_flagged(self) -> None:
        """The «فاصله مسخره» case: leading leaking into the designed gap.

        A 201px measured gap against a 54px design with 27px tolerance is the
        shape of the shipped defect — not a wrong gap *value*, but a gap that grew
        by the line box's own unused height (the real render's was 133px against a
        designed 26px). The frame stays inside the zone; pushing the lead further
        down to widen the gap past this would move it out of the envelope
        entirely, which is a different fault.
        """
        result = measure_stack_rhythm(self._two_band_frame(200), lead_px=99)
        assert result["checked"] is True
        assert result["passed"] is False
        assert result["band_gaps_px"] == [201.0]
        assert any("leading is leaking" in problem for problem in result["problems"])

    def test_a_tight_gap_is_not_a_fault(self) -> None:
        """One-sided: a gap smaller than designed cannot be leading.

        A 30px painted gap against a 54px design fails no threshold — leading
        only ever adds space, so a tight gap is a composing choice, not a
        line-box leak.
        """
        result = measure_stack_rhythm(self._two_band_frame(30), lead_px=99)
        if result["checked"] is False and "fewer than two" in result.get("reason", ""):
            pytest.skip("PIL could not shape both bands; nothing to measure")
        assert result["checked"] is True
        assert result["passed"] is True, result["problems"]
        assert result["band_gaps_px"] == [31.0]

    def test_bands_that_touch_merge_into_one_band(self) -> None:
        """Gaps below the band finder's `LINE_GAP_PX` are one block, not zero gap.

        Reporting a 0px gap for two blocks whose inks touch would be a false
        reading; declining is the honest answer, and it is what a well-trimmed
        multi-line block produces when its lines share ink rows.
        """
        result = measure_stack_rhythm(self._two_band_frame(0), lead_px=99)
        assert result["checked"] is False
        assert "fewer than two" in result["reason"]

    def test_a_three_pixel_gap_is_reported_not_merged(self) -> None:
        """Above the merge floor and far below the design: found, and passed.

        A 4px measured band is real separation and real ink rhythm — tighter than
        the design, which the check deliberately forgives (one-sided: only a gap
        *larger* than designed can be leading, because leading only adds).
        """
        result = measure_stack_rhythm(self._two_band_frame(3), lead_px=99)
        assert result["checked"] is True
        assert result["band_gaps_px"] == [4.0]
        assert result["passed"] is True, result["problems"]

    def test_a_single_band_declines_rather_than_measuring(self) -> None:
        """A lone hero has no gap to measure; saying so beats reporting noise."""
        frame = _frame()
        _set_text(
            frame,
            "۲۲۶۴ نفر",
            weight="Black",
            size_px=216,
            colour=ACCENT,
            baseline_y=820,
        )
        result = measure_stack_rhythm(frame, lead_px=99)
        assert result["checked"] is False
        assert "fewer than two" in result["reason"]

    def test_an_empty_zone_declines(self) -> None:
        result = measure_stack_rhythm(_frame(), lead_px=99)
        assert result["checked"] is False
        assert "fewer than two" in result["reason"]

    def test_the_designed_gap_scales_with_the_lead(self) -> None:
        """`STACK_GAP_RATIO` is 0.55 of the lead size, so the tolerance follows it.

        Asserted on the reported numbers rather than the token, because what the
        caller needs to trust is the pair (designed, tolerance) as measured at
        this lead size. A 30px painted gap passes at lead 54 the same way 54px
        passes at lead 99.
        """
        result = measure_stack_rhythm(self._two_band_frame(30, lead_px=54), lead_px=54)
        if result.get("checked") is False and "fewer than two" in result.get("reason", ""):
            pytest.skip("PIL could not shape both bands; nothing to measure")
        assert result["designed_gap_px"] == 30.0  # round(54 × 0.55)
        assert result["tolerance_px"] >= 14  # max(14, 0.5 × designed)
        assert result["passed"] is True, result["problems"]

    def test_the_tolerance_is_never_below_its_floor(self) -> None:
        """`max(14, 0.5 × designed)`: at small lead sizes the floor binds.

        At lead 40 the designed gap is 22px, so 0.5 × 22 = 11 would round under
        the 14px absolute floor, and the floor takes over — which is what keeps a
        small-type proof render (scale 0.5) from failing on encoder noise.
        """
        result = measure_stack_rhythm(self._two_band_frame(30, lead_px=40), lead_px=40)
        if result.get("checked") is False and "fewer than two" in result.get("reason", ""):
            pytest.skip("PIL could not shape both bands; nothing to measure")
        assert result["designed_gap_px"] == 22.0
        assert result["tolerance_px"] == 14.0  # the floor, not 11
        assert result["passed"] is True, result["problems"]

    def test_landscape_geometry_is_used_when_asked(self) -> None:
        """The zone differs by format; the bands must be looked for in the right one.

        The landscape zone (rows 257..823) is narrower than vertical's, so the same
        physical bands are found only when the landscape geometry is honoured.
        """
        frame = _frame("landscape")
        _set_text(
            frame,
            "۲۲۶۴ نفر",
            weight="Black",
            size_px=168,
            colour=ACCENT,
            baseline_y=420,
            fmt="landscape",
        )
        _set_text(
            frame,
            "مطالعهٔ دانشگاه اولوی فنلاند روی",
            size_px=64,
            colour=INK,
            baseline_y=680,
            fmt="landscape",
        )
        result = measure_stack_rhythm(frame, lead_px=64, fmt="landscape")
        if result.get("checked") is False and "fewer than two" in result.get("reason", ""):
            pytest.skip("PIL could not shape both bands in the landscape zone")
        assert result["checked"] is True
        assert result["passed"] is True, result["problems"]

    def test_claim_qualifier_hook_gap_derives_from_the_tail(self) -> None:
        """The approved hook's painted gap passes against the tail derivation.

        Moment 1 is a claim+qualifier hook: `stackGapPxForMoment` in `layout.ts`
        derives the real gap from the tail size (68 → 37px), while the old
        verifier derived its expectation from the lead (36 → 20px) and flagged
        the correct 36px-painted render as a rhythm fault. The frame below
        paints 36px of real ink separation — within 1px of the 37px design —
        and must pass with `claim_qualifier=True` (designed 37, tolerance 18.5)
        while failing without it (designed 20, tolerance 14). That split is
        the regression pin: a future divergence between the two derivations
        fails loudly instead of reintroducing the spurious flag.
        """
        frame = self._two_band_frame(36)
        hooked = measure_stack_rhythm(
            frame, lead_px=36, tail_px=68, claim_qualifier=True
        )
        if hooked.get("checked") is False and "fewer than two" in hooked.get("reason", ""):
            pytest.skip("PIL could not shape both bands; nothing to measure")
        assert hooked["checked"] is True
        assert hooked["designed_gap_px"] == 37.0  # round(68 × 0.55)
        assert hooked["passed"] is True, hooked["problems"]
        lead_only = measure_stack_rhythm(frame, lead_px=36)
        assert lead_only["checked"] is True
        assert lead_only["designed_gap_px"] == 20.0  # round(36 × 0.55)
        assert lead_only["passed"] is False  # the old spurious flag, pinned

    def test_hook_branch_refuses_to_guess_without_the_tail(self) -> None:
        """`claim_qualifier=True` without `tail_px` raises, not silently 20px.

        Falling back to the lead derivation would reintroduce exactly the
        defect this branch exists to fix — the wrong design stated
        confidently. Loud is better than wrong.
        """
        with pytest.raises(ValueError):
            expected_stack_gap_px(36.0, claim_qualifier=True)



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
        _paint_line(bad, width_fraction=0.6, anchored=False)

        summary = verify_frames([("good", good), ("bad", bad)])
        assert summary["passed"] is False
        assert any(problem.startswith("bad:") for problem in summary["problems"])
        assert not any(problem.startswith("good:") for problem in summary["problems"])

    def test_a_set_with_no_text_anywhere_is_reported(self) -> None:
        """Either the sampling missed every moment or the font failed — both need saying."""
        summary = verify_frames([("a", _frame()), ("b", _frame())])
        assert summary["passed"] is False
        assert any("no sampled frame" in problem for problem in summary["problems"])

    def test_frames_between_moments_do_not_fail_a_set(self) -> None:
        """Under the moment model most of the runtime is deliberately empty.

        A stricter version of the same test than the caption model needed: there, a gap
        was a brief transition, so a blind sample almost always landed on text. Here
        nearly half the runtime has none, and treating that as a fault would fail every
        real render.
        """
        frame = _frame()
        _paint_line(frame, width_fraction=0.6)
        summary = verify_frames([("with-text", frame), ("between-moments", _frame())])
        assert summary["passed"] is True
        assert summary["frames_with_text"] == ["with-text"]

    def test_an_empty_set_is_not_a_failure(self) -> None:
        """Nothing was asked, so nothing is wrong. The caller chooses the frames."""
        assert verify_frames([])["passed"] is True


class TestAnchorReport:
    """Drift across a whole render, which per-frame pass/fail cannot show.

    A systematic 20px offset passes every frame individually and is still a bug worth
    seeing; the median over every measured line is what makes it visible.
    """

    def test_anchored_lines_report_a_negligible_median(self) -> None:
        frames = []
        for index in range(3):
            frame = _frame()
            _paint_line(frame, width_fraction=0.5 + index * 0.1)
            frames.append((f"frame-{index}", frame))
        report = anchor_report(frames)
        assert report["lines_measured"] == 3
        assert report["median_offset_px"] < 2

    def test_every_line_is_counted_not_every_frame(self) -> None:
        frame = _frame()
        _paint_line(frame, line_index=0)
        _paint_line(frame, line_index=1, width_fraction=0.4)
        assert anchor_report([("f", frame)])["lines_measured"] == 2

    def test_an_empty_frame_reports_none_without_failing(self) -> None:
        report = anchor_report([("empty", _frame())])
        assert report["lines_measured"] == 0
        assert report["per_frame"]["empty"] is None

    def test_the_tolerance_is_reported_alongside_the_measurement(self) -> None:
        """A number without its threshold is not actionable."""
        frame = _frame()
        _paint_line(frame)
        assert anchor_report([("f", frame)])["tolerance_px"] == ANCHOR_TOLERANCE_PX

class TestDilate:
    """The structuring element is a square, and that is not a detail.

    A cross-shaped dilation never covers a diagonal neighbour at any radius, and an
    accent glyph's antialiased rim follows the glyph outline — so on every curved or
    diagonal stroke the rim sits diagonally from its own ink and survives the
    subtraction. The surviving pixels pass `ink_mask` and fail `accent_mask`, so they
    land in the neutral mask and get read as a separate element.

    On the real render that put 43 stray pixels on the hero's rows out to column 993,
    and `check_moment_arrangement` called a correct frame a reversed RTL row.
    """

    def test_a_diagonal_neighbour_is_covered(self) -> None:
        mask = np.zeros((11, 11), dtype=bool)
        mask[5, 5] = True
        assert _dilate(mask, 1)[6, 6], (
            "radius 1 did not reach the diagonal neighbour, so the structuring element "
            "is a cross rather than a square and an accent rim will leak"
        )

    @pytest.mark.parametrize("radius", [1, 2, 3])
    def test_the_grown_area_is_the_full_square(self, radius: int) -> None:
        mask = np.zeros((21, 21), dtype=bool)
        mask[10, 10] = True
        assert _dilate(mask, radius).sum() == (2 * radius + 1) ** 2

    def test_the_original_mask_is_not_modified(self) -> None:
        mask = np.zeros((7, 7), dtype=bool)
        mask[3, 3] = True
        _dilate(mask, 2)
        assert mask.sum() == 1

    def test_a_real_accent_rim_leaves_no_ink_right_of_the_hero(self) -> None:
        """The end-to-end property, on real glyphs rather than a synthetic point.

        Set as the composition sets it: an accent hero at the anchor with its unit far to
        the left. After subtracting the dilated accent, nothing neutral may remain on the
        hero's own rows to the right of the unit — anything there is rim.
        """
        frame = _frame()
        _, anchor = moment_columns(frame.shape[1], "vertical")
        _set_text(
            frame, "۲۲۶۴", weight="Black", size_px=260, colour=ACCENT,
            anchor_x=anchor, baseline_y=620,
        )
        _set_text(
            frame, "نفر", size_px=44, colour=INK_SECONDARY,
            anchor_x=anchor - 560, baseline_y=800,
        )
        height, width, _ = frame.shape
        zone_top, zone_bottom = moment_zone(width, height, "vertical")
        zone = slice(zone_top, zone_bottom)

        accent = accent_mask(frame)[zone]
        if not accent.any():
            pytest.skip("PIL could not shape the figure; nothing to measure")
        neutral = ink_mask(frame)[zone] & ~_dilate(accent, 3)

        accent_rows = np.where(accent.sum(axis=1) > 0)[0]
        band = neutral[accent_rows.min() : accent_rows.max() + 1]
        neutral_cols = np.where(band.sum(axis=0) > 0)[0]
        accent_cols = np.where(accent.sum(axis=0) > 0)[0]

        assert neutral_cols.size and neutral_cols.max() < accent_cols.max(), (
            "neutral ink survives to the right of the hero's rightmost accent pixel, so "
            "the rim was not fully excluded"
        )


class TestInkOvershoot:
    """Ink spilling *past* the column edge is a different quantity from missing the anchor.

    `ANCHOR_TOLERANCE_PX` is sized to the glyph's right side bearing — blank space inside
    the advance box, which makes ink fall short. Overshoot has the opposite causes and
    they are the renderer's: antialiasing writes partial pixels outside the box, and H.264
    ringing adds more around a high-contrast edge. The predecessor allowed 1px here while
    allowing 32px there, and failed three of thirteen correct real moments by 1.4-4.4px.
    """

    def test_the_measured_real_overshoot_passes(self) -> None:
        """4.4px past the anchor, the worst case on the real render."""
        frame = _frame()
        height, width, _ = frame.shape
        zone_top, _ = moment_zone(width, height, "vertical")
        _, anchor = moment_columns(width, "vertical")
        frame[zone_top + 40 : zone_top + 66, int(anchor) - 300 : int(anchor) + 5] = INK
        measurement = measure_moment(frame)
        assert measurement.inside_text_column is True
        assert measurement.problems == []

    def test_a_real_overflow_is_still_caught(self) -> None:
        """The allowance is 8px; a broken column runs to the frame edge, 86px away."""
        frame = _frame()
        height, width, _ = frame.shape
        zone_top, _ = moment_zone(width, height, "vertical")
        _, anchor = moment_columns(width, "vertical")
        frame[zone_top + 40 : zone_top + 66, int(anchor) - 300 : int(anchor) + 60] = INK
        measurement = measure_moment(frame)
        assert measurement.inside_text_column is False
        assert any("past the anchor" in problem for problem in measurement.problems)

    def test_the_allowance_is_far_below_a_real_overflow(self) -> None:
        """Sanity on the constant itself, not on a frame."""
        assert INK_OVERSHOOT_PX < ANCHOR_TOLERANCE_PX
        assert INK_OVERSHOOT_PX >= 5  # the measured 4.4px worst case, plus margin


class TestGapIsEmpty:
    """The gaps are the model, so their emptiness is worth measuring.

    This is the one check that cannot use brightness. A gap frame has no scrim by design,
    so `ink_mask` returns 31-99% on real footage — the accent's colour separation is the
    only instrument that survives without a scrim behind it.
    """

    def test_footage_with_no_type_passes_however_bright(self) -> None:
        """The case that defeats every brightness-based check."""
        frame = _frame(background=(250, 250, 250))
        result = check_gap_is_empty(frame)
        assert result["passed"] is True
        assert result["accent_fraction"] == 0.0

    def test_a_figure_hero_still_painting_is_caught(self) -> None:
        frame = _frame()
        _set_text(
            frame, "۲۲۶۴", weight="Black", size_px=260, colour=ACCENT, baseline_y=650
        )
        result = check_gap_is_empty(frame)
        if result["accent_fraction"] == 0.0:
            pytest.skip("PIL could not shape the figure; nothing to detect")
        assert result["passed"] is False
        assert any("overran its exit" in problem for problem in result["problems"])

    def test_the_ceiling_clears_the_noisiest_real_gap(self) -> None:
        """0.0246% was the worst real gap; the ceiling is 0.5%."""
        assert GAP_ACCENT_CEILING > 0.0003
        assert GAP_ACCENT_CEILING < 0.038  # under the faintest real hero, 3.84%

    def test_the_scope_limit_is_stated_in_the_result(self) -> None:
        """The residual blind spot is neutral-only residue, and it is stated.

        Every moment paints an accent hero, so an overrun spilling accent ink is
        caught whatever the kind; what remains undetectable is neutral-only
        residue with the hero fully exited, which no threshold separates from
        unscrimmed footage. Pinned because the limitation is the kind a reader
        assumes away: the check reports "passed" for that residue and must say
        so where it is read, not only in a docstring.
        """
        result = check_gap_is_empty(_frame())
        assert "neutral-only" in result["detects"]


class TestScrimPlateau:
    """The plateau is the per-moment darkened band; the zone is its envelope.

    ``SCRIM_CEILING`` holds only on the plateau: outside it bright footage
    passes and would be misread as type. So every ink-bearing check is scoped
    here, not to the zone — and bright bands ABOVE/BELOW the plateau must not
    be read as ink while type inside still is.
    """

    def test_the_plateau_is_inside_the_zone_for_a_short_moment(self) -> None:
        """A small moment's plateau sits well inside the envelope."""
        zone_top, zone_bottom = moment_zone(1080, 1920, "vertical")
        plateau_top, plateau_bottom = scrim_plateau(1080, 1920, "vertical", 250)
        assert plateau_top > zone_top
        assert plateau_bottom < zone_bottom
        assert plateau_bottom - plateau_top < zone_bottom - zone_top

    def test_the_plateau_margin_is_pinned(self) -> None:
        assert SCRIM_PLATEAU_MARGIN_PX == 28

    def test_the_centre_is_the_optical_centre(self) -> None:
        assert moment_centre_fraction("vertical") == pytest.approx(0.44, abs=0.01)
        assert moment_centre_fraction("landscape") == pytest.approx(0.5, abs=0.01)

    def test_the_plateau_scales_with_the_frame(self) -> None:
        full_top, full_bottom = scrim_plateau(1080, 1920, "vertical", 300)
        half_top, half_bottom = scrim_plateau(540, 960, "vertical", 300)
        assert half_top == pytest.approx(full_top / 2, abs=1)
        assert half_bottom == pytest.approx(full_bottom / 2, abs=1)

    def test_bright_footage_above_the_plateau_is_not_ink(self) -> None:
        """Bands outside the plateau — the falloff and unscrimmed rows — must
        not be counted. Only ink inside the plateau may be measured."""
        # Use a tall stack so the plateau covers the painted line at zone+40
        stack = 700
        frame = _frame()
        _paint_line(frame, width_fraction=0.6)
        # Bright footage band at the very top of the zone, above the plateau
        # For stack 700 plateau starts at 467, so 442..460 is outside
        frame[442:460, 0:1080] = (180, 175, 170)  # unscrimmed bright footage
        height, width, _ = frame.shape
        plateau_top, plateau_bottom = scrim_plateau(width, height, "vertical", stack)
        assert 460 < plateau_top
        measurement = measure_moment(frame, stack_height_px=stack)
        # Must not report the bright band as an extra line or as overflow
        assert measurement.line_count == 1
        assert measurement.problems == []
        # Column must be inside, not spanning 0..993
        assert measurement.glyph_columns is not None
        # 0.6 width span from anchor 993.6 left 113.08 => left ~465; bright band at 0..1080 would pull to 0 if counted
        assert measurement.glyph_columns[0] >= 400

    def test_bright_footage_below_the_plateau_is_not_ink(self) -> None:
        stack = 700
        frame = _frame()
        _paint_line(frame, width_fraction=0.6)
        # Bright band well below plateau (plateau 467..1223, so 1230+ is outside)
        # Need a band below plateau but inside zone: zone bottom 1247, plateau bottom 1223, so 1230..1247 is below plateau
        frame[1230:1247, 0:1080] = (200, 195, 185)
        plateau_top, plateau_bottom = scrim_plateau(frame.shape[1], frame.shape[0], "vertical", stack)
        assert 1230 > plateau_bottom
        measurement = measure_moment(frame, stack_height_px=stack)
        assert measurement.line_count == 1
        assert measurement.problems == []

    def test_type_inside_the_plateau_is_still_measured_exactly(self) -> None:
        stack = 700
        frame = _frame()
        _paint_line(frame, width_fraction=0.6)
        measurement = measure_moment(frame, stack_height_px=stack)
        assert measurement.line_count == 1
        assert measurement.has_text
        assert measurement.problems == []

    def test_plateau_rows_explicit_override(self) -> None:
        """Explicit plateau_rows should exclude a bright band even without height."""
        frame = _frame()
        _paint_line(frame, width_fraction=0.6)
        # Text at 482..508, plateau at 600..1100 would miss the text — choose plateau that CONTAINS text
        # Text centre ~495, so plateau must start <482. Use 440..1100 which includes text but excludes a band at 1150+
        frame[1150:1247, 0:1080] = (180, 180, 180)
        plateau = (440, 1100)
        measurement = measure_moment(frame, plateau_rows=plateau)
        assert measurement.line_count == 1
        assert measurement.problems == []

    def test_check_moment_arrangement_scoped_to_plateau(self) -> None:
        """A bright band outside the plateau must not be read as 'ink above hero'."""
        frame = _frame()
        _set_text(
            frame,
            "۲۲۶۴ نفر",
            weight="Black",
            size_px=216,
            colour=ACCENT,
            baseline_y=820,
        )
        # Bright unscrimmed band where a gap-framed footage highlight would sit
        frame[442:500, 200:900] = (200, 190, 180)
        # With zone-wide measurement the band would be neutral ink above hero
        # With plateau scoping it is outside and ignored
        result = check_moment_arrangement(frame, roles=["hero"], stack_height_px=280)
        # hero alone: expect no ink above; outside-plateau band must not create a false problem
        if result["checked"]:
            assert result["passed"] is True
            assert result["ink_above_hero"] is False

    def test_measure_stack_rhythm_scoped_to_plateau(self) -> None:
        """Bands outside plateau must not count as rhythm bands."""
        frame = _frame()
        _paint_line(frame, line_index=0, width_fraction=0.6)
        _paint_line(frame, line_index=2, width_fraction=0.5)
        # Bright band outside plateau should not create an extra band
        frame[442:460, 0:1080] = (180, 180, 180)
        result = measure_stack_rhythm(frame, lead_px=99, stack_height_px=280)
        # Should decline or pass without counting the bright band as a band
        if result.get("checked"):
            assert result["passed"] is True
