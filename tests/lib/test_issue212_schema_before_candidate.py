"""#212: a schema-breaking edit draft is refused before it consumes a candidate."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from lib import persian_edit_workspace as workspace
from lib.persian_edit_workspace import PersianEditWorkspaceError
from tests.lib.test_issue35_convergence_workspace import _schema_valid_edit


def _invented_field(payload: dict) -> dict:
    """The Mac run's defect: a free-text key next to a real one on a shot."""
    broken = deepcopy(payload)
    broken["persian"]["shots"][0]["visualComplexityReview"] = "free-text note"
    return broken


def test_schema_break_is_refused_without_writing_a_candidate(tmp_path: Path) -> None:
    project = tmp_path / "project"
    with pytest.raises(PersianEditWorkspaceError, match=r"(?s)EDIT_SCHEMA.*visualComplexityReview"):
        workspace.stage_edit_draft(
            project, "base", _invented_field(_schema_valid_edit()),
            max_candidates=2, enforce_edit_schema=True,
        )
    assert workspace.convergence_status(project)["candidateCount"] == 0
    assert not (project / "artifacts").exists() or not any(
        (project / "artifacts").rglob("candidate.json")
    )


def test_a_refused_draft_does_not_spend_the_bounded_budget(tmp_path: Path) -> None:
    """Two slots: a malformed draft, then the corrected one, then a real recovery."""
    project = tmp_path / "project"
    good = _schema_valid_edit()
    with pytest.raises(PersianEditWorkspaceError, match="EDIT_SCHEMA"):
        workspace.stage_edit_draft(
            project, "base-bad", _invented_field(good), max_candidates=2, enforce_edit_schema=True,
        )
    workspace.stage_edit_draft(project, "base", good, max_candidates=2, enforce_edit_schema=True)
    child = workspace.stage_edit_draft(
        project, "layout-1", _schema_valid_edit(recipe="recipe-b"),
        parent_attempt_id="base",
        diagnostic_issue={"code": "FILM_TYPE_LAYOUT_OVERFLOW", "recoveryClass": "FILM_TYPE_LAYOUT"},
        strategy="select_curated_typography_recipe",
        changed_fields=["typography.recipe"],
        max_candidates=2,
        enforce_edit_schema=True,
    )
    assert child["disposition"] == "staged"
    status = workspace.convergence_status(project)
    assert status["candidateCount"] == 2
    assert status["status"] == "active"


def test_refusal_lists_every_defect_with_its_pointer(tmp_path: Path) -> None:
    broken = _invented_field(_schema_valid_edit())
    broken["persian"]["moments"][0]["semanticRoleX"] = "x"
    del broken["persian"]["shots"][0]["attribution"]
    with pytest.raises(PersianEditWorkspaceError) as excinfo:
        workspace.stage_edit_draft(
            tmp_path / "p", "base", broken, max_candidates=2, enforce_edit_schema=True,
        )
    message = str(excinfo.value)
    assert "/persian/shots/0/visualComplexityReview" in message
    assert "/persian/moments/0/semanticRoleX" in message
    assert "'attribution' is a required property" in message
    assert "no convergence budget spent" in message


def test_front_door_enforces_the_schema_before_candidate_consumption(tmp_path: Path, monkeypatch) -> None:
    from lib import persian_video_workflow as workflow

    project = tmp_path / "run"
    project.mkdir()
    source = project / "candidate.json"
    state = {
        "project_id": "run",
        "status": "active",
        "next_phase": "no_copy_preflight",
        "budgets": {"max_revisions_per_stage": 1},
        "user_revision_cycles": 0,
        "hook_selection": {"authority": "test"},
        "read_allowlist": {"project_root": str(project)},
        "projects_root": str(tmp_path),
        "phase_telemetry": {},
    }
    monkeypatch.setattr(workflow, "load_workflow_state", lambda *a, **k: state)
    monkeypatch.setattr(workflow, "validate_edit_hook_authority", lambda *a, **k: {"valid": True})

    source.write_text(json.dumps(_invented_field(_schema_valid_edit())), encoding="utf-8")
    with pytest.raises(PersianEditWorkspaceError, match="EDIT_SCHEMA"):
        workflow.stage_workflow_edit_draft("run", "base", source, pipeline_dir=tmp_path)
    assert workspace.convergence_status(project, revision_cycle=0)["candidateCount"] == 0
    assert state["status"] == "active"
