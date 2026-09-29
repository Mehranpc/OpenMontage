"""#246: the candidate ceiling scales with the plan's footage events.

A fixed 16 left a 14-event plan two spare candidates. Review rejected 6 of 14, and the run
stopped on a human question (the 2026-09-27 acceptance rerun on f13d914).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lib.persian_video_workflow import bounded_asset_search_request
from tests.lib.test_issue35_semantic_scene_plan_checkpoint import _event
from tests.lib.test_persian_video_workflow import BASE, _bootstrap_to_assets


def _plan(tmp_path: Path, events: int) -> None:
    beats = [{"id": f"beat-{i}", "intent_fa": "x", "script_line_fa": "x", "duration_seconds": 4.0,
              "typographic": False, "visual_events": [_event(f"ev-{i:02d}", 4.0)]}
             for i in range(events)]
    path = tmp_path / "run" / "checkpoint_scene_plan.json"
    checkpoint = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    checkpoint.update({"stage": "scene_plan", "status": "completed",
                       "artifacts": {"scene_plan": {"version": "2.0", "beats": beats}}})
    path.write_text(json.dumps(checkpoint, ensure_ascii=False), encoding="utf-8")


@pytest.mark.parametrize(("events", "ceiling"), [(0, 16), (5, 16), (8, 16), (14, 28), (20, 32)])
def test_ceiling_is_two_per_event_never_below_policy_and_capped(tmp_path: Path, events: int, ceiling: int) -> None:
    _bootstrap_to_assets(tmp_path)
    if events:
        _plan(tmp_path, events)
    request = bounded_asset_search_request("run", {}, retry_pass=0, pipeline_dir=tmp_path, now=BASE)
    assert request["max_candidates_total"] == ceiling


def test_moment_carriers_count_double_toward_the_ceiling(tmp_path: Path) -> None:
    """#335: 8 of 11 events carried a moment and 22 candidates were spent before the last
    carrier was resolved. A carrier needs footage that leaves a band clear, so it weighs 2."""
    from lib.persian_video_workflow import _planned_footage_events, load_workflow_state

    _bootstrap_to_assets(tmp_path)
    _plan(tmp_path, 11)
    path = tmp_path / "run" / "checkpoint_scene_plan.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    events = [e for b in data["artifacts"]["scene_plan"]["beats"] for e in b["visual_events"]]
    state = load_workflow_state("run", pipeline_dir=tmp_path)
    assert _planned_footage_events(state) == 11
    for event in events[:8]:
        event["carries_moment"] = True
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    assert _planned_footage_events(state) == 19
    request = bounded_asset_search_request("run", {}, retry_pass=0, pipeline_dir=tmp_path, now=BASE)
    assert request["max_candidates_total"] == 32  # 2 * 19 = 38, capped at 32
