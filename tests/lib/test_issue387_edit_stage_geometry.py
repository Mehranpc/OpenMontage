"""#387: under v3_staged, edit staging never refuses for subject geometry.

Found in the #387 Mac acceptance run: preflight skipped its geometric precheck for v3,
but ``stage_edit_draft`` still ran the declared-negative-space check and the
hard-region geometric precheck, refusing an edit whose text the v3 ladder adapts to
the locked footage. v2 behaviour is unchanged.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from lib import persian_edit_workspace as workspace
from lib.persian_edit_workspace import PersianEditWorkspaceError
from lib.persian_pipeline_profile import OPT_IN_ENV, PROFILE_V3
from tests.lib.test_issue164_declared_region_is_measured import (
    _OCCUPIED, _edit, _plan, _write_plan_checkpoint,
)


def _project(tmp_path: Path, *, v3: bool) -> Path:
    project = tmp_path / "project"
    project.mkdir(parents=True)
    plan = _plan(region="upper_band")
    if v3:
        plan["metadata"] = {"pipeline_profile": PROFILE_V3}
    _write_plan_checkpoint(project, plan)
    return project


def test_v3_stages_an_edit_whose_declared_region_the_subject_occupies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(OPT_IN_ENV, PROFILE_V3)
    project = _project(tmp_path, v3=True)

    staged = workspace.stage_edit_draft(project, "occupied-v3", _edit(avoid=_OCCUPIED))

    assert staged["changedScopes"] is not None


def test_v2_still_refuses_the_same_occupied_declared_region(tmp_path: Path) -> None:
    project = _project(tmp_path, v3=False)

    with pytest.raises(PersianEditWorkspaceError, match="occupied by the reviewed subject"):
        workspace.stage_edit_draft(project, "occupied-v2", _edit(avoid=_OCCUPIED))


def _refusing_precheck(*_args, **_kwargs) -> dict:
    return {"status": "measured", "blockingIssues": [{
        "code": "ASSET_SELECTION_HARD_REGION_COLLISION",
        "message": "provably infeasible reviewed hard-region geometry",
        "details": {"stage": "geometric_precheck"},
    }]}


def test_v3_skips_the_hard_region_geometric_precheck_at_staging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(OPT_IN_ENV, PROFILE_V3)
    monkeypatch.setattr(workspace, "geometric_hard_region_precheck", _refusing_precheck)
    project = _project(tmp_path, v3=True)

    staged = workspace.stage_edit_draft(project, "hard-v3", _edit(avoid=[]))

    assert staged["changedScopes"] is not None


def test_v2_still_runs_the_hard_region_geometric_precheck(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(workspace, "geometric_hard_region_precheck", _refusing_precheck)
    project = _project(tmp_path, v3=False)

    with pytest.raises(PersianEditWorkspaceError, match="ASSET_SELECTION_HARD_REGION_COLLISION"):
        workspace.stage_edit_draft(project, "hard-v2", _edit(avoid=[]))


def test_v3_plan_without_opt_in_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(OPT_IN_ENV, raising=False)
    project = _project(tmp_path, v3=True)

    with pytest.raises(PersianEditWorkspaceError, match="not enabled"):
        workspace.stage_edit_draft(project, "no-opt-in", _edit(avoid=_OCCUPIED))
