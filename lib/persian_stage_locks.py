"""Forward-only stage locks for the v3 staged Persian pipeline (#387 increment 2).

Each v3 stage writes an immutable lock checkpoint under ``stage_locks/`` with the
SHA-256 of every locked file, the digests of the earlier locks it consumed, and the
implementation SHA. A later stage may only read locked files; rewriting a locked
checkpoint, mutating the footage workspace after the footage lock, or rewinding into
a locked stage is refused. The only future backward path is the human time-range
revision of #387 increment 5, which will create a new lock version.

Stages 0 (narration & timing) and 1 (footage) are wired to real checkpoints here.
Stages 2–4 (subtitles, styled text, watermark) use the same API once increments 3–4
split them out of the current edit/compose phases.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

STAGE_NAMES = {
    0: "narration_timing",
    1: "footage",
    2: "subtitles",
    3: "styled_text",
    4: "watermark",
}
LOCK_DIR = "stage_locks"
LOCK_SCHEMA = "openmontage.stage_lock.v1"

#: Workflow phase -> v3 stage. Post-footage authoring phases are stage 2 until
#: increments 3–4 split subtitles / styled text / watermark into their own phases.
PHASE_STAGE = {
    "validate_input": 0,
    "create_project": 0,
    "open_backlot": 0,
    "prepare_inputs": 0,
    "align_script_timing": 0,
    "plan_scenes_moments": 0,
    "acquire_assets": 1,
    "review_subject_regions": 2,
    "no_copy_preflight": 2,
    "render_opening_candidate": 5,
    "opening_review": 5,
    "render_final_candidate": 5,
    "master_final_candidate": 5,
    "final_review": 5,
    "awaiting_human": 5,
}

#: Phase whose completion writes a stage lock, and the checkpoint files it locks.
LOCKING_PHASES = {
    "plan_scenes_moments": (0, ("checkpoint_script.json", "checkpoint_scene_plan.json")),
    "acquire_assets": (1, ("checkpoint_assets.json",)),
}

#: Checkpoint stage name -> v3 stage that owns it once locked.
CHECKPOINT_STAGE = {"script": 0, "scene_plan": 0, "assets": 1}


class StageLockError(ValueError):
    """A locked v3 stage would be mutated or a lock is inconsistent."""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def lock_path(project_dir: Path, stage: int) -> Path:
    return Path(project_dir) / LOCK_DIR / f"stage-{int(stage)}.json"


def read_stage_lock(project_dir: Path, stage: int) -> dict[str, Any] | None:
    path = lock_path(project_dir, stage)
    if not path.is_file():
        return None
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StageLockError(f"stage {stage} lock is unreadable: {path}") from exc
    if not isinstance(record, dict) or record.get("schema") != LOCK_SCHEMA:
        raise StageLockError(f"stage {stage} lock is malformed: {path}")
    return record


def is_locked(project_dir: Path, stage: int) -> bool:
    return lock_path(project_dir, stage).is_file()


def locked_stages(project_dir: Path) -> list[int]:
    return [stage for stage in STAGE_NAMES if is_locked(project_dir, stage)]


def _file_digests(project_dir: Path, files: Sequence[str]) -> dict[str, str]:
    project_dir = Path(project_dir).resolve()
    result: dict[str, str] = {}
    for raw in files:
        rel = str(raw)
        path = (project_dir / rel).resolve()
        if project_dir not in path.parents:
            raise StageLockError(f"locked file must be inside the project: {rel}")
        if not path.is_file():
            raise StageLockError(f"cannot lock missing file: {rel}")
        result[rel] = _sha256_file(path)
    if not result:
        raise StageLockError("a stage lock needs at least one file")
    return dict(sorted(result.items()))


def verify_stage_lock(project_dir: Path, stage: int) -> dict[str, Any]:
    """Recompute a lock; any changed or missing locked file is a refusal."""
    record = read_stage_lock(project_dir, stage)
    if record is None:
        raise StageLockError(f"stage {stage} is not locked")
    files = record.get("files")
    if not isinstance(files, Mapping) or not files:
        raise StageLockError(f"stage {stage} lock has no files")
    try:
        current = _file_digests(project_dir, list(files))
    except StageLockError as exc:
        raise StageLockError(f"locked stage {stage} was mutated: {exc}") from exc
    changed = sorted(rel for rel, sha in files.items() if current.get(rel) != sha)
    if changed:
        raise StageLockError(f"locked stage {stage} ({STAGE_NAMES[stage]}) was mutated: {changed}")
    if record.get("content_digest") != _digest(dict(files)):
        raise StageLockError(f"stage {stage} lock content digest does not match its files")
    return record


def verify_stage_locks(project_dir: Path) -> list[dict[str, Any]]:
    """Verify every existing lock and that locks form a contiguous prefix 0..n."""
    present = locked_stages(project_dir)
    if present != list(range(len(present))):
        raise StageLockError(f"stage locks must be contiguous from stage 0; found {present}")
    records = [verify_stage_lock(project_dir, stage) for stage in present]
    for record in records:
        stage = int(record["stage"])
        expected = {str(prior["stage"]): prior["content_digest"] for prior in records[:stage]}
        if dict(record.get("input_digests") or {}) != expected:
            raise StageLockError(f"stage {stage} lock does not bind the earlier locks it consumed")
    return records


def write_stage_lock(
    project_dir: Path,
    stage: int,
    files: Sequence[str],
    *,
    implementation_sha: str,
    now: datetime | None = None,
    lock_version: int = 1,
    provenance: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Lock one stage. Earlier stages must be locked; an existing lock is immutable.

    ``lock_version`` > 1 and ``provenance`` are used only by a human time-range
    revision, after the previous lock was archived with :func:`archive_stage_lock`.
    """
    if stage not in STAGE_NAMES:
        raise StageLockError(f"unknown stage {stage!r}")
    prior = verify_stage_locks(project_dir)
    if len(prior) < stage:
        raise StageLockError(f"stage {stage} cannot lock before stages 0..{stage - 1}")
    digests = _file_digests(project_dir, files)
    existing = read_stage_lock(project_dir, stage)
    if existing is not None:
        if dict(existing.get("files") or {}) == digests:
            return existing
        raise StageLockError(
            f"stage {stage} ({STAGE_NAMES[stage]}) is locked; changing it needs a human range revision"
        )
    record = {
        "schema": LOCK_SCHEMA,
        "stage": stage,
        "name": STAGE_NAMES[stage],
        "lock_version": int(lock_version),
        "files": digests,
        "content_digest": _digest(digests),
        "input_digests": {str(item["stage"]): item["content_digest"] for item in prior[:stage]},
        "implementation_sha": str(implementation_sha or "unknown"),
        "locked_at": (now or datetime.now(timezone.utc)).isoformat(),
    }
    if provenance:
        record["provenance"] = dict(provenance)
    path = lock_path(project_dir, stage)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return record


def archive_stage_lock(project_dir: Path, stage: int, *, reason: str) -> dict[str, Any]:
    """Move the active lock of ``stage`` to ``stage_locks/history/`` (human revision only).

    The lock must still verify, and only the last locked stage may be reopened, so a
    revision can never leave a later lock bound to a stage that is changing.
    """
    record = verify_stage_lock(project_dir, stage)
    present = locked_stages(project_dir)
    if present and present[-1] != stage:
        raise StageLockError(f"stage {stage} cannot reopen while later stages {present} are locked")
    history = Path(project_dir) / LOCK_DIR / "history"
    history.mkdir(parents=True, exist_ok=True)
    target = history / f"stage-{stage}.v{int(record.get('lock_version') or 1)}.json"
    if target.exists():
        raise StageLockError(f"stage {stage} lock version is already archived: {target.name}")
    archived = {**record, "archived_reason": str(reason)}
    target.write_text(json.dumps(archived, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    lock_path(project_dir, stage).unlink()
    return archived


def assert_stage_unlocked(project_dir: Path, stage: int, *, action: str) -> None:
    if is_locked(project_dir, stage):
        raise StageLockError(
            f"{action} refused: stage {stage} ({STAGE_NAMES[stage]}) is locked; "
            "only a human time-range revision may change it (#387)"
        )


def assert_checkpoint_writable(project_dir: Path, checkpoint_stage: str) -> None:
    stage = CHECKPOINT_STAGE.get(str(checkpoint_stage))
    if stage is not None:
        assert_stage_unlocked(project_dir, stage, action=f"writing checkpoint_{checkpoint_stage}.json")


def assert_rewind_allowed(
    project_dir: Path, current_phase: str | None, target_phase: str, *, user_directed: bool
) -> None:
    """v3 is forward-only: no automatic rewind, and no rewind into a locked stage."""
    target_stage = PHASE_STAGE.get(target_phase)
    if target_stage is None:
        raise StageLockError(f"unknown target phase {target_phase!r}")
    if not user_directed:
        raise StageLockError(
            "v3_staged is forward-only: automatic send-back is refused; later stages adapt to "
            "locked footage, and only a human time-range revision may reopen it (#387)"
        )
    if target_stage in STAGE_NAMES and is_locked(project_dir, target_stage):
        assert_stage_unlocked(project_dir, target_stage, action=f"send-back to {target_phase}")
