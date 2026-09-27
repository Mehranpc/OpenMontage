"""#226: deterministic edit defects are refused before they consume a convergence candidate."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from lib import persian_edit_workspace as workspace
from lib import persian_video_workflow as workflow
from lib.persian_edit_workspace import PersianEditWorkspaceError
from tests.lib.test_issue35_convergence_workspace import _schema_valid_edit


def _front_door(tmp_path: Path, monkeypatch, payload: dict) -> Path:
    project = tmp_path / "run"
    project.mkdir(exist_ok=True)
    state = {
        "project_id": "run", "status": "active", "next_phase": "no_copy_preflight",
        "budgets": {"max_revisions_per_stage": 3}, "user_revision_cycles": 0,
        "hook_selection": {"authority": "test"},
        "read_allowlist": {"project_root": str(project)}, "projects_root": str(tmp_path),
        "phase_telemetry": {},
    }
    monkeypatch.setattr(workflow, "load_workflow_state", lambda *a, **k: state)
    monkeypatch.setattr(workflow, "validate_edit_hook_authority", lambda *a, **k: {"valid": True})
    source = project / "candidate.json"
    source.write_text(json.dumps(payload), encoding="utf-8")
    return source


def test_a_region_outside_its_retimed_shot_is_refused_without_a_candidate(tmp_path, monkeypatch):
    """The run's bookkeeping defect: shots moved, reviewed regions kept old absolute times."""
    payload = _schema_valid_edit()
    payload["persian"]["shots"][0]["avoidRegions"] = [
        {"x": 0.1, "y": 0.1, "w": 0.3, "h": 0.3, "priority": "hard",
         "startSeconds": 0.0, "endSeconds": 4.5}  # shot-1 now ends at 3.0
    ]
    source = _front_door(tmp_path, monkeypatch, payload)
    with pytest.raises(PersianEditWorkspaceError, match=r"(?s)EDIT_PRECHECK.*region.after_shot"):
        workflow.stage_workflow_edit_draft("run", "base", source, pipeline_dir=tmp_path)
    assert workspace.convergence_status(tmp_path / "run", revision_cycle=0)["candidateCount"] == 0


def test_a_retention_defect_is_refused_without_a_candidate(tmp_path, monkeypatch):
    payload = _schema_valid_edit()
    payload["persian"]["shots"] = payload["persian"]["shots"][:1]
    payload["persian"]["shots"][0]["endSeconds"] = 6.0
    source = _front_door(tmp_path, monkeypatch, payload)
    with pytest.raises(PersianEditWorkspaceError, match=r"(?s)EDIT_PRECHECK.*RETENTION_GATE"):
        workflow.stage_workflow_edit_draft("run", "base", source, pipeline_dir=tmp_path)
    assert workspace.convergence_status(tmp_path / "run", revision_cycle=0)["candidateCount"] == 0


def test_a_clean_draft_passes_the_precheck(tmp_path, monkeypatch):
    workflow._refuse_cheap_preflight_defects_before_candidate(_schema_valid_edit(), {"authority": "t"})


def test_retime_leaves_headroom_over_the_reading_floor() -> None:
    """The run's "needs 4.958s, has 4.958s" knife-edge cost a candidate."""
    from lib.persian_moments import build_moments
    from lib.persian_sync import READ_FLOOR_MARGIN_SECONDS, TimedWord, retime_moments

    moment = build_moments([{
        "id": "m", "kind": "statement", "startSeconds": 10.0, "endSeconds": 12.0,
        "anchorText": "پیام صبح روز بعد",
        "segments": [{"role": "lead", "text": "بیشترین تمایل"}, {"role": "hero", "text": "پیام صبح روز بعد"}],
    }])[0]
    words = [TimedWord(word=w, start=10.0 + i * 0.2, end=10.15 + i * 0.2)
             for i, w in enumerate(["پیام", "صبح", "روز", "بعد"])]
    retimed = retime_moments([moment], words)[0]
    assert READ_FLOOR_MARGIN_SECONDS >= 0.002
    serialized_span = retimed.to_props()["endSeconds"] - retimed.to_props()["startSeconds"]
    assert serialized_span >= moment.min_read_seconds + 0.001
