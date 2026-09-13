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
from lib.persian_durable_job import DurableJobError, reconcile_job, start_job
from lib.persian_edit_workspace import (
    PersianEditWorkspaceError, artifact_sha256, preflight_edit_draft, promote_edit_draft, stage_edit_draft,
)
from schemas.artifacts import validate_artifact
from jsonschema.exceptions import ValidationError

WORKFLOW_VERSION = "2.0"
STATE_FILENAME = "persian-video-workflow.json"
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
    "render_final_candidate",
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
    "render_final_candidate": ("compose",),
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
            "budgets": asdict(get_workflow_budgets()),
            "attempts": {},
            "send_backs": 0,
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
    started = _parse_timestamp(
        str(state.get("budget_window_started_at") or state.get("created_at") or "")
    )
    current = now or datetime.now(timezone.utc)
    elapsed_minutes = max(0.0, (current - started).total_seconds() / 60.0)
    limit = int((state.get("budgets") or {}).get("max_wall_time_minutes", 0))
    if limit <= 0 or elapsed_minutes > limit:
        raise PersianVideoWorkflowError(
            f"workflow wall-time budget exceeded: {elapsed_minutes:.1f}m > {limit}m"
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
    attempts = dict(state.get("attempts") or {})
    count = int(attempts.get(phase, 0)) + 1
    limit = 1 + int(state["budgets"]["max_revisions_per_stage"])
    if count > limit:
        raise PersianVideoWorkflowError(
            f"retry budget exhausted for {phase}: {count - 1} retries > {limit - 1}"
        )
    attempts[phase] = count
    state["attempts"] = attempts
    _write_state(Path(state["read_allowlist"]["project_root"]), state)
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
        "checkpoint_edit_path": str(root / "checkpoint_edit.json"),
    }


def complete_phase(
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
    if (state.get("asset_usage") or {}).get("pending_pass") is not None:
        raise PersianVideoWorkflowError(
            "asset search result accounting must complete before send-back"
        )
    if state.get("status") == "awaiting_human":
        raise PersianVideoWorkflowError("workflow already stopped at awaiting_human")
    if phase != state.get("next_phase"):
        raise PersianVideoWorkflowError(
            f"cannot complete {phase!r}; next phase is {state.get('next_phase')!r}"
        )
    if phase not in {"open_backlot", "awaiting_human"} and not int(
        (state.get("attempts") or {}).get(phase, 0)
    ):
        raise PersianVideoWorkflowError(
            f"phase {phase!r} must be attempted before it can complete"
        )
    phase_evidence = dict(evidence or {})
    if phase == "prepare_inputs":
        phase_evidence.update(_validate_prepare_inputs_completion(state, phase_evidence))
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
    _write_state(_project_root(state), state)
    return state


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

    reconciliation = {
        "at": datetime.now(timezone.utc).isoformat(),
        "rewoundTo": rewind_to,
        "problems": problems,
        "archivedCheckpoints": archived,
    }
    state["last_reconciliation"] = reconciliation
    _write_state(_project_root(state), state)
    return state


def request_send_back(
    project_id: str,
    target_phase: str,
    *,
    reason: str,
    pipeline_dir: Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Rewind a bounded production without erasing retry history."""
    state = load_workflow_state(project_id, pipeline_dir=pipeline_dir)
    assert_within_wall_time(state, now=now)
    if state.get("status") == "awaiting_human":
        raise PersianVideoWorkflowError(
            "workflow already stopped at awaiting_human; use the checkpoint approval protocol"
        )
    if target_phase not in PHASES[3:-1]:
        raise PersianVideoWorkflowError(
            "send-back target must be an operational phase before awaiting_human"
        )
    if not reason.strip():
        raise PersianVideoWorkflowError("send-back requires a non-empty reason")
    current = state.get("next_phase")
    current_index = len(PHASES) if current is None else _phase_index(str(current))
    target_index = _phase_index(target_phase)
    if target_index >= current_index:
        raise PersianVideoWorkflowError(
            f"send-back must rewind the workflow; current={current!r}, target={target_phase!r}"
        )

    used = int(state.get("send_backs", 0)) + 1
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
    history.append({"target_phase": target_phase, "reason": reason.strip(), "archived_checkpoints": archived})
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

    used_candidates = int(usage.get("candidates_considered", 0))
    used_bytes = int(usage.get("bytes_downloaded", 0))
    remaining_candidates = policy["max_candidates_total"] - used_candidates
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
    if candidates > int(pending_limits["max_candidates_total"]):
        raise PersianVideoWorkflowError("asset result exceeded its issued candidate ceiling")
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

    candidates += int(usage.get("candidates_considered", 0))
    downloaded_bytes += int(usage.get("bytes_downloaded", 0))
    if candidates > policy["max_candidates_total"]:
        raise PersianVideoWorkflowError("asset candidate budget exceeded")
    if downloaded_bytes > policy["max_total_download_bytes"]:
        raise PersianVideoWorkflowError("asset download-byte budget exceeded")
    usage.pop("pending_pass", None)
    usage.pop("pending_output_dir", None)
    usage.pop("pending_limits", None)
    usage.update(
        completed_passes=completed_passes + [retry_pass],
        candidates_considered=candidates,
        bytes_downloaded=downloaded_bytes,
    )
    state["asset_usage"] = usage
    _write_state(_project_root(state), state)
    return state


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
    if audio.get("unexpected_silence") is True or audio.get("clipping_detected") is True:
        raise PersianVideoWorkflowError("final_review audio_spotcheck found silence or clipping")
    if audio.get("mix_intelligible") is not True or list(audio.get("issues") or []):
        raise PersianVideoWorkflowError("final_review audio_spotcheck must pass without issues")

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

    return {
        "final_review_path": str(review_path),
        "final_review_sha256": _hash_file(review_path),
        "candidate_path": candidate["candidate_path"],
        "candidate_sha256": candidate["candidate_sha256"],
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


def workflow_status(
    project_id: str, *, pipeline_dir: Path | None = None
) -> dict[str, Any]:
    state = load_workflow_state(project_id, pipeline_dir=pipeline_dir)
    input_record = dict(state.get("input") or {})
    return {
        "project_id": state["project_id"],
        "status": state["status"],
        "next_phase": state.get("next_phase"),
        "input_mode": input_record.get("mode"),
        "script_authority": input_record.get("script_authority"),
        "completed_phases": state.get("completed_phases", []),
        "attempts": state.get("attempts", {}),
        "send_backs": state.get("send_backs", 0),
        "asset_usage": state.get("asset_usage", {}),
    }


def _load_text_file(path: str) -> str:
    source = Path(path).expanduser().resolve()
    if _is_within(source, PROJECTS_DIR.resolve()):
        raise PersianVideoWorkflowError(
            "refusing text input from an existing project directory"
        )
    if not source.is_file():
        raise PersianVideoWorkflowError(f"text input file does not exist: {source}")
    return source.read_text(encoding="utf-8")


def _add_bootstrap_inputs(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--narration", metavar="PATH")
    script = parser.add_mutually_exclusive_group()
    script.add_argument("--approved-script", metavar="TEXT")
    script.add_argument("--approved-script-file", metavar="PATH")


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


def stage_workflow_edit_draft(
    project_id: str, attempt_id: str, input_path: str | Path, *, pipeline_dir: Path | None = None
) -> dict[str, Any]:
    state = load_workflow_state(project_id, pipeline_dir=pipeline_dir)
    if state.get("next_phase") != "no_copy_preflight":
        raise PersianVideoWorkflowError(
            f"edit drafts are only accepted during no_copy_preflight; next phase is {state.get('next_phase')!r}"
        )
    source = assert_read_allowed(state, input_path)
    payload = _read_json(str(source))
    return stage_edit_draft(_project_root(state), attempt_id, payload)


def preflight_workflow_edit_draft(
    project_id: str, attempt_id: str, *, pipeline_dir: Path | None = None
) -> dict[str, Any]:
    state = load_workflow_state(project_id, pipeline_dir=pipeline_dir)
    if state.get("next_phase") != "no_copy_preflight":
        raise PersianVideoWorkflowError(
            f"edit preflight is only valid during no_copy_preflight; next phase is {state.get('next_phase')!r}"
        )
    return preflight_edit_draft(_project_root(state), attempt_id)


def promote_workflow_edit_draft(
    project_id: str, attempt_id: str, *, pipeline_dir: Path | None = None
) -> dict[str, Any]:
    state = load_workflow_state(project_id, pipeline_dir=pipeline_dir)
    if state.get("next_phase") != "no_copy_preflight":
        raise PersianVideoWorkflowError(
            f"edit promotion is only valid during no_copy_preflight; next phase is {state.get('next_phase')!r}"
        )
    result = promote_edit_draft(_project_root(state), attempt_id)
    canonical = Path(result["canonicalPath"])
    edit = json.loads(canonical.read_text(encoding="utf-8"))
    projects_root = Path(str(state.get("projects_root") or PROJECTS_DIR)).resolve()
    checkpoint_path = write_checkpoint(
        projects_root, project_id, "edit", "completed", {"edit_decisions": edit},
        pipeline_type="persian-footage", human_approval_required=False, human_approved=False,
        metadata={"preflight_attempt_id": attempt_id, "artifact_sha256": result["artifactSha256"]},
    )
    return {**result, "checkpointPath": str(checkpoint_path)}


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

    status = sub.add_parser("status", help="show bounded workflow state")
    status.add_argument("project_id")

    resume = sub.add_parser("resume", help="start a new bounded session and reopen Backlot")
    resume.add_argument("project_id")

    attempt = sub.add_parser("attempt", help="record one phase attempt")
    attempt.add_argument("project_id")
    attempt.add_argument("--phase")

    complete = sub.add_parser("complete", help="complete exactly one phase")
    complete.add_argument("project_id")
    complete.add_argument("--phase")
    complete.add_argument("--evidence-json")

    send_back = sub.add_parser("send-back", help="rewind within the send-back budget")
    send_back.add_argument("project_id")
    send_back.add_argument("target_phase")
    send_back.add_argument("--reason", required=True)

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

    edit_stage = sub.add_parser("edit-stage", help="stage an immutable edit draft inside the project")
    edit_stage.add_argument("project_id")
    edit_stage.add_argument("attempt_id")
    edit_stage.add_argument("--json", required=True, metavar="PATH")

    edit_preflight = sub.add_parser("edit-preflight", help="preflight one staged edit draft")
    edit_preflight.add_argument("project_id")
    edit_preflight.add_argument("attempt_id")

    edit_promote = sub.add_parser("edit-promote", help="promote a digest-bound passing edit draft")
    edit_promote.add_argument("project_id")
    edit_promote.add_argument("attempt_id")

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
                project_id=args.project_id,
            )
            _print_json(workflow_status(state["project_id"]))
        elif args.command == "attach-narration":
            state = attach_narration(args.project_id, args.path)
            _print_json(workflow_status(state["project_id"]))
        elif args.command == "status":
            _print_json(workflow_status(args.project_id))
        elif args.command == "resume":
            _print_json(resume_workflow(args.project_id))
        elif args.command == "attempt":
            state = load_workflow_state(args.project_id)
            phase = args.phase or state.get("next_phase")
            if not phase:
                raise PersianVideoWorkflowError("workflow has no next phase")
            _print_json(record_phase_attempt(args.project_id, str(phase)))
        elif args.command == "complete":
            state = load_workflow_state(args.project_id)
            phase = args.phase or state.get("next_phase")
            if not phase:
                raise PersianVideoWorkflowError("workflow has no next phase")
            evidence = _read_json(args.evidence_json) if args.evidence_json else None
            _print_json(complete_phase(args.project_id, str(phase), evidence=evidence))
        elif args.command == "send-back":
            _print_json(
                request_send_back(
                    args.project_id,
                    args.target_phase,
                    reason=args.reason,
                )
            )
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
        elif args.command == "edit-stage":
            _print_json(stage_workflow_edit_draft(args.project_id, args.attempt_id, args.json))
        elif args.command == "edit-preflight":
            _print_json(preflight_workflow_edit_draft(args.project_id, args.attempt_id))
        elif args.command == "edit-promote":
            _print_json(promote_workflow_edit_draft(args.project_id, args.attempt_id))
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
    except (PersianVideoWorkflowError, PersianEditWorkspaceError, DurableJobError, CheckpointValidationError) as exc:
        parser = build_parser()
        parser.error(str(exc))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
