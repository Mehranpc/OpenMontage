from __future__ import annotations

from datetime import datetime, timedelta, timezone

from lib.persian_video_workflow import assert_within_wall_time, phase_time_accounting

BASE = datetime(2026, 9, 17, 11, 30, tzinfo=timezone.utc)


def _entry(start_minutes: float, duration_seconds: float, execution_class: str = "editorial") -> dict:
    started = BASE + timedelta(minutes=start_minutes)
    return {
        "attempt": 1,
        "started_at": started.isoformat(),
        "finished_at": (started + timedelta(seconds=duration_seconds)).isoformat(),
        "duration_seconds": duration_seconds,
        "execution_class": execution_class,
        "outcome": "succeeded",
    }


def test_honest_timing_reports_true_wall_clock_and_unattributed_gaps() -> None:
    state = {
        "created_at": BASE.isoformat(),
        "budget_window_started_at": BASE.isoformat(),
        "phase_telemetry": {
            "opening_review": [_entry(10, 600)],
            "render_final_candidate": [_entry(25, 300, "external_durable")],
            "final_review": [_entry(60, 120)],
        },
    }

    result = phase_time_accounting(state, now=BASE + timedelta(minutes=80))

    assert result["workflow_wall_seconds"] == 4800.0
    assert result["total_observed_seconds"] == 1020.0
    assert result["review_phase_seconds"] == 720.0
    assert result["orchestration_gap_seconds"] == 3780.0
    assert result["unattributed_wall_seconds"] == 3780.0
    assert result["provider_wait_seconds"] == 300.0
    assert result["editorial_wall_seconds"] == 720.0


def test_runtime_target_is_advisory_not_a_hard_execution_kill() -> None:
    state = {
        "created_at": BASE.isoformat(),
        "budget_window_started_at": BASE.isoformat(),
        "budgets": {"max_wall_time_minutes": 45},
        "phase_telemetry": {"opening_review": [_entry(0, 3600)]},
    }

    # Issue #32 treats 30/45 minutes as an architecture/SLO signal. The front door
    # must not kill a valid production merely because elapsed work crossed 45m.
    assert_within_wall_time(state, now=BASE + timedelta(minutes=80))
