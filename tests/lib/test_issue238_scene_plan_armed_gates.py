"""#238: asset and region gates audit against the front door's scene plan.

The front door keeps the plan only in ``checkpoint_scene_plan.json``. The asset
commands read ``artifacts/scene_plan.json``, which nothing but ``reconcile-plan``
wrote, so on a normal run the audit ran with no plan and a manifest missing whole
events passed ``build-manifest`` and ``write-checkpoint`` (found on the 58048e2
acceptance run: 9 of 13 events, ``auditProblems: []``).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lib import persian_asset_commands as commands
from lib.persian_scene_plan_source import materialize_scene_plan
from tests.lib.test_issue35_asset_candidate_workspace import (
    _selected_candidate,
    _write_matching_scene_plan,
)
from tests.lib.test_issue35_semantic_scene_plan_checkpoint import _event


def _front_door_project(tmp_path: Path, *, extra_event: bool) -> Path:
    project = tmp_path / "run"
    _selected_candidate(project)
    plan = _write_matching_scene_plan(project)
    if extra_event:
        plan["beats"].append({
            "id": "beat-2", "intent_fa": "دوم", "script_line_fa": "دوم", "duration_seconds": 4.0,
            "typographic": False, "visual_events": [_event("event-2", 4.0)],
        })
        (project / "checkpoint_scene_plan.json").write_text(json.dumps({
            "stage": "scene_plan", "status": "completed", "artifacts": {"scene_plan": plan},
        }, ensure_ascii=False), encoding="utf-8")
    assert not (project / "artifacts" / "scene_plan.json").exists()
    return project


def test_a_manifest_missing_a_planned_event_is_refused_on_a_front_door_run(tmp_path: Path) -> None:
    _front_door_project(tmp_path, extra_event=True)
    with pytest.raises(commands.PersianAssetCommandError, match="event-2: no asset"):
        commands.build_manifest(tmp_path, "run")


def test_a_complete_manifest_still_builds_and_the_plan_is_materialised(tmp_path: Path) -> None:
    project = _front_door_project(tmp_path, extra_event=False)
    commands.build_manifest(tmp_path, "run")
    artifact = project / "artifacts" / "scene_plan.json"
    checkpoint = json.loads((project / "checkpoint_scene_plan.json").read_text(encoding="utf-8"))
    assert json.loads(artifact.read_text(encoding="utf-8")) == checkpoint["artifacts"]["scene_plan"]


def test_no_scene_plan_at_all_is_refused_not_audited_clean(tmp_path: Path) -> None:
    project = tmp_path / "run"
    _selected_candidate(project)
    with pytest.raises(commands.PersianAssetCommandError, match="no completed scene plan"):
        commands.build_manifest(tmp_path, "run")


def test_the_checkpoint_wins_over_a_stale_artifact(tmp_path: Path) -> None:
    project = _front_door_project(tmp_path, extra_event=True)
    artifact = project / "artifacts" / "scene_plan.json"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text(json.dumps({"beats": []}), encoding="utf-8")
    materialize_scene_plan(project)
    assert len(json.loads(artifact.read_text(encoding="utf-8"))["beats"]) == 2


def test_an_identical_artifact_is_not_rewritten(tmp_path: Path) -> None:
    project = _front_door_project(tmp_path, extra_event=False)
    path = materialize_scene_plan(project)
    before = path.stat().st_mtime_ns
    materialize_scene_plan(project)
    assert path.stat().st_mtime_ns == before
