"""Near-black run detection for the Persian render gate.

Calibrated against measured production data from coffee-hormones-fa: the broken
render's dead seconds measured YAVG 17-19, the repaired render 55-74 over the
same seconds, and legitimate dark cinematic footage (macro coffee-bean shot)
sits at ~28. So a run below 22 fails, a run below 30 warns, and 28 must pass.

These tests feed synthetic per-frame series — hermetic, no fixtures, no ffmpeg.
The two real renders are verified manually, not in this suite.
"""

from __future__ import annotations

import pytest

from lib.persian_render_qa import (
    DEAD_LUMA_FAIL,
    DEAD_LUMA_WARN,
    find_coverage_gaps,
    find_dark_runs,
    window_mean,
)


def _frames(
    yavg: float, count: int, start: float = 0.0, fps: float = 30.0
) -> list[tuple[float, float]]:
    return [(start + index / fps, yavg) for index in range(count)]


class TestDeadRunDetection:
    def test_a_run_at_or_over_one_second_below_22_is_flagged(self) -> None:
        samples = _frames(125.0, 60) + _frames(17.5, 40, start=2.0)
        runs = find_dark_runs(samples, below=DEAD_LUMA_FAIL, min_seconds=1.0)
        assert len(runs) == 1
        assert runs[0].start_seconds == pytest.approx(2.0)
        assert runs[0].end_seconds == pytest.approx(2.0 + 40 / 30.0)
        assert runs[0].mean_yavg == pytest.approx(17.5)

    def test_exactly_one_second_below_22_is_flagged(self) -> None:
        samples = _frames(18.0, 30, start=5.0)
        runs = find_dark_runs(samples, below=DEAD_LUMA_FAIL, min_seconds=1.0)
        assert len(runs) == 1

    def test_legitimate_dark_footage_at_28_is_not_a_failure(self) -> None:
        """The macro coffee-bean shot: real footage with texture at YAVG ~28."""
        samples = _frames(28.0, 150, start=52.0)
        assert find_dark_runs(samples, below=DEAD_LUMA_FAIL, min_seconds=1.0) == []

    def test_28_is_warned_but_not_failed(self) -> None:
        samples = _frames(28.0, 60)
        warned = find_dark_runs(samples, below=DEAD_LUMA_WARN, min_seconds=1.0)
        failed = find_dark_runs(samples, below=DEAD_LUMA_FAIL, min_seconds=1.0)
        assert len(warned) == 1
        assert failed == []

    def test_a_sub_second_dip_is_not_flagged(self) -> None:
        """Twenty dark frames (0.67s) inside bright footage: a dip, not a stretch."""
        samples = (
            _frames(120.0, 60)
            + _frames(17.0, 20, start=2.0)
            + _frames(120.0, 60, start=2.0 + 20 / 30.0)
        )
        assert find_dark_runs(samples, below=DEAD_LUMA_FAIL, min_seconds=1.0) == []

    def test_a_dip_diluted_inside_its_second_is_not_flagged(self) -> None:
        """A half-second hole averages with bright neighbours above the floor."""
        samples = [(0.0, 60.0), (1.0, 25.0), (2.0, 60.0)]
        assert find_dark_runs(samples, below=DEAD_LUMA_FAIL, min_seconds=1.0) == []

    def test_empty_series_is_safe_and_a_lone_dark_second_counts(self) -> None:
        """No samples means no run; one dark 1s bin IS a full second of darkness."""
        assert find_dark_runs([], below=DEAD_LUMA_FAIL, min_seconds=1.0) == []
        runs = find_dark_runs([(3.0, 10.0)], below=DEAD_LUMA_FAIL, min_seconds=1.0)
        assert len(runs) == 1
        assert runs[0].start_seconds == pytest.approx(3.0)

    def test_two_separate_runs_are_reported_separately(self) -> None:
        samples = (
            _frames(17.0, 40, start=1.0)
            + _frames(120.0, 60, start=1.0 + 40 / 30.0)
            + _frames(18.0, 35, start=5.0)
        )
        runs = find_dark_runs(samples, below=DEAD_LUMA_FAIL, min_seconds=1.0)
        assert len(runs) == 2
        assert runs[0].start_seconds == pytest.approx(1.0)
        assert runs[1].start_seconds == pytest.approx(5.0)


class TestCoverageGaps:
    def test_a_real_gap_is_reported(self) -> None:
        gaps = find_coverage_gaps([(0.0, 5.0), (7.5, 12.0)], 12.0)
        assert gaps == [(5.0, 7.5)]

    def test_a_trailing_tail_is_reported(self) -> None:
        gaps = find_coverage_gaps([(0.0, 5.0)], 12.0)
        assert gaps == [(5.0, 12.0)]

    def test_rounding_noise_stays_quiet(self) -> None:
        """Millisecond seams from float arithmetic are not an uncovered stretch."""
        gaps = find_coverage_gaps([(0.0, 5.0004), (5.0, 12.0)], 12.0)
        assert gaps == []

    def test_a_quarter_second_hole_fails(self) -> None:
        """A visible black flash must fail with margin above the tolerance."""
        gaps = find_coverage_gaps([(0.0, 5.0), (5.25, 12.0)], 12.0)
        assert gaps == [(5.0, 5.25)]

    def test_full_coverage_is_quiet(self) -> None:
        gaps = find_coverage_gaps([(0.0, 5.0), (5.0, 12.0)], 12.0)
        assert gaps == []


class TestWindowMeanBinWidth:
    def test_frame_rate_input_uses_its_own_spacing(self) -> None:
        """30fps samples around a 1s dark window: the window mean is the dark
        value, not the dark second diluted by bright neighbours."""
        fps = 30.0
        samples = [
            (index / fps, 20.0 if 5.0 <= index / fps < 6.0 else 100.0)
            for index in range(int(7 * fps))
        ]
        assert window_mean(samples, 5.0, 6.0) == pytest.approx(20.0)

    def test_one_second_bins_still_overlap(self) -> None:
        samples = [(0.0, 60.0), (1.0, 25.0), (2.0, 60.0)]
        assert window_mean(samples, 0.5, 1.5) == pytest.approx(42.5)
