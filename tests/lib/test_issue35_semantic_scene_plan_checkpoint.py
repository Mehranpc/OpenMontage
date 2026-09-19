from __future__ import annotations

from schemas.artifacts import validate_artifact
from lib.persian_video_workflow import validate_scene_plan_budget, validate_scene_plan_duration


def _event(event_id: str, duration: float) -> dict:
    return {
        "id": event_id,
        "duration_seconds": duration,
        "narration_span": "متن تأییدشده",
        "intent": "show the literal subject",
        "subject": "video gaming",
        "action": "playing a console game",
        "desired_affect": "curiosity",
        "motif": "gaming focus",
        "visual_search_brief": "real gamer playing console at home",
        "shot_composition": "close player and controller, crop-safe center action",
        "human_presence": True,
        "importance": 3,
        "conflict_visibility": "the subject is visibly engaged in play",
        "fallback_level": "exact_literal",
        "camera": "push-in",
        "shows_subject": True,
        "shot_scale": "close up",
        "environment": "living room",
        "queries": ["gamer controller close up", "console player living room"],
    }


def _semantic_plan() -> dict:
    return {
        "version": "2.0",
        "format": "vertical",
        "subject": "video gaming",
        "target_duration_seconds": 47.49,
        "beats": [
            {
                "id": "beat-1",
                "intent_fa": "شروع",
                "script_line_fa": "متن تأییدشده",
                "duration_seconds": 20.0,
                "typographic": False,
                "visual_events": [_event("event-1", 20.0)],
            },
            {
                "id": "beat-2",
                "intent_fa": "پایان",
                "script_line_fa": "ادامه متن تأییدشده",
                "duration_seconds": 27.49,
                "typographic": False,
                "visual_events": [_event("event-2", 27.49)],
            },
        ],
    }


def test_semantic_scene_plan_is_a_first_class_checkpoint_artifact() -> None:
    validate_artifact("scene_plan", _semantic_plan())


def test_legacy_scene_plan_remains_schema_compatible() -> None:
    validate_artifact(
        "scene_plan",
        {
            "version": "1.0",
            "scenes": [
                {
                    "id": "scene-1",
                    "type": "broll",
                    "description": "legacy fixture",
                    "start_seconds": 0.0,
                    "end_seconds": 5.0,
                }
            ],
        },
    )


def test_semantic_plan_budget_reads_top_level_visual_events() -> None:
    evidence = validate_scene_plan_budget(
        _semantic_plan(), max_semantic_candidates=16, rejection_margin=0.25
    )
    assert evidence["mandatoryDistinctEvents"] == 2
    assert evidence["eventIds"] == ["event-1", "event-2"]


def test_semantic_plan_duration_uses_beat_duration_sum() -> None:
    evidence = validate_scene_plan_duration(
        _semantic_plan(), narration_duration_seconds=47.49, fps=30.0
    )
    assert evidence["withinFrameTolerance"] is True
    assert evidence["scenePlanEndSeconds"] == 47.49
