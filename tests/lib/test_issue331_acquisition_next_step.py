"""#331: status names the remaining search passes and the one next step.

On the 2026-09-29 Mac run the agent declared the search budget exhausted after
pass 0 and asked the user a routine recovery question; the retry pass was unspent.
"""
from __future__ import annotations

import json
from pathlib import Path

from lib import persian_video_workflow as workflow
from lib.persian_video_workflow import bounded_asset_search_request, record_asset_search_result
from tests.lib.test_persian_video_workflow import BASE, _asset_result, _bootstrap_to_assets

ROOT = Path(__file__).resolve().parents[2]


def _plan(tmp_path: Path) -> None:
    plan = {"beats": [{"id": "b1", "visual_events": [
        {"id": "ve-4", "carries_moment": True, "negative_space": "upper_third"},
        {"id": "ve-5"},
    ]}]}
    path = tmp_path / "run" / "artifacts" / "scene_plan.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(plan), encoding="utf-8")


def _status(tmp_path: Path) -> dict:
    return workflow.workflow_status("run", pipeline_dir=tmp_path, now=BASE)


def test_after_pass_zero_the_retry_is_named_as_the_next_step(tmp_path: Path) -> None:
    _bootstrap_to_assets(tmp_path)
    _plan(tmp_path)
    assert _status(tmp_path)["acquisition"]["nextPass"] == 0

    request = bounded_asset_search_request("run", {}, retry_pass=0, pipeline_dir=tmp_path, now=BASE)
    record_asset_search_result("run", retry_pass=0, result_data=_asset_result(request, candidates=0, downloaded_bytes=0),
                               pipeline_dir=tmp_path, now=BASE)
    acquisition = _status(tmp_path)["acquisition"]
    assert acquisition["completedPasses"] == [0]
    assert acquisition["remainingPasses"] == [1]
    assert acquisition["unresolvedEvents"] == ["ve-4", "ve-5"]
    assert "--retry-pass 1" in acquisition["nextStep"]
    assert "not a user decision" in acquisition["nextStep"]
    line = workflow.format_status_line(_status(tmp_path))
    assert "passes_left=1" in line and "unresolved=ve-4,ve-5" in line


def test_a_spent_retry_names_the_scoped_send_back(tmp_path: Path) -> None:
    _bootstrap_to_assets(tmp_path)
    _plan(tmp_path)
    for retry in (0, 1):
        request = bounded_asset_search_request("run", {}, retry_pass=retry, pipeline_dir=tmp_path, now=BASE)
        record_asset_search_result("run", retry_pass=retry,
                                   result_data=_asset_result(request, candidates=0, downloaded_bytes=0),
                                   pipeline_dir=tmp_path, now=BASE)
    acquisition = _status(tmp_path)["acquisition"]
    assert acquisition["remainingPasses"] == []
    assert "reopen-asset-search" in acquisition["nextStep"]


def test_status_outside_acquisition_has_no_acquisition_block(tmp_path: Path) -> None:
    from tests.lib.test_persian_video_workflow import _bootstrap

    _bootstrap(tmp_path)
    assert _status(tmp_path)["acquisition"] is None


def test_asset_director_says_recovery_in_budget_is_not_a_user_decision() -> None:
    text = (ROOT / "skills/pipelines/persian-footage/asset-director.md").read_text(encoding="utf-8")
    assert "Recovery inside the pass budget is not a user decision" in text
    assert "`remainingPasses` is empty" in text


# --- queries_append and reopen-asset-search: re-sourcing without a replan ------------

from lib.checkpoint import read_checkpoint  # noqa: E402
from lib.persian_video_workflow import (  # noqa: E402
    PersianVideoWorkflowError, load_workflow_state, reconcile_scene_plan, reopen_asset_search,
)
from tests.lib.test_issue224_plan_reconcile import _event, _plan as _checkpoint_plan, _run_at_acquire  # noqa: E402
import pytest  # noqa: E402


def _spend_both_passes(tmp_path: Path) -> None:
    for retry in (0, 1):
        request = bounded_asset_search_request("run", {}, retry_pass=retry, pipeline_dir=tmp_path, now=BASE)
        record_asset_search_result("run", retry_pass=retry,
                                   result_data=_asset_result(request, candidates=0, downloaded_bytes=0),
                                   pipeline_dir=tmp_path, now=BASE)


def test_reconcile_appends_queries_and_keeps_the_authored_ones(tmp_path: Path) -> None:
    _run_at_acquire(tmp_path)
    before = list(_event(_checkpoint_plan(tmp_path), "event-0")["queries"])
    reconcile_scene_plan("run", [{"visual_event_id": "event-0",
                                  "queries_append": ["phone resting on table, plain wall above"]}],
                         reason="authored queries return close-ups", pipeline_dir=tmp_path, now=BASE)
    event = _event(_checkpoint_plan(tmp_path), "event-0")
    assert event["queries"] == before
    assert event["reconciled_queries"] == ["phone resting on table, plain wall above"]
    assert load_workflow_state("run", pipeline_dir=tmp_path)["send_backs"] == 0


def test_append_refuses_duplicates_and_caps_at_two_per_event(tmp_path: Path) -> None:
    _run_at_acquire(tmp_path)
    first = _event(_checkpoint_plan(tmp_path), "event-0")["queries"][0]
    with pytest.raises(PersianVideoWorkflowError, match="already authored"):
        reconcile_scene_plan("run", [{"visual_event_id": "event-0", "queries_append": [first]}],
                             reason="x", pipeline_dir=tmp_path, now=BASE)
    reconcile_scene_plan("run", [{"visual_event_id": "event-0", "queries_append": ["a b", "c d"]}],
                         reason="x", pipeline_dir=tmp_path, now=BASE)
    with pytest.raises(PersianVideoWorkflowError, match="at most 2"):
        reconcile_scene_plan("run", [{"visual_event_id": "event-0", "queries_append": ["e f"]}],
                             reason="x", pipeline_dir=tmp_path, now=BASE)


def test_reopen_needs_the_retry_spent_and_an_appended_query(tmp_path: Path) -> None:
    _run_at_acquire(tmp_path)
    with pytest.raises(PersianVideoWorkflowError, match="still available"):
        reopen_asset_search("run", ["event-0"], reason="x", pipeline_dir=tmp_path, now=BASE)
    _spend_both_passes(tmp_path)
    with pytest.raises(PersianVideoWorkflowError, match="queries_append first"):
        reopen_asset_search("run", ["event-0"], reason="x", pipeline_dir=tmp_path, now=BASE)
    reconcile_scene_plan("run", [{"visual_event_id": "event-0", "queries_append": ["phone flat on desk top down"]}],
                         reason="x", pipeline_dir=tmp_path, now=BASE)
    result = reopen_asset_search("run", ["event-0"], reason="band never clear", pipeline_dir=tmp_path, now=BASE)
    state = load_workflow_state("run", pipeline_dir=tmp_path)
    assert result["reopened"] == ["event-0"] and state["send_backs"] == 1
    assert state["next_phase"] == "acquire_assets"
    assert state["asset_usage"]["completed_passes"] == []
    assert state["asset_reacquisition_scope"]["visualEventIds"] == ["event-0"]
    # The scoped pass may run the appended query, and only for the named event.
    request = bounded_asset_search_request(
        "run", {"queries": [{"slot_id": "event-0", "query": "phone flat on desk top down"}]},
        retry_pass=0, pipeline_dir=tmp_path, now=BASE,
    )
    assert request["queries"][0]["query"] == "phone flat on desk top down"
    record_asset_search_result("run", retry_pass=0,
                               result_data=_asset_result(request, candidates=0, downloaded_bytes=0),
                               pipeline_dir=tmp_path, now=BASE)
    with pytest.raises(PersianVideoWorkflowError, match="outside scoped reacquisition"):
        bounded_asset_search_request(
            "run", {"queries": [{"slot_id": "event-1", "query": "x"}]},
            retry_pass=1, pipeline_dir=tmp_path, now=BASE,
        )
    assert read_checkpoint(tmp_path, "run", "scene_plan")["status"] == "completed"


def test_the_manifest_accepts_a_reconciled_query() -> None:
    from lib.persian_assets import _scene_asset_requirements

    plan = {"beats": [{"id": "b", "visual_events": [
        {"id": "ve", "queries": ["a", "b"], "reconciled_queries": ["c"]}]}]}
    requirement = _scene_asset_requirements(plan)[0][0]
    assert requirement["reconciled_queries"] == ["c"]


# --- a replan rewinds through acquisition, so the spent passes must not outlive it -----


def test_a_replan_starts_a_fresh_search_cycle_instead_of_a_dead_end(tmp_path: Path) -> None:
    """2026-09-29 run: after both passes were spent, send-back plan_scenes_moments left
    completed_passes=[0, 1], so the replanned queries failed with 'pass 0 was already
    recorded' and no path to new footage remained inside acquire_assets."""
    from lib.persian_video_workflow import request_send_back

    _run_at_acquire(tmp_path)
    _spend_both_passes(tmp_path)
    assert load_workflow_state("run", pipeline_dir=tmp_path)["asset_usage"]["completed_passes"] == [0, 1]

    request_send_back("run", "plan_scenes_moments", reason="footage never kept the band clear",
                      pipeline_dir=tmp_path, now=BASE)
    state = load_workflow_state("run", pipeline_dir=tmp_path)
    assert state["next_phase"] == "plan_scenes_moments"
    assert state["asset_usage"]["completed_passes"] == []
    assert state["asset_usage"]["acquisition_cycle"] == 1
    assert state["asset_reacquisition_grant"]["candidates"] >= 4


def test_a_send_back_before_any_search_changes_nothing_about_passes(tmp_path: Path) -> None:
    from lib.persian_video_workflow import request_send_back

    _run_at_acquire(tmp_path)
    request_send_back("run", "plan_scenes_moments", reason="rewrite", pipeline_dir=tmp_path, now=BASE)
    state = load_workflow_state("run", pipeline_dir=tmp_path)
    assert not (state.get("asset_usage") or {}).get("completed_passes")
    assert "asset_reacquisition_grant" not in state


def test_reopen_accepts_queries_a_replan_authored_after_the_passes_were_spent(tmp_path: Path) -> None:
    """A run already parked at acquire_assets with [0, 1] spent and a replanned query
    that no pass has run: reopen must work without another append."""
    from lib.persian_asset_workspace import record_discovery_pass

    _run_at_acquire(tmp_path)
    root = tmp_path / "run"
    plan = _checkpoint_plan(tmp_path)
    event = _event(plan, "event-0")
    old_query = event["queries"][0]
    clip = root / "assets" / "clips" / "c.mp4"
    clip.parent.mkdir(parents=True, exist_ok=True)
    clip.write_bytes(b"x")
    _spend_both_passes(tmp_path)
    record_discovery_pass(root, 0, [
        {"source": "pexels", "source_id": str(i), "path": str(clip), "query": q,
         "slot_id": "event-0", "duration": 5.0}
        for i, q in enumerate(event["queries"])])
    with pytest.raises(PersianVideoWorkflowError, match="no pass has run yet"):
        reopen_asset_search("run", ["event-0"], reason="x", pipeline_dir=tmp_path, now=BASE)
    # The replan rewrote the event's queries; none of them has run.
    import json as _json
    cp = root / "checkpoint_scene_plan.json"
    data = _json.loads(cp.read_text(encoding="utf-8"))
    ev = next(e for b in data["artifacts"]["scene_plan"]["beats"] for e in b["visual_events"] if e["id"] == "event-0")
    ev["queries"] = ["phone flat on a plain desk", "person holding phone in a wide cafe"]
    cp.write_text(_json.dumps(data), encoding="utf-8")
    assert reopen_asset_search("run", ["event-0"], reason="y", pipeline_dir=tmp_path, now=BASE)["reopened"] == ["event-0"]
