"""#195: the scene-plan gate declares a duration-coverage rule and now enforces it.

The contract (`pipeline_defs/persian-footage.yaml`) tells the agent that
`lib.persian_scenes.audit_scene_plan` enforces "Sum of beat durations ... the target
duration", but the audit had no target to check against and
`validate_scene_plan_duration` -- the one implementation of the rule -- had no callers.
These tests pin both ends: the audit reports a plan that misses the target, and
`plan_scenes_moments` completion refuses one, reusing that same function.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

import lib.persian_video_workflow as workflow
from lib.persian_scenes import (
    audit_scene_plan,
    scene_plan_duration_tolerance_seconds,
)
from lib.persian_video_workflow import (
    PHASES,
    PersianVideoWorkflowError,
    bootstrap_persian_video,
    complete_phase,
    load_workflow_state,
    record_phase_attempt,
    validate_scene_plan_duration,
)

ROOT = Path(__file__).resolve().parents[2]
BASE = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)


def _beat(index: int, duration: float) -> dict:
    return {"id": f"beat-{index}", "duration_seconds": duration}


def _audit_plan(beats: list[dict], **extra) -> dict:
    return {"metadata": {"subject": "coffee", "beats": beats}, **extra}


def _duration_problems(report: dict) -> list[str]:
    return [problem for problem in report["problems"] if "target duration" in problem]


def _legacy_plan(end_seconds: float, **extra) -> dict:
    return {
        "version": "1.0",
        "scenes": [
            {
                "id": "fixture-scene",
                "type": "broll",
                "description": "checkpoint fixture",
                "start_seconds": 0.0,
                "end_seconds": end_seconds,
            }
        ],
        **extra,
    }


def _bootstrap(tmp_path: Path) -> dict:
    external = tmp_path.parent / f"{tmp_path.name}-source.wav"
    external.write_bytes(b"audio")
    return bootstrap_persian_video(
        title="Run",
        narration_path=str(external),
        approved_script="متن تأییدشده",
        project_id="run",
        pipeline_dir=tmp_path,
        backlot_opener=lambda pid: 0,
        now=BASE,
    )


def _advance_to_plan_scenes(tmp_path: Path) -> dict:
    """Walk to plan_scenes_moments, bypassing checkpoint-backed phases.

    Real runs always have a completed `script` checkpoint by now (align_script_timing
    gates on it); the bypass keeps these tests focused on the duration binding, which
    writes its own checkpoints below.
    """
    state = load_workflow_state("run", pipeline_dir=tmp_path)
    while state.get("next_phase") != "plan_scenes_moments":
        phase = state.get("next_phase")
        state = record_phase_attempt("run", phase, pipeline_dir=tmp_path, now=BASE)
        if phase in workflow._PHASE_CHECKPOINT or phase in {
            "render_opening_candidate", "render_final_candidate", "master_final_candidate",
        }:
            completed = list(state.get("completed_phases") or [])
            completed.append(phase)
            state["completed_phases"] = completed
            state["next_phase"] = PHASES[PHASES.index(phase) + 1]
            workflow._write_state(tmp_path / "run", state)
            continue
        evidence = None
        if phase == "prepare_inputs":
            approved = state["input"].get("approved_script")
            script_sha = approved["sha256"] if approved else "a" * 64
            evidence = {
                "authoritative_script_sha256": script_sha,
                "narration_sha256": state["input"]["narration"]["sha256"],
            }
        state = complete_phase("run", phase, evidence=evidence, pipeline_dir=tmp_path, now=BASE)
    return state


def _write_checkpoint(tmp_path: Path, stage: str, artifact_name: str, artifact: dict) -> None:
    (tmp_path / "run" / f"checkpoint_{stage}.json").write_text(
        json.dumps(
            {
                "version": "1.0",
                "project_id": "run",
                "pipeline_type": "persian-footage",
                "stage": stage,
                "status": "completed",
                "timestamp": BASE.isoformat(),
                "checkpoint_policy": "guided",
                "human_approval_required": False,
                "human_approved": False,
                "artifacts": {artifact_name: artifact},
            }
        ),
        encoding="utf-8",
    )


def _write_script_checkpoint(tmp_path: Path, total_duration_seconds: float) -> None:
    _write_checkpoint(
        tmp_path,
        "script",
        "script",
        {
            "version": "1.0",
            "title": "Run",
            "total_duration_seconds": total_duration_seconds,
            "sections": [
                {"id": "s1", "text": "متن", "start_seconds": 0.0, "end_seconds": total_duration_seconds}
            ],
        },
    )


# --- The audit enforces the rule it advertises ------------------------------------------


def test_audit_reports_a_plan_that_misses_the_target_duration() -> None:
    report = audit_scene_plan(
        _audit_plan([_beat(1, 10.0), _beat(2, 5.0)]), target_duration_seconds=20.0
    )
    problems = _duration_problems(report)
    assert problems, report["problems"]
    assert "15.000s" in problems[0] and "20.000s" in problems[0]


def test_audit_accepts_a_plan_within_one_frame_of_the_target() -> None:
    # Half a frame at 30fps is inside; anything that widens the tolerance to zero would
    # refuse a plan the contract promises to accept.
    report = audit_scene_plan(
        _audit_plan([_beat(1, 10.0), _beat(2, 5.0 + 1.0 / 60.0)]),
        target_duration_seconds=15.0,
    )
    assert _duration_problems(report) == []


def test_audit_reads_the_target_duration_declared_on_the_plan() -> None:
    report = audit_scene_plan(
        _audit_plan([_beat(1, 10.0), _beat(2, 5.0)], target_duration_seconds=20.0)
    )
    assert _duration_problems(report), report["problems"]


def test_audit_makes_no_claim_when_no_target_is_named() -> None:
    report = audit_scene_plan(_audit_plan([_beat(1, 10.0), _beat(2, 5.0)]))
    assert _duration_problems(report) == []


def test_the_audit_and_the_binding_share_one_tolerance() -> None:
    plan = _legacy_plan(end_seconds=15.0)
    # One frame at 30fps is 0.0(3)s; half a frame is inside, two frames are outside.
    inside = validate_scene_plan_duration(
        plan, narration_duration_seconds=15.0 + 1.0 / 60.0
    )
    assert inside["frameToleranceSeconds"] == round(
        scene_plan_duration_tolerance_seconds(30.0), 6
    )
    with pytest.raises(PersianVideoWorkflowError, match="authoritative narration duration"):
        validate_scene_plan_duration(plan, narration_duration_seconds=15.0 + 2.0 / 30.0)


# --- plan_scenes_moments completion refuses a mistimed plan ------------------------------


def test_completion_refuses_a_plan_that_does_not_cover_the_narration(tmp_path: Path) -> None:
    _bootstrap(tmp_path)
    _advance_to_plan_scenes(tmp_path)
    _write_script_checkpoint(tmp_path, 60.0)
    _write_checkpoint(tmp_path, "scene_plan", "scene_plan", _legacy_plan(end_seconds=1.0))

    record_phase_attempt("run", "plan_scenes_moments", pipeline_dir=tmp_path, now=BASE)
    with pytest.raises(
        PersianVideoWorkflowError, match="does not match authoritative narration duration"
    ):
        complete_phase(
            "run", "plan_scenes_moments", evidence={}, pipeline_dir=tmp_path, now=BASE
        )


def test_completion_advances_a_plan_that_covers_the_narration_within_a_frame(
    tmp_path: Path,
) -> None:
    _bootstrap(tmp_path)
    _advance_to_plan_scenes(tmp_path)
    _write_script_checkpoint(tmp_path, 60.0)
    _write_checkpoint(
        tmp_path,
        "scene_plan",
        "scene_plan",
        _legacy_plan(end_seconds=60.0 + 1.0 / 60.0),
    )

    record_phase_attempt("run", "plan_scenes_moments", pipeline_dir=tmp_path, now=BASE)
    state = complete_phase(
        "run", "plan_scenes_moments", evidence={}, pipeline_dir=tmp_path, now=BASE
    )
    assert "plan_scenes_moments" in state["completed_phases"]
    binding = state["evidence"]["plan_scenes_moments"]["durationBinding"]
    assert binding["withinFrameTolerance"] is True
    assert binding["narrationDurationSeconds"] == 60.0


def test_completion_binds_a_plan_to_its_own_declared_target_without_a_script_checkpoint(
    tmp_path: Path,
) -> None:
    _bootstrap(tmp_path)
    _advance_to_plan_scenes(tmp_path)
    _write_checkpoint(
        tmp_path,
        "scene_plan",
        "scene_plan",
        _legacy_plan(end_seconds=1.0, target_duration_seconds=60.0),
    )

    record_phase_attempt("run", "plan_scenes_moments", pipeline_dir=tmp_path, now=BASE)
    with pytest.raises(
        PersianVideoWorkflowError, match="does not match authoritative narration duration"
    ):
        complete_phase(
            "run", "plan_scenes_moments", evidence={}, pipeline_dir=tmp_path, now=BASE
        )


# --- The contract names the gate; the gate enforces the rule -----------------------------


def test_the_gate_named_in_the_manifest_is_what_enforces_the_duration_rule() -> None:
    manifest = yaml.safe_load((ROOT / "pipeline_defs" / "persian-footage.yaml").read_text())
    stage = next(item for item in manifest["stages"] if item["name"] == "scene_plan")
    focus = stage["review_focus"]
    rule = next(line for line in focus if "beat durations" in line)
    gate = next(line for line in focus if "RUN THE GATE" in line)
    assert "audit_scene_plan" in gate
    # The declared rule is the frame-exact binding, and the function the contract names
    # is the function that enforces it.
    assert "one frame" in rule
    plan = _audit_plan([_beat(1, 1.0), _beat(2, 1.0)], target_duration_seconds=60.0)
    assert _duration_problems(audit_scene_plan(plan, target_duration_seconds=60.0))
