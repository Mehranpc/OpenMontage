"""#213: moment copy that cannot be read in its window is refused at plan time."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from lib import persian_video_workflow as workflow
from lib.persian_moments import MAX_TEXT_COVERAGE
from lib.persian_scenes import _film_motion, moment_copy_feasibility_problems
from lib.persian_video_workflow import complete_phase, record_phase_attempt
from tests.lib.test_issue195_scene_plan_duration_gate import (
    BASE, _advance_to_plan_scenes, _bootstrap, _write_checkpoint,
)

HERO = [{"role": "hero", "text": "دو روز صبر کردن"}]
LONG = [
    {"role": "lead", "text": "در این مطالعه، شرکت‌کننده‌ها"},
    {"role": "hero", "text": "۵۴۳ نفر"},
    {"role": "tail", "text": "تصور کردند یک قرار اول داشتند."},
]


def _event(index: int, duration: float) -> dict:
    """A schema-complete visual event, so the plan checkpoint itself validates."""
    return {
        "id": f"event-{index}", "duration_seconds": duration, "carries_moment": True,
        "negative_space": "upper_band", "narration_span": "span", "intent": "intent",
        "subject": "phone", "action": "lying", "desired_affect": "calm", "motif": "phone",
        "visual_search_brief": "phone on table", "shot_composition": "wide",
        "human_presence": False, "importance": 2, "conflict_visibility": "low",
        "fallback_level": "exact_literal", "camera": "none", "shows_subject": True,
        "shot_scale": "wide", "environment": "table",
        "queries": ["phone on plain table wide shot", "phone lying on empty desk"],
    }


def _beats(*events: tuple[float, list | None]) -> list[dict]:
    beats = []
    for index, (duration, copy_) in enumerate(events):
        event = _event(index, duration)
        if copy_ is not None:
            event["moment_copy"] = copy_
        beats.append({
            "id": f"beat-{index}", "duration_seconds": duration, "typographic": False,
            "visual_events": [event],
        })
    return beats


def test_copy_that_fits_its_window_passes() -> None:
    assert moment_copy_feasibility_problems(_beats((4.0, HERO)), 60.0) == []


def test_copy_longer_than_its_window_is_refused_with_the_film_floor() -> None:
    problems = moment_copy_feasibility_problems(_beats((3.0, LONG)), 60.0)
    assert len(problems) == 1
    assert "event-0" in problems[0] and "needs" in problems[0] and "3.00s" in problems[0]


def test_events_without_declared_copy_are_not_charged() -> None:
    assert moment_copy_feasibility_problems(_beats((1.0, None)), 60.0) == []


def test_the_set_is_refused_when_floors_exceed_the_coverage_ceiling() -> None:
    """The Mac run's shape: every moment fits alone, the set cannot fit the ceiling."""
    events = [(6.0, LONG)] * 7
    duration = 62.5
    problems = moment_copy_feasibility_problems(_beats(*events), duration)
    assert any("coverage ceiling" in p for p in problems)
    assert f"{MAX_TEXT_COVERAGE * duration:.1f}s" in next(p for p in problems if "coverage" in p)


def test_malformed_copy_is_a_plan_problem() -> None:
    problems = moment_copy_feasibility_problems(_beats((4.0, [{"role": "kicker", "text": "x"}])), 60.0)
    assert problems and "moment_copy[0]" in problems[0]


def test_uses_the_film_type_floor_not_the_plain_estimate() -> None:
    from lib.persian_moments import PersianMoment, PersianSegment

    segments = [PersianSegment(role=s["role"], text=s["text"]) for s in LONG]
    probe = PersianMoment(id="p", kind="statement", start_seconds=0, end_seconds=9, segments=segments)
    plain, film = probe.min_read_seconds, probe.film_min_read_seconds(_film_motion())
    assert film > plain
    window = (plain + film) / 2
    assert moment_copy_feasibility_problems(_beats((window, LONG)), 60.0)


def test_plan_completion_refuses_infeasible_declared_copy(tmp_path: Path) -> None:
    _bootstrap(tmp_path)
    _advance_to_plan_scenes(tmp_path)
    plan = {"version": "2.0", "format": "vertical", "subject": "phone",
            "beats": _beats((3.0, LONG), (57.0, None))}
    _write_checkpoint(tmp_path, "scene_plan", "scene_plan", plan)
    record_phase_attempt("run", "plan_scenes_moments", pipeline_dir=tmp_path, now=BASE)
    with pytest.raises(workflow.PersianVideoWorkflowError, match="MOMENT_COPY_INFEASIBLE"):
        complete_phase("run", "plan_scenes_moments", evidence={}, pipeline_dir=tmp_path, now=BASE)


def test_plan_completion_advances_feasible_declared_copy(tmp_path: Path) -> None:
    _bootstrap(tmp_path)
    _advance_to_plan_scenes(tmp_path)
    plan = {"version": "2.0", "format": "vertical", "subject": "phone",
            "beats": _beats((4.0, HERO), (56.0, None))}
    _write_checkpoint(tmp_path, "scene_plan", "scene_plan", plan)
    record_phase_attempt("run", "plan_scenes_moments", pipeline_dir=tmp_path, now=BASE)
    state = complete_phase("run", "plan_scenes_moments", evidence={}, pipeline_dir=tmp_path, now=BASE)
    assert "plan_scenes_moments" in state["completed_phases"]
