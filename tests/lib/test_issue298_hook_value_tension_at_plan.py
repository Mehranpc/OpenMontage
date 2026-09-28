"""#298 (#263 item K): viewer value and semantic tension ceilings at plan.

Real first-date timings: «قرار خوب» at 1.12s, «پیام بدی یا صبر کنی» at 3.72s,
«پژوهشگرا» at 5.16s.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from lib import persian_video_workflow as workflow
from tests.lib.test_issue262_hook_proof_at_plan import _script_checkpoint, _state  # noqa: F401


def test_prompt_value_and_tension_are_recorded(tmp_path: Path) -> None:
    records = workflow._plan_hook_opening_ceilings(_state(tmp_path), {
        "hook_viewer_value": {"anchorText": "قرار خوب", "evidence": "the viewer's own situation"},
        "hook_semantic_tension": {"anchorText": "پیام بدی یا صبر کنی", "evidence": "the open choice"},
    })
    assert records["hook_viewer_value"]["atSeconds"] == pytest.approx(1.12, abs=0.01)
    assert records["hook_semantic_tension"]["atSeconds"] == pytest.approx(3.72, abs=0.01)


def test_late_tension_stops_the_plan_even_for_a_user_owned_hook(tmp_path: Path) -> None:
    state = _state(tmp_path, user_hook="پیام بدی یا صبر کنی؟ بعد از یه قرار خوب")
    with pytest.raises(workflow.PersianVideoWorkflowError, match=r"\[HOOK_TENSION_LATE\].*5\.1\ds.*4\.0s"):
        workflow._plan_hook_opening_ceilings(state, {"hook_semantic_tension": {"anchorText": "پژوهشگرا"}})


def test_both_late_ceilings_are_named_at_once(tmp_path: Path) -> None:
    with pytest.raises(workflow.PersianVideoWorkflowError) as caught:
        workflow._plan_hook_opening_ceilings(_state(tmp_path), {
            "hook_viewer_value": {"anchorText": "پیام بدی"},
            "hook_semantic_tension": {"anchorText": "پژوهشگرا"},
        })
    assert "[HOOK_VALUE_LATE]" in str(caught.value) and "[HOOK_TENSION_LATE]" in str(caught.value)


def test_nothing_named_changes_nothing(tmp_path: Path) -> None:
    assert workflow._plan_hook_opening_ceilings(_state(tmp_path), {}) == {}
