"""#387 increment 6: v3 sits behind a pipeline version; no in-place migration."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from lib import persian_pipeline_profile as profile
from lib.persian_asset_workspace import PersianAssetWorkspaceError, _review_profile
from lib.persian_video_workflow import PersianVideoWorkflowError, _is_v3_staged, load_workflow_state
from tests.lib.test_issue387_topic_admission import V3, _run


@pytest.fixture
def v3(monkeypatch):
    monkeypatch.setenv(profile.OPT_IN_ENV, "v3_staged")


def _switch_plan(project: Path, metadata: dict | None) -> None:
    path = project / "checkpoint_scene_plan.json"
    record = json.loads(path.read_text())
    plan = record["artifacts"]["scene_plan"]
    plan.pop("metadata", None)
    if metadata is not None:
        plan["metadata"] = metadata
    path.write_text(json.dumps(record))


def test_v2_stays_the_default_and_v3_still_needs_the_opt_in(monkeypatch):
    monkeypatch.delenv(profile.OPT_IN_ENV, raising=False)
    assert profile.DEFAULT_PROFILE == profile.PROFILE_V2
    assert profile.plan_profile({"beats": []}) == "v2"
    with pytest.raises(profile.PipelineProfileError, match="not enabled"):
        profile.plan_profile({"metadata": V3})


def test_the_plan_phase_pins_the_profile(tmp_path, v3):
    project = _run(tmp_path, V3)
    pin = profile.read_profile_pin(project)
    assert pin["profile"] == "v3_staged" and pin["pinnedAtPhase"] == "plan_scenes_moments"
    state = load_workflow_state("run", pipeline_dir=tmp_path)
    assert state["evidence"]["plan_scenes_moments"]["pipelineProfilePin"]["profile"] == "v3_staged"


@pytest.mark.parametrize("start, switch", [(None, V3), (V3, None)])
def test_an_existing_project_is_not_migrated_in_place(tmp_path, v3, start, switch):
    project = _run(tmp_path, start)
    _switch_plan(project, switch)
    state = load_workflow_state("run", pipeline_dir=tmp_path)
    with pytest.raises(PersianVideoWorkflowError, match=profile.MIGRATION_REFUSED):
        _is_v3_staged(state)
    with pytest.raises(PersianAssetWorkspaceError, match="not migrated in place"):
        _review_profile(project)


def test_a_project_that_predates_the_pin_is_pinned_to_what_it_runs(tmp_path, v3):
    project = _run(tmp_path, None)
    (project / profile.PIN_FILENAME).unlink()
    assert profile.project_profile(project) == "v2"  # reading never writes
    assert not (project / profile.PIN_FILENAME).exists()
    profile.pin_project_profile(project, "v2", phase="acquire_assets")
    _switch_plan(project, V3)
    with pytest.raises(profile.PipelineProfileError, match=profile.MIGRATION_REFUSED):
        profile.project_profile(project)


def test_pinning_is_idempotent_and_never_rewrites(tmp_path):
    first = profile.pin_project_profile(tmp_path, "v2", phase="plan_scenes_moments")
    again = profile.pin_project_profile(tmp_path, "v2", phase="acquire_assets")
    assert again == first
    with pytest.raises(profile.PipelineProfileError, match="Start a fresh project"):
        profile.pin_project_profile(tmp_path, "v3_staged")
    (tmp_path / profile.PIN_FILENAME).write_text('{"profile": "v4"}')
    with pytest.raises(profile.PipelineProfileError, match="malformed"):
        profile.read_profile_pin(tmp_path)


def test_without_a_plan_the_pin_decides(tmp_path):
    assert profile.project_profile(tmp_path) == "v2"
    profile.pin_project_profile(tmp_path, "v3_staged")
    assert profile.project_profile(tmp_path) == "v3_staged"


def test_a_rejected_identity_is_never_rehabilitated_automatically(tmp_path, v3):
    from lib import persian_asset_workspace as workspace
    from tests.lib.test_issue387_topic_admission import _review, _select, _stage, _v3_review

    project = _run(tmp_path, V3)
    candidate = _stage(project, "person-phone")
    _review(tmp_path, candidate, _v3_review(topic_match="off_topic"))
    workspace.reject_asset_candidate(project, candidate, category="semantic", reason="old action-level bar")
    with pytest.raises((PersianVideoWorkflowError, PersianAssetWorkspaceError), match="rejected asset candidate cannot be selected"):
        _select(tmp_path, candidate)
    with pytest.raises((PersianVideoWorkflowError, PersianAssetWorkspaceError), match="immutable"):
        _review(tmp_path, candidate, _v3_review())
