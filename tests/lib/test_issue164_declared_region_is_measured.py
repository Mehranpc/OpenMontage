"""#164: a declared negative space must actually be clear of the reviewed subject.

The plan-time audit checks a declared region against the profile's safe area using a
*nominal* rect -- it cannot see the frame. So a plan can declare `upper_band` for a shot
whose subject occupies exactly that band, pass every plan gate, and only discover it at
placement. Observed on a real L3 run: shot-5 declared `upper_band` while three phones
occupied y 0.25-0.70, and the run paid a repair cycle to find out.

The edit knows each shot's reviewed hard regions, so that is where "clear" stops being
asserted and starts being measured.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import json

from lib import persian_edit_workspace as workspace
from lib.persian_edit_workspace import PersianEditWorkspaceError


def _plan(*, region: str) -> dict:
    return {
        "version": "2.0",
        "format": "vertical",
        "subject": "phone",
        "beats": [
            {
                "id": "beat-1",
                "duration_seconds": 2.5,
                "typographic": False,
                "visual_events": [
                    {
                        "id": "ve-1",
                        "duration_seconds": 2.5,
                        "narration_span": "نمونه",
                        "intent": "show the phone on a table",
                        "subject": "phone",
                        "action": "resting",
                        "desired_affect": "curiosity",
                        "motif": "waiting",
                        "visual_search_brief": "phone on a table, wide",
                        "shot_composition": "wide, subject off-centre",
                        "human_presence": False,
                        "importance": 2,
                        "conflict_visibility": "none",
                        "fallback_level": "exact_literal",
                        "camera": "push-in",
                        "shows_subject": True,
                        "shot_scale": "overhead",
                        "environment": "kitchen",
                        "queries": ["sample query", "second sample query"],
                        "carries_moment": True,
                        "negative_space": region,
                    }
                ],
            }
        ],
    }


def _edit(*, avoid) -> dict:
    return {
        "persian": {
            "durationSeconds": 6.0,
            "shots": [
                {
                    "id": "shot-1",
                    "visualEventId": "ve-1",
                    "startSeconds": 0.0,
                    "endSeconds": 6.0,
                    "narrativeRole": "hook",
                    "avoidRegions": avoid,
                }
            ],
            "moments": [
                {
                    "id": "moment-01",
                    "kind": "hook",
                    "startSeconds": 0.0,
                    "endSeconds": 2.5,
                    "segments": [{"role": "hero", "text": "نمونه"}],
                }
            ],
            "typographicBeats": [],
            "captions": [],
            "audio": {},
            "watermark": {"persianText": "طریقت تسلیم", "latinText": "Pathway"},
        }
    }


def _write_plan_checkpoint(project: Path, plan: dict) -> None:
    """Written directly: the checkpoint writer enforces pipeline order, and this test is
    about the placement check, not about staging a whole pipeline."""
    (project / "checkpoint_scene_plan.json").write_text(
        json.dumps(
            {
                "version": "1.0",
                "project_id": project.name,
                "pipeline_type": "persian-footage",
                "stage": "scene_plan",
                "status": "completed",
                "timestamp": "2026-09-26T00:00:00+00:00",
                "checkpoint_policy": "guided",
                "human_approval_required": False,
                "human_approved": False,
                "artifacts": {"scene_plan": plan},
            }
        ),
        encoding="utf-8",
    )


def _project_with_plan(tmp_path: Path, *, region: str) -> Path:
    project = tmp_path / "project"
    project.mkdir(parents=True)
    _write_plan_checkpoint(project, _plan(region=region))
    return project


_OCCUPIED = [
    {"x": 0.0, "y": 0.2, "w": 1.0, "h": 0.5, "startSeconds": 0.0, "endSeconds": 6.0}
]
_CLEAR = [
    {"x": 0.0, "y": 0.8, "w": 1.0, "h": 0.2, "startSeconds": 0.0, "endSeconds": 6.0}
]


def test_a_declared_region_the_subject_occupies_is_refused(tmp_path: Path) -> None:
    project = _project_with_plan(tmp_path, region="upper_band")

    with pytest.raises(
        PersianEditWorkspaceError, match="occupied by the reviewed subject"
    ):
        workspace.stage_edit_draft(project, "occupied", _edit(avoid=_OCCUPIED))


def test_a_declared_region_the_subject_leaves_free_is_accepted(tmp_path: Path) -> None:
    project = _project_with_plan(tmp_path, region="upper_band")

    staged = workspace.stage_edit_draft(project, "clear", _edit(avoid=_CLEAR))

    assert staged["changedScopes"] is not None


def test_a_plan_without_a_copy_bearing_event_is_unaffected(tmp_path: Path) -> None:
    """The check binds declared regions only: an edit for a plan that declares none must
    stage exactly as before."""
    project = tmp_path / "project"
    project.mkdir(parents=True)
    plan = _plan(region="upper_band")
    plan["beats"][0]["visual_events"][0]["carries_moment"] = False
    _write_plan_checkpoint(project, plan)

    staged = workspace.stage_edit_draft(project, "no-moment", _edit(avoid=_OCCUPIED))

    assert staged["changedScopes"] is not None
