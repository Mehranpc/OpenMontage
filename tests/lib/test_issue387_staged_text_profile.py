"""#387 increment 3: the edit carries the v3 text policy only when the plan does."""
from __future__ import annotations

import pytest

from lib import persian_pipeline_profile as profile
from lib import persian_video_workflow as workflow
from lib.persian_video_workflow import PersianVideoWorkflowError, load_workflow_state
from tests.lib.test_issue387_topic_admission import V3, _run


def _edit(value=None) -> dict:
    return {"persian": {} if value is None else {"pipelineProfile": value}}


def test_edit_profile_defaults_to_v2_and_v3_is_opt_in(monkeypatch):
    monkeypatch.delenv(profile.OPT_IN_ENV, raising=False)
    assert profile.edit_profile(_edit()) == "v2"
    assert profile.edit_profile(_edit("v2")) == "v2"
    with pytest.raises(profile.PipelineProfileError, match="not enabled"):
        profile.edit_profile(_edit("v3_staged"))
    with pytest.raises(profile.PipelineProfileError, match="must be one of"):
        profile.edit_profile(_edit("lenient"))
    monkeypatch.setenv(profile.OPT_IN_ENV, "v3_staged")
    assert profile.edit_profile(_edit("v3_staged")) == "v3_staged"


def test_a_v2_plan_refuses_a_v3_edit(tmp_path, monkeypatch):
    monkeypatch.delenv(profile.OPT_IN_ENV, raising=False)
    _run(tmp_path, None)
    state = load_workflow_state("run", pipeline_dir=tmp_path)
    workflow._require_edit_profile_matches_plan(state, _edit())
    monkeypatch.setenv(profile.OPT_IN_ENV, "v3_staged")
    with pytest.raises(PersianVideoWorkflowError, match="must equal the scene plan's 'v2'"):
        workflow._require_edit_profile_matches_plan(state, _edit("v3_staged"))


def test_a_v3_plan_refuses_an_edit_that_drops_v3(tmp_path, monkeypatch):
    monkeypatch.setenv(profile.OPT_IN_ENV, "v3_staged")
    _run(tmp_path, V3)
    state = load_workflow_state("run", pipeline_dir=tmp_path)
    workflow._require_edit_profile_matches_plan(state, _edit("v3_staged"))
    with pytest.raises(PersianVideoWorkflowError, match="must equal the scene plan's 'v3_staged'"):
        workflow._require_edit_profile_matches_plan(state, _edit())
