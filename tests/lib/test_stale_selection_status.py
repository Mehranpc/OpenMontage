"""Public #360 diagnosis survives missing selected records, including at a stop."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from lib import persian_asset_workspace as workspace
from lib import persian_video_workflow as workflow
from tests.lib.test_issue224_plan_reconcile import _run_at_acquire
from tests.lib.test_issue360_preparation_and_stop import _stopped_run
from tests.lib.test_issue360_truthful_readiness import BASE, _candidate, _project_bytes


@pytest.mark.parametrize("stopped", [False, True])
@pytest.mark.parametrize("damage", ["missing", "unreadable"])
def test_public_status_reports_stale_selected_evidence_without_repairing_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
    stopped: bool, damage: str,
) -> None:
    if stopped:
        project, _ = _stopped_run(tmp_path)
        selected = workspace.asset_workspace_status(project)["selectedCandidateIds"]["event-0"]
    else:
        project = _run_at_acquire(tmp_path)
        selected = _candidate(tmp_path, "event-0", "selected")
        workflow.select_workflow_asset_candidate(
            "run", "event-0", selected, rejected_alternatives={}, pipeline_dir=tmp_path,
        )
    # A second valid selection must survive the damaged neighbour.
    good = _candidate(tmp_path, "event-1", "good")
    # Seed the intact selection via the workspace in the stopped case; no budget bypass
    # is performed by the operation under test, which is read-only status.
    workspace.select_asset_candidate(project, "event-1", good, rejected_alternatives={})
    path = workspace._candidate_path(project, selected)
    if damage == "missing":
        path.unlink()
    else:
        path.write_text("{torn", encoding="utf-8")
    durable = _project_bytes(project)

    first = workflow.workflow_status("run", pipeline_dir=tmp_path, now=BASE)
    again = workflow.workflow_status("run", pipeline_dir=tmp_path, now=BASE)
    acquisition = first["acquisition"]
    assert acquisition == again["acquisition"]
    assert first["asset_workspace"]["selectedCount"] == 2
    assert first["asset_workspace"]["selectedCandidateIds"] == {
        "event-0": selected, "event-1": good,
    }
    assert acquisition["recordedSelectionCount"] == 2
    assert acquisition["validSelectionCount"] == 1
    assert acquisition["unresolvedEvents"] == ["event-2"]
    assert acquisition["staleEvents"] == ["event-0"]
    assert acquisition["invalidEvents"] == []
    assert acquisition["readiness"]["disposition"] == "stale_selections"
    [diagnostic] = acquisition["readiness"]["diagnostics"]["event-0"]
    assert diagnostic["code"] == "SELECTION_CANDIDATE_MISSING"
    assert diagnostic["candidateId"] == selected
    assert acquisition["preparation"]["blockers"] == {
        "event-0": ["SELECTION_CANDIDATE_MISSING"],
    }
    assert "Do not build the manifest yet" in acquisition["nextStep"]
    if stopped:
        assert first["status"] == "failed"
        assert first["budget_stop"]
        assert acquisition["preparation"]["decisionRequired"]["kind"] == "budget_stop"
    else:
        assert acquisition["preparation"]["decisionRequired"] is None
    assert _project_bytes(project) == durable

    # Read-only diagnosis must not weaken mutation admission: the full ledger's
    # unknown source window still refuses an otherwise idempotent selection.
    with pytest.raises(workspace.PersianAssetWorkspaceError, match="does not exist|unreadable"):
        workspace.select_asset_candidate(project, "event-1", good, rejected_alternatives={})
    assert _project_bytes(project) == durable

    monkeypatch.setattr(workflow, "PROJECTS_DIR", tmp_path)
    capsys.readouterr()
    assert workflow.main(["status", "run", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["acquisition"]["staleEvents"] == ["event-0"]
    assert payload["acquisition"]["validSelectionCount"] == 1
    assert payload["budget_stop"] == first["budget_stop"]
    assert workflow.main(["status", "run"]) == 0
    assert "Do not build the manifest yet" in capsys.readouterr().out
    assert _project_bytes(project) == durable
