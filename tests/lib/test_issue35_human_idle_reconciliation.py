from __future__ import annotations

from datetime import datetime, timedelta, timezone

from lib import persian_video_workflow as workflow
from lib import persian_workflow_telemetry as telemetry


BASE = datetime(2026, 9, 20, 21, 0, tzinfo=timezone.utc)


def _state(trace_id: str) -> dict:
    return {
        "created_at": BASE.isoformat(),
        "causal_telemetry": telemetry.new_causal_trace(trace_id, started_at=BASE),
    }


def _human_idle_bounds(state: dict) -> list[tuple[str, str]]:
    return [
        (span["started_at"], span["finished_at"])
        for span in state["causal_telemetry"]["spans"]
        if span.get("kind") == "human_idle"
    ]


def test_human_idle_starts_after_late_reconciliation_that_crosses_terminal_time() -> None:
    state = _state("trace-crossing-reconcile")
    telemetry.record_causal_interval(
        state,
        span_id="reconcile:render-final",
        name="late render reconciliation",
        category="accounting_reconciliation",
        started_at=BASE + timedelta(seconds=8),
        finished_at=BASE + timedelta(seconds=15),
        kind="reconciliation",
    )
    telemetry.finish_causal_span(
        state,
        "run:trace-crossing-reconcile",
        finished_at=BASE + timedelta(seconds=10),
        outcome="awaiting_human",
    )

    telemetry.record_human_idle_and_reopen_run(
        state,
        resumed_at=BASE + timedelta(seconds=25),
        reason="explicit user revision",
    )

    assert _human_idle_bounds(state) == [
        (
            (BASE + timedelta(seconds=15)).isoformat(),
            (BASE + timedelta(seconds=25)).isoformat(),
        )
    ]


def test_human_idle_preserves_real_wait_gaps_around_post_terminal_system_work() -> None:
    state = _state("trace-split-idle")
    telemetry.record_causal_interval(
        state,
        span_id="reconcile:late",
        name="late reconciliation",
        category="accounting_reconciliation",
        started_at=BASE + timedelta(seconds=12),
        finished_at=BASE + timedelta(seconds=15),
        kind="reconciliation",
    )
    telemetry.finish_causal_span(
        state,
        "run:trace-split-idle",
        finished_at=BASE + timedelta(seconds=10),
        outcome="awaiting_human",
    )

    telemetry.record_human_idle_and_reopen_run(
        state,
        resumed_at=BASE + timedelta(seconds=25),
        reason="explicit user revision",
    )

    assert _human_idle_bounds(state) == [
        (
            (BASE + timedelta(seconds=10)).isoformat(),
            (BASE + timedelta(seconds=12)).isoformat(),
        ),
        (
            (BASE + timedelta(seconds=15)).isoformat(),
            (BASE + timedelta(seconds=25)).isoformat(),
        ),
    ]
    accounting = workflow.phase_time_accounting(state, now=BASE + timedelta(seconds=25))
    assert accounting["human_idle_seconds"] == 12.0
