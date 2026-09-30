"""A scoped reopen must not strand the events it did not name.

`reopen-asset-search` re-sources a named subset of events and scopes the cycle to
them. The scope is a *re-sourcing* boundary, but `select_workflow_asset_candidate`
applied it to selection too, and `acquire_assets` cannot complete without a canonical
manifest row for *every* visual event. So a reopen that names a subset while other
events still have no selection makes the phase unreachable: selection outside the
scope is refused, and the scope is popped only by the completion the manifest blocks.

The 2026-09-30 run stopped there for real -- four events were reopened, eight
already-reviewed events could not be selected, and every other escape refused
(send-back cannot rewind to the phase it is already on; reopen needs an unspent
retry pass first). This test pins the gap: an event with no selection may still be
selected during a scoped reopen, while re-selecting an event the scope did not name
stays refused.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from lib import persian_asset_workspace as workspace
from lib.persian_video_workflow import (
    PersianVideoWorkflowError,
    reconcile_scene_plan,
    reopen_asset_search,
    select_workflow_asset_candidate,
)
from tests.lib.test_issue224_plan_reconcile import _run_at_acquire
from tests.lib.test_issue331_acquisition_next_step import _spend_both_passes
from tests.lib.test_issue35_asset_candidate_workspace import _discovered, _review
from tests.lib.test_persian_video_workflow import BASE


def _reopened_scope(tmp_path: Path, events: list[str]) -> None:
    """Leave the run mid scoped reopen for `events`, with both retry passes spent."""
    _spend_both_passes(tmp_path)
    reconcile_scene_plan(
        "run",
        [{"visual_event_id": event, "queries_append": [f"one more framing for {event}"]}
         for event in events],
        reason="band never clear", pipeline_dir=tmp_path, now=BASE,
    )
    reopen_asset_search("run", events, reason="band never clear", pipeline_dir=tmp_path, now=BASE)


def _reviewed_candidate(tmp_path: Path, event: str, source_id: str, *, discovery_pass: int = 0) -> str:
    project = tmp_path / "run"
    discovery = workspace.record_discovery_pass(
        project, discovery_pass,
        [_discovered(project, source_id=source_id, name=f"{source_id}.mp4", slot_id=event)],
    )
    candidate = workspace.stage_asset_candidate(
        project,
        discovery_id=discovery["candidateIds"][0],
        visual_event_id=event,
        semantic_beat_id="beat-1",
        source_in_seconds=0.0,
        duration_seconds=4.0,
        intended_crop={"mode": "full_frame"},
        candidate_rank=1,
        query="person thinking at desk",
        narration_span="این یک جمله نمونه است",
    )
    workspace.record_candidate_review(project, candidate["candidateId"], _review())
    return candidate["candidateId"]


def test_an_event_outside_the_scope_can_still_be_selected_when_it_has_no_selection(
    tmp_path: Path,
) -> None:
    """The scoped-repair gap that made acquire_assets unreachable (#341 run)."""
    _run_at_acquire(tmp_path)
    candidate = _reviewed_candidate(tmp_path, "event-1", "source-gap")
    _reopened_scope(tmp_path, ["event-0"])

    # event-1 was never named by the repair and never had a selection. The canonical
    # manifest needs its row, so the scope must not block filling the gap.
    select_workflow_asset_candidate(
        "run", "event-1", candidate, rejected_alternatives={},
        pipeline_dir=tmp_path,
    )
    assert workspace.asset_workspace_status(tmp_path / "run")["selectedCandidateIds"] == {"event-1": candidate}


@pytest.mark.parametrize("event_id", ["event-1", " event-1 "])
def test_the_scope_still_refuses_replacing_an_event_it_did_not_name(
    tmp_path: Path, event_id: str,
) -> None:
    """The fix keeps the boundary: a scoped repair may not swap other events' picks."""
    _run_at_acquire(tmp_path)
    first = _reviewed_candidate(tmp_path, "event-1", "source-first")
    select_workflow_asset_candidate(
        "run", "event-1", first, rejected_alternatives={},
        pipeline_dir=tmp_path,
    )
    replacement = _reviewed_candidate(tmp_path, "event-1", "source-replacement", discovery_pass=1)
    _reopened_scope(tmp_path, ["event-0"])

    with pytest.raises(PersianVideoWorkflowError, match="outside scoped reacquisition"):
        select_workflow_asset_candidate(
            "run", event_id, replacement, rejected_alternatives={first: "prefer replacement"}, replace_existing=True,
            pipeline_dir=tmp_path,
        )

    assert workspace.asset_workspace_status(tmp_path / "run")["selectedCandidateIds"] == {"event-1": first}
