"""#346: the documented retime remedy must satisfy the precheck it answers.

On the 2026-09-29 Mac run (text-after-first-date-20260929 @ 5cfae66) the edit
precheck refused three moments on the Film Type reading floor. The agent ran
`retime_moments` exactly as `edit-director.md` shows (no `film_motion`), which
derived ends against the plain estimate, and the precheck refused the same three
moments again. The precheck message also dropped the hint naming the derived end.
"""
from __future__ import annotations

import copy
from pathlib import Path

from lib.persian_moments import build_moments
from lib.persian_sync import TimedWord, retime_moments
from tests.lib.test_issue271_moment_pacing_in_precheck import _edit, _pacing

REPO = Path(__file__).resolve().parents[2]


def _apply(edit: dict, retimed) -> dict:
    out = copy.deepcopy(edit)
    derived = {moment.id: moment.to_props() for moment in retimed}
    for moment in out["persian"]["moments"]:
        if moment["kind"] != "hook":
            props = derived[moment["id"]]
            moment["startSeconds"], moment["endSeconds"] = props["startSeconds"], props["endSeconds"]
    return out


def test_the_documented_retime_call_passes_the_pacing_precheck():
    edit = _edit(end=10.76)
    persian = edit["persian"]
    assert [d for d in _pacing(edit) if d.message.startswith("m-immediate:")]
    # Exactly the edit-director.md call shape before #346: no film_motion.
    retimed = retime_moments(
        build_moments(persian["moments"]),
        TimedWord.from_dicts(persian["audio"]["wordTimings"]),
        simultaneous_hook_typography=True,
    )
    assert not [d for d in _pacing(_apply(edit, retimed)) if d.message.startswith("m-immediate:")]


def test_the_skill_snippet_names_the_film_type_floor():
    text = (REPO / "skills/pipelines/persian-footage/edit-director.md").read_text(encoding="utf-8")
    assert "film_motion=_film_motion()" in text


def test_the_precheck_refusal_carries_the_derived_end(tmp_path):
    from lib.persian_video_workflow import _refuse_cheap_preflight_defects_before_candidate
    from lib.persian_edit_workspace import PersianEditWorkspaceError
    import pytest
    from unittest import mock

    report = {
        "ok": False,
        "blockingIssues": [{
            "code": "moments.pacing", "path": "/persian/moments",
            "message": "m-immediate: reveal at +0.00s needs 3.049s but has 2.763s.",
            "hint": "retime_moments derives endSeconds=10.802 for m-immediate",
        }],
    }
    with mock.patch("lib.persian_preflight.aggregate_preflight_edit_decisions", return_value=report):
        with pytest.raises(PersianEditWorkspaceError, match=r"retime_moments derives endSeconds=10\.802"):
            _refuse_cheap_preflight_defects_before_candidate({}, {})
