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
    audit_render_luminance,
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


class TestTypographicPlateLuminance:
    @staticmethod
    def _patch_frames(monkeypatch, samples: list[tuple[float, float]]) -> None:
        monkeypatch.setattr(
            "lib.persian_render_qa._measure_luma_frames",
            lambda *a, **k: (samples, 0.1),
        )

    def test_dark_plate_with_real_moment_text_is_not_dead_black(self, monkeypatch, tmp_path) -> None:
        samples = [(float(i), 20.0 if 19 <= i < 25 else 80.0) for i in range(0, 51)]
        self._patch_frames(monkeypatch, samples)
        qa = audit_render_luminance(
            tmp_path / "render.mp4",
            beat_windows=[{"id": "beat-5", "startSeconds": 18.9, "endSeconds": 25.58}],
            moment_windows=[{"id": "moment-3", "startSeconds": 18.9, "endSeconds": 25.58}],
        )
        assert qa.passed is True
        assert qa.dead_runs == []
        assert qa.beat_luma[0]["meanYavg"] == pytest.approx(35.0)

    def test_partial_second_plate_boundary_is_not_a_dead_stretch(self, monkeypatch, tmp_path) -> None:
        """#147: reproduce the L3 38-39s raw-bin YAVG of exactly 21.4."""
        samples = [(37.0, 80.0)]
        samples += [
            (38.0 + index / 100.0, 57.0 if index < 11 else 17.0)
            for index in range(100)
        ]
        samples += [(39.0 + index / 100.0, 17.0) for index in range(100)]
        samples += [
            (40.0 + index / 100.0, 17.0 if index < 97 else 80.0)
            for index in range(100)
        ]
        samples += [(41.0, 80.0)]
        self._patch_frames(monkeypatch, samples)
        qa = audit_render_luminance(
            tmp_path / "render.mp4",
            beat_windows=[{"id": "beat-10", "startSeconds": 38.11, "endSeconds": 40.97}],
            moment_windows=[{"id": "m-card", "startSeconds": 38.11, "endSeconds": 40.97}],
        )
        assert dict(qa.per_second)[38.0] == pytest.approx(21.4)
        assert qa.passed is True
        assert qa.dead_runs == []

    @pytest.mark.parametrize("unprotected_yavg, expected_pass", [(23.0, True), (20.0, False)])
    def test_protected_endcaps_preserve_real_unprotected_run_verdict(
        self, monkeypatch, tmp_path, unprotected_yavg, expected_pass
    ) -> None:
        """Protection must neither darken safe footage nor hide a real 1.2s run."""
        samples = []
        for index in range(200):
            stamp = index / 100.0
            protected = stamp < 0.4 or stamp >= 1.6
            samples.append((stamp, 17.0 if protected else unprotected_yavg))
        self._patch_frames(monkeypatch, samples)
        beat_windows = [
            {"id": "lead", "startSeconds": 0.0, "endSeconds": 0.4},
            {"id": "tail", "startSeconds": 1.6, "endSeconds": 2.0},
        ]
        moment_windows = [
            {"id": "lead-text", "startSeconds": 0.0, "endSeconds": 0.4},
            {"id": "tail-text", "startSeconds": 1.6, "endSeconds": 2.0},
        ]
        qa = audit_render_luminance(
            tmp_path / "render.mp4",
            beat_windows=beat_windows,
            moment_windows=moment_windows,
        )
        assert qa.passed is expected_pass
        if expected_pass:
            assert qa.dead_runs == []
        else:
            assert len(qa.dead_runs) == 1
            # Bins 0.0-1.0 and 1.0-2.0 are both unprotected-dark, so the run is
            # reported at the measurement's own 1s resolution. The gate decides
            # on unprotected bin means; it cannot honestly claim sub-second
            # boundaries it never measured.
            assert qa.dead_runs[0].start_seconds == pytest.approx(0.0)
            assert qa.dead_runs[0].end_seconds == pytest.approx(2.0)

    @pytest.mark.parametrize(
        "label, dark, protected, expected_fail",
        [
            ("interior 0.02s blip inside a fully dark second", (4.0, 5.0), [(4.0, 4.02)], True),
            ("interior 0.04s blip inside a 2.0s dark stretch", (4.0, 6.0), [(4.98, 5.02)], True),
            ("typography over 1.0s of a 2.5s plate leaves a textless tail", (4.0, 6.5), [(4.2, 5.2)], True),
            ("a fully protected plate is not dead content", (4.0, 6.5), [(4.0, 6.5)], False),
            ("protection elsewhere does not excuse darkness", (4.0, 6.0), [(7.0, 8.0)], True),
        ],
    )
    def test_interior_protection_cannot_hide_a_dead_stretch(
        self, monkeypatch, tmp_path, label, dark, protected, expected_fail
    ) -> None:
        """A protected window overlapping a dark region must not sever it below
        `min_seconds`: the unprotected remainder is still dead footage.

        Regression for the interval-splitting approach, which returned
        `passed=True` for a 2.5s plate with a 1.3s textless tail.
        """
        dark_start, dark_end = dark
        samples = []
        for index in range(700):
            stamp = round(index / 100.0, 2)
            if not dark_start <= stamp < dark_end:
                yavg = 80.0
            elif any(start <= stamp < end for start, end in protected):
                yavg = 90.0
            else:
                yavg = 17.0
            samples.append((stamp, yavg))
        self._patch_frames(monkeypatch, samples)
        beat_windows = [
            {"id": f"beat-{i}", "startSeconds": start, "endSeconds": end}
            for i, (start, end) in enumerate(protected)
        ]
        moment_windows = [
            {"id": f"moment-{i}", "startSeconds": start, "endSeconds": end}
            for i, (start, end) in enumerate(protected)
        ]
        qa = audit_render_luminance(
            tmp_path / "render.mp4",
            beat_windows=beat_windows,
            moment_windows=moment_windows,
        )
        assert qa.passed is not expected_fail, label
        assert bool(qa.dead_runs) is expected_fail, label

    def test_dark_plate_without_moment_text_still_fails(self, monkeypatch, tmp_path) -> None:
        samples = [(float(i), 20.0 if 19 <= i < 25 else 80.0) for i in range(0, 51)]
        self._patch_frames(monkeypatch, samples)
        qa = audit_render_luminance(
            tmp_path / "render.mp4",
            beat_windows=[{"id": "beat-5", "startSeconds": 18.9, "endSeconds": 25.58}],
            moment_windows=[],
        )
        assert qa.passed is False
        assert qa.dead_runs
