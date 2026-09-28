"""#315: a search in a fresh acquisition cycle records the next workspace discovery pass.

f418063 Mac acceptance run (2026-09-28): after a user-directed rewind to acquire_assets,
the workflow's pass counter restarted at 0, but the workspace's pass-000 from the first
cycle still existed with different clips, so every search of the new cycle was refused
with "asset discovery pass identity is immutable; use the next retry pass", while retry
pass 1 was refused as "passes must be sequential; completed=[]".
"""
from __future__ import annotations

from pathlib import Path

from lib import persian_asset_workspace as workspace
from lib.persian_video_workflow import (
    bounded_asset_search_request, load_workflow_state, record_asset_search_result, _write_state,
)
from tests.lib.test_issue239_retry_after_review import _clip, _first_pass
from tests.lib.test_persian_video_workflow import BASE, _asset_result


def test_a_new_cycle_search_with_different_clips_is_recorded(tmp_path: Path) -> None:
    project = _first_pass(tmp_path, ["ev-1", "ev-13"])
    # What a rewind into acquisition does to the ledger (request_send_back, #175).
    state = load_workflow_state("run", pipeline_dir=tmp_path)
    usage = dict(state.get("asset_usage") or {})
    usage["completed_passes"] = []
    usage["acquisition_cycle"] = int(usage.get("acquisition_cycle") or 0) + 1
    state["asset_usage"] = usage
    _write_state(project, state)

    request = bounded_asset_search_request(
        "run", {"queries": [{"query": "lit night street", "slot_id": "ev-13", "kind": "video"}]},
        retry_pass=0, pipeline_dir=tmp_path, now=BASE,
    )
    record_asset_search_result(
        "run", retry_pass=0,
        result_data=_asset_result(request, candidates=1, downloaded_bytes=100,
                                  clips=[_clip(tmp_path, "ev-13-lit")]),
        pipeline_dir=tmp_path, now=BASE,
    )
    status = workspace.asset_workspace_status(project)
    assert status["discoveryPassCount"] == 2
