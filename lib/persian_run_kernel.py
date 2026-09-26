"""Deep execution envelope for durable Persian production phases.

Creative/editorial decisions remain agent-owned. This module owns the deterministic
mechanics that connect one workflow phase attempt to one durable process, its semantic
result, persisted evidence/checkpoint state, and workflow transition outcome.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager, nullcontext
from contextvars import ContextVar
import fcntl
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import time
from typing import Any, Callable, Mapping, Sequence

from lib.json_safe import to_json_safe
from lib.persian_durable_job import durable_command_sha256
from lib.persian_workflow_telemetry import (
    CAUSAL_CATEGORIES,
    causal_phase_span_id,
    record_causal_interval,
)
from lib import persian_video_workflow as workflow

MEDIA_EXECUTION_PHASES = frozenset({
    "render_opening_candidate", "render_final_candidate", "master_final_candidate",
})
_COMMIT_JOB: ContextVar[str | None] = ContextVar("persian_commit_job", default=None)


def require_measured_phase_commit(state: Mapping[str, Any], phase: str,
                                  evidence: Mapping[str, Any]) -> None:
    """Bind each media phase to successful execution and exact output bytes."""
    if phase not in MEDIA_EXECUTION_PHASES:
        return
    job_id = _COMMIT_JOB.get()
    if job_id is None:
        raise workflow.PersianVideoWorkflowError(
            f"{phase} must complete through the run kernel; use run/status/commit "
            "with the same durable job identity, not direct complete"
        )
    envelope = _read_json(_envelope_path(state, job_id))
    if (envelope.get("phase") != phase
            or envelope.get("phaseAttempt") != (state.get("attempts") or {}).get(phase)
            or int(envelope.get("revisionCycle", 0)) != int(state.get("user_revision_cycles") or 0)):
        raise workflow.PersianVideoWorkflowError("media execution belongs to another phase attempt or revision cycle")
    if envelope.get("executionOutcome") != "succeeded" or envelope.get("telemetryOutcome") != "succeeded":
        raise workflow.PersianVideoWorkflowError("media execution and causal reporting must succeed before commit")
    result = envelope.get("semanticResult")
    data = result.get("data") if isinstance(result, Mapping) else None
    if not isinstance(data, Mapping):
        raise workflow.PersianVideoWorkflowError("media execution requires a semantic result with output identity")
    reported_path = data.get("output_path")
    reported_sha = str(data.get("output_sha256") or "").lower()
    if not reported_path or not re.fullmatch(r"[0-9a-f]{64}", reported_sha):
        raise workflow.PersianVideoWorkflowError("media execution result lacks output path and sha256")
    output = workflow._project_file(state, reported_path, label="measured media output")
    if workflow._hash_file(output) != reported_sha:
        raise workflow.PersianVideoWorkflowError("measured media output sha256 changed after execution")
    evidence_path = evidence.get("candidatePath") if phase == "master_final_candidate" else evidence.get("output_path")
    if not evidence_path or workflow._project_file(state, evidence_path, label="phase media output") != output:
        raise workflow.PersianVideoWorkflowError("phase media output does not match measured execution")
    evidence_sha = evidence.get("candidateSha256") if phase == "master_final_candidate" else evidence.get("opening_candidate_sha256" if phase == "render_opening_candidate" else "output_sha256")
    if str(evidence_sha or "").lower() != reported_sha:
        raise workflow.PersianVideoWorkflowError("phase media sha256 does not match measured execution")


_ENVELOPE_VERSION = "1.0"
_JOB_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
_CHECKPOINTED_PHASES = frozenset({
    "align_script_timing",
    "plan_scenes_moments",
    "acquire_assets",
    "no_copy_preflight",
})


class PersianRunKernelError(ValueError):
    """Raised when the production execution envelope would become inconsistent."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_time(value: object) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or ""))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _countable_span_bounds(span: Mapping[str, Any]) -> tuple[datetime, datetime] | None:
    if not bool(span.get("count_toward_wall")) or span.get("kind") == "phase_residual":
        return None
    started = _parse_time(span.get("started_at"))
    finished = _parse_time(span.get("finished_at"))
    if started is None or finished is None or finished <= started:
        return None
    return started, finished


def _uncovered_reconciliation_intervals(
    start: datetime, end: datetime, spans: Sequence[Mapping[str, Any]]
) -> list[tuple[datetime, datetime]]:
    """Return lag intervals not already explained by measured causal work."""
    covered: list[tuple[datetime, datetime]] = []
    for span in spans:
        bounds = _countable_span_bounds(span)
        if bounds is None:
            continue
        left = max(start, bounds[0])
        right = min(end, bounds[1])
        if right > left:
            covered.append((left, right))
    if not covered:
        return [(start, end)] if end > start else []
    covered.sort(key=lambda item: item[0])
    merged: list[list[datetime]] = []
    for left, right in covered:
        if not merged or left > merged[-1][1]:
            merged.append([left, right])
        elif right > merged[-1][1]:
            merged[-1][1] = right
    gaps: list[tuple[datetime, datetime]] = []
    cursor = start
    for left, right in merged:
        if left > cursor:
            gaps.append((cursor, left))
        cursor = max(cursor, right)
    if cursor < end:
        gaps.append((cursor, end))
    return gaps


def _validate_job_id(job_id: str) -> str:
    if not _JOB_ID_RE.fullmatch(job_id):
        raise PersianRunKernelError(
            "job_id must be 1-80 ASCII letters/digits plus ._- characters"
        )
    return job_id


def _project_root(state: Mapping[str, Any]) -> Path:
    return Path(str(state["read_allowlist"]["project_root"])).resolve()


def _envelope_path(state: Mapping[str, Any], job_id: str) -> Path:
    return _project_root(state) / ".jobs" / _validate_job_id(job_id) / "execution-envelope.json"


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps(to_json_safe(dict(payload)), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temp.replace(path)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PersianRunKernelError(f"execution envelope is unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise PersianRunKernelError(f"execution envelope is not a JSON object: {path}")
    return value



@contextmanager
def _media_start_serialization(state: Mapping[str, Any], phase: str):
    """Serialize media-job admission so concurrent callers cannot both launch renders."""
    if phase not in MEDIA_EXECUTION_PHASES:
        yield
        return
    lock_path = _project_root(state) / ".jobs" / ".media-start.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _assert_media_execution_slot(
    project_id: str,
    requested_job_id: str,
    *,
    requested_idempotence_key: str,
    pipeline_dir: Path | None,
) -> None:
    """Allow at most one current-revision media execution until it is resolved.

    A successful render remains authoritative even after its process exits: callers
    must commit/reconcile that exact job rather than launch duplicate expensive work.
    Failed/interrupted historical jobs do not occupy the slot after reconciliation.
    """
    state = workflow.load_workflow_state(project_id, pipeline_dir=pipeline_dir)
    revision_cycle = int(state.get("user_revision_cycles") or 0)
    jobs_root = _project_root(state) / ".jobs"
    for path in sorted(jobs_root.glob("*/execution-envelope.json")):
        owner_job_id = path.parent.name
        if owner_job_id == requested_job_id:
            continue
        envelope = _read_json(path)
        if str(envelope.get("idempotenceKey") or "") == requested_idempotence_key:
            # A restarted caller may present a fresh job id for the same logical
            # operation. Let durable idempotence resolve it to the original job;
            # the media slot must block only distinct logical executions.
            continue
        if envelope.get("phase") not in MEDIA_EXECUTION_PHASES:
            continue
        if int(envelope.get("revisionCycle") or 0) != revision_cycle:
            continue
        if envelope.get("workflowTransitionOutcome") == "succeeded":
            continue

        if envelope.get("executionMode") != "inline_fixture":
            try:
                reconcile_phase_job(project_id, owner_job_id, pipeline_dir=pipeline_dir)
            except Exception as exc:
                raise PersianRunKernelError(
                    f"media execution slot cannot be established while job {owner_job_id!r} "
                    f"cannot be reconciled: {exc}"
                ) from exc
            envelope = _read_json(path)
            if envelope.get("workflowTransitionOutcome") == "succeeded":
                continue

        outcome = str(envelope.get("executionOutcome") or "pending")
        if outcome in {"failed", "interrupted"}:
            continue
        if outcome == "succeeded":
            raise PersianRunKernelError(
                f"successful media execution job {owner_job_id!r} must be committed/reconciled "
                "before another media execution can start"
            )
        raise PersianRunKernelError(
            f"media execution slot is occupied by job {owner_job_id!r} "
            f"(phase={envelope.get('phase')!r}, outcome={outcome!r})"
        )


def _open_phase_attempt(state: Mapping[str, Any], phase: str) -> int | None:
    telemetry = state.get("phase_telemetry")
    entries = telemetry.get(phase) if isinstance(telemetry, Mapping) else None
    if not isinstance(entries, list) or not entries or not isinstance(entries[-1], Mapping):
        return None
    latest = entries[-1]
    if latest.get("finished_at") or latest.get("outcome") != "running":
        return None
    try:
        return int(latest["attempt"])
    except (KeyError, TypeError, ValueError):
        return None


def _idempotence_already_persisted(
    state: Mapping[str, Any], idempotence_key: str
) -> bool:
    index_path = _project_root(state) / ".jobs" / "idempotence.json"
    if not index_path.is_file():
        return False
    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PersianRunKernelError(
            f"durable idempotence index is unreadable: {index_path}"
        ) from exc
    if not isinstance(index, Mapping):
        raise PersianRunKernelError("durable idempotence index must be a JSON object")
    return bool(index.get(idempotence_key))


def _enforce_new_execution_budget(
    state: Mapping[str, Any],
    *,
    project_id: str,
    phase: str,
    job_id: str,
    argv: Sequence[str],
    idempotence_key: str,
    telemetry_category: str,
    pipeline_dir: Path | None,
    now: datetime | None,
) -> dict[str, Any]:
    if _idempotence_already_persisted(state, idempotence_key):
        return dict(state)
    try:
        return workflow.enforce_front_door_budget(
            project_id,
            operation="run-kernel:start",
            pipeline_dir=pipeline_dir,
            now=now,
            operation_evidence={
                "phase": phase,
                "job_id": job_id,
                "idempotence_key": idempotence_key,
                "telemetry_category": telemetry_category,
                "command_sha256": durable_command_sha256(argv),
            },
        )
    except workflow.PersianVideoWorkflowError as exc:
        raise PersianRunKernelError(str(exc)) from exc


def _enforce_execution_checkpoint(
    project_id: str,
    *,
    operation: str,
    phase: str,
    job_id: str,
    pipeline_dir: Path | None,
    now: datetime | None = None,
) -> None:
    """Stop a live parent at a safe control boundary without discarding its durable child."""
    try:
        state = workflow.enforce_front_door_budget(
            project_id,
            operation=operation,
            pipeline_dir=pipeline_dir,
            now=now,
            operation_evidence={"phase": phase, "job_id": job_id},
        )
    except workflow.PersianVideoWorkflowError as exc:
        raise PersianRunKernelError(str(exc)) from exc
    stop = state.get("budget_stop")
    if (
        state.get("status") == "failed"
        and isinstance(stop, Mapping)
        and stop.get("reason") in {"wall_budget_exceeded", "phase_budget_exceeded"}
    ):
        raise PersianRunKernelError(
            f"{stop.get('reason')}: workflow budget already stopped durable job {job_id!r}; "
            "reconcile/status remains available until an explicit resume decision"
        )


def _artifact_identity(evidence: Mapping[str, Any]) -> dict[str, Any]:
    """Keep only durable identity fields, not the whole phase evidence payload."""
    identity: dict[str, Any] = {}
    for key, value in evidence.items():
        lower = str(key).lower()
        if lower.endswith("sha256") or lower.endswith("_path"):
            if isinstance(value, (str, int, float, bool)) or value is None:
                identity[str(key)] = value
    return identity


def _job_error_reason(job: Mapping[str, Any]) -> str:
    semantic = job.get("semanticResult")
    if isinstance(semantic, Mapping) and str(semantic.get("error") or "").strip():
        return str(semantic["error"]).strip()
    if str(job.get("semanticError") or "").strip():
        return str(job["semanticError"]).strip()
    return (
        f"durable execution failed: process={job.get('processOutcome')} "
        f"semantic={job.get('semanticOutcome')} exit={job.get('exitCode')}"
    )


def _decorate_job(job: Mapping[str, Any], envelope: Mapping[str, Any]) -> dict[str, Any]:
    execution_outcome = str(
        envelope.get("executionOutcome") or job.get("executionOutcome") or "pending"
    )
    status = str(job.get("status") or "pending")
    if execution_outcome in {"failed", "interrupted"}:
        status = execution_outcome
    return {
        **dict(job),
        "status": status,
        "processOutcome": envelope.get("processOutcome", job.get("processOutcome")),
        "semanticOutcome": envelope.get("semanticOutcome", job.get("semanticOutcome")),
        "executionOutcome": execution_outcome,
        "reportingOutcome": envelope.get("reportingOutcome", job.get("reportingOutcome")),
        "phaseAttempt": envelope["phaseAttempt"],
        "executionEnvelopePath": envelope["path"],
        "executionEnvelope": dict(envelope),
    }


def load_execution_envelope(
    project_id: str,
    job_id: str,
    *,
    pipeline_dir: Path | None = None,
) -> dict[str, Any]:
    state = workflow.load_workflow_state(project_id, pipeline_dir=pipeline_dir)
    return _read_json(_envelope_path(state, job_id))


def _persist_job_causal_span(
    project_id: str,
    envelope: Mapping[str, Any],
    job: Mapping[str, Any],
    *,
    pipeline_dir: Path | None,
    reconciled_at: datetime | None = None,
) -> None:
    state = workflow.load_workflow_state(project_id, pipeline_dir=pipeline_dir)
    if not isinstance(state.get("causal_telemetry"), Mapping):
        return
    phase = str(envelope["phase"])
    attempt = int(envelope["phaseAttempt"])
    job_id = str(envelope["jobId"])
    started = (
        job.get("startedAt")
        or job.get("createdAt")
        or envelope.get("startedAt")
    )
    if not started:
        return
    terminal = str(envelope.get("executionOutcome") or job.get("executionOutcome") or "")
    finished = job.get("finishedAt") if terminal in {"succeeded", "failed", "interrupted"} else None
    category = str(envelope.get("telemetryCategory") or "machine_local_execution")
    # Durable jobs may legitimately overlap: the kernel serializes only media
    # phases (see start_phase_job), so one attempt can run more than one non-media
    # job, and a job is not reconciled until the terminal awaiting_human seam, so
    # its reconciliation-lag span runs from finishedAt to terminal observation and
    # legitimately crosses later phases' windows. Declaring one shared concurrency
    # group for the whole durable-job family lets causal accounting dedupe that
    # genuine overlap (surfaced as explicit_concurrency_seconds) instead of failing
    # the second job's telemetry with "overlap requires an explicit shared
    # concurrency_group". Do not narrow this to a per-phase/attempt key — deferred
    # reconciliation makes cross-phase overlap reachable — and do not drop it: an
    # empty group makes overlapping jobs unaccountable. The spans still carry
    # phase/attempt/job_id in their fields, so no identity is lost.
    job_concurrency_group = "durable_jobs"
    record_causal_interval(
        state,
        span_id=f"job:{job_id}",
        name=f"durable job {job_id}",
        category=category,
        started_at=str(started),
        finished_at=(str(finished) if finished else None),
        parent_span_id=causal_phase_span_id(phase, attempt),
        outcome=(terminal if finished else "running"),
        kind="durable_job",
        count_toward_wall=True,
        concurrency_group=job_concurrency_group,
        fields={"job_id": job_id, "phase": phase, "attempt": attempt},
    )
    if finished:
        reconcile_span_prefix = f"reconcile:{job_id}"
        trace = state.get("causal_telemetry") or {}
        spans = list(trace.get("spans") or []) if isinstance(trace, Mapping) else []
        already_recorded = any(
            isinstance(item, Mapping)
            and (
                str(item.get("span_id") or "") == reconcile_span_prefix
                or str(item.get("span_id") or "").startswith(reconcile_span_prefix + ":")
            )
            for item in spans
        )
        finished_time = _parse_time(finished)
        observed = reconciled_at or datetime.now(timezone.utc)
        if not already_recorded and finished_time is not None and observed > finished_time:
            gaps = _uncovered_reconciliation_intervals(finished_time, observed, spans)
            for index, (gap_start, gap_end) in enumerate(gaps, 1):
                span_id = (
                    reconcile_span_prefix
                    if index == 1
                    else f"{reconcile_span_prefix}:{index}"
                )
                record_causal_interval(
                    state,
                    span_id=span_id,
                    name=f"reconcile durable job {job_id}",
                    category="accounting_reconciliation",
                    started_at=gap_start,
                    finished_at=gap_end,
                    parent_span_id=causal_phase_span_id(phase, attempt),
                    outcome="succeeded",
                    kind="reconciliation",
                    count_toward_wall=True,
                    concurrency_group=job_concurrency_group,
                    fields={
                        "job_id": job_id,
                        "phase": phase,
                        "attempt": attempt,
                        "lag_segment_index": index,
                        "lag_segment_count": len(gaps),
                        "observed_at": observed.isoformat(),
                    },
                )
    workflow._write_state(_project_root(state), state)


def _reconcile_job_telemetry(
    project_id: str,
    envelope: dict[str, Any],
    job: Mapping[str, Any],
    *,
    pipeline_dir: Path | None,
    reconciled_at: datetime | None = None,
) -> bool:
    """Persist causal reporting without allowing it to rewrite execution truth."""
    try:
        _persist_job_causal_span(
            project_id,
            envelope,
            job,
            pipeline_dir=pipeline_dir,
            reconciled_at=reconciled_at,
        )
    except Exception as exc:
        envelope["telemetryOutcome"] = "failed"
        envelope["telemetryError"] = str(exc)
        envelope["updatedAt"] = _now()
        return False
    envelope["telemetryOutcome"] = "succeeded"
    envelope.pop("telemetryError", None)
    envelope["updatedAt"] = _now()
    return True


def _persist_transition_causal_span(
    project_id: str,
    envelope: Mapping[str, Any],
    *,
    pipeline_dir: Path | None,
    outcome: str,
    finished_at: datetime | None = None,
) -> None:
    state = workflow.load_workflow_state(project_id, pipeline_dir=pipeline_dir)
    trace = state.get("causal_telemetry")
    if not isinstance(trace, Mapping):
        return
    spans = [
        dict(item)
        for item in list(trace.get("spans") or [])
        if isinstance(item, Mapping)
    ]
    job_id = str(envelope["jobId"])
    phase = str(envelope["phase"])
    phase_attempt = int(envelope["phaseAttempt"])
    transition_attempt = int(envelope.get("workflowTransitionAttempts") or 0) + 1
    transition_span_id = f"transition:{job_id}:{transition_attempt}"
    current = next(
        (item for item in spans if item.get("span_id") == transition_span_id),
        None,
    )
    if current and current.get("started_at"):
        start_value = current["started_at"]
    elif transition_attempt > 1:
        # A retry is a new accounting operation. Starting it at the prior failed
        # transition would falsely claim any intervening repair/editorial work and
        # can overlap a prospectively measured explicit-work span.
        start_value = _now()
    else:
        reconcile_prefix = f"reconcile:{job_id}"
        reconcile = max(
            (
                item
                for item in spans
                if (
                    str(item.get("span_id") or "") == reconcile_prefix
                    or str(item.get("span_id") or "").startswith(reconcile_prefix + ":")
                )
                and item.get("finished_at")
            ),
            key=lambda item: _parse_time(item.get("finished_at"))
            or datetime.min.replace(tzinfo=timezone.utc),
            default=None,
        )
        job_span = next(
            (item for item in spans if item.get("span_id") == f"job:{job_id}"),
            None,
        )
        start_value = (
            (reconcile or {}).get("finished_at")
            or (job_span or {}).get("finished_at")
            or envelope.get("updatedAt")
            or _now()
        )
        # The durable job may finish before required editorial/checkpoint work.
        # A first commit transition begins after the latest completed countable
        # interval in this phase; it must not claim that intervening work.
        completed_boundaries = [
            item.get("finished_at")
            for item in spans
            if item.get("count_toward_wall")
            and item.get("finished_at")
            and item.get("parent_span_id") == causal_phase_span_id(phase, phase_attempt)
        ]
        if completed_boundaries:
            start_value = max(
                [start_value, *completed_boundaries],
                key=lambda value: _parse_time(value)
                or datetime.min.replace(tzinfo=timezone.utc),
            )
    start = _parse_time(start_value) or datetime.now(timezone.utc)
    end = None if outcome == "running" and finished_at is None else (finished_at or datetime.now(timezone.utc))
    if end is not None and end < start:
        end = start
    record_causal_interval(
        state,
        span_id=transition_span_id,
        name=f"workflow transition {job_id} attempt {transition_attempt}",
        category="accounting_reconciliation",
        started_at=start,
        finished_at=end,
        parent_span_id=causal_phase_span_id(phase, phase_attempt),
        outcome=outcome,
        kind="workflow_transition",
        count_toward_wall=True,
        fields={
            "job_id": job_id,
            "phase": phase,
            "attempt": phase_attempt,
            "transition_attempt": transition_attempt,
        },
    )
    workflow._write_state(_project_root(state), state)


def _start_phase_job_unlocked(
    project_id: str,
    *,
    job_id: str,
    phase: str,
    argv: Sequence[str],
    idempotence_key: str,
    telemetry_category: str = "machine_local_execution",
    pipeline_dir: Path | None = None,
    launch: bool = True,
    owns_transition: bool = True,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Bind one current workflow attempt to one durable execution exactly once."""
    telemetry_category = str(telemetry_category).strip()
    if telemetry_category not in CAUSAL_CATEGORIES or telemetry_category == "workflow_wall":
        raise PersianRunKernelError(
            f"unsupported production telemetry category: {telemetry_category!r}"
        )
    state = workflow.load_workflow_state(project_id, pipeline_dir=pipeline_dir)
    path = _envelope_path(state, job_id)
    if path.is_file():
        envelope = _read_json(path)
        if str(envelope.get("phase")) != phase:
            raise PersianRunKernelError(
                f"job {job_id!r} is already bound to phase {envelope.get('phase')!r}"
            )
        if str(envelope.get("idempotenceKey")) != idempotence_key:
            raise PersianRunKernelError(
                f"job {job_id!r} is already bound to a different idempotence key"
            )
        recorded_category = str(envelope.get("telemetryCategory") or "machine_local_execution")
        if recorded_category != telemetry_category:
            raise PersianRunKernelError(
                f"job {job_id!r} is already bound to telemetry category {recorded_category!r}"
            )
        recorded_mode = str(envelope.get("transitionMode") or "workflow")
        requested_mode = "workflow" if owns_transition else "measured_only"
        if recorded_mode != requested_mode:
            raise PersianRunKernelError(
                f"job {job_id!r} is already bound to transition mode {recorded_mode!r}"
            )
        requested_command_sha = durable_command_sha256(argv)
        recorded_command_sha = str(envelope.get("commandSha256") or "")
        if recorded_command_sha and recorded_command_sha != requested_command_sha:
            raise PersianRunKernelError(
                f"job {job_id!r} is already bound to a different command"
            )
        return reconcile_phase_job(project_id, job_id, pipeline_dir=pipeline_dir)

    if phase != state.get("next_phase"):
        raise PersianRunKernelError(
            f"cannot start {phase!r}; next phase is {state.get('next_phase')!r}"
        )
    state = _enforce_new_execution_budget(
        state,
        project_id=project_id,
        phase=phase,
        job_id=job_id,
        argv=argv,
        idempotence_key=idempotence_key,
        telemetry_category=telemetry_category,
        pipeline_dir=pipeline_dir,
        now=now,
    )
    phase_attempt = _open_phase_attempt(state, phase)
    created_attempt = phase_attempt is None
    if created_attempt:
        state = workflow.record_phase_attempt(
            project_id, phase, pipeline_dir=pipeline_dir, now=now
        )
        phase_attempt = int((state.get("attempts") or {})[phase])

    try:
        job = workflow.start_workflow_job(
            project_id,
            job_id=job_id,
            phase=phase,
            argv=argv,
            idempotence_key=idempotence_key,
            pipeline_dir=pipeline_dir,
            launch=launch,
        )
    except Exception as exc:
        if created_attempt:
            try:
                workflow.record_phase_failure(
                    project_id,
                    phase,
                    reason=f"durable job start failed: {exc}",
                    pipeline_dir=pipeline_dir,
                    now=now,
                )
            except Exception:
                pass
        raise

    actual_job_id = str(job.get("jobId") or job_id)
    if actual_job_id != job_id:
        if not created_attempt:
            # The logical operation already exists under this idempotence key. This
            # is the expected recovery path after a caller crash: reconcile the
            # durable identity instead of rerunning externally billed/download work.
            return reconcile_phase_job(
                project_id, actual_job_id, pipeline_dir=pipeline_dir, now=now
            )
        try:
            workflow.record_phase_failure(
                project_id,
                phase,
                reason=(
                    f"idempotence key belongs to durable job {actual_job_id!r}; "
                    f"reuse that job id instead of {job_id!r}"
                ),
                pipeline_dir=pipeline_dir,
                now=now,
            )
        except Exception:
            pass
        raise PersianRunKernelError(
            f"idempotence key belongs to existing durable job {actual_job_id!r}; reuse that job id"
        )

    trace = state.get("causal_telemetry")
    trace_id = str(trace.get("trace_id")) if isinstance(trace, Mapping) and trace.get("trace_id") else None
    parent_span_id = causal_phase_span_id(phase, int(phase_attempt))
    envelope = {
        "version": _ENVELOPE_VERSION,
        "path": str(path),
        "projectId": project_id,
        "phase": phase,
        "phaseAttempt": int(phase_attempt),
        "revisionCycle": int(state.get("user_revision_cycles") or 0),
        "jobId": actual_job_id,
        "traceId": trace_id,
        "causalSpanId": f"job:{actual_job_id}",
        "parentSpanId": parent_span_id,
        "idempotenceKey": idempotence_key,
        "commandSha256": str(job.get("commandSha256") or durable_command_sha256(argv)),
        "telemetryCategory": telemetry_category,
        "telemetryOutcome": "pending",
        "durableStatus": job.get("status"),
        "processOutcome": job.get("processOutcome", "pending"),
        "semanticOutcome": job.get("semanticOutcome", "pending"),
        "executionOutcome": job.get("executionOutcome", "pending"),
        "reportingOutcome": job.get("reportingOutcome", "pending"),
        "artifactOutcome": "pending",
        "artifactIdentity": {},
        "checkpointOutcome": "pending",
        # A measured-only job is bound to the phase attempt and owns its own causal
        # span, but it does not own the workflow transition: the phase still advances
        # through the front door's own completion (#188).
        "transitionMode": "workflow" if owns_transition else "measured_only",
        "workflowTransitionOutcome": "pending",
        "workflowTransitionAttempts": 0,
        "nextPhase": phase,
        "durableResultPath": job.get("resultPath"),
        "semanticResultPath": job.get("semanticResultPath"),
        "startedAt": job.get("startedAt") or job.get("createdAt") or _now(),
        "updatedAt": _now(),
    }
    _atomic_json(path, envelope)
    _reconcile_job_telemetry(
        project_id, envelope, job, pipeline_dir=pipeline_dir, reconciled_at=now
    )
    _atomic_json(path, envelope)
    return _decorate_job(job, envelope)



def start_phase_job(
    project_id: str,
    *,
    job_id: str,
    phase: str,
    argv: Sequence[str],
    idempotence_key: str,
    telemetry_category: str = "machine_local_execution",
    pipeline_dir: Path | None = None,
    launch: bool = True,
    owns_transition: bool = True,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Start one durable phase job with race-safe media execution admission."""
    state = workflow.load_workflow_state(project_id, pipeline_dir=pipeline_dir)
    guard = _media_start_serialization(state, phase) if phase in MEDIA_EXECUTION_PHASES else nullcontext()
    with guard:
        refreshed = workflow.load_workflow_state(project_id, pipeline_dir=pipeline_dir)
        existing_path = _envelope_path(refreshed, job_id)
        if phase in MEDIA_EXECUTION_PHASES and not existing_path.is_file():
            _assert_media_execution_slot(
                project_id,
                job_id,
                requested_idempotence_key=idempotence_key,
                pipeline_dir=pipeline_dir,
            )
        return _start_phase_job_unlocked(
            project_id,
            job_id=job_id,
            phase=phase,
            argv=argv,
            idempotence_key=idempotence_key,
            telemetry_category=telemetry_category,
            pipeline_dir=pipeline_dir,
            launch=launch,
            owns_transition=owns_transition,
            now=now,
        )


def _close_failed_attempt_if_current(
    project_id: str,
    envelope: Mapping[str, Any],
    job: Mapping[str, Any],
    *,
    pipeline_dir: Path | None,
    now: datetime | None = None,
) -> None:
    state = workflow.load_workflow_state(project_id, pipeline_dir=pipeline_dir)
    phase = str(envelope["phase"])
    if state.get("next_phase") != phase:
        return
    if _open_phase_attempt(state, phase) != int(envelope["phaseAttempt"]):
        return
    workflow.record_phase_failure(
        project_id,
        phase,
        reason=_job_error_reason(job),
        pipeline_dir=pipeline_dir,
        now=now,
    )


def reconcile_phase_job(
    project_id: str,
    job_id: str,
    *,
    pipeline_dir: Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Reconcile durable execution without inferring workflow completion from exit code."""
    envelope = load_execution_envelope(project_id, job_id, pipeline_dir=pipeline_dir)
    job = workflow.reconcile_workflow_job(project_id, job_id, pipeline_dir=pipeline_dir)
    for key in (
        "status",
        "processOutcome",
        "semanticOutcome",
        "executionOutcome",
        "reportingOutcome",
        "semanticResult",
        "semanticError",
        "exitCode",
        "finishedAt",
    ):
        if key in job:
            envelope[{"status": "durableStatus"}.get(key, key)] = job[key]
    envelope["updatedAt"] = _now()

    effective_job = dict(job)
    if (
        job.get("processOutcome") == "succeeded"
        and job.get("semanticOutcome") == "not_reported"
    ):
        envelope["executionOutcome"] = "failed"
        effective_job["executionOutcome"] = "failed"
        effective_job["semanticError"] = (
            "production run kernel requires a semantic result; "
            "process exit code alone is not success"
        )

    # Durable child timestamps come from the real runtime clock. Keep telemetry
    # reconciliation on that same clock even when tests inject a workflow/budget
    # clock through ``now`` for deterministic phase accounting.
    _reconcile_job_telemetry(
        project_id,
        envelope,
        effective_job,
        pipeline_dir=pipeline_dir,
        reconciled_at=datetime.now(timezone.utc),
    )

    if envelope.get("executionOutcome") in {"failed", "interrupted"}:
        _close_failed_attempt_if_current(
            project_id, envelope, effective_job, pipeline_dir=pipeline_dir, now=now
        )
        envelope["workflowTransitionOutcome"] = "blocked"
        envelope["workflowTransitionError"] = _job_error_reason(effective_job)
    elif envelope.get("transitionMode") == "measured_only":
        # No phase advanced here, and none was meant to: the job contributed a measured
        # span and its semantic result, and the phase still advances through its own
        # completion. Recording the transition as succeeded would claim an advancement
        # that did not happen; leaving it pending would describe a finished job as
        # unresolved (#188).
        envelope["workflowTransitionOutcome"] = "not_applicable"
        envelope.pop("workflowTransitionError", None)

    state = workflow.load_workflow_state(project_id, pipeline_dir=pipeline_dir)
    envelope["nextPhase"] = state.get("next_phase")
    _atomic_json(Path(str(envelope["path"])), envelope)
    return _decorate_job(job, envelope)


def reconcile_terminal_jobs(
    project_id: str, *, pipeline_dir: Path | None = None
) -> None:
    """Settle durable execution/reporting before freezing a presentation summary.

    Historical failed attempts are retained; pending execution or failed reporting
    prevents presentation and remains recoverable through the same job identity.
    """
    state = workflow.load_workflow_state(project_id, pipeline_dir=pipeline_dir)
    for path in sorted((_project_root(state) / ".jobs").glob("*/execution-envelope.json")):
        existing = _read_json(path)
        if existing.get("executionMode") == "inline_fixture":
            if (existing.get("executionOutcome") != "succeeded"
                    or existing.get("telemetryOutcome") != "succeeded"
                    or existing.get("workflowTransitionOutcome") != "succeeded"):
                raise PersianRunKernelError(f"inline fixture job {path.parent.name!r} is incomplete")
            continue
        job = reconcile_phase_job(project_id, path.parent.name, pipeline_dir=pipeline_dir)
        envelope = job["executionEnvelope"]
        if envelope.get("executionOutcome") not in {"succeeded", "failed", "interrupted"}:
            raise PersianRunKernelError(f"durable job {path.parent.name!r} is still pending")
        if envelope.get("telemetryOutcome") != "succeeded":
            raise PersianRunKernelError(
                f"durable job {path.parent.name!r} causal telemetry requires reconciliation: "
                f"{envelope.get('telemetryError', 'not reported')}"
            )
        phase = str(envelope["phase"])
        window_start = _parse_time(state.get("budget_window_started_at") or state.get("created_at"))
        job_start = _parse_time(envelope.get("startedAt"))
        in_current_window = window_start is None or job_start is None or job_start >= window_start
        if (in_current_window and phase in state.get("completed_phases", [])
                and envelope.get("phaseAttempt") == (state.get("attempts") or {}).get(phase)
                and envelope.get("executionOutcome") != "succeeded"):
            raise PersianRunKernelError(
                f"completed phase {phase!r} requires successful semantic execution "
                f"for durable job {path.parent.name!r}"
            )


def _record_commit_failure(
    envelope: dict[str, Any], evidence: Mapping[str, Any], exc: Exception
) -> None:
    identity = _artifact_identity(evidence)
    envelope["artifactIdentity"] = identity
    envelope["artifactOutcome"] = "unvalidated" if identity else "pending"
    envelope["checkpointOutcome"] = (
        "not_committed" if envelope["phase"] in _CHECKPOINTED_PHASES else "not_applicable"
    )
    envelope["workflowTransitionOutcome"] = "failed"
    envelope["workflowTransitionError"] = str(exc)
    envelope["workflowTransitionAttempts"] = int(
        envelope.get("workflowTransitionAttempts") or 0
    ) + 1
    envelope["updatedAt"] = _now()


def _record_commit_success(
    envelope: dict[str, Any], state: Mapping[str, Any]
) -> None:
    phase = str(envelope["phase"])
    all_evidence = state.get("evidence") if isinstance(state.get("evidence"), Mapping) else {}
    evidence = all_evidence.get(phase) if isinstance(all_evidence, Mapping) else {}
    evidence = evidence if isinstance(evidence, Mapping) else {}
    identity = _artifact_identity(evidence)
    envelope["artifactIdentity"] = identity
    envelope["artifactOutcome"] = "validated" if identity else "not_applicable"
    envelope["checkpointOutcome"] = (
        "validated" if phase in _CHECKPOINTED_PHASES else "not_applicable"
    )
    envelope["workflowTransitionOutcome"] = "succeeded"
    envelope.pop("workflowTransitionError", None)
    envelope["workflowTransitionAttempts"] = int(
        envelope.get("workflowTransitionAttempts") or 0
    ) + 1
    envelope["nextPhase"] = state.get("next_phase")
    envelope["committedAt"] = _now()
    envelope["updatedAt"] = envelope["committedAt"]


def commit_phase_job(
    project_id: str,
    job_id: str,
    *,
    evidence: Mapping[str, Any] | None = None,
    pipeline_dir: Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Advance workflow state from one successful durable execution, idempotently."""
    envelope = load_execution_envelope(project_id, job_id, pipeline_dir=pipeline_dir)
    state = workflow.load_workflow_state(project_id, pipeline_dir=pipeline_dir)
    phase = str(envelope["phase"])

    # A measured-only job does not own a workflow transition, so committing one is
    # refused on both the fresh and the already-completed path. Without this the
    # invariant held on `run` but not on `commit`: an operator could advance the phase
    # from a job whose whole purpose is to be measured, and the envelope would then
    # claim `succeeded` where reconcile records `not_applicable` (#188, #193).
    if str(envelope.get("transitionMode") or "workflow") == "measured_only":
        raise PersianRunKernelError(
            f"job {job_id!r} is measured-only and does not own a workflow transition; "
            f"{phase!r} advances through its own completion"
        )

    if envelope.get("workflowTransitionOutcome") == "succeeded":
        return state

    reconcile_phase_job(project_id, job_id, pipeline_dir=pipeline_dir, now=now)
    envelope = load_execution_envelope(project_id, job_id, pipeline_dir=pipeline_dir)
    if envelope.get("executionOutcome") != "succeeded":
        raise PersianRunKernelError(
            "workflow commit requires successful semantic execution; "
            f"process={envelope.get('processOutcome')} semantic={envelope.get('semanticOutcome')}"
        )
    if envelope.get("telemetryOutcome") != "succeeded":
        raise PersianRunKernelError(
            "causal telemetry reporting failed; successful execution is preserved. "
            "Retry reconciliation/commit for the same durable job. "
            f"error={envelope.get('telemetryError')}"
        )

    # Persist the transition span before any workflow state advancement. A telemetry
    # write failure therefore cannot leave canonical workflow state ahead of its trace.
    _persist_transition_causal_span(
        project_id, envelope, pipeline_dir=pipeline_dir, outcome="running"
    )

    if phase in list(state.get("completed_phases") or []):
        _persist_transition_causal_span(
            project_id, envelope, pipeline_dir=pipeline_dir, outcome="succeeded"
        )
        _record_commit_success(envelope, state)
        _atomic_json(Path(str(envelope["path"])), envelope)
        return state

    phase_evidence = dict(evidence or {})
    if phase in MEDIA_EXECUTION_PHASES and evidence is None:
        semantic = envelope.get("semanticResult")
        data = semantic.get("data") if isinstance(semantic, Mapping) else None
        derived = data.get("phase_evidence") if isinstance(data, Mapping) else None
        if not isinstance(derived, Mapping):
            raise PersianRunKernelError(
                "media job result requires phase_evidence when commit evidence is omitted"
            )
        phase_evidence = dict(derived)
    token = _COMMIT_JOB.set(job_id)
    try:
        committed = workflow.complete_phase(
            project_id,
            phase,
            evidence=phase_evidence,
            pipeline_dir=pipeline_dir,
            now=now,
        )
    except Exception as exc:
        _persist_transition_causal_span(
            project_id, envelope, pipeline_dir=pipeline_dir, outcome="failed"
        )
        _record_commit_failure(envelope, phase_evidence, exc)
        _atomic_json(Path(str(envelope["path"])), envelope)
        raise
    finally:
        _COMMIT_JOB.reset(token)

    _persist_transition_causal_span(
        project_id, envelope, pipeline_dir=pipeline_dir, outcome="succeeded"
    )
    _record_commit_success(envelope, committed)
    _atomic_json(Path(str(envelope["path"])), envelope)
    return committed


def run_inline_fixture_media_phase(
    project_id: str,
    *,
    phase: str,
    job_id: str,
    operation: Callable[[], Mapping[str, Any]],
    output_path: Path,
    evidence_from_data: Callable[[Mapping[str, Any]], Mapping[str, Any]],
    pipeline_dir: Path | None = None,
) -> dict[str, Any]:
    """Measure the synthetic local fixture harness's in-process media operations.

    Production calls use the durable `run` command. This adapter is solely for the
    repository's monkeypatchable local E2E fixture. It persists execution truth
    before committing, so a failed phase commit never repeats successful media.
    """
    from hashlib import sha256

    if phase not in MEDIA_EXECUTION_PHASES:
        raise PersianRunKernelError("inline fixture execution is limited to media phases")
    state = workflow.load_workflow_state(project_id, pipeline_dir=pipeline_dir)
    if state.get("next_phase") != phase:
        raise PersianRunKernelError(f"cannot execute {phase!r}; next phase is {state.get('next_phase')!r}")
    path = _envelope_path(state, job_id)
    if path.exists():
        envelope = _read_json(path)
        if envelope.get("phase") != phase or envelope.get("executionMode") != "inline_fixture":
            raise PersianRunKernelError("fixture job identity is already bound elsewhere")
        if envelope.get("executionOutcome") != "succeeded":
            raise PersianRunKernelError("prior fixture execution did not succeed")
        result = envelope["semanticResult"]
        operation_data = result["operationData"]
    else:
        state = workflow.record_phase_attempt(project_id, phase, pipeline_dir=pipeline_dir)
        attempt = (state.get("attempts") or {})[phase]
        started = datetime.now(timezone.utc)
        envelope = {
            "version": _ENVELOPE_VERSION, "path": str(path), "projectId": project_id,
            "phase": phase, "phaseAttempt": attempt,
            "revisionCycle": int(state.get("user_revision_cycles") or 0),
            "jobId": job_id, "executionMode": "inline_fixture", "startedAt": started.isoformat(),
            "executionOutcome": "running", "telemetryOutcome": "pending",
            "workflowTransitionOutcome": "pending", "workflowTransitionAttempts": 0,
        }
        _atomic_json(path, envelope)
        try:
            raw = dict(operation())
            if raw.get("success") is not True:
                raise PersianRunKernelError(str(raw.get("error") or "fixture media operation failed"))
            operation_data = dict(raw.get("data") or {})
            actual_path = workflow._project_file(state, output_path, label="fixture media output")
            digest = sha256(actual_path.read_bytes()).hexdigest()
        except Exception as exc:
            envelope["executionOutcome"] = "failed"
            envelope["semanticResult"] = {"success": False, "error": str(exc)}
            _atomic_json(path, envelope)
            workflow.record_phase_failure(project_id, phase, reason=str(exc), pipeline_dir=pipeline_dir)
            raise
        finished = datetime.now(timezone.utc)
        if finished < started:
            finished = started
        envelope["executionOutcome"] = "succeeded"
        envelope["semanticResult"] = {
            "success": True,
            "data": {"output_path": str(actual_path), "output_sha256": digest},
            "operationData": operation_data,
        }
        _atomic_json(path, envelope)
        state = workflow.load_workflow_state(project_id, pipeline_dir=pipeline_dir)
        record_causal_interval(
            state, span_id=f"job:{job_id}", name=f"fixture execution {phase}",
            category="browser_render_execution" if phase != "master_final_candidate" else "machine_local_execution",
            started_at=started, finished_at=finished,
            parent_span_id=causal_phase_span_id(phase, attempt),
            outcome="succeeded", kind="durable_job", count_toward_wall=True,
            fields={"job_id": job_id, "phase": phase, "attempt": attempt},
        )
        workflow._write_state(_project_root(state), state)
        envelope["telemetryOutcome"] = "succeeded"
        _atomic_json(path, envelope)
    evidence = dict(evidence_from_data(operation_data))
    token = _COMMIT_JOB.set(job_id)
    try:
        committed = workflow.complete_phase(project_id, phase, evidence=evidence,
                                            pipeline_dir=pipeline_dir)
    finally:
        _COMMIT_JOB.reset(token)
    _record_commit_success(envelope, committed)
    _atomic_json(path, envelope)
    return operation_data

def run_phase_job(
    project_id: str,
    *,
    job_id: str,
    phase: str,
    argv: Sequence[str],
    idempotence_key: str,
    telemetry_category: str = "machine_local_execution",
    evidence: Mapping[str, Any] | None = None,
    pipeline_dir: Path | None = None,
    poll_interval_seconds: float = 0.5,
    timeout_seconds: float = 1800.0,
    owns_transition: bool = True,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Run one durable phase to terminal state and commit it without caller polling.

    With ``owns_transition=False`` the job is measured only: it runs to terminal state
    and is reconciled here, but it does not commit a workflow transition, because the
    phase it belongs to advances through its own completion (#188).

    The durable job remains the source of execution truth. A timeout does not kill
    or replace the job; callers may later reconcile/commit the same identity.
    """
    poll_interval = float(poll_interval_seconds)
    timeout = float(timeout_seconds)
    if poll_interval <= 0:
        raise PersianRunKernelError("poll_interval_seconds must be positive")
    if timeout <= 0:
        raise PersianRunKernelError("timeout_seconds must be positive")

    result = start_phase_job(
        project_id,
        job_id=job_id,
        phase=phase,
        argv=argv,
        idempotence_key=idempotence_key,
        telemetry_category=telemetry_category,
        pipeline_dir=pipeline_dir,
        owns_transition=owns_transition,
        now=now,
    )
    _enforce_execution_checkpoint(
        project_id, operation="run-kernel:after-start", phase=phase, job_id=job_id,
        pipeline_dir=pipeline_dir,
        now=now,
    )
    deadline = time.monotonic() + timeout
    while str(result.get("executionOutcome") or "pending") not in {
        "succeeded", "failed", "interrupted"
    }:
        _enforce_execution_checkpoint(
            project_id, operation="run-kernel:wait", phase=phase, job_id=job_id,
            pipeline_dir=pipeline_dir,
            now=now,
        )
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise PersianRunKernelError(
                f"durable job {job_id!r} is still running after {timeout:.3f}s; "
                "the job was preserved. Retry status/commit with the same identity."
            )
        time.sleep(min(poll_interval, remaining))
        result = reconcile_phase_job(
            project_id, job_id, pipeline_dir=pipeline_dir, now=now
        )
        _enforce_execution_checkpoint(
            project_id, operation="run-kernel:after-reconcile", phase=phase, job_id=job_id,
            pipeline_dir=pipeline_dir,
            now=now,
        )

    outcome = str(result.get("executionOutcome") or "pending")
    if outcome != "succeeded":
        raise PersianRunKernelError(
            f"durable job {job_id!r} finished with execution outcome {outcome!r}; "
            "workflow commit was not attempted"
        )
    if not owns_transition:
        return reconcile_phase_job(
            project_id, job_id, pipeline_dir=pipeline_dir, now=now
        )
    return commit_phase_job(
        project_id,
        job_id,
        evidence=evidence,
        pipeline_dir=pipeline_dir,
        now=now,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="persian-run-kernel")
    sub = parser.add_subparsers(dest="command", required=True)

    start = sub.add_parser("start", help="start one current-phase durable execution")
    start.add_argument("project_id")
    start.add_argument("job_id")
    start.add_argument("--phase", required=True)
    start.add_argument("--idempotence-key", required=True)
    start.add_argument(
        "--telemetry-category",
        default="machine_local_execution",
        choices=sorted(CAUSAL_CATEGORIES - {"workflow_wall"}),
    )
    start.add_argument(
        "--measured-only",
        action="store_true",
        help="measure this execution without letting it own the phase's workflow transition",
    )
    start.add_argument("argv", nargs="+")

    run = sub.add_parser(
        "run", help="start, wait for, reconcile, and commit one current-phase durable execution"
    )
    run.add_argument("project_id")
    run.add_argument("job_id")
    run.add_argument("--phase", required=True)
    run.add_argument("--idempotence-key", required=True)
    run.add_argument(
        "--telemetry-category",
        default="machine_local_execution",
        choices=sorted(CAUSAL_CATEGORIES - {"workflow_wall"}),
    )
    run.add_argument("--evidence-json")
    run.add_argument("--poll-interval-seconds", type=float, default=0.5)
    run.add_argument("--timeout-seconds", type=float, default=1800.0)
    run.add_argument(
        "--measured-only",
        action="store_true",
        help="measure this execution without letting it own the phase's workflow transition",
    )
    run.add_argument("argv", nargs="+")

    status = sub.add_parser("status", help="reconcile one execution envelope")
    status.add_argument("project_id")
    status.add_argument("job_id")

    commit = sub.add_parser("commit", help="commit one successful execution into workflow state")
    commit.add_argument("project_id")
    commit.add_argument("job_id")
    commit.add_argument("--evidence-json")
    return parser


def _read_evidence(path: str | None) -> dict[str, Any]:
    if path is None:
        return {}
    raw = Path(path).expanduser().resolve()
    try:
        payload = json.loads(raw.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PersianRunKernelError(f"could not read evidence JSON: {raw}") from exc
    if not isinstance(payload, dict):
        raise PersianRunKernelError("evidence JSON must contain one object")
    return payload


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "start":
            command = list(args.argv)
            command = command[1:] if command[:1] == ["--"] else command
            result = start_phase_job(
                args.project_id,
                job_id=args.job_id,
                phase=args.phase,
                argv=command,
                idempotence_key=args.idempotence_key,
                telemetry_category=args.telemetry_category,
                owns_transition=not args.measured_only,
            )
        elif args.command == "run":
            command = list(args.argv)
            command = command[1:] if command[:1] == ["--"] else command
            result = run_phase_job(
                args.project_id,
                job_id=args.job_id,
                phase=args.phase,
                argv=command,
                idempotence_key=args.idempotence_key,
                telemetry_category=args.telemetry_category,
                evidence=_read_evidence(args.evidence_json),
                poll_interval_seconds=args.poll_interval_seconds,
                timeout_seconds=args.timeout_seconds,
                owns_transition=not args.measured_only,
            )
        elif args.command == "status":
            result = reconcile_phase_job(args.project_id, args.job_id)
        else:
            result = commit_phase_job(
                args.project_id,
                args.job_id,
                evidence=_read_evidence(args.evidence_json),
            )
    except (PersianRunKernelError, workflow.PersianVideoWorkflowError, OSError, ValueError) as exc:
        parser.error(str(exc))
        return 2
    print(json.dumps(to_json_safe(result), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    # `python -m lib.persian_run_kernel` loads this file twice: once as __main__ and,
    # when the workflow imports it, again as lib.persian_run_kernel. Module-level state
    # exists in both copies -- including _COMMIT_JOB, the ContextVar carrying the
    # in-flight job identity -- so a commit made here would be invisible to the
    # workflow's commit guard and every media phase commit would fail with "must
    # complete through the run kernel" (#169).
    #
    # Delegate to the package instance so exactly one copy does the work.
    import lib.persian_run_kernel as _package_kernel

    raise SystemExit(_package_kernel.main())
