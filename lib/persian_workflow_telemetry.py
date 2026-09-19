"""Causal and legacy telemetry helpers for Persian production workflows.

Phase telemetry remains readable for older workflow records. New production runs also
carry one causal trace whose structural spans describe parentage and whose accounting
spans explain real wall-clock intervals without pretending that a phase-open duration
is equivalent to machine or provider work.
"""
from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any


TERMINAL_ATTEMPT_OUTCOMES = frozenset(
    {"succeeded", "failed", "timed_out", "cancelled", "superseded"}
)
CAUSAL_CATEGORIES = frozenset(
    {
        "workflow_wall",
        "machine_local_execution",
        "provider_network_wait",
        "agent_editorial_work",
        "browser_render_execution",
        "review_evidence_assembly",
        "accounting_reconciliation",
        "automated_recovery",
        "human_idle",
    }
)
_RESERVED_SPAN_FIELDS = frozenset(
    {
        "trace_id",
        "span_id",
        "parent_span_id",
        "name",
        "kind",
        "category",
        "started_at",
        "finished_at",
        "outcome",
        "count_toward_wall",
        "concurrency_group",
    }
)


def _parse(value: object) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or ""))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _required_time(value: datetime | str, label: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    parsed = _parse(value)
    if parsed is None:
        raise ValueError(f"{label} must be an ISO-8601 timestamp")
    return parsed


def new_causal_trace(trace_id: str, *, started_at: datetime | str) -> dict[str, Any]:
    trace_id = str(trace_id).strip()
    if not trace_id:
        raise ValueError("trace_id must be non-empty")
    started = _required_time(started_at, "started_at")
    run_span_id = f"run:{trace_id}"
    return {
        "version": 1,
        "trace_id": trace_id,
        "run_span_id": run_span_id,
        "started_at": started.isoformat(),
        "spans": [
            {
                "trace_id": trace_id,
                "span_id": run_span_id,
                "parent_span_id": None,
                "name": "persian_production_run",
                "kind": "run",
                "category": "workflow_wall",
                "started_at": started.isoformat(),
                "finished_at": None,
                "outcome": "running",
                "count_toward_wall": False,
            }
        ],
    }


def _causal_trace(state: Mapping[str, Any]) -> dict[str, Any] | None:
    trace = state.get("causal_telemetry")
    return dict(trace) if isinstance(trace, Mapping) else None


def _span_times(span: Mapping[str, Any]) -> tuple[datetime, datetime] | None:
    started = _parse(span.get("started_at"))
    finished = _parse(span.get("finished_at"))
    if started is None or finished is None:
        return None
    return started, finished


def _validate_overlap(spans: list[Mapping[str, Any]], candidate: Mapping[str, Any]) -> None:
    if not candidate.get("count_toward_wall"):
        return
    candidate_times = _span_times(candidate)
    if candidate_times is None:
        return
    candidate_group = str(candidate.get("concurrency_group") or "").strip()
    for existing in spans:
        if str(existing.get("span_id")) == str(candidate.get("span_id")):
            continue
        if not existing.get("count_toward_wall"):
            continue
        existing_times = _span_times(existing)
        if existing_times is None:
            continue
        start = max(candidate_times[0], existing_times[0])
        end = min(candidate_times[1], existing_times[1])
        if end <= start:
            continue
        existing_group = str(existing.get("concurrency_group") or "").strip()
        if candidate_group and candidate_group == existing_group:
            continue
        raise ValueError(
            "causal accounting span overlap requires an explicit shared concurrency_group: "
            f"{candidate.get('span_id')} overlaps {existing.get('span_id')}"
        )


def record_causal_interval(
    state: dict[str, Any],
    *,
    span_id: str,
    name: str,
    category: str,
    started_at: datetime | str,
    finished_at: datetime | str | None = None,
    parent_span_id: str | None = None,
    outcome: str | None = None,
    kind: str = "work",
    count_toward_wall: bool = True,
    concurrency_group: str | None = None,
    fields: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Create or update one span while preserving explicit concurrency semantics."""
    trace = _causal_trace(state)
    if trace is None:
        raise ValueError("causal_telemetry trace is missing")
    category = str(category).strip()
    if category not in CAUSAL_CATEGORIES:
        raise ValueError(f"unsupported causal telemetry category: {category!r}")
    span_id = str(span_id).strip()
    if not span_id:
        raise ValueError("span_id must be non-empty")
    started = _required_time(started_at, "started_at")
    finished = _required_time(finished_at, "finished_at") if finished_at is not None else None
    if finished is not None and finished < started:
        raise ValueError("finished_at cannot precede started_at")
    resolved_parent = parent_span_id
    if resolved_parent is None and span_id != trace.get("run_span_id"):
        resolved_parent = str(trace.get("run_span_id") or "") or None
    spans = [dict(item) for item in list(trace.get("spans") or []) if isinstance(item, Mapping)]
    if resolved_parent is not None and not any(
        str(item.get("span_id")) == str(resolved_parent) for item in spans
    ):
        raise ValueError(f"parent span not found: {resolved_parent}")
    if fields:
        reserved = sorted(_RESERVED_SPAN_FIELDS.intersection(str(key) for key in fields))
        if reserved:
            raise ValueError(
                "reserved span fields cannot be overridden: " + ", ".join(reserved)
            )
    candidate: dict[str, Any] = {
        "trace_id": str(trace["trace_id"]),
        "span_id": span_id,
        "parent_span_id": resolved_parent,
        "name": str(name),
        "kind": str(kind),
        "category": category,
        "started_at": started.isoformat(),
        "finished_at": finished.isoformat() if finished is not None else None,
        "outcome": str(outcome or ("running" if finished is None else "succeeded")),
        "count_toward_wall": bool(count_toward_wall),
    }
    if concurrency_group:
        candidate["concurrency_group"] = str(concurrency_group)
    if fields:
        candidate.update({str(key): value for key, value in fields.items()})

    _validate_overlap(spans, candidate)
    replaced = False
    for index, existing in enumerate(spans):
        if str(existing.get("span_id")) == span_id:
            spans[index] = candidate
            replaced = True
            break
    if not replaced:
        spans.append(candidate)
    trace["spans"] = spans
    state["causal_telemetry"] = trace
    return candidate


def finish_causal_span(
    state: dict[str, Any],
    span_id: str,
    *,
    finished_at: datetime | str,
    outcome: str,
) -> dict[str, Any]:
    trace = _causal_trace(state)
    if trace is None:
        raise ValueError("causal_telemetry trace is missing")
    spans = [dict(item) for item in list(trace.get("spans") or []) if isinstance(item, Mapping)]
    existing = next((item for item in spans if str(item.get("span_id")) == span_id), None)
    if existing is None:
        raise ValueError(f"causal span not found: {span_id}")
    return record_causal_interval(
        state,
        span_id=span_id,
        name=str(existing.get("name") or span_id),
        category=str(existing.get("category") or "agent_editorial_work"),
        started_at=str(existing.get("started_at")),
        finished_at=finished_at,
        parent_span_id=existing.get("parent_span_id"),
        outcome=outcome,
        kind=str(existing.get("kind") or "work"),
        count_toward_wall=bool(existing.get("count_toward_wall")),
        concurrency_group=(str(existing.get("concurrency_group")) if existing.get("concurrency_group") else None),
        fields={
            key: value
            for key, value in existing.items()
            if key not in _RESERVED_SPAN_FIELDS
        },
    )


def causal_phase_span_id(phase: str, attempt: int) -> str:
    return f"phase:{phase}:{int(attempt)}"


def record_phase_attempt_span(
    state: dict[str, Any],
    phase: str,
    attempt: int,
    *,
    started_at: datetime | str,
) -> dict[str, Any]:
    trace = _causal_trace(state)
    if trace is None:
        raise ValueError("causal_telemetry trace is missing")
    return record_causal_interval(
        state,
        span_id=causal_phase_span_id(phase, attempt),
        name=f"{phase} attempt {int(attempt)}",
        category="agent_editorial_work",
        started_at=started_at,
        parent_span_id=str(trace["run_span_id"]),
        kind="phase_attempt",
        count_toward_wall=False,
        fields={"phase": phase, "attempt": int(attempt)},
    )


def finish_phase_attempt_span(
    state: dict[str, Any],
    phase: str,
    attempt: int,
    *,
    finished_at: datetime | str,
    outcome: str,
) -> None:
    trace = _causal_trace(state)
    if trace is None:
        return
    span_id = causal_phase_span_id(phase, attempt)
    spans = list(trace.get("spans") or [])
    if not any(isinstance(item, Mapping) and item.get("span_id") == span_id for item in spans):
        return
    finish_causal_span(state, span_id, finished_at=finished_at, outcome=outcome)


def _interval_union_seconds(intervals: list[tuple[datetime, datetime]]) -> float:
    if not intervals:
        return 0.0
    ordered = sorted(intervals, key=lambda item: item[0])
    merged: list[list[datetime]] = []
    for start, end in ordered:
        if not merged or start > merged[-1][1]:
            merged.append([start, end])
        elif end > merged[-1][1]:
            merged[-1][1] = end
    return sum((end - start).total_seconds() for start, end in merged)


def causal_time_accounting(
    state: Mapping[str, Any],
    *,
    now: datetime,
    since: datetime | None = None,
    include_open: bool = False,
) -> dict[str, Any] | None:
    """Explain wall time using causal accounting spans, preserving uncovered time."""
    trace = _causal_trace(state)
    if trace is None:
        return None
    current = _required_time(now, "now")
    origin = since or _parse(trace.get("started_at")) or _parse(state.get("created_at")) or current
    origin = _required_time(origin, "origin")
    intervals: list[tuple[datetime, datetime]] = []
    category_seconds = {category: 0.0 for category in CAUSAL_CATEGORIES}
    counted = 0
    raw_total = 0.0
    for raw in list(trace.get("spans") or []):
        if not isinstance(raw, Mapping) or not raw.get("count_toward_wall"):
            continue
        started = _parse(raw.get("started_at"))
        finished = _parse(raw.get("finished_at"))
        if started is None:
            continue
        if finished is None:
            if not include_open:
                continue
            finished = current
        clipped_start = max(origin, started)
        clipped_end = min(current, finished)
        if clipped_end <= clipped_start:
            continue
        duration = (clipped_end - clipped_start).total_seconds()
        counted += 1
        raw_total += duration
        intervals.append((clipped_start, clipped_end))
        category = str(raw.get("category") or "")
        if category in category_seconds:
            category_seconds[category] += duration
    covered = _interval_union_seconds(intervals)
    wall = max(0.0, (current - origin).total_seconds())
    unattributed = max(0.0, wall - covered)
    concurrency = max(0.0, raw_total - covered)
    coverage_percent = 100.0 if wall <= 0.0 else min(100.0, (covered / wall) * 100.0)
    provider = category_seconds["provider_network_wait"]
    editorial = category_seconds["agent_editorial_work"]
    browser = category_seconds["browser_render_execution"]
    machine = category_seconds["machine_local_execution"]
    review = category_seconds["review_evidence_assembly"]
    accounting = category_seconds["accounting_reconciliation"]
    recovery = category_seconds["automated_recovery"]
    human_idle = category_seconds["human_idle"]
    external = provider + machine + browser
    return {
        "job_runtime_seconds": round(wall, 3),
        "workflow_wall_seconds": round(wall, 3),
        "provider_wait_seconds": round(provider, 3),
        "machine_execution_seconds": round(machine, 3),
        "browser_render_seconds": round(browser, 3),
        "accounting_lag_seconds": round(accounting, 3),
        "editorial_wall_seconds": round(editorial, 3),
        "review_phase_seconds": round(review, 3),
        "automated_recovery_seconds": round(recovery, 3),
        "human_idle_seconds": round(human_idle, 3),
        "causal_covered_seconds": round(covered, 3),
        "explicit_concurrency_seconds": round(concurrency, 3),
        "telemetry_span_count": counted,
        "causal_coverage_percent": round(coverage_percent, 3),
        "orchestration_gap_seconds": round(unattributed, 3),
        "unattributed_wall_seconds": round(unattributed, 3),
        "active_editorial_seconds": round(editorial, 3),
        "external_durable_seconds": round(external, 3),
        "total_observed_seconds": round(covered, 3),
    }


def reconcile_phase_telemetry(
    state: dict[str, Any], *, now: datetime | None = None
) -> dict[str, Any]:
    """Close stale running attempts using later attempts or terminal workflow time."""
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
            try:
                attempt = int(item.get("attempt") or 0)
            except (TypeError, ValueError):
                attempt = 0
            if attempt > 0:
                finish_phase_attempt_span(
                    state,
                    str(phase),
                    attempt,
                    finished_at=finished,
                    outcome="superseded",
                )
        updated[str(phase)] = entries
    state["phase_telemetry"] = updated
    return state


__all__ = [
    "CAUSAL_CATEGORIES",
    "TERMINAL_ATTEMPT_OUTCOMES",
    "causal_phase_span_id",
    "causal_time_accounting",
    "finish_causal_span",
    "finish_phase_attempt_span",
    "new_causal_trace",
    "record_causal_interval",
    "record_phase_attempt_span",
    "reconcile_phase_telemetry",
]
