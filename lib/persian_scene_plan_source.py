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
