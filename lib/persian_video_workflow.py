"""Deterministic front-door state for Persian video production.

The pipeline director skills still own creative decisions. This module owns the
workflow envelope: fresh-project bootstrap, stage order, read isolation, retry
and download budgets, and the terminal digest-bound awaiting-human transition.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from uuid import uuid4

from backlot.__main__ import cmd_open as open_backlot
from lib.checkpoint import CheckpointValidationError, init_project, read_checkpoint, write_checkpoint
from lib.paths import PROJECTS_DIR, REPO_ROOT
from lib.pipeline_loader import load_pipeline_readonly
from lib.persian_film_type_docs import active_film_type_version, film_type_contract_paths
from lib.persian_editorial_hook import (
    build_initial_hook_selection,
    finalize_automatic_hook_selection,
    validate_user_hook_unchanged,
    validate_edit_hook_authority,
)
from lib.persian_durable_job import DurableJobError, reconcile_job, start_job
from lib.persian_alignment_provider import (
    AlignmentProviderError,
    build_alignment_provider_plan,
    validate_alignment_provider_decision,
)
from lib.persian_asset_workspace import (
    PersianAssetWorkspaceError,
    asset_workspace_status,
    record_candidate_review,
    record_discovery_pass,
    reject_asset_candidate,
    select_asset_candidate,
    stage_asset_candidate,
    validate_asset_manifest_against_workspace,
)
from lib.persian_edit_workspace import (
    PersianEditWorkspaceError, artifact_sha256, compare_edit_candidates, convergence_status,
    load_promotable_edit_draft, mark_blocked_convergence_exhausted, preflight_edit_draft,
    promote_edit_draft, stage_edit_draft,
)
from lib.persian_rendered_review import (
    HOOK_RENDER_REVIEW_VERSIONS,
    PersianRenderedReviewError,
    validate_rendered_audio_review,
    validate_rendered_hook_review,
    validate_cold_viewer_review_input,
)
from lib.persian_hook_quality import resolve_hook_timing_authority
from lib.persian_workflow_telemetry import (
    backfill_phase_residual_spans,
    causal_phase_span_id,
    causal_time_accounting,
    finish_causal_span,
    finish_phase_attempt_span,
    new_causal_trace,
    record_causal_interval,
    record_human_idle_and_reopen_run,
    record_phase_attempt_span,
    reconcile_phase_telemetry,
)
from lib.persian_quality_evidence import compose_quality_evidence
from lib.persian_recovery_policy import recovery_policy_for_issue
from schemas.artifacts import validate_artifact
from jsonschema.exceptions import ValidationError

WORKFLOW_VERSION = "2.0"
STATE_FILENAME = "persian-video-workflow.json"
PHASE_SLO_SECONDS = {
    "align_script_timing": 8 * 60,
    "plan_scenes_moments": 5 * 60,
    "acquire_assets": 10 * 60,
    "no_copy_preflight": 5 * 60,
    "render_opening_candidate": 4 * 60,
    "opening_review": 3 * 60,
    "render_final_candidate": 15 * 60,
    "master_final_candidate": 5 * 60,
    "final_review": 3 * 60,
}
END_TO_END_SLO_SECONDS = 45 * 60

PHASES = (
    "validate_input",
    "create_project",
    "open_backlot",
    "prepare_inputs",
    "align_script_timing",
    "plan_scenes_moments",
    "acquire_assets",
    "review_subject_regions",
    "no_copy_preflight",
    "render_opening_candidate",
    "opening_review",
    "render_final_candidate",
    "master_final_candidate",
    "final_review",
    "awaiting_human",
)

# A workflow phase may only be considered durable once the corresponding
# canonical checkpoint exists. These mappings reconcile the lightweight front
# door with the project checkpoint protocol without fabricating state.
_PHASE_CHECKPOINT = {
    "align_script_timing": "script",
    "plan_scenes_moments": "scene_plan",
    "acquire_assets": "assets",
    "no_copy_preflight": "edit",
}
_REWIND_INVALIDATES = {
    "prepare_inputs": ("script", "scene_plan", "assets", "edit", "compose"),
    "align_script_timing": ("script", "scene_plan", "assets", "edit", "compose"),
    "plan_scenes_moments": ("scene_plan", "assets", "edit", "compose"),
    "acquire_assets": ("assets", "edit", "compose"),
    "review_subject_regions": ("edit", "compose"),
    "no_copy_preflight": ("edit", "compose"),
    "render_opening_candidate": ("compose",),
    "opening_review": ("compose",),
    "render_final_candidate": ("compose",),
    "master_final_candidate": ("compose",),
    "final_review": ("compose",),
}

_PROJECT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,79}$")


class PersianVideoWorkflowError(ValueError):
    """Raised when the front-door workflow contract would be violated."""


@dataclass(frozen=True)
class WorkflowBudgets:
    max_revisions_per_stage: int
    max_send_backs: int
    max_wall_time_minutes: int
    asset_retry_passes: int = 1
    clips_per_query: int = 1
    max_candidates_total: int = 16
    max_bytes_per_clip: int = 96 * 1024 * 1024
    max_total_download_bytes: int = 512 * 1024 * 1024


def get_workflow_budgets() -> WorkflowBudgets:
    """Resolve the orchestration envelope from the canonical manifest."""
    manifest = load_pipeline_readonly("persian-footage")
    orchestration = manifest.get("orchestration") or {}
    try:
        return WorkflowBudgets(
            max_revisions_per_stage=int(orchestration["max_revisions_per_stage"]),
            max_send_backs=int(orchestration["max_send_backs"]),
            max_wall_time_minutes=int(orchestration["max_wall_time_minutes"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise PersianVideoWorkflowError(
            "persian-footage orchestration limits are missing or invalid"
        ) from exc


def asset_search_policy() -> dict[str, Any]:
    """Return the only automatic stock-search budget for this workflow."""
    budget = get_workflow_budgets()
    return {
        "sources": ["pexels", "pixabay_video"],
        "clips_per_query": budget.clips_per_query,
        "max_candidates_total": budget.max_candidates_total,
        "max_bytes_per_clip": budget.max_bytes_per_clip,
        "max_total_download_bytes": budget.max_total_download_bytes,
        "max_retry_passes": budget.asset_retry_passes,
    }


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _slug(text: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return value[:40] or "persian-video"


def new_project_id(
    title: str,
    *,
    now: datetime | None = None,
    token: str | None = None,
) -> str:
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%d-%H%M%S")
    suffix = (token or uuid4().hex[:8]).lower()
    return f"{_slug(title)}-{stamp}-{suffix}"


def _validate_project_id(project_id: str) -> None:
    if not _PROJECT_ID_RE.fullmatch(project_id):
        raise PersianVideoWorkflowError(
            "project_id must be 2-80 lowercase ASCII letters/digits plus ._-"
        )


def _validate_narration_source(path_value: str) -> dict[str, Any]:
    path = Path(path_value).expanduser().resolve()
    if not path.is_file():
        raise PersianVideoWorkflowError(f"narration file does not exist: {path}")
    return {
        "original_source_path": str(path),
        "sha256": _hash_file(path),
    }


def _validate_approved_script(text_value: str) -> dict[str, Any]:
    text = str(text_value)
    if not text.strip():
        raise PersianVideoWorkflowError("approved script must not be empty")
    return {"text": text, "sha256": _hash_text(text)}


def _production_input_mode(*, has_script: bool, has_narration: bool) -> str:
    if has_script and has_narration:
        return "approved_script_with_narration"
    if has_script:
        return "approved_script_only"
    if has_narration:
        return "narration_only"
    raise PersianVideoWorkflowError(
        "Persian video production requires an approved Persian script and/or narration audio"
    )


_EXTERNAL_DURABLE_PHASES = frozenset({
    "acquire_assets", "render_opening_candidate", "render_final_candidate", "master_final_candidate"
})


def alignment_execution_policy(state: Mapping[str, Any]) -> dict[str, Any]:
    """Choose the lightest adequate alignment path from script authority."""
    input_record = state.get("input") if isinstance(state.get("input"), Mapping) else {}
    authority = str(input_record.get("script_authority") or "spoken_narration")
    if authority == "approved_script":
        return {
            "mode": "timing_oriented",
            "scriptAuthority": "approved_script",
            "primaryModelClass": "smallest_adequate_word_timing",
            "heavyTranscriptionRecoveryOnly": True,
        }
    return {
        "mode": "transcription_oriented",
        "scriptAuthority": authority,
        "primaryModelClass": "speech_transcription",
        "heavyTranscriptionRecoveryOnly": False,
    }


def alignment_provider_plan_for_project(
    project_id: str, *, pipeline_dir: Path | None = None, registry=None
) -> dict[str, Any]:
    """Probe live provider capability/availability for the current workflow policy."""
    state = load_workflow_state(project_id, pipeline_dir=pipeline_dir)
    policy = state.get("alignment_policy") or alignment_execution_policy(state)
    try:
        if registry is None:
            return build_alignment_provider_plan(policy)
        return build_alignment_provider_plan(policy, registry=registry)
    except AlignmentProviderError as exc:
        raise PersianVideoWorkflowError(str(exc)) from exc


def _validate_alignment_completion(
    state: Mapping[str, Any], evidence: Mapping[str, Any]
) -> dict[str, Any]:
    """Require durable provider-selection truth before alignment can advance."""
    policy = state.get("alignment_policy") or alignment_execution_policy(state)
    decision = evidence.get("provider_decision")
    if not isinstance(decision, Mapping):
        raise PersianVideoWorkflowError(
            "align_script_timing completion requires a persisted provider decision"
        )
    try:
        validate_alignment_provider_decision(decision, policy)
    except AlignmentProviderError as exc:
        raise PersianVideoWorkflowError(
            f"alignment provider decision is invalid: {exc}"
        ) from exc
    count = evidence.get("word_timing_count")
    if not isinstance(count, int) or isinstance(count, bool) or count <= 0:
        raise PersianVideoWorkflowError(
            "align_script_timing completion requires positive word_timing_count"
        )
    mode = str(evidence.get("alignment_mode") or decision.get("mode") or "")
    if mode != str(policy.get("mode") or ""):
        raise PersianVideoWorkflowError(
            "alignment_mode does not match the workflow alignment policy"
        )
    selected_provider = str(decision.get("selectedProvider") or "")
    selected_tool = str(decision.get("selectedTool") or "")
    selected_model = str(decision.get("selectedModel") or "")
    if str(evidence.get("provider") or selected_provider) != selected_provider:
        raise PersianVideoWorkflowError(
            "alignment completion provider does not match provider decision"
        )
    if str(evidence.get("model") or selected_model) != selected_model:
        raise PersianVideoWorkflowError(
            "alignment completion model does not match provider decision"
        )
    normalized = {
        "alignment_mode": mode,
        "provider": selected_provider,
        "provider_tool": selected_tool,
        "model": selected_model,
        "provider_execution_seconds": float(decision.get("executionDurationSeconds") or 0.0),
        "word_timing_count": count,
        "heavy_recovery_used": bool(decision.get("heavyRecoveryUsed")),
        "provider_fallback_reason": decision.get("fallbackReason"),
        "provider_decision": dict(decision),
    }
    for key in (
        "alignment_result_path", "alignment_result_sha256",
        "provider_plan_path", "provider_plan_sha256",
    ):
        value = evidence.get(key)
        if value is not None:
            normalized[key] = value
    return normalized


def start_alignment_job_for_project(
    project_id: str, *, pipeline_dir: Path | None = None, job_id: str | None = None
) -> dict[str, Any]:
    """Start the canonical durable alignment job after provider availability probing."""
    from lib.persian_alignment_job import AlignmentJobError, start_alignment_job
    try:
        return start_alignment_job(
            project_id, pipeline_dir=pipeline_dir, job_id=job_id, launch=True
        )
    except AlignmentJobError as exc:
        raise PersianVideoWorkflowError(str(exc)) from exc


def alignment_job_status_for_project(
    project_id: str, job_id: str, *, pipeline_dir: Path | None = None
) -> dict[str, Any]:
    from lib.persian_alignment_job import AlignmentJobError, reconcile_alignment_job
    try:
        return reconcile_alignment_job(project_id, job_id, pipeline_dir=pipeline_dir)
    except AlignmentJobError as exc:
        raise PersianVideoWorkflowError(str(exc)) from exc


def commit_alignment_job_for_project(
    project_id: str, job_id: str, *, pipeline_dir: Path | None = None
) -> dict[str, Any]:
    from lib.persian_alignment_job import AlignmentJobError, commit_alignment_job
    try:
        return commit_alignment_job(project_id, job_id, pipeline_dir=pipeline_dir)
    except AlignmentJobError as exc:
        raise PersianVideoWorkflowError(str(exc)) from exc


def repair_trivial_zero_length_timings(
    timings: Sequence[Mapping[str, Any]], *, epsilon_seconds: float = 0.08
) -> list[dict[str, Any]]:
    """Repair exact zero-length word timings only when the next boundary proves room.

    This deterministic repair never overlaps the following word and deliberately
    leaves ambiguous/reversed timings untouched so heavy alignment remains a real
    fallback rather than the default response to harmless quantization.
    """
    if epsilon_seconds <= 0:
        raise PersianVideoWorkflowError("epsilon_seconds must be positive")
    repaired = [dict(item) for item in timings]
    for index, item in enumerate(repaired):
        pair = ("start", "end") if "start" in item or "end" in item else ("startSeconds", "endSeconds")
        start_key, end_key = pair
        try:
            start = float(item[start_key]); end = float(item[end_key])
        except (KeyError, TypeError, ValueError):
            continue
        if abs(end - start) > 1e-9:
            continue
        next_start = None
        if index + 1 < len(repaired):
            nxt = repaired[index + 1]
            next_key = "start" if "start" in nxt else "startSeconds"
            try:
                next_start = float(nxt[next_key])
            except (KeyError, TypeError, ValueError):
                next_start = None
        if next_start is None or next_start <= start + 1e-9:
            continue
        item[end_key] = round(min(next_start, start + epsilon_seconds), 6)
    return repaired


def validate_scene_plan_budget(
    scene_plan: Mapping[str, Any], *, max_semantic_candidates: int, rejection_margin: float = 0.25
) -> dict[str, Any]:
    """Reject plans whose mandatory distinct events consume the sourcing safety margin."""
    if max_semantic_candidates <= 0:
        raise PersianVideoWorkflowError("max_semantic_candidates must be positive")
    if not 0 <= rejection_margin < 1:
        raise PersianVideoWorkflowError("rejection_margin must be in [0, 1)")
    beats = scene_plan.get("beats") if isinstance(scene_plan, Mapping) else None
    if not isinstance(beats, list):
        metadata = scene_plan.get("metadata") if isinstance(scene_plan, Mapping) else None
        beats = metadata.get("beats") if isinstance(metadata, Mapping) else []
    event_ids: list[str] = []
    for beat in beats or []:
        if not isinstance(beat, Mapping):
            continue
        for event in beat.get("visual_events") or []:
            if not isinstance(event, Mapping):
                continue
            event_id = str(event.get("id") or "").strip()
            if event_id and event_id not in event_ids:
                event_ids.append(event_id)
    mandatory = len(event_ids)
    allowed = int(max_semantic_candidates * (1.0 - rejection_margin))
    headroom = max_semantic_candidates - mandatory
    if mandatory > allowed:
        raise PersianVideoWorkflowError(
            "scene plan consumes too much semantic candidate budget: "
            f"{mandatory} mandatory distinct events leave only {headroom} candidate(s); "
            f"policy requires at least {max_semantic_candidates - allowed} rejection-margin candidate(s)"
        )
    return {
        "policyVersion": "1.0",
        "mandatoryDistinctEvents": mandatory,
        "maxSemanticCandidates": max_semantic_candidates,
        "semanticCandidateHeadroom": headroom,
        "requiredRejectionMargin": rejection_margin,
        "eventIds": event_ids,
    }


def validate_scene_plan_duration(
    scene_plan: Mapping[str, Any], *, narration_duration_seconds: float, fps: float = 30.0
) -> dict[str, Any]:
    """Bind the scene-plan tail to authoritative narration within one frame."""
    if narration_duration_seconds <= 0 or fps <= 0:
        raise PersianVideoWorkflowError("authoritative narration duration and fps must be positive")
    scenes = scene_plan.get("scenes") if isinstance(scene_plan, Mapping) else None
    if isinstance(scenes, list) and scenes:
        ends: list[float] = []
        for scene in scenes:
            if not isinstance(scene, Mapping):
                raise PersianVideoWorkflowError("scene plan scenes must be objects")
            try:
                ends.append(float(scene["end_seconds"]))
            except (KeyError, TypeError, ValueError) as exc:
                raise PersianVideoWorkflowError("scene plan scene end_seconds must be numeric") from exc
        plan_end = max(ends)
    else:
        beats = scene_plan.get("beats") if isinstance(scene_plan, Mapping) else None
        if not isinstance(beats, list):
            metadata = scene_plan.get("metadata") if isinstance(scene_plan, Mapping) else None
            beats = metadata.get("beats") if isinstance(metadata, Mapping) else None
        if not isinstance(beats, list) or not beats:
            raise PersianVideoWorkflowError(
                "scene plan requires scenes or semantic beats for duration validation"
            )
        durations: list[float] = []
        for beat in beats:
            if not isinstance(beat, Mapping):
                raise PersianVideoWorkflowError("scene plan beats must be objects")
            try:
                duration = float(beat["duration_seconds"])
            except (KeyError, TypeError, ValueError) as exc:
                raise PersianVideoWorkflowError(
                    "scene plan beat duration_seconds must be numeric"
                ) from exc
            if duration <= 0:
                raise PersianVideoWorkflowError(
                    "scene plan beat duration_seconds must be positive"
                )
            durations.append(duration)
        plan_end = sum(durations)
    delta = abs(plan_end - float(narration_duration_seconds))
    tolerance = 1.0 / float(fps)
    if delta > tolerance + 1e-9:
        raise PersianVideoWorkflowError(
            "scene-plan end time does not match authoritative narration duration: "
            f"plan={plan_end:.3f}s narration={narration_duration_seconds:.3f}s "
            f"tolerance={tolerance:.3f}s"
        )
    return {
        "policyVersion": "1.0",
        "scenePlanEndSeconds": round(plan_end, 6),
        "narrationDurationSeconds": round(float(narration_duration_seconds), 6),
        "deltaSeconds": round(delta, 6),
        "frameToleranceSeconds": round(tolerance, 6),
        "withinFrameTolerance": True,
    }


def _execution_class_for_phase(phase: str) -> str:
    return "external_durable" if phase in _EXTERNAL_DURABLE_PHASES else "editorial"


def phase_time_accounting(
    state: Mapping[str, Any],
    *,
    now: datetime | None = None,
    since: datetime | None = None,
    include_open: bool = False,
) -> dict[str, float]:
    """Sum phase telemetry without charging external/durable time as editorial time."""
    current = now or datetime.now(timezone.utc)
    causal = causal_time_accounting(
        state, now=current, since=since, include_open=include_open
    )
    editorial = 0.0
    external = 0.0
    telemetry = state.get("phase_telemetry")
    if not isinstance(telemetry, Mapping):
        telemetry = {}
    for entries in telemetry.values():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, Mapping):
                continue
            try:
                started = _parse_timestamp(str(entry.get("started_at") or ""))
            except PersianVideoWorkflowError:
                continue
            if since is not None and started < since:
                continue
            raw_duration = entry.get("duration_seconds")
            if isinstance(raw_duration, (int, float)) and not isinstance(raw_duration, bool):
                duration = max(0.0, float(raw_duration))
            else:
                finished_raw = str(entry.get("finished_at") or "").strip()
                if finished_raw:
                    try:
                        finished = _parse_timestamp(finished_raw)
                    except PersianVideoWorkflowError:
                        continue
                elif include_open:
                    finished = current
                else:
                    continue
                duration = max(0.0, (finished - started).total_seconds())
            if str(entry.get("execution_class") or "editorial") == "external_durable":
                external += duration
            else:
                editorial += duration
    if causal is not None:
        # Keep legacy phase-class aliases readable for older reports/consumers while
        # causal spans remain authoritative for coverage and category timing.
        causal["active_editorial_seconds"] = round(editorial, 3)
        causal["external_durable_seconds"] = round(external, 3)
        return causal
    accounting_lag = 0.0
    telemetry = state.get("phase_telemetry")
    if isinstance(telemetry, Mapping):
        for entries in telemetry.values():
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if isinstance(entry, Mapping):
                    raw = entry.get("accounting_lag_seconds")
                    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
                        accounting_lag += max(0.0, float(raw))
    total = editorial + external
    if since is not None:
        origin = since
    else:
        created_raw = str(state.get("created_at") or "").strip()
        if created_raw:
            origin = _parse_timestamp(created_raw)
        else:
            # Utility callers may ask only for the metric schema without a durable
            # workflow state. Use the earliest valid phase start when available; an
            # entirely empty synthetic state has zero wall time rather than raising.
            starts: list[datetime] = []
            for entries in telemetry.values():
                if isinstance(entries, list):
                    for entry in entries:
                        if isinstance(entry, Mapping) and str(entry.get("started_at") or "").strip():
                            try:
                                starts.append(_parse_timestamp(str(entry["started_at"])))
                            except PersianVideoWorkflowError:
                                pass
            origin = min(starts) if starts else current
    wall_seconds = max(0.0, (current - origin).total_seconds())
    review_seconds = 0.0
    for phase_name in ("opening_review", "final_review"):
        entries = telemetry.get(phase_name) if isinstance(telemetry, Mapping) else None
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, Mapping):
                continue
            raw = entry.get("duration_seconds")
            if isinstance(raw, (int, float)) and not isinstance(raw, bool):
                review_seconds += max(0.0, float(raw))
    gap = max(0.0, wall_seconds - total)
    return {
        # Issue #32: the number called runtime must match the user's wall clock.
        # Instrumented work remains available separately instead of pretending it
        # covers time between phase attempts or review preparation/accounting gaps.
        "job_runtime_seconds": round(wall_seconds, 3),
        "workflow_wall_seconds": round(wall_seconds, 3),
        "provider_wait_seconds": round(external, 3),
        "accounting_lag_seconds": round(accounting_lag, 3),
        "editorial_wall_seconds": round(editorial, 3),
        "review_phase_seconds": round(review_seconds, 3),
        "orchestration_gap_seconds": round(gap, 3),
        "unattributed_wall_seconds": round(gap, 3),
        # Backward-compatible aliases consumed by older reports/tests.
        "active_editorial_seconds": round(editorial, 3),
        "external_durable_seconds": round(external, 3),
        "total_observed_seconds": round(total, 3),
    }


def _freeze_performance_summary(state: dict[str, Any], *, now: datetime) -> None:
    """Append a reporting revision while retaining earlier acceptance evidence."""
    previous = state.get("performance_summary")
    if isinstance(previous, Mapping):
        state.setdefault("performance_summary_history", []).append(dict(previous))
    accounting = phase_time_accounting(state, now=now)
    window = _parse_timestamp(str(state.get("budget_window_started_at") or state["created_at"]))
    candidate = state.get("approval") or (state.get("evidence") or {}).get("awaiting_human") or {}
    state["performance_summary"] = {
        **accounting,
        "recorded_at": now.isoformat(),
        "status": state.get("status"),
        "candidate_sha256": candidate.get("candidate_sha256"),
        "revision_cycle": int(state.get("user_revision_cycles") or 0),
        "revision_window": phase_time_accounting(state, now=now, since=window),
        "endToEndSloSeconds": END_TO_END_SLO_SECONDS,
        "endToEndSloExceeded": accounting["workflow_wall_seconds"] > END_TO_END_SLO_SECONDS,
        "phaseSloExceeded": {
            name: any(bool(item.get("slo_exceeded")) for item in entries if isinstance(item, Mapping))
            for name, entries in (state.get("phase_telemetry") or {}).items()
            if isinstance(entries, list)
        },
    }


def _finish_phase_telemetry(
    state: dict[str, Any], phase: str, *, outcome: str, now: datetime | None = None
) -> None:
    telemetry = dict(state.get("phase_telemetry") or {})
    entries = list(telemetry.get(phase) or [])
    if not entries or not isinstance(entries[-1], Mapping):
        return
    entry = dict(entries[-1])
    if entry.get("finished_at"):
        return
    finished = now or datetime.now(timezone.utc)
    try:
        started = _parse_timestamp(str(entry.get("started_at") or ""))
    except PersianVideoWorkflowError:
        started = finished
    entry["finished_at"] = finished.isoformat()
    entry["duration_seconds"] = round(max(0.0, (finished - started).total_seconds()), 3)
    entry["outcome"] = outcome
    try:
        attempt_number = int(entry.get("attempt") or 0)
    except (TypeError, ValueError):
        attempt_number = 0
    if attempt_number > 0:
        finish_phase_attempt_span(
            state, phase, attempt_number, finished_at=finished, outcome=outcome
        )
    slo = PHASE_SLO_SECONDS.get(phase)
    if slo is not None:
        entry["slo_seconds"] = slo
        entry["slo_exceeded"] = entry["duration_seconds"] > slo
    entries[-1] = entry
    telemetry[phase] = entries
    state["phase_telemetry"] = telemetry
    if attempt_number > 0:
        backfill_phase_residual_spans(state, phase, attempt_number)


def _state_path(project_dir: Path) -> Path:
    return project_dir / STATE_FILENAME


def _write_state(project_dir: Path, state: Mapping[str, Any]) -> None:
    path = _state_path(project_dir)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(dict(state), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def _repo_read_allowlist(profile_version: str | None = None) -> list[str]:
    paths = [
        (REPO_ROOT / "skills" / "persian-video").resolve(),
        (REPO_ROOT / "skills" / "pipelines" / "persian-footage").resolve(),
        (REPO_ROOT / "skills" / "meta" / "checkpoint-protocol.md").resolve(),
        (REPO_ROOT / "skills" / "meta" / "reviewer.md").resolve(),
        (REPO_ROOT / "pipeline_defs" / "persian-footage.yaml").resolve(),
        (REPO_ROOT / "styles" / "persian-footage").resolve(),
        (REPO_ROOT / "docs" / "reference" / "persian-hooks").resolve(),
        *film_type_contract_paths(profile_version, repo_root=REPO_ROOT),
        (REPO_ROOT / ".agents" / "skills" / "music").resolve(),
        (REPO_ROOT / ".agents" / "skills" / "speech-to-text").resolve(),
        (REPO_ROOT / ".agents" / "skills" / "ffmpeg").resolve(),
        (REPO_ROOT / ".agents" / "skills" / "video-toolkit").resolve(),
    ]
    return list(dict.fromkeys(str(path) for path in paths))


def bootstrap_persian_video(
    *,
    title: str,
    narration_path: str | None = None,
    approved_script: str | None = None,
    hook_text: str | None = None,
    project_id: str | None = None,
    pipeline_dir: Path | None = None,
    backlot_opener: Callable[[str | None], int] = open_backlot,
    now: datetime | None = None,
    id_token: str | None = None,
) -> dict[str, Any]:
    """Create one fresh production project from already-approved Persian inputs."""
    projects_root = (pipeline_dir or PROJECTS_DIR).resolve()
    script_source = _validate_approved_script(approved_script) if approved_script is not None else None
    narration_source = _validate_narration_source(narration_path) if narration_path is not None else None
    mode = _production_input_mode(
        has_script=script_source is not None,
        has_narration=narration_source is not None,
    )
    if narration_source is not None:
        requested_source = Path(narration_source["original_source_path"])
        if _is_within(requested_source, projects_root):
            raise PersianVideoWorkflowError(
                "refusing initial narration input from an existing project directory"
            )

    created_at = now or datetime.now(timezone.utc)
    pid = project_id or new_project_id(title, now=created_at, token=id_token)
    _validate_project_id(pid)
    project_dir = projects_root / pid
    if project_dir.exists():
        raise PersianVideoWorkflowError(
            f"refusing to reuse existing project directory: {project_dir}"
        )

    created = False
    try:
        init_project(pid, title=title, pipeline_type="persian-footage", pipeline_dir=projects_root)
        created = True
        inputs_dir = project_dir / "inputs"
        inputs_dir.mkdir(parents=True, exist_ok=True)
        input_record: dict[str, Any] = {"mode": mode}

        if script_source is not None:
            script_path = inputs_dir / "approved_script.txt"
            script_path.write_text(script_source.pop("text"), encoding="utf-8")
            script_source["source_path"] = str(script_path.resolve())
            input_record["approved_script"] = script_source

        if narration_source is not None:
            original = Path(narration_source["original_source_path"])
            suffix = original.suffix if original.suffix else ".audio"
            narration_copy = inputs_dir / f"narration{suffix}"
            shutil.copy2(original, narration_copy)
            narration_source["source_path"] = str(narration_copy.resolve())
            input_record["narration"] = narration_source

        input_record["script_authority"] = (
            "approved_script" if script_source is not None else "spoken_narration"
        )
        profile_version = active_film_type_version(repo_root=REPO_ROOT)
        state: dict[str, Any] = {
            "version": WORKFLOW_VERSION,
            "film_type_profile_version": profile_version,
            "project_id": pid,
            "pipeline_type": "persian-footage",
            "created_at": created_at.isoformat(),
            "budget_window_started_at": created_at.isoformat(),
            "status": "active",
            "completed_phases": ["validate_input", "create_project"],
            "next_phase": "open_backlot",
            "input": input_record,
            "hook_selection": build_initial_hook_selection(hook_text),
            "budgets": asdict(get_workflow_budgets()),
            "attempts": {},
            "send_backs": 0,
            "recovery_attempts": {},
            "phase_telemetry": {},
            "causal_telemetry": new_causal_trace(uuid4().hex, started_at=created_at),
            "performance_slo": {
                "phaseSeconds": dict(PHASE_SLO_SECONDS),
                "endToEndSeconds": END_TO_END_SLO_SECONDS,
                "policy": "engineering-target-not-correctness-shortcut",
            },
            "alignment_policy": alignment_execution_policy({"input": input_record}),
            "projects_root": str(projects_root),
            "read_allowlist": {
                "project_root": str(project_dir.resolve()),
                "source_paths": [],
                "repo_paths": _repo_read_allowlist(profile_version),
            },
            "evidence": {},
        }
        _write_state(project_dir, state)
    except Exception:
        if created:
            shutil.rmtree(project_dir, ignore_errors=True)
        raise

    try:
        backlot_code = int(backlot_opener(pid))
    except Exception:
        backlot_code = 1
    state["completed_phases"].append("open_backlot")
    state["next_phase"] = "prepare_inputs"
    state["backlot"] = {"attempted": True, "exit_code": backlot_code}
    _write_state(project_dir, state)
    return state


def attach_narration(
    project_id: str,
    narration_path: str,
    *,
    pipeline_dir: Path | None = None,
) -> dict[str, Any]:
    """Attach narration audio to a script-first project before input preparation completes."""
    state = load_workflow_state(project_id, pipeline_dir=pipeline_dir)
    if state.get("next_phase") != "prepare_inputs":
        raise PersianVideoWorkflowError(
            "narration can be attached only while prepare_inputs is active"
        )
    input_record = dict(state.get("input") or {})
    if input_record.get("narration"):
        raise PersianVideoWorkflowError("this project already has narration audio")
    if not input_record.get("approved_script"):
        raise PersianVideoWorkflowError(
            "attach-narration is only for an approved-script-first project"
        )

    source = _validate_narration_source(narration_path)
    raw = Path(source["original_source_path"])
    project_root = _project_root(state)
    projects_root = Path(str(state.get("projects_root") or PROJECTS_DIR)).resolve()
    if _is_within(raw, projects_root) and not _is_within(raw, project_root):
        raise PersianVideoWorkflowError("refusing narration audio from a sibling project")

    if _is_within(raw, project_root):
        stored = raw
    else:
        inputs_dir = project_root / "inputs"
        inputs_dir.mkdir(parents=True, exist_ok=True)
        suffix = raw.suffix if raw.suffix else ".audio"
        stored = inputs_dir / f"narration{suffix}"
        shutil.copy2(raw, stored)
    source["source_path"] = str(stored.resolve())
    input_record["narration"] = source
    input_record["mode"] = "approved_script_with_narration"
    input_record["script_authority"] = "approved_script"
    state["input"] = input_record
    _write_state(project_root, state)
    return state


def load_workflow_state(
    project_id: str,
    *,
    pipeline_dir: Path | None = None,
) -> dict[str, Any]:
    _validate_project_id(project_id)
    project_dir = (pipeline_dir or PROJECTS_DIR).resolve() / project_id
    path = _state_path(project_dir)
    if not path.is_file():
        raise PersianVideoWorkflowError(f"workflow state not found: {path}")
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PersianVideoWorkflowError(f"workflow state is unreadable: {path}") from exc
    if state.get("version") != WORKFLOW_VERSION or state.get("project_id") != project_id:
        raise PersianVideoWorkflowError("workflow state identity/version mismatch")
    return state


def record_hook_selection(
    project_id: str,
    *,
    selected_text: str,
    hook_family: str,
    candidates: Sequence[Mapping[str, Any]],
    score: float,
    content_match_score: int,
    evidence_checked: bool,
    unsupported_claims_rejected: bool,
    rationale: str,
    pipeline_dir: Path | None = None,
) -> dict[str, Any]:
    """Persist the automatic hook winner without weakening user-authored authority."""
    state = load_workflow_state(project_id, pipeline_dir=pipeline_dir)
    initial = state.get("hook_selection")
    if not isinstance(initial, Mapping):
        raise PersianVideoWorkflowError("workflow is missing its hook-selection authority record")
    if str(initial.get("mode") or "") == "user_supplied":
        validate_user_hook_unchanged(initial, selected_text)
        return state
    state["hook_selection"] = finalize_automatic_hook_selection(
        initial, selected_text=selected_text, hook_family=hook_family, candidates=candidates,
        score=score, content_match_score=content_match_score, evidence_checked=evidence_checked,
        unsupported_claims_rejected=unsupported_claims_rejected, rationale=rationale,
    )
    _write_state(_project_root(state), state)
    return state


def record_user_hook_override(
    project_id: str,
    *,
    selected_text: str,
    reason: str,
    pipeline_dir: Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Bind explicit user hook feedback as authoritative copy in a revision cycle.

    This is intentionally narrower than automatic hook selection. It is available
    only after an explicit user-directed rewind to ``no_copy_preflight`` and only
    for a hook that was previously selected automatically. The superseded decision
    is retained verbatim in durable history before the new user authority is stored.
    """
    state = load_workflow_state(project_id, pipeline_dir=pipeline_dir)
    text = str(selected_text or "").strip()
    why = str(reason or "").strip()
    if not text:
        raise PersianVideoWorkflowError("user hook override requires non-empty selected text")
    if not why:
        raise PersianVideoWorkflowError("user hook override requires a non-empty reason")
    if state.get("status") != "active" or state.get("next_phase") != "no_copy_preflight":
        raise PersianVideoWorkflowError(
            "user hook override requires an active user-directed revision at no_copy_preflight"
        )
    cycle = int(state.get("user_revision_cycles") or 0)
    history = list(state.get("send_back_history") or [])
    latest = history[-1] if history else None
    if (
        cycle <= 0
        or not isinstance(latest, Mapping)
        or latest.get("user_directed_revision") is not True
        or latest.get("target_phase") != "no_copy_preflight"
    ):
        raise PersianVideoWorkflowError(
            "user hook override requires an explicit user-directed revision rewind"
        )

    previous = state.get("hook_selection")
    if not isinstance(previous, Mapping):
        raise PersianVideoWorkflowError("workflow is missing its hook-selection authority record")
    if str(previous.get("mode") or "") != "automatic":
        raise PersianVideoWorkflowError(
            "user hook override only converts a previously automatic hook selection; "
            "existing user-supplied authority remains immutable"
        )

    stamp = now or datetime.now(timezone.utc)
    decision = build_initial_hook_selection(text)
    decision.update({
        "source": "user_directed_revision",
        "revision_cycle": cycle,
        "reason": why,
        "overrides_sha256": str(previous.get("sha256") or ""),
    })
    prior_history = list(state.get("hook_selection_history") or [])
    prior_history.append({
        "revision_cycle": cycle,
        "superseded_at": stamp.isoformat(),
        "reason": why,
        "decision": dict(previous),
    })
    state["hook_selection_history"] = prior_history
    state["hook_selection"] = decision
    _write_state(_project_root(state), state)
    return state


def assert_read_allowed(state: Mapping[str, Any], requested_path: str | Path) -> Path:
    """Reject reads from sibling projects and anything outside the explicit allowlist."""
    requested = Path(requested_path).expanduser().resolve()
    policy = state.get("read_allowlist") or {}
    project_root = Path(str(policy.get("project_root") or "")).resolve()
    projects_root = Path(str(state.get("projects_root") or PROJECTS_DIR)).resolve()

    if _is_within(requested, projects_root):
        if _is_within(requested, project_root):
            return requested
        raise PersianVideoWorkflowError(
            f"read isolation violation: sibling project path is forbidden: {requested}"
        )

    for raw in policy.get("source_paths", []):
        if requested == Path(str(raw)).expanduser().resolve():
            return requested

    for raw in policy.get("repo_paths", []):
        allowed = Path(str(raw)).resolve()
        if requested == allowed or (allowed.is_dir() and _is_within(requested, allowed)):
            return requested

    raise PersianVideoWorkflowError(
        f"read path is outside the Persian workflow allowlist: {requested}"
    )


def _parse_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise PersianVideoWorkflowError("invalid workflow created_at timestamp") from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def assert_within_wall_time(
    state: Mapping[str, Any], *, now: datetime | None = None
) -> None:
    """Validate budget timing metadata.

    Enforcement happens only after a phase finishes, so in-flight work is never
    killed. The next phase cannot start after a persisted budget stop.
    """
    started = _parse_timestamp(
        str(state.get("budget_window_started_at") or state.get("created_at") or "")
    )
    current = now or datetime.now(timezone.utc)
    if current < started:
        raise PersianVideoWorkflowError("workflow timing clock moved before the active window")
    limit = int((state.get("budgets") or {}).get("max_wall_time_minutes", 0))
    if limit <= 0:
        raise PersianVideoWorkflowError("workflow max_wall_time_minutes must be positive")


def _phase_elapsed_seconds(state: Mapping[str, Any], phase: str, *, now: datetime) -> float:
    telemetry = state.get("phase_telemetry")
    entries = telemetry.get(phase) if isinstance(telemetry, Mapping) else None
    if not isinstance(entries, list) or not entries or not isinstance(entries[-1], Mapping):
        return 0.0
    latest = entries[-1]
    duration = latest.get("duration_seconds")
    if duration is not None:
        return max(0.0, float(duration))
    started_at = latest.get("started_at")
    if not started_at:
        return 0.0
    return max(0.0, (now - _parse_timestamp(str(started_at))).total_seconds())


def _budget_stop_payload(
    state: Mapping[str, Any], completed_phase: str, *, now: datetime
) -> dict[str, Any] | None:
    window_started = _parse_timestamp(
        str(state.get("budget_window_started_at") or state.get("created_at") or "")
    )
    wall_seconds = max(0.0, (now - window_started).total_seconds())
    wall_limit_seconds = int((state.get("budgets") or {}).get("max_wall_time_minutes", 0)) * 60
    phase_seconds = _phase_elapsed_seconds(state, completed_phase, now=now)
    phase_limit = int(PHASE_SLO_SECONDS.get(completed_phase, 0))

    if wall_seconds > wall_limit_seconds:
        reason = "wall_budget_exceeded"
        threshold_seconds = wall_limit_seconds
        observed_seconds = wall_seconds
    elif phase_limit and phase_seconds > 2 * phase_limit:
        reason = "phase_budget_exceeded"
        threshold_seconds = 2 * phase_limit
        observed_seconds = phase_seconds
    else:
        return None

    next_phase = state.get("next_phase")
    remaining = list(PHASES[_phase_index(str(next_phase)):]) if next_phase in PHASES else []
    overage_seconds = max(0.0, observed_seconds - threshold_seconds)
    minimum_extra_minutes = max(1, int((overage_seconds + 59) // 60))
    return {
        "status": "failed",
        "quality_disposition": "needs_decision",
        "reason": reason,
        "stopped_at": now.isoformat(),
        "boundary_after_phase": completed_phase,
        "next_phase": next_phase,
        "remaining_phases": remaining,
        "observed_seconds": round(observed_seconds, 3),
        "threshold_seconds": threshold_seconds,
        "options": [
            {"action": "continue_with_extension", "minimum_extra_minutes": minimum_extra_minutes},
            {"action": "continue_to_preview", "preview_phase": "render_opening_candidate"},
            {"action": "stop"},
        ],
    }


def _enforce_phase_boundary_budget(
    state: dict[str, Any], completed_phase: str, *, now: datetime
) -> bool:
    stop = _budget_stop_payload(state, completed_phase, now=now)
    if stop is None:
        return False
    state["status"] = "failed"
    state["budget_stop"] = stop
    trace = state.get("causal_telemetry")
    if isinstance(trace, Mapping) and trace.get("run_span_id"):
        finish_causal_span(
            state, str(trace["run_span_id"]), finished_at=now, outcome="needs_decision"
        )
    return True


_EXPLICIT_WORK_CATEGORIES = frozenset({
    "agent_editorial_work",
    "review_evidence_assembly",
})


def _running_phase_attempt(state: Mapping[str, Any], phase: str) -> int | None:
    telemetry = state.get("phase_telemetry")
    entries = telemetry.get(phase) if isinstance(telemetry, Mapping) else None
    if not isinstance(entries, list) or not entries or not isinstance(entries[-1], Mapping):
        return None
    latest = entries[-1]
    if latest.get("finished_at") or latest.get("outcome") != "running":
        return None
    try:
        return int(latest.get("attempt") or 0) or None
    except (TypeError, ValueError):
        return None


def _open_countable_work_spans(state: Mapping[str, Any]) -> list[dict[str, Any]]:
    trace = state.get("causal_telemetry")
    spans = trace.get("spans") if isinstance(trace, Mapping) else None
    if not isinstance(spans, list):
        return []
    return [
        dict(span) for span in spans
        if isinstance(span, Mapping)
        and bool(span.get("count_toward_wall"))
        and not span.get("finished_at")
        and span.get("kind") not in {"run", "phase_attempt"}
    ]


def start_explicit_work_span(
    project_id: str,
    *,
    category: str,
    name: str,
    pipeline_dir: Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Prospectively measure one real agent/review work interval.

    This never backfills phase residuals. The caller must finish the span before
    durable execution, human wait, or phase completion.
    """
    category = str(category).strip()
    if category not in _EXPLICIT_WORK_CATEGORIES:
        raise PersianVideoWorkflowError(
            f"explicit work category must be one of {sorted(_EXPLICIT_WORK_CATEGORIES)}"
        )
    label = str(name).strip()
    if not label:
        raise PersianVideoWorkflowError("explicit work span name must be non-empty")
    state = load_workflow_state(project_id, pipeline_dir=pipeline_dir)
    phase = str(state.get("next_phase") or "")
    if state.get("status") != "active" or phase not in PHASES:
        raise PersianVideoWorkflowError("explicit work requires one active workflow phase")
    open_work = _open_countable_work_spans(state)
    if open_work:
        raise PersianVideoWorkflowError(
            "explicit work span is already open; finish existing measured work before starting another"
        )
    effective_now = now or datetime.now(timezone.utc)
    attempt = _running_phase_attempt(state, phase)
    if attempt is None:
        state = record_phase_attempt(
            project_id, phase, pipeline_dir=pipeline_dir, now=effective_now
        )
        attempt = int((state.get("attempts") or {}).get(phase) or 0)
    if attempt <= 0:
        raise PersianVideoWorkflowError("explicit work requires a durable phase attempt")
    trace = state.get("causal_telemetry")
    spans = list(trace.get("spans") or []) if isinstance(trace, Mapping) else []
    sequence = 1 + sum(
        1 for span in spans
        if isinstance(span, Mapping)
        and span.get("kind") == "explicit_work"
        and span.get("phase") == phase
        and int(span.get("attempt") or 0) == attempt
    )
    span_id = f"work:{phase}:{attempt}:{sequence}"
    span = record_causal_interval(
        state,
        span_id=span_id,
        name=label,
        category=category,
        started_at=effective_now,
        parent_span_id=causal_phase_span_id(phase, attempt),
        outcome="running",
        kind="explicit_work",
        count_toward_wall=True,
        fields={"phase": phase, "attempt": attempt, "sequence": sequence},
    )
    _write_state(_project_root(state), state)
    return span


def finish_explicit_work_span(
    project_id: str,
    span_id: str,
    *,
    outcome: str = "succeeded",
    pipeline_dir: Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Finish one prospectively opened explicit work interval, idempotently."""
    if outcome not in {"succeeded", "failed", "interrupted"}:
        raise PersianVideoWorkflowError("explicit work outcome must be succeeded, failed, or interrupted")
    state = load_workflow_state(project_id, pipeline_dir=pipeline_dir)
    trace = state.get("causal_telemetry")
    spans = list(trace.get("spans") or []) if isinstance(trace, Mapping) else []
    existing = next(
        (dict(span) for span in spans if isinstance(span, Mapping) and span.get("span_id") == span_id),
        None,
    )
    if existing is None or existing.get("kind") != "explicit_work":
        raise PersianVideoWorkflowError(f"explicit work span not found: {span_id}")
    if existing.get("finished_at"):
        return existing
    effective_now = now or datetime.now(timezone.utc)
    if outcome == "interrupted":
        finished = _abandon_open_explicit_work(
            state, existing, reason="work-finish reported interruption without a verified stop time",
            now=effective_now,
        )
    else:
        finished = finish_causal_span(
            state, span_id, finished_at=effective_now, outcome=outcome
        )
    _write_state(_project_root(state), state)
    return finished


def abandon_explicit_work_span(
    project_id: str,
    span_id: str,
    *,
    reason: str,
    pipeline_dir: Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Recover an open span whose actual stop time is unknown.

    The entire interval is unverified: closing it at recovery time as countable
    work would invent editorial/review time. Keep both timestamps and the reason
    in the trace, but leave the elapsed wall time unattributed.
    """
    explanation = str(reason).strip()
    if not explanation:
        raise PersianVideoWorkflowError("abandoning explicit work requires a reason")
    state = load_workflow_state(project_id, pipeline_dir=pipeline_dir)
    trace = state.get("causal_telemetry")
    spans = trace.get("spans") if isinstance(trace, Mapping) else None
    existing = next(
        (dict(span) for span in spans or []
         if isinstance(span, Mapping) and span.get("span_id") == span_id),
        None,
    )
    if existing is None or existing.get("kind") != "explicit_work":
        raise PersianVideoWorkflowError(f"explicit work span not found: {span_id}")
    if existing.get("finished_at"):
        return existing
    recovered_at = now or datetime.now(timezone.utc)
    recovered = _abandon_open_explicit_work(state, existing, reason=explanation, now=recovered_at)
    _write_state(_project_root(state), state)
    return recovered


def _abandon_open_explicit_work(
    state: dict[str, Any], span: Mapping[str, Any], *, reason: str, now: datetime
) -> dict[str, Any]:
    return record_causal_interval(
        state,
        span_id=str(span["span_id"]),
        name=str(span["name"]),
        category=str(span["category"]),
        started_at=str(span["started_at"]),
        finished_at=now,
        parent_span_id=str(span["parent_span_id"]),
        outcome="abandoned_unverified",
        kind="explicit_work",
        count_toward_wall=False,
        fields={
            **{key: value for key, value in span.items() if key not in {
                "trace_id", "span_id", "parent_span_id", "name", "kind", "category",
                "started_at", "finished_at", "outcome", "count_toward_wall",
                "concurrency_group",
            }},
            "measurement_disposition": "unverified_abandonment",
            "recovery_reason": reason,
        },
    )


def _interrupt_open_explicit_work_for_phase(
    state: dict[str, Any], phase: str, *, now: datetime
) -> None:
    """Close measured agent/review work when a send-back abandons its phase."""
    for span in _open_countable_work_spans(state):
        if span.get("kind") != "explicit_work" or span.get("phase") != phase:
            continue
        _abandon_open_explicit_work(
            state, span, reason="phase superseded before measured work was closed", now=now
        )


def _assert_no_open_explicit_work(state: Mapping[str, Any], phase: str) -> None:
    open_spans = [
        span for span in _open_countable_work_spans(state)
        if span.get("kind") == "explicit_work" and span.get("phase") == phase
    ]
    if open_spans:
        raise PersianVideoWorkflowError(
            "finish explicit work span before completing the current phase"
        )


def record_phase_attempt(
    project_id: str,
    phase: str,
    *,
    pipeline_dir: Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    state = load_workflow_state(project_id, pipeline_dir=pipeline_dir)
    assert_within_wall_time(state, now=now)
    if phase != state.get("next_phase") or phase not in PHASES:
        raise PersianVideoWorkflowError(
            f"cannot attempt {phase!r}; next phase is {state.get('next_phase')!r}"
        )
    if state.get("status") != "active":
        raise PersianVideoWorkflowError(
            f"cannot start a phase while workflow status is {state.get('status')!r}"
        )
    attempts = dict(state.get("attempts") or {})
    count = int(attempts.get(phase, 0)) + 1
    limit = 1 + int(state["budgets"]["max_revisions_per_stage"])
    if count > limit:
        raise PersianVideoWorkflowError(
            f"retry budget exhausted for {phase}: {count - 1} retries > {limit - 1}"
        )
    attempts[phase] = count
    state["attempts"] = attempts
    effective_now = now or datetime.now(timezone.utc)
    telemetry = dict(state.get("phase_telemetry") or {})
    entries = list(telemetry.get(phase) or [])
    entries.append({
        "attempt": count,
        "started_at": effective_now.isoformat(),
        "finished_at": None,
        "duration_seconds": None,
        "execution_class": _execution_class_for_phase(phase),
        "outcome": "running",
    })
    telemetry[phase] = entries
    state["phase_telemetry"] = telemetry
    if not isinstance(state.get("causal_telemetry"), Mapping):
        created = _parse_timestamp(str(state.get("created_at") or effective_now.isoformat()))
        state["causal_telemetry"] = new_causal_trace(uuid4().hex, started_at=created)
    record_phase_attempt_span(
        state, phase, count, started_at=effective_now
    )
    # A fresh attempt explicitly supersedes any stale unfinished predecessor at
    # this same phase. This prevents crash/restart history from accumulating
    # phantom `running` attempts while leaving the newest attempt genuinely open.
    reconcile_phase_telemetry(state, now=effective_now)
    _write_state(Path(state["read_allowlist"]["project_root"]), state)
    return state


def record_phase_failure(
    project_id: str,
    phase: str,
    *,
    reason: str,
    pipeline_dir: Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Close the current phase attempt as failed without inventing workflow progress."""
    state = load_workflow_state(project_id, pipeline_dir=pipeline_dir)
    if phase not in PHASES or phase != state.get("next_phase"):
        raise PersianVideoWorkflowError(
            f"cannot fail {phase!r}; next phase is {state.get('next_phase')!r}"
        )
    telemetry = state.get("phase_telemetry") or {}
    entries = list(telemetry.get(phase) or []) if isinstance(telemetry, Mapping) else []
    if not entries or not isinstance(entries[-1], Mapping):
        raise PersianVideoWorkflowError(
            f"cannot fail {phase!r} without a recorded running attempt"
        )
    if entries[-1].get("finished_at"):
        raise PersianVideoWorkflowError(
            f"cannot fail {phase!r}; latest attempt is already finished"
        )
    _finish_phase_telemetry(state, phase, outcome="failed", now=now)
    telemetry = dict(state.get("phase_telemetry") or {})
    entries = list(telemetry.get(phase) or [])
    entry = dict(entries[-1])
    entry["failure_reason"] = str(reason).strip() or "unspecified failure"
    entries[-1] = entry
    telemetry[phase] = entries
    state["phase_telemetry"] = telemetry
    failures = list(state.get("phase_failures") or [])
    failures.append({
        "phase": phase,
        "attempt": int(entry.get("attempt") or 0),
        "reason": entry["failure_reason"],
        "finished_at": entry.get("finished_at"),
    })
    state["phase_failures"] = failures
    _write_state(_project_root(state), state)
    return state


def _project_root(state: Mapping[str, Any]) -> Path:
    return Path(str(state["read_allowlist"]["project_root"])).resolve()


def _valid_sha256(value: object) -> bool:
    raw = str(value or "").strip().lower()
    return len(raw) == 64 and all(ch in "0123456789abcdef" for ch in raw)


def _validate_prepare_inputs_completion(
    state: Mapping[str, Any], evidence: Mapping[str, Any]
) -> dict[str, Any]:
    input_record = dict(state.get("input") or {})
    narration = input_record.get("narration")
    if not isinstance(narration, Mapping):
        raise PersianVideoWorkflowError(
            "prepare_inputs cannot complete until narration audio is attached"
        )
    narration_path = Path(str(narration.get("source_path") or "")).resolve()
    if not _is_within(narration_path, _project_root(state)) or not narration_path.is_file():
        raise PersianVideoWorkflowError(
            "prepare_inputs narration must be a real file inside the current project"
        )
    actual_audio_sha = _hash_file(narration_path)
    if actual_audio_sha != str(narration.get("sha256") or "").lower():
        raise PersianVideoWorkflowError("prepare_inputs narration hash no longer matches its bytes")

    script_sha = str(evidence.get("authoritative_script_sha256") or "").strip().lower()
    if not _valid_sha256(script_sha):
        raise PersianVideoWorkflowError(
            "prepare_inputs evidence requires authoritative_script_sha256"
        )
    approved = input_record.get("approved_script")
    if isinstance(approved, Mapping):
        expected = str(approved.get("sha256") or "").strip().lower()
        if script_sha != expected:
            raise PersianVideoWorkflowError(
                "prepare_inputs authoritative script hash does not match the approved script"
            )

    reported_audio_sha = str(evidence.get("narration_sha256") or "").strip().lower()
    if reported_audio_sha != actual_audio_sha:
        raise PersianVideoWorkflowError(
            "prepare_inputs evidence narration_sha256 does not match the attached audio"
        )
    return {
        "authoritative_script_sha256": script_sha,
        "narration_sha256": actual_audio_sha,
        "input_mode": input_record.get("mode"),
        "script_authority": input_record.get("script_authority"),
    }


def _phase_index(phase: str) -> int:
    try:
        return PHASES.index(phase)
    except ValueError as exc:
        raise PersianVideoWorkflowError(f"unknown workflow phase: {phase!r}") from exc


def _validate_no_copy_preflight_completion(
    state: Mapping[str, Any], evidence: Mapping[str, Any]
) -> dict[str, Any]:
    attempt_id = str(evidence.get("attempt_id") or "").strip()
    if not attempt_id or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", attempt_id):
        raise PersianVideoWorkflowError(
            "no_copy_preflight completion requires the promoted draft attempt_id"
        )
    root = _project_root(state)
    report_path = root / ".preflight" / "edit" / attempt_id / "preflight_report.json"
    canonical_path = root / "artifacts" / "edit_decisions.json"
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
        canonical = json.loads(canonical_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PersianVideoWorkflowError(
            "no_copy_preflight requires a persisted passing report and promoted canonical edit"
        ) from exc
    if not isinstance(report, dict) or report.get("ok") is not True:
        raise PersianVideoWorkflowError("no_copy_preflight report is missing or refused")
    if not isinstance(canonical, dict):
        raise PersianVideoWorkflowError("promoted edit_decisions must be a JSON object")
    digest = artifact_sha256(canonical)
    if report.get("artifactSha256") != digest:
        raise PersianVideoWorkflowError(
            "no_copy_preflight report digest does not match the promoted canonical edit"
        )
    projects_root = Path(str(state.get("projects_root") or PROJECTS_DIR)).resolve()
    try:
        checkpoint = read_checkpoint(projects_root, str(state["project_id"]), "edit")
    except (CheckpointValidationError, OSError, json.JSONDecodeError) as exc:
        raise PersianVideoWorkflowError(
            "no_copy_preflight cannot complete until checkpoint_edit.json records the promoted edit"
        ) from exc
    checkpoint_edit = (checkpoint.get("artifacts") or {}).get("edit_decisions")
    if checkpoint.get("status") != "completed" or not isinstance(checkpoint_edit, dict):
        raise PersianVideoWorkflowError("checkpoint_edit.json is not a completed canonical edit checkpoint")
    if artifact_sha256(checkpoint_edit) != digest:
        raise PersianVideoWorkflowError(
            "checkpoint_edit.json does not match the promoted canonical edit bytes"
        )
    return {
        "attempt_id": attempt_id,
        "artifact_sha256": digest,
        "preflight_report_path": str(report_path),
        "preflight_report_sha256": _hash_file(report_path),
        "checkpoint_edit_path": str(root / "checkpoint_edit.json"),
    }


def _complete_phase_impl(
    project_id: str,
    phase: str,
    *,
    evidence: Mapping[str, Any] | None = None,
    pipeline_dir: Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Advance exactly one phase; terminal advancement validates the real candidate."""
    state = load_workflow_state(project_id, pipeline_dir=pipeline_dir)
    assert_within_wall_time(state, now=now)
    if state.get("status") == "awaiting_human":
        raise PersianVideoWorkflowError("workflow already stopped at awaiting_human")
    if state.get("status") != "active":
        raise PersianVideoWorkflowError(
            f"cannot complete a phase while workflow status is {state.get('status')!r}"
        )
    if (state.get("asset_usage") or {}).get("pending_pass") is not None:
        raise PersianVideoWorkflowError(
            "asset search result accounting must complete before send-back"
        )
    if phase != state.get("next_phase"):
        raise PersianVideoWorkflowError(
            f"cannot complete {phase!r}; next phase is {state.get('next_phase')!r}"
        )
    if phase == "awaiting_human":
        from lib.persian_run_kernel import reconcile_terminal_jobs

        reconcile_terminal_jobs(project_id, pipeline_dir=pipeline_dir)
        state = load_workflow_state(project_id, pipeline_dir=pipeline_dir)
    if phase not in {"open_backlot", "awaiting_human"} and not int(
        (state.get("attempts") or {}).get(phase, 0)
    ):
        raise PersianVideoWorkflowError(
            f"phase {phase!r} must be attempted before it can complete"
        )
    # Checkpoint-backed phases are transaction-like: durable checkpoint truth is
    # the outer commit prerequisite. Validate it before phase-specific evidence so
    # a missing canonical checkpoint cannot be obscured by a newer validator.
    stage = _PHASE_CHECKPOINT.get(phase)
    checkpoint: Mapping[str, Any] | None = None
    if stage is not None:
        try:
            checkpoint = read_checkpoint(
                Path(str(state.get("projects_root") or PROJECTS_DIR)).resolve(),
                project_id,
                stage,
            )
        except (CheckpointValidationError, OSError, json.JSONDecodeError) as exc:
            raise PersianVideoWorkflowError(
                f"checkpoint_{stage}.json must be valid before {phase} can complete"
            ) from exc
        if not checkpoint or checkpoint.get("status") != "completed":
            raise PersianVideoWorkflowError(
                f"checkpoint_{stage}.json must be completed before {phase} can complete"
            )

    phase_evidence = dict(evidence or {})
    if phase == "prepare_inputs":
        phase_evidence.update(_validate_prepare_inputs_completion(state, phase_evidence))
    if phase == "align_script_timing":
        phase_evidence.update(_validate_alignment_completion(state, phase_evidence))
    if phase == "plan_scenes_moments" and "sourcing_order" in phase_evidence:
        raw_order = phase_evidence.get("sourcing_order")
        if not isinstance(raw_order, list) or not raw_order:
            raise PersianVideoWorkflowError(
                "plan_scenes_moments sourcing_order must be a non-empty list when provided"
            )
        sourcing_order = [str(item).strip() for item in raw_order]
        if any(not item for item in sourcing_order) or len(set(sourcing_order)) != len(sourcing_order):
            raise PersianVideoWorkflowError(
                "plan_scenes_moments sourcing_order requires unique non-empty visual-event ids"
            )
        phase_evidence["sourcing_order"] = sourcing_order
    if phase == "no_copy_preflight":
        phase_evidence.update(_validate_no_copy_preflight_completion(state, phase_evidence))
    if phase == "final_review":
        phase_evidence.update(_validate_final_review_completion(state, phase_evidence))
    if phase == "acquire_assets" and (state.get("asset_usage") or {}).get("pending_pass") is not None:
        raise PersianVideoWorkflowError(
            "asset search result accounting must complete before acquire_assets can complete"
        )
    if phase == "awaiting_human":
        phase_evidence.update(_validate_awaiting_human_candidate(state))

    if phase == "acquire_assets" and checkpoint is not None:
        artifacts = checkpoint.get("artifacts") if isinstance(checkpoint.get("artifacts"), Mapping) else {}
        manifest = artifacts.get("asset_manifest") if isinstance(artifacts, Mapping) else None
        if not isinstance(manifest, Mapping):
            raise PersianVideoWorkflowError(
                "completed assets checkpoint requires an asset_manifest artifact"
            )
        phase_evidence["assetWorkspaceBinding"] = (
            validate_asset_manifest_against_workspace(_project_root(state), manifest)
        )

    completed = list(state.get("completed_phases") or [])
    if phase not in completed:
        completed.append(phase)
    state["completed_phases"] = completed
    all_evidence = dict(state.get("evidence") or {})
    all_evidence[phase] = phase_evidence
    state["evidence"] = all_evidence

    if phase == "awaiting_human":
        state["status"] = "awaiting_human"
        state["next_phase"] = None
    else:
        state["next_phase"] = PHASES[_phase_index(phase) + 1]
    effective_now = now or datetime.now(timezone.utc)
    _finish_phase_telemetry(state, phase, outcome="succeeded", now=effective_now)
    reconcile_phase_telemetry(state, now=effective_now)
    if phase != "awaiting_human":
        _enforce_phase_boundary_budget(state, phase, now=effective_now)
    if phase == "awaiting_human":
        terminal_now = effective_now
        trace = state.get("causal_telemetry")
        if isinstance(trace, Mapping) and trace.get("run_span_id"):
            finish_causal_span(
                state,
                str(trace["run_span_id"]),
                finished_at=terminal_now,
                outcome="awaiting_human",
            )
        _freeze_performance_summary(state, now=terminal_now)
    _write_state(_project_root(state), state)
    return state


def complete_phase(
    project_id: str,
    phase: str,
    *,
    evidence: Mapping[str, Any] | None = None,
    pipeline_dir: Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Complete one phase and persist success/failure timing without inventing progress."""
    current = load_workflow_state(project_id, pipeline_dir=pipeline_dir)
    _assert_no_open_explicit_work(current, phase)
    from lib.persian_run_kernel import require_measured_phase_commit

    require_measured_phase_commit(current, phase, evidence or {})
    try:
        return _complete_phase_impl(
            project_id, phase, evidence=evidence, pipeline_dir=pipeline_dir, now=now
        )
    except Exception:
        try:
            state = load_workflow_state(project_id, pipeline_dir=pipeline_dir)
            _finish_phase_telemetry(state, phase, outcome="failed", now=now)
            _write_state(_project_root(state), state)
        except Exception:
            pass
        raise


def _archive_stale_checkpoint(project_root: Path, stage: str, *, reason: str) -> str | None:
    path = project_root / f"checkpoint_{stage}.json"
    if not path.exists():
        return None
    history = project_root / "history"
    history.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    target = history / f"checkpoint_{stage}_reconciled_{stamp}.json"
    shutil.copy2(path, target)
    path.unlink()
    meta = history / f"checkpoint_{stage}_reconciled_{stamp}.reason.txt"
    meta.write_text(reason.strip() + "\n", encoding="utf-8")
    return str(target)


def _invalidate_checkpoints_for_rewind(state: Mapping[str, Any], target_phase: str, *, reason: str) -> list[str]:
    root = _project_root(state)
    archived: list[str] = []
    for stage in _REWIND_INVALIDATES.get(target_phase, ("compose",)):
        moved = _archive_stale_checkpoint(root, stage, reason=reason)
        if moved:
            archived.append(moved)
    return archived


def reconcile_workflow_state(
    project_id: str, *, pipeline_dir: Path | None = None
) -> dict[str, Any]:
    """Reconcile workflow claims with durable checkpoints; never invent progress."""
    state = load_workflow_state(project_id, pipeline_dir=pipeline_dir)
    projects_root = Path(str(state.get("projects_root") or PROJECTS_DIR)).resolve()
    completed = list(state.get("completed_phases") or [])
    rewind_to: str | None = None
    problems: list[dict[str, Any]] = []
    for phase, stage in _PHASE_CHECKPOINT.items():
        if phase not in completed:
            continue
        try:
            checkpoint = read_checkpoint(projects_root, project_id, stage)
        except (CheckpointValidationError, OSError, json.JSONDecodeError) as exc:
            checkpoint = None
            problems.append({"phase": phase, "stage": stage, "problem": str(exc)})
        if not checkpoint or checkpoint.get("status") != "completed":
            problems.append({"phase": phase, "stage": stage, "problem": "missing-or-not-completed"})
            if rewind_to is None or _phase_index(phase) < _phase_index(rewind_to):
                rewind_to = phase

    archived: list[str] = []
    recovered: list[dict[str, Any]] = []
    if rewind_to is not None:
        target_index = _phase_index(rewind_to)
        state["completed_phases"] = [p for p in completed if _phase_index(p) < target_index]
        evidence = dict(state.get("evidence") or {})
        state["evidence"] = {k: v for k, v in evidence.items() if _phase_index(k) < target_index}
        state["next_phase"] = rewind_to
        state["status"] = "active"
        archived = _invalidate_checkpoints_for_rewind(
            state, rewind_to, reason="workflow/checkpoint reconciliation after missing or incomplete prerequisite checkpoint",
        )
    elif state.get("next_phase") == "render_final_candidate":
        # A render process may finish successfully after the controlling process
        # disappears. Recover only from the durable compose checkpoint and the
        # exact digest-bound MP4 it names. Mere MP4 presence never advances state.
        compose_path = _project_root(state) / "checkpoint_compose.json"
        if compose_path.is_file():
            try:
                candidate = _validate_awaiting_human_candidate(
                    state, require_final_review=False
                )
            except PersianVideoWorkflowError as exc:
                problems.append({
                    "phase": "render_final_candidate",
                    "stage": "compose",
                    "problem": str(exc),
                })
            else:
                completed_now = list(state.get("completed_phases") or [])
                if "render_final_candidate" not in completed_now:
                    completed_now.append("render_final_candidate")
                state["completed_phases"] = completed_now
                state["next_phase"] = "final_review"
                state["status"] = "active"
                all_evidence = dict(state.get("evidence") or {})
                all_evidence["render_final_candidate"] = {
                    "candidate_path": candidate["candidate_path"],
                    "candidate_sha256": candidate["candidate_sha256"],
                    "checkpoint": candidate["checkpoint"],
                    "recovered": True,
                }
                state["evidence"] = all_evidence
                # The expensive render itself succeeded; only the controller/report
                # path disappeared. Preserve that fact instead of labelling the
                # recovered attempt failed or merely superseded.
                _finish_phase_telemetry(
                    state, "render_final_candidate", outcome="succeeded"
                )
                recovered.append({
                    "phase": "render_final_candidate",
                    "candidatePath": candidate["candidate_path"],
                    "candidateSha256": candidate["candidate_sha256"],
                    "checkpoint": candidate["checkpoint"],
                })

    reconciliation = {
        "at": datetime.now(timezone.utc).isoformat(),
        "rewoundTo": rewind_to,
        "problems": problems,
        "archivedCheckpoints": archived,
        "recoveredPhases": recovered,
    }
    state["last_reconciliation"] = reconciliation
    reconcile_phase_telemetry(state)
    _write_state(_project_root(state), state)
    return state


def record_recovery_attempt(
    project_id: str,
    *,
    diagnostic_code: str,
    recovery_class: str | None = None,
    strategy: str,
    artifact_sha256: str | None = None,
    pipeline_dir: Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Record one bounded deterministic repair attempt for no-copy preflight.

    Calling after the class budget is exhausted persists an explicit terminal
    ``needs_revision`` state. New user feedback can reopen a fresh bounded cycle
    through ``request_send_back(..., user_directed_revision=True)``.
    """
    state = load_workflow_state(project_id, pipeline_dir=pipeline_dir)
    if state.get("status") != "active" or state.get("next_phase") != "no_copy_preflight":
        raise PersianVideoWorkflowError(
            "deterministic recovery attempts are recorded only during active no_copy_preflight"
        )
    plan = recovery_policy_for_issue({
        "code": diagnostic_code,
        "recoveryClass": recovery_class or "",
    })
    recovery_class = str(plan["recoveryClass"])
    history = dict(state.get("recovery_attempts") or {})
    entries = list(history.get(recovery_class) or [])
    max_attempts = int(plan["maxAttempts"])
    stamp = now or datetime.now(timezone.utc)
    if len(entries) >= max_attempts:
        state["status"] = "needs_revision"
        state["next_phase"] = None
        state["recovery_stop"] = {
            "at": stamp.isoformat(),
            "diagnosticCode": str(diagnostic_code),
            "recoveryClass": recovery_class,
            "attemptsUsed": len(entries),
            "maxAttempts": max_attempts,
            "outcome": "needs_human_editorial_revision",
        }
        trace = state.get("causal_telemetry")
        if isinstance(trace, Mapping) and trace.get("run_span_id"):
            finish_causal_span(
                state, str(trace["run_span_id"]),
                finished_at=stamp, outcome="needs_revision",
            )
        reconcile_phase_telemetry(state, now=stamp)
        _write_state(_project_root(state), state)
        return state
    if strategy not in plan["strategies"]:
        raise PersianVideoWorkflowError(
            f"strategy {strategy!r} is not allowed for {recovery_class}; "
            f"allowed={plan['strategies']}"
        )
    if artifact_sha256 is not None and not _valid_sha256(artifact_sha256):
        raise PersianVideoWorkflowError("recovery artifact_sha256 must be a lowercase sha256")
    entries.append({
        "attempt": len(entries) + 1,
        "at": stamp.isoformat(),
        "diagnosticCode": str(diagnostic_code),
        "strategy": strategy,
        "policyVersion": plan["version"],
        **({"artifactSha256": artifact_sha256} if artifact_sha256 else {}),
    })
    history[recovery_class] = entries
    state["recovery_attempts"] = history
    _write_state(_project_root(state), state)
    return state


def request_send_back(
    project_id: str,
    target_phase: str,
    *,
    reason: str,
    pipeline_dir: Path | None = None,
    now: datetime | None = None,
    user_directed_revision: bool = False,
) -> dict[str, Any]:
    """Rewind a bounded production; explicit user feedback may open one fresh cycle."""
    state = load_workflow_state(project_id, pipeline_dir=pipeline_dir)
    effective_now = now or datetime.now(timezone.utc)
    prior_status = str(state.get("status") or "")
    if not user_directed_revision:
        assert_within_wall_time(state, now=effective_now)
    elif prior_status in {"awaiting_human", "needs_revision"}:
        record_human_idle_and_reopen_run(
            state, resumed_at=effective_now, reason=reason.strip() or "explicit user revision"
        )
    if state.get("status") == "awaiting_human" and not user_directed_revision:
        raise PersianVideoWorkflowError(
            "workflow already stopped at awaiting_human; use an explicit user-directed revision or the checkpoint approval protocol"
        )
    if target_phase not in PHASES[3:-1]:
        raise PersianVideoWorkflowError(
            "send-back target must be an operational phase before awaiting_human"
        )
    if not reason.strip():
        raise PersianVideoWorkflowError("send-back requires a non-empty reason")
    current = state.get("next_phase")
    # Rewinding abandons the currently open attempt by definition. Close it as
    # superseded before changing the phase pointer so telemetry has no zombie work.
    if isinstance(current, str):
        _interrupt_open_explicit_work_for_phase(state, current, now=effective_now)
        _finish_phase_telemetry(state, current, outcome="superseded", now=effective_now)
    current_index = len(PHASES) if current is None else _phase_index(str(current))
    target_index = _phase_index(target_phase)
    if target_index >= current_index:
        raise PersianVideoWorkflowError(
            f"send-back must rewind the workflow; current={current!r}, target={target_phase!r}"
        )

    previous_send_backs = int(state.get("send_backs", 0))
    previous_attempts = dict(state.get("attempts") or {})
    if user_directed_revision:
        # The bounded protocol explicitly permits a fresh cycle after new user
        # feedback.  Record the provenance and reset only operational counters at
        # or after the requested rewind; never silently expand the automatic budget.
        state["user_revision_cycles"] = int(state.get("user_revision_cycles", 0)) + 1
        state["send_backs"] = 0
        state["budget_window_started_at"] = effective_now.isoformat()
        state["recovery_attempts"] = {}
        state.pop("recovery_stop", None)
        state["attempts"] = {
            key: value for key, value in previous_attempts.items()
            if key in PHASES and _phase_index(key) < target_index
        }
    else:
        used = previous_send_backs + 1
        limit = int(state["budgets"]["max_send_backs"])
        if used > limit:
            raise PersianVideoWorkflowError(
                f"send-back budget exhausted: {used} requested > {limit} allowed"
            )
        state["send_backs"] = used
    state["status"] = "active"
    state["next_phase"] = target_phase
    state["completed_phases"] = [
        p for p in state.get("completed_phases", []) if _phase_index(p) < target_index
    ]
    evidence = dict(state.get("evidence") or {})
    state["evidence"] = {
        key: value for key, value in evidence.items() if _phase_index(key) < target_index
    }
    history = list(state.get("send_back_history") or [])
    archived = _invalidate_checkpoints_for_rewind(state, target_phase, reason=reason.strip())
    history.append({
        "target_phase": target_phase,
        "reason": reason.strip(),
        "archived_checkpoints": archived,
        **({
            "user_directed_revision": True,
            "prior_send_backs": previous_send_backs,
            "prior_attempts": previous_attempts,
        } if user_directed_revision else {}),
    })
    state["send_back_history"] = history
    _write_state(_project_root(state), state)
    return state


def bounded_asset_search_request(
    project_id: str,
    request: Mapping[str, Any],
    *,
    retry_pass: int,
    pipeline_dir: Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return a direct_clip_search request clamped to the shared workflow budget."""
    state = load_workflow_state(project_id, pipeline_dir=pipeline_dir)
    assert_within_wall_time(state, now=now)
    if state.get("next_phase") != "acquire_assets":
        raise PersianVideoWorkflowError("asset search is allowed only during acquire_assets")
    policy = asset_search_policy()
    if retry_pass < 0 or retry_pass > policy["max_retry_passes"]:
        raise PersianVideoWorkflowError(
            f"asset retry pass {retry_pass} exceeds max {policy['max_retry_passes']}"
        )
    usage = dict(state.get("asset_usage") or {})
    completed_passes = list(usage.get("completed_passes") or [])
    pending_pass = usage.get("pending_pass")
    if pending_pass is not None:
        raise PersianVideoWorkflowError(
            f"asset search pass {pending_pass} is still pending result accounting"
        )
    if retry_pass in completed_passes:
        raise PersianVideoWorkflowError(f"asset search pass {retry_pass} was already recorded")
    if retry_pass != len(completed_passes):
        raise PersianVideoWorkflowError(
            f"asset search passes must be sequential; completed={completed_passes}"
        )

    bounded = dict(request)
    if retry_pass == 1:
        sourcing_order = list(
            ((state.get("evidence") or {}).get("plan_scenes_moments") or {}).get("sourcing_order") or []
        )
        queries = bounded.get("queries")
        if sourcing_order and isinstance(queries, list) and queries:
            priority = {event_id: index for index, event_id in enumerate(sourcing_order)}
            normalized_queries = []
            for index, query in enumerate(queries):
                if not isinstance(query, Mapping):
                    raise PersianVideoWorkflowError("asset retry queries must be objects")
                slot_id = str(query.get("slot_id") or "").strip()
                if not slot_id:
                    raise PersianVideoWorkflowError(
                        "importance-weighted asset retry requires slot_id on every query"
                    )
                if slot_id not in priority:
                    raise PersianVideoWorkflowError(
                        f"asset retry slot_id {slot_id!r} is absent from the scene sourcing_order"
                    )
                normalized_queries.append((priority[slot_id], index, dict(query)))
            normalized_queries.sort(key=lambda item: (item[0], item[1]))
            bounded["queries"] = [query for _, _, query in normalized_queries]
    project_root = _project_root(state)
    raw_output_dir = str(bounded.get("output_dir") or "").strip()
    if raw_output_dir:
        raw_output = Path(raw_output_dir).expanduser()
        output_dir = (
            raw_output.resolve()
            if raw_output.is_absolute()
            else (project_root / raw_output).resolve()
        )
    else:
        output_dir = (project_root / "assets").resolve()
    if not _is_within(output_dir, project_root):
        raise PersianVideoWorkflowError(
            f"asset output_dir must stay inside the current project: {output_dir}"
        )
    bounded["output_dir"] = str(output_dir)

    sources = bounded.get("sources", policy["sources"])
    if list(sources) != policy["sources"]:
        raise PersianVideoWorkflowError(
            f"asset sources must be exactly {policy['sources']}; got {sources}"
        )
    bounded["sources"] = policy["sources"]
    if int(bounded.get("clips_per_query", policy["clips_per_query"])) != policy["clips_per_query"]:
        raise PersianVideoWorkflowError("clips_per_query is fixed at 1 for Persian production")
    bounded["clips_per_query"] = policy["clips_per_query"]

    used_semantic_candidates = int(
        usage.get("semantic_candidates_reviewed", usage.get("candidates_considered", 0))
    )
    used_bytes = int(usage.get("bytes_downloaded", 0))
    remaining_candidates = policy["max_candidates_total"] - used_semantic_candidates
    remaining_bytes = policy["max_total_download_bytes"] - used_bytes
    if remaining_candidates <= 0 or remaining_bytes <= 0:
        raise PersianVideoWorkflowError("shared asset download/candidate budget is exhausted")

    for key, ceiling in (
        ("max_candidates_total", remaining_candidates),
        ("max_bytes_per_clip", policy["max_bytes_per_clip"]),
        ("max_total_download_bytes", remaining_bytes),
    ):
        requested = int(bounded.get(key, ceiling))
        if requested > ceiling:
            raise PersianVideoWorkflowError(
                f"{key}={requested} exceeds remaining workflow ceiling {ceiling}"
            )
        if requested <= 0:
            raise PersianVideoWorkflowError(f"{key} must be positive")
        bounded[key] = requested

    usage["pending_pass"] = retry_pass
    usage["pending_output_dir"] = bounded["output_dir"]
    usage["pending_limits"] = {
        "max_candidates_total": bounded["max_candidates_total"],
        "max_bytes_per_clip": bounded["max_bytes_per_clip"],
        "max_total_download_bytes": bounded["max_total_download_bytes"],
    }
    state["asset_usage"] = usage
    _write_state(_project_root(state), state)
    return bounded


def record_asset_search_result(
    project_id: str,
    *,
    retry_pass: int,
    result_data: Mapping[str, Any],
    pipeline_dir: Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Account a completed stock-search pass against shared candidate/byte limits."""
    state = load_workflow_state(project_id, pipeline_dir=pipeline_dir)
    assert_within_wall_time(state, now=now)
    if state.get("next_phase") != "acquire_assets":
        raise PersianVideoWorkflowError("asset results are accepted only during acquire_assets")
    policy = asset_search_policy()
    if retry_pass < 0 or retry_pass > policy["max_retry_passes"]:
        raise PersianVideoWorkflowError("asset retry pass is outside the workflow budget")

    usage = dict(state.get("asset_usage") or {})
    completed_passes = list(usage.get("completed_passes") or [])
    if retry_pass != len(completed_passes):
        raise PersianVideoWorkflowError(
            f"asset result pass must be next in sequence; completed={completed_passes}"
        )
    if usage.get("pending_pass") != retry_pass:
        raise PersianVideoWorkflowError(
            f"asset result pass {retry_pass} has no matching issued request"
        )
    pending_limits = dict(usage.get("pending_limits") or {})
    pending_output_dir = str(usage.get("pending_output_dir") or "")
    if str(result_data.get("output_dir") or "") != pending_output_dir:
        raise PersianVideoWorkflowError(
            "asset result output_dir does not match the issued request"
        )
    if list(result_data.get("resolved_sources") or []) != policy["sources"]:
        raise PersianVideoWorkflowError("asset result sources do not match the issued provider set")
    for key, expected in pending_limits.items():
        try:
            actual = int(result_data[key])
        except (KeyError, TypeError, ValueError) as exc:
            raise PersianVideoWorkflowError(
                f"asset result must echo the issued {key} limit"
            ) from exc
        if actual != int(expected):
            raise PersianVideoWorkflowError(
                f"asset result {key} does not match the issued request"
            )
    try:
        candidates = int(result_data["candidates_considered"])
        downloaded_bytes = int(result_data["bytes_downloaded"])
    except (KeyError, TypeError, ValueError) as exc:
        raise PersianVideoWorkflowError(
            "asset result requires integer candidates_considered and bytes_downloaded counters"
        ) from exc
    if candidates < 0 or downloaded_bytes < 0:
        raise PersianVideoWorkflowError("asset usage counters must be non-negative")
    semantic_raw = result_data.get("semantic_candidates_reviewed")
    technical_raw = result_data.get("technical_rejects", 0)
    duplicate_raw = result_data.get("duplicate_technical_rejects", 0)
    try:
        semantic_candidates = candidates if semantic_raw is None else int(semantic_raw)
        technical_rejects = int(technical_raw)
        duplicate_technical_rejects = int(duplicate_raw)
    except (TypeError, ValueError) as exc:
        raise PersianVideoWorkflowError(
            "asset semantic/technical candidate counters must be integers"
        ) from exc
    if min(semantic_candidates, technical_rejects, duplicate_technical_rejects) < 0:
        raise PersianVideoWorkflowError("asset semantic/technical candidate counters must be non-negative")
    if semantic_candidates > candidates:
        raise PersianVideoWorkflowError("semantic_candidates_reviewed cannot exceed candidates_considered")
    if technical_rejects > candidates:
        raise PersianVideoWorkflowError("technical_rejects cannot exceed candidates_considered")
    if semantic_candidates > int(pending_limits["max_candidates_total"]):
        raise PersianVideoWorkflowError("asset result exceeded its issued semantic candidate ceiling")
    if downloaded_bytes > int(pending_limits["max_total_download_bytes"]):
        raise PersianVideoWorkflowError("asset result exceeded its issued download-byte ceiling")
    clip_ceiling = int(pending_limits["max_bytes_per_clip"])
    clips = result_data.get("clips") or []
    if not isinstance(clips, list):
        raise PersianVideoWorkflowError("asset result clips must be a list")
    project_root = _project_root(state)
    for clip in clips:
        if not isinstance(clip, Mapping):
            raise PersianVideoWorkflowError("asset result clip entries must be objects")
        reported_path = str(clip.get("path") or "").strip()
        if not reported_path:
            raise PersianVideoWorkflowError("asset result clips require a path")
        raw_path = Path(reported_path).expanduser()
        clip_path = (
            raw_path.resolve()
            if raw_path.is_absolute()
            else (project_root / raw_path).resolve()
        )
        if not _is_within(clip_path, project_root):
            raise PersianVideoWorkflowError(
                f"asset clip must stay inside the current project: {clip_path}"
            )
        if not clip_path.is_file():
            raise PersianVideoWorkflowError(f"asset clip file does not exist: {clip_path}")
        if clip.get("skipped_existing"):
            continue
        try:
            clip_bytes = int(clip["file_size_bytes"])
        except (KeyError, TypeError, ValueError) as exc:
            raise PersianVideoWorkflowError(
                "downloaded asset result clips require integer file_size_bytes"
            ) from exc
        if clip_bytes < 0:
            raise PersianVideoWorkflowError("asset clip byte counters must be non-negative")
        if clip_path.stat().st_size != clip_bytes:
            raise PersianVideoWorkflowError(
                "asset result file_size_bytes does not match the clip on disk"
            )
        if clip_bytes > clip_ceiling:
            raise PersianVideoWorkflowError("asset result exceeded its issued per-clip byte ceiling")

    identified_clips = [
        dict(clip) for clip in clips
        if isinstance(clip, Mapping)
        and str(clip.get("source") or clip.get("provider") or "").strip()
        and str(clip.get("source_id") or clip.get("clip_id") or "").strip()
    ]
    if identified_clips:
        record_discovery_pass(project_root, retry_pass, identified_clips)

    candidates += int(usage.get("candidates_considered", 0))
    semantic_candidates += int(
        usage.get("semantic_candidates_reviewed", usage.get("candidates_considered", 0))
    )
    technical_rejects += int(usage.get("technical_rejects", 0))
    duplicate_technical_rejects += int(usage.get("duplicate_technical_rejects", 0))
    downloaded_bytes += int(usage.get("bytes_downloaded", 0))
    if semantic_candidates > policy["max_candidates_total"]:
        raise PersianVideoWorkflowError("asset semantic candidate budget exceeded")
    if downloaded_bytes > policy["max_total_download_bytes"]:
        raise PersianVideoWorkflowError("asset download-byte budget exceeded")
    usage.pop("pending_pass", None)
    usage.pop("pending_output_dir", None)
    usage.pop("pending_limits", None)
    usage.update(
        completed_passes=completed_passes + [retry_pass],
        candidates_considered=candidates,
        semantic_candidates_reviewed=semantic_candidates,
        technical_rejects=technical_rejects,
        duplicate_technical_rejects=duplicate_technical_rejects,
        bytes_downloaded=downloaded_bytes,
        workspace_discovery_candidates=asset_workspace_status(project_root)["discoveryCandidateCount"],
        workspace_discovery_passes=asset_workspace_status(project_root)["discoveryPassCount"],
    )
    state["asset_usage"] = usage
    _write_state(_project_root(state), state)
    return state


def _require_asset_candidate_phase(state: Mapping[str, Any]) -> None:
    if state.get("status") != "active" or state.get("next_phase") != "acquire_assets":
        raise PersianVideoWorkflowError(
            "asset candidate lifecycle is available only during active acquire_assets"
        )


def stage_workflow_asset_candidate(
    project_id: str, input_path: str | Path, *, pipeline_dir: Path | None = None
) -> dict[str, Any]:
    state = load_workflow_state(project_id, pipeline_dir=pipeline_dir)
    _require_asset_candidate_phase(state)
    source = assert_read_allowed(state, str(input_path))
    payload = _read_json(str(source))
    return stage_asset_candidate(
        _project_root(state),
        discovery_id=str(payload.get("discovery_id") or payload.get("discoveryId") or ""),
        visual_event_id=str(payload.get("visual_event_id") or payload.get("visualEventId") or ""),
        semantic_beat_id=str(payload.get("semantic_beat_id") or payload.get("semanticBeatId") or ""),
        narrative_role=(str(payload.get("narrative_role") or payload.get("narrativeRole") or "") or None),
        source_in_seconds=payload.get("source_in_seconds", payload.get("sourceInSeconds", 0.0)),
        duration_seconds=payload.get("duration_seconds", payload.get("durationSeconds")),
        intended_crop=payload.get("intended_crop") or payload.get("intendedCrop") or {},
        candidate_rank=payload.get("candidate_rank", payload.get("candidateRank")),
        query=str(payload.get("query") or ""),
        narration_span=str(payload.get("narration_span") or payload.get("narrationSpan") or ""),
    )


def review_workflow_asset_candidate(
    project_id: str, candidate_id: str, input_path: str | Path, *, pipeline_dir: Path | None = None
) -> dict[str, Any]:
    state = load_workflow_state(project_id, pipeline_dir=pipeline_dir)
    _require_asset_candidate_phase(state)
    source = assert_read_allowed(state, str(input_path))
    return record_candidate_review(
        _project_root(state), candidate_id, _read_json(str(source))
    )


def reject_workflow_asset_candidate(
    project_id: str, candidate_id: str, *, category: str, reason: str,
    pipeline_dir: Path | None = None,
) -> dict[str, Any]:
    state = load_workflow_state(project_id, pipeline_dir=pipeline_dir)
    _require_asset_candidate_phase(state)
    return reject_asset_candidate(
        _project_root(state), candidate_id, category=category, reason=reason
    )


def select_workflow_asset_candidate(
    project_id: str, visual_event_id: str, candidate_id: str, *,
    rejected_alternatives: Mapping[str, str], replace_existing: bool = False,
    pipeline_dir: Path | None = None,
) -> dict[str, Any]:
    state = load_workflow_state(project_id, pipeline_dir=pipeline_dir)
    _require_asset_candidate_phase(state)
    return select_asset_candidate(
        _project_root(state), visual_event_id, candidate_id,
        rejected_alternatives=rejected_alternatives,
        replace_existing=replace_existing,
    )


def _candidate_path(project_root: Path, reported: str) -> Path:
    raw = Path(reported).expanduser()
    path = raw.resolve() if raw.is_absolute() else (project_root / raw).resolve()
    if not _is_within(path, project_root):
        raise PersianVideoWorkflowError(
            f"final candidate must live inside its own project: {path}"
        )
    if not path.is_file():
        raise PersianVideoWorkflowError(f"final candidate file does not exist: {path}")
    return path


def _project_file(state: Mapping[str, Any], reported: object, *, label: str) -> Path:
    raw = Path(str(reported or "").strip()).expanduser()
    if not str(reported or "").strip():
        raise PersianVideoWorkflowError(f"{label} path is required")
    project_root = _project_root(state)
    path = raw.resolve() if raw.is_absolute() else (project_root / raw).resolve()
    if not _is_within(path, project_root):
        raise PersianVideoWorkflowError(f"{label} must live inside its own project: {path}")
    if not path.is_file():
        raise PersianVideoWorkflowError(f"{label} file does not exist: {path}")
    return path



def _final_review_quality_evidence(
    report: Mapping[str, Any], *, hook_review: Mapping[str, Any] | None
) -> dict[str, Any]:
    """Compose normalized final-review evidence while preserving source domains.

    Legacy render reports may omit ``quality_evidence``. When a render report does
    declare normalized evidence, it must still match the raw authored-retention and
    rendered-motion sources exactly; final-review semantic observations are layered
    on only after that render-time identity has been verified.
    """
    retention = report.get("retention_audit")
    motion = report.get("post_render_motion_qa")
    if not isinstance(retention, Mapping):
        raise PersianVideoWorkflowError("final review requires render_report.retention_audit")
    if not isinstance(motion, Mapping):
        raise PersianVideoWorkflowError("final review requires render_report.post_render_motion_qa")
    render_quality = compose_quality_evidence(retention, motion)
    declared = report.get("quality_evidence")
    if declared is not None:
        if not isinstance(declared, Mapping) or dict(declared) != render_quality:
            raise PersianVideoWorkflowError(
                "render_report.quality_evidence must match normalized retention/motion source evidence"
            )
    return compose_quality_evidence(retention, motion, hook_review=hook_review)

def _final_quality_evidence_artifact(
    state: Mapping[str, Any], quality: Mapping[str, Any], evidence: Mapping[str, Any]
) -> dict[str, str]:
    """Persist once, then verify the normalized final-review evidence by digest."""
    reported_path = str(evidence.get("quality_evidence_path") or "").strip()
    reported_sha = str(evidence.get("quality_evidence_sha256") or "").strip().lower()
    if reported_path or reported_sha:
        if not reported_path or not reported_sha:
            raise PersianVideoWorkflowError(
                "final quality evidence requires both path and sha256 once persisted"
            )
        path = _project_file(state, reported_path, label="final quality evidence")
        actual_sha = _hash_file(path)
        if actual_sha != reported_sha:
            raise PersianVideoWorkflowError(
                "quality evidence artifact changed after the final review phase completed"
            )
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise PersianVideoWorkflowError(
                "final quality evidence artifact is unreadable JSON"
            ) from exc
        if payload != dict(quality):
            raise PersianVideoWorkflowError(
                "final quality evidence artifact no longer matches normalized review evidence"
            )
        return {"path": str(path), "sha256": actual_sha}

    path = _project_root(state) / "artifacts" / "final_quality_evidence.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps(dict(quality), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temp.replace(path)
    return {"path": str(path), "sha256": _hash_file(path)}


def _render_report_review_fields(report: Mapping[str, Any]) -> None:
    retention = report.get("retention_audit")
    if not isinstance(retention, Mapping):
        raise PersianVideoWorkflowError("final review requires render_report.retention_audit")
    problems = retention.get("problems")
    if not isinstance(problems, list):
        raise PersianVideoWorkflowError("retention_audit.problems must be a list")
    if problems:
        raise PersianVideoWorkflowError("retention_audit has blocking problems; revise before human review")

    motion = report.get("post_render_motion_qa")
    if not isinstance(motion, Mapping):
        raise PersianVideoWorkflowError("final review requires render_report.post_render_motion_qa")
    if motion.get("passed") is not True or list(motion.get("failRuns") or []):
        raise PersianVideoWorkflowError(
            "post_render_motion_qa failed the anti-slideshow gate; revise before human review"
        )

    silent = report.get("silent_watch_audit")
    if not isinstance(silent, Mapping):
        raise PersianVideoWorkflowError("final review requires render_report.silent_watch_audit")
    for field in ("main_point_understood", "hook_direction_understood", "conclusion_understood"):
        if silent.get(field) is not True:
            raise PersianVideoWorkflowError(
                f"silent_watch_audit.{field} must be true after watching the rendered candidate muted"
            )
    if not list(silent.get("notes") or []):
        raise PersianVideoWorkflowError("silent_watch_audit.notes must record what was understood while muted")

    for field in ("cut_rhythm", "caption_readability", "strongest_scene", "weakest_scene"):
        if not str(report.get(field) or "").strip():
            raise PersianVideoWorkflowError(f"final review requires non-empty render_report.{field}")
    if str(report.get("strongest_scene") or "").strip() == str(report.get("weakest_scene") or "").strip():
        raise PersianVideoWorkflowError("strongest_scene and weakest_scene must identify different review findings")
    for field in ("hook_strength", "resolution_strength"):
        value = str(report.get(field) or "").strip()
        if value not in {"acceptable", "strong"}:
            raise PersianVideoWorkflowError(
                f"render_report.{field} must be acceptable or strong before human review"
            )


def _required_preflight_hook_quality(state: Mapping[str, Any]) -> dict[str, Any] | None:
    phase_evidence = (state.get("evidence") or {}).get("no_copy_preflight")
    if not isinstance(phase_evidence, Mapping):
        return None
    reported_path = phase_evidence.get("preflight_report_path")
    if not str(reported_path or "").strip():
        return None
    report_path = _project_file(state, reported_path, label="no-copy preflight report")
    reported_sha = str(phase_evidence.get("preflight_report_sha256") or "").strip().lower()
    if reported_sha and _hash_file(report_path) != reported_sha:
        raise PersianVideoWorkflowError("no-copy preflight report changed after completion")
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PersianVideoWorkflowError("no-copy preflight report is unreadable JSON") from exc
    audit = ((report.get("evidence") or {}).get("hookQualityAudit")) if isinstance(report, Mapping) else None
    if not isinstance(audit, Mapping) or audit.get("required") is not True:
        return None
    if str(audit.get("disposition") or "") not in {"acceptable", "strong"} or list(audit.get("problems") or []):
        raise PersianVideoWorkflowError("required preflight hook-quality audit is not passing")
    return dict(audit)


def _validate_cold_viewer_input_artifact(
    state: Mapping[str, Any], metadata: Mapping[str, Any], hook_review: Mapping[str, Any],
    *, candidate_sha256: str,
) -> dict[str, str]:
    ref = metadata.get("coldViewerReviewInput")
    if not isinstance(ref, Mapping):
        raise PersianVideoWorkflowError(
            "passing Hook Quality v2 review requires a digest-bound cold-viewer review input artifact"
        )
    path = _project_file(state, ref.get("path"), label="cold-viewer review input")
    actual_sha = _hash_file(path)
    declared_sha = str(ref.get("sha256") or "").strip().lower()
    if declared_sha != actual_sha:
        raise PersianVideoWorkflowError(
            "cold-viewer review input sha256 does not match the persisted artifact bytes"
        )
    cold = hook_review.get("coldViewer")
    if not isinstance(cold, Mapping):
        raise PersianVideoWorkflowError("hook review is missing cold-viewer evidence")
    reviewed_input_sha = str(cold.get("reviewInputSha256") or "").strip().lower()
    if reviewed_input_sha != actual_sha:
        raise PersianVideoWorkflowError(
            "cold-viewer review result is not bound to the persisted review input digest"
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PersianVideoWorkflowError("cold-viewer review input is unreadable JSON") from exc
    if not isinstance(payload, Mapping):
        raise PersianVideoWorkflowError("cold-viewer review input must be a JSON object")
    try:
        validate_cold_viewer_review_input(payload, candidate_sha256=candidate_sha256)
    except PersianRenderedReviewError as exc:
        raise PersianVideoWorkflowError(str(exc)) from exc
    return {"path": str(path), "sha256": actual_sha}


def _validate_final_review_completion(
    state: Mapping[str, Any], evidence: Mapping[str, Any]
) -> dict[str, Any]:
    candidate = _validate_awaiting_human_candidate(state, require_final_review=False)
    review_path = _project_file(state, evidence.get("final_review_path"), label="final_review artifact")
    try:
        review = json.loads(review_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PersianVideoWorkflowError("final_review artifact is unreadable JSON") from exc
    if not isinstance(review, dict):
        raise PersianVideoWorkflowError("final_review artifact must be a JSON object")

    metadata = review.get("metadata")
    hook_review = metadata.get("hookQualityReview") if isinstance(metadata, Mapping) else None
    hook_review_strength = (
        str(hook_review.get("strength") or "").strip() if isinstance(hook_review, Mapping) else None
    )
    preflight_hook = _required_preflight_hook_quality(state)
    if preflight_hook is not None:
        if not isinstance(metadata, Mapping) or not isinstance(hook_review, Mapping):
            raise PersianVideoWorkflowError(
                "final_review hook-quality review is required because no_copy_preflight recorded a required hook audit"
            )
        if metadata.get("hookQualityAudit") != preflight_hook:
            raise PersianVideoWorkflowError(
                "final_review hookQualityAudit does not match preflight hookQualityAudit"
            )

    # The durable workflow hook selection is the only thing that can grant a
    # late-payoff exception, so it is resolved here and enforced by the durable-aware
    # validator. The artifact-contract layer only checks evidence shape.
    hook_timing = resolve_hook_timing_authority(state.get("hook_selection"))
    if (
        isinstance(hook_review, Mapping)
        and str(hook_review.get("version") or "") in HOOK_RENDER_REVIEW_VERSIONS
    ):
        try:
            validate_rendered_hook_review(
                hook_review,
                candidate_sha256=candidate["candidate_sha256"],
                require_pass=review.get("status") == "pass",
                hook_timing=hook_timing,
            )
        except PersianRenderedReviewError as exc:
            raise PersianVideoWorkflowError(
                f"final_review hook-quality review failed: {exc}"
            ) from exc
    elif preflight_hook is not None and str(preflight_hook.get("version") or "") == "2.0":
        raise PersianVideoWorkflowError(
            "final_review hook-quality review must use rendered Hook Quality v2 evidence"
        )

    try:
        validate_artifact("final_review", review)
    except ValidationError as exc:
        raise PersianVideoWorkflowError(f"final_review artifact fails schema: {exc.message}") from exc
    if review.get("status") != "pass" or review.get("recommended_action") != "present_to_user":
        raise PersianVideoWorkflowError(
            "final_review must pass with recommended_action='present_to_user' before human review"
        )
    reviewed_output = _project_file(state, review.get("output_path"), label="final_review output")
    if reviewed_output != Path(candidate["candidate_path"]).resolve():
        raise PersianVideoWorkflowError("final_review output_path does not match the digest-bound candidate")

    checks = review.get("checks") or {}
    technical = checks.get("technical_probe") or {}
    if technical.get("valid_container") is not True or list(technical.get("issues") or []):
        raise PersianVideoWorkflowError("final_review technical_probe must pass without issues")
    visual = checks.get("visual_spotcheck") or {}
    if int(visual.get("frames_sampled") or 0) < 4:
        raise PersianVideoWorkflowError("final_review visual_spotcheck requires at least four sampled frames")
    for field in ("black_frames_detected", "broken_overlays", "missing_assets", "unreadable_text"):
        if visual.get(field) is not False:
            raise PersianVideoWorkflowError(f"final_review visual_spotcheck.{field} must be false")
    if list(visual.get("issues") or []):
        raise PersianVideoWorkflowError("final_review visual_spotcheck must pass without issues")
    frame_paths = list(visual.get("frame_paths") or [])
    if len(frame_paths) < 4:
        raise PersianVideoWorkflowError("final_review must retain paths for at least four reviewed frames")
    for frame in frame_paths:
        _project_file(state, frame, label="final_review frame")

    audio = checks.get("audio_spotcheck") or {}
    if not isinstance(audio, Mapping):
        raise PersianVideoWorkflowError("final_review audio_spotcheck must be an evidence object")
    try:
        validate_rendered_audio_review(
            audio,
            candidate_sha256=candidate["candidate_sha256"],
            require_pass=True,
        )
    except PersianRenderedReviewError as exc:
        raise PersianVideoWorkflowError(
            f"final_review rendered audio evidence failed: {exc}"
        ) from exc

    promise = checks.get("promise_preservation") or {}
    if promise.get("delivery_promise_honored") is not True:
        raise PersianVideoWorkflowError("final_review delivery promise must be honored")
    if promise.get("runtime_swap_detected") is not False or promise.get("silent_downgrade_detected") is not False:
        raise PersianVideoWorkflowError("final_review detected a renderer/runtime downgrade")
    if list(promise.get("issues") or []):
        raise PersianVideoWorkflowError("final_review promise_preservation must pass without issues")

    subtitle = checks.get("subtitle_check") or {}
    if subtitle.get("subtitles_expected") is True and subtitle.get("subtitles_present") is not True:
        raise PersianVideoWorkflowError("final_review expected subtitles/captions but did not find them")
    if subtitle.get("timing_drift_detected") is True or list(subtitle.get("issues") or []):
        raise PersianVideoWorkflowError("final_review subtitle/caption check has blocking issues")

    project_id = str(state["project_id"])
    projects_root = Path(str(state["projects_root"])).resolve()
    checkpoint = read_checkpoint(projects_root, project_id, "compose")
    report = (checkpoint.get("artifacts") or {}).get("render_report") if checkpoint else None
    if not isinstance(report, Mapping):
        raise PersianVideoWorkflowError("compose checkpoint is missing render_report")
    _render_report_review_fields(report)
    quality_evidence = _final_review_quality_evidence(report, hook_review=hook_review)
    if hook_review_strength is not None and str(report.get("hook_strength") or "").strip() != hook_review_strength:
        raise PersianVideoWorkflowError(
            "render_report.hook_strength must match final_review hook-quality review strength"
        )
    if str(report.get("caption_mode") or "") in {"burned_captions", "hybrid"}:
        caption_frames = list(report.get("caption_verification_frames") or [])
        if len(caption_frames) < 3:
            raise PersianVideoWorkflowError(
                "burned/hybrid final review requires caption_verification_frames for entry/mid/exit"
            )
        for frame in caption_frames:
            _project_file(state, frame, label="caption verification frame")
    report_ref = _project_file(state, report.get("final_review_ref"), label="render_report.final_review_ref")
    if report_ref != review_path:
        raise PersianVideoWorkflowError("render_report.final_review_ref does not point at the reviewed artifact")

    cold_input: dict[str, str] | None = None
    if (
        isinstance(hook_review, Mapping)
        and str(hook_review.get("version") or "") in HOOK_RENDER_REVIEW_VERSIONS
    ):
        if not isinstance(metadata, Mapping):
            raise PersianVideoWorkflowError("Hook Quality v2 final review requires metadata")
        cold_input = _validate_cold_viewer_input_artifact(
            state, metadata, hook_review, candidate_sha256=candidate["candidate_sha256"]
        )

    quality_ref = _final_quality_evidence_artifact(state, quality_evidence, evidence)

    return {
        "final_review_path": str(review_path),
        "final_review_sha256": _hash_file(review_path),
        "candidate_path": candidate["candidate_path"],
        "candidate_sha256": candidate["candidate_sha256"],
        "quality_evidence_path": quality_ref["path"],
        "quality_evidence_sha256": quality_ref["sha256"],
        **({
            "cold_viewer_input_path": cold_input["path"],
            "cold_viewer_input_sha256": cold_input["sha256"],
        } if cold_input is not None else {}),
    }


def _validate_awaiting_human_candidate(
    state: Mapping[str, Any], *, require_final_review: bool = True
) -> dict[str, Any]:
    project_id = str(state["project_id"])
    projects_root = Path(str(state["projects_root"])).resolve()
    try:
        checkpoint = read_checkpoint(projects_root, project_id, "compose")
    except (CheckpointValidationError, OSError, json.JSONDecodeError) as exc:
        raise PersianVideoWorkflowError(
            "compose checkpoint is invalid or unreadable"
        ) from exc
    if not checkpoint:
        raise PersianVideoWorkflowError("compose checkpoint is required before awaiting_human")
    if checkpoint.get("project_id") != project_id:
        raise PersianVideoWorkflowError("compose checkpoint belongs to another project")
    if checkpoint.get("stage") != "compose":
        raise PersianVideoWorkflowError("checkpoint_compose.json must identify stage='compose'")
    if checkpoint.get("pipeline_type") != "persian-footage":
        raise PersianVideoWorkflowError("compose checkpoint belongs to another pipeline")
    if checkpoint.get("status") != "awaiting_human":
        raise PersianVideoWorkflowError("compose checkpoint must have status='awaiting_human'")
    if checkpoint.get("human_approval_required") is not True:
        raise PersianVideoWorkflowError("compose checkpoint must require human approval")
    if checkpoint.get("human_approved") is not False:
        raise PersianVideoWorkflowError("final candidate must remain unapproved")

    report = (checkpoint.get("artifacts") or {}).get("render_report")
    if not isinstance(report, Mapping):
        raise PersianVideoWorkflowError("compose checkpoint is missing render_report")
    if (
        report.get("delivery_status") != "final_candidate"
        or report.get("human_visual_approval") is not False
        or report.get("persian_text_verified") is not False
    ):
        raise PersianVideoWorkflowError(
            "terminal candidate must be final_candidate with both approval flags false"
        )
    outputs = report.get("outputs")
    if not isinstance(outputs, Sequence) or not outputs or not isinstance(outputs[0], Mapping):
        raise PersianVideoWorkflowError("render_report.outputs[0] is required")
    primary = outputs[0]
    reported_path = str(primary.get("path") or "").strip()
    if not reported_path or str(primary.get("format") or "").strip().lower() != "mp4":
        raise PersianVideoWorkflowError("final candidate primary output must be a reported MP4 path")
    reported_digest = str(primary.get("sha256") or "").strip().lower()
    if len(reported_digest) != 64 or any(ch not in "0123456789abcdef" for ch in reported_digest):
        raise PersianVideoWorkflowError("final candidate requires a lowercase 64-character sha256")

    project_root = _project_root(state)
    candidate = _candidate_path(project_root, reported_path)
    actual_digest = _hash_file(candidate)
    if actual_digest != reported_digest:
        raise PersianVideoWorkflowError(
            "final candidate sha256 does not match the exact MP4 bytes"
        )
    result = {
        "candidate_path": str(candidate),
        "candidate_sha256": actual_digest,
        "checkpoint": "checkpoint_compose.json",
    }
    if require_final_review:
        review_evidence = (state.get("evidence") or {}).get("final_review")
        if not isinstance(review_evidence, Mapping):
            raise PersianVideoWorkflowError("validated final_review evidence is required before awaiting_human")
        verified = _validate_final_review_completion(state, review_evidence)
        if verified["final_review_sha256"] != str(review_evidence.get("final_review_sha256") or ""):
            raise PersianVideoWorkflowError("final_review artifact changed after the review phase completed")
        if verified["candidate_sha256"] != actual_digest:
            raise PersianVideoWorkflowError("final_review was performed on a different candidate digest")
        result.update({
            "final_review_path": verified["final_review_path"],
            "final_review_sha256": verified["final_review_sha256"],
        })
    return result



def reconcile_approved_compose_checkpoint(
    project_id: str,
    *,
    pipeline_dir: Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Consume one checkpoint-validated explicit approval into workflow truth.

    The checkpoint protocol remains the authority for approval provenance. This seam
    only reconciles the front-door state so `checkpoint_compose=completed` can never
    coexist indefinitely with workflow `status=awaiting_human`.
    """
    state = load_workflow_state(project_id, pipeline_dir=pipeline_dir)
    status = str(state.get("status") or "")
    completed_phases = list(state.get("completed_phases") or [])
    active_at_final_gate = (
        status == "active"
        and state.get("next_phase") == "awaiting_human"
        and "final_review" in completed_phases
    )
    if status not in {"awaiting_human", "completed"} and not active_at_final_gate:
        raise PersianVideoWorkflowError(
            "approval reconciliation requires workflow awaiting_human/completed or "
            "active at the final awaiting_human gate after final_review"
        )
    projects_root = Path(str(state.get("projects_root") or PROJECTS_DIR)).resolve()
    try:
        checkpoint = read_checkpoint(projects_root, project_id, "compose")
    except (CheckpointValidationError, OSError, json.JSONDecodeError) as exc:
        raise PersianVideoWorkflowError("approved compose checkpoint is invalid") from exc
    if not isinstance(checkpoint, Mapping):
        raise PersianVideoWorkflowError("approved compose checkpoint is required")
    if (
        checkpoint.get("project_id") != project_id
        or checkpoint.get("pipeline_type") != "persian-footage"
        or checkpoint.get("stage") != "compose"
        or checkpoint.get("status") != "completed"
        or checkpoint.get("human_approved") is not True
    ):
        raise PersianVideoWorkflowError(
            "compose checkpoint must be completed with human_approved=true"
        )
    report = (checkpoint.get("artifacts") or {}).get("render_report")
    if not isinstance(report, Mapping) or (
        report.get("delivery_status") != "approved"
        or report.get("human_visual_approval") is not True
        or not isinstance(report.get("persian_text_verified"), bool)
    ):
        raise PersianVideoWorkflowError("approved render_report flags are invalid")
    outputs = report.get("outputs")
    if not isinstance(outputs, Sequence) or not outputs or not isinstance(outputs[0], Mapping):
        raise PersianVideoWorkflowError("approved render_report.outputs[0] is required")
    primary = outputs[0]
    candidate = _candidate_path(_project_root(state), str(primary.get("path") or ""))
    reported_digest = str(primary.get("sha256") or "").strip().lower()
    actual_digest = _hash_file(candidate)
    if actual_digest != reported_digest:
        raise PersianVideoWorkflowError("approved candidate sha256 does not match exact MP4 bytes")
    metadata = checkpoint.get("metadata")
    approval_record = metadata.get("approval_record") if isinstance(metadata, Mapping) else None
    if not isinstance(approval_record, Mapping) or (
        approval_record.get("source") != "explicit_user_response"
        or str(approval_record.get("candidate_path") or "").strip() != str(candidate)
        or str(approval_record.get("candidate_sha256") or "").strip().lower() != actual_digest
    ):
        raise PersianVideoWorkflowError("approved compose checkpoint lacks exact explicit approval provenance")
    approval_raw = str(
        approval_record.get("approved_at")
        or checkpoint.get("timestamp")
        or ""
    ).strip()
    approved_at = _parse_timestamp(approval_raw) if approval_raw else (now or datetime.now(timezone.utc))
    if now is not None and approved_at > now:
        approved_at = now

    if state.get("status") != "completed":
        if status == "awaiting_human":
            record_human_idle_and_reopen_run(
                state, resumed_at=approved_at, reason="explicit final candidate approval"
            )
        trace = state.get("causal_telemetry")
        if isinstance(trace, Mapping) and trace.get("run_span_id"):
            finish_causal_span(
                state, str(trace["run_span_id"]),
                finished_at=approved_at, outcome="completed",
            )
        state["status"] = "completed"
        state["next_phase"] = None
        if "awaiting_human" not in completed_phases:
            completed_phases.append("awaiting_human")
        state["completed_phases"] = completed_phases
        state["approval"] = {
            "source": "explicit_user_response",
            "approved_at": approved_at.isoformat(),
            "candidate_path": str(candidate),
            "candidate_sha256": actual_digest,
            "persian_text_verified": bool(report.get("persian_text_verified")),
        }
        reconcile_phase_telemetry(state, now=approved_at)
        _freeze_performance_summary(state, now=approved_at)
        _write_state(_project_root(state), state)
    return state


def _last_project_write(project_root: Path) -> tuple[str | None, datetime | None]:
    latest_path: Path | None = None
    latest_mtime = -1.0
    for candidate in project_root.rglob("*"):
        if not candidate.is_file():
            continue
        try:
            modified = candidate.stat().st_mtime
        except OSError:
            continue
        if modified > latest_mtime:
            latest_path = candidate
            latest_mtime = modified
    if latest_path is None:
        return None, None
    return str(latest_path.relative_to(project_root)), datetime.fromtimestamp(
        latest_mtime, tz=timezone.utc
    )


def workflow_status(
    project_id: str, *, pipeline_dir: Path | None = None, now: datetime | None = None
) -> dict[str, Any]:
    state = load_workflow_state(project_id, pipeline_dir=pipeline_dir)
    current = now or datetime.now(timezone.utc)
    input_record = dict(state.get("input") or {})
    phase = state.get("next_phase")
    phase_elapsed = (
        _phase_elapsed_seconds(state, str(phase), now=current) if phase in PHASES else 0.0
    )
    window_started = _parse_timestamp(
        str(state.get("budget_window_started_at") or state.get("created_at") or "")
    )
    total_elapsed = max(0.0, (current - window_started).total_seconds())
    budget_seconds = int((state.get("budgets") or {}).get("max_wall_time_minutes", 0)) * 60
    last_path, last_at = _last_project_write(_project_root(state))
    idle_seconds = None if last_at is None else max(0.0, (current - last_at).total_seconds())
    activity = "idle" if idle_seconds is None or idle_seconds >= 15 * 60 else "progressing"
    return {
        "project_id": state["project_id"],
        "status": state["status"],
        "next_phase": state.get("next_phase"),
        "input_mode": input_record.get("mode"),
        "script_authority": input_record.get("script_authority"),
        "completed_phases": state.get("completed_phases", []),
        "attempts": state.get("attempts", {}),
        "send_backs": state.get("send_backs", 0),
        "recovery_attempts": state.get("recovery_attempts", {}),
        "recovery_stop": state.get("recovery_stop"),
        "convergence": convergence_status(
            _project_root(state),
            revision_cycle=int(state.get("user_revision_cycles") or 0),
        ),
        "asset_usage": state.get("asset_usage", {}),
        "asset_workspace": asset_workspace_status(_project_root(state)),
        "alignment_policy": state.get("alignment_policy") or alignment_execution_policy(state),
        "causal_trace_id": (state.get("causal_telemetry") or {}).get("trace_id"),
        "time_accounting": phase_time_accounting(state),
        "performance_slo": state.get("performance_slo"),
        "performance_summary": state.get("performance_summary"),
        "budget_stop": state.get("budget_stop"),
        "operational_summary": {
            "phase": phase,
            "phase_elapsed_seconds": round(phase_elapsed, 3),
            "total_elapsed_seconds": round(total_elapsed, 3),
            "wall_budget_seconds": budget_seconds,
            "last_written_file": last_path,
            "last_write_at": last_at.isoformat() if last_at else None,
            "idle_seconds": round(idle_seconds, 3) if idle_seconds is not None else None,
            "activity": activity,
        },
    }


def format_status_line(status: Mapping[str, Any]) -> str:
    summary = status.get("operational_summary") or {}
    return (
        f"project={status.get('project_id')} status={status.get('status')} "
        f"phase={summary.get('phase') or '-'} "
        f"phase_elapsed={summary.get('phase_elapsed_seconds', 0):.3f}s "
        f"total={summary.get('total_elapsed_seconds', 0):.3f}/"
        f"{summary.get('wall_budget_seconds', 0)}s "
        f"last_write={summary.get('last_written_file') or '-'} "
        f"activity={summary.get('activity') or 'idle'}"
    )


def _load_text_file(path: str) -> str:
    if str(path).strip() == "-":
        text = sys.stdin.read()
        if not text.strip():
            raise PersianVideoWorkflowError("approved script stdin must not be empty")
        return text
    source = Path(path).expanduser().resolve()
    if _is_within(source, REPO_ROOT.resolve()):
        raise PersianVideoWorkflowError(
            "refusing approved-script scratch from the repository; use --approved-script, "
            "--approved-script-file -, or a source file outside the repository"
        )
    if not source.is_file():
        raise PersianVideoWorkflowError(f"text input file does not exist: {source}")
    return source.read_text(encoding="utf-8")


def _add_bootstrap_inputs(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--narration", metavar="PATH")
    script = parser.add_mutually_exclusive_group()
    script.add_argument("--approved-script", metavar="TEXT")
    script.add_argument("--approved-script-file", metavar="PATH")
    parser.add_argument("--hook", metavar="TEXT", help="authoritative opening hook; bypasses automatic hook selection")


def _bootstrap_inputs(args: argparse.Namespace) -> tuple[str | None, str | None]:
    narration = args.narration
    approved_script = args.approved_script
    if args.approved_script_file is not None:
        approved_script = _load_text_file(args.approved_script_file)
    if narration is None and approved_script is None:
        raise PersianVideoWorkflowError(
            "bootstrap requires --narration and/or --approved-script/--approved-script-file"
        )
    return narration, approved_script


def resume_workflow(
    project_id: str,
    *,
    pipeline_dir: Path | None = None,
    backlot_opener: Callable[[str | None], int] = open_backlot,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Start a fresh wall-time window without resetting durable workflow budgets."""
    state = reconcile_workflow_state(project_id, pipeline_dir=pipeline_dir)
    stamp = now or datetime.now(timezone.utc)
    state["budget_window_started_at"] = stamp.isoformat()
    state["resumed_at"] = stamp.isoformat()
    try:
        code = int(backlot_opener(project_id))
    except Exception:
        code = 1
    history = list(state.get("backlot_resume_attempts") or [])
    history.append({"at": stamp.isoformat(), "exit_code": code})
    state["backlot_resume_attempts"] = history
    _write_state(_project_root(state), state)
    return state


def _terminalize_from_convergence_stop(
    state: dict[str, Any], convergence: Mapping[str, Any], *, revision_cycle: int
) -> bool:
    unresolved = convergence.get("unresolved")
    if convergence.get("status") != "needs_revision" or not isinstance(unresolved, Mapping):
        return False
    if int(unresolved.get("revisionCycle") or 0) != int(revision_cycle):
        return False
    if str(unresolved.get("outcome") or "") != "needs_human_editorial_revision":
        return False

    stamp = datetime.now(timezone.utc)
    raw_at = str(unresolved.get("at") or "").strip()
    if raw_at:
        try:
            parsed = datetime.fromisoformat(raw_at.replace("Z", "+00:00"))
            stamp = parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            pass

    diagnostics = unresolved.get("unresolvedDiagnostics")
    first_diagnostic = (
        diagnostics[0]
        if isinstance(diagnostics, list)
        and diagnostics
        and isinstance(diagnostics[0], Mapping)
        else {}
    )
    stop = {
        "at": raw_at or stamp.isoformat(),
        "diagnosticCode": str(first_diagnostic.get("code") or ""),
        "recoveryClass": unresolved.get("recoveryClass"),
        "attemptsUsed": int(unresolved.get("attemptsUsed") or 0),
        "maxAttempts": unresolved.get("maxAttempts"),
        "outcome": "needs_human_editorial_revision",
        "reason": str(unresolved.get("reason") or "convergence_budget_exhausted"),
        "globalCandidatesUsed": int(unresolved.get("globalCandidatesUsed") or 0),
        "globalMaxCandidates": int(unresolved.get("globalMaxCandidates") or 0),
        "revisionCycle": int(revision_cycle),
        "source": "convergence_workspace",
    }
    state["status"] = "needs_revision"
    state["next_phase"] = None
    state["recovery_stop"] = stop
    trace = state.get("causal_telemetry")
    if isinstance(trace, Mapping) and trace.get("run_span_id"):
        finish_causal_span(
            state, str(trace["run_span_id"]), finished_at=stamp, outcome="needs_revision"
        )
    reconcile_phase_telemetry(state, now=stamp)
    _write_state(_project_root(state), state)
    return True


def stage_workflow_edit_draft(
    project_id: str,
    attempt_id: str,
    input_path: str | Path,
    *,
    parent_attempt_id: str | None = None,
    diagnostic_code: str | None = None,
    recovery_class: str | None = None,
    strategy: str | None = None,
    changed_fields: Sequence[str] | None = None,
    pipeline_dir: Path | None = None,
) -> dict[str, Any]:
    state = load_workflow_state(project_id, pipeline_dir=pipeline_dir)
    if state.get("next_phase") != "no_copy_preflight":
        raise PersianVideoWorkflowError(
            f"edit drafts are only accepted during no_copy_preflight; next phase is {state.get('next_phase')!r}"
        )
    source = assert_read_allowed(state, input_path)
    payload = _read_json(str(source))
    decision = state.get("hook_selection")
    if not isinstance(decision, Mapping):
        raise PersianVideoWorkflowError("workflow is missing its hook-selection authority record")
    authority = validate_edit_hook_authority(decision, payload)

    recovery_metadata_present = any(
        value for value in (diagnostic_code, recovery_class, strategy, list(changed_fields or []))
    )
    if parent_attempt_id and not (diagnostic_code or recovery_class):
        raise PersianVideoWorkflowError(
            "recovery child candidates require --diagnostic-code and/or --recovery-class"
        )
    if recovery_metadata_present and not parent_attempt_id:
        raise PersianVideoWorkflowError(
            "recovery metadata requires --parent so candidate ancestry remains explicit"
        )

    issue: dict[str, Any] | None = None
    if diagnostic_code or recovery_class:
        issue = {}
        if diagnostic_code:
            issue["code"] = str(diagnostic_code)
        if recovery_class:
            issue["recoveryClass"] = str(recovery_class)

    max_candidates = 1 + int((state.get("budgets") or {}).get("max_revisions_per_stage", 0))
    if max_candidates <= 1:
        raise PersianVideoWorkflowError("workflow convergence budget is missing or invalid")
    revision_cycle = int(state.get("user_revision_cycles") or 0)
    current_convergence = convergence_status(
        _project_root(state), revision_cycle=revision_cycle
    )
    if _terminalize_from_convergence_stop(
        state, current_convergence, revision_cycle=revision_cycle
    ):
        raise PersianVideoWorkflowError(
            "convergence workspace requires human editorial revision before more candidates can be staged"
        )
    current_ids = set(str(item) for item in current_convergence.get("candidateIds") or [])
    if parent_attempt_id is None and current_ids and attempt_id not in current_ids:
        raise PersianVideoWorkflowError(
            "base convergence candidate already exists for this revision cycle; "
            "stage recovery as an explicit child with --parent and recovery metadata"
        )
    try:
        staged = stage_edit_draft(
            _project_root(state),
            attempt_id,
            payload,
            parent_attempt_id=parent_attempt_id,
            diagnostic_issue=issue,
            strategy=strategy,
            changed_fields=changed_fields,
            max_candidates=max_candidates,
            revision_cycle=revision_cycle,
            hook_authority=decision,
        )
    except PersianEditWorkspaceError:
        stopped = convergence_status(_project_root(state), revision_cycle=revision_cycle)
        _terminalize_from_convergence_stop(state, stopped, revision_cycle=revision_cycle)
        raise
    return {
        **staged,
        "hookAuthority": authority,
        "convergenceBudget": {
            "maxCandidates": max_candidates,
            "revisionCycle": revision_cycle,
        },
    }


def preflight_workflow_edit_draft(
    project_id: str, attempt_id: str, *, pipeline_dir: Path | None = None,
    recertify_promoted: bool = False,
    recertify_staged: bool = False,
) -> dict[str, Any]:
    state = load_workflow_state(project_id, pipeline_dir=pipeline_dir)
    if state.get("next_phase") != "no_copy_preflight":
        raise PersianVideoWorkflowError(
            f"edit preflight is only valid during no_copy_preflight; next phase is {state.get('next_phase')!r}"
        )
    decision = state.get("hook_selection")
    if not isinstance(decision, Mapping):
        raise PersianVideoWorkflowError("workflow is missing its hook-selection authority record")
    report = preflight_edit_draft(
        _project_root(state),
        attempt_id,
        hook_authority=decision,
        recertify_promoted=recertify_promoted,
        recertify_staged=recertify_staged,
    )
    if report.get("ok") is not True:
        max_candidates = 1 + int((state.get("budgets") or {}).get("max_revisions_per_stage", 0))
        revision_cycle = int(state.get("user_revision_cycles") or 0)
        mark_blocked_convergence_exhausted(
            _project_root(state),
            attempt_id,
            max_candidates=max_candidates,
            revision_cycle=revision_cycle,
        )
        convergence = convergence_status(
            _project_root(state), revision_cycle=revision_cycle
        )
        if _terminalize_from_convergence_stop(
            state, convergence, revision_cycle=revision_cycle
        ):
            report["convergenceStop"] = dict(state.get("recovery_stop") or {})
    return report


def promote_workflow_edit_draft(
    project_id: str, attempt_id: str, *, pipeline_dir: Path | None = None
) -> dict[str, Any]:
    state = load_workflow_state(project_id, pipeline_dir=pipeline_dir)
    if state.get("next_phase") != "no_copy_preflight":
        raise PersianVideoWorkflowError(
            f"edit promotion is only valid during no_copy_preflight; next phase is {state.get('next_phase')!r}"
        )

    project_root = _project_root(state)
    decision = state.get("hook_selection")
    if not isinstance(decision, Mapping):
        raise PersianVideoWorkflowError("workflow is missing its hook-selection authority record")
    edit, _, digest = load_promotable_edit_draft(
        project_root, attempt_id, hook_authority=decision
    )
    try:
        validate_artifact("edit_decisions", edit)
    except Exception as exc:
        raise CheckpointValidationError(
            f"Artifact 'edit_decisions' failed schema validation before promotion: {exc}"
        ) from exc

    canonical = project_root / "artifacts" / "edit_decisions.json"
    previous_exists = canonical.is_file()
    previous_bytes = canonical.read_bytes() if previous_exists else None
    projects_root = Path(str(state.get("projects_root") or PROJECTS_DIR)).resolve()
    try:
        result = promote_edit_draft(
            project_root, attempt_id, hook_authority=decision
        )
        checkpoint_path = write_checkpoint(
            projects_root, project_id, "edit", "completed", {"edit_decisions": edit},
            pipeline_type="persian-footage", human_approval_required=False, human_approved=False,
            metadata={"preflight_attempt_id": attempt_id, "artifact_sha256": digest},
        )
    except Exception:
        # Promotion and checkpoint persistence form one workflow-level transaction:
        # a validation/write failure must never leave canonical edit bytes advanced.
        if previous_exists and previous_bytes is not None:
            canonical.parent.mkdir(parents=True, exist_ok=True)
            rollback = canonical.with_suffix(canonical.suffix + ".rollback.tmp")
            rollback.write_bytes(previous_bytes)
            rollback.replace(canonical)
        elif canonical.exists():
            canonical.unlink()
        raise
    return {**result, "checkpointPath": str(checkpoint_path)}


def compare_workflow_edit_candidates(
    project_id: str,
    left_attempt_id: str,
    right_attempt_id: str,
    *,
    pipeline_dir: Path | None = None,
) -> dict[str, Any]:
    state = load_workflow_state(project_id, pipeline_dir=pipeline_dir)
    if state.get("next_phase") != "no_copy_preflight":
        raise PersianVideoWorkflowError(
            f"edit candidate comparison is only valid during no_copy_preflight; next phase is {state.get('next_phase')!r}"
        )
    return compare_edit_candidates(_project_root(state), left_attempt_id, right_attempt_id)


def start_workflow_job(
    project_id: str, *, job_id: str, phase: str, argv: Sequence[str],
    idempotence_key: str, pipeline_dir: Path | None = None, launch: bool = True,
) -> dict[str, Any]:
    state = load_workflow_state(project_id, pipeline_dir=pipeline_dir)
    if phase not in PHASES or phase != state.get("next_phase"):
        raise PersianVideoWorkflowError(
            f"durable job phase must equal the workflow next phase {state.get('next_phase')!r}; got {phase!r}"
        )
    return start_job(
        _project_root(state), job_id=job_id, phase=phase, argv=argv,
        idempotence_key=idempotence_key, launch=launch,
    )


def reconcile_workflow_job(
    project_id: str, job_id: str, *, pipeline_dir: Path | None = None
) -> dict[str, Any]:
    state = load_workflow_state(project_id, pipeline_dir=pipeline_dir)
    return reconcile_job(_project_root(state), job_id)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="persian-video")
    sub = parser.add_subparsers(dest="command", required=True)

    bootstrap = sub.add_parser("bootstrap", help="create a fresh Persian video project")
    bootstrap.add_argument("--title", required=True)
    bootstrap.add_argument("--project-id")
    _add_bootstrap_inputs(bootstrap)

    attach = sub.add_parser("attach-narration", help="attach audio to a script-first project")
    attach.add_argument("project_id")
    attach.add_argument("path")

    status = sub.add_parser("status", help="show one-line bounded workflow status")
    status.add_argument("project_id")
    status.add_argument("--json", action="store_true", help="emit the full machine-readable state")

    approval_reconcile = sub.add_parser(
        "reconcile-approval",
        help="reconcile an explicit completed compose approval into workflow state",
    )
    approval_reconcile.add_argument("project_id")

    alignment_plan = sub.add_parser(
        "alignment-plan",
        help="probe capability/status and select the policy-valid timing/transcription provider",
    )
    alignment_plan.add_argument("project_id")

    alignment_start = sub.add_parser(
        "alignment-start", help="start canonical durable alignment through the run kernel"
    )
    alignment_start.add_argument("project_id")
    alignment_start.add_argument("--job-id")

    alignment_status = sub.add_parser(
        "alignment-status", help="reconcile one canonical durable alignment job"
    )
    alignment_status.add_argument("project_id")
    alignment_status.add_argument("job_id")

    alignment_commit = sub.add_parser(
        "alignment-commit", help="commit successful durable alignment into workflow state"
    )
    alignment_commit.add_argument("project_id")
    alignment_commit.add_argument("job_id")

    resume = sub.add_parser("resume", help="start a new bounded session and reopen Backlot")
    resume.add_argument("project_id")

    attempt = sub.add_parser("attempt", help="record one phase attempt")
    attempt.add_argument("project_id")
    attempt.add_argument("--phase")

    work_start = sub.add_parser(
        "work-start", help="prospectively start one measured agent/review work interval"
    )
    work_start.add_argument("project_id")
    work_start.add_argument("--category", choices=sorted(_EXPLICIT_WORK_CATEGORIES), required=True)
    work_start.add_argument("--name", required=True)

    work_finish = sub.add_parser(
        "work-finish", help="finish one prospectively measured agent/review work interval"
    )
    work_finish.add_argument("project_id")
    work_finish.add_argument("span_id")
    work_finish.add_argument(
        "--outcome", choices=["succeeded", "failed", "interrupted"], default="succeeded"
    )

    work_abandon = sub.add_parser(
        "work-abandon", help="recover an open work interval with an unknown stop time"
    )
    work_abandon.add_argument("project_id")
    work_abandon.add_argument("span_id")
    work_abandon.add_argument("--reason", required=True)

    complete = sub.add_parser("complete", help="complete exactly one phase")
    complete.add_argument("project_id")
    complete.add_argument("--phase")
    complete.add_argument("--evidence-json")

    recovery = sub.add_parser("recovery-attempt", help="record one bounded deterministic preflight repair")
    recovery.add_argument("project_id")
    recovery.add_argument("--code", required=True)
    recovery.add_argument("--class", dest="recovery_class")
    recovery.add_argument("--strategy", required=True)
    recovery.add_argument("--artifact-sha256")

    send_back = sub.add_parser("send-back", help="rewind within the send-back budget")
    send_back.add_argument("project_id")
    send_back.add_argument("target_phase")
    send_back.add_argument("--reason", required=True)
    send_back.add_argument(
        "--user-directed-revision", action="store_true",
        help="start a fresh bounded revision cycle after explicit new user feedback",
    )

    hook_override = sub.add_parser(
        "hook-override",
        help="bind explicit user hook feedback as authoritative copy in a revision cycle",
    )
    hook_override.add_argument("project_id")
    hook_override.add_argument("--text", required=True)
    hook_override.add_argument("--reason", required=True)

    guard = sub.add_parser("guard-read", help="check one path against the read allowlist")
    guard.add_argument("project_id")
    guard.add_argument("path")

    asset_request = sub.add_parser("asset-request", help="clamp a stock request to workflow budgets")
    asset_request.add_argument("project_id")
    asset_request.add_argument("--retry-pass", type=int, required=True)
    asset_request.add_argument("--json", required=True, metavar="PATH")

    asset_result = sub.add_parser("asset-result", help="account one stock-search result")
    asset_result.add_argument("project_id")
    asset_result.add_argument("--retry-pass", type=int, required=True)
    asset_result.add_argument("--json", required=True, metavar="PATH")

    asset_candidate_stage = sub.add_parser("asset-candidate-stage", help="stage one durable source-window/crop candidate")
    asset_candidate_stage.add_argument("project_id")
    asset_candidate_stage.add_argument("--json", required=True, metavar="PATH")

    asset_candidate_review = sub.add_parser("asset-candidate-review", help="persist immutable review evidence for a candidate")
    asset_candidate_review.add_argument("project_id")
    asset_candidate_review.add_argument("candidate_id")
    asset_candidate_review.add_argument("--json", required=True, metavar="PATH")

    asset_candidate_reject = sub.add_parser("asset-candidate-reject", help="record a technical, semantic, or editorial rejection")
    asset_candidate_reject.add_argument("project_id")
    asset_candidate_reject.add_argument("candidate_id")
    asset_candidate_reject.add_argument("--category", choices=["technical", "semantic", "editorial"], required=True)
    asset_candidate_reject.add_argument("--reason", required=True)

    asset_candidate_select = sub.add_parser("asset-candidate-select", help="select one reviewed candidate for a visual event")
    asset_candidate_select.add_argument("project_id")
    asset_candidate_select.add_argument("visual_event_id")
    asset_candidate_select.add_argument("candidate_id")
    asset_candidate_select.add_argument("--rejections-json", metavar="PATH")
    asset_candidate_select.add_argument("--replace-existing", action="store_true")

    edit_stage = sub.add_parser("edit-stage", help="stage an immutable edit draft inside the project")
    edit_stage.add_argument("project_id")
    edit_stage.add_argument("attempt_id")
    edit_stage.add_argument("--json", required=True, metavar="PATH")
    edit_stage.add_argument("--parent", dest="parent_attempt_id")
    edit_stage.add_argument("--diagnostic-code")
    edit_stage.add_argument("--recovery-class")
    edit_stage.add_argument("--strategy")
    edit_stage.add_argument("--changed-field", dest="changed_fields", action="append")

    edit_preflight = sub.add_parser("edit-preflight", help="preflight one staged edit draft")
    edit_preflight.add_argument("project_id")
    edit_preflight.add_argument("attempt_id")
    edit_preflight.add_argument(
        "--recertify-promoted",
        action="store_true",
        help=(
            "recompute policy/code-dependent preflight evidence for the already-promoted "
            "canonical digest without creating a new convergence candidate"
        ),
    )
    edit_preflight.add_argument(
        "--recertify-staged",
        action="store_true",
        help=(
            "recompute policy/code-dependent preflight evidence for the same immutable "
            "staged/blocked candidate after dependency context changes, without consuming "
            "another convergence candidate"
        ),
    )

    edit_promote = sub.add_parser("edit-promote", help="promote a digest-bound passing edit draft")
    edit_promote.add_argument("project_id")
    edit_promote.add_argument("attempt_id")

    edit_compare = sub.add_parser("edit-compare", help="compare two durable convergence candidates")
    edit_compare.add_argument("project_id")
    edit_compare.add_argument("left_attempt_id")
    edit_compare.add_argument("right_attempt_id")

    job_start = sub.add_parser("job-start", help="start one detached idempotent job for the current phase")
    job_start.add_argument("project_id")
    job_start.add_argument("job_id")
    job_start.add_argument("--phase", required=True)
    job_start.add_argument("--idempotence-key", required=True)
    job_start.add_argument("argv", nargs="+")

    job_status = sub.add_parser("job-status", help="reconcile and show one durable job")
    job_status.add_argument("project_id")
    job_status.add_argument("job_id")
    return parser


def _read_json(path: str) -> dict[str, Any]:
    raw = Path(path).expanduser().resolve()
    try:
        value = json.loads(raw.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PersianVideoWorkflowError(f"could not read JSON object: {raw}") from exc
    if not isinstance(value, dict):
        raise PersianVideoWorkflowError(f"expected a JSON object: {raw}")
    return value


def _print_json(value: Mapping[str, Any]) -> None:
    print(json.dumps(dict(value), ensure_ascii=False, indent=2))


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "bootstrap":
            narration_path, approved_script = _bootstrap_inputs(args)
            state = bootstrap_persian_video(
                title=args.title,
                narration_path=narration_path,
                approved_script=approved_script,
                hook_text=args.hook,
                project_id=args.project_id,
            )
            _print_json(workflow_status(state["project_id"]))
        elif args.command == "attach-narration":
            state = attach_narration(args.project_id, args.path)
            _print_json(workflow_status(state["project_id"]))
        elif args.command == "status":
            status = workflow_status(args.project_id)
            if args.json:
                _print_json(status)
            else:
                print(format_status_line(status))
        elif args.command == "reconcile-approval":
            _print_json(reconcile_approved_compose_checkpoint(args.project_id))
        elif args.command == "alignment-plan":
            _print_json(alignment_provider_plan_for_project(args.project_id))
        elif args.command == "alignment-start":
            _print_json(start_alignment_job_for_project(args.project_id, job_id=args.job_id))
        elif args.command == "alignment-status":
            _print_json(alignment_job_status_for_project(args.project_id, args.job_id))
        elif args.command == "alignment-commit":
            _print_json(commit_alignment_job_for_project(args.project_id, args.job_id))
        elif args.command == "resume":
            _print_json(resume_workflow(args.project_id))
        elif args.command == "attempt":
            state = load_workflow_state(args.project_id)
            phase = args.phase or state.get("next_phase")
            if not phase:
                raise PersianVideoWorkflowError("workflow has no next phase")
            _print_json(record_phase_attempt(args.project_id, str(phase)))
        elif args.command == "work-start":
            _print_json(start_explicit_work_span(
                args.project_id, category=args.category, name=args.name
            ))
        elif args.command == "work-finish":
            _print_json(finish_explicit_work_span(
                args.project_id, args.span_id, outcome=args.outcome
            ))
        elif args.command == "work-abandon":
            _print_json(abandon_explicit_work_span(
                args.project_id, args.span_id, reason=args.reason
            ))
        elif args.command == "complete":
            state = load_workflow_state(args.project_id)
            phase = args.phase or state.get("next_phase")
            if not phase:
                raise PersianVideoWorkflowError("workflow has no next phase")
            evidence = _read_json(args.evidence_json) if args.evidence_json else None
            _print_json(complete_phase(args.project_id, str(phase), evidence=evidence))
        elif args.command == "recovery-attempt":
            _print_json(record_recovery_attempt(
                args.project_id, diagnostic_code=args.code,
                recovery_class=args.recovery_class, strategy=args.strategy,
                artifact_sha256=args.artifact_sha256,
            ))
        elif args.command == "send-back":
            _print_json(
                request_send_back(
                    args.project_id,
                    args.target_phase,
                    reason=args.reason,
                    user_directed_revision=args.user_directed_revision,
                )
            )
        elif args.command == "hook-override":
            _print_json(record_user_hook_override(
                args.project_id, selected_text=args.text, reason=args.reason,
            ))
        elif args.command == "guard-read":
            state = load_workflow_state(args.project_id)
            _print_json({"allowed_path": str(assert_read_allowed(state, args.path))})
        elif args.command == "asset-request":
            _print_json(
                bounded_asset_search_request(
                    args.project_id,
                    _read_json(args.json),
                    retry_pass=args.retry_pass,
                )
            )
        elif args.command == "asset-result":
            _print_json(
                record_asset_search_result(
                    args.project_id,
                    retry_pass=args.retry_pass,
                    result_data=_read_json(args.json),
                )
            )
        elif args.command == "asset-candidate-stage":
            _print_json(stage_workflow_asset_candidate(args.project_id, args.json))
        elif args.command == "asset-candidate-review":
            _print_json(review_workflow_asset_candidate(
                args.project_id, args.candidate_id, args.json
            ))
        elif args.command == "asset-candidate-reject":
            _print_json(reject_workflow_asset_candidate(
                args.project_id, args.candidate_id,
                category=args.category, reason=args.reason,
            ))
        elif args.command == "asset-candidate-select":
            rejections = _read_json(args.rejections_json) if args.rejections_json else {}
            _print_json(select_workflow_asset_candidate(
                args.project_id, args.visual_event_id, args.candidate_id,
                rejected_alternatives={str(k): str(v) for k, v in rejections.items()},
                replace_existing=args.replace_existing,
            ))
        elif args.command == "edit-stage":
            _print_json(stage_workflow_edit_draft(
                args.project_id,
                args.attempt_id,
                args.json,
                parent_attempt_id=args.parent_attempt_id,
                diagnostic_code=args.diagnostic_code,
                recovery_class=args.recovery_class,
                strategy=args.strategy,
                changed_fields=args.changed_fields,
            ))
        elif args.command == "edit-preflight":
            _print_json(preflight_workflow_edit_draft(
                args.project_id,
                args.attempt_id,
                recertify_promoted=args.recertify_promoted,
                recertify_staged=args.recertify_staged,
            ))
        elif args.command == "edit-promote":
            _print_json(promote_workflow_edit_draft(args.project_id, args.attempt_id))
        elif args.command == "edit-compare":
            _print_json(compare_workflow_edit_candidates(
                args.project_id, args.left_attempt_id, args.right_attempt_id
            ))
        elif args.command == "job-start":
            command = list(args.argv)
            command = command[1:] if command[:1] == ["--"] else command
            if not command:
                raise PersianVideoWorkflowError("job-start requires a command after --")
            _print_json(start_workflow_job(
                args.project_id, job_id=args.job_id, phase=args.phase, argv=command,
                idempotence_key=args.idempotence_key,
            ))
        elif args.command == "job-status":
            _print_json(reconcile_workflow_job(args.project_id, args.job_id))
        return 0
    except (PersianVideoWorkflowError, PersianAssetWorkspaceError, PersianEditWorkspaceError, DurableJobError, CheckpointValidationError) as exc:
        parser = build_parser()
        parser.error(str(exc))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
