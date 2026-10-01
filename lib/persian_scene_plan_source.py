"""One source for the scene plan the asset and region gates audit against.

The Persian front door persists the plan inside ``checkpoint_scene_plan.json``. The
asset and region commands read ``artifacts/scene_plan.json``, which only
``reconcile-plan`` used to write. A front-door run therefore had no such file, and
``audit_asset_manifest(manifest, None)`` skipped every plan-dependent rule: a manifest
missing whole events audited clean (#238). This module materialises that file from the
completed checkpoint so every reader sees the same plan, and the file's hash still binds
region sheets and proposals.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

SCENE_PLAN_ARTIFACT = Path("artifacts") / "scene_plan.json"


def _checkpoint_plan(project: Path) -> dict[str, Any] | None:
    path = project / "checkpoint_scene_plan.json"
    if not path.is_file():
        return None
    try:
        checkpoint = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(checkpoint, dict) or checkpoint.get("status") != "completed":
        return None
    plan = (checkpoint.get("artifacts") or {}).get("scene_plan")
    return plan if isinstance(plan, dict) and plan else None


class ScenePlanUnreadable(ValueError):
    """The effective scene plan exists but cannot be read as an object."""


def _readable_plan(value: object, source: Path) -> dict[str, Any]:
    """Require an actual requirements graph, not merely a nonempty JSON object."""
    if not isinstance(value, dict) or not value:
        raise ScenePlanUnreadable(f"scene plan is not a plan object: {source}")
    beats = value.get("beats")
    if beats is None:
        metadata = value.get("metadata")
        beats = metadata.get("beats") if isinstance(metadata, dict) else None
    if not isinstance(beats, list) or not beats:
        raise ScenePlanUnreadable(f"scene plan has no readable beat requirements: {source}")
    for beat in beats:
        if not isinstance(beat, dict) or not isinstance(beat.get("id"), str) or not beat["id"].strip():
            raise ScenePlanUnreadable(f"scene plan has a malformed beat: {source}")
        events = beat.get("visual_events")
        if events is not None and (
            not isinstance(events, list) or any(
                not isinstance(event, dict)
                or not isinstance(event.get("id"), str)
                or not event["id"].strip()
                for event in events
            )
        ):
            raise ScenePlanUnreadable(f"scene plan has malformed visual-event requirements: {source}")
    return value


def load_effective_scene_plan(project: Path) -> dict[str, Any] | None:
    """Read the effective plan without materialising it; malformed truth fails closed.

    A completed checkpoint is authoritative even when malformed: do not silently
    replace it with an older artifact. With no completed checkpoint, retain the
    supported artifact-only legacy path. Neither read writes any project file.
    """
    project = Path(project)
    checkpoint = project / "checkpoint_scene_plan.json"
    if checkpoint.is_file():
        try:
            record = json.loads(checkpoint.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ScenePlanUnreadable(f"scene-plan checkpoint is unreadable: {checkpoint}") from exc
        if not isinstance(record, dict):
            raise ScenePlanUnreadable(f"scene-plan checkpoint is not an object: {checkpoint}")
        if record.get("status") == "completed":
            artifacts = record.get("artifacts")
            if not isinstance(artifacts, dict):
                raise ScenePlanUnreadable(f"scene-plan checkpoint artifacts are malformed: {checkpoint}")
            return _readable_plan(artifacts.get("scene_plan"), checkpoint)
    artifact = project / SCENE_PLAN_ARTIFACT
    if not artifact.is_file():
        return None
    try:
        value = json.loads(artifact.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ScenePlanUnreadable(f"scene-plan artifact is unreadable: {artifact}") from exc
    return _readable_plan(value, artifact)


def materialize_scene_plan(project: Path) -> Path | None:
    """Return the scene-plan artifact path, written from the completed checkpoint.

    The completed checkpoint is authoritative: a missing or diverging artifact is
    rewritten from it. With no completed checkpoint an existing artifact is used as is.
    Returns ``None`` only when there is no scene plan at all.
    """
    project = Path(project)
    artifact = project / SCENE_PLAN_ARTIFACT
    plan = _checkpoint_plan(project)
    if plan is None:
        return artifact if artifact.is_file() else None
    rendered = json.dumps(plan, ensure_ascii=False, indent=2) + "\n"
    current = artifact.read_text(encoding="utf-8") if artifact.is_file() else None
    if current is not None:
        try:
            if json.loads(current) == plan:
                return artifact
        except json.JSONDecodeError:
            pass
    artifact.parent.mkdir(parents=True, exist_ok=True)
    temporary = artifact.with_name(f".{artifact.name}.{uuid4().hex}.tmp")
    temporary.write_text(rendered, encoding="utf-8")
    temporary.replace(artifact)
    return artifact
