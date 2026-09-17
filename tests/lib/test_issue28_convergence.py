from __future__ import annotations

from pathlib import Path

import pytest

from lib import persian_finalization
from lib.persian_recovery_policy import recovery_policy_for_issue
from lib.persian_video_workflow import (
    PersianVideoWorkflowError,
    validate_scene_plan_budget,
    validate_scene_plan_duration,
)


def test_watermark_and_typography_recovery_cannot_mutate_editorial_assets() -> None:
    watermark = recovery_policy_for_issue({"code": "WATERMARK_COVERAGE"})
    typography = recovery_policy_for_issue({"code": "FILM_TYPE_LAYOUT"})
    assert watermark["mutationSurface"] == ["watermark.schedule", "watermark.suppression"]
    assert typography["mutationSurface"] == ["typography.recipe", "typography.line_plan", "typography.duration"]
    forbidden = ("asset", "footage", "scene", "subject")
    assert not any(word in strategy for strategy in watermark["strategies"] for word in forbidden)
    assert not any(word in strategy for strategy in typography["strategies"] for word in forbidden)


def test_scene_plan_must_leave_semantic_candidate_rejection_margin() -> None:
    plan = {"metadata": {"beats": [{"visual_events": [{"id": f"e{i}"} for i in range(14)]}]}}
    with pytest.raises(PersianVideoWorkflowError, match="candidate budget"):
        validate_scene_plan_budget(plan, max_semantic_candidates=16, rejection_margin=0.25)
    healthy = {"metadata": {"beats": [{"visual_events": [{"id": f"e{i}"} for i in range(8)]}]}}
    evidence = validate_scene_plan_budget(healthy, max_semantic_candidates=16, rejection_margin=0.25)
    assert evidence["mandatoryDistinctEvents"] == 8
    assert evidence["semanticCandidateHeadroom"] == 8


def test_scene_plan_duration_must_match_authoritative_narration_with_frame_tolerance() -> None:
    plan = {"scenes": [{"start_seconds": 0.0, "end_seconds": 47.5}]}
    evidence = validate_scene_plan_duration(plan, narration_duration_seconds=47.49, fps=30.0)
    assert evidence["withinFrameTolerance"] is True
    with pytest.raises(PersianVideoWorkflowError, match="authoritative narration duration"):
        validate_scene_plan_duration(plan, narration_duration_seconds=47.1, fps=30.0)


def test_mastering_is_idempotent_when_candidate_already_meets_policy(tmp_path: Path) -> None:
    source = tmp_path / "render.mp4"
    source.write_bytes(b"already-safe")
    measured = {
        "candidateSha256": persian_finalization.sha256_file(source),
        "outputIntegratedLufs": -16.0,
        "truePeakDbfs": -1.5,
    }
    result = persian_finalization.master_final_candidate(
        source,
        tmp_path / "mastered.mp4",
        measure=lambda _path: dict(measured),
        run_master=lambda *_args, **_kwargs: pytest.fail("safe candidate must not be re-encoded"),
    )
    assert result["reencoded"] is False
    assert Path(result["candidatePath"]) == source
    assert result["candidateSha256"] == persian_finalization.sha256_file(source)


def test_candidate_identity_is_minted_from_mastered_bytes_only(tmp_path: Path) -> None:
    source = tmp_path / "render.mp4"
    output = tmp_path / "mastered.mp4"
    source.write_bytes(b"unsafe-render")
    measurements = iter([
        {"candidateSha256": persian_finalization.sha256_file(source), "outputIntegratedLufs": -16.0, "truePeakDbfs": -0.2},
        {"candidateSha256": "placeholder", "outputIntegratedLufs": -16.2, "truePeakDbfs": -1.6},
    ])

    def fake_measure(path: Path) -> dict:
        value = dict(next(measurements))
        value["candidateSha256"] = persian_finalization.sha256_file(path)
        return value

    def fake_master(input_path: Path, output_path: Path, _policy: dict) -> None:
        assert input_path == source
        output_path.write_bytes(b"deterministically-mastered")

    result = persian_finalization.master_final_candidate(
        source, output, measure=fake_measure, run_master=fake_master
    )
    assert result["reencoded"] is True
    assert result["inputSha256"] == persian_finalization.sha256_file(source)
    assert result["candidateSha256"] == persian_finalization.sha256_file(output)
    assert result["candidateSha256"] != result["inputSha256"]
    assert result["truePeakDbfs"] <= persian_finalization.MASTER_TRUE_PEAK_DBFS
