from __future__ import annotations

from pathlib import Path

from lib import persian_edit_workspace as workspace
from lib.persian_film_type import FilmTypePreflightError
from lib.persian_recovery_policy import recovery_policy_for_issue


def _edit(*, hook_end_seconds: float) -> dict:
    return {
        "persian": {
            "durationSeconds": 6.0,
            "shots": [
                {
                    "id": "shot-1",
                    "startSeconds": 0.0,
                    "endSeconds": 6.0,
                    "narrativeRole": "hook",
                }
            ],
            "moments": [
                {
                    "id": "moment-01",
                    "kind": "hook",
                    "startSeconds": 0.0,
                    "endSeconds": hook_end_seconds,
                    "segments": [{"role": "hero", "text": "بازی‌های ویدیویی"}],
                }
            ],
            "typographicBeats": [],
            "captions": [],
            "audio": {},
            "watermark": {},
        }
    }


def test_film_type_opening_hold_failure_routes_to_hook_timing_recovery(tmp_path: Path) -> None:
    error = FilmTypePreflightError(
        "Moment moment-01: Film Type 2.16 opening hook must occupy one complete 3-5s composition."
    )
    assert error.code == "HOOK_TYPOGRAPHIC_DURATION_FILM_TYPE"

    plan = recovery_policy_for_issue({"code": error.code})
    assert plan["recoveryClass"] == "HOOK_TIMING"
    assert plan["mutationSurface"] == ["hook.duration", "hook.payoff_timing"]
    assert "retime_hook_window_only" in plan["strategies"]

    project = tmp_path / "project"
    workspace.stage_edit_draft(project, "base", _edit(hook_end_seconds=5.75), max_candidates=4)
    staged = workspace.stage_edit_draft(
        project,
        "retimed",
        _edit(hook_end_seconds=5.0),
        parent_attempt_id="base",
        diagnostic_issue={"code": error.code, "recoveryClass": plan["recoveryClass"]},
        strategy="retime_hook_window_only",
        changed_fields=["hook.duration"],
        max_candidates=4,
    )

    assert staged["changedScopes"] == ["hook", "timeline"]


def test_other_film_type_prepass_failures_remain_layout_recovery() -> None:
    error = FilmTypePreflightError("Moment moment-02: measured line overflow")
    assert error.code == "FILM_TYPE_PREPASS"
    assert recovery_policy_for_issue({"code": error.code})["recoveryClass"] == "FILM_TYPE_LAYOUT"
