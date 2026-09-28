"""#263 item L: the assets checkpoint must record spend when acquire_assets completes.

Delivery quality reads spend from that checkpoint and blocks the report without it
(#234), which was discovered only at stage-candidate, after the render.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lib import persian_video_workflow as workflow
from tests.lib.test_persian_video_workflow import BASE, _bootstrap_to_assets


def _complete_with(tmp_path: Path, monkeypatch, checkpoint: dict) -> dict:
    _bootstrap_to_assets(tmp_path)
    workflow.record_phase_attempt("run", "acquire_assets", pipeline_dir=tmp_path, now=BASE)
    monkeypatch.setattr(workflow, "read_checkpoint", lambda *args, **kwargs: checkpoint)
    monkeypatch.setattr(
        workflow, "validate_asset_manifest_against_workspace",
        lambda project_dir, manifest: {"enforced": True, "selectedCount": 0},
    )
    return workflow.complete_phase("run", "acquire_assets", pipeline_dir=tmp_path, now=BASE)


def test_a_manifest_without_spend_is_refused_at_acquire_assets(tmp_path, monkeypatch) -> None:
    checkpoint = {"status": "completed", "artifacts": {"asset_manifest": {"version": "1.0", "assets": []}}}
    with pytest.raises(workflow.PersianVideoWorkflowError, match="must record spend"):
        _complete_with(tmp_path, monkeypatch, checkpoint)


@pytest.mark.parametrize("bad", [None, True, -1.0, "0"])
def test_a_non_numeric_or_negative_total_is_refused(tmp_path, monkeypatch, bad) -> None:
    checkpoint = {"status": "completed",
                  "artifacts": {"asset_manifest": {"version": "1.0", "assets": [], "total_cost_usd": bad}}}
    with pytest.raises(workflow.PersianVideoWorkflowError, match="must record spend"):
        _complete_with(tmp_path, monkeypatch, checkpoint)


def test_a_manifest_total_is_enough(tmp_path, monkeypatch) -> None:
    checkpoint = {"status": "completed",
                  "artifacts": {"asset_manifest": {"version": "1.0", "assets": [], "total_cost_usd": 0.0}}}
    state = _complete_with(tmp_path, monkeypatch, checkpoint)
    assert "acquire_assets" in state["completed_phases"]


def test_a_cost_snapshot_is_enough(tmp_path, monkeypatch) -> None:
    checkpoint = {"status": "completed", "cost_snapshot": {"total_spent_usd": 1.25},
                  "artifacts": {"asset_manifest": {"version": "1.0", "assets": []}}}
    state = _complete_with(tmp_path, monkeypatch, checkpoint)
    assert "acquire_assets" in state["completed_phases"]
