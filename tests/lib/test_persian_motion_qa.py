from __future__ import annotations

import pytest

from lib.persian_motion_qa import (
    MOTION_SAMPLE_FPS,
    MotionDelta,
    find_near_static_runs,
    frame_mean_abs_delta,
)


def _deltas(seconds: float, value: float, *, start: float = 0.5) -> list[MotionDelta]:
    step = 1.0 / MOTION_SAMPLE_FPS
    count = int(seconds / step)
    return [MotionDelta(start + index * step, value) for index in range(count)]


def test_identical_frames_have_zero_delta() -> None:
    assert frame_mean_abs_delta(bytes([10, 20, 30]), bytes([10, 20, 30])) == 0.0


def test_mean_absolute_delta_is_per_pixel() -> None:
    assert frame_mean_abs_delta(bytes([0, 10, 20, 30]), bytes([2, 8, 22, 28])) == pytest.approx(2.0)


def test_frame_delta_refuses_mismatched_or_empty_frames() -> None:
    with pytest.raises(ValueError):
        frame_mean_abs_delta(b"", b"")
    with pytest.raises(ValueError):
        frame_mean_abs_delta(b"a", b"ab")


def test_long_near_frozen_run_is_detected() -> None:
    runs = find_near_static_runs(_deltas(9.5, 0.2), min_seconds=9.0)
    assert len(runs) == 1
    assert runs[0].start_seconds == pytest.approx(0.0)
    assert runs[0].duration_seconds >= 9.0


def test_live_pixels_do_not_form_a_static_run() -> None:
    assert find_near_static_runs(_deltas(12.0, 4.0), min_seconds=7.0) == []


def test_a_visual_change_splits_two_short_static_stretches() -> None:
    step = 1.0 / MOTION_SAMPLE_FPS
    first = _deltas(4.0, 0.0)
    break_at = first[-1].at_seconds + step
    second = [MotionDelta(break_at, 10.0)]
    second.extend(
        MotionDelta(break_at + (index + 1) * step, 0.0)
        for index in range(int(4.0 / step))
    )
    assert find_near_static_runs(first + second, min_seconds=7.0) == []


def test_missing_sample_breaks_contiguity() -> None:
    samples = _deltas(4.0, 0.0)
    samples += [MotionDelta(item.at_seconds + 6.0, item.mean_abs_delta) for item in _deltas(4.0, 0.0)]
    assert find_near_static_runs(samples, min_seconds=7.0) == []
