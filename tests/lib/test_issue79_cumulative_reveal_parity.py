from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from lib import persian_edit_workspace as workspace
from lib.persian_edit_workspace import PersianEditWorkspaceError
from lib.persian_moments import audit_moments, build_moments
from lib.persian_recovery_policy import recovery_policy_for_issue


def _timing_moment(*, reveals: tuple[float, float, float], end: float = 4.63) -> dict:
    return {
        "id": "timing-build",
        "kind": "statement",
        "startSeconds": 0.0,
        "endSeconds": end,
        "presentation": {"placement": "auto", "motion": "cut-in", "sequenceMode": "accumulate"},
        "segments": [
            {"role": "hero", "text": "بلافاصله", "revealAfterSeconds": reveals[0]},
            {"role": "hero", "text": "صبح روز بعد", "revealAfterSeconds": reveals[1]},
            {"role": "hero", "text": "دو روز بعد", "revealAfterSeconds": reveals[2]},
        ],
    }


def test_accumulate_minimum_duration_does_not_double_count_authored_reveal_gaps() -> None:
    moments = build_moments([_timing_moment(reveals=(0.0, 1.25, 2.75))])
    audit = audit_moments(moments, duration_seconds=10.0, adaptive_pixel_typography=True)

    assert moments[0].min_read_seconds <= 4.63
    assert audit.problems == []


def test_accumulate_rejects_an_intermediate_window_that_is_too_short() -> None:
    moments = build_moments([_timing_moment(reveals=(0.0, 0.3, 0.6))])
    audit = audit_moments(moments, duration_seconds=10.0, adaptive_pixel_typography=True)

    assert any("reveal step at +0.00s needs" in problem for problem in audit.problems)


def _edit() -> dict:
    return {
        "metadata": {},
        "persian": {
            "durationSeconds": 8.0,
            "shots": [
                {
                    "id": "shot-1",
                    "startSeconds": 0.0,
                    "endSeconds": 8.0,
                    "visualEventId": "event-1",
                    "changeType": "establish",
                    "narrativeRole": "exposition",
                    "humanPresence": True,
                    "src": "/tmp/source.mp4",
                    "avoidRegions": [],
                }
            ],
            "moments": [
                {
                    "id": "timing-build",
                    "kind": "statement",
                    "startSeconds": 1.0,
                    "endSeconds": 6.0,
                    "presentation": {"sequenceMode": "accumulate"},
                    "segments": [
                        {"role": "hero", "text": "اول", "revealAfterSeconds": 0.0},
                        {"role": "hero", "text": "دوم", "revealAfterSeconds": 1.2},
                    ],
                }
            ],
            "typographicBeats": [],
            "captions": [],
            "audio": {},
            "watermark": {},
        },
    }


def test_reveal_schedule_is_a_timeline_change_not_a_copy_change() -> None:
    base = _edit()
    child = deepcopy(base)
    child["persian"]["moments"][0]["segments"][1]["revealAfterSeconds"] = 1.5

    assert workspace._changed_scopes(base, child) == ["timeline"]


def test_film_type_layout_recovery_exposes_bounded_reveal_schedule_repair() -> None:
    policy = recovery_policy_for_issue(
        {"code": "FILM_TYPE_PREPASS", "recoveryClass": "FILM_TYPE_LAYOUT"}
    )

    assert "retime_reveal_schedule_within_readability_policy" in policy["strategies"]
    assert "timeline.reveal_schedule" in policy["mutationSurface"]


def test_layout_recovery_can_retime_reveals_but_cannot_rewrite_copy(tmp_path: Path) -> None:
    project = tmp_path / "project"
    base = _edit()
    workspace.stage_edit_draft(project, "base", base, max_candidates=10)

    retimed = deepcopy(base)
    retimed["persian"]["moments"][0]["segments"][1]["revealAfterSeconds"] = 1.5
    staged = workspace.stage_edit_draft(
        project,
        "retimed",
        retimed,
        parent_attempt_id="base",
        diagnostic_issue={"code": "FILM_TYPE_PREPASS", "recoveryClass": "FILM_TYPE_LAYOUT"},
        strategy="retime_reveal_schedule_within_readability_policy",
        changed_fields=["timeline.reveal_schedule"],
        max_candidates=10,
    )
    assert staged["changedScopes"] == ["timeline"]

    rewritten = deepcopy(retimed)
    rewritten["persian"]["moments"][0]["segments"][1]["text"] = "متن تازه"
    with pytest.raises(PersianEditWorkspaceError, match="mutation surface"):
        workspace.stage_edit_draft(
            project,
            "rewritten",
            rewritten,
            parent_attempt_id="retimed",
            diagnostic_issue={"code": "FILM_TYPE_PREPASS", "recoveryClass": "FILM_TYPE_LAYOUT"},
            strategy="retime_reveal_schedule_within_readability_policy",
            changed_fields=["timeline.reveal_schedule"],
            max_candidates=10,
        )
