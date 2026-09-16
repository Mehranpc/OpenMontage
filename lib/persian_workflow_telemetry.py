"""Terminal reconciliation helpers for Persian workflow phase telemetry.

A completed workflow must not retain stale `running` attempts. The workflow module
calls this helper at terminal transitions; keeping the mechanics isolated also makes
the state repair independently testable and reusable by resume/reconcile tooling.
"""
from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any


TERMINAL_ATTEMPT_OUTCOMES = frozenset(
    {"succeeded", "failed", "timed_out", "cancelled", "superseded"}
)


def _parse(value: object) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or ""))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def reconcile_phase_telemetry(
    state: dict[str, Any], *, now: datetime | None = None
) -> dict[str, Any]:
    """Close stale running attempts using later attempts or terminal workflow time.

    The function mutates and returns ``state`` for the same state-machine style used
    by ``persian_video_workflow``. Earlier unfinished attempts are superseded at the
    next attempt's start. If the workflow itself is terminal, any final orphan is
    superseded at ``now``. Active workflows keep their newest open attempt untouched.
    """
    telemetry = state.get("phase_telemetry")
    if not isinstance(telemetry, Mapping):
        return state
    terminal_workflow = str(state.get("status") or "") in {
        "awaiting_human",
        "completed",
        "failed",
        "cancelled",
    } or "awaiting_human" in list(state.get("completed_phases") or [])
    resolved_now = now or datetime.now(timezone.utc)
    updated: dict[str, Any] = dict(telemetry)

    for phase, raw_entries in telemetry.items():
        if not isinstance(raw_entries, list):
            continue
        entries = [dict(item) if isinstance(item, Mapping) else item for item in raw_entries]
        for index, item in enumerate(entries):
            if not isinstance(item, dict):
                continue
            if item.get("finished_at") and str(item.get("outcome") or "") in TERMINAL_ATTEMPT_OUTCOMES:
                continue
            next_start = None
            for later in entries[index + 1 :]:
                if isinstance(later, Mapping):
                    next_start = _parse(later.get("started_at"))
                    if next_start is not None:
                        break
            if next_start is None and not terminal_workflow:
                continue
            finished = next_start or resolved_now
            started = _parse(item.get("started_at")) or finished
            item["finished_at"] = finished.isoformat()
            item["duration_seconds"] = round(max(0.0, (finished - started).total_seconds()), 3)
            item["outcome"] = "superseded"
        updated[str(phase)] = entries
    state["phase_telemetry"] = updated
    return state


__all__ = ["TERMINAL_ATTEMPT_OUTCOMES", "reconcile_phase_telemetry"]
